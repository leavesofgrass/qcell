"""Tests for the degraded pure-Python restriction mode (abax.restricted).

These tests exercise both the static AST allowlist (check_ast) and the
end-to-end runner (run_restricted). They also document -- honestly -- that
this is hardening, not a security boundary.
"""

from __future__ import annotations

import pytest

from abax.restricted import (
    ALLOWED_IMPORTS,
    RestrictionError,
    check_ast,
    run_restricted,
    safe_builtins,
)

# ---------------------------------------------------------------------------
# Happy path: allowed code runs and produces output.
# ---------------------------------------------------------------------------


def test_allowed_code_runs_and_captures_output():
    result = run_restricted("print(sum(range(10)))")
    assert result["error"] is None
    assert result["output"].strip() == "45"


def test_import_math_is_allowed_and_usable():
    src = "import math\nprint(math.factorial(5))"
    check_ast(src)  # must not raise
    result = run_restricted(src)
    assert result["error"] is None
    assert result["output"].strip() == "120"


def test_from_import_of_allowed_module_works():
    src = "from math import sqrt\nprint(sqrt(16))"
    result = run_restricted(src)
    assert result["error"] is None
    assert result["output"].strip() == "4.0"


def test_namespace_value_is_visible_to_code():
    result = run_restricted("print(supplied * 2)", {"supplied": 21})
    assert result["error"] is None
    assert result["output"].strip() == "42"


def test_namespace_readback_after_run():
    result = run_restricted("answer = 6 * 7")
    assert result["error"] is None
    assert result["namespace"]["answer"] == 42


# ---------------------------------------------------------------------------
# Import restrictions.
# ---------------------------------------------------------------------------


def test_import_os_is_rejected():
    with pytest.raises(RestrictionError) as exc:
        check_ast("import os")
    assert "os" in str(exc.value)


@pytest.mark.parametrize("mod", ["sys", "subprocess", "socket", "shutil", "pathlib", "io"])
def test_dangerous_imports_rejected(mod):
    with pytest.raises(RestrictionError):
        check_ast(f"import {mod}")


def test_from_import_of_forbidden_module_rejected():
    with pytest.raises(RestrictionError):
        check_ast("from os import path")


def test_relative_import_rejected():
    with pytest.raises(RestrictionError):
        check_ast("from . import something")


def test_run_restricted_surfaces_import_rejection_as_error():
    # check_ast raises, but run_restricted must not propagate -- it captures it.
    result = run_restricted("import os")
    assert result["error"] is not None
    assert "RestrictionError" in result["error"]
    assert result["output"] == ""


# ---------------------------------------------------------------------------
# Dunder / reflection escape.
# ---------------------------------------------------------------------------


def test_classic_subclasses_escape_is_rejected():
    # The canonical "break out via the object graph" gadget.
    with pytest.raises(RestrictionError) as exc:
        check_ast("().__class__.__bases__[0].__subclasses__()")
    # Some dunder attribute in the chain is rejected (the walker hits the
    # outermost one first); which one is an implementation detail.
    assert "dunder attribute" in str(exc.value)


@pytest.mark.parametrize(
    "src",
    [
        "x.__globals__",
        "f.__code__",
        "obj.__dict__",
        "type.__mro__",
    ],
)
def test_dunder_attribute_access_rejected(src):
    with pytest.raises(RestrictionError):
        check_ast(src)


def test_bare_dunder_name_rejected():
    with pytest.raises(RestrictionError):
        check_ast("print(__builtins__)")


# ---------------------------------------------------------------------------
# Forbidden builtin calls.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        "eval('1+1')",
        "exec('x = 1')",
        "compile('1', '<s>', 'eval')",
        "open('/etc/passwd')",
        "input('> ')",
        "getattr(x, '__class__')",
        "setattr(x, 'y', 1)",
        "delattr(x, 'y')",
        "globals()",
        "locals()",
        "vars()",
        "breakpoint()",
    ],
)
def test_forbidden_builtin_calls_rejected(src):
    with pytest.raises(RestrictionError):
        check_ast(src)


def test_dunder_import_call_rejected():
    with pytest.raises(RestrictionError):
        check_ast("__import__('os')")


# ---------------------------------------------------------------------------
# Runtime error handling: user code must never kill the caller.
# ---------------------------------------------------------------------------


def test_runtime_error_captured_not_raised():
    result = run_restricted("print(1)\nraise ValueError('boom')")
    assert result["error"] is not None
    assert "ValueError" in result["error"]
    assert "boom" in result["error"]
    # Output produced before the error is still captured.
    assert result["output"].strip() == "1"


def test_zero_division_captured():
    result = run_restricted("1 / 0")
    assert result["error"] is not None
    assert "ZeroDivisionError" in result["error"]


def test_syntax_error_captured_not_raised():
    result = run_restricted("def (:")
    assert result["error"] is not None
    assert "SyntaxError" in result["error"]


# ---------------------------------------------------------------------------
# safe_builtins() contents.
# ---------------------------------------------------------------------------


def test_safe_builtins_omits_dangerous_names():
    b = safe_builtins()
    for name in ("eval", "exec", "compile", "open", "input", "getattr",
                 "setattr", "delattr", "globals", "locals", "vars", "breakpoint"):
        assert name not in b, f"{name} must not be in safe builtins"


def test_safe_builtins_includes_common_helpers():
    b = safe_builtins()
    for name in ("abs", "min", "max", "sum", "len", "range", "print",
                 "int", "str", "list", "dict", "sorted"):
        assert name in b


def test_safe_builtins_includes_exceptions():
    b = safe_builtins()
    assert b["ValueError"] is ValueError
    assert b["KeyError"] is KeyError


def test_restricted_import_wrapper_blocks_disallowed():
    imp = safe_builtins()["__import__"]
    with pytest.raises(RestrictionError):
        imp("os")


def test_restricted_import_wrapper_allows_allowlisted():
    imp = safe_builtins()["__import__"]
    mod = imp("math")
    assert mod.pi > 3


# ---------------------------------------------------------------------------
# Honest documentation of the contract.
#
# This is HARDENING, NOT a security boundary. AST allowlisting and namespace
# restriction in CPython can always be escaped by a determined attacker
# (bytecode tricks, C-level escapes, reference walking). The value is stopping
# CASUAL / ACCIDENTAL harm, not defeating an adversary. The tests below assert
# only the honest API contract -- they do NOT claim the escape surface is
# closed.
# ---------------------------------------------------------------------------


def test_not_a_security_boundary_contract():
    # The module openly states it is not a sandbox. We assert the runner's
    # documented contract: it returns a dict and never raises for arbitrary
    # input -- NOT that arbitrary code is contained.
    result = run_restricted("print('hello')")
    assert set(result) == {"output", "error", "namespace"}
    # Known limitation: a determined attacker inside CPython can still escape.
    # We do not, and cannot, assert otherwise. This test exists to document
    # that the contract is "best-effort hardening", nothing stronger.


def test_allowlist_is_a_frozenset_constant():
    # Documenting the shape of the public allowlist so callers can introspect.
    assert isinstance(ALLOWED_IMPORTS, frozenset)
    assert "math" in ALLOWED_IMPORTS
    assert "os" not in ALLOWED_IMPORTS
