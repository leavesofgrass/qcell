"""Wave H — additional Excel/Gnumeric statistics functions.

Pure-stdlib statistics that round out parity: the ``…A`` variants that treat
text as zero (``MAXA``/``MINA``/``VARA``/``VARPA``/``STDEVA``/``STDEVPA``), the
*exclusive* percentile family (``PERCENTILE.EXC``/``QUARTILE.EXC``/
``PERCENTRANK.EXC``), population skew (``SKEWP``), ``PROB``, and — now that the
engine spills — the array-returning regressors and binners ``FREQUENCY``,
``MODE.MULT``, ``TREND``, ``GROWTH``, ``LINEST`` and ``LOGEST``.

The regression functions are single-variable (one predictor); multi-variable
LINEST is out of scope. Registered by :func:`register`.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from .errors import CellError, is_error
from .values import RangeValue


def _arg(args: list, i: int, default: Any = None) -> Any:
    return args[i] if i < len(args) else default


def _flat(v: Any) -> list:
    if isinstance(v, RangeValue):
        return v.flat()
    if isinstance(v, list):
        out: list = []
        for item in v:
            out.extend(_flat(item))
        return out
    return [v]


def _nums(v: Any) -> list:
    """Flatten and keep only real numbers (booleans excluded, Excel-style)."""
    out = []
    for x in _flat(v):
        if isinstance(x, bool):
            continue
        if isinstance(x, (int, float)):
            out.append(float(x))
    return out


def _first_error(v: Any) -> "CellError | None":
    for x in _flat(v):
        if is_error(x):
            return x
    return None


# --- the "A" variants (text -> 0, TRUE -> 1, FALSE -> 0) --------------------


def _nums_a(v: Any) -> "tuple[CellError | None, list]":
    out = []
    for x in _flat(v):
        if is_error(x):
            return x, out
        if x is None:
            continue  # a truly empty cell is ignored
        if isinstance(x, bool):
            out.append(1.0 if x else 0.0)
        elif isinstance(x, (int, float)):
            out.append(float(x))
        else:
            out.append(0.0)  # text counts as zero
    return None, out


def _a_reduce(reducer: Callable, sample: bool = False, need: int = 1):
    def impl(args: list) -> Any:
        err, xs = _nums_a(args)
        if err is not None:
            return err
        if len(xs) < need:
            return CellError(CellError.NUM if sample else CellError.DIV0)
        try:
            return reducer(xs)
        except (ValueError, ZeroDivisionError):
            return CellError(CellError.NUM)
    return impl


def _variance(xs: list, sample: bool) -> float:
    n = len(xs)
    m = sum(xs) / n
    ss = sum((x - m) ** 2 for x in xs)
    return ss / (n - 1) if sample else ss / n


# --- exclusive percentile family -------------------------------------------


def _percentile_exc(xs: list, k: float) -> "float | CellError":
    xs = sorted(xs)
    n = len(xs)
    if n == 0 or not (1.0 / (n + 1) <= k <= n / (n + 1)):
        return CellError(CellError.NUM)
    rank = k * (n + 1)          # 1-based
    lo = int(math.floor(rank))
    frac = rank - lo
    if lo >= n:
        return xs[-1]
    return xs[lo - 1] + frac * (xs[lo] - xs[lo - 1])


def _fn_percentile_exc(args: list) -> Any:
    err = _first_error(_arg(args, 0))
    if err:
        return err
    xs = _nums(_arg(args, 0))
    k = _arg(args, 1)
    if not isinstance(k, (int, float)) or isinstance(k, bool):
        return CellError(CellError.VALUE)
    return _percentile_exc(xs, float(k))


def _fn_quartile_exc(args: list) -> Any:
    xs = _nums(_arg(args, 0))
    q = _arg(args, 1)
    if not isinstance(q, (int, float)) or isinstance(q, bool):
        return CellError(CellError.VALUE)
    q = int(q)
    if q == 0:
        return min(xs) if xs else CellError(CellError.NUM)
    if q == 4:
        return max(xs) if xs else CellError(CellError.NUM)
    if q not in (1, 2, 3):
        return CellError(CellError.NUM)
    return _percentile_exc(xs, q / 4.0)


def _fn_percentrank_exc(args: list) -> Any:
    xs = sorted(_nums(_arg(args, 0)))
    x = _arg(args, 1)
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not xs:
        return CellError(CellError.VALUE)
    x = float(x)
    n = len(xs)
    if x < xs[0] or x > xs[-1]:
        return CellError(CellError.NA)
    below = sum(1 for v in xs if v < x)
    same = sum(1 for v in xs if v == x)
    if same:
        rank = below + 1
    else:
        # interpolate between the bracketing ranks
        hi = next(i for i, v in enumerate(xs) if v > x)
        frac = (x - xs[hi - 1]) / (xs[hi] - xs[hi - 1])
        rank = hi + frac
    return rank / (n + 1)


# --- skew (population) / PROB ----------------------------------------------


def _fn_skewp(args: list) -> Any:
    err = _first_error(args)
    if err:
        return err
    xs = _nums(args)
    n = len(xs)
    if n < 1:
        return CellError(CellError.DIV0)
    m = sum(xs) / n
    sp = math.sqrt(sum((x - m) ** 2 for x in xs) / n)
    if sp == 0:
        return CellError(CellError.DIV0)
    return sum(((x - m) / sp) ** 3 for x in xs) / n


def _fn_kurtp(args: list) -> Any:
    """KURTP — population excess kurtosis of the values."""
    err = _first_error(args)
    if err:
        return err
    xs = _nums(args)
    n = len(xs)
    if n < 1:
        return CellError(CellError.DIV0)
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    if var == 0:
        return CellError(CellError.DIV0)
    return sum((x - m) ** 4 for x in xs) / n / (var * var) - 3.0


def _fn_covariance_s(args: list) -> Any:
    """COVARIANCE.S — sample covariance of two equal-length ranges."""
    xs, ys = _nums(_arg(args, 0)), _nums(_arg(args, 1))
    n = len(xs)
    if n != len(ys):
        return CellError(CellError.VALUE)
    if n < 2:
        return CellError(CellError.DIV0)
    mx, my = sum(xs) / n, sum(ys) / n
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)


def _fn_range(args: list) -> Any:
    """RANGE — the spread ``max - min`` of the values (Gnumeric)."""
    err = _first_error(args)
    if err:
        return err
    xs = _nums(args)
    if not xs:
        return CellError(CellError.NUM)
    return max(xs) - min(xs)


def _fn_prob(args: list) -> Any:
    xs = _nums(_arg(args, 0))
    ps = _nums(_arg(args, 1))
    if len(xs) != len(ps):
        return CellError(CellError.NA)
    lower = _arg(args, 2)
    upper = _arg(args, 3, lower)
    if not isinstance(lower, (int, float)) or isinstance(lower, bool):
        return CellError(CellError.VALUE)
    if not isinstance(upper, (int, float)) or isinstance(upper, bool):
        upper = lower
    lo, hi = float(lower), float(upper)
    if lo > hi:
        lo, hi = hi, lo
    return sum(p for x, p in zip(xs, ps) if lo <= x <= hi)


# --- array-returning (spilling) functions ----------------------------------


def _fn_frequency(args: list) -> Any:
    """FREQUENCY(data, bins) — counts per bin; spills a column of len(bins)+1."""
    data = _nums(_arg(args, 0))
    bins = sorted(_nums(_arg(args, 1)))
    counts = [0] * (len(bins) + 1)
    for x in data:
        placed = False
        for i, b in enumerate(bins):
            if x <= b:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return [float(c) for c in counts]


def _fn_mode_mult(args: list) -> Any:
    """MODE.MULT(range) — every value tied for the highest frequency; spills."""
    xs = _nums(args)
    if not xs:
        return CellError(CellError.NA)
    freq: dict = {}
    order: list = []
    for x in xs:
        if x not in freq:
            order.append(x)
        freq[x] = freq.get(x, 0) + 1
    top = max(freq.values())
    if top < 2:
        return CellError(CellError.NA)
    return [x for x in order if freq[x] == top]


def _regression(ys: list, xs: list) -> "tuple[float, float] | None":
    """Ordinary least squares: return (slope, intercept) or None if degenerate."""
    n = len(xs)
    if n == 0 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return slope, my - slope * mx


def _xy(args: list, log_y: bool):
    ys = _nums(_arg(args, 0))
    xarg = _arg(args, 1)
    xs = _nums(xarg) if xarg is not None else [float(i + 1) for i in range(len(ys))]
    if len(xs) != len(ys) or not ys:
        return None
    if log_y:
        if any(y <= 0 for y in ys):
            return None
        ys = [math.log(y) for y in ys]
    return ys, xs


def _fn_trend(args: list) -> Any:
    xy = _xy(args, log_y=False)
    if xy is None:
        return CellError(CellError.VALUE)
    ys, xs = xy
    fit = _regression(ys, xs)
    if fit is None:
        return CellError(CellError.NUM)
    slope, intercept = fit
    newx = _arg(args, 2)
    new_xs = _nums(newx) if newx is not None else xs
    return [slope * x + intercept for x in new_xs]


def _fn_growth(args: list) -> Any:
    xy = _xy(args, log_y=True)
    if xy is None:
        return CellError(CellError.VALUE)
    ys, xs = xy
    fit = _regression(ys, xs)
    if fit is None:
        return CellError(CellError.NUM)
    slope, intercept = fit
    newx = _arg(args, 2)
    new_xs = _nums(newx) if newx is not None else xs
    return [math.exp(slope * x + intercept) for x in new_xs]


def _x_matrix(xarg: Any, n: int) -> "list | None":
    """The predictor matrix as ``n`` rows x ``k`` columns (one column per
    predictor), or None on a numeric/shape mismatch. Omitted -> the default
    single predictor 1..n."""
    if xarg is None:
        return [[float(i + 1)] for i in range(n)]
    from .spill import as_grid
    grid = as_grid(xarg)
    if len(grid) == n:
        rows = grid
    elif grid and len(grid[0]) == n:
        rows = [list(col) for col in zip(*grid)]   # k x n -> n x k
    else:
        return None
    out = []
    for row in rows:
        vals = []
        for v in row:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return None
            vals.append(float(v))
        out.append(vals)
    return out


def _ols(ys: list, X: list) -> "list | None":
    """Ordinary least squares with an intercept via the normal equations.
    Returns coefficients ``[b0, b1, ..., bk]`` (intercept first) or None."""
    n = len(ys)
    if n == 0 or not X or any(len(row) != len(X[0]) for row in X):
        return None
    k = len(X[0])
    design = [[1.0, *row] for row in X]           # leading intercept column
    m = k + 1
    a = [[sum(design[r][i] * design[r][j] for r in range(n)) for j in range(m)]
         for i in range(m)]
    b = [sum(design[r][i] * ys[r] for r in range(n)) for i in range(m)]
    from .science.regression import _solve
    try:
        return _solve(a, b)
    except Exception:  # noqa: BLE001 - singular system -> #NUM! upstream
        return None


def _fn_linest(args: list) -> Any:
    """LINEST(known_y, [known_x]) — least-squares coefficients as one row.

    Single predictor -> ``[[slope, intercept]]``; ``k`` predictors ->
    ``[[b_k, ..., b_1, intercept]]`` (Excel's right-to-left order)."""
    ys = _nums(_arg(args, 0))
    if not ys:
        return CellError(CellError.VALUE)
    x = _x_matrix(_arg(args, 1), len(ys))
    if x is None:
        return CellError(CellError.VALUE)
    coef = _ols(ys, x)
    if coef is None:
        return CellError(CellError.NUM)
    return [list(reversed(coef))]


def _fn_logest(args: list) -> Any:
    """LOGEST(known_y, [known_x]) — exponential fit ``y = b * m1^x1 * ...`` as one
    row ``[[m_k, ..., m_1, b]]`` (each ``m`` = exp of the log-linear coefficient)."""
    ys = _nums(_arg(args, 0))
    if not ys:
        return CellError(CellError.VALUE)
    if any(y <= 0 for y in ys):
        return CellError(CellError.NUM)
    x = _x_matrix(_arg(args, 1), len(ys))
    if x is None:
        return CellError(CellError.VALUE)
    coef = _ols([math.log(y) for y in ys], x)
    if coef is None:
        return CellError(CellError.NUM)
    return [[math.exp(c) for c in reversed(coef)]]


# --- registry --------------------------------------------------------------

_REGISTRY: dict[str, Callable[[list], Any]] = {
    "MAXA": _a_reduce(max),
    "MINA": _a_reduce(min),
    "VARA": _a_reduce(lambda xs: _variance(xs, True), sample=True, need=2),
    "VARPA": _a_reduce(lambda xs: _variance(xs, False), need=1),
    "STDEVA": _a_reduce(lambda xs: math.sqrt(_variance(xs, True)), sample=True, need=2),
    "STDEVPA": _a_reduce(lambda xs: math.sqrt(_variance(xs, False)), need=1),
    "PERCENTILE.EXC": _fn_percentile_exc,
    "QUARTILE.EXC": _fn_quartile_exc,
    "PERCENTRANK.EXC": _fn_percentrank_exc,
    "SKEWP": _fn_skewp,
    "KURTP": _fn_kurtp,
    "COVARIANCE.S": _fn_covariance_s,
    "RANGE": _fn_range,
    "PROB": _fn_prob,
    "FREQUENCY": _fn_frequency,
    "MODE.MULT": _fn_mode_mult,
    "TREND": _fn_trend,
    "GROWTH": _fn_growth,
    "LINEST": _fn_linest,
    "LOGEST": _fn_logest,
}


def register(functions: dict) -> None:
    """Merge the additional statistics functions into the engine's table."""
    functions.update(_REGISTRY)
