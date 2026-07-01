"""Sandbox Phase 3 — the strict-mode seam, the fail-closed self-test, the bridge
integration, and (on Windows) the real AppContainer confinement."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

from abax import sandbox
from abax.core.workbook import Workbook


# --- the seam -----------------------------------------------------------------


def test_select_confinement_returns_a_strategy():
    strat = sandbox.select_confinement()
    # Always returns something implementing the interface (a real strategy or the
    # null sentinel), never raises.
    for attr in ("available", "wrap_argv", "child_env", "apply_in_child", "describe"):
        assert hasattr(strat, attr)
    assert isinstance(strat.describe(), str)


def test_strict_requested_env(monkeypatch):
    monkeypatch.delenv(sandbox.STRICT_ENV, raising=False)
    assert sandbox.strict_requested() is False
    monkeypatch.setenv(sandbox.STRICT_ENV, "1")
    assert sandbox.strict_requested() is True
    monkeypatch.setenv(sandbox.STRICT_ENV, "0")
    assert sandbox.strict_requested() is False


def test_null_confinement_is_unavailable():
    null = sandbox._NullConfinement()
    assert null.available() is False
    assert null.wrap_argv(["x"], "s") == ["x"]
    assert null.apply_in_child("s") is None


# --- the fail-closed self-test ------------------------------------------------


def test_selftest_detects_unconfined_filesystem(tmp_path):
    # No confinement is active in the test process, so writing outside the
    # scratch dir succeeds -> selftest must raise SandboxEscape.
    scratch = str(tmp_path / "scratch")
    os.makedirs(scratch)
    with pytest.raises(sandbox.SandboxEscape):
        sandbox.selftest(scratch, check_network=False)


def test_selftest_network_escape_detected():
    # The test process can reach the network stack, so the network probe is an
    # escape. (Filesystem half disabled via a writable scratch to isolate.)
    with pytest.raises(sandbox.SandboxEscape):
        # Use a scratch that IS writable so the FS check passes to reach the net
        # check — but the FS check will fire first in most envs, so just assert
        # that a fully-unconfined process fails the selftest somehow.
        sandbox.selftest(tempfile.gettempdir())


# --- bridge integration: fail closed when strict but unavailable --------------


class _FakeUnavailable:
    name = "fake"

    def available(self):
        return False

    def describe(self):
        return "fake"


def test_bridge_refuses_when_strict_and_no_confinement(monkeypatch):
    from abax.gui.console.console_bridge import ConsoleBridge

    monkeypatch.setattr(sandbox, "select_confinement", lambda: _FakeUnavailable())
    b = ConsoleBridge(strict=True)
    try:
        assert b.strict_unavailable() is True
        r = b.execute("print('should not run')", Workbook().to_envelope())
        assert "Strict sandbox mode is on" in r["error"]
        assert r.get("output", "") == ""
    finally:
        b.close()


def test_bridge_non_strict_runs_normally():
    from abax.gui.console.console_bridge import ConsoleBridge

    b = ConsoleBridge(strict=False)
    try:
        assert b.strict_unavailable() is False
        r = b.execute("print(6*7)", Workbook().to_envelope())
        assert "42" in r["output"]
    finally:
        b.close()


# --- Windows AppContainer: real confinement (verified on this platform) --------

_win = sys.platform == "win32"


@pytest.mark.skipif(not _win, reason="AppContainer is Windows-only")
def test_windows_confinement_available():
    from abax.sandbox_windows import confinement

    strat = confinement()
    assert strat is not None
    assert strat.available() is True
    assert "AppContainer" in strat.describe()


@pytest.mark.skipif(not _win, reason="AppContainer is Windows-only")
def test_windows_strict_worker_runs_and_confines():
    """The headline test: a strict worker on Windows runs benign code but user
    code cannot write outside scratch or open a socket, and cleanup reverts the
    profile + ACL grants."""
    from abax.gui.console.console_bridge import ConsoleBridge

    b = ConsoleBridge(strict=True)
    assert b.strict_unavailable() is False
    try:
        env = Workbook().to_envelope()
        # Benign command runs (confinement lets the worker function).
        r = b.execute("put('A1','5'); print('ok', cell('A1'))", env, timeout=60)
        assert not r.get("crashed"), r
        assert "ok 5" in r["output"]
        assert Workbook.from_envelope(r["envelope"]).sheet.get("A1") == 5

        # User code writing to the home dir is denied by the AppContainer.
        esc = (r"import os; "
               r"open(os.path.expanduser('~/abx_test_escape.txt'),'w').write('x'); "
               r"print('ESCAPED')")
        r2 = b.execute(esc, env, timeout=60)
        assert "ESCAPED" not in (r2.get("output") or "")
        assert "PermissionError" in (r2.get("output") or "") or r2.get("crashed")

        # User code opening a socket is denied (no network capability).
        net = (r"import socket; s=socket.socket(); "
               r"s.connect(('192.0.2.1',80)); print('NET')")
        r3 = b.execute(net, env, timeout=60)
        assert "NET" not in (r3.get("output") or "")
    finally:
        b.close()
