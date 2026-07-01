"""Wave H — additional Excel/Gnumeric statistics functions."""

from __future__ import annotations

import math

from abax.core.errors import CellError
from abax.core.functions import FUNCTIONS
from abax.core.values import RangeValue


def v(name, *a):
    return FUNCTIONS[name](list(a))


def col(vals):
    return RangeValue([[x] for x in vals])


def test_all_registered():
    for name in ("MAXA", "MINA", "VARA", "VARPA", "STDEVA", "STDEVPA",
                 "PERCENTILE.EXC", "QUARTILE.EXC", "PERCENTRANK.EXC", "SKEWP",
                 "PROB", "FREQUENCY", "MODE.MULT", "TREND", "GROWTH", "LINEST",
                 "LOGEST"):
        assert name in FUNCTIONS, name


def test_a_variants_count_text_as_zero():
    # text -> 0, TRUE -> 1, so MAXA sees {1, 2, 0, 1}; MINA sees the 0.
    assert v("MAXA", col([1, 2, "hi", True])) == 2
    assert v("MINA", col([1, 2, "hi", True])) == 0


def test_varpa_stdeva():
    assert math.isclose(v("VARPA", col([1, 2, 3])), 2 / 3)
    assert math.isclose(v("STDEVA", col([1, 2, 3, 4])), math.sqrt(5 / 3))


def test_percentile_exc():
    assert math.isclose(v("PERCENTILE.EXC", col([1, 2, 3, 4]), 0.25), 1.25)
    # out of the valid (1/(n+1), n/(n+1)) range -> #NUM!
    assert isinstance(v("PERCENTILE.EXC", col([1, 2, 3, 4]), 0.1), CellError)


def test_quartile_exc():
    assert math.isclose(v("QUARTILE.EXC", col([1, 2, 3, 4]), 1), 1.25)
    assert math.isclose(v("QUARTILE.EXC", col([1, 2, 3, 4]), 3), 3.75)


def test_percentrank_exc():
    r = v("PERCENTRANK.EXC", col([1, 2, 3, 4]), 2)
    assert math.isclose(r, 2 / 5)   # rank 2 of n+1=5


def test_skewp_symmetric_is_zero():
    assert abs(v("SKEWP", col([1, 2, 3, 4, 5]))) < 1e-12


def test_prob():
    xs = col([1, 2, 3, 4])
    ps = col([0.1, 0.2, 0.3, 0.4])
    assert math.isclose(v("PROB", xs, ps, 2, 3), 0.5)
    assert math.isclose(v("PROB", xs, ps, 3), 0.3)   # single value


def test_frequency_bins():
    assert v("FREQUENCY", col([1, 2, 3, 4, 5]), col([2, 4])) == [2.0, 2.0, 1.0]


def test_mode_mult():
    assert v("MODE.MULT", col([1, 2, 2, 3, 3])) == [2.0, 3.0]
    assert isinstance(v("MODE.MULT", col([1, 2, 3])), CellError)  # no repeats -> #N/A


def test_trend_and_linest():
    ys, xs = col([2, 4, 6]), col([1, 2, 3])
    assert v("TREND", ys, xs, col([4, 5])) == [8.0, 10.0]
    assert v("LINEST", ys, xs) == [[2.0, 0.0]]


def test_linest_multiple_regression():
    # y = 1 + 2*x1 + 3*x2 exactly; LINEST returns [b2, b1, intercept].
    x = RangeValue([[1, 1], [2, 1], [1, 2], [3, 2], [2, 3]])
    ys = [1 + 2 * a + 3 * b for a, b in ([1, 1], [2, 1], [1, 2], [3, 2], [2, 3])]
    r = v("LINEST", RangeValue([[y] for y in ys]), x)
    assert [round(c, 6) for c in r[0]] == [3.0, 2.0, 1.0]


def test_growth_and_logest():
    ys, xs = col([2, 4, 8]), col([1, 2, 3])
    g = v("GROWTH", ys, xs, col([4]))
    assert math.isclose(g[0], 16.0, rel_tol=1e-9)
    base, factor = v("LOGEST", ys, xs)[0]
    assert math.isclose(base, 2.0) and math.isclose(factor, 1.0)


def test_kurtp_covariance_s_range():
    import math
    assert math.isclose(v("KURTP", col([1, 2, 3, 4, 5])), -1.3)
    assert v("COVARIANCE.S", col([1, 2, 3]), col([2, 4, 6])) == 2.0
    assert v("RANGE", col([3, 7, 1, 5])) == 6
