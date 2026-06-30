"""RF toolkit dialog — mode switching + per-mode computation."""

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

    return MainWindow(Settings())


def test_rf_dialog_each_mode_computes(win):
    from qcell.gui.dialogs.rf_dialog import RFDialog

    dlg = RFDialog(win)

    rows = dict(dlg.compute_rows())                 # default: Link budget
    assert "Free-space path loss" in rows and "Link margin" in rows

    dlg._mode.setCurrentIndex(1)                     # Coax line
    rows = dict(dlg.compute_rows())
    assert any("Z0" in k for k in rows)

    dlg._mode.setCurrentIndex(2)                     # Antenna dimensions
    rows = dict(dlg.compute_rows())
    dipole = next(v for k, v in rows.items() if "dipole" in k)
    assert "m" in dipole and "ft" in dipole          # dual-unit output

    dlg._mode.setCurrentIndex(3)                     # Matching (L-network)
    rows = dict(dlg.compute_rows())
    assert "Loaded Q" in rows
    assert any("Solution 1" in k for k in rows)


def test_rf_dialog_is_wired_into_window(win):
    assert callable(win.show_rf_tool)
    assert "RF toolkit..." in win._palette_actions()


def test_smith_dialog_gamma_plot_and_paint(win, app):
    from qcell.gui._qtcompat import QPixmap
    from qcell.gui.dialogs.smith_dialog import SmithDialog

    dlg = SmithDialog(win)                                  # defaults R=75, X=25, Z0=50
    expect = (complex(75, 25) - 50) / (complex(75, 25) + 50)
    assert abs(dlg.gamma() - expect) < 1e-9

    dlg._plot()
    assert len(dlg._chart._points) == 2                     # load point + matched (centre)
    assert "VSWR" in dlg._readout.text() and "Return loss" in dlg._readout.text()

    pm = QPixmap(240, 240)                                  # exercise paintEvent (no crash)
    dlg._chart.render(pm)


def test_smith_wired_into_window(win):
    assert callable(win.show_smith_chart)
    assert "Smith chart..." in win._palette_actions()
