"""Tests for the macOS sandbox-exec confinement strategy.

The profile-builder and interface tests are pure string building / attribute
checks and run on ANY OS (they execute during collection on Windows/Linux CI).
The real end-to-end escape tests actually invoke ``sandbox-exec`` and are
skipped unless running on macOS with the binary present.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

import abax.sandbox_macos as macos
from abax.sandbox import Confinement

DARWIN = sys.platform == "darwin"
HAVE_SANDBOX_EXEC = os.path.isfile(macos.SANDBOX_EXEC) and os.access(
    macos.SANDBOX_EXEC, os.X_OK
)


# --- interface / import (any OS) ---------------------------------------------


def test_module_imports_and_confinement_returns_interface():
    strat = macos.confinement()
    assert strat is not None
    # Structurally satisfies the frozen Confinement protocol on any OS.
    assert isinstance(strat, Confinement)
    assert strat.name == "macos-sandbox-exec"


def test_confinement_available_type_is_bool():
    # available() must not raise on a non-darwin host; it just returns False.
    assert isinstance(macos.confinement().available(), bool)


def test_available_false_off_darwin():
    if not DARWIN:
        assert macos.confinement().available() is False


def test_describe_mentions_mechanism_and_guarantees():
    text = macos.confinement().describe().lower()
    assert "sandbox-exec" in text
    assert "network" in text
    assert "scratch" in text


def test_apply_in_child_is_noop():
    assert macos.confinement().apply_in_child("/whatever/scratch") is None


# --- profile builder (any OS) ------------------------------------------------


def test_profile_has_deny_default_baseline():
    prof = macos.build_profile("/tmp/scratch")
    assert "(version 1)" in prof
    assert "(deny default)" in prof


def test_profile_confines_writes_to_scratch_subpath():
    scratch = os.path.abspath("/tmp/abax_scratch_xyz")
    prof = macos.build_profile(scratch)
    # A file-write* subpath rule naming exactly the scratch dir must be present.
    # The builder abspath+escapes the path, so derive the expected form the same
    # way (matters on Windows where abspath drive-prefixes a "/tmp/..." string).
    expected = macos._sbpl_string(os.path.abspath(scratch))
    assert f'(allow file-write* (subpath "{expected}"))' in prof


def test_profile_never_allows_network():
    prof = macos.build_profile("/tmp/scratch")
    # The whole point: no outbound network allow of any kind.
    assert "network-outbound" not in prof
    assert "(allow network" not in prof


def test_profile_allows_process_and_interpreter_bringup():
    prof = macos.build_profile("/tmp/scratch")
    for clause in (
        "(allow process-fork)",
        "(allow process-exec)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow signal (target self))",
        "(allow file-read*)",
    ):
        assert clause in prof, clause


def test_sbpl_string_escapes_quotes_and_backslashes():
    # The escaper is what protects the SBPL string literal from a path that
    # contains a quote or backslash (which could otherwise inject profile
    # syntax). Test it directly, independent of OS path normalization.
    assert macos._sbpl_string('a"b') == 'a\\"b'
    assert macos._sbpl_string("a\\b") == "a\\\\b"
    assert macos._sbpl_string('x\\"y') == 'x\\\\\\"y'


# --- wrap_argv / child_env (any OS) ------------------------------------------


def test_wrap_argv_prepends_sandbox_exec_and_profile():
    argv = ["/usr/bin/python3", "-m", "abax.console_worker"]
    wrapped = macos.confinement().wrap_argv(argv, "/tmp/scratch")
    assert wrapped[0] == macos.SANDBOX_EXEC
    assert wrapped[1] == "-p"
    # The inline profile sits between -p and the original argv.
    assert "(deny default)" in wrapped[2]
    assert wrapped[3:] == argv


def test_child_env_points_tmpdir_at_scratch():
    out = macos.confinement().child_env({"PATH": "/usr/bin"}, "/tmp/scratch")
    assert out["TMPDIR"] == "/tmp/scratch"
    assert out["PATH"] == "/usr/bin"  # existing env preserved
    # Original mapping not mutated in place.
    src = {"A": "1"}
    macos.confinement().child_env(src, "/tmp/scratch")
    assert "TMPDIR" not in src


# --- real end-to-end confinement (macOS only) --------------------------------


@pytest.mark.skipif(
    not (DARWIN and HAVE_SANDBOX_EXEC),
    reason="sandbox-exec end-to-end escape tests only run on macOS",
)
def test_e2e_write_outside_scratch_is_denied(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    outside = tmp_path / "outside.txt"
    prog = textwrap.dedent(
        f"""
        import sys
        try:
            open({str(outside)!r}, "w").write("escape")
            sys.exit(0)  # write succeeded -> escape (bad)
        except OSError:
            sys.exit(3)  # denied -> confined (good)
        """
    )
    argv = [sys.executable, "-c", prog]
    wrapped = macos.confinement().wrap_argv(argv, str(scratch))
    rc = subprocess.run(wrapped, capture_output=True).returncode
    assert rc == 3, "write outside scratch was NOT denied"
    assert not outside.exists()


@pytest.mark.skipif(
    not (DARWIN and HAVE_SANDBOX_EXEC),
    reason="sandbox-exec end-to-end escape tests only run on macOS",
)
def test_e2e_write_inside_scratch_is_allowed(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    target = scratch / "ok.txt"
    prog = textwrap.dedent(
        f"""
        open({str(target)!r}, "w").write("fine")
        """
    )
    argv = [sys.executable, "-c", prog]
    wrapped = macos.confinement().wrap_argv(argv, str(scratch))
    rc = subprocess.run(wrapped, capture_output=True).returncode
    assert rc == 0
    assert target.read_text() == "fine"


@pytest.mark.skipif(
    not (DARWIN and HAVE_SANDBOX_EXEC),
    reason="sandbox-exec end-to-end escape tests only run on macOS",
)
def test_e2e_outbound_socket_is_denied(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    prog = textwrap.dedent(
        """
        import socket, sys, errno
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("192.0.2.1", 80))  # RFC 5737 TEST-NET, never answers
            sys.exit(0)  # reached the stack -> escape (bad)
        except OSError as exc:
            sys.exit(3 if exc.errno in (errno.EPERM, errno.EACCES) else 0)
        """
    )
    argv = [sys.executable, "-c", prog]
    wrapped = macos.confinement().wrap_argv(argv, str(scratch))
    rc = subprocess.run(wrapped, capture_output=True).returncode
    assert rc == 3, "outbound socket was NOT denied by the sandbox"
