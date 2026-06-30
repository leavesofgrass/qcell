"""The calculator view (open state + Deg/Rad) persists across sessions."""

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


def _win(settings):
    from qcell.gui.main_window import MainWindow

    return MainWindow(settings)


def test_calc_open_persists_and_restores(app):
    win = _win(Settings())
    assert win._settings.calc_open is False
    win.show_calculator()
    assert win._settings.calc_open is True
    win.toggle_calculator()                        # hide
    assert win._settings.calc_open is False

    reopened = _win(Settings(calc_open=True))
    assert reopened._calc_panel() is not None       # restored open on launch


def test_calc_degrees_persists(app):
    win = _win(Settings())
    win.show_calculator()
    panel = win._calc_panel()
    panel._kind = "alg"
    panel._rebuild()
    face = panel._widget
    start = face._calc.degrees
    face._do("@deg")
    assert face._calc.degrees != start
    assert win._settings.calc_degrees == face._calc.degrees

    win._settings.calc_degrees = True              # a rebuilt faceplate restores it
    panel._rebuild()
    assert panel._widget._calc.degrees is True
