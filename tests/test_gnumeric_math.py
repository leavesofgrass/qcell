"""Wave H — Gnumeric special-math and number-theory functions."""

from __future__ import annotations

import math

from abax.core.errors import CellError
from abax.core.functions import FUNCTIONS


def v(name, *a):
    return FUNCTIONS[name](list(a))


def test_all_registered():
    for name in ("BETA", "BETALN", "POCHHAMMER", "GD",
                 "ITHPRIME", "ISPRIME", "NT_D", "NT_SIGMA", "NT_PHI", "NT_MU"):
        assert name in FUNCTIONS, name


def test_beta_and_betaln():
    assert math.isclose(v("BETA", 2, 3), 1 / 12)
    assert math.isclose(v("BETALN", 2, 3), math.log(1 / 12))
    assert isinstance(v("BETA", -1, 2), CellError)


def test_pochhammer():
    assert v("POCHHAMMER", 5, 3) == 210      # 5*6*7
    assert v("POCHHAMMER", 1, 5) == 120      # 1*2*3*4*5 = 5!
    assert math.isclose(v("POCHHAMMER", 2.5, 2), 2.5 * 3.5)


def test_gudermannian():
    assert v("GD", 0) == 0.0
    # gd is odd and bounded by pi/2
    assert math.isclose(v("GD", 1), -v("GD", -1))
    assert v("GD", 100) <= math.pi / 2


def test_ithprime_and_isprime():
    assert v("ITHPRIME", 1) == 2
    assert v("ITHPRIME", 10) == 29
    assert v("ISPRIME", 97) is True
    assert v("ISPRIME", 1) is False
    assert v("ISPRIME", 100) is False


def test_number_theory():
    assert v("NT_D", 12) == 6          # 1,2,3,4,6,12
    assert v("NT_SIGMA", 12) == 28     # sum of divisors
    assert v("NT_PHI", 12) == 4        # coprime: 1,5,7,11
    assert v("NT_PHI", 1) == 1
    assert v("NT_MU", 1) == 1
    assert v("NT_MU", 30) == -1        # 2*3*5, three distinct primes
    assert v("NT_MU", 12) == 0         # 2^2 * 3, squared factor


def test_domain_errors():
    assert isinstance(v("NT_D", 0), CellError)
    assert isinstance(v("NT_PHI", -3), CellError)


def test_nt_pi_prime_counting():
    assert v("NT_PI", 10) == 4       # 2,3,5,7
    assert v("NT_PI", 20) == 8
    assert v("NT_PI", 1) == 0
