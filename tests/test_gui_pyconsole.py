"""Integration: the GUI Python console runs out-of-process and applies edits back."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("qcell.gui._qtcompat")

from qcell.gui._qtcompat import QApplication  # noqa: E402
from qcell.settings import Settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def win(app):
    from qcell.gui.main_window import MainWindow

    return MainWindow(Settings(code_consent=True))     # past the consent gate


def test_console_runs_in_subprocess_and_applies(win):
    win.show_pyconsole()
    console = win._pyconsole_dock.widget()
    console._in.setText("put('A1', '5')")
    console._run()                                     # spawns the worker, round-trips
    try:
        assert win._doc.workbook.sheet.get("A1") == 5  # change applied to the live wb
    finally:
        console._bridge.close()
