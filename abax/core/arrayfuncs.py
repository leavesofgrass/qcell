"""Modern spreadsheet array functions.

Pure-stdlib companion to :mod:`abax.core.functions`. Each callable follows the
same eager-function convention: it receives a single ``args`` list of
already-evaluated values, where a *range* argument arrives as a
:class:`abax.core.values.RangeValue` and scalars arrive as plain Python values.
Errors are :class:`abax.core.errors.CellError` values that propagate.

These functions return **arrays** — a 1-D Python ``list`` (a column) or a
list-of-lists (a 2-D block). When such a result is the top-level value of a
formula cell it *spills* across the neighbouring cells (see
:mod:`abax.core.spill` and the spill engine on :class:`~abax.core.sheet.Sheet`);
when nested inside an aggregate it composes, because ``_flatten`` recurses into
lists (e.g. ``=SUM(UNIQUE(A1:A9))`` works either way).

Register with the engine via :func:`register`, which merges :data:`EAGER`
(UPPERCASE name -> callable) into the engine's function table.
"""

from __future__ import annotations

import random
from typing import Any, Callable

from .errors import CellError
from .spill import as_grid, dims, flatten_grid
from .values import RangeValue

# --- local coercion helpers (kept independent of functions.py) -------------


def _arg(args: list, i: int, default: Any = None) -> Any:
    return args[i] if i < len(args) else default


def _as_number(v: Any) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if v is None or v == "":
        return 0.0
    return float(v)  # may raise ValueError


def _try_num(v: Any) -> float | None:
    try:
        return _as_number(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any, default: int | None = None) -> int | None:
    n = _try_num(v)
    return default if n is None else int(n)


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _equal(a: Any, b: Any) -> bool:
    an, bn = _try_num(a), _try_num(b)
    if an is not None and bn is not None and not isinstance(a, str) and not isinstance(b, str):
        return an == bn
    return _text(a).lower() == _text(b).lower()


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1")
    return bool(v)


def _is_blank(v: Any) -> bool:
    return v is None or v == ""


def _flat(v: Any) -> list[Any]:
    """Flatten a RangeValue / list (or scalar) to a flat list of values."""
    if isinstance(v, RangeValue):
        return v.flat()
    if isinstance(v, list):
        out: list[Any] = []
        for item in v:
            out.extend(_flat(item))
        return out
    return [v]


def _is_array(v: Any) -> bool:
    return isinstance(v, (list, RangeValue))


_NA = CellError(CellError.NA)


# --- lookup / de-dup / filter (1-D column results) -------------------------


def xlookup(args: list) -> Any:
    """XLOOKUP(lookup_value, lookup_array, return_array, [if_not_found], [match_mode]).

    Exact match only. Returns the ``return_array`` element at the first index
    where ``lookup_array`` matches ``lookup_value``; otherwise ``if_not_found``
    when supplied, else ``#N/A``.
    """
    lookup_value = _arg(args, 0)
    lookup_array = _flat(_arg(args, 1))
    return_array = _flat(_arg(args, 2))
    has_default = len(args) > 3
    if_not_found = _arg(args, 3)
    for i, candidate in enumerate(lookup_array):
        if _equal(candidate, lookup_value):
            return return_array[i] if i < len(return_array) else CellError(CellError.NA)
    return if_not_found if has_default else CellError(CellError.NA)


def unique(args: list) -> list:
    """UNIQUE(range) — distinct non-empty values in first-occurrence order."""
    seen: list[Any] = []
    out: list[Any] = []
    for v in _flat(_arg(args, 0)):
        if _is_blank(v):
            continue
        if any(_equal(v, s) for s in seen):
            continue
        seen.append(v)
        out.append(v)
    return out


def _sort_key(v: Any) -> tuple:
    """Sort key: numbers first (by value), then text (case-insensitive), blanks last."""
    if _is_blank(v):
        return (2, "")
    n = _try_num(v)
    if n is not None and not isinstance(v, str):
        return (0, n)
    return (1, _text(v).lower())


def sort(args: list) -> list:
    """SORT(range, [ascending=TRUE]) — numeric values sort numerically, others
    as text, blanks last."""
    values = list(_flat(_arg(args, 0)))
    ascending = _truthy(_arg(args, 1, True))
    ordered = sorted(values, key=_sort_key)
    if not ascending:
        ordered.reverse()
    return ordered


def sortby(args: list) -> Any:
    """SORTBY(array, by_array1, [order1], by_array2, [order2], ...) — sort the
    rows of ``array`` by one or more parallel key arrays."""
    grid = as_grid(_arg(args, 0))
    n = len(grid)
    # Collect (key_values, order) pairs: an array arg starts a new key; a scalar
    # arg sets the sort order (1 asc, -1 desc) of the key it follows.
    keys: list[list] = []
    for a in args[1:]:
        if _is_array(a):
            keys.append([_flat(a), 1])
        elif keys:
            num = _try_num(a)
            keys[-1][1] = -1 if (num is not None and num < 0) else 1
    if not keys:
        return sort([_arg(args, 0)])
    for vals, _order in keys:
        if len(vals) != n:
            return CellError(CellError.VALUE)
    # Stable multi-key sort: apply each key from last to first.
    order = list(range(n))
    for vals, o in reversed(keys):
        order.sort(key=lambda i, vv=vals: _sort_key(vv[i]), reverse=(o < 0))
    return [grid[i] for i in order]


def filter_(args: list) -> Any:
    """FILTER(range, condition_range) — values of ``range`` where the parallel
    ``condition_range`` value is truthy. Length mismatch -> ``#VALUE!``; no
    matches -> an empty array (the cell shows ``#CALC!``).

    Named ``filter_`` to avoid shadowing the builtin; registered as ``FILTER``.
    """
    values = _flat(_arg(args, 0))
    conditions = _flat(_arg(args, 1))
    if len(values) != len(conditions):
        return CellError(CellError.VALUE)
    return [v for v, cond in zip(values, conditions) if _truthy(cond)]


# --- generators ------------------------------------------------------------


def sequence(args: list) -> Any:
    """SEQUENCE(rows, [cols=1], [start=1], [step=1]) — ``rows*cols`` numbers
    ``start, start+step, ...``. A single column is a 1-D result; multiple columns
    spill as a 2-D block."""
    rows = _try_num(_arg(args, 0))
    cols = _try_num(_arg(args, 1, 1))
    start = _try_num(_arg(args, 2, 1))
    step = _try_num(_arg(args, 3, 1))
    if rows is None or cols is None or start is None or step is None:
        return CellError(CellError.VALUE)
    rows, cols = int(rows), int(cols)
    if rows < 0 or cols < 0:
        return CellError(CellError.VALUE)
    if cols == 1:
        return [start + i * step for i in range(rows)]
    return [[start + (i * cols + j) * step for j in range(cols)] for i in range(rows)]


def randarray(args: list) -> Any:
    """RANDARRAY([rows=1], [cols=1], [min=0], [max=1], [integer=FALSE])."""
    rows = _int(_arg(args, 0), 1) or 0
    cols = _int(_arg(args, 1), 1) or 0
    lo = _try_num(_arg(args, 2, 0))
    hi = _try_num(_arg(args, 3, 1))
    integer = _truthy(_arg(args, 4, False))
    if rows < 0 or cols < 0 or lo is None or hi is None or hi < lo:
        return CellError(CellError.VALUE)

    def one() -> float:
        return float(random.randint(int(lo), int(hi))) if integer else lo + random.random() * (hi - lo)

    if cols == 1:
        return [one() for _ in range(rows)]
    return [[one() for _ in range(cols)] for _ in range(rows)]


# --- reshaping (2-D results) -----------------------------------------------


def transpose(args: list) -> Any:
    """TRANSPOSE(array) — flip rows and columns."""
    grid = as_grid(_arg(args, 0))
    if not grid or not grid[0]:
        return CellError(CellError.VALUE)
    return [list(col) for col in zip(*grid)]


def vstack(args: list) -> Any:
    """VSTACK(a, b, ...) — stack arrays vertically; short rows pad with #N/A."""
    grids = [as_grid(a) for a in args]
    width = max((dims(g)[1] for g in grids), default=0)
    if width == 0:
        return CellError(CellError.VALUE)
    out: list[list[Any]] = []
    for g in grids:
        for row in g:
            out.append(list(row) + [_NA] * (width - len(row)))
    return out


def hstack(args: list) -> Any:
    """HSTACK(a, b, ...) — stack arrays horizontally; short columns pad with #N/A."""
    grids = [as_grid(a) for a in args]
    height = max((dims(g)[0] for g in grids), default=0)
    if height == 0:
        return CellError(CellError.VALUE)
    out: list[list[Any]] = []
    for r in range(height):
        row: list[Any] = []
        for g in grids:
            gc = dims(g)[1]
            row.extend(g[r] if r < len(g) else [_NA] * gc)
        out.append(row)
    return out


def _row_indices(n: int, k: int | None, take: bool) -> list[int]:
    """Index list for TAKE/DROP along one axis (``take``: keep vs drop)."""
    if k is None:
        return list(range(n)) if take else list(range(n))
    if take:
        if k >= 0:
            return list(range(min(k, n)))
        return list(range(max(0, n + k), n))
    # drop
    if k >= 0:
        return list(range(min(k, n), n))
    return list(range(0, max(0, n + k)))


def take(args: list) -> Any:
    """TAKE(array, rows, [cols]) — keep the first/last ``rows``/``cols`` (negative
    counts from the end)."""
    grid = as_grid(_arg(args, 0))
    nr, nc = dims(grid)
    ri = _row_indices(nr, _int(_arg(args, 1)) if len(args) > 1 else None, take=True)
    ci = _row_indices(nc, _int(_arg(args, 2)) if len(args) > 2 else None, take=True)
    if not ri or not ci:
        return []
    return [[grid[r][c] for c in ci] for r in ri]


def drop(args: list) -> Any:
    """DROP(array, rows, [cols]) — remove the first/last ``rows``/``cols``."""
    grid = as_grid(_arg(args, 0))
    nr, nc = dims(grid)
    ri = _row_indices(nr, _int(_arg(args, 1)) if len(args) > 1 else None, take=False)
    ci = _row_indices(nc, _int(_arg(args, 2)) if len(args) > 2 else None, take=False)
    if not ri or not ci:
        return []
    return [[grid[r][c] for c in ci] for r in ri]


def _pick(count: int, k: int) -> int | None:
    """1-based index into ``count`` items, negative from the end; None if OOB."""
    idx = k - 1 if k > 0 else count + k
    return idx if 0 <= idx < count else None


def chooserows(args: list) -> Any:
    """CHOOSEROWS(array, row_num1, [row_num2], ...) — pick rows (1-based, negative
    counts from the end)."""
    grid = as_grid(_arg(args, 0))
    nr = len(grid)
    out: list[list[Any]] = []
    for a in args[1:]:
        k = _int(a)
        if k is None:
            return CellError(CellError.VALUE)
        idx = _pick(nr, k)
        if idx is None:
            return CellError(CellError.VALUE)
        out.append(list(grid[idx]))
    return out or CellError(CellError.VALUE)


def choosecols(args: list) -> Any:
    """CHOOSECOLS(array, col_num1, [col_num2], ...) — pick columns."""
    grid = as_grid(_arg(args, 0))
    nc = dims(grid)[1]
    picks: list[int] = []
    for a in args[1:]:
        k = _int(a)
        if k is None:
            return CellError(CellError.VALUE)
        idx = _pick(nc, k)
        if idx is None:
            return CellError(CellError.VALUE)
        picks.append(idx)
    if not picks:
        return CellError(CellError.VALUE)
    return [[row[c] for c in picks] for row in grid]


def _keep(v: Any, ignore: int) -> bool:
    """Keep-value predicate for TOROW/TOCOL's ``ignore`` argument
    (0 keep all, 1 skip blanks, 2 skip errors, 3 skip both)."""
    if ignore in (1, 3) and _is_blank(v):
        return False
    if ignore in (2, 3) and isinstance(v, CellError):
        return False
    return True


def torow(args: list) -> Any:
    """TOROW(array, [ignore=0], [scan_by_column=FALSE]) — flatten to one row."""
    grid = as_grid(_arg(args, 0))
    ignore = _int(_arg(args, 1, 0), 0)
    by_col = _truthy(_arg(args, 2, False))
    vals = [v for v in flatten_grid(grid, by_col) if _keep(v, ignore)]
    return [vals] if vals else []


def tocol(args: list) -> Any:
    """TOCOL(array, [ignore=0], [scan_by_column=FALSE]) — flatten to one column."""
    grid = as_grid(_arg(args, 0))
    ignore = _int(_arg(args, 1, 0), 0)
    by_col = _truthy(_arg(args, 2, False))
    return [v for v in flatten_grid(grid, by_col) if _keep(v, ignore)]


def expand(args: list) -> Any:
    """EXPAND(array, rows, [cols], [pad=#N/A]) — grow to ``rows`` x ``cols``,
    filling new cells with ``pad``."""
    grid = as_grid(_arg(args, 0))
    nr, nc = dims(grid)
    tr = _int(_arg(args, 1), nr)
    tc = _int(_arg(args, 2), nc) if len(args) > 2 and _arg(args, 2) is not None else nc
    pad = _arg(args, 3, _NA)
    if pad is None:
        pad = _NA
    if tr is None or tc is None or tr < nr or tc < nc:
        return CellError(CellError.VALUE)
    return [[grid[r][c] if r < nr and c < nc else pad for c in range(tc)] for r in range(tr)]


def wraprows(args: list) -> Any:
    """WRAPROWS(vector, wrap_count, [pad=#N/A]) — wrap a 1-D vector into rows of
    ``wrap_count``."""
    vec = flatten_grid(as_grid(_arg(args, 0)))
    w = _int(_arg(args, 1))
    pad = _arg(args, 2, _NA)
    if pad is None:
        pad = _NA
    if w is None or w <= 0:
        return CellError(CellError.VALUE)
    out: list[list[Any]] = []
    for i in range(0, len(vec), w):
        chunk = vec[i:i + w]
        out.append(chunk + [pad] * (w - len(chunk)))
    return out


def wrapcols(args: list) -> Any:
    """WRAPCOLS(vector, wrap_count, [pad=#N/A]) — wrap a 1-D vector into columns
    of ``wrap_count``."""
    vec = flatten_grid(as_grid(_arg(args, 0)))
    h = _int(_arg(args, 1))
    pad = _arg(args, 2, _NA)
    if pad is None:
        pad = _NA
    if h is None or h <= 0:
        return CellError(CellError.VALUE)
    cols: list[list[Any]] = []
    for i in range(0, len(vec), h):
        chunk = vec[i:i + h]
        cols.append(chunk + [pad] * (h - len(chunk)))
    return [[cols[c][r] for c in range(len(cols))] for r in range(h)]


# --- matrix functions (spill) ----------------------------------------------


def _float_grid(v: Any) -> "list | None":
    try:
        return [[float(x) for x in row] for row in as_grid(v)]
    except (TypeError, ValueError):
        return None


def mmult(args: list) -> Any:
    """MMULT(a, b) — matrix product (spills the result block)."""
    from .science.matrix import MatrixError, matmul

    a, b = _float_grid(_arg(args, 0)), _float_grid(_arg(args, 1))
    if a is None or b is None:
        return CellError(CellError.VALUE)
    try:
        return matmul(a, b)
    except MatrixError:
        return CellError(CellError.VALUE)


def minverse(args: list) -> Any:
    """MINVERSE(a) — inverse of a square matrix (spills)."""
    from .science.matrix import MatrixError, inverse

    a = _float_grid(_arg(args, 0))
    if a is None:
        return CellError(CellError.VALUE)
    try:
        return inverse(a)
    except MatrixError:
        return CellError(CellError.NUM)   # singular or non-square


def munit(args: list) -> Any:
    """MUNIT(n) — the n x n identity matrix (spills)."""
    from .science.matrix import MatrixError, identity

    n = _int(_arg(args, 0))
    if n is None or n < 1:
        return CellError(CellError.VALUE)
    try:
        return identity(n)
    except MatrixError:
        return CellError(CellError.VALUE)


# --- registry --------------------------------------------------------------

EAGER: dict[str, Callable[[list], Any]] = {
    "MMULT": mmult,
    "MINVERSE": minverse,
    "MUNIT": munit,
    "XLOOKUP": xlookup,
    "UNIQUE": unique,
    "SORT": sort,
    "SORTBY": sortby,
    "FILTER": filter_,
    "SEQUENCE": sequence,
    "RANDARRAY": randarray,
    "TRANSPOSE": transpose,
    "VSTACK": vstack,
    "HSTACK": hstack,
    "TAKE": take,
    "DROP": drop,
    "CHOOSEROWS": chooserows,
    "CHOOSECOLS": choosecols,
    "TOROW": torow,
    "TOCOL": tocol,
    "EXPAND": expand,
    "WRAPROWS": wraprows,
    "WRAPCOLS": wrapcols,
}


def register(functions: dict) -> None:
    """Merge :data:`EAGER` into the engine's eager-function table."""
    functions.update(EAGER)
