"""Evaluate an AST against a cell-value resolver.

The resolver is any callable ``resolver(row, col) -> value`` returning the
already-computed value of a cell (the :class:`~qcell.core.sheet.Sheet`
provides one). The evaluator handles operator semantics, error propagation,
and lazy evaluation of ``IF``; everything else dispatches to
:data:`qcell.core.functions.FUNCTIONS`.
"""

from __future__ import annotations

from typing import Any, Callable

from . import ast_nodes as A
from .errors import CellError, FormulaError, is_error
from .functions import FUNCTIONS, LAZY_FUNCTIONS
from .reference import parse_a1, parse_range
from .tokenizer import Token  # noqa: F401  (re-export convenience)
from .values import RangeValue

Resolver = Callable[[str, int, int], Any]  # (sheet_name, row, col) -> value


def _num(v: Any) -> float | CellError:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return CellError(CellError.VALUE)


def _compare(op: str, a: Any, b: Any) -> Any:
    # Numeric compare when both look numeric; else string compare (Excel-ish).
    an, bn = _num(a), _num(b)
    if not is_error(an) and not is_error(bn) and not isinstance(a, str) and not isinstance(b, str):
        left, right = an, bn
    else:
        left = a if isinstance(a, str) else _text_for_cmp(a)
        right = b if isinstance(b, str) else _text_for_cmp(b)
        if isinstance(left, str) and isinstance(right, str):
            left, right = left.lower(), right.lower()
    try:
        if op == "=":
            return left == right
        if op == "<>":
            return left != right
        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        if op == ">=":
            return left >= right
    except TypeError:
        return CellError(CellError.VALUE)
    return CellError(CellError.VALUE)


def _text_for_cmp(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def evaluate(node: Any, resolver: Resolver) -> Any:
    # Ordered by frequency in real recalc (Ref/Number/Binary/Func dominate), so
    # the common cases short-circuit early. A type->handler dict was measured
    # *slower* here: isinstance on a short chain is cheap C-level work, while
    # per-node handler functions add Python call overhead that dominates.
    if isinstance(node, A.Ref):
        row, col = parse_a1(node.text)
        return resolver(node.sheet, row, col)
    if isinstance(node, A.Number):
        return node.value
    if isinstance(node, A.Binary):
        return _eval_binary(node, resolver)
    if isinstance(node, A.Func):
        return _eval_func(node, resolver)
    if isinstance(node, A.String):
        return node.value
    if isinstance(node, A.Range):
        r1, c1, r2, c2 = parse_range(node.text)
        grid = [
            [resolver(node.sheet, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)
        ]
        return RangeValue(grid)
    if isinstance(node, A.Name):
        if node.text == "TRUE":
            return True
        if node.text == "FALSE":
            return False
        return CellError(CellError.NAME, node.text)
    if isinstance(node, A.Unary):
        val = evaluate(node.operand, resolver)
        if is_error(val):
            return val
        n = _num(val)
        if is_error(n):
            return n
        return -n if node.op == "-" else n
    if isinstance(node, A.Error):
        return CellError(node.code)
    raise FormulaError(f"cannot evaluate node: {node!r}")


def _eval_binary(node: A.Binary, resolver: Resolver) -> Any:
    op = node.op
    left = evaluate(node.left, resolver)
    right = evaluate(node.right, resolver)
    # A range or array used as a scalar operand is an error.
    if isinstance(left, (list, RangeValue)) or isinstance(right, (list, RangeValue)):
        return CellError(CellError.VALUE)
    if is_error(left):
        return left
    if is_error(right):
        return right
    if op == "&":
        return _text_for_cmp(left) + _text_for_cmp(right)
    if op in ("=", "<>", "<", ">", "<=", ">="):
        return _compare(op, left, right)
    a, b = _num(left), _num(right)
    if is_error(a):
        return a
    if is_error(b):
        return b
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return CellError(CellError.DIV0) if b == 0 else a / b
    if op == "%":
        return CellError(CellError.DIV0) if b == 0 else a % b
    if op == "^":
        try:
            return float(a) ** float(b)
        except (ValueError, OverflowError):
            return CellError(CellError.NUM)
    raise FormulaError(f"unknown operator: {op}")


def _eval_func(node: A.Func, resolver: Resolver) -> Any:
    name = node.name
    # Lazy functions (IF, IFERROR, IFS, SWITCH, CHOOSE) receive unevaluated AST
    # nodes plus an on-demand evaluator, so untaken branches never run.
    lazy = LAZY_FUNCTIONS.get(name)
    if lazy is not None:
        return lazy(node.args, lambda n: evaluate(n, resolver))

    fn = FUNCTIONS.get(name)
    if fn is None:
        return CellError(CellError.NAME, name)
    args = [evaluate(a, resolver) for a in node.args]
    try:
        return fn(args)
    except (ValueError, TypeError, ZeroDivisionError, IndexError, OverflowError):
        return CellError(CellError.VALUE)
