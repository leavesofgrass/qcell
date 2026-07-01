"""Tests for the Linux OS-confinement strategies (:mod:`abax.sandbox_linux`).

Three tiers:

* **Cross-platform** — importing the module, the interface shape, and the pure
  argv-builder. These run on any OS (Windows CI included) because they only
  construct data or monkeypatch the bwrap probe.
* **Linux+bwrap end-to-end** — actually spawn a Python child under bwrap and assert
  it cannot write outside scratch or open an outbound socket. Guarded with skipif.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pytest

from abax import sandbox as sb
from abax import sandbox_linux as sl

# --------------------------------------------------------------------------- #
# Cross-platform: import + interface shape (runs anywhere)
# --------------------------------------------------------------------------- #


def test_module_imports_on_any_os():
    # The mere import must not touch Linux-only syscalls.
    assert hasattr(sl, "confinement")


def test_confinement_returns_none_or_valid_interface():
    strat = sl.confinement()
    if strat is None:
        return  # "nothing usable" is a legitimate result (e.g. Windows box)
    # Whatever it returns must satisfy the frozen Protocol surface.
    for attr in ("name", "available", "wrap_argv", "child_env", "apply_in_child", "describe"):
        assert hasattr(strat, attr), attr
    assert isinstance(strat, sb.Confinement)  # runtime_checkable Protocol
    assert isinstance(strat.name, str)
    assert isinstance(strat.describe(), str)
    assert isinstance(strat.available(), bool)


def test_landlock_abi_probe_never_raises():
    # On non-Linux it returns 0 without touching libc; on Linux it returns a real
    # ABI (>=0). Either way it must not raise.
    v = sl.landlock_abi_version()
    assert isinstance(v, int)
    if not sys.platform.startswith("linux"):
        assert v == 0


def test_landlock_strategy_is_not_standalone_available():
    # Documented invariant: Landlock alone can't deny the network, so it must never
    # advertise itself as usable.
    strat = sl._LandlockConfine(abi=1)
    assert strat.available() is False
    with pytest.raises(RuntimeError):
        strat.apply_in_child("/tmp/whatever")


# --------------------------------------------------------------------------- #
# Cross-platform: bwrap argv builder (runs anywhere; no bwrap needed)
# --------------------------------------------------------------------------- #


def test_build_bwrap_argv_shape():
    scratch = os.path.abspath("scratchdir")
    argv = ["/usr/bin/python3", "-m", "abax.console_worker", "--flag"]
    cmd = sl.build_bwrap_argv("/usr/bin/bwrap", argv, scratch)

    assert cmd[0] == "/usr/bin/bwrap"
    # Read-only root so the interpreter/site-packages remain importable.
    assert "--ro-bind" in cmd
    ro_idx = cmd.index("--ro-bind")
    assert cmd[ro_idx + 1 : ro_idx + 3] == ["/", "/"]
    # Network is unshared -> outbound sockets have nowhere to go.
    assert "--unshare-net" in cmd
    assert "--unshare-pid" in cmd
    assert "--die-with-parent" in cmd
    assert "--dev" in cmd and "--proc" in cmd


def test_build_bwrap_argv_binds_scratch_writable():
    scratch = os.path.abspath("mywork")
    cmd = sl.build_bwrap_argv("/usr/bin/bwrap", ["/usr/bin/python3"], scratch)
    # --bind (read-write) of the scratch dir at its own path.
    assert "--bind" in cmd
    b_idx = cmd.index("--bind")
    assert cmd[b_idx + 1] == scratch
    assert cmd[b_idx + 2] == scratch
    # And it must NOT be re-bound read-only anywhere.
    for i, tok in enumerate(cmd):
        if tok == "--ro-bind":
            assert cmd[i + 1] != scratch


def test_build_bwrap_argv_preserves_original_argv_tail():
    argv = ["/usr/bin/python3", "-X", "utf8", "-m", "abax.console_worker"]
    cmd = sl.build_bwrap_argv("/usr/bin/bwrap", argv, os.path.abspath("s"))
    # Everything after the "--" separator is the original argv, verbatim & in order.
    assert "--" in cmd
    sep = cmd.index("--")
    assert cmd[sep + 1 :] == argv


def test_bwrap_strategy_via_monkeypatched_probe(monkeypatch):
    # Force the bwrap path to look present, without bwrap installed, so we exercise
    # the wrapper strategy's own methods on any OS.
    monkeypatch.setattr(sl, "_bwrap_path", lambda: "/usr/bin/bwrap")
    strat = sl.confinement()
    assert strat is not None
    assert strat.name == "bwrap"
    assert strat.available() is True

    scratch = os.path.abspath("s")
    cmd = strat.wrap_argv(["/usr/bin/python3", "-c", "print(1)"], scratch)
    assert cmd[0] == "/usr/bin/bwrap"
    assert "--unshare-net" in cmd
    assert cmd[-3:] == ["/usr/bin/python3", "-c", "print(1)"]

    # child_env redirects TMPDIR into scratch and leaves other keys intact.
    env = strat.child_env({"PYTHONPATH": "/x", "PATH": "/bin"}, scratch)
    assert env["TMPDIR"] == scratch
    assert env["PYTHONPATH"] == "/x"
    # apply_in_child is a pure-wrapper no-op (must not raise).
    assert strat.apply_in_child(scratch) is None


def test_confinement_returns_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(sl, "_bwrap_path", lambda: None)
    monkeypatch.setattr(sl, "landlock_abi_version", lambda: 0)
    assert sl.confinement() is None


# --------------------------------------------------------------------------- #
# Linux + bwrap end-to-end (skips unless actually runnable)
# --------------------------------------------------------------------------- #

_HAVE_BWRAP = sys.platform.startswith("linux") and sl._bwrap_path() is not None


@pytest.mark.skipif(not _HAVE_BWRAP, reason="requires Linux with a working bwrap")
def test_e2e_cannot_write_outside_scratch():
    with tempfile.TemporaryDirectory() as scratch:
        outside = os.path.join(tempfile.gettempdir(), "abax_e2e_escape_probe")
        # Try to write to a path outside scratch from inside the jail.
        code = (
            "import sys\n"
            f"try:\n"
            f"    open({outside!r}, 'w').write('x')\n"
            f"    print('WROTE')\n"
            f"except OSError:\n"
            f"    print('DENIED')\n"
        )
        argv = [sys.executable, "-c", code]
        strat = sl.confinement()
        cmd = strat.wrap_argv(argv, scratch)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert "DENIED" in proc.stdout, proc.stdout + proc.stderr
        assert not os.path.exists(outside)


@pytest.mark.skipif(not _HAVE_BWRAP, reason="requires Linux with a working bwrap")
def test_e2e_can_write_inside_scratch():
    with tempfile.TemporaryDirectory() as scratch:
        target = os.path.join(scratch, "ok.txt")
        code = f"open({target!r}, 'w').write('hi'); print('WROTE')\n"
        strat = sl.confinement()
        cmd = strat.wrap_argv([sys.executable, "-c", code], scratch)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert "WROTE" in proc.stdout, proc.stdout + proc.stderr
        assert os.path.exists(target)


@pytest.mark.skipif(not _HAVE_BWRAP, reason="requires Linux with a working bwrap")
def test_e2e_cannot_open_outbound_socket():
    with tempfile.TemporaryDirectory() as scratch:
        code = (
            "import socket, errno\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "s.settimeout(2)\n"
            "try:\n"
            "    s.connect(('192.0.2.1', 80))\n"
            "    print('REACHED')\n"
            "except OSError as e:\n"
            "    print('DENIED' if e.errno in (errno.ENETUNREACH, errno.EPERM,\n"
            "          errno.EACCES, errno.EHOSTUNREACH, errno.ENETDOWN) else 'REACHED')\n"
        )
        strat = sl.confinement()
        cmd = strat.wrap_argv([sys.executable, "-c", code], scratch)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        # With --unshare-net there is no route out -> connect fails with ENETUNREACH.
        assert "DENIED" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.skipif(not _HAVE_BWRAP, reason="requires Linux with a working bwrap")
def test_e2e_selftest_passes_under_bwrap():
    # The real fail-closed selftest must pass inside the jail: writing outside is
    # denied and the network is unreachable.
    with tempfile.TemporaryDirectory() as scratch:
        code = (
            "from abax import sandbox\n"
            f"sandbox.selftest({scratch!r})\n"
            "print('SELFTEST_OK')\n"
        )
        env = dict(os.environ)
        # Ensure the child can import abax (inherit our sys.path via PYTHONPATH).
        env["PYTHONPATH"] = os.pathsep.join(
            [p for p in sys.path if p]
        )
        strat = sl.confinement()
        env = strat.child_env(env, scratch)
        cmd = strat.wrap_argv([sys.executable, "-c", code], scratch)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        assert "SELFTEST_OK" in proc.stdout, proc.stdout + proc.stderr
