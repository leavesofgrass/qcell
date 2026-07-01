"""Dynamic-array spill: a formula whose result is an array fills neighbouring
cells, blocks with #SPILL! on collision, and stores only the source formula."""

from __future__ import annotations

from abax.core.errors import CellError
from abax.core.sheet import Sheet
from abax.core.workbook import Workbook


def _vals(sheet, cells):
    return [sheet.get(ref) for ref in cells]


# --- basic vertical spill --------------------------------------------------


def test_sequence_spills_down():
    s = Sheet()
    s.set("A1", "=SEQUENCE(3)")
    assert _vals(s, ["A1", "A2", "A3"]) == [1, 2, 3]
    # The anchor is the only stored cell — the rest are spilled, not written.
    assert s.get_raw(1, 0) == ""
    assert s.get_raw(2, 0) == ""


def test_unique_spills_down():
    s = Sheet()
    for r, v in enumerate([3, 1, 3, 2, 1]):
        s.set_cell(r, 0, str(v))
    s.set("C1", "=UNIQUE(A1:A5)")
    assert _vals(s, ["C1", "C2", "C3"]) == [3, 1, 2]
    assert s.get("C4") is None


def test_sort_spills_down():
    s = Sheet()
    for r, v in enumerate([3, 1, 2]):
        s.set_cell(r, 0, str(v))
    s.set("B1", "=SORT(A1:A3)")
    assert _vals(s, ["B1", "B2", "B3"]) == [1, 2, 3]


# --- 2-D spill -------------------------------------------------------------


def test_sequence_2d_spills_block():
    s = Sheet()
    s.set("A1", "=SEQUENCE(2,3)")
    assert _vals(s, ["A1", "B1", "C1"]) == [1, 2, 3]
    assert _vals(s, ["A2", "B2", "C2"]) == [4, 5, 6]


def test_transpose_spills_sideways():
    s = Sheet()
    for r, v in enumerate([10, 20, 30]):
        s.set_cell(r, 0, str(v))  # A1:A3 (a column)
    s.set("C1", "=TRANSPOSE(A1:A3)")
    assert _vals(s, ["C1", "D1", "E1"]) == [10, 20, 30]


# --- collision / empty -----------------------------------------------------


def test_collision_is_spill_error():
    s = Sheet()
    s.set("A1", "=SEQUENCE(3)")
    s.set("A2", "blocker")            # sits inside the would-be spill range
    val = s.get("A1")
    assert isinstance(val, CellError) and val.code == CellError.SPILL
    # The blocker keeps its own value; nothing else spilled.
    assert s.get("A2") == "blocker"
    assert s.get("A3") is None


def test_spill_clears_when_blocker_removed():
    s = Sheet()
    s.set("A1", "=SEQUENCE(3)")
    s.set("A2", "blocker")
    assert s.get("A1").code == CellError.SPILL
    s.set("A2", "")                   # remove the blocker
    assert _vals(s, ["A1", "A2", "A3"]) == [1, 2, 3]


def test_filter_no_match_is_calc():
    s = Sheet()
    for r, v in enumerate([1, 2, 3]):
        s.set_cell(r, 0, str(v))
        s.set_cell(r, 1, "0")         # condition column B1:B3 all-false
    s.set("C1", "=FILTER(A1:A3, B1:B3)")
    val = s.get("C1")
    assert isinstance(val, CellError) and val.code == CellError.CALC


# --- composition & dependencies -------------------------------------------


def test_spilled_cells_feed_aggregates():
    s = Sheet()
    s.set("A1", "=SEQUENCE(3)")       # spills 1,2,3 into A1:A3
    s.set("C1", "=SUM(A1:A3)")
    assert s.get("C1") == 6


def test_dependent_updates_when_source_changes():
    s = Sheet()
    for r, v in enumerate([5, 1, 3]):
        s.set_cell(r, 0, str(v))
    s.set("C1", "=SORT(A1:A3)")
    s.set("E1", "=C3")                # reads the largest, spilled value
    assert s.get("E1") == 5
    s.set_cell(1, 0, "9")             # A2: 1 -> 9, so sorted top is now 9
    assert s.get("E1") == 9


# --- introspection helpers -------------------------------------------------


def test_spill_region_and_edges():
    s = Sheet()
    s.set("A1", "=SEQUENCE(2,2)")
    assert s.is_spill_anchor(0, 0)
    assert s.is_spilled_into(0, 1)
    assert not s.is_spilled_into(0, 0)  # the anchor is not "spilled into"
    assert s.spill_region(0, 0) == (0, 0, 1, 1)
    assert "top" in s.spill_edges(0, 0) and "left" in s.spill_edges(0, 0)
    assert "bottom" in s.spill_edges(1, 1) and "right" in s.spill_edges(1, 1)


def test_used_bounds_includes_spill():
    s = Sheet()
    s.set("A1", "=SEQUENCE(4)")       # A1:A4 even though only A1 is stored
    assert s.used_bounds() == (4, 1)


# --- serialization ---------------------------------------------------------


def test_envelope_stores_only_source_formula():
    wb = Workbook()
    wb.sheet.set("A1", "=SEQUENCE(3)")
    env = wb.to_envelope()
    cells = env["data"]["sheets"][0]["cells"]
    assert cells == {"A1": "=SEQUENCE(3)"}   # spilled A2/A3 are NOT persisted

    # Round-trips and re-spills on load.
    wb2 = Workbook.from_envelope(env)
    assert _vals(wb2.sheet, ["A1", "A2", "A3"]) == [1, 2, 3]


# --- reshaping family ------------------------------------------------------


def test_vstack_and_hstack():
    s = Sheet()
    s.set("A1", "=VSTACK(SEQUENCE(1,2), SEQUENCE(1,2,3))")
    assert _vals(s, ["A1", "B1"]) == [1, 2]
    assert _vals(s, ["A2", "B2"]) == [3, 4]


def test_take_drop_choose():
    s = Sheet()
    for r, v in enumerate([1, 2, 3, 4, 5]):
        s.set_cell(r, 0, str(v))
    s.set("C1", "=TAKE(A1:A5, 2)")
    assert _vals(s, ["C1", "C2"]) == [1, 2]
    s.set("D1", "=DROP(A1:A5, 3)")
    assert _vals(s, ["D1", "D2"]) == [4, 5]
    s.set("E1", "=CHOOSEROWS(A1:A5, 1, -1)")
    assert _vals(s, ["E1", "E2"]) == [1, 5]


def test_array_arithmetic_broadcasts_and_spills():
    s = Sheet()
    for r, val in enumerate([1, 2, 3]):
        s.set_cell(r, 0, str(val))          # A1:A3 = 1,2,3
    s.set("C1", "=A1:A3*2")                 # array * scalar
    assert _vals(s, ["C1", "C2", "C3"]) == [2, 4, 6]
    s.set("E1", "=10+A1:A3")                # scalar + array
    assert _vals(s, ["E1", "E2", "E3"]) == [11, 12, 13]


def test_array_comparison_feeds_filter():
    s = Sheet()
    for r, val in enumerate([5, 15, 25]):
        s.set_cell(r, 0, str(val))
    # The comparison now broadcasts to an array of booleans FILTER can use.
    s.set("C1", "=FILTER(A1:A3, A1:A3>9)")
    assert _vals(s, ["C1", "C2"]) == [15, 25]


def test_elementwise_product_composes_in_sum():
    s = Sheet()
    for r, val in enumerate([1, 2, 3]):
        s.set_cell(r, 0, str(val))
    s.set("C1", "=SUM(A1:A3*A1:A3)")        # 1 + 4 + 9
    assert s.get("C1") == 14


def test_row_times_column_outer_product():
    s = Sheet()
    for c, val in enumerate([1, 2, 3]):
        s.set_cell(0, c, str(val))          # A1:C1 (row)
    for r, val in enumerate([10, 20]):
        s.set_cell(r, 4, str(val))          # E1:E2 (column)
    s.set("A3", "=A1:C1 * E1:E2")           # 1x3 * 2x1 -> 2x3
    assert s.get_value(2, 0) == 10 and s.get_value(2, 2) == 30
    assert s.get_value(3, 0) == 20 and s.get_value(3, 2) == 60


def test_incompatible_shapes_value_error():
    s = Sheet()
    for r, val in enumerate([1, 2, 3]):
        s.set_cell(r, 0, str(val))          # A1:A3 (3 tall)
    for r, val in enumerate([1, 2]):
        s.set_cell(r, 1, str(val))          # B1:B2 (2 tall)
    s.set("D1", "=A1:A3 + B1:B2")
    val = s.get("D1")
    assert isinstance(val, CellError) and val.code == CellError.VALUE


def test_spill_reference_operator():
    s = Sheet()
    s.set("A1", "=SEQUENCE(3)")            # spills 1,2,3 into A1:A3
    s.set("C1", "=SUM(A1#)")               # aggregate over the whole spill
    assert s.get("C1") == 6
    s.set("E1", "=A1#")                    # re-spill the array elsewhere
    assert _vals(s, ["E1", "E2", "E3"]) == [1, 2, 3]


def test_spill_reference_2d_and_updates():
    s = Sheet()
    s.set("A1", "=SEQUENCE(2, 2)")         # 1,2 / 3,4
    s.set("D1", "=SUM(A1#)")
    assert s.get("D1") == 10
    s.set("A1", "=SEQUENCE(3)")            # source now a 3-tall column
    assert s.get("D1") == 6                # dependent spill-ref recomputed


def test_spill_reference_to_non_spill_is_ref_error():
    s = Sheet()
    s.set("A1", "5")                       # a plain value, not a spill anchor
    s.set("B1", "=A1#")
    val = s.get("B1")
    assert isinstance(val, CellError) and val.code == CellError.REF


def test_implicit_intersection_operator():
    s = Sheet()
    for r, val in enumerate([10, 20, 30, 40, 50]):
        s.set_cell(r, 0, str(val))          # A1:A5
    # '@A1:A5' picks the element on the caller's row.
    s.set("C3", "=@A1:A5")                  # row index 2 -> A3
    assert s.get_value(2, 2) == 30
    # '@' on a function result forces the first value (no spill).
    s.set("E1", "=@SEQUENCE(5)")
    assert s.get("E1") == 1
    assert s.get("E2") is None              # did not spill


def test_implicit_intersection_row_range():
    s = Sheet()
    for c, val in enumerate([7, 8, 9]):
        s.set_cell(10, c, str(val))         # A11:C11 (a row)
    s.set("B12", "=@A11:C11")               # column index 1 -> B11
    assert s.get_value(11, 1) == 8


# --- array constants -------------------------------------------------------


def test_array_constant_row_and_column():
    s = Sheet()
    s.set("A1", "={10,20,30}")             # a row
    assert [s.get_value(0, c) for c in range(3)] == [10, 20, 30]
    s.set("A3", "={1;2;3}")                # a column
    assert [s.get_value(r, 0) for r in (2, 3, 4)] == [1, 2, 3]


def test_array_constant_2d_and_compose():
    s = Sheet()
    s.set("A1", "={1,2;3,4}")
    assert s.get_value(0, 0) == 1 and s.get_value(1, 1) == 4
    s.set("E1", "=SUM({1,2,3,4})")
    assert s.get("E1") == 10
    s.set("E2", "=SORT({3,1,2})")
    assert [s.get_value(r, 4) for r in (1, 2, 3)] == [1, 2, 3]


def test_array_constant_broadcasts():
    s = Sheet()
    s.set("A1", "={1,2,3}*10")
    assert [s.get_value(0, c) for c in range(3)] == [10, 20, 30]


# --- array-aware IF --------------------------------------------------------


def test_if_broadcasts_over_array_condition():
    s = Sheet()
    for r, v in enumerate([1, 5, 3]):
        s.set_cell(r, 0, str(v))
    s.set("C1", '=IF(A1:A3>2, "big", "small")')
    assert [s.get_value(r, 2) for r in range(3)] == ["small", "big", "big"]


def test_if_array_picks_from_array_branch_and_sums():
    s = Sheet()
    for r, v in enumerate([1, 5, 3]):
        s.set_cell(r, 0, str(v))
    s.set("C1", "=SUM(IF(A1:A3>2, A1:A3, 0))")   # 5 + 3
    assert s.get("C1") == 8


# --- matrix functions ------------------------------------------------------


def test_munit_spills_identity():
    s = Sheet()
    s.set("A1", "=MUNIT(3)")
    assert [s.get_value(0, c) for c in range(3)] == [1, 0, 0]
    assert [s.get_value(2, c) for c in range(3)] == [0, 0, 1]


def test_mmult_spills_product():
    s = Sheet()
    for (r, c, v) in [(0, 0, 1), (0, 1, 2), (1, 0, 3), (1, 1, 4)]:
        s.set_cell(r, c, str(v))          # A1:B2
    for (r, c, v) in [(0, 4, 5), (0, 5, 6), (1, 4, 7), (1, 5, 8)]:
        s.set_cell(r, c, str(v))          # E1:F2
    s.set("A4", "=MMULT(A1:B2, E1:F2)")
    assert [s.get_value(3, 0), s.get_value(3, 1)] == [19, 22]
    assert [s.get_value(4, 0), s.get_value(4, 1)] == [43, 50]


def test_minverse_and_singular():
    s = Sheet()
    for (r, c, v) in [(0, 0, 4), (0, 1, 7), (1, 0, 2), (1, 1, 6)]:
        s.set_cell(r, c, str(v))
    s.set("A4", "=MINVERSE(A1:B2)")
    assert round(s.get_value(3, 0), 4) == 0.6 and round(s.get_value(4, 1), 4) == 0.4
    # a singular matrix has no inverse -> #NUM!
    s2 = Sheet()
    for (r, c, v) in [(0, 0, 1), (0, 1, 2), (1, 0, 2), (1, 1, 4)]:
        s2.set_cell(r, c, str(v))
    s2.set("A4", "=MINVERSE(A1:B2)")
    val = s2.get("A4")
    assert isinstance(val, CellError) and val.code == CellError.NUM
