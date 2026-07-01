"""Reference/context functions (ROW, COLUMN, ROWS, COLUMNS, OFFSET, INDIRECT,
ADDRESS) — they see the calling cell and the raw reference, via EvalContext."""

from __future__ import annotations

import pytest

from abax.core.workbook import Workbook


@pytest.fixture()
def grid():
    wb = Workbook()
    s = wb.sheets[0]
    for r in range(5):
        for c in range(3):
            s.set_cell(r, c, str((r + 1) * 10 + c))  # A1=10, B1=11, A2=20, ...
    return s


def _put_get(sheet, formula, at="E1"):
    sheet.set(at, formula)
    return sheet.get(at)


def test_row_column_no_arg(grid):
    assert _put_get(grid, "=ROW()", "E1") == 1.0       # E1 is row 0
    assert _put_get(grid, "=COLUMN()", "E2") == 5.0     # column E == 5


def test_row_column_of_reference(grid):
    assert _put_get(grid, "=ROW(C4)") == 4.0
    assert _put_get(grid, "=COLUMN(C4)") == 3.0


def test_rows_columns(grid):
    assert _put_get(grid, "=ROWS(A1:A10)") == 10.0
    assert _put_get(grid, "=COLUMNS(A1:C1)") == 3.0


def test_offset_single_cell(grid):
    assert _put_get(grid, "=OFFSET(A1,1,1)") == 21    # B2 == 21


def test_offset_range_in_aggregate(grid):
    assert _put_get(grid, "=SUM(OFFSET(A1,0,0,3,1))") == 60.0   # A1:A3 = 10+20+30
    assert _put_get(grid, "=SUM(OFFSET(A1,0,0,1,3))") == 33.0   # A1:C1 = 10+11+12


def test_offset_negative_is_ref_error(grid):
    assert "REF" in str(_put_get(grid, "=OFFSET(A1,-1,0)")).upper()


def test_indirect(grid):
    assert _put_get(grid, '=INDIRECT("A2")') == 20
    assert _put_get(grid, '=SUM(INDIRECT("A1:A3"))') == 60.0
    assert "REF" in str(_put_get(grid, '=INDIRECT("not a ref")')).upper()


def test_address(grid):
    assert _put_get(grid, "=ADDRESS(2,3)") == "$C$2"
    assert _put_get(grid, "=ADDRESS(2,3,4)") == "C2"
    assert _put_get(grid, "=ADDRESS(2,3,2)") == "C$2"
    assert _put_get(grid, '=ADDRESS(1,1,1,TRUE,"Sheet2")') == "Sheet2!$A$1"


def test_is_function_recognizes_context_names():
    from abax.core.completion import is_function, signature

    for name in ("ROW", "OFFSET", "INDIRECT", "ADDRESS",
                 "ISREF", "ISFORMULA", "FORMULATEXT", "SHEET", "SHEETS", "CELL"):
        assert is_function(name)
        assert signature(name).startswith(name + "(")


# --- the info half (ISREF / ISFORMULA / FORMULATEXT / SHEET / SHEETS / CELL) --


def test_isref(grid):
    assert _put_get(grid, "=ISREF(A1)") is True
    assert _put_get(grid, "=ISREF(A1:C3)") is True
    assert _put_get(grid, "=ISREF(42)") is False
    assert _put_get(grid, '=ISREF("A1")') is False   # a string is not a reference


def test_isformula_and_formulatext(grid):
    grid.set("D1", "=SUM(A1:A3)")
    grid.set("D2", "plain text")
    assert _put_get(grid, "=ISFORMULA(D1)") is True
    assert _put_get(grid, "=ISFORMULA(D2)") is False
    assert _put_get(grid, "=ISFORMULA(D9)") is False          # empty cell
    assert _put_get(grid, "=FORMULATEXT(D1)") == "=SUM(A1:A3)"
    out = _put_get(grid, "=FORMULATEXT(D2)")                   # not a formula
    assert "N/A" in str(out).upper()


def test_sheet_and_sheets(grid):
    wb = grid.workbook
    wb.add_sheet("Data")
    assert _put_get(grid, "=SHEET()") == 1.0
    assert _put_get(grid, '=SHEET("Data")') == 2.0
    assert "N/A" in str(_put_get(grid, '=SHEET("Nope")')).upper()
    assert _put_get(grid, "=SHEETS()") == 2.0
    assert _put_get(grid, "=SHEETS(A1)") == 1.0


def test_cell_info_types(grid):
    assert _put_get(grid, '=CELL("address",C4)') == "$C$4"
    assert _put_get(grid, '=CELL("row",C4)') == 4.0
    assert _put_get(grid, '=CELL("col",C4)') == 3.0
    assert _put_get(grid, '=CELL("contents",A2)') == 20
    assert _put_get(grid, '=CELL("contents",D9)') == 0.0       # empty -> 0
    assert _put_get(grid, '=CELL("type",A1)') == "v"
    assert _put_get(grid, '=CELL("type",D9)') == "b"
    grid.set("D2", "label")
    assert _put_get(grid, '=CELL("type",D2)') == "l"
    # No reference -> the calling cell itself.
    assert _put_get(grid, '=CELL("address")', at="F5") == "$F$5"
    assert "VALUE" in str(_put_get(grid, '=CELL("nope",A1)')).upper()
