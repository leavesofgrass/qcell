"""Wave H — Gnumeric R.* distribution family, oracle-tested against R/scipy."""

from __future__ import annotations

import math

import pytest

from abax.core.errors import CellError
from abax.core.functions import FUNCTIONS


def v(name, *a):
    return FUNCTIONS[name](list(a))


def close(a, b, tol=1e-6):
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


def test_all_registered():
    for name in ("R.DNORM", "R.PNORM", "R.QNORM", "R.DGAMMA", "R.PT", "R.QF",
                 "R.DBINOM", "R.PHYPER", "R.DCAUCHY"):
        assert name in FUNCTIONS, name


# --- densities / CDFs vs known values --------------------------------------


def test_normal():
    assert close(v("R.DNORM", 0, 0, 1), 0.3989422804014327)
    assert close(v("R.PNORM", 1.96, 0, 1), 0.9750021048517796)
    assert close(v("R.QNORM", 0.975, 0, 1), 1.959963984540054)


def test_normal_defaults_standard():
    # Parameters default to the standard normal.
    assert close(v("R.PNORM", 0), 0.5)
    assert close(v("R.DNORM", 0), 0.3989422804014327)


def test_student_t():
    assert close(v("R.DT", 0, 5), 0.3796066898224944)
    assert close(v("R.PT", 0, 5), 0.5)
    assert close(v("R.PT", 2.015048, 5), 0.95, tol=1e-4)


def test_chisq_matches_normal_square():
    # chi-square(1) CDF at 1 equals 2*Phi(1) - 1.
    assert close(v("R.PCHISQ", 1, 1), 2 * v("R.PNORM", 1) - 1)


def test_exponential_and_gamma_agree():
    # Gamma(shape=1, scale=1) is Exponential(rate=1).
    assert close(v("R.PEXP", 1, 1), 0.6321205588285577)
    assert close(v("R.DGAMMA", 2.0, 1.0, 1.0), v("R.DEXP", 2.0, 1.0))


def test_f_median_is_one():
    assert close(v("R.PF", 1, 10, 10), 0.5)


def test_uniform():
    assert close(v("R.DUNIF", 0.5, 0, 2), 0.5)
    assert close(v("R.PUNIF", 0.5, 0, 2), 0.25)


def test_cauchy_quantile_roundtrip():
    assert close(v("R.PCAUCHY", v("R.QCAUCHY", 0.7, 0, 1), 0, 1), 0.7)


def test_discrete_binom_poisson():
    assert close(v("R.DPOIS", 2, 3), 0.22404180765538786)
    assert close(v("R.PBINOM", 2, 10, 0.5), 0.0546875)
    assert close(v("R.DBINOM", 5, 10, 0.5), 0.24609375)


def test_geometric_and_nbinom():
    assert close(v("R.DGEOM", 2, 0.5), 0.125)          # 0.5 * 0.5^2
    assert close(v("R.PGEOM", 1, 0.5), 0.75)           # k=0,1 -> 0.5 + 0.25
    assert close(v("R.DNBINOM", 3, 2, 0.5), 0.125)


def test_hypergeometric():
    assert close(v("R.DHYPER", 1, 5, 10, 50), 0.4313371972285503)


def test_discrete_quantiles():
    assert v("R.QBINOM", 0.5, 10, 0.5) == 5.0
    assert v("R.QPOIS", 0.5, 4) == 4.0
    assert v("R.QGEOM", 0.75, 0.5) == 1.0
    assert v("R.QHYPER", 0.5, 5, 10, 50) == 1.0


def test_gumbel():
    # CDF at the location is exp(-1).
    assert close(v("R.PGUMBEL", 0, 0, 1), math.exp(-1))
    assert close(v("R.PGUMBEL", v("R.QGUMBEL", 0.7, 0, 1), 0, 1), 0.7)


def test_laplace_and_logistic():
    assert close(v("R.PLAPLACE", 0, 0, 1), 0.5)
    assert close(v("R.PLOGIS", 0, 0, 1), 0.5)
    assert close(v("R.PLOGIS", v("R.QLOGIS", 0.8, 0, 1), 0, 1), 0.8)
    assert close(v("R.DLAPLACE", 0, 0, 1), 0.5)   # 1/(2b) at the peak


# --- quantile inverses -----------------------------------------------------


@pytest.mark.parametrize("dname,qname,params,p", [
    ("R.PGAMMA", "R.QGAMMA", (2.0, 1.5), 0.3),
    ("R.PBETA", "R.QBETA", (2.0, 3.0), 0.6),
    ("R.PCHISQ", "R.QCHISQ", (4.0,), 0.8),
    ("R.PT", "R.QT", (7.0,), 0.9),
    ("R.PF", "R.QF", (5.0, 8.0), 0.65),
    ("R.PWEIBULL", "R.QWEIBULL", (1.5, 2.0), 0.4),
])
def test_quantile_roundtrip(dname, qname, params, p):
    x = v(qname, p, *params)
    assert close(v(dname, x, *params), p, tol=1e-5)


# --- error handling --------------------------------------------------------


def test_bad_probability_is_num_error():
    r = v("R.QNORM", 1.5)   # p outside (0,1)
    assert isinstance(r, CellError) and r.code == CellError.NUM


def test_non_numeric_is_value_error():
    r = v("R.DNORM", "abc", 0, 1)
    assert isinstance(r, CellError) and r.code == CellError.VALUE


def test_skew_normal():
    # Owen's T gives SN(0,1,1) CDF at 0 = 0.25 exactly.
    assert close(v("R.PSNORM", 0, 0, 1, 1), 0.25, tol=1e-4)
    # shape 0 reduces to the standard normal.
    assert close(v("R.PSNORM", 0, 0, 1, 0), 0.5)
    assert close(v("R.DSNORM", 0, 0, 1, 0), 0.3989422804014327)
    # quantile inverts the CDF.
    q = v("R.QSNORM", 0.25, 0, 1, 1)
    assert close(v("R.PSNORM", q, 0, 1, 1), 0.25, tol=1e-4)


def test_rayleigh_and_pareto():
    import math
    assert close(v("R.PRAYLEIGH", 1, 1), 1 - math.exp(-0.5))
    assert close(v("R.PRAYLEIGH", v("R.QRAYLEIGH", 0.6, 2), 2), 0.6)
    assert close(v("R.PPARETO", 2, 1, 1), 0.5)          # 1-(1/2)^1
    assert close(v("R.PPARETO", v("R.QPARETO", 0.7, 3, 2), 3, 2), 0.7)
