"""The organizer's points formula: parse once, evaluate per team per game.

A formula is an expression over the stage's column keys plus ``place``,
``place_pts`` and ``teams`` (docs/plans/2026-09-26-ffa-custom-scoring.md §4).
It is parsed with the standard :mod:`ast` against a whitelist of nodes and run
by a recursive interpreter: ``eval`` and ``compile`` are never called, so a
saved formula cannot reach anything except arithmetic on the numbers it is
handed. Everything the whitelist does not name is refused on write, which is
why a future Python construct cannot leak in.
"""

from __future__ import annotations

import ast
import math
import operator
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = (
    "BUILTIN_VARIABLES",
    "FORMULA_MAX_LENGTH",
    "FORMULA_MAX_NODES",
    "FUNCTIONS",
    "RESERVED_NAMES",
    "FfaFormulaError",
    "Formula",
    "compile_formula",
    "round_half_up",
)

#: An organizer writes a rule, not a program. Both caps exist so a pasted blob
#: is refused at the edit endpoint instead of being walked per team per game
#: forever after.
FORMULA_MAX_LENGTH = 500
FORMULA_MAX_NODES = 100

#: Readable in every formula, whatever the stage's columns are.
BUILTIN_VARIABLES: frozenset[str] = frozenset({"place", "place_pts", "teams"})
FUNCTIONS: frozenset[str] = frozenset({"min", "max", "abs", "round", "if"})
#: Refused as a column key: a column called ``place`` or ``min`` would shadow
#: the builtin and silently change every formula that already reads it.
RESERVED_NAMES: frozenset[str] = BUILTIN_VARIABLES | FUNCTIONS | {"if_", "and", "or", "not"}

#: ``if`` is a Python keyword, so ``if(a, b, c)`` cannot be parsed as a call.
#: Renaming it before the parse is unambiguous: the language has no strings and
#: no column may be called ``if``/``if_`` (RESERVED_NAMES).
_IF_CALL = re.compile(r"\bif(?=\s*\()")
_CONDITIONAL = "if_"

_MAX_ROUND_DIGITS = 6

_COMPARISONS: dict[type[ast.cmpop], Callable[[float, float], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
#: Minimum and maximum argument count per callable.
_ARITY: dict[str, tuple[int, int]] = {
    "min": (2, 255),
    "max": (2, 255),
    "abs": (1, 1),
    "round": (1, 2),
    _CONDITIONAL: (3, 3),
}


class FfaFormulaError(ValueError):
    """A formula that cannot be saved, with the position a client underlines.

    ``offset`` is 0-based and always points into the string the organizer
    typed, never into the rewritten one the parser saw.
    """

    def __init__(self, code: str, message: str, *, offset: int, name: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.offset = offset
        self.name = name


@dataclass(frozen=True, slots=True)
class Formula:
    source: str
    #: The variables the formula reads -- column keys and builtins, never
    #: function names. ``FfaRules.requires_placement`` is a question about this.
    names: frozenset[str]
    #: The checked tree. Compared by nothing: two formulas are the same formula
    #: when their source is.
    node: ast.expr = field(repr=False, compare=False)

    def evaluate(self, values: Mapping[str, float]) -> float:
        """Points for one team in one game. A name with no value reads as 0."""
        return _finite(_eval(self.node, values))


def compile_formula(source: str, columns: Iterable[str]) -> Formula:
    """Parse and check ``source``; raise :class:`FfaFormulaError` if it cannot run."""
    if not source.strip():
        raise FfaFormulaError("ffa_formula_syntax", "The formula is empty", offset=0)
    if len(source) > FORMULA_MAX_LENGTH:
        raise FfaFormulaError(
            "ffa_formula_too_complex",
            f"The formula is longer than {FORMULA_MAX_LENGTH} characters",
            offset=FORMULA_MAX_LENGTH,
        )
    parsed, inserted = _rewrite_if(source)
    try:
        tree = ast.parse(parsed, mode="eval")
    except SyntaxError as exc:
        raise FfaFormulaError(
            "ffa_formula_syntax",
            exc.msg or "The formula cannot be parsed",
            offset=_origin(max((exc.offset or 1) - 1, 0), inserted),
        ) from exc
    if sum(1 for _ in ast.walk(tree)) > FORMULA_MAX_NODES:
        raise FfaFormulaError(
            "ffa_formula_too_complex", f"The formula has more than {FORMULA_MAX_NODES} parts", offset=0
        )
    known = BUILTIN_VARIABLES | {str(key) for key in columns}
    names: set[str] = set()
    _check(tree.body, known, names, inserted)
    return Formula(source=source, names=frozenset(names), node=tree.body)


def round_half_up(value: float, digits: int = 0) -> float:
    """Arithmetic rounding: ``round_half_up(2.5) == 3.0``, unlike Python's.

    An organizer writing ``round(x)`` means the school rule, and a total that
    lands on a different place than the one they computed by hand is a support
    ticket. Half goes away from zero, so -2.5 -> -3.
    """
    if not math.isfinite(value):
        return value
    try:
        return float(Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        # More integer digits than the decimal context carries: the value is far
        # past any real points total, and rounding it would change nothing.
        return value


# ── parse ────────────────────────────────────────────────────────────────────


def _rewrite_if(source: str) -> tuple[str, tuple[int, ...]]:
    """``if(`` -> ``if_(``, plus every offset an underscore was inserted at.

    The offsets are in the rewritten string, which is what :func:`_origin` maps
    back from.
    """
    parts: list[str] = []
    inserted: list[int] = []
    last = 0
    for match in _IF_CALL.finditer(source):
        parts.append(source[last : match.end()])
        parts.append("_")
        inserted.append(match.end() + len(inserted))
        last = match.end()
    parts.append(source[last:])
    return "".join(parts), tuple(inserted)


def _origin(offset: int, inserted: Sequence[int]) -> int:
    """An offset in the rewritten string, back in the organizer's coordinates."""
    return max(offset - sum(1 for position in inserted if position < offset), 0)


def _position(node: ast.AST, inserted: Sequence[int]) -> int:
    # ``col_offset`` is a utf-8 byte offset; every name this grammar accepts is
    # ASCII, so for anything that parses the two coincide.
    return _origin(getattr(node, "col_offset", 0), inserted)


#: An int literal bigger than this cannot even be converted to a float.
_MAX_FLOAT_INT = int(sys.float_info.max)


def _in_float_range(value: int | float) -> bool:
    """Is this literal a number the interpreter can compute with?

    ``math.isfinite`` converts its argument to a float first, so an int past
    the float range raises OverflowError there instead of answering False.
    """
    if isinstance(value, int):
        return -_MAX_FLOAT_INT <= value <= _MAX_FLOAT_INT
    return math.isfinite(value)


def _check(node: ast.expr, known: set[str], names: set[str], inserted: Sequence[int]) -> None:
    """Whitelist walk: collect the names read, refuse everything unlisted."""
    if isinstance(node, ast.Constant):
        # ``_finite`` on an int past the float range raises OverflowError, not
        # ValueError, and an unhandled one would answer 500 where the contract
        # promises a 422 with a position. Such a literal is out of range by the
        # same rule as ``1e400``, so it is refused the same way.
        if type(node.value) not in (int, float) or not _in_float_range(node.value):
            raise FfaFormulaError(
                "ffa_formula_unsupported", "Only finite numbers are allowed", offset=_position(node, inserted)
            )
        return
    if isinstance(node, ast.Name):
        if node.id in FUNCTIONS or node.id == _CONDITIONAL:
            raise FfaFormulaError(
                "ffa_formula_unsupported", f"`{node.id}` is a function: call it", offset=_position(node, inserted)
            )
        if node.id not in known:
            raise FfaFormulaError(
                "ffa_formula_unknown_name",
                f"Unknown name `{node.id}`",
                offset=_position(node, inserted),
                name=node.id,
            )
        names.add(node.id)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
        _check(node.operand, known, names, inserted)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        _check(node.left, known, names, inserted)
        _check(node.right, known, names, inserted)
        return
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            _check(value, known, names, inserted)
        return
    if isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _COMPARISONS:
                raise FfaFormulaError(
                    "ffa_formula_unsupported",
                    f"`{type(op).__name__}` is not allowed here",
                    offset=_position(node, inserted),
                )
        _check(node.left, known, names, inserted)
        for comparator in node.comparators:
            _check(comparator, known, names, inserted)
        return
    if isinstance(node, ast.Call):
        _check_call(node, known, names, inserted)
        return
    raise FfaFormulaError(
        "ffa_formula_unsupported",
        f"`{type(node).__name__}` is not allowed in a formula",
        offset=_position(node, inserted),
    )


def _check_call(node: ast.Call, known: set[str], names: set[str], inserted: Sequence[int]) -> None:
    offset = _position(node, inserted)
    if not isinstance(node.func, ast.Name) or node.func.id not in _ARITY:
        raise FfaFormulaError("ffa_formula_unsupported", "Unknown function", offset=offset)
    if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
        raise FfaFormulaError("ffa_formula_unsupported", "Arguments must be plain values", offset=offset)
    shown = "if" if node.func.id == _CONDITIONAL else node.func.id
    low, high = _ARITY[node.func.id]
    if not low <= len(node.args) <= high:
        raise FfaFormulaError(
            "ffa_formula_unsupported", f"`{shown}` does not take {len(node.args)} arguments", offset=offset
        )
    if node.func.id == "round" and len(node.args) == 2:
        digits = node.args[1]
        if not isinstance(digits, ast.Constant) or type(digits.value) is not int:
            raise FfaFormulaError(
                "ffa_formula_unsupported", "round() digits must be a whole number", offset=_position(digits, inserted)
            )
        if not 0 <= digits.value <= _MAX_ROUND_DIGITS:
            raise FfaFormulaError(
                "ffa_formula_unsupported",
                f"round() digits must be between 0 and {_MAX_ROUND_DIGITS}",
                offset=_position(digits, inserted),
            )
    for arg in node.args:
        _check(arg, known, names, inserted)


# ── evaluate ─────────────────────────────────────────────────────────────────


def _finite(value: float) -> float:
    """Overflow and NaN score nothing rather than poisoning a team's total."""
    return value if math.isfinite(value) else 0.0


def _eval(node: ast.expr, values: Mapping[str, float]) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(values.get(node.id, 0.0))
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return 0.0 if _eval(node.operand, values) else 1.0
        value = _eval(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, values), _eval(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        # Dividing by zero is a lobby with no deaths, not a broken game.
        return 0.0 if right == 0 else left / right
    if isinstance(node, ast.BoolOp):
        parts = [_eval(value, values) for value in node.values]
        truthy = any(parts) if isinstance(node.op, ast.Or) else all(parts)
        return 1.0 if truthy else 0.0
    if isinstance(node, ast.Compare):
        left = _eval(node.left, values)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval(comparator, values)
            if not _COMPARISONS[type(op)](left, right):
                return 0.0
            left = right
        return 1.0
    return _eval_call(node, values)


def _eval_call(node: ast.Call, values: Mapping[str, float]) -> float:
    name = node.func.id  # type: ignore[union-attr]  # _check_call proved it is a Name
    args = [_eval(arg, values) for arg in node.args]
    if name == "min":
        return min(args)
    if name == "max":
        return max(args)
    if name == "abs":
        return abs(args[0])
    if name == _CONDITIONAL:
        return args[1] if args[0] else args[2]
    return round_half_up(args[0], int(node.args[1].value) if len(args) == 2 else 0)  # type: ignore[union-attr]
