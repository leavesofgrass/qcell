"""Formula autocomplete — stdlib-only, so it lives in core.

Given the text of a formula being typed and a cursor position, return the
function names that complete the current token. Reads the live
:data:`qcell.core.functions.FUNCTIONS` / ``LAZY_FUNCTIONS`` registries, so any
user-defined functions installed by :mod:`qcell.macros` show up automatically.

The TUI and GUI both drive their completion UI from these pure functions.
"""

from __future__ import annotations


def function_names() -> list[str]:
    """All callable function names (built-ins + UDFs), sorted."""
    from .functions import FUNCTIONS, LAZY_FUNCTIONS

    return sorted(set(FUNCTIONS) | set(LAZY_FUNCTIONS))


def _in_string(text: str, cursor: int) -> bool:
    # qcell string literals are double-quoted; an odd number of quotes before
    # the cursor means we're inside one (good enough for completion gating).
    return text[:cursor].count('"') % 2 == 1


def current_token(text: str, cursor: int | None = None) -> tuple[str, int]:
    """Return ``(token, start_index)`` for the identifier ending at the cursor.

    The token is the trailing run of identifier characters that begins with a
    letter — i.e. a partial function name. Returns ``("", cursor)`` when the
    cursor is inside a string or not on a name.
    """
    if cursor is None:
        cursor = len(text)
    cursor = max(0, min(cursor, len(text)))
    if _in_string(text, cursor):
        return "", cursor
    start = cursor
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_."):
        start -= 1
    token = text[start:cursor]
    if not token or not token[0].isalpha():
        return "", cursor
    return token, start


def complete(text: str, cursor: int | None = None, *, require_formula: bool = True) -> list[str]:
    """Function names that start with the current token (case-insensitive)."""
    if require_formula and not text.startswith("="):
        return []
    token, _ = current_token(text, cursor)
    if not token:
        return []
    up = token.upper()
    return [n for n in function_names() if n.startswith(up)]


def common_prefix(names: list[str]) -> str:
    """Longest common prefix across ``names`` (for tab-to-common-prefix)."""
    if not names:
        return ""
    lo, hi = min(names), max(names)
    i = 0
    while i < len(lo) and i < len(hi) and lo[i] == hi[i]:
        i += 1
    return lo[:i]


def apply_completion(text: str, cursor: int | None, name: str) -> tuple[str, int]:
    """Replace the current token with ``name(`` and return ``(text, cursor)``."""
    if cursor is None:
        cursor = len(text)
    _, start = current_token(text, cursor)
    insert = name + "("
    new_text = text[:start] + insert + text[cursor:]
    return new_text, start + len(insert)


# Short signatures for discoverability. Anything not listed falls back to the
# function's docstring first line (covers UDFs), then ``NAME(...)``.
SIGNATURES = {
    "SUM": "SUM(number1, [number2], ...)",
    "AVERAGE": "AVERAGE(number1, [number2], ...)",
    "COUNT": "COUNT(value1, ...)",
    "COUNTIF": "COUNTIF(range, criteria)",
    "SUMIF": "SUMIF(range, criteria, [sum_range])",
    "AVERAGEIF": "AVERAGEIF(range, criteria, [average_range])",
    "IF": "IF(condition, value_if_true, [value_if_false])",
    "IFERROR": "IFERROR(value, value_if_error)",
    "IFS": "IFS(cond1, val1, [cond2, val2], ...)",
    "SWITCH": "SWITCH(expr, case1, val1, ..., [default])",
    "CHOOSE": "CHOOSE(index, value1, value2, ...)",
    "VLOOKUP": "VLOOKUP(lookup, table, col_index, [approximate])",
    "HLOOKUP": "HLOOKUP(lookup, table, row_index, [approximate])",
    "INDEX": "INDEX(range, row_num, [col_num])",
    "MATCH": "MATCH(lookup, range, [match_type])",
    "ROUND": "ROUND(number, num_digits)",
    "CONCAT": "CONCAT(text1, text2, ...)",
    "LEFT": "LEFT(text, [num_chars])",
    "MID": "MID(text, start, num_chars)",
    "SUBSTITUTE": "SUBSTITUTE(text, old, new, [instance])",
    "DATE": "DATE(year, month, day)",
    "DATEDIF": "DATEDIF(start, end, unit)",
    "TEXT": "TEXT(value, format)",
}


def signature(name: str) -> str:
    name = name.upper()
    if name in SIGNATURES:
        return SIGNATURES[name]
    from .functions import FUNCTIONS

    fn = FUNCTIONS.get(name)
    if fn is not None and fn.__doc__:
        first = fn.__doc__.strip().splitlines()[0].strip()
        if first:
            return first
    return f"{name}(...)"


# --- argument hints (which function/param the cursor is inside) ------------


def _name_before(text: str, paren_pos: int) -> str:
    """Identifier immediately preceding a ``(`` at ``paren_pos`` (else "")."""
    j = paren_pos - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    end = j + 1
    while j >= 0 and (text[j].isalnum() or text[j] in "_."):
        j -= 1
    name = text[j + 1 : end]
    return name if name and name[0].isalpha() else ""


def active_call(text: str, cursor: int | None = None) -> tuple[str, int] | None:
    """Return ``(FUNC_NAME, arg_index)`` for the innermost unclosed *named*
    call containing the cursor, or ``None``.

    ``arg_index`` is 0-based, counting commas at that call's paren depth.
    Commas inside nested parens or strings don't count.
    """
    if cursor is None:
        cursor = len(text)
    cursor = max(0, min(cursor, len(text)))
    stack: list[list] = []  # [name, arg_index]
    i = 0
    in_str = False
    while i < cursor:
        ch = text[i]
        if in_str:
            if ch == '"':
                if i + 1 < cursor and text[i + 1] == '"':  # "" escape
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            stack.append([_name_before(text, i), 0])
        elif ch == ")":
            if stack:
                stack.pop()
        elif ch == ",":
            if stack:
                stack[-1][1] += 1
        i += 1
    for name, idx in reversed(stack):
        if name:
            return name.upper(), idx
    return None


def _params(name: str) -> list[str]:
    """Parameter names parsed from a function's signature string."""
    sig = signature(name)
    if "(" not in sig:
        return []
    inner = sig[sig.index("(") + 1 : sig.rindex(")")] if ")" in sig else sig[sig.index("(") + 1 :]
    return [p.strip() for p in inner.split(",")] if inner.strip() else []


def signature_hint(text: str, cursor: int | None = None) -> dict | None:
    """Structured hint for the call under the cursor, or ``None``.

    Returns ``{name, arg_index, params, signature}``.
    """
    call = active_call(text, cursor)
    if call is None:
        return None
    name, arg_index = call
    return {
        "name": name,
        "arg_index": arg_index,
        "params": _params(name),
        "signature": signature(name),
    }


def format_hint(hint: dict, marker: tuple[str, str] = ("»", "«")) -> str:
    """Render a hint with the current parameter wrapped in ``marker``.

    Extra arguments beyond the listed params highlight the last one (variadic).
    """
    params = hint["params"]
    if not params:
        return hint["signature"]
    idx = min(hint["arg_index"], len(params) - 1)
    pieces = [f"{marker[0]}{p}{marker[1]}" if i == idx else p for i, p in enumerate(params)]
    return f"{hint['name']}(" + ", ".join(pieces) + ")"
