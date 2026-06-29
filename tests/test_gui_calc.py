"""Calculator <-> cell value bridge (both directions, multi-cell, entry commit)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("qcell.gui._qtcompat")

from qcell.gui._qtcompat import QApplication, QTableWidgetSelectionRange  # noqa: E402
from qcell.settings import Settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def win(app):
    from qcell.gui.main_window import MainWindow

    return MainWindow(Settings())


def test_cell_to_calc_loads_value(win):
    win._commit_cell(0, 0, "42")
    win._table.setCurrentCell(0, 0)
    win.cell_to_calc()                       # opens the calculator and loads 42
    panel = win._calc_panel()
    assert panel is not None
    assert panel.current_value() == 42.0


def test_calc_to_cells_fills_selection(win):
    win.show_calculator()
    win._calc_panel().load_value(7)
    win._table.clearSelection()
    win._table.setRangeSelected(QTableWidgetSelectionRange(1, 1, 2, 2), True)
    win.calc_to_cells()
    sheet = win._doc.workbook.sheet
    for r in (1, 2):
        for c in (1, 2):
            assert sheet.get_raw(r, c) == "7"
    assert win._doc.can_undo            # the bulk write is one undo step


def test_uncommitted_entry_is_read(win):
    # The old bug: a number typed but not Enter-committed sat in the entry buffer
    # and "Send to cell" wrote a stale X. current_value() must commit it first.
    win.show_calculator()
    panel = win._calc_panel()
    w = panel._widget
    if not hasattr(w, "keypad"):
        pytest.skip("default model is not the HP keypad")
    w.keypad.entry = "9"            # single digit: same in the 16C's hex mode
    assert panel.current_value() == 9.0
    assert w.keypad.entry == ""     # the entry was committed, not left dangling


def test_algebraic_model_is_wired(win):
    from qcell.gui.algebraic_faceplate import AlgebraicFaceplate

    win.show_calculator()
    panel = win._calc_panel()
    panel._kind = "alg"
    panel._rebuild()
    assert isinstance(panel._widget, AlgebraicFaceplate)
    panel.load_value(12.5)              # value bridge works for the algebraic calc
    assert panel.current_value() == 12.5


def test_send_without_calculator_is_safe(win):
    win.calc_to_cells()                      # no calculator open
    assert "Ctrl+K" in win.statusBar().currentMessage()
    assert win._doc.workbook.sheet.get_raw(0, 0) == ""   # nothing written
