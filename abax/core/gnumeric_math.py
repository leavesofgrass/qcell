"""Wave H — Gnumeric special-math and number-theory functions.

Pure-stdlib functions Gnumeric ships that Excel lacks: the beta function and its
log, the Pochhammer symbol, the Gudermannian, and Gnumeric's number-theory pack
(``ITHPRIME`` / ``ISPRIME`` / ``NT_D`` / ``NT_SIGMA`` / ``NT_PHI`` / ``NT_MU``).
Registered by :func:`register` alongside the other parity packs.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from .errors import CellError


def _num(v: Any) -> "float | None":
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _arg(args: list, i: int, default: Any = None) -> Any:
    return args[i] if i < len(args) else default


# --- special functions -----------------------------------------------------


def _beta(args: list) -> Any:
    a = _num(_arg(args, 0)); b = _num(_arg(args, 1))
    if a is None or b is None:
        return CellError(CellError.VALUE)
    if a <= 0 or b <= 0:
        return CellError(CellError.NUM)
    try:
        return math.exp(math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b))
    except (ValueError, OverflowError):
        return CellError(CellError.NUM)


def _betaln(args: list) -> Any:
    a = _num(_arg(args, 0)); b = _num(_arg(args, 1))
    if a is None or b is None:
        return CellError(CellError.VALUE)
    if a <= 0 or b <= 0:
        return CellError(CellError.NUM)
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _pochhammer(args: list) -> Any:
    """POCHHAMMER(x, n) — the rising factorial (x)_n = Gamma(x+n)/Gamma(x)."""
    x = _num(_arg(args, 0)); n = _num(_arg(args, 1))
    if x is None or n is None:
        return CellError(CellError.VALUE)
    try:
        # Use the sign-aware gamma via lgamma where the arguments are positive;
        # fall back to a direct product for small integer n (handles x <= 0).
        if n == int(n) and 0 <= n <= 170:
            result = 1.0
            for k in range(int(n)):
                result *= (x + k)
            return result
        return math.exp(math.lgamma(x + n) - math.lgamma(x))
    except (ValueError, OverflowError):
        return CellError(CellError.NUM)


def _gd(args: list) -> Any:
    """GD(x) — the Gudermannian function, gd(x) = 2*atan(tanh(x/2))."""
    x = _num(_arg(args, 0))
    if x is None:
        return CellError(CellError.VALUE)
    return 2.0 * math.atan(math.tanh(x / 2.0))


# --- number theory ---------------------------------------------------------


def _ithprime(args: list) -> Any:
    """ITHPRIME(n) — the n-th prime (ITHPRIME(1) = 2)."""
    n = _num(_arg(args, 0))
    if n is None:
        return CellError(CellError.VALUE)
    n = int(n)
    if n < 1 or n > 1_000_000:
        return CellError(CellError.NUM)
    count = 0
    candidate = 1
    while count < n:
        candidate += 1
        if _is_prime(candidate):
            count += 1
    return float(candidate)


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def _isprime(args: list) -> Any:
    n = _num(_arg(args, 0))
    if n is None:
        return CellError(CellError.VALUE)
    return _is_prime(int(n))


def _nt_pi(args: list) -> Any:
    """NT_PI(n) — the prime-counting function: how many primes are <= n."""
    n = _num(_arg(args, 0))
    if n is None:
        return CellError(CellError.VALUE)
    n = int(n)
    if n < 2:
        return 0.0
    return float(sum(1 for k in range(2, n + 1) if _is_prime(k)))


def _divisors(n: int) -> "list[int]":
    n = abs(int(n))
    if n == 0:
        return []
    out = set()
    i = 1
    while i * i <= n:
        if n % i == 0:
            out.add(i)
            out.add(n // i)
        i += 1
    return sorted(out)


def _nt_d(args: list) -> Any:
    """NT_D(n) — the number of divisors of n."""
    n = _num(_arg(args, 0))
    if n is None:
        return CellError(CellError.VALUE)
    if int(n) < 1:
        return CellError(CellError.NUM)
    return float(len(_divisors(int(n))))


def _nt_sigma(args: list) -> Any:
    """NT_SIGMA(n) — the sum of the divisors of n."""
    n = _num(_arg(args, 0))
    if n is None:
        return CellError(CellError.VALUE)
    if int(n) < 1:
        return CellError(CellError.NUM)
    return float(sum(_divisors(int(n))))


def _prime_factors(n: int) -> "dict[int, int]":
    n = abs(int(n))
    factors: dict[int, int] = {}
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors[d] = factors.get(d, 0) + 1
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        factors[n] = factors.get(n, 0) + 1
    return factors


def _nt_phi(args: list) -> Any:
    """NT_PHI(n) — Euler's totient: the count of k in [1, n] coprime to n."""
    n = _num(_arg(args, 0))
    if n is None:
        return CellError(CellError.VALUE)
    n = int(n)
    if n < 1:
        return CellError(CellError.NUM)
    result = n
    for p in _prime_factors(n):
        result -= result // p
    return float(result)


def _nt_mu(args: list) -> Any:
    """NT_MU(n) — the Moebius function (0 if n has a squared prime factor,
    else (-1)^k for k distinct primes)."""
    n = _num(_arg(args, 0))
    if n is None:
        return CellError(CellError.VALUE)
    n = int(n)
    if n < 1:
        return CellError(CellError.NUM)
    if n == 1:
        return 1.0
    factors = _prime_factors(n)
    if any(exp > 1 for exp in factors.values()):
        return 0.0
    return float((-1) ** len(factors))


# --- registry --------------------------------------------------------------

_REGISTRY: dict[str, Callable[[list], Any]] = {
    "BETA": _beta,
    "BETALN": _betaln,
    "POCHHAMMER": _pochhammer,
    "GD": _gd,
    "ITHPRIME": _ithprime,
    "ISPRIME": _isprime,
    "NT_PI": _nt_pi,
    "NT_D": _nt_d,
    "NT_SIGMA": _nt_sigma,
    "NT_PHI": _nt_phi,
    "NT_MU": _nt_mu,
}


def register(functions: dict) -> None:
    """Merge the special-math / number-theory functions into the engine's table."""
    functions.update(_REGISTRY)
