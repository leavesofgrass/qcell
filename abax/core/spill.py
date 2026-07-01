"""Dynamic-array spill support — array-result normalization and 2-D helpers.

A formula that evaluates to an *array* (a Python ``list`` — 1-D for a column, or
a list-of-lists for a 2-D block) "spills": the top-left cell is the **anchor**
and the remaining values fill the neighbouring cells. The spill bookkeeping
(anchor -> region, collision -> ``#SPILL!``) lives on :class:`~abax.core.sheet.Sheet`;
this module holds the pure, side-effect-free pieces both the sheet and the array
functions rely on.

Conventions for array results returned by functions:

* a **1-D list** of scalars is a *column* (spills vertically);
* a **list-of-lists** is a 2-D block, one inner list per row;
* an **empty list** is "no result" -> the anchor shows ``#CALC!``.

``RangeValue`` (a bare range reference) is deliberately *not* treated as a
spilling array here — only function/array results spill — so ``=A1:A3`` keeps
its existing scalar-context behaviour.
"""

from __future__ import annotations

from typing import Any

from .errors import CellError
from .values import RangeValue


def is_array(value: Any) -> bool:
    """True if ``value`` is an array result that should spill (a ``list``)."""
    return isinstance(value, list)


def to_grid(value: Any) -> "list[list[Any]] | None":
    """Normalize an array result into a rectangular 2-D grid (list of rows).

    Returns ``None`` for a non-array (scalar / RangeValue / error) and for an
    empty array (the caller turns the latter into ``#CALC!``). A ragged 2-D
    result is padded to the widest row with ``#N/A`` (Excel's fill value).
    """
    if not isinstance(value, list) or not value:
        return None
    if all(isinstance(row, list) for row in value):
        width = max((len(row) for row in value), default=0)
        if width == 0:
            return None
        na = CellError(CellError.NA)
        return [list(row) + [na] * (width - len(row)) for row in value]
    # 1-D list of scalars -> a single column.
    return [[v] for v in value]


# --- shape helpers for the array functions ---------------------------------


def as_grid(value: Any) -> "list[list[Any]]":
    """Coerce any function argument into a 2-D grid for row/column operations.

    A :class:`RangeValue` keeps its shape; a 1-D ``list`` becomes a single
    column; a list-of-lists is taken as-is; a scalar becomes a 1x1 grid.
    """
    if isinstance(value, RangeValue):
        return [list(row) for row in value.grid]
    if isinstance(value, list):
        if value and all(isinstance(row, list) for row in value):
            return [list(row) for row in value]
        return [[v] for v in value]
    return [[value]]


def flatten_grid(grid: "list[list[Any]]", by_col: bool = False) -> list[Any]:
    """Flatten a grid to a 1-D list, row-major by default (column-major if
    ``by_col``)."""
    if by_col:
        return [grid[r][c] for c in range(len(grid[0])) for r in range(len(grid))]
    return [v for row in grid for v in row]


def dims(grid: "list[list[Any]]") -> "tuple[int, int]":
    """``(nrows, ncols)`` of a rectangular grid."""
    return len(grid), (len(grid[0]) if grid else 0)
