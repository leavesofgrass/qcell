"""Wave H — Gnumeric-compatibility special functions (the R.* statistical family).

Gnumeric exposes an R-style probability-distribution family: for each
distribution, a density (``R.D…``), a cumulative distribution (``R.P…``) and a
quantile / inverse (``R.Q…``). This pure-stdlib pack implements the common
continuous and discrete distributions on top of the numerical backbone already
in :mod:`abax.core.stats_dist` (the regularized incomplete gamma/beta, the
normal CDF/quantile, and the discrete PMFs) — no new heavy machinery, and every
function is oracle-tested against known R/Gnumeric values.

Registered by :func:`register`, called from the ``functions`` package assembler
alongside the other pure-function packs (math, stats, text, finance, engineering).
"""

from __future__ import annotations

import math
from typing import Any, Callable

from .errors import CellError
from .stats_dist import (
    _betai,
    _binom_pmf,
    _gammp,
    _hypgeom_pmf,
    _norm_ppf_std,
    _phi,
    _poisson_pmf,
    _try_num,
)

_SQRT2PI = math.sqrt(2.0 * math.pi)


def _num(v: Any) -> "float | None":
    return _try_num(v)


def _arg(args: list, i: int, default: Any = None) -> Any:
    return args[i] if i < len(args) else default


# --- continuous densities / CDFs -------------------------------------------


def _norm_pdf(x: float, mu: float, sd: float) -> float:
    z = (x - mu) / sd
    return math.exp(-0.5 * z * z) / (sd * _SQRT2PI)


def _norm_cdf(x: float, mu: float, sd: float) -> float:
    return _phi((x - mu) / sd)


def _snorm_pdf(x: float, loc: float, scale: float, shape: float) -> float:
    """Skew-normal density SN(location, scale, shape)."""
    z = (x - loc) / scale
    return 2.0 / scale * (math.exp(-0.5 * z * z) / _SQRT2PI) * _phi(shape * z)


def _snorm_cdf(x: float, loc: float, scale: float, shape: float) -> float:
    """Skew-normal CDF by Simpson integration of the density (the tail beyond
    ~8 scale units contributes nothing)."""
    lo = loc - 8.0 * scale
    hi = min(x, loc + 8.0 * scale)
    if hi <= lo:
        return 0.0
    n = 400  # even
    h = (hi - lo) / n
    total = _snorm_pdf(lo, loc, scale, shape) + _snorm_pdf(hi, loc, scale, shape)
    for i in range(1, n):
        total += (4 if i % 2 else 2) * _snorm_pdf(lo + i * h, loc, scale, shape)
    val = total * h / 3.0
    if x >= loc + 8.0 * scale:
        val = 1.0
    return min(1.0, max(0.0, val))


def _gamma_pdf(x: float, shape: float, scale: float) -> float:
    if x < 0:
        return 0.0
    if x == 0:
        return 0.0 if shape > 1 else (1.0 / scale if shape == 1 else math.inf)
    return math.exp((shape - 1) * math.log(x) - x / scale
                    - shape * math.log(scale) - math.lgamma(shape))


def _gamma_cdf(x: float, shape: float, scale: float) -> float:
    return 0.0 if x <= 0 else _gammp(shape, x / scale)


def _beta_pdf(x: float, a: float, b: float) -> float:
    if x <= 0 or x >= 1:
        return 0.0
    logb = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return math.exp((a - 1) * math.log(x) + (b - 1) * math.log1p(-x) - logb)


def _t_pdf(x: float, df: float) -> float:
    c = math.lgamma((df + 1) / 2) - math.lgamma(df / 2) - 0.5 * math.log(df * math.pi)
    return math.exp(c - (df + 1) / 2 * math.log1p(x * x / df))


def _t_cdf(x: float, df: float) -> float:
    if x == 0:
        return 0.5
    xt = df / (df + x * x)
    half = 0.5 * _betai(df / 2, 0.5, xt)
    return 1.0 - half if x > 0 else half


def _f_pdf(x: float, d1: float, d2: float) -> float:
    if x <= 0:
        return 0.0
    logn = (d1 / 2) * math.log(d1) + (d2 / 2) * math.log(d2) + (d1 / 2 - 1) * math.log(x)
    logd = ((d1 + d2) / 2) * math.log(d1 * x + d2) + math.lgamma(d1 / 2) \
        + math.lgamma(d2 / 2) - math.lgamma((d1 + d2) / 2)
    return math.exp(logn - logd)


def _f_cdf(x: float, d1: float, d2: float) -> float:
    return 0.0 if x <= 0 else _betai(d1 / 2, d2 / 2, d1 * x / (d1 * x + d2))


def _chisq_pdf(x: float, df: float) -> float:
    return _gamma_pdf(x, df / 2, 2.0)


def _chisq_cdf(x: float, df: float) -> float:
    return _gamma_cdf(x, df / 2, 2.0)


def _weibull_cdf(x: float, shape: float, scale: float) -> float:
    return 0.0 if x < 0 else 1.0 - math.exp(-((x / scale) ** shape))


def _weibull_pdf(x: float, shape: float, scale: float) -> float:
    if x < 0:
        return 0.0
    return (shape / scale) * (x / scale) ** (shape - 1) * math.exp(-((x / scale) ** shape))


def _gumbel_pdf(x: float, loc: float, scale: float) -> float:
    z = (x - loc) / scale
    return math.exp(-(z + math.exp(-z))) / scale


def _gumbel_cdf(x: float, loc: float, scale: float) -> float:
    return math.exp(-math.exp(-(x - loc) / scale))


def _laplace_pdf(x: float, loc: float, scale: float) -> float:
    return math.exp(-abs(x - loc) / scale) / (2.0 * scale)


def _laplace_cdf(x: float, loc: float, scale: float) -> float:
    if x < loc:
        return 0.5 * math.exp((x - loc) / scale)
    return 1.0 - 0.5 * math.exp(-(x - loc) / scale)


def _logis_pdf(x: float, loc: float, scale: float) -> float:
    z = (x - loc) / scale
    e = math.exp(-abs(z))
    return e / (scale * (1.0 + e) ** 2)


def _logis_cdf(x: float, loc: float, scale: float) -> float:
    return 1.0 / (1.0 + math.exp(-(x - loc) / scale))


def _rayleigh_pdf(x: float, scale: float) -> float:
    if x < 0:
        return 0.0
    return (x / scale**2) * math.exp(-x * x / (2 * scale * scale))


def _rayleigh_cdf(x: float, scale: float) -> float:
    return 0.0 if x < 0 else 1.0 - math.exp(-x * x / (2 * scale * scale))


def _pareto_pdf(x: float, scale: float, shape: float) -> float:
    if x < scale:
        return 0.0
    return shape * scale**shape / x ** (shape + 1)


def _pareto_cdf(x: float, scale: float, shape: float) -> float:
    return 0.0 if x < scale else 1.0 - (scale / x) ** shape


def _bisect(cdf, target: float, lo: float, hi: float) -> float:
    """Invert a monotone CDF on [lo, hi] by bisection (expanding hi if needed)."""
    for _ in range(200):
        if cdf(hi) >= target:
            break
        lo, hi = hi, hi * 2 + 1
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if cdf(mid) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12 * max(1.0, abs(hi)):
            break
    return 0.5 * (lo + hi)


# --- wrapper factories (validate args, dispatch to the math above) ---------


def _cont3(fn: Callable, p1def=None, p2def=None, *, domain_lo=None):
    """Wrap a ``fn(x, p1, p2)`` continuous distribution taking one value + two
    parameters (either parameter may carry a default)."""
    def impl(args: list) -> Any:
        x = _num(_arg(args, 0))
        p1 = _num(_arg(args, 1, p1def))
        p2 = _num(_arg(args, 2, p2def))
        if x is None or p1 is None or p2 is None:
            return CellError(CellError.VALUE)
        try:
            return fn(x, p1, p2)
        except (ValueError, OverflowError, ZeroDivisionError):
            return CellError(CellError.NUM)
    return impl


def _cont2(fn: Callable, pdef=None):
    """Wrap a ``fn(x, p)`` continuous distribution: one value + one parameter."""
    def impl(args: list) -> Any:
        x = _num(_arg(args, 0))
        p = _num(_arg(args, 1, pdef))
        if x is None or p is None:
            return CellError(CellError.VALUE)
        try:
            return fn(x, p)
        except (ValueError, OverflowError, ZeroDivisionError):
            return CellError(CellError.NUM)
    return impl


# Quantile wrappers built on _bisect, with a distribution-specific bracket.


def _q_normal(args: list) -> Any:
    p = _num(_arg(args, 0)); mu = _num(_arg(args, 1, 0.0)); sd = _num(_arg(args, 2, 1.0))
    if p is None or mu is None or sd is None or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return mu + sd * _norm_ppf_std(p)


def _q_lognormal(args: list) -> Any:
    p = _num(_arg(args, 0)); ml = _num(_arg(args, 1, 0.0)); sl = _num(_arg(args, 2, 1.0))
    if p is None or ml is None or sl is None or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return math.exp(ml + sl * _norm_ppf_std(p))


def _q_exp(args: list) -> Any:
    p = _num(_arg(args, 0)); rate = _num(_arg(args, 1, 1.0))
    if p is None or rate is None or not (0.0 <= p < 1.0) or rate <= 0:
        return CellError(CellError.NUM)
    return -math.log1p(-p) / rate


def _q_weibull(args: list) -> Any:
    p = _num(_arg(args, 0)); k = _num(_arg(args, 1)); lam = _num(_arg(args, 2, 1.0))
    if p is None or k is None or lam is None or not (0.0 <= p < 1.0) or k <= 0 or lam <= 0:
        return CellError(CellError.NUM)
    return lam * (-math.log1p(-p)) ** (1.0 / k)


def _q_uniform(args: list) -> Any:
    p = _num(_arg(args, 0)); a = _num(_arg(args, 1, 0.0)); b = _num(_arg(args, 2, 1.0))
    if p is None or a is None or b is None or not (0.0 <= p <= 1.0):
        return CellError(CellError.NUM)
    return a + p * (b - a)


def _q_cauchy(args: list) -> Any:
    p = _num(_arg(args, 0)); loc = _num(_arg(args, 1, 0.0)); sc = _num(_arg(args, 2, 1.0))
    if p is None or loc is None or sc is None or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return loc + sc * math.tan(math.pi * (p - 0.5))


def _q_gamma(args: list) -> Any:
    p = _num(_arg(args, 0)); shape = _num(_arg(args, 1)); scale = _num(_arg(args, 2, 1.0))
    if p is None or shape is None or scale is None or not (0.0 < p < 1.0) or shape <= 0:
        return CellError(CellError.NUM)
    return _bisect(lambda t: _gamma_cdf(t, shape, scale), p, 0.0, shape * scale + 1.0)


def _q_beta(args: list) -> Any:
    p = _num(_arg(args, 0)); a = _num(_arg(args, 1)); b = _num(_arg(args, 2))
    if p is None or a is None or b is None or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return _bisect(lambda t: _betai(a, b, t), p, 0.0, 1.0)


def _q_chisq(args: list) -> Any:
    p = _num(_arg(args, 0)); df = _num(_arg(args, 1))
    if p is None or df is None or not (0.0 < p < 1.0) or df <= 0:
        return CellError(CellError.NUM)
    return _bisect(lambda t: _chisq_cdf(t, df), p, 0.0, df + 10.0)


def _q_t(args: list) -> Any:
    p = _num(_arg(args, 0)); df = _num(_arg(args, 1))
    if p is None or df is None or not (0.0 < p < 1.0) or df <= 0:
        return CellError(CellError.NUM)
    return _bisect(lambda t: _t_cdf(t, df), p, -1e6, 1e6)


def _q_f(args: list) -> Any:
    p = _num(_arg(args, 0)); d1 = _num(_arg(args, 1)); d2 = _num(_arg(args, 2))
    if p is None or d1 is None or d2 is None or not (0.0 < p < 1.0) or d1 <= 0 or d2 <= 0:
        return CellError(CellError.NUM)
    return _bisect(lambda t: _f_cdf(t, d1, d2), p, 0.0, 100.0)


def _q_gumbel(args: list) -> Any:
    p = _num(_arg(args, 0)); loc = _num(_arg(args, 1, 0.0)); sc = _num(_arg(args, 2, 1.0))
    if p is None or loc is None or sc is None or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return loc - sc * math.log(-math.log(p))


def _q_laplace(args: list) -> Any:
    p = _num(_arg(args, 0)); loc = _num(_arg(args, 1, 0.0)); sc = _num(_arg(args, 2, 1.0))
    if p is None or loc is None or sc is None or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return loc + sc * math.log(2 * p) if p < 0.5 else loc - sc * math.log(2 * (1 - p))


def _q_logis(args: list) -> Any:
    p = _num(_arg(args, 0)); loc = _num(_arg(args, 1, 0.0)); sc = _num(_arg(args, 2, 1.0))
    if p is None or loc is None or sc is None or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return loc + sc * math.log(p / (1 - p))


def _q_rayleigh(args: list) -> Any:
    p = _num(_arg(args, 0)); sc = _num(_arg(args, 1, 1.0))
    if p is None or sc is None or not (0.0 <= p < 1.0) or sc <= 0:
        return CellError(CellError.NUM)
    return sc * math.sqrt(-2.0 * math.log1p(-p))


def _q_pareto(args: list) -> Any:
    p = _num(_arg(args, 0)); scale = _num(_arg(args, 1)); shape = _num(_arg(args, 2))
    if p is None or scale is None or shape is None or not (0.0 <= p < 1.0) \
            or scale <= 0 or shape <= 0:
        return CellError(CellError.NUM)
    return scale / (1.0 - p) ** (1.0 / shape)


# --- discrete distributions ------------------------------------------------


def _geom_pmf(k: int, p: float) -> float:
    return p * (1.0 - p) ** k if k >= 0 else 0.0


def _nbinom_pmf(k: int, size: float, prob: float) -> float:
    if k < 0:
        return 0.0
    logc = math.lgamma(k + size) - math.lgamma(size) - math.lgamma(k + 1)
    return math.exp(logc + size * math.log(prob) + k * math.log1p(-prob))


def _disc(pmf: Callable, cdf: bool, nparams: int):
    """Wrap a discrete distribution's PMF into a density (cdf=False) or a
    cumulative (cdf=True) callable with ``nparams`` distribution parameters."""
    def impl(args: list) -> Any:
        kv = _num(_arg(args, 0))
        params = [_num(_arg(args, i + 1)) for i in range(nparams)]
        if kv is None or any(p is None for p in params):
            return CellError(CellError.VALUE)
        k = int(math.floor(kv))
        try:
            if not cdf:
                return pmf(k, *params)
            return sum(pmf(i, *params) for i in range(0, k + 1))
        except (ValueError, OverflowError):
            return CellError(CellError.NUM)
    return impl


def _snorm_args(args: list):
    x = _num(_arg(args, 0))
    loc = _num(_arg(args, 1, 0.0))
    sc = _num(_arg(args, 2, 1.0))
    sh = _num(_arg(args, 3, 0.0))
    if x is None or loc is None or sc is None or sh is None or sc <= 0:
        return None
    return x, loc, sc, sh


def _fn_dsnorm(args: list) -> Any:
    a = _snorm_args(args)
    if a is None:
        return CellError(CellError.NUM)
    return _snorm_pdf(*a)


def _fn_psnorm(args: list) -> Any:
    a = _snorm_args(args)
    if a is None:
        return CellError(CellError.NUM)
    return _snorm_cdf(*a)


def _q_snorm(args: list) -> Any:
    p = _num(_arg(args, 0))
    loc = _num(_arg(args, 1, 0.0))
    sc = _num(_arg(args, 2, 1.0))
    sh = _num(_arg(args, 3, 0.0))
    if p is None or loc is None or sc is None or sh is None or sc <= 0 or not (0.0 < p < 1.0):
        return CellError(CellError.NUM)
    return _bisect(lambda t: _snorm_cdf(t, loc, sc, sh), p, loc - 8 * sc, loc + 8 * sc)


def _disc_quantile(pmf: Callable, nparams: int):
    """Quantile for a discrete distribution: the smallest k with CDF(k) >= p."""
    def impl(args: list) -> Any:
        p = _num(_arg(args, 0))
        params = [_num(_arg(args, i + 1)) for i in range(nparams)]
        if p is None or any(x is None for x in params) or not (0.0 <= p <= 1.0):
            return CellError(CellError.NUM)
        try:
            cum = 0.0
            for k in range(0, 1_000_000):
                cum += pmf(k, *params)
                if cum >= p - 1e-12:
                    return float(k)
        except (ValueError, OverflowError):
            return CellError(CellError.NUM)
        return CellError(CellError.NUM)
    return impl


# --- registry --------------------------------------------------------------

_REGISTRY: dict[str, Callable[[list], Any]] = {
    # Normal
    "R.DNORM": _cont3(_norm_pdf, 0.0, 1.0),
    "R.PNORM": _cont3(_norm_cdf, 0.0, 1.0),
    "R.QNORM": _q_normal,
    # Log-normal
    "R.DLNORM": _cont3(lambda x, ml, sl: _norm_pdf(math.log(x), ml, sl) / x if x > 0 else 0.0,
                       0.0, 1.0),
    "R.PLNORM": _cont3(lambda x, ml, sl: _norm_cdf(math.log(x), ml, sl) if x > 0 else 0.0,
                       0.0, 1.0),
    "R.QLNORM": _q_lognormal,
    # Exponential (rate)
    "R.DEXP": _cont2(lambda x, rate: rate * math.exp(-rate * x) if x >= 0 else 0.0, 1.0),
    "R.PEXP": _cont2(lambda x, rate: 1.0 - math.exp(-rate * x) if x >= 0 else 0.0, 1.0),
    "R.QEXP": _q_exp,
    # Gamma (shape, scale)
    "R.DGAMMA": _cont3(_gamma_pdf, None, 1.0),
    "R.PGAMMA": _cont3(_gamma_cdf, None, 1.0),
    "R.QGAMMA": _q_gamma,
    # Beta
    "R.DBETA": _cont3(_beta_pdf),
    "R.PBETA": _cont3(lambda x, a, b: _betai(a, b, x)),  # _betai takes (a, b, x)
    "R.QBETA": _q_beta,
    # Weibull (shape, scale)
    "R.DWEIBULL": _cont3(_weibull_pdf, None, 1.0),
    "R.PWEIBULL": _cont3(_weibull_cdf, None, 1.0),
    "R.QWEIBULL": _q_weibull,
    # Chi-square
    "R.DCHISQ": _cont2(_chisq_pdf),
    "R.PCHISQ": _cont2(_chisq_cdf),
    "R.QCHISQ": _q_chisq,
    # Student t
    "R.DT": _cont2(_t_pdf),
    "R.PT": _cont2(_t_cdf),
    "R.QT": _q_t,
    # F
    "R.DF": _cont3(_f_pdf),
    "R.PF": _cont3(_f_cdf),
    "R.QF": _q_f,
    # Uniform
    "R.DUNIF": _cont3(lambda x, a, b: 1.0 / (b - a) if a <= x <= b else 0.0, 0.0, 1.0),
    "R.PUNIF": _cont3(lambda x, a, b: min(1.0, max(0.0, (x - a) / (b - a))), 0.0, 1.0),
    "R.QUNIF": _q_uniform,
    # Cauchy
    "R.DCAUCHY": _cont3(lambda x, loc, sc: 1.0 / (math.pi * sc * (1 + ((x - loc) / sc) ** 2)),
                        0.0, 1.0),
    "R.PCAUCHY": _cont3(lambda x, loc, sc: 0.5 + math.atan((x - loc) / sc) / math.pi, 0.0, 1.0),
    "R.QCAUCHY": _q_cauchy,
    # Gumbel (extreme value)
    "R.DGUMBEL": _cont3(_gumbel_pdf, 0.0, 1.0),
    "R.PGUMBEL": _cont3(_gumbel_cdf, 0.0, 1.0),
    "R.QGUMBEL": _q_gumbel,
    # Laplace (double exponential)
    "R.DLAPLACE": _cont3(_laplace_pdf, 0.0, 1.0),
    "R.PLAPLACE": _cont3(_laplace_cdf, 0.0, 1.0),
    "R.QLAPLACE": _q_laplace,
    # Logistic
    "R.DLOGIS": _cont3(_logis_pdf, 0.0, 1.0),
    "R.PLOGIS": _cont3(_logis_cdf, 0.0, 1.0),
    "R.QLOGIS": _q_logis,
    # Skew-normal
    "R.DSNORM": _fn_dsnorm,
    "R.PSNORM": _fn_psnorm,
    "R.QSNORM": _q_snorm,
    # Rayleigh (scale)
    "R.DRAYLEIGH": _cont2(_rayleigh_pdf, 1.0),
    "R.PRAYLEIGH": _cont2(_rayleigh_cdf, 1.0),
    "R.QRAYLEIGH": _q_rayleigh,
    # Pareto (scale = minimum, shape)
    "R.DPARETO": _cont3(_pareto_pdf),
    "R.PPARETO": _cont3(_pareto_cdf),
    "R.QPARETO": _q_pareto,
    # Discrete
    "R.DBINOM": _disc(lambda k, n, p: _binom_pmf(k, int(n), p), False, 2),
    "R.PBINOM": _disc(lambda k, n, p: _binom_pmf(k, int(n), p), True, 2),
    "R.QBINOM": _disc_quantile(lambda k, n, p: _binom_pmf(k, int(n), p), 2),
    "R.DPOIS": _disc(lambda k, lam: _poisson_pmf(k, lam), False, 1),
    "R.PPOIS": _disc(lambda k, lam: _poisson_pmf(k, lam), True, 1),
    "R.QPOIS": _disc_quantile(lambda k, lam: _poisson_pmf(k, lam), 1),
    "R.DGEOM": _disc(_geom_pmf, False, 1),
    "R.PGEOM": _disc(_geom_pmf, True, 1),
    "R.QGEOM": _disc_quantile(_geom_pmf, 1),
    "R.DNBINOM": _disc(_nbinom_pmf, False, 2),
    "R.PNBINOM": _disc(_nbinom_pmf, True, 2),
    "R.QNBINOM": _disc_quantile(_nbinom_pmf, 2),
    "R.DHYPER": _disc(lambda k, ns, m, npop: _hypgeom_pmf(k, int(ns), int(m), int(npop)), False, 3),
    "R.PHYPER": _disc(lambda k, ns, m, npop: _hypgeom_pmf(k, int(ns), int(m), int(npop)), True, 3),
    "R.QHYPER": _disc_quantile(
        lambda k, ns, m, npop: _hypgeom_pmf(k, int(ns), int(m), int(npop)), 3),
}


def register(functions: dict) -> None:
    """Merge the Wave-H R.* distribution family into the engine's table."""
    functions.update(_REGISTRY)
