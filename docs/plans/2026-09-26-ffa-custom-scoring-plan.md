# FFA: столбцы организатора и формула очков — план реализации

**Status:** ready to implement (2026-09-26)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** организатор FFA-стадии задаёт столбцы игры и формулу, по которой из них и места считаются очки; очки, места и
публичная таблица пересчитываются автоматически.

**Architecture:** сырые значения игры — `encounter_game_result.stats jsonb`; столбцы и формула — колонки стадии
`ffa_columns jsonb` / `ffa_formula varchar(500)` рядом с `ffa_placement_points` (в API — блок `ffa_scoring`).
Формулу разбирает чистый модуль `shared/domain/ffa_formula.py` (стандартный `ast` + белый список узлов, без `eval`),
`shared/domain/ffa_scoring.py` считает по ней очки; запись результата, `Standing` и чтение лобби вызывают одну и ту же
арифметику. Непубличные столбцы обрезаются в публичном чтении; организатор читает всё через новый админский маршрут.

**Tech Stack:** Python 3.14 / SQLAlchemy 2 / Alembic / pydantic 2 (backend), Go gateway, Next.js 16 / react-query /
next-intl / vitest (frontend).

**Spec:** [`2026-09-26-ffa-custom-scoring.md`](./2026-09-26-ffa-custom-scoring.md) — читать до начала любой задачи.

## Global Constraints

- Столбцов на стадию — 0–10; ключ `^[a-z][a-z0-9_]{0,23}$`, уникален, не служебное имя: `place`, `place_pts`,
  `teams`, `min`, `max`, `abs`, `round`, `if`, `if_`, `and`, `or`, `not`; подпись — 1–32 символа.
- Формула — 1–500 символов, не больше 100 узлов; деление на 0 → 0; не конечный результат → 0; очки игры округляются до
  4 знаков; `round(x, n)` — половина вверх, `0 ≤ n ≤ 6`.
- Значение столбца — конечное число `0 ≤ v ≤ 1e9`, дробное допустимо; ключа нет в `stats` → 0.
- Место обязательно (перестановка `1..N`) ⇔ формула читает `place` или `place_pts`; иначе места либо у всех, либо ни
  у кого, и без мест они выводятся из очков игры: 10, 7, 7, 3 → 1, 2, 2, 4.
- Колонки стадии по умолчанию: `ffa_columns = [{"key": "score", "label": "Счёт", "public": true, "better": "higher"}]`,
  `ffa_formula = 'score'`. Пустой список столбцов — законная лига «только за место», а не «не настроено».
- Публичное чтение (`rpc.tournament.ffa_stage`, `rpc.tournament.ffa_lobby`) не содержит значений непубличных столбцов
  ни в `rules.columns`, ни в `row.stats`, ни в `cell.stats`. Админское —
  `GET /api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa`, право `match.update`, в кэш шлюза не попадает.
- Правка формулы, `placement_points`, ключей или `better` — 409 после старта посеянной следующей стадии; `label` и
  `public` — всегда; удаление ключа со значениями — 422 `ffa_column_in_use`; любая правка блока ставит пересчёт мест.
- Отказ с позицией: запись `details.fields[]` несёт `offset` (0-based) и `name` плоско рядом с `field`/`msg`/`code`.
- Поле `score` уходит из API и БД без переходного периода; задачи 2–14 выходят одним релизом.
- Коммит на задачу: `type(ffa): imperative subject`. Внутри задачи запускаются только её тесты; форматтеры, линтеры и
  полный прогон — один раз, задача 14, шаг 10.
- Команды: backend — из `backend/`, интеграционные тесты с `TEST_POSTGRES_DOCKER=1`; frontend — из `frontend/`,
  `bunx vitest run <путь>`.

## Порядок и зависимости

Задачи выполняются по номерам. Жёсткие зависимости: 1 → 2 → {3, 4, 5}; 6 ← {2, 5}; 7 ← {3, 5}; 8 ← 6;
9 ← {6, 8}; {10, 11} ← 9; 12 ← {3, 9}; 13 ← 12; 14 — последней. Промежуточные коммиты 2–13 могут ломать соседние
модули — каждая задача называет, что ломает и кто чинит; тесты самой задачи обязаны проходить.

## Решения, принятые при сборке плана

1. **Хранение — колонки стадии, не `settings_json`.** Коммит `35416163` снял `stage.settings_json`; спека §1, §3.1,
   §3.3, §5.1, §6, §7.2 уже исправлены под колонки `ffa_columns` / `ffa_formula`.
2. **Функция правил — существующая `ffa_rules(stage)`**, а не `parse_ffa_rules(settings)`.
3. **Проброс `ctx` в `field_entry` — в задаче 3, плоско** (по прецеденту `http_error`, `backend/shared/rpc/common.py:250-251`);
   задача 12 только читает `entry.offset` / `entry.name`. Разделы A и D предлагали разные формы — выбрана плоская.
4. **Пустой список столбцов не подменяется столбцом по умолчанию** ни в `ffa_rules` (задача 2), ни в
   `Stage.ffa_scoring` (задача 5): иначе лига «только за место» (`formula = place_pts`) считалась бы по `score` и
   давала всем ноль.
5. **Публичная `StandingsTable` подписывает `ffa_stat:<key>` подписью столбца** из уже загруженных `stages`
   (задача 13, шаг 7), ключ — только пока запрос не вернулся.

---

## Раздел A. Чистое ядро: формула, правила, схема настроек, тай-брейки

Задачи 1–4. Задача 1 самодостаточна. Задачи 2–4 выходят одним релизом с разделом B: после задачи 2 ломаются
`services/encounter/ffa.py` и `standings/service.py` (они ещё читают `FfaGameLine.score`), после задачи 4 ломается
`tests/test_standings_serialization.py` (строит `models.Stage(**stage_regulation())`, а колонок `ffa_columns` /
`ffa_formula` ещё нет — их добавляет задача 5). В каждой задаче указано, что она ломает; тесты самой задачи проходят.

Команды тестов — из каталога `backend/`. Ни один тест раздела A не ходит в БД, переменные окружения не нужны, кроме
`DEBUG=true`, который тесты `tournament-service` выставляют сами (`os.environ["DEBUG"] = "true"` в шапке файла).

---

### Задача 1. Разборщик формулы `shared/domain/ffa_formula.py`

**Files:**

- Create: `backend/shared/domain/ffa_formula.py`
- Create (test): `backend/shared/tests/test_ffa_formula.py`

**Interfaces:**

- Consumes: только стандартная библиотека (`ast`, `math`, `operator`, `re`, `dataclasses`, `decimal`). Ни модели, ни
  сессии, ни pydantic — модуль обязан импортироваться из `shared.domain.ffa_scoring` без побочных эффектов.
- Produces:
  ```python
  FORMULA_MAX_LENGTH: int = 500
  FORMULA_MAX_NODES: int = 100
  BUILTIN_VARIABLES: frozenset[str]   # {"place", "place_pts", "teams"}
  FUNCTIONS: frozenset[str]           # {"min", "max", "abs", "round", "if"}
  RESERVED_NAMES: frozenset[str]      # BUILTIN_VARIABLES | FUNCTIONS | {"if_", "and", "or", "not"}

  class FfaFormulaError(ValueError):
      def __init__(self, code: str, message: str, *, offset: int, name: str | None = None) -> None: ...
      code: str      # ffa_formula_syntax | ffa_formula_unknown_name | ffa_formula_unsupported | ffa_formula_too_complex
      offset: int    # 0-based позиция в ИСХОДНОЙ строке
      name: str | None

  @dataclass(frozen=True, slots=True)
  class Formula:
      source: str
      names: frozenset[str]
      node: ast.expr
      def evaluate(self, values: Mapping[str, float]) -> float: ...

  def compile_formula(source: str, columns: Iterable[str]) -> Formula: ...
  def round_half_up(value: float, digits: int = 0) -> float: ...
  ```

Шаги:

- [ ] **Шаг 1. Написать падающий тест.** Создать `backend/shared/tests/test_ffa_formula.py` целиком:

```python
"""The formula language: what it computes, and what it refuses to save.

Pure, no fixtures::

    uv run pytest shared/tests/test_ffa_formula.py -v

Every rejection is checked by ``code`` and by ``offset`` in the string the
organizer typed -- that pair is what the stage editor underlines, so it is the
contract, not the wording of the message.
"""

from __future__ import annotations

import pytest

from shared.domain.ffa_formula import FfaFormulaError, compile_formula, round_half_up

COLUMNS = ("kills", "deaths")


def points(source: str, **values: float) -> float:
    return compile_formula(source, COLUMNS).evaluate(values)


def error(source: str, columns: tuple[str, ...] = COLUMNS) -> FfaFormulaError:
    with pytest.raises(FfaFormulaError) as info:
        compile_formula(source, columns)
    return info.value


def test_every_construct_of_the_grammar_computes() -> None:
    assert points("place_pts + kills * 2 - deaths", place_pts=10, kills=3, deaths=1) == 15
    assert points("1_000 + 0.5") == 1000.5
    assert points("-kills", kills=4) == -4
    assert points("(kills + deaths) / 2", kills=3, deaths=1) == 2
    assert points("teams - place", teams=8, place=3) == 5
    assert points("min(kills, deaths, 5)", kills=9, deaths=7) == 5
    assert points("max(kills, deaths)", kills=9, deaths=7) == 9
    assert points("abs(0 - kills)", kills=4) == 4
    assert points("if(place <= 3, 10, 0)", place=2) == 10
    assert points("if(place <= 3, 10, 0)", place=9) == 0


def test_comparisons_and_logic_are_one_or_zero() -> None:
    assert points("kills == 3", kills=3) == 1.0
    assert points("kills != 3", kills=3) == 0.0
    assert points("1 < kills < 5", kills=3) == 1.0
    assert points("1 < kills < 2", kills=3) == 0.0
    assert points("kills and deaths", kills=3, deaths=0) == 0.0
    assert points("kills or deaths", kills=0, deaths=2) == 1.0
    assert points("not kills", kills=0) == 1.0


def test_a_name_with_no_value_reads_as_zero() -> None:
    # A column added mid-stage: games already played have no value for it.
    assert points("kills + deaths", kills=5) == 5


def test_dividing_by_zero_scores_zero() -> None:
    assert points("kills / deaths", kills=7, deaths=0) == 0.0


def test_an_overflowing_result_scores_zero() -> None:
    assert points("1e308 * 10") == 0.0


def test_round_is_arithmetic_not_bankers() -> None:
    assert points("round(2.5)") == 3
    assert points("round(0 - 2.5)") == -3
    assert points("round(kills / 3, 2)", kills=10) == 3.33
    assert round_half_up(0.1 + 0.2, 4) == 0.3


def test_names_are_the_variables_read_never_the_functions() -> None:
    assert compile_formula("place_pts + kills", COLUMNS).names == frozenset({"place_pts", "kills"})
    assert compile_formula("min(kills, 3)", COLUMNS).names == frozenset({"kills"})
    assert compile_formula("score", ("score",)).names == frozenset({"score"})


@pytest.mark.parametrize(
    "source",
    [
        "kills ** 2",
        "kills % 2",
        "kills // 2",
        "kills.real",
        "[kills][0]",
        "round(kills, ndigits=2)",
        "min(*[1, 2])",
        "(x for x in [1])",
        "lambda: 1",
        "(k := 2)",
        "True",
        "None",
        "1j",
        "'x'",
        "1 in [1]",
        "min(kills)",
        "abs(kills, 1)",
        "if(kills, 1)",
        "round(kills, 7)",
        "round(kills, kills)",
        "min",
    ],
)
def test_everything_outside_the_grammar_is_refused(source: str) -> None:
    assert error(source).code == "ffa_formula_unsupported"


def test_an_unknown_name_carries_the_name_and_its_position() -> None:
    unknown = error("place_pts + kils")
    assert (unknown.code, unknown.offset, unknown.name) == ("ffa_formula_unknown_name", 12, "kils")


def test_positions_point_into_the_string_the_organizer_typed() -> None:
    # ``if(`` is rewritten to ``if_(`` before parsing, so every offset the
    # parser reports is one character too far right per preceding ``if``.
    source = "if(place == 1, kills, kils)"
    assert error(source).offset == 22 and source[22:26] == "kils"

    nested = "if(place == 1, if(kills > 3, 1, 0), kills ** 2)"
    rejected = error(nested)
    assert rejected.code == "ffa_formula_unsupported"
    assert rejected.offset == 36 and nested[36:41] == "kills"


def test_an_unparsable_formula_is_a_syntax_error() -> None:
    assert error("kills +").code == "ffa_formula_syntax"
    assert error("").code == "ffa_formula_syntax"


def test_a_formula_too_big_to_walk_is_refused() -> None:
    assert error(" + ".join(["kills"] * 60)).code == "ffa_formula_too_complex"
    assert error("kills * " + "1" * 500).code == "ffa_formula_too_complex"
```

- [ ] **Шаг 2. Запустить — должен упасть.** `uv run pytest shared/tests/test_ffa_formula.py -v` из `backend/`.
  Ожидаемо: `ERROR shared/tests/test_ffa_formula.py - ModuleNotFoundError: No module named 'shared.domain.ffa_formula'`
  — ни один тест не собран.

- [ ] **Шаг 3. Реализовать.** Создать `backend/shared/domain/ffa_formula.py`:

```python
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


def _check(node: ast.expr, known: set[str], names: set[str], inserted: Sequence[int]) -> None:
    """Whitelist walk: collect the names read, refuse everything unlisted."""
    if isinstance(node, ast.Constant):
        if type(node.value) not in (int, float) or not math.isfinite(node.value):
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
```

- [ ] **Шаг 4. Запустить — должен пройти.** `uv run pytest shared/tests/test_ffa_formula.py -v` из `backend/`.
  Ожидаемо: `32 passed` (21 параметризованный случай `test_everything_outside_the_grammar_is_refused` + 11 остальных).

- [ ] **Шаг 5. Коммит.**
  `git add backend/shared/domain/ffa_formula.py backend/shared/tests/test_ffa_formula.py`
  `git commit -m "feat(ffa): parse and evaluate the organizer's points formula"`

---

### Задача 2. Правила и проверка игры `shared/domain/ffa_scoring.py`

**Files:**

- Modify: `backend/shared/domain/ffa_scoring.py` — переписывается целиком (текущие строки 1–170)
- Modify (test): `backend/shared/tests/test_ffa_scoring.py` — переписывается целиком (текущие строки 1–86)

Что задача ломает у соседей (лечат задачи 4, 5, 6): `FfaGameLine.score` больше нет, поэтому перестают
импортироваться/работать `backend/tournament-service/src/services/encounter/ffa.py` (строит `FfaGameLine(..., score=)`)
и `backend/tournament-service/src/services/standings/service.py:756` (`ffa_score=row.score`). Тесты самой задачи 2
(`shared/tests/test_ffa_scoring.py`, `shared/tests/test_ffa_formula.py`) проходят.

**Interfaces:**

- Consumes: `shared.domain.ffa_formula.Formula`, `compile_formula`, `round_half_up` (задача 1); у стадии читаются
  атрибуты `ffa_columns: list[dict]`, `ffa_placement_points: list[float]`, `ffa_formula: str` (колонки добавляет
  задача 5; до неё `ffa_rules` вызывается только с `None` или с тестовым двойником).
- Produces:
  ```python
  FFA_MAX_LOBBY_SIZE = 100
  FFA_MAX_COLUMNS = 10
  FFA_STAT_MAX = 1_000_000_000.0
  DEFAULT_COLUMN_KEY = "score"
  DEFAULT_COLUMN_LABEL = "Счёт"
  DEFAULT_FORMULA = "score"
  GAME_POINTS_DIGITS = 4

  class FfaResultError(ValueError): code: str

  @dataclass(frozen=True, slots=True)
  class FfaColumn:
      key: str; label: str; public: bool = True; better: Literal["higher", "lower"] = "higher"

  @dataclass(frozen=True, slots=True)
  class FfaRules:
      columns: tuple[FfaColumn, ...]
      placement_points: tuple[float, ...]
      formula: Formula
      @property
      def requires_placement(self) -> bool: ...
      @property
      def column_keys(self) -> tuple[str, ...]: ...

  def ffa_rules(stage: Any | None) -> FfaRules: ...

  @dataclass(frozen=True, slots=True)
  class FfaGameLine:
      team_id: int; placement: int | None; stats: Mapping[str, float]

  def normalize_game_lines(lines, participant_ids, rules) -> tuple[FfaGameLine, ...]: ...
  def game_points(line: FfaGameLine, rules: FfaRules, teams: int) -> float: ...

  @dataclass(slots=True)
  class FfaTeamTotals:
      team_id: int; games: int = 0; points: float = 0.0; wins: int = 0
      stats: dict[str, float] = field(default_factory=dict)
      best_placement: int | None = None; last_placement: int | None = None

  def team_totals(team_ids, games, rules) -> dict[int, FfaTeamTotals]: ...
  ```

Шаги:

- [ ] **Шаг 1. Написать падающий тест.** Заменить `backend/shared/tests/test_ffa_scoring.py` целиком. Текущие
  тесты пинят удаляемое поведение и переписываются:
  `test_score_only_game_ranks_by_score_and_ties_share_a_place` (строки 25–28) → `test_places_are_derived_from_game_points_with_shared_places`;
  `test_a_formula_that_pays_for_placement_needs_every_place_exactly_once` (31–38) → сохраняется по смыслу, но
  «формула платит за место» теперь определяется `formula.names`, а не непустым `placement_points`;
  `test_score_only_lobby_accepts_given_places_including_ties` (41–44) → сохраняется;
  `test_every_participant_is_accounted_for_exactly_once` (47–62) → строка `([line(1, -1), line(2, 1)], "ffa_result_invalid_score")`
  (строка 53) **удаляется**, вместо неё случаи `ffa_result_unknown_stat` / `ffa_result_missing_stat` / `ffa_result_invalid_stat`;
  `test_game_points_add_the_placement_table_and_the_score` (65–68) → `test_game_points_round_to_four_places`;
  `test_totals_seed_every_participant_and_track_placement_metrics` (71–81) — `totals[2].score == 7` (строка 80)
  заменяется на `totals[2].stats == {"kills": 7.0}`;
  `test_rules_read_the_stage_columns_and_default_to_score_only` (84–86) → `test_no_stage_reads_as_one_score_column`,
  `test_a_stage_without_columns_scores_placement_only` и `test_rules_read_the_stage_columns`.

```python
"""FFA scoring: which game is valid, what it pays, and what a season totals to.

Pure, no session and no ORM row::

    uv run pytest shared/tests/test_ffa_scoring.py -v
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.domain.ffa_formula import compile_formula
from shared.domain.ffa_scoring import (
    FfaColumn,
    FfaGameLine,
    FfaResultError,
    FfaRules,
    ffa_rules,
    game_points,
    normalize_game_lines,
    team_totals,
)


def rules(formula: str, *columns: FfaColumn, placement_points: tuple[float, ...] = ()) -> FfaRules:
    used = columns or (FfaColumn(key="score", label="Счёт"),)
    return FfaRules(
        columns=used,
        placement_points=placement_points,
        formula=compile_formula(formula, [column.key for column in used]),
    )


KILLS = FfaColumn(key="kills", label="Kills")
DEATHS = FfaColumn(key="deaths", label="Deaths", public=False, better="lower")

BATTLE_ROYALE = rules("place_pts + kills", KILLS, placement_points=(10, 6, 5))
BY_SCORE = rules("kills * 2 - deaths", KILLS, DEATHS)


def line(team_id: int, placement: int | None = None, **stats: float) -> FfaGameLine:
    return FfaGameLine(team_id=team_id, placement=placement, stats=stats)


def test_placement_is_required_exactly_when_the_formula_reads_it() -> None:
    assert BATTLE_ROYALE.requires_placement is True
    assert BY_SCORE.requires_placement is False
    assert rules("teams - place").requires_placement is True


def test_places_are_derived_from_game_points_with_shared_places() -> None:
    # 10, 7, 7, 3 -> 1, 2, 2, 4: the points the formula paid, not a raw column.
    lines = normalize_game_lines(
        [
            line(1, kills=5, deaths=0),
            line(2, kills=3, deaths=1),
            line(3, kills=3, deaths=1),
            line(4, kills=1, deaths=0),
        ],
        [1, 2, 3, 4],
        BY_SCORE,
    )

    assert [(item.team_id, item.placement) for item in lines] == [(1, 1), (2, 2), (3, 2), (4, 4)]


def test_a_formula_that_pays_for_placement_needs_every_place_exactly_once() -> None:
    with pytest.raises(FfaResultError) as missing:
        normalize_game_lines([line(1, kills=3), line(2, kills=1)], [1, 2], BATTLE_ROYALE)
    with pytest.raises(FfaResultError) as shared_place:
        normalize_game_lines([line(1, 1, kills=3), line(2, 1, kills=1)], [1, 2], BATTLE_ROYALE)

    assert missing.value.code == "ffa_result_placement_required"
    assert shared_place.value.code == "ffa_result_invalid_placement"


def test_a_formula_that_ignores_placement_accepts_given_places_including_ties() -> None:
    lines = normalize_game_lines(
        [line(1, 1, kills=5, deaths=0), line(2, 1, kills=5, deaths=0)], [1, 2], BY_SCORE
    )

    assert [item.placement for item in lines] == [1, 1]


@pytest.mark.parametrize(
    ("lines", "code"),
    [
        ([line(1, kills=1, deaths=0), line(2, kills=1, deaths=0), line(9, kills=1, deaths=0)], "ffa_result_unknown_team"),
        ([line(1, kills=1, deaths=0), line(1, kills=2, deaths=0), line(2, kills=1, deaths=0)], "ffa_result_duplicate_team"),
        ([line(1, kills=1, deaths=0)], "ffa_result_missing_team"),
        ([line(1, kills=1, deaths=0, assists=2), line(2, kills=1, deaths=0)], "ffa_result_unknown_stat"),
        ([line(1, kills=1), line(2, kills=1, deaths=0)], "ffa_result_missing_stat"),
        ([line(1, kills=-1, deaths=0), line(2, kills=1, deaths=0)], "ffa_result_invalid_stat"),
        ([line(1, kills=float("inf"), deaths=0), line(2, kills=1, deaths=0)], "ffa_result_invalid_stat"),
        ([line(1, kills=2e9, deaths=0), line(2, kills=1, deaths=0)], "ffa_result_invalid_stat"),
        ([line(1, 1, kills=1, deaths=0), line(2, kills=1, deaths=0)], "ffa_result_mixed_placement"),
        ([line(1, 3, kills=1, deaths=0), line(2, 1, kills=1, deaths=0)], "ffa_result_invalid_placement"),
    ],
)
def test_a_game_is_refused_with_the_code_the_client_branches_on(lines: list[FfaGameLine], code: str) -> None:
    with pytest.raises(FfaResultError) as exc_info:
        normalize_game_lines(lines, [1, 2], BY_SCORE)

    assert exc_info.value.code == code


def test_game_points_are_the_formula_rounded_to_four_places() -> None:
    thirds = rules("kills / 3", KILLS)

    assert game_points(line(1, 1, kills=10), thirds, 4) == 3.3333
    assert game_points(line(1, 2, kills=4), BATTLE_ROYALE, 4) == 10.0
    # A place past the end of the table pays nothing; kills still count.
    assert game_points(line(1, 9, kills=2), BATTLE_ROYALE, 4) == 2.0


def test_a_key_with_no_value_counts_as_zero() -> None:
    # A column added mid-stage must not break the games already played.
    later = rules("kills + assists", KILLS, FfaColumn(key="assists", label="Assists"))

    assert game_points(FfaGameLine(team_id=1, placement=1, stats={"kills": 4}), later, 3) == 4.0


def test_totals_sum_every_column_and_seed_the_whole_roster() -> None:
    games = [
        normalize_game_lines([line(1, 1, kills=3), line(2, 2, kills=5), line(3, 3, kills=0)], [1, 2, 3], BATTLE_ROYALE),
        normalize_game_lines([line(1, 3, kills=0), line(2, 1, kills=2), line(3, 2, kills=1)], [1, 2, 3], BATTLE_ROYALE),
    ]

    totals = team_totals([1, 2, 3, 4], games, BATTLE_ROYALE)

    assert totals[1].points == 13 + 5 and totals[1].wins == 1 and totals[1].last_placement == 3
    assert totals[2].points == 11 + 12 and totals[2].best_placement == 1
    assert totals[2].stats == {"kills": 7.0}
    assert totals[4].games == 0 and totals[4].points == 0 and totals[4].stats == {"kills": 0.0}


def test_no_stage_reads_as_one_score_column() -> None:
    default = ffa_rules(None)

    assert default.column_keys == ("score",)
    assert default.requires_placement is False
    assert game_points(FfaGameLine(team_id=1, placement=1, stats={"score": 7}), default, 3) == 7.0


def test_a_stage_without_columns_scores_placement_only() -> None:
    # An empty column list is a legal stage, not a missing one: a placement-only
    # league must not fall back to the score column and score everyone zero.
    stage = SimpleNamespace(ffa_columns=[], ffa_placement_points=[10, 6, 3], ffa_formula="place_pts")

    rules = ffa_rules(stage)

    assert rules.column_keys == ()
    assert rules.requires_placement is True
    assert game_points(FfaGameLine(team_id=1, placement=2, stats={}), rules, 3) == 6.0


def test_rules_read_the_stage_columns() -> None:
    stage = SimpleNamespace(
        ffa_columns=[
            {"key": "kills", "label": "Убийства"},
            {"key": "deaths", "label": "Смерти", "public": False, "better": "lower"},
        ],
        ffa_placement_points=[10, 6, 5],
        ffa_formula="place_pts + kills * 2 - deaths",
    )

    parsed = ffa_rules(stage)

    assert parsed.columns == (
        FfaColumn(key="kills", label="Убийства"),
        FfaColumn(key="deaths", label="Смерти", public=False, better="lower"),
    )
    assert parsed.placement_points == (10.0, 6.0, 5.0)
    assert parsed.requires_placement is True
    assert game_points(FfaGameLine(team_id=1, placement=2, stats={"kills": 3, "deaths": 1}), parsed, 4) == 11.0
```

- [ ] **Шаг 2. Запустить — должен упасть.** `uv run pytest shared/tests/test_ffa_scoring.py -v` из `backend/`.
  Ожидаемо: `ImportError: cannot import name 'FfaColumn' from 'shared.domain.ffa_scoring'` — собирается 0 тестов.

- [ ] **Шаг 3. Реализовать.** Заменить `backend/shared/domain/ffa_scoring.py` целиком (текущее содержимое —
  строки 1–170: `FfaRules(placement_points, score_points)` 39–49, `ffa_rules(stage)` 52–63, `FfaGameLine(..., score)`
  66–70, `normalize_game_lines` 73–109, `_derive_placements` 112–122, `game_points(line, rules)` 125–129,
  `FfaTeamTotals.score` 132–143, `team_totals` 146–169):

```python
"""FFA lobby scoring: validate one game, pay it by the formula, sum the totals.

Pure: no session, no ORM rows. The result writer validates with it, the
standings builder ranks with it and the lobby read renders with it, so the
table a viewer sees and the ``Standing`` rows advancement reads are the same
arithmetic by construction (docs/plans/2026-09-26-ffa-custom-scoring.md §5).

What a game pays is the organizer's own formula over the organizer's own
columns; nothing here knows what a "kill" is.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from shared.domain.ffa_formula import Formula, compile_formula, round_half_up

__all__ = (
    "DEFAULT_COLUMN_KEY",
    "DEFAULT_COLUMN_LABEL",
    "DEFAULT_FORMULA",
    "FFA_MAX_COLUMNS",
    "FFA_MAX_LOBBY_SIZE",
    "FFA_STAT_MAX",
    "FfaColumn",
    "FfaGameLine",
    "FfaResultError",
    "FfaRules",
    "FfaTeamTotals",
    "ffa_rules",
    "game_points",
    "normalize_game_lines",
    "team_totals",
)

#: Toornament's cap on one FFA match; a lobby past it is a data-entry mistake.
FFA_MAX_LOBBY_SIZE = 100
#: A dialog with more inputs than this is a spreadsheet, not a result form.
FFA_MAX_COLUMNS = 10
#: The biggest value a game may record: past it the number is a typo.
FFA_STAT_MAX = 1_000_000_000.0
#: A stage that configured nothing scores exactly what it scored before this
#: feature: one column of raw score, paid one for one.
DEFAULT_COLUMN_KEY = "score"
DEFAULT_COLUMN_LABEL = "Счёт"
DEFAULT_FORMULA = DEFAULT_COLUMN_KEY
#: Float noise must not become a false inequality in a tiebreak (plan §12).
GAME_POINTS_DIGITS = 4


class FfaResultError(ValueError):
    """An invalid game result, carrying the machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FfaColumn:
    """One value the organizer records per team per game."""

    key: str
    label: str
    #: False = the value is the organizer's business: not in the public table
    #: and not in the public API answer.
    public: bool = True
    #: Which way this column ranks when a tiebreak sums it.
    better: Literal["higher", "lower"] = "higher"


@dataclass(frozen=True, slots=True)
class FfaRules:
    columns: tuple[FfaColumn, ...]
    #: Points for 1st, 2nd, ... place, read by the formula as ``place_pts``.
    #: A place past the end scores 0.
    placement_points: tuple[float, ...]
    formula: Formula

    @property
    def requires_placement(self) -> bool:
        """Must every team's place be entered by hand?

        It is a question about the formula, never a separate flag: a flag could
        drift away from the rule it describes.
        """
        return bool(self.formula.names & {"place", "place_pts"})

    @property
    def column_keys(self) -> tuple[str, ...]:
        return tuple(column.key for column in self.columns)


_DEFAULT_COLUMNS = (FfaColumn(key=DEFAULT_COLUMN_KEY, label=DEFAULT_COLUMN_LABEL),)


def ffa_rules(stage: Any | None) -> FfaRules:
    """A stage's scoring from its columns (``Stage.ffa_columns``/``ffa_formula``).

    No stage at all reads as the default block. A stage always carries its own
    columns -- the column default is the score column (plan §3.1) -- so an empty
    list is a legal placement-only league, never "not configured". The columns
    and the formula were validated on write (``FfaScoring``), so a formula that
    does not compile here is corrupt data: it raises rather than silently scoring
    zero.
    """
    if stage is None:
        return FfaRules(
            columns=_DEFAULT_COLUMNS,
            placement_points=(),
            formula=compile_formula(DEFAULT_FORMULA, (DEFAULT_COLUMN_KEY,)),
        )
    columns = tuple(
        FfaColumn(
            key=str(item["key"]),
            label=str(item["label"]),
            public=bool(item.get("public", True)),
            better="lower" if item.get("better") == "lower" else "higher",
        )
        for item in stage.ffa_columns or ()
    )
    return FfaRules(
        columns=columns,
        placement_points=tuple(float(value) for value in stage.ffa_placement_points or ()),
        formula=compile_formula(stage.ffa_formula, [column.key for column in columns]),
    )


@dataclass(frozen=True, slots=True)
class FfaGameLine:
    team_id: int
    placement: int | None
    #: The raw values entered for this team in this game, by column key.
    stats: Mapping[str, float]


def normalize_game_lines(
    lines: Iterable[FfaGameLine],
    participant_ids: Iterable[int],
    rules: FfaRules,
) -> tuple[FfaGameLine, ...]:
    """Validate one game; return its lines, best place first, every place set."""
    expected = set(participant_ids)
    given = list(lines)
    keys = set(rules.column_keys)
    seen: set[int] = set()
    for item in given:
        if item.team_id not in expected:
            raise FfaResultError("ffa_result_unknown_team", f"Team {item.team_id} is not in this lobby")
        if item.team_id in seen:
            raise FfaResultError("ffa_result_duplicate_team", f"Team {item.team_id} is listed twice")
        seen.add(item.team_id)
        _check_stats(item, keys)
    missing = expected - seen
    if missing:
        raise FfaResultError("ffa_result_missing_team", f"No result for teams {sorted(missing)}")

    placements = [item.placement for item in given if item.placement is not None]
    if placements and len(placements) != len(given):
        raise FfaResultError("ffa_result_mixed_placement", "Give a place for every team or for none")
    if not placements:
        if rules.requires_placement:
            raise FfaResultError(
                "ffa_result_placement_required", "This stage scores placement: give every team's place"
            )
        return _derive_placements(given, rules)

    size = len(given)
    if any(place < 1 or place > size for place in placements):
        raise FfaResultError("ffa_result_invalid_placement", f"Places must be between 1 and {size}")
    if rules.requires_placement and sorted(placements) != list(range(1, size + 1)):
        raise FfaResultError("ffa_result_invalid_placement", "Each place from 1 to N must be taken exactly once")
    return tuple(sorted(given, key=lambda item: (item.placement or 0, item.team_id)))


def _check_stats(line: FfaGameLine, keys: set[str]) -> None:
    """Exactly the stage's columns, each a finite number in range."""
    for key, value in line.stats.items():
        if key not in keys:
            raise FfaResultError("ffa_result_unknown_stat", f"Team {line.team_id}: this stage has no column `{key}`")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= FFA_STAT_MAX
        ):
            raise FfaResultError(
                "ffa_result_invalid_stat",
                f"Team {line.team_id}: `{key}` must be a number between 0 and {FFA_STAT_MAX:.0f}",
            )
    absent = sorted(keys - set(line.stats))
    if absent:
        raise FfaResultError("ffa_result_missing_stat", f"Team {line.team_id}: no value for {absent}")


def _derive_placements(lines: Sequence[FfaGameLine], rules: FfaRules) -> tuple[FfaGameLine, ...]:
    """Competition ranking by game points: 10, 7, 7, 3 -> 1, 2, 2, 4.

    Points, not a column: the lobby has several columns and only the formula
    says how they compare.
    """
    teams = len(lines)
    scored = sorted(
        ((game_points(item, rules, teams), item) for item in lines),
        key=lambda pair: (-pair[0], pair[1].team_id),
    )
    derived: list[FfaGameLine] = []
    placement = 0
    previous: float | None = None
    for index, (points, item) in enumerate(scored, 1):
        if points != previous:
            placement, previous = index, points
        derived.append(FfaGameLine(team_id=item.team_id, placement=placement, stats=item.stats))
    return tuple(derived)


def game_points(line: FfaGameLine, rules: FfaRules, teams: int) -> float:
    """What this team's game pays, by the stage's formula."""
    place = line.placement or 0
    place_points = rules.placement_points[place - 1] if 1 <= place <= len(rules.placement_points) else 0.0
    values: dict[str, float] = {key: float(value) for key, value in line.stats.items()}
    values["place"] = float(place)
    values["place_pts"] = place_points
    values["teams"] = float(teams)
    return round_half_up(rules.formula.evaluate(values), GAME_POINTS_DIGITS)


@dataclass(slots=True)
class FfaTeamTotals:
    team_id: int
    games: int = 0
    points: float = 0.0
    #: Games finished in 1st place, a shared 1st included.
    wins: int = 0
    #: Every column of the stage summed, zero for a team that has not played.
    stats: dict[str, float] = field(default_factory=dict)
    best_placement: int | None = None
    #: Place in the latest game this team has a result in.
    last_placement: int | None = None


def team_totals(
    team_ids: Iterable[int],
    games: Sequence[Sequence[FfaGameLine]],
    rules: FfaRules,
) -> dict[int, FfaTeamTotals]:
    """Sum confirmed games, oldest first, into one row per team.

    ``team_ids`` seeds a zero row for every participant: the table is the
    roster, not the results, so a team that has not played yet still appears.
    """
    keys = rules.column_keys

    def blank(team_id: int) -> FfaTeamTotals:
        return FfaTeamTotals(team_id=team_id, stats=dict.fromkeys(keys, 0.0))

    totals = {team_id: blank(team_id) for team_id in team_ids}
    for game in games:
        teams = len(game)
        for item in game:
            row = totals.setdefault(item.team_id, blank(item.team_id))
            row.games += 1
            row.points += game_points(item, rules, teams)
            for key, value in item.stats.items():
                row.stats[key] = row.stats.get(key, 0.0) + float(value)
            if item.placement is not None:
                row.wins += item.placement == 1
                row.best_placement = (
                    item.placement if row.best_placement is None else min(row.best_placement, item.placement)
                )
                row.last_placement = item.placement
    # Summing already-rounded games still drifts (0.1 + 0.2); a total that a
    # tiebreak compares must not differ by 1e-13 from an equal one.
    for row in totals.values():
        row.points = round_half_up(row.points, GAME_POINTS_DIGITS)
        row.stats = {key: round_half_up(value, GAME_POINTS_DIGITS) for key, value in row.stats.items()}
    return totals
```

- [ ] **Шаг 4. Запустить — должен пройти.** `uv run pytest shared/tests/test_ffa_scoring.py shared/tests/test_ffa_formula.py -v`
  из `backend/`. Ожидаемо: `52 passed` — 20 в `test_ffa_scoring.py` (10 параметризованных случаев
  `test_a_game_is_refused_...` + 10 остальных) и 32 в `test_ffa_formula.py`.

- [ ] **Шаг 5. Коммит.**
  `git add backend/shared/domain/ffa_scoring.py backend/shared/tests/test_ffa_scoring.py`
  `git commit -m "feat(ffa): score games from organizer columns and the formula"`

---

### Задача 3. Схема настроек `FfaScoring`

**Files:**

- Modify: `backend/tournament-service/src/schemas/stage.py` — импорты (строки 1–7), `__all__` (9–20), класс
  `FfaScoring` (55–71)
- Modify: `backend/shared/rpc/common.py` — `field_entry` (178–189): пробросить `ctx`, иначе позиция ошибки не
  доходит до клиента
- Modify (test): `backend/tournament-service/tests/test_ffa_stage_settings.py` — тело `FfaScoringSchemaTests`
  (31–59) переписывается
- Modify (test): `backend/shared/tests/test_rpc_error_details.py` — добавить один тест в `ValidationDetailTests`
  (после строки 187)

Задача ничего не ломает у соседей: `FfaScoring` — единственный писатель блока, а `_apply_stage_fields`
(`admin/stage.py:127-131`) ломается уже задачей 5 и чинится там же.

**Interfaces:**

- Consumes: `shared.domain.ffa_formula.{FORMULA_MAX_LENGTH, RESERVED_NAMES, FfaFormulaError, compile_formula}`
  (задача 1); `shared.domain.ffa_scoring.{DEFAULT_COLUMN_KEY, DEFAULT_COLUMN_LABEL, DEFAULT_FORMULA,
  FFA_MAX_COLUMNS, FFA_MAX_LOBBY_SIZE}` (задача 2); `pydantic_core.PydanticCustomError`.
- Produces:
  ```python
  COLUMN_KEY_PATTERN: re.Pattern[str]      # [a-z][a-z0-9_]{0,23}
  class FfaColumnSettings(BaseModel):      # extra="forbid"
      key: str; label: str; public: bool = True; better: Literal["higher", "lower"] = "higher"
  class FfaScoring(BaseModel):             # extra="forbid"
      columns: list[FfaColumnSettings]     # default: [{"key": "score", "label": "Счёт"}]
      placement_points: list[float] = []
      formula: str = "score"
  ```
  Оба имени экспортируются через `src.schemas` (`schemas/__init__.py:11` делает `from .stage import *`).

**Как позиция ошибки доходит до клиента.** RPC-обработчик стадии оборачивает вызов в `_run`
(`backend/tournament-service/src/rpc/_helpers.py:76-92`); `except ValidationError` там зовёт
`shared.rpc.common.validation_error` (`backend/shared/rpc/common.py:261-275`), который строит
`details["fields"]` через `field_entry` (`common.py:178-189`). Сегодня `field_entry` кладёт только
`field`/`msg`/`code` — `ctx` теряется, то есть `offset` до фронта не доезжает. Шлюз пишет `details` в тело ответа
как есть (`gateway/internal/apierr/apierr.go:64-80` для v1, `82-93` для v2), поэтому достаточно поправить
`field_entry`. Скалярные ключи `ctx` кладутся **плоско** рядом с `field`/`msg`/`code` — это уже принятая форма
записи с атрибутами: `http_error` делает так же для словаря деталей (`common.py:250-251`, `limit_name`/`scope`/
`limit` у отказов квоты). Итоговое тело 422 (v1):

```json
{"fields": [{"field": "ffa_scoring.formula", "msg": "Unknown name `kils`", "code": "ffa_formula_unknown_name",
             "offset": 12, "name": "kils"}],
 "detail": "Unknown name `kils`", "code": "unprocessable"}
```

(у ошибки из `model_validator` `loc` указывает на сам блок, поэтому `field` = `"ffa_scoring"`; у ошибки ключа
`loc` = `("ffa_scoring", "columns", 0, "key")` → `field` = `"ffa_scoring.columns.0.key"`.) Фронт (задача 12)
читает `entry.offset` и `entry.name`.

Шаги:

- [ ] **Шаг 1. Написать падающий тест.** В `backend/shared/tests/test_rpc_error_details.py` добавить в класс
  `ValidationDetailTests` после `test_body_and_payload_are_stripped_from_the_field_path` (строка 187):

```python
    def test_custom_error_context_rides_the_entry(self) -> None:
        # A ``PydanticCustomError`` carries the position and the offending name in
        # ``ctx``; dropping it leaves a client with a code and nowhere to point.
        entry = field_entry(
            {
                "loc": ("body", "ffa_scoring", "formula"),
                "msg": "unknown name 'kils' at 13",
                "type": "ffa_formula_unknown_name",
                "ctx": {"offset": 13, "name": "kils"},
            }
        )
        self.assertEqual(
            entry,
            {
                "field": "ffa_scoring.formula",
                "msg": "unknown name 'kils' at 13",
                "code": "ffa_formula_unknown_name",
                "offset": 13,
                "name": "kils",
            },
        )

    def test_unserialisable_context_values_are_dropped(self) -> None:
        # ``ValidationError.errors()`` puts the raw exception in ``ctx`` for a plain
        # ``ValueError``; the envelope is JSON, so only scalars may ride along.
        entry = field_entry({"field": "x", "msg": "bad", "code": "value_error", "ctx": {"error": ValueError("boom")}})
        self.assertEqual(entry, {"field": "x", "msg": "bad", "code": "value_error"})
```

  В `backend/tournament-service/tests/test_ffa_stage_settings.py` заменить класс `FfaScoringSchemaTests`
  (строки 31–59) целиком. Удаляемые тесты, пинившие снятое поведение: `test_negative_score_points_are_refused`
  (51–53, поля `score_points` больше нет) и `test_a_stage_edit_carries_the_block_with_its_unsent_defaults`
  (55–59, проверяет `score_label`/`score_points`) — второй переписан под новые дефолты; `test_unknown_ffa_scoring_keys_are_refused`
  (37–41) перестаёт передавать `score_points`. `FfaStageTypeTests` (62–66) не трогаем.

```python
class FfaScoringSchemaTests(TestCase):
    KILLS = {"key": "kills", "label": "Kills"}

    def _reject(self, **block) -> dict:
        with self.assertRaises(pydantic.ValidationError) as ctx:
            schemas.FfaScoring(**block)
        return ctx.exception.errors()[0]

    def test_an_unconfigured_block_is_one_score_column(self) -> None:
        # A stage that never opened the editor must score exactly what it
        # scored before columns existed.
        scoring = schemas.FfaScoring()
        self.assertEqual([("score", "Счёт", True, "higher")], [
            (c.key, c.label, c.public, c.better) for c in scoring.columns
        ])
        self.assertEqual("score", scoring.formula)

    def test_negative_placement_points_are_refused(self) -> None:
        # A negative place reward means finishing higher can cost points.
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(columns=[self.KILLS], formula="kills", placement_points=[10, -1])

    def test_unknown_ffa_scoring_keys_are_refused(self) -> None:
        # The object is closed: a typo'd key would otherwise be accepted and
        # silently score nothing.
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(columns=[self.KILLS], formula="kills", score_points=1)

    def test_a_placement_table_longer_than_a_lobby_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(columns=[self.KILLS], formula="kills", placement_points=[1.0] * (FFA_MAX_LOBBY_SIZE + 1))

    def test_a_full_length_placement_table_is_accepted(self) -> None:
        scoring = schemas.FfaScoring(
            columns=[self.KILLS], formula="kills", placement_points=[1.0] * FFA_MAX_LOBBY_SIZE
        )
        self.assertEqual(FFA_MAX_LOBBY_SIZE, len(scoring.placement_points))

    def test_a_column_key_must_be_a_usable_identifier(self) -> None:
        self.assertEqual("ffa_column_key_invalid", self._reject(columns=[{"key": "Kills", "label": "K"}], formula="1")["type"])
        self.assertEqual("ffa_column_key_invalid", self._reject(columns=[{"key": "", "label": "K"}], formula="1")["type"])

    def test_a_column_may_not_shadow_a_formula_word(self) -> None:
        for key in ("place", "place_pts", "teams", "min", "round", "if", "if_", "not"):
            self.assertEqual(
                "ffa_column_key_reserved", self._reject(columns=[{"key": key, "label": "K"}], formula="1")["type"], key
            )

    def test_duplicate_and_too_many_columns_are_refused(self) -> None:
        duplicate = self._reject(columns=[{"key": "k", "label": "A"}, {"key": "k", "label": "B"}], formula="k")
        self.assertEqual("ffa_column_duplicate", duplicate["type"])
        self.assertEqual("k", duplicate["ctx"]["name"])
        too_many = self._reject(columns=[{"key": f"c{i}", "label": "x"} for i in range(FFA_MAX_COLUMNS + 1)], formula="1")
        self.assertEqual("ffa_columns_too_many", too_many["type"])

    def test_a_blank_label_is_refused(self) -> None:
        self.assertEqual("string_too_short", self._reject(columns=[{"key": "k", "label": "   "}], formula="k")["type"])

    def test_a_broken_formula_is_not_saved_and_carries_its_position(self) -> None:
        unknown = self._reject(columns=[self.KILLS], formula="place_pts + kils")
        self.assertEqual("ffa_formula_unknown_name", unknown["type"])
        self.assertEqual({"offset": 12, "name": "kils"}, unknown["ctx"])

        unsupported = self._reject(columns=[self.KILLS], formula="kills ** 2")
        self.assertEqual("ffa_formula_unsupported", unsupported["type"])
        self.assertEqual(0, unsupported["ctx"]["offset"])

        self.assertEqual("ffa_formula_syntax", self._reject(columns=[self.KILLS], formula="kills +")["type"])

    def test_a_formula_reading_a_column_that_is_not_there_is_refused(self) -> None:
        # The pair is validated together: a column renamed without touching the
        # formula must not be storable.
        error = self._reject(columns=[self.KILLS], formula="kills + deaths")
        self.assertEqual(("ffa_formula_unknown_name", "deaths"), (error["type"], error["ctx"]["name"]))

    def test_a_configured_block_round_trips(self) -> None:
        scoring = schemas.StageUpdate(
            ffa_scoring={
                "columns": [
                    {"key": "kills", "label": " Убийства "},
                    {"key": "deaths", "label": "Смерти", "public": False, "better": "lower"},
                ],
                "placement_points": [10, 7, 5],
                "formula": "place_pts + kills * 2 - deaths",
            }
        ).ffa_scoring
        self.assertEqual("Убийства", scoring.columns[0].label)
        self.assertEqual((False, "lower"), (scoring.columns[1].public, scoring.columns[1].better))
        self.assertEqual([10.0, 7.0, 5.0], scoring.placement_points)
```

  и заменить строку 28 (`from shared.domain.ffa_scoring import FFA_MAX_LOBBY_SIZE  # noqa: E402`) на:

```python
from shared.domain.ffa_scoring import FFA_MAX_COLUMNS, FFA_MAX_LOBBY_SIZE  # noqa: E402
```

- [ ] **Шаг 2. Запустить — должен упасть.**
  `uv run pytest tournament-service/tests/test_ffa_stage_settings.py shared/tests/test_rpc_error_details.py -v` из `backend/`.
  Ожидаемо: задачи 2 и 3 идут подряд, поэтому `FFA_MAX_COLUMNS` уже существует и падают сами проверки:
  в `test_ffa_stage_settings.py` — `pydantic_core.ValidationError: 1 validation error for FfaScoring / columns
  Extra inputs are not permitted` в каждом новом тесте (поля `columns`/`formula` у схемы ещё нет, а
  `extra="forbid"` их отвергает), и `AttributeError: 'FfaScoring' object has no attribute 'columns'` в
  `test_an_unconfigured_block_is_one_score_column`; в `test_rpc_error_details.py` — `AssertionError` в
  `test_custom_error_context_rides_the_entry` (в записи нет `offset`/`name`), а
  `test_unserialisable_context_values_are_dropped` уже зелёный.

- [ ] **Шаг 3. Реализовать `field_entry`.** В `backend/shared/rpc/common.py` заменить строки 178–189:

```python
def field_entry(item: dict[str, Any]) -> dict[str, Any]:
    """One ``details["fields"]`` entry from an error item.

    Accepts both dialects that reach here: ``ApiExc`` items (``msg``/``code``,
    sometimes ``field``) and pydantic items (``loc``/``msg``/``type``).
    """
    field = _loc_path(item.get("loc")) or item.get("field")
    return {
        "field": str(field) if field else None,
        "msg": str(item.get("msg") or "invalid value"),
        "code": str(item.get("code") or item.get("type") or "error"),
    }
```

на:

```python
def field_entry(item: dict[str, Any]) -> dict[str, Any]:
    """One ``details["fields"]`` entry from an error item.

    Accepts both dialects that reach here: ``ApiExc`` items (``msg``/``code``,
    sometimes ``field``) and pydantic items (``loc``/``msg``/``type``).

    ``ctx`` from a ``PydanticCustomError`` is merged in flat, scalars only -- the
    same shape ``http_error`` gives an attribute bag: the code says *what* is
    wrong and the context says *where* (the FFA formula errors carry a 0-based
    ``offset`` the stage editor points at). Non-scalars are dropped: pydantic's
    own ``value_error`` context holds the ``ValueError`` instance, which would
    make the envelope unserializable.
    """
    field = _loc_path(item.get("loc")) or item.get("field")
    entry = {
        "field": str(field) if field else None,
        "msg": str(item.get("msg") or "invalid value"),
        "code": str(item.get("code") or item.get("type") or "error"),
    }
    ctx = item.get("ctx")
    if isinstance(ctx, dict):
        entry.update(
            {
                key: value
                for key, value in ctx.items()
                if key not in entry and (value is None or isinstance(value, (str, int, float, bool)))
            }
        )
    return entry
```

- [ ] **Шаг 4. Реализовать схему.** В `backend/tournament-service/src/schemas/stage.py` заменить строки 1–7:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.domain.ffa_scoring import FFA_MAX_LOBBY_SIZE
from src.core import enums
from src.schemas.base import BaseRead
```

на:

```python
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from shared.domain.ffa_formula import FORMULA_MAX_LENGTH, RESERVED_NAMES, FfaFormulaError, compile_formula
from shared.domain.ffa_scoring import (
    DEFAULT_COLUMN_KEY,
    DEFAULT_COLUMN_LABEL,
    DEFAULT_FORMULA,
    FFA_MAX_COLUMNS,
    FFA_MAX_LOBBY_SIZE,
)
from src.core import enums
from src.schemas.base import BaseRead
```

  В `__all__` (строки 9–20) добавить `"FfaColumnSettings",` сразу перед строкой 17 (`"FfaScoring",`).

  Заменить строки 55–71 (весь класс `FfaScoring` с полями `placement_points`/`score_points`/`score_label` и
  валидатором `_non_negative`) на:

```python
#: A column key is a formula identifier, so it is spelled like one and short
#: enough to type: a lowercase letter, then letters, digits or underscores.
COLUMN_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,23}")


class FfaColumnSettings(BaseModel):
    """One value an ffa_league stage records per team per game."""

    model_config = ConfigDict(extra="forbid")

    key: str
    #: The organizer's word for it ("Kills", "Убийства"): each stage has its
    #: own, so it is data, not a translation key.
    label: str = Field(min_length=1, max_length=32)
    #: False = viewers see neither the column nor its values (plan §2).
    public: bool = True
    better: Literal["higher", "lower"] = "higher"

    @field_validator("label", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("key")
    @classmethod
    def _usable_key(cls, value: str) -> str:
        if not COLUMN_KEY_PATTERN.fullmatch(value):
            raise PydanticCustomError(
                "ffa_column_key_invalid",
                "A column key is up to 24 characters: a lowercase letter, then letters, digits or _",
                {"name": value},
            )
        if value in RESERVED_NAMES:
            raise PydanticCustomError(
                "ffa_column_key_reserved", "`{name}` is a word the formula language owns", {"name": value}
            )
        return value


class FfaScoring(BaseModel):
    """What an ffa_league stage records and what it pays for it (plan §3.1).

    Inert on any other stage type. The unset block is the behaviour a stage had
    before columns existed: one raw score column paid one for one.
    """

    model_config = ConfigDict(extra="forbid")

    columns: list[FfaColumnSettings] = Field(default_factory=lambda: [_default_column()])
    #: Points for 1st, 2nd, ... place, read by the formula as ``place_pts``.
    placement_points: list[float] = Field(default_factory=list, max_length=FFA_MAX_LOBBY_SIZE)
    formula: str = Field(default=DEFAULT_FORMULA, min_length=1, max_length=FORMULA_MAX_LENGTH)

    @field_validator("placement_points")
    @classmethod
    def _non_negative(cls, value: list[float]) -> list[float]:
        if any(points < 0 for points in value):
            raise ValueError("placement points cannot be negative")
        return value

    @field_validator("columns")
    @classmethod
    def _distinct(cls, value: list[FfaColumnSettings]) -> list[FfaColumnSettings]:
        if len(value) > FFA_MAX_COLUMNS:
            raise PydanticCustomError(
                "ffa_columns_too_many", "A stage has at most {limit} columns", {"limit": FFA_MAX_COLUMNS}
            )
        seen: set[str] = set()
        for column in value:
            if column.key in seen:
                raise PydanticCustomError("ffa_column_duplicate", "`{name}` is listed twice", {"name": column.key})
            seen.add(column.key)
        return value

    @model_validator(mode="after")
    def _formula_compiles(self) -> FfaScoring:
        """Columns and formula are one rule: neither is valid without the other.

        The error the parser raises is re-raised with its own code and its
        position in ``ctx``, so the editor can underline the character instead
        of showing "invalid".
        """
        try:
            compile_formula(self.formula, [column.key for column in self.columns])
        except FfaFormulaError as exc:
            raise PydanticCustomError(exc.code, str(exc), {"offset": exc.offset, "name": exc.name}) from exc
        return self


def _default_column() -> FfaColumnSettings:
    return FfaColumnSettings(key=DEFAULT_COLUMN_KEY, label=DEFAULT_COLUMN_LABEL)
```

- [ ] **Шаг 5. Запустить — должен пройти.**
  `uv run pytest tournament-service/tests/test_ffa_stage_settings.py shared/tests/test_rpc_error_details.py -v`
  из `backend/`. Ожидаемо: `test_ffa_stage_settings.py` — `13 passed`; `test_rpc_error_details.py` — все прежние
  тесты плюс `test_custom_error_context_rides_the_entry` и `test_unserialisable_context_values_are_dropped`, ни
  одного падения (существующие `test_message_is_a_summary_not_the_repr` и
  `test_body_and_payload_are_stripped_from_the_field_path` сверяют записи по равенству и не меняются: у
  `missing`/`int_parsing` в pydantic 2 `ctx` отсутствует).

- [ ] **Шаг 6. Коммит.**
  `git add backend/tournament-service/src/schemas/stage.py backend/shared/rpc/common.py backend/tournament-service/tests/test_ffa_stage_settings.py backend/shared/tests/test_rpc_error_details.py`
  `git commit -m "feat(ffa): validate the stage's columns and formula on write"`

---

### Задача 4. Тай-брейки `ffa_stat:<key>`

**Files:**

- Modify: `backend/tournament-service/src/services/standings/service.py` — импорт (15), пресет `ffa_default`
  (60–66), `KNOWN_TIEBREAK_METRICS` (73–88), `RankedStageTeam` (104–107), `normalize_tiebreak_order` (203–225),
  `_tiebreak_order` (228–236), `_metric_value` (270–280), `_build_ffa_stage_standings` (749–763)
- Modify (test): `backend/tournament-service/tests/_stage_regulation.py` — строки 28–30
- Modify (test): `backend/tournament-service/tests/test_standings_ranking.py` — класс `FfaTiebreakTests` (133–185)
- Modify (test): `backend/tournament-service/tests/test_ffa_standings.py` — строки 33–35, 44–50, 64–77 и
  утверждения, читающие `score`

Что задача ломает у соседей (лечит задача 5): `_stage_regulation.py` перестаёт отдавать `ffa_score_points` /
`ffa_score_label` и начинает отдавать `ffa_columns` / `ffa_formula`, поэтому
`tests/test_standings_serialization.py:50-52` (`models.Stage(**stage_regulation())`) падает до того, как задача 5
добавит эти колонки модели, а `tests/test_ffa_results_integration.py:59,61,856` (`{"ffa_score_points": 1}`) —
до задачи 6. Тесты самой задачи 4 проходят.

**Interfaces:**

- Consumes: `shared.domain.ffa_scoring.{FfaGameLine, FfaRules, FfaTeamTotals, ffa_rules, team_totals}` (задача 2);
  у стадии — `stage.ffa_columns`, `stage.ffa_placement_points`, `stage.ffa_formula`, `stage.tiebreak_order`.
- Produces:
  ```python
  FFA_STAT_PREFIX = "ffa_stat:"
  RULE_PRESET_DEFAULTS["ffa_default"] = ["points", "ffa_game_wins", "ffa_last_placement"]
  KNOWN_TIEBREAK_METRICS                      # без "ffa_score"
  RankedStageTeam.ffa_stats: dict[str, float] # вместо ffa_score: int
  def normalize_tiebreak_order(metrics, *, ffa_columns: typing.Sequence[str] = ()) -> list[str]: ...
  def _tiebreak_order(stage: models.Stage, *, rules: FfaRules | None = None) -> list[str]: ...
  ```

Шаги:

- [ ] **Шаг 1. Написать падающий тест.** В `backend/tournament-service/tests/_stage_regulation.py` заменить
  строки 28–30:

```python
        "ffa_placement_points": [],
        "ffa_score_points": 1.0,
        "ffa_score_label": None,
```

на:

```python
        "ffa_placement_points": [],
        "ffa_columns": [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}],
        "ffa_formula": "score",
```

  В `backend/tournament-service/tests/test_standings_ranking.py` заменить класс `FfaTiebreakTests` (строки
  133–185) целиком. Удаляемые тесты, пинившие снятую метрику: `test_every_ffa_metric_survives_normalization`
  (141–143, перечисляет `ffa_score`) и `test_ffa_score_and_game_wins_rank_higher_first` (167–175) — оба переписаны
  под `ffa_stat:<key>`; `test_an_ffa_league_stage_defaults_to_the_ffa_preset` (177–185) переписан под новый пресет.

```python
class FfaTiebreakTests(TestCase):
    """Plan §5.4: the lobby metrics, and what "no games yet" ranks as."""

    ORDER = ["points", "ffa_last_placement"]

    def test_ffa_metrics_are_known_and_garbage_is_still_dropped(self) -> None:
        self.assertEqual(["ffa_game_wins"], service.normalize_tiebreak_order(["ffa_game_wins", "bogus"]))

    def test_every_built_in_ffa_metric_survives_normalization(self) -> None:
        metrics = ["ffa_game_wins", "ffa_best_placement", "ffa_last_placement"]
        self.assertEqual(metrics, service.normalize_tiebreak_order(metrics))

    def test_a_column_metric_survives_only_while_its_column_exists(self) -> None:
        # The order is stored as text; deleting a column must not leave a
        # tiebreaker that scores every team 0 -- indistinguishable from one
        # that fired and separated nobody.
        order = ["points", "ffa_stat:kills"]
        self.assertEqual(order, service.normalize_tiebreak_order(order, ffa_columns=["kills", "deaths"]))
        self.assertEqual(["points"], service.normalize_tiebreak_order(order, ffa_columns=["deaths"]))
        self.assertEqual(["points"], service.normalize_tiebreak_order(order))

    def test_the_retired_ffa_score_metric_is_dropped(self) -> None:
        self.assertEqual([], service.normalize_tiebreak_order(["ffa_score"], ffa_columns=["score"]))

    def test_a_better_last_placement_breaks_a_points_tie(self) -> None:
        # Lower place is better, and the sort is descending -- the metric must
        # invert, or first place would rank below last.
        ordered = service._sort_ranked_teams(
            [_team(1, points=6.0, ffa_last_placement=4), _team(2, points=6.0, ffa_last_placement=1)],
            tiebreak_order=self.ORDER,
        )
        self.assertEqual([2, 1], [team.team_id for team in ordered])

    def test_a_team_with_no_games_ranks_below_every_real_place(self) -> None:
        # `None` is "never played", not "placed 0th": a team the lobby has not
        # seen yet must not win the tiebreak against a team that did play.
        ordered = service._sort_ranked_teams(
            [
                _team(1, points=0.0, ffa_last_placement=None),
                _team(2, points=0.0, ffa_last_placement=9),
                _team(3, points=0.0, ffa_last_placement=2),
            ],
            tiebreak_order=self.ORDER,
        )
        self.assertEqual([3, 2, 1], [team.team_id for team in ordered])

    def test_a_column_sum_and_game_wins_rank_higher_first(self) -> None:
        by_kills = service._sort_ranked_teams(
            [_team(1, ffa_stats={"kills": 12.0}), _team(2, ffa_stats={"kills": 30.0})],
            tiebreak_order=["ffa_stat:kills"],
        )
        by_wins = service._sort_ranked_teams(
            [_team(1, wins=0), _team(2, wins=3)],
            tiebreak_order=["ffa_game_wins"],
        )
        self.assertEqual([2, 1], [team.team_id for team in by_kills])
        self.assertEqual([2, 1], [team.team_id for team in by_wins])

    def test_a_team_with_no_value_for_the_column_ranks_last_on_it(self) -> None:
        ordered = service._sort_ranked_teams(
            [_team(1, ffa_stats={}), _team(2, ffa_stats={"kills": 1.0})],
            tiebreak_order=["ffa_stat:kills"],
        )
        self.assertEqual([2, 1], [team.team_id for team in ordered])

    def test_an_ffa_league_stage_defaults_to_its_first_column(self) -> None:
        stage = SimpleNamespace(
            **stage_regulation(
                ffa_columns=[{"key": "kills", "label": "K"}, {"key": "deaths", "label": "D", "better": "lower"}],
                ffa_formula="kills * 2 - deaths",
            ),
            stage_type=service.StageType.FFA_LEAGUE,
        )
        self.assertEqual("ffa_default", service._rule_profile(stage))
        self.assertEqual(
            ["points", "ffa_game_wins", "ffa_stat:kills", "ffa_last_placement"],
            service._tiebreak_order(stage),
        )
```

  В `backend/tournament-service/tests/test_ffa_standings.py` заменить строки 33–35:

```python
#: Places pay 10/6/4/2 and every point of score pays 1 -- enough for two teams
#: to reach the same total by different routes.
SCORING = {"ffa_placement_points": [10, 6, 4, 2], "ffa_score_points": 1}
```

на:

```python
#: Places pay 10/6/4/2 and every kill pays 1 -- enough for two teams to reach
#: the same total by different routes. ``deaths`` is the hidden column the
#: direction test ranks by: fewer is better.
SCORING = {
    "ffa_placement_points": [10, 6, 4, 2],
    "ffa_columns": [
        {"key": "kills", "label": "Kills"},
        {"key": "deaths", "label": "Deaths", "public": False, "better": "lower"},
    ],
    "ffa_formula": "place_pts + kills",
}
```

  заменить строки 44–50 (`_stage`) на:

```python
def _stage(**overrides: object) -> SimpleNamespace:
    return SimpleNamespace(
        **stage_regulation(**{**SCORING, **overrides}),
        id=7,
        stage_type=StageType.FFA_LEAGUE,
        order=1,
    )
```

  заменить строки 64–77 (`_game` и `GAMES`) на:

```python
def _game(rows: list[tuple[int, int, int, int]]) -> tuple[FfaGameLine, ...]:
    return tuple(
        FfaGameLine(team_id=team_id, placement=placement, stats={"kills": kills, "deaths": deaths})
        for team_id, placement, kills, deaths in rows
    )


#: Two games of a four-team lobby.
#:
#: A and B both finish on 20: A by winning twice for nothing, B by placing
#: second twice with four kills each. C and D share third place in both games
#: and trade the same two kill counts -- no metric in ``ffa_default`` can
#: separate them, but D dies less.
GAMES = [
    _game([(TEAM_A, 1, 0, 1), (TEAM_B, 2, 4, 1), (TEAM_C, 3, 0, 2), (TEAM_D, 3, 2, 0)]),
    _game([(TEAM_A, 1, 0, 1), (TEAM_B, 2, 4, 1), (TEAM_C, 3, 2, 2), (TEAM_D, 3, 0, 0)]),
]
```

  в `test_teams_no_metric_separated_share_a_tie_group` заменить комментарий и утверждение (строки 103–104):

```python
        # C and D: same points, same wins, same raw score, same last place.
        self.assertEqual([None, None, 3, 3], [row.tie_group for row in standings])
```

на:

```python
        # C and D: same points, same wins, same kills, same last place. Deaths
        # separate them, but the default order does not look at them.
        self.assertEqual([None, None, 3, 3], [row.tie_group for row in standings])
```

  и добавить в конец класса `FfaStageStandingsTests` (после строки 170) новый тест направления:

```python
    def test_a_lower_is_better_column_ranks_the_smaller_sum_first(self) -> None:
        # C and D are equal on everything the default order knows; an explicit
        # order by the hidden "deaths" column has to put the team that died
        # less (D, 0) above the one that died more (C, 4).
        standings = standings_service._build_ffa_stage_standings(
            _tournament(),
            _stage(tiebreak_order=["points", "ffa_game_wins", "ffa_stat:deaths"]),
            _item([TEAM_A, TEAM_B, TEAM_C, TEAM_D]),
            [TEAM_A, TEAM_B, TEAM_C, TEAM_D],
            GAMES,
        )

        self.assertEqual([TEAM_A, TEAM_B, TEAM_D, TEAM_C], [row.team_id for row in standings])
        self.assertEqual([None, None, None, None], [row.tie_group for row in standings])
```

- [ ] **Шаг 2. Запустить — должен упасть.**
  `uv run pytest tournament-service/tests/test_standings_ranking.py tournament-service/tests/test_ffa_standings.py -v`
  из `backend/`. Ожидаемо (задачи 2–4 идут подряд, поэтому `ffa_rules`/`team_totals` уже новые):
  в `test_standings_ranking.py` —
  `TypeError: normalize_tiebreak_order() got an unexpected keyword argument 'ffa_columns'` в
  `test_a_column_metric_survives_only_while_its_column_exists`;
  `AssertionError: Lists differ: [2, 1] != [1, 2]` в `test_a_column_sum_and_game_wins_rank_higher_first` и
  `test_a_team_with_no_value_for_the_column_ranks_last_on_it` (метрики `ffa_stat:` ещё нет, `_metric_value`
  возвращает 0 и остаётся откат по `team_id`);
  `AssertionError: ['points', 'ffa_game_wins', 'ffa_score', 'ffa_last_placement'] != ['points', 'ffa_game_wins',
  'ffa_stat:kills', 'ffa_last_placement']` в `test_an_ffa_league_stage_defaults_to_its_first_column`;
  `AssertionError: Lists differ: ['ffa_score'] != []` в `test_the_retired_ffa_score_metric_is_dropped`
  (метрика ещё в `KNOWN_TIEBREAK_METRICS`).
  В `test_ffa_standings.py` — `AttributeError: 'FfaTeamTotals' object has no attribute 'score'` из
  `standings/service.py:756` (`ffa_score=row.score`) во всех восьми тестах.

- [ ] **Шаг 3. Реализовать.** В `backend/tournament-service/src/services/standings/service.py`:

  (а) строка 15 — заменить

```python
from shared.domain.ffa_scoring import FfaGameLine, ffa_rules, team_totals
```

  на

```python
from shared.domain.ffa_scoring import FfaGameLine, FfaRules, FfaTeamTotals, ffa_rules, team_totals
```

  (б) строки 60–66 — заменить пресет

```python
    "ffa_default": [
        "points",
        "ffa_game_wins",
        "ffa_score",
        "ffa_last_placement",
    ],
}
```

  на

```python
    # The stage's own headline column is spliced in by ``_tiebreak_order``: it
    # is not a fixed metric name, it depends on what the organizer configured.
    "ffa_default": [
        "points",
        "ffa_game_wins",
        "ffa_last_placement",
    ],
}

#: A tiebreak by the sum of one stage column: ``ffa_stat:kills``. The key after
#: the prefix is an organizer's column key, so it is validated against the
#: stage, not against a fixed list.
FFA_STAT_PREFIX = "ffa_stat:"
```

  (в) строки 83–86 внутри `KNOWN_TIEBREAK_METRICS` — удалить `"ffa_score",` (строка 84); остаётся

```python
        "ffa_game_wins",
        "ffa_best_placement",
        "ffa_last_placement",
```

  (г) строки 104–105 в `RankedStageTeam` — заменить

```python
    #: FFA only: raw score summed and placement metrics (plan §5.3).
    ffa_score: int = 0
```

  на

```python
    #: FFA only: every stage column summed, already oriented so that more is
    #: better (plan §5.4), plus the placement metrics below.
    ffa_stats: dict[str, float] = field(default_factory=dict)
```

  (д) строки 203–225 — заменить сигнатуру и фильтр `normalize_tiebreak_order`:

```python
def normalize_tiebreak_order(metrics: typing.Iterable[typing.Any]) -> list[str]:
```

  на

```python
def normalize_tiebreak_order(
    metrics: typing.Iterable[typing.Any], *, ffa_columns: typing.Sequence[str] = ()
) -> list[str]:
```

  в докстроке после строки 214 (`      metric can never separate teams the first pass left equal.`) добавить абзац:

```python

    ``ffa_stat:<key>`` is known only while the stage still has that column:
    deleting a column must not leave a tiebreaker that scores every team 0.
```

  и заменить тело (строки 219–225):

```python
    ordered: list[str] = []
    for metric in metrics:
        if not isinstance(metric, str) or metric not in KNOWN_TIEBREAK_METRICS:
            continue
        if metric not in ordered:
            ordered.append(metric)
    return ordered
```

  на

```python
    columns = {f"{FFA_STAT_PREFIX}{key}" for key in ffa_columns}
    ordered: list[str] = []
    for metric in metrics:
        if not isinstance(metric, str) or (metric not in KNOWN_TIEBREAK_METRICS and metric not in columns):
            continue
        if metric not in ordered:
            ordered.append(metric)
    return ordered
```

  (е) строки 228–236 — заменить `_tiebreak_order` целиком:

```python
def _tiebreak_order(stage: models.Stage) -> list[str]:
    if stage.tiebreak_order is not None:
        normalized = normalize_tiebreak_order(stage.tiebreak_order)
        # A stored list with nothing the engine knows would rank by team id alone.
        if normalized:
            return normalized
    return normalize_tiebreak_order(
        RULE_PRESET_DEFAULTS.get(_rule_profile(stage), RULE_PRESET_DEFAULTS["bracket_default"])
    )
```

  на

```python
def _tiebreak_order(stage: models.Stage, *, rules: FfaRules | None = None) -> list[str]:
    """``rules`` is passed by the FFA builder, which already compiled them."""
    if rules is None and stage.stage_type == StageType.FFA_LEAGUE:
        rules = ffa_rules(stage)
    columns = rules.column_keys if rules is not None else ()
    if stage.tiebreak_order is not None:
        normalized = normalize_tiebreak_order(stage.tiebreak_order, ffa_columns=columns)
        # A stored list with nothing the engine knows would rank by team id alone.
        if normalized:
            return normalized
    profile = _rule_profile(stage)
    preset = RULE_PRESET_DEFAULTS.get(profile, RULE_PRESET_DEFAULTS["bracket_default"])
    if profile == "ffa_default" and columns:
        # The stage's first column is its headline stat: "most kills wins the
        # tie" is what an organizer means by an unconfigured FFA league.
        preset = [*preset[:2], f"{FFA_STAT_PREFIX}{columns[0]}", *preset[2:]]
    return normalize_tiebreak_order(preset, ffa_columns=columns)
```

  (ж) строки 272–273 в `_metric_value` — заменить

```python
    if metric == "ffa_score":
        return team.ffa_score
```

  на

```python
    if metric.startswith(FFA_STAT_PREFIX):
        # Already oriented by ``_ranking_stats``; a team with no value for the
        # column reads as 0, which is what "has not played" sums to anyway.
        return team.ffa_stats.get(metric[len(FFA_STAT_PREFIX) :], 0.0)
```

  (з) строки 749–763 в `_build_ffa_stage_standings` — заменить

```python
    totals = team_totals(seed_ids, games, ffa_rules(stage))
    teams = [
        RankedStageTeam(
            team_id=row.team_id,
            matches=row.games,
            wins=row.wins,
            points=row.points,
            ffa_score=row.score,
            ffa_best_placement=row.best_placement,
            ffa_last_placement=row.last_placement,
        )
        for row in totals.values()
    ]
    order = _tiebreak_order(stage)
```

  на

```python
    rules = ffa_rules(stage)
    totals = team_totals(seed_ids, games, rules)
    teams = [
        RankedStageTeam(
            team_id=row.team_id,
            matches=row.games,
            wins=row.wins,
            points=row.points,
            ffa_stats=_ranking_stats(row, rules),
            ffa_best_placement=row.best_placement,
            ffa_last_placement=row.last_placement,
        )
        for row in totals.values()
    ]
    order = _tiebreak_order(stage, rules=rules)
```

  и добавить помощника прямо перед `def _build_ffa_stage_standings(` (то есть перед строкой 730):

```python
def _ranking_stats(row: FfaTeamTotals, rules: FfaRules) -> dict[str, float]:
    """Column sums oriented so that more is better for every key.

    ``_metric_value`` sorts descending, so a ``better="lower"`` column (deaths,
    penalties) is negated here rather than inside the sort -- exactly what
    ``ffa_last_placement`` does, and for the same reason.
    """
    return {
        column.key: -row.stats.get(column.key, 0.0) if column.better == "lower" else row.stats.get(column.key, 0.0)
        for column in rules.columns
    }


```

- [ ] **Шаг 4. Запустить — должен пройти.**
  `uv run pytest tournament-service/tests/test_standings_ranking.py tournament-service/tests/test_ffa_standings.py -v`
  из `backend/`. Ожидаемо: `test_standings_ranking.py` — `28 passed` (сейчас 26: `FfaTiebreakTests` растёт с 6 до
  8 тестов); `test_ffa_standings.py` — `8 passed` (сейчас 7).
  (`tournament-service/tests/test_bracket_engine_tournament72.py:325` зовёт `normalize_tiebreak_order` одним
  позиционным аргументом — новый keyword-only параметр имеет значение по умолчанию, этот вызов не меняется;
  проверить: `uv run pytest tournament-service/tests/test_bracket_engine_tournament72.py -q` — прежний результат.)

- [ ] **Шаг 5. Коммит.**
  `git add backend/tournament-service/src/services/standings/service.py backend/tournament-service/tests/_stage_regulation.py backend/tournament-service/tests/test_standings_ranking.py backend/tournament-service/tests/test_ffa_standings.py`
  `git commit -m "feat(ffa): tiebreak by any FFA column sum"`

---

---

## Раздел B. Хранение, сервис FFA, правка стадии, шлюз (задачи 5–8)

Контекст раздела. Первая редакция спеки была написана до коммита `35416163`
(«store stage regulation in columns»), который удалил `tournament.stage.settings_json`: миграция
`stjson01_stage_settings_columns.py:187` дропает колонку, а регламент стадии живёт в типизированных колонках
(`shared/models/tournament/stage.py:104-132`). Главный агент подтвердил новую форму хранения (см. «Отклонения от
контракта» в конце файла): блок API по-прежнему называется `ffa_scoring`, но лежит в колонках
`stage.ffa_columns jsonb` + `stage.ffa_formula varchar(500)` + существующей `stage.ffa_placement_points float8[]`.
Функция домена сохраняет имя и сигнатуру `ffa_rules(stage)` (не `parse_ffa_rules(settings)`).

Голова цепочки alembic на сегодня — `stjson01` (`backend/migrations/versions/stjson01_stage_settings_columns.py:39`);
никакая ревизия не ссылается на неё как на `down_revision`.

Задачи 5–8 выходят одним релизом с задачами 1–4 и 9–14. Промежуточный коммит ломает соседей — это нормально и
отмечено в каждой задаче отдельно; тесты самой задачи обязаны проходить.

Все команды бэкенда выполняются из каталога `backend/`. Интеграционные тесты берут `db_session`
(`shared/testing/db.py:259`), который сам поднимает `docker-compose.test.yml` и прогоняет `alembic upgrade head`,
когда `POSTGRES_*` указывают на закреплённую в репозитории заглушку `127.0.0.1:55432/anak_test`
(`shared/testing/db.py:86-117,159-168`). Поэтому в командах достаточно `TEST_POSTGRES_DOCKER=1`: остальные
`POSTGRES_*` имеют ровно эти значения по умолчанию. Если база уже поднята и мигрирована — переменная ничего не
меняет.

---

### Задача 5. Миграция `ffa0002`, `EncounterGameResult.stats`, колонки стадии и репозиторий

**Files:**

- Create: `backend/migrations/versions/ffa0002_game_result_stats.py`
- Modify: `backend/shared/models/tournament/encounter_game_result.py:1-41` (докстринг 1-8, импорты 12-13,
  `__table_args__` 23-35, колонка 41)
- Modify: `backend/shared/models/tournament/stage.py:3-15` (импорты), `:69-76` (`__table_args__`),
  `:125-130` (ffa-колонки), `:161-167` (property `ffa_scoring`)
- Modify: `backend/shared/repository/encounter.py:148-208` (`EncounterGameResultRepository`)
- Modify: `backend/tournament-service/src/services/admin/stage.py:127-131` (`_apply_stage_fields`)
- Modify: `backend/tournament-service/tests/_stage_regulation.py:16-32`
- Tests: `backend/tournament-service/tests/test_ffa_schema_integration.py` (правка сырых вставок 196-201, 215-221;
  новые тесты CHECK и `stat_keys_for_stage`)

**Interfaces:**

- Consumes: `shared.domain.ffa_scoring.FfaGameLine(team_id, placement, stats)` — задача 2;
  `src.schemas.stage.FfaScoring(columns, placement_points, formula)` — задача 3.
- Produces:
  - `EncounterGameResult.stats: Mapped[dict]` (JSONB, NOT NULL, server_default `'{}'::jsonb`);
    CHECK `ck_encounter_game_result_stats` = `jsonb_typeof(stats) = 'object'`; колонки `score` больше нет.
  - `Stage.ffa_columns: Mapped[list[dict]]` (JSONB, NOT NULL, server_default — один столбец `score`),
    `Stage.ffa_formula: Mapped[str]` (varchar(500), NOT NULL, server_default `score`);
    `Stage.ffa_score_points` / `Stage.ffa_score_label` и CHECK `ck_stage_ffa_score_points` удалены.
  - `Stage.ffa_scoring` (property) → `{"columns": list[dict], "placement_points": list[float], "formula": str}`.
  - `EncounterGameResultRepository.stat_keys_for_stage(session, stage_id: int) -> set[str]`.
  - Ревизия alembic `ffa0002`, `down_revision = "stjson01"`.

Задача ломает соседей до конца релиза: `shared/domain/ffa_scoring.ffa_rules` (задача 2, приземляется раньше) уже
читает `stage.ffa_columns`/`ffa_formula`, а `src/services/encounter/ffa.py` и `src/rpc/ffa.py` до задачи 6 ещё
строят `FfaGameLine(..., score=...)` и читают `row.score` — `test_ffa_results_integration.py` в этом коммите
красный, это чинит задача 6.

- [ ] **Шаг 1. Написать падающие тесты схемы.** В `backend/tournament-service/tests/test_ffa_schema_integration.py`
  перевести сырые вставки на `stats` и добавить две гарантии: CHECK на форму `stats` и запрос ключей по стадии.

  Заменить `test_ffa_schema_integration.py:77-87` (`_lobby` не умеет класть лобби в стадию):

  ```python
  async def _stage(session: Any, tournament_id: int) -> int:
      return (
          await session.execute(
              sa.text(
                  "insert into tournament.stage (tournament_id, name, stage_type, \"order\") "
                  "values (:t, 'Lobbies', 'ffa_league', 1) returning id"
              ),
              {"t": tournament_id},
          )
      ).scalar_one()


  async def _lobby(session: Any, tournament_id: int, stage_id: int | None = None) -> int:
      return (
          await session.execute(
              sa.text(
                  "insert into tournament.encounter (name, format, home_score, away_score, round, best_of, "
                  "tournament_id, stage_id, status, result_status) values ('Lobby', 'ffa', 0, 0, 1, 3, :t, :s, "
                  "'OPEN', 'none') returning id"
              ),
              {"t": tournament_id, "s": stage_id},
          )
      ).scalar_one()
  ```

  Заменить сырую вставку результата в `test_a_result_belongs_to_a_participant_of_the_same_lobby`
  (`test_ffa_schema_integration.py:196-201`):

  ```python
                  await db_session.execute(
                      sa.text(
                          "insert into tournament.encounter_game_result "
                          "(game_id, encounter_id, team_id, placement, stats) "
                          "values (:g, :e, :t, 1, '{\"score\": 5}'::jsonb)"
                      ),
                      {"g": game, "e": lobby, "t": teams[2]},
                  )
  ```

  И ту же вставку в `test_deleting_the_lobby_removes_participants_games_and_results`
  (`test_ffa_schema_integration.py:215-221`):

  ```python
              await db_session.execute(
                  sa.text(
                      "insert into tournament.encounter_game_result "
                      "(game_id, encounter_id, team_id, placement, stats) "
                      "values (:g, :e, :t, 1, '{\"score\": 5}'::jsonb)"
                  ),
                  {"g": game, "e": lobby, "t": teams[0]},
              )
  ```

  Добавить в конец файла (после `test_deleting_the_lobby_removes_participants_games_and_results`,
  `test_ffa_schema_integration.py:234`):

  ```python
  def test_a_result_row_refuses_stats_that_are_not_an_object(db_session) -> None:
      """The formula reads ``stats`` by key: a number or an array there is not a
      value the engine could misread, it is a row no reader can use at all."""

      async def _run() -> None:
          workspace_id, tournament_id, teams = await _seed(db_session)
          try:
              lobby = await _lobby(db_session, tournament_id)
              await _participant(db_session, lobby, teams[0], 1)
              game = await _ffa_game(db_session, lobby)
              with pytest.raises(IntegrityError):
                  await db_session.execute(
                      sa.text(
                          "insert into tournament.encounter_game_result "
                          "(game_id, encounter_id, team_id, placement, stats) values (:g, :e, :t, 1, '7'::jsonb)"
                      ),
                      {"g": game, "e": lobby, "t": teams[0]},
                  )
          finally:
              await _drop(db_session, workspace_id)

      asyncio.run(_run())


  def test_stat_keys_of_a_stage_skip_cancelled_games(db_session) -> None:
      """What the stage editor asks before it removes a column: which keys have
      values behind them. A cancelled game is history, not a value in play."""

      async def _run() -> set[str]:
          workspace_id, tournament_id, teams = await _seed(db_session)
          try:
              stage_id = await _stage(db_session, tournament_id)
              lobby = await _lobby(db_session, tournament_id, stage_id)
              await _participant(db_session, lobby, teams[0], 1)
              live = await _ffa_game(db_session, lobby)
              await db_session.execute(
                  sa.text(
                      "insert into tournament.encounter_game_result "
                      "(game_id, encounter_id, team_id, placement, stats) "
                      "values (:g, :e, :t, 1, '{\"kills\": 4, \"deaths\": 1}'::jsonb)"
                  ),
                  {"g": live, "e": lobby, "t": teams[0]},
              )
              cancelled = await _ffa_game(db_session, lobby)
              await db_session.execute(
                  sa.text("update tournament.encounter_game set state = 'cancelled', position = 2 where id = :g"),
                  {"g": cancelled},
              )
              await db_session.execute(
                  sa.text(
                      "insert into tournament.encounter_game_result "
                      "(game_id, encounter_id, team_id, placement, stats) "
                      "values (:g, :e, :t, 1, '{\"penalty\": 2}'::jsonb)"
                  ),
                  {"g": cancelled, "e": lobby, "t": teams[0]},
              )
              await db_session.commit()
              return await EncounterGameResultRepository().stat_keys_for_stage(db_session, stage_id)
          finally:
              await _drop(db_session, workspace_id)

      assert asyncio.run(_run()) == {"kills", "deaths"}
  ```

  Добавить импорт рядом с остальными (после `test_ffa_schema_integration.py:30`):

  ```python
  from shared.repository.encounter import EncounterGameResultRepository  # noqa: E402
  ```

  И дописать в докстринг файла (`test_ffa_schema_integration.py:3-7`) после «…and the two cascades.»:
  «…and the one query the stage editor asks of the result rows.»

- [ ] **Шаг 2. Прогнать — падает.**

  ```
  cd backend && TEST_POSTGRES_DOCKER=1 uv run pytest tournament-service/tests/test_ffa_schema_integration.py -v
  ```

  Ожидаемо: `test_a_result_belongs_to_a_participant_of_the_same_lobby`,
  `test_deleting_the_lobby_removes_participants_games_and_results`,
  `test_a_result_row_refuses_stats_that_are_not_an_object` падают с
  `psycopg.errors.UndefinedColumn: column "stats" of relation "encounter_game_result" does not exist`;
  `test_stat_keys_of_a_stage_skip_cancelled_games` — `ImportError`/`AttributeError`:
  `EncounterGameResultRepository` не имеет `stat_keys_for_stage`.

- [ ] **Шаг 3. Написать миграцию `ffa0002`.** Новый файл
  `backend/migrations/versions/ffa0002_game_result_stats.py` (стиль и блок замков — копия
  `ffa0001_encounter_format_participants.py:21-59`):

  ```python
  """FFA scoring: per-game ``stats jsonb``, and a stage's own columns + formula.

  The organizer now decides what a game records and what it pays: the single
  ``encounter_game_result.score`` integer becomes a free ``stats`` object, and the
  stage's ``ffa_score_points``/``ffa_score_label`` pair becomes ``ffa_columns``
  (what is entered per game) plus ``ffa_formula`` (the expression over them).
  Every existing stage keeps the arithmetic it had: one ``score`` column and the
  formula those two numbers spelled out.

  ``encounter_result_audit.ffa_results_json`` is left alone -- it is history, and
  new rows are written in the new shape.

  Revision ID: ffa0002
  Revises: stjson01
  """

  from __future__ import annotations

  import json
  import re
  import time
  from collections.abc import Sequence

  import sqlalchemy as sa
  from alembic import op
  from sqlalchemy.dialects import postgresql
  from sqlalchemy.exc import OperationalError

  # Annotated form on purpose: scripts/export_erd.py finds the chain's head with
  # ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
  revision: str = "ffa0002"
  down_revision: str | Sequence[str] | None = "stjson01"
  branch_labels: str | Sequence[str] | None = None
  depends_on: str | Sequence[str] | None = None

  RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})
  LOCK_TIMEOUT = "3s"
  LOCK_ATTEMPTS = 40
  LOCK_BACKOFF_SECONDS = 6.0
  _EXCLUSIVE = "tournament.encounter_game_result, tournament.stage"

  #: A stage that configured nothing: one "score" column, points = score.
  DEFAULT_COLUMNS = [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}]
  DEFAULT_FORMULA = "score"
  _DEFAULT_COLUMNS_SQL = json.dumps(DEFAULT_COLUMNS, ensure_ascii=False)

  #: The only formulas ``ffa_score_points`` can express again on the way back.
  _REVERSIBLE_FORMULA = re.compile(r"^(?:place_pts \+ )?score(?: \* (?P<k>[0-9]+(?:\.[0-9]+)?))?$")


  def _take_locks() -> None:
      """Take every lock this revision needs, before it changes anything.

      Each attempt is its own SAVEPOINT: a cancelled or deadlocked statement
      aborts the transaction alembic wraps the migration in, and rolling the
      savepoint back both restores that transaction and releases whatever locks
      the attempt did get. ``SET LOCAL`` is issued outside the savepoint so a
      rollback does not also roll back the timeout.
      """
      bind = op.get_bind()
      bind.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
      for attempt in range(1, LOCK_ATTEMPTS + 1):
          savepoint = bind.begin_nested()
          try:
              bind.execute(sa.text(f"LOCK TABLE {_EXCLUSIVE} IN ACCESS EXCLUSIVE MODE"))
          except OperationalError as exc:
              savepoint.rollback()
              if getattr(exc.orig, "sqlstate", None) not in RETRYABLE_SQLSTATES or attempt == LOCK_ATTEMPTS:
                  raise
              time.sleep(LOCK_BACKOFF_SECONDS)
          else:
              savepoint.commit()
              return


  def _multiplier(points: float) -> str:
      """``score_points`` as the tail of the formula; 1 pays for no ``* 1``."""
      return "" if points == 1 else f" * {points:g}"


  def upgrade() -> None:
      _take_locks()
      bind = op.get_bind()

      # ── results: one integer -> the organizer's object ────────────────────
      op.add_column(
          "encounter_game_result",
          sa.Column("stats", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
          schema="tournament",
      )
      op.execute("UPDATE tournament.encounter_game_result SET stats = jsonb_build_object('score', score)")
      op.drop_constraint("ck_encounter_game_result_score", "encounter_game_result", schema="tournament")
      op.drop_column("encounter_game_result", "score", schema="tournament")
      op.create_check_constraint(
          "ck_encounter_game_result_stats",
          "encounter_game_result",
          "jsonb_typeof(stats) = 'object'",
          schema="tournament",
      )

      # ── stage: score_points/score_label -> columns + formula ──────────────
      op.add_column(
          "stage",
          sa.Column(
              "ffa_columns",
              postgresql.JSONB(),
              nullable=False,
              server_default=sa.text(f"'{_DEFAULT_COLUMNS_SQL}'::jsonb"),
          ),
          schema="tournament",
      )
      op.add_column(
          "stage",
          sa.Column("ffa_formula", sa.String(500), nullable=False, server_default=DEFAULT_FORMULA),
          schema="tournament",
      )
      # A Python loop, not one UPDATE: the formula depends on both numbers and on
      # whether the multiplier is worth writing at all, and ffa_league stages are
      # counted in single digits.
      for stage_id, placement_points, score_points, score_label in bind.execute(
          sa.text(
              "SELECT id, ffa_placement_points, ffa_score_points, ffa_score_label "
              "FROM tournament.stage WHERE stage_type = 'ffa_league'"
          )
      ).all():
          columns = [
              {
                  "key": "score",
                  "label": (score_label or "").strip() or "Счёт",
                  "public": True,
                  "better": "higher",
              }
          ]
          tail = _multiplier(float(1 if score_points is None else score_points))
          formula = f"place_pts + score{tail}" if placement_points else f"score{tail}"
          bind.execute(
              sa.text(
                  "UPDATE tournament.stage SET ffa_columns = CAST(:columns AS jsonb), ffa_formula = :formula "
                  "WHERE id = :id"
              ),
              {"columns": json.dumps(columns, ensure_ascii=False), "formula": formula, "id": stage_id},
          )

      op.drop_constraint("ck_stage_ffa_score_points", "stage", schema="tournament")
      op.drop_column("stage", "ffa_score_points", schema="tournament")
      op.drop_column("stage", "ffa_score_label", schema="tournament")

      # ── the tiebreak metric that named the removed column ─────────────────
      op.execute(
          "UPDATE tournament.stage SET tiebreak_order = array_replace(tiebreak_order, 'ffa_score', 'ffa_stat:score') "
          "WHERE tiebreak_order IS NOT NULL AND 'ffa_score' = ANY(tiebreak_order)"
      )


  def downgrade() -> None:
      _take_locks()
      bind = op.get_bind()

      # Every refusal is checked BEFORE the first DDL: a downgrade that cannot be
      # expressed with score_points must leave the database exactly as it was.
      restore: dict[int, tuple[float, str | None]] = {}
      for stage_id, columns, formula in bind.execute(
          sa.text("SELECT id, ffa_columns, ffa_formula FROM tournament.stage WHERE stage_type = 'ffa_league'")
      ).all():
          keys = [column.get("key") for column in (columns or [])]
          if keys != ["score"]:
              raise RuntimeError(f"stage {stage_id} scores by {keys}; downgrade would drop those columns")
          match = _REVERSIBLE_FORMULA.match((formula or "").strip())
          if match is None:
              raise RuntimeError(f"stage {stage_id} pays by {formula!r}; ffa_score_points cannot express it")
          label = (columns[0].get("label") or "").strip()
          restore[stage_id] = (float(match.group("k") or 1), None if label in ("", "Счёт") else label)

      stray = bind.execute(
          sa.text("SELECT count(*) FROM tournament.encounter_game_result WHERE stats - 'score' <> '{}'::jsonb")
      ).scalar()
      if stray:
          raise RuntimeError(f"{stray} FFA results hold stats other than 'score'; downgrade would drop them")

      op.add_column(
          "stage",
          sa.Column("ffa_score_points", sa.Float(), nullable=False, server_default="1"),
          schema="tournament",
      )
      op.add_column("stage", sa.Column("ffa_score_label", sa.String(32), nullable=True), schema="tournament")
      op.create_check_constraint("ck_stage_ffa_score_points", "stage", "ffa_score_points >= 0", schema="tournament")
      for stage_id, (points, label) in restore.items():
          bind.execute(
              sa.text("UPDATE tournament.stage SET ffa_score_points = :points, ffa_score_label = :label WHERE id = :id"),
              {"points": points, "label": label, "id": stage_id},
          )
      op.drop_column("stage", "ffa_formula", schema="tournament")
      op.drop_column("stage", "ffa_columns", schema="tournament")
      op.execute(
          "UPDATE tournament.stage SET tiebreak_order = array_replace(tiebreak_order, 'ffa_stat:score', 'ffa_score') "
          "WHERE tiebreak_order IS NOT NULL AND 'ffa_stat:score' = ANY(tiebreak_order)"
      )

      op.add_column(
          "encounter_game_result",
          sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
          schema="tournament",
      )
      op.execute(
          "UPDATE tournament.encounter_game_result SET score = COALESCE(round((stats ->> 'score')::numeric), 0)::int"
      )
      op.drop_constraint("ck_encounter_game_result_stats", "encounter_game_result", schema="tournament")
      op.drop_column("encounter_game_result", "stats", schema="tournament")
      op.create_check_constraint(
          "ck_encounter_game_result_score", "encounter_game_result", "score >= 0", schema="tournament"
      )
  ```

- [ ] **Шаг 4. Перевести модели на новые колонки.**

  `backend/shared/models/tournament/encounter_game_result.py` — заменить строки 1-8 (докстринг), 12-13 (импорты),
  26 (CHECK) и 41 (колонка).

  Было (`encounter_game_result.py:3-5`):

  ```python
  ``placement`` is always stored: when the stage's formula pays nothing for
  placement it is derived from ``score`` (ties share a place), so "games won" and
  "best placement" mean the same for a score-only lobby and a battle royale.
  ```

  Стало (докстринг целиком, строки 1-8):

  ```python
  """One participant's result in one FFA lobby game.

  ``stats`` is what the organizer's columns collected for this team in this game
  (``{"kills": 12, "deaths": 3}``); the points it pays are never stored -- the
  stage's formula computes them on every read (plan §2). ``placement`` is always
  stored: when the formula pays nothing for placement it is derived from the
  game's points (ties share a place), so "games won" and "best placement" mean
  the same for a score-only lobby and a battle royale. The composite FK to the
  participant makes a result for a team outside the lobby impossible.
  """
  ```

  Было (`encounter_game_result.py:12-13`):

  ```python
  from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, UniqueConstraint
  from sqlalchemy.orm import Mapped, mapped_column
  ```

  Стало:

  ```python
  from sqlalchemy import (
      BigInteger,
      CheckConstraint,
      ForeignKey,
      ForeignKeyConstraint,
      Index,
      Integer,
      UniqueConstraint,
      text,
  )
  from sqlalchemy.dialects.postgresql import JSONB
  from sqlalchemy.orm import Mapped, mapped_column
  ```

  Было (`encounter_game_result.py:26`):

  ```python
          CheckConstraint("score >= 0", name="ck_encounter_game_result_score"),
  ```

  Стало:

  ```python
          CheckConstraint("jsonb_typeof(stats) = 'object'", name="ck_encounter_game_result_stats"),
  ```

  Было (`encounter_game_result.py:41`):

  ```python
      score: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
  ```

  Стало:

  ```python
      #: The organizer's columns for this team in this game; a key the stage does
      #: not have is simply absent, and an absent key reads as 0 (plan §3.2).
      stats: Mapped[dict[str, float]] = mapped_column(
          JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
      )
  ```

  (`JSONB` без `with_variant`: это принятая в репозитории форма —
  `shared/models/tournament/encounter_result_audit.py:78`, — а для SQLite-стендов зарегистрирован шим
  `shared/testing/sqlite_dialect.py:37-39`. FFA-результаты ни один SQLite-набор не пишет.)

  `backend/shared/models/tournament/stage.py` — четыре правки.

  Было (`stage.py:16`):

  ```python
  from sqlalchemy.dialects.postgresql import ARRAY
  ```

  Стало:

  ```python
  from sqlalchemy.dialects.postgresql import ARRAY, JSONB
  ```

  Было (`stage.py:74`):

  ```python
          CheckConstraint("ffa_score_points >= 0", name="ck_stage_ffa_score_points"),
  ```

  Стало: строку удалить (проверку заменяет схема `FfaScoring` задачи 3 — она компилирует формулу, а не сравнивает
  число).

  Было (`stage.py:125-130`):

  ```python
      #: FFA league only: points for 1st, 2nd, ... place; empty = score-only.
      ffa_placement_points: Mapped[list[float]] = mapped_column(_FLOAT_ARRAY, default=list, server_default="{}")
      #: FFA league only: points per unit of raw score.
      ffa_score_points: Mapped[float] = mapped_column(Float(), default=1.0, server_default="1")
      #: FFA league only: the organizer's word for the score column ("Kills").
      ffa_score_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
  ```

  Стало:

  ```python
      #: FFA league only: points for 1st, 2nd, ... place; empty = the formula
      #: pays nothing for placement.
      ffa_placement_points: Mapped[list[float]] = mapped_column(_FLOAT_ARRAY, default=list, server_default="{}")
      #: FFA league only: what the organizer enters per game -- ``{"key", "label",
      #: "public", "better"}`` per column, validated by ``FfaScoring`` (plan §3.1).
      ffa_columns: Mapped[list[dict[str, typing.Any]]] = mapped_column(
          JSONB,
          default=lambda: [dict(column) for column in DEFAULT_FFA_COLUMNS],
          server_default=text(_DEFAULT_FFA_COLUMNS_SQL),
      )
      #: FFA league only: the expression a game's points are computed with.
      ffa_formula: Mapped[str] = mapped_column(
          String(500), default=DEFAULT_FFA_FORMULA, server_default=DEFAULT_FFA_FORMULA
      )
  ```

  И рядом с `_TEXT_ARRAY`/`_FLOAT_ARRAY` (после `stage.py:30`) добавить константы и импорт `text`
  (в блок `from sqlalchemy import (...)`, `stage.py:3-15`, добавить строку `text,` после `String,`):

  ```python
  #: What an ffa_league stage pays for until the organizer says otherwise: one
  #: column called "score", and points = that column. Mirrors migration ffa0002.
  DEFAULT_FFA_COLUMNS: tuple[dict[str, typing.Any], ...] = (
      {"key": "score", "label": "Счёт", "public": True, "better": "higher"},
  )
  DEFAULT_FFA_FORMULA = "score"
  _DEFAULT_FFA_COLUMNS_SQL = (
      """'[{"key": "score", "label": "Счёт", "public": true, "better": "higher"}]'::jsonb"""
  )
  ```

  Было (`stage.py:161-167`):

  ```python
      @property
      def ffa_scoring(self) -> dict[str, typing.Any]:
          return {
              "placement_points": list(self.ffa_placement_points or ()),
              "score_points": self.ffa_score_points,
              "score_label": self.ffa_score_label,
          }
  ```

  Стало:

  ```python
      @property
      def ffa_scoring(self) -> dict[str, typing.Any]:
          """The ``ffa_scoring`` block of the API, rebuilt from the columns.

          An empty column list is a placement-only league and is shown as such;
          only a stage not yet flushed (column still ``None``, the server default
          not applied) reads the default block.
          """
          return {
              "columns": [
                  dict(column)
                  for column in (self.ffa_columns if self.ffa_columns is not None else DEFAULT_FFA_COLUMNS)
              ],
              "placement_points": list(self.ffa_placement_points or ()),
              "formula": self.ffa_formula or DEFAULT_FFA_FORMULA,
          }
  ```

  Если после удаления `ffa_score_points` в файле больше нет ни одного `Float()`-столбца — оставить импорт `Float`:
  он нужен `_FLOAT_ARRAY` (`stage.py:30`) и `win_points`/`draw_points`/`loss_points` (`stage.py:111-113`).

- [ ] **Шаг 5. Перевести репозиторий на `stats` и добавить `stat_keys_for_stage`.**

  Было (`backend/shared/repository/encounter.py:162-171`):

  ```python
          session.add_all(
              models.EncounterGameResult(
                  game_id=game.id,
                  encounter_id=game.encounter_id,
                  team_id=line.team_id,
                  placement=line.placement,
                  score=line.score,
              )
              for line in lines
          )
  ```

  Стало:

  ```python
          session.add_all(
              models.EncounterGameResult(
                  game_id=game.id,
                  encounter_id=game.encounter_id,
                  team_id=line.team_id,
                  placement=line.placement,
                  stats={key: float(value) for key, value in line.stats.items()},
              )
              for line in lines
          )
  ```

  Было (`backend/shared/repository/encounter.py:192`):

  ```python
                  models.EncounterGameResult.score,
  ```

  Стало:

  ```python
                  models.EncounterGameResult.stats,
  ```

  Добавить после `list_confirmed_for_stage` (`encounter.py:208`):

  ```python
      async def stat_keys_for_stage(self, session: AsyncSession, stage_id: int) -> set[str]:
          """Every stat key a live game of ``stage_id`` holds a value for.

          What the stage editor asks before it drops a column: a key with values
          behind it is a record of the tournament, not a setting (plan §6).
          Cancelled games are excluded for the same reason their cells read as
          unplayed -- they are history the table no longer counts.
          """
          keys = sa.func.jsonb_object_keys(models.EncounterGameResult.stats).label("key")
          result = await session.execute(
              sa.select(keys)
              .join(models.EncounterGame, models.EncounterGame.id == models.EncounterGameResult.game_id)
              .join(models.Encounter, models.Encounter.id == models.EncounterGameResult.encounter_id)
              .where(
                  models.Encounter.stage_id == stage_id,
                  models.EncounterGame.state != enums.EncounterGameState.CANCELLED,
              )
              .distinct()
          )
          return set(result.scalars())
  ```

- [ ] **Шаг 6. Перевести запись настроек стадии и тестовую фикстуру регламента.**

  Было (`backend/tournament-service/src/services/admin/stage.py:127-131`):

  ```python
      if "ffa_scoring" in fields:
          ffa_scoring = fields.pop("ffa_scoring")
          stage.ffa_placement_points = list(ffa_scoring["placement_points"])
          stage.ffa_score_points = ffa_scoring["score_points"]
          stage.ffa_score_label = ffa_scoring["score_label"]
  ```

  Стало:

  ```python
      if "ffa_scoring" in fields:
          ffa_scoring = fields.pop("ffa_scoring")
          stage.ffa_columns = [dict(column) for column in ffa_scoring["columns"]]
          stage.ffa_placement_points = list(ffa_scoring["placement_points"])
          stage.ffa_formula = ffa_scoring["formula"]
  ```

  Было (`backend/tournament-service/tests/_stage_regulation.py:28-30`):

  ```python
          "ffa_placement_points": [],
          "ffa_score_points": 1.0,
          "ffa_score_label": None,
  ```

  Стало:

  ```python
          "ffa_placement_points": [],
          "ffa_columns": [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}],
          "ffa_formula": "score",
  ```

- [ ] **Шаг 7. Прогнать — проходит.**

  ```
  cd backend && TEST_POSTGRES_DOCKER=1 uv run pytest tournament-service/tests/test_ffa_schema_integration.py -v
  ```

  Ожидаемо: 8 passed (шесть прежних тестов + `test_a_result_row_refuses_stats_that_are_not_an_object` +
  `test_stat_keys_of_a_stage_skip_cancelled_games`). Фикстура `db_session` сама прогоняет
  `alembic upgrade head`, то есть применяет `ffa0002`.

- [ ] **Шаг 8. Проверить обратный ход миграции вручную.**

  ```
  cd backend && DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/anak_test uv run alembic downgrade -1
  cd backend && DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/anak_test uv run alembic upgrade head
  ```

  Ожидаемо: `downgrade` проходит на базе, где все ffa-стадии остались в форме `[score]` (её оставляет сам
  `upgrade`), возвращает `score`/`ffa_score_points`/`ffa_score_label`; повторный `upgrade` снова даёт `ffa0002`.
  Отказ проверяется руками на копии: задать стадии `ffa_formula = 'kills * 2'` и убедиться, что `downgrade`
  падает с `RuntimeError: stage <id> scores by ['kills']; downgrade would drop those columns`.

- [ ] **Шаг 9. Коммит.**

  ```
  git add backend/migrations/versions/ffa0002_game_result_stats.py \
          backend/shared/models/tournament/encounter_game_result.py \
          backend/shared/models/tournament/stage.py \
          backend/shared/repository/encounter.py \
          backend/tournament-service/src/services/admin/stage.py \
          backend/tournament-service/tests/_stage_regulation.py \
          backend/tournament-service/tests/test_ffa_schema_integration.py
  git commit -m "feat(ffa): store per-game stats and the stage's columns and formula"
  ```

---

### Задача 6. FFA-сервис: запись и чтение через `stats`, `public_view`, админское чтение RPC

**Files:**

- Modify: `backend/tournament-service/src/schemas/ffa.py:22-31` (`__all__`), `:34-37` (вход),
  `:53-56` (`FfaRulesRead`), `:59-65` (`FfaGameCellRead`), `:68-83` (`FfaLobbyRowRead`)
- Modify: `backend/tournament-service/src/services/encounter/ffa.py:36-45` (импорты домена),
  `:57-62` (импорты схем), `:68` (`__all__`), `:212` (снимок журнала), `:378` (строки стадии),
  `:463-470` (правила чтения), `:501` (строки лобби), `:592` (итог строки), `:616-631` (`_read_cell`),
  `:665-673` (`_snapshot`), `:684` (`_confirmed_games`), + новая модульная `public_view`
- Modify: `backend/tournament-service/src/rpc/ffa.py:78-100` (публичные чтения), `:127` (строка ввода),
  + новый подписчик `rpc.tournament.ffa_stage_admin`
- Tests: `backend/tournament-service/tests/test_ffa_results_integration.py`
  (`:58-61`, `:137-142`, `:247`, `:260`, `:332-339`, `:545-585`, `:855-908` + новые тесты)

**Interfaces:**

- Consumes: `shared.domain.ffa_scoring` — `FfaGameLine(team_id, placement, stats)`, `FfaRules.columns`
  (`FfaColumn(key, label, public, better)`), `FfaRules.formula.source`, `FfaRules.requires_placement`,
  `game_points(line, rules, teams) -> float`, `team_totals(...) -> dict[int, FfaTeamTotals]` с
  `FfaTeamTotals.stats: dict[str, float]` (задача 2); `EncounterGameResult.stats` (задача 5).
- Produces:
  - `src.schemas.ffa.FfaGameResultLineInput{team_id, placement, stats}`,
    `FfaColumnRead{key, label, public, better}`,
    `FfaRulesRead{columns, placement_points, formula, requires_placement}`,
    `FfaGameCellRead{position, state, placement, points, stats}`,
    `FfaLobbyRowRead{..., stats}`;
  - `src.services.encounter.ffa.public_view(lobby: FfaLobbyRead) -> FfaLobbyRead`;
  - RPC-субъект `rpc.tournament.ffa_stage_admin` (ответ — список полного `FfaLobbyRead`);
  - снимок журнала `{"team_id", "placement", "stats"}`.

Задача чинит `test_ffa_results_integration.py`, сломанный задачами 2 и 5, и ломает шлюз до задачи 8: субъекта
`rpc.tournament.ffa_stage_admin` ещё нет ни в одном маршруте — доступен он станет только с задачей 8.

- [ ] **Шаг 1. Переписать тесты записи и чтения под `stats` (падают).**
  `backend/tournament-service/tests/test_ffa_results_integration.py`.

  Было (`:58-61`):

  ```python
  #: Score-only: a point per elimination, places derived from the scoreboard.
  SCORING = {"ffa_score_points": 1}
  #: Battle-royale style: 1st place pays 10, 2nd 6, 3rd 4, plus a point per score.
  PLACEMENT_SCORING = {"ffa_placement_points": [10, 6, 4], "ffa_score_points": 1}
  ```

  Стало:

  ```python
  #: One "score" column, no placement points: places derive from the scoreboard.
  SCORE_COLUMN = [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}]
  SCORING = {"ffa_columns": SCORE_COLUMN, "ffa_formula": "score"}
  #: Battle-royale style: 1st place pays 10, 2nd 6, 3rd 4, plus a point per score.
  PLACEMENT_SCORING = {
      "ffa_placement_points": [10, 6, 4],
      "ffa_columns": SCORE_COLUMN,
      "ffa_formula": "place_pts + score",
  }
  #: Two columns, one of them hidden from viewers, and a formula over both.
  KILLS_DEATHS = {
      "ffa_columns": [
          {"key": "kills", "label": "Kills", "public": True, "better": "higher"},
          {"key": "deaths", "label": "Deaths", "public": False, "better": "lower"},
      ],
      "ffa_formula": "kills * 2 - deaths",
  }
  ```

  Было (`:137-142`):

  ```python
  def _lines(team_ids: list[int], scores: list[int], placements: list[int | None] | None = None) -> list[FfaGameLine]:
      places = placements or [None] * len(team_ids)
      return [
          FfaGameLine(team_id=team_id, placement=place, score=score)
          for team_id, place, score in zip(team_ids, places, scores, strict=True)
      ]
  ```

  Стало:

  ```python
  def _lines(team_ids: list[int], scores: list[int], placements: list[int | None] | None = None) -> list[FfaGameLine]:
      places = placements or [None] * len(team_ids)
      return [
          FfaGameLine(team_id=team_id, placement=place, stats={"score": score})
          for team_id, place, score in zip(team_ids, places, scores, strict=True)
      ]


  def _stat_lines(team_ids: list[int], stats: list[dict[str, float]]) -> list[FfaGameLine]:
      return [
          FfaGameLine(team_id=team_id, placement=None, stats=values)
          for team_id, values in zip(team_ids, stats, strict=True)
      ]
  ```

  Было (`:247` и `:260`):

  ```python
                          "select team_id, placement, score from tournament.encounter_game_result "
  ```
  ```python
      assert rows == [(team_ids[0], 1, 10), (team_ids[1], 2, 7), (team_ids[2], 2, 7)]
  ```

  Стало:

  ```python
                          "select team_id, placement, stats from tournament.encounter_game_result "
  ```
  ```python
      assert rows == [(team_ids[0], 1, {"score": 10}), (team_ids[1], 2, {"score": 7}), (team_ids[2], 2, {"score": 7})]
  ```

  Было (`:332-339`, снимок журнала правки):

  ```python
          {"team_id": team_ids[0], "placement": 1, "score": 10},
          {"team_id": team_ids[1], "placement": 2, "score": 6},
          {"team_id": team_ids[2], "placement": 3, "score": 2},
  ```
  ```python
          {"team_id": team_ids[1], "placement": 1, "score": 8},
          {"team_id": team_ids[0], "placement": 2, "score": 4},
          {"team_id": team_ids[2], "placement": 3, "score": 1},
  ```

  Стало:

  ```python
          {"team_id": team_ids[0], "placement": 1, "stats": {"score": 10}},
          {"team_id": team_ids[1], "placement": 2, "stats": {"score": 6}},
          {"team_id": team_ids[2], "placement": 3, "stats": {"score": 2}},
  ```
  ```python
          {"team_id": team_ids[1], "placement": 1, "stats": {"score": 8}},
          {"team_id": team_ids[0], "placement": 2, "stats": {"score": 4}},
          {"team_id": team_ids[2], "placement": 3, "stats": {"score": 1}},
  ```

  Было (`:545-585`, таблица отказов; строки 559-563 пинят удалённый код `ffa_result_invalid_score`):

  ```python
          (
              SCORING,
              lambda ids: [FfaGameLine(team_id=team_id, placement=None, score=-1) for team_id in ids],
              "ffa_result_invalid_score",
          ),
  ```

  Стало — этот случай удаляется, вместо него три случая новой проверки значений (§5.2), а остальные строки
  таблицы переводятся на `stats={"score": 1}`:

  ```python
  @pytest.mark.parametrize(
      ("regulation", "build", "code"),
      [
          (
              SCORING,
              lambda ids: [FfaGameLine(team_id=ids[0], placement=None, stats={"score": 1})],
              "ffa_result_missing_team",
          ),
          (
              SCORING,
              lambda ids: [
                  FfaGameLine(team_id=team_id, placement=None, stats={"score": 1}) for team_id in [*ids, ids[0]]
              ],
              "ffa_result_duplicate_team",
          ),
          (
              SCORING,
              lambda ids: [
                  FfaGameLine(team_id=team_id, placement=None, stats={"score": 1}) for team_id in [*ids[:2], -1]
              ],
              "ffa_result_unknown_team",
          ),
          (
              SCORING,
              lambda ids: [FfaGameLine(team_id=team_id, placement=None, stats={"score": -1}) for team_id in ids],
              "ffa_result_invalid_stat",
          ),
          (
              SCORING,
              lambda ids: [
                  FfaGameLine(team_id=team_id, placement=None, stats={"score": 1, "kills": 2}) for team_id in ids
              ],
              "ffa_result_unknown_stat",
          ),
          (
              SCORING,
              lambda ids: [FfaGameLine(team_id=team_id, placement=None, stats={}) for team_id in ids],
              "ffa_result_missing_stat",
          ),
          (
              SCORING,
              lambda ids: [
                  FfaGameLine(team_id=team_id, placement=place, stats={"score": 1})
                  for team_id, place in zip(ids, [1, None, None], strict=True)
              ],
              "ffa_result_mixed_placement",
          ),
          (
              PLACEMENT_SCORING,
              lambda ids: [FfaGameLine(team_id=team_id, placement=None, stats={"score": 1}) for team_id in ids],
              "ffa_result_placement_required",
          ),
          (
              PLACEMENT_SCORING,
              lambda ids: [
                  FfaGameLine(team_id=team_id, placement=place, stats={"score": 1})
                  for team_id, place in zip(ids, [1, 1, 2], strict=True)
              ],
              "ffa_result_invalid_placement",
          ),
      ],
  )
  ```

  Было (`:855-856`):

  ```python
  #: Placement pays, and the organizer named the score column.
  LABELLED_SCORING = {"ffa_placement_points": [10, 6, 4], "ffa_score_points": 1, "ffa_score_label": "Kills"}
  ```

  Стало:

  ```python
  #: Placement pays, and the organizer named the single column.
  LABELLED_SCORING = {
      "ffa_placement_points": [10, 6, 4],
      "ffa_columns": [{"key": "score", "label": "Kills", "public": True, "better": "higher"}],
      "ffa_formula": "place_pts + score",
  }
  ```

  Было (`:886-908`):

  ```python
      assert (lobby.rules.placement_points, lobby.rules.score_points, lobby.rules.score_label) == (
          [10.0, 6.0, 4.0],
          1.0,
          "Kills",
      )
  ```
  ```python
      assert [(row.points, row.games_played, row.wins, row.score) for row in lobby.rows] == [
          (15.0, 1, 1, 5),
          (9.0, 1, 0, 3),
          (5.0, 1, 0, 1),
      ]
  ```
  ```python
      assert [(cell.position, cell.state, cell.placement, cell.score, cell.points) for cell in lobby.rows[0].games] == [
          (1, enums.EncounterGameState.CONFIRMED, 1, 5, 15.0),
          (2, None, None, None, None),
      ]
  ```

  Стало:

  ```python
      assert (lobby.rules.placement_points, lobby.rules.formula, lobby.rules.requires_placement) == (
          [10.0, 6.0, 4.0],
          "place_pts + score",
          True,
      )
      assert [(c.key, c.label, c.public, c.better) for c in lobby.rules.columns] == [
          ("score", "Kills", True, "higher")
      ]
  ```
  ```python
      assert [(row.points, row.games_played, row.wins, row.stats) for row in lobby.rows] == [
          (15.0, 1, 1, {"score": 5}),
          (9.0, 1, 0, {"score": 3}),
          (5.0, 1, 0, {"score": 1}),
      ]
  ```
  ```python
      assert [(cell.position, cell.state, cell.placement, cell.stats, cell.points) for cell in lobby.rows[0].games] == [
          (1, enums.EncounterGameState.CONFIRMED, 1, {"score": 5}, 15.0),
          (2, None, None, None, None),
      ]
  ```

  И три новых теста в конец секции чтений (после
  `test_the_lobby_read_refuses_a_duel_and_an_unknown_encounter`, `:1014`):

  ```python
  def test_a_public_read_carries_no_value_of_a_hidden_column(db_session) -> None:
      """A hidden column is hidden from the API, not merely from the table: not in
      ``rules.columns``, not in a row total, not in a game cell (plan §7.3)."""

      async def _run() -> tuple:
          seeded = await _seed(db_session, games=1, regulation=KILLS_DEATHS)
          try:
              await ffa_encounter_service.set_game_results(
                  db_session,
                  seeded.lobby_id,
                  1,
                  _stat_lines(
                      seeded.team_ids,
                      [{"kills": 6, "deaths": 1}, {"kills": 3, "deaths": 2}, {"kills": 1, "deaths": 4}],
                  ),
                  actor_user_id=None,
                  reason=None,
              )
              full = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
              return full, public_view(full)
          finally:
              await _drop(db_session, seeded)

      full, public = asyncio.run(_run())
      assert [column.key for column in full.rules.columns] == ["kills", "deaths"]
      assert [column.key for column in public.rules.columns] == ["kills"]
      # The rule itself stays readable, hidden key and all: it is a rule, not data.
      assert public.rules.formula == "kills * 2 - deaths"
      assert [row.stats for row in public.rows] == [{"kills": 6}, {"kills": 3}, {"kills": 1}]
      assert [row.stats for row in full.rows] == [
          {"kills": 6, "deaths": 1},
          {"kills": 3, "deaths": 2},
          {"kills": 1, "deaths": 4},
      ]
      assert [cell.stats for cell in public.rows[0].games] == [{"kills": 6}]
      assert [cell.stats for cell in full.rows[0].games] == [{"kills": 6, "deaths": 1}]
      # Points are computed from every column, hidden ones included.
      assert [row.points for row in public.rows] == [11.0, 4.0, -2.0]


  def test_points_and_places_come_from_the_formula(db_session) -> None:
      """No placement points, no places entered: the formula decides the points and
      the points decide the places, ties shared (plan §5.2)."""

      async def _run() -> tuple:
          seeded = await _seed(db_session, games=1, regulation=KILLS_DEATHS)
          try:
              await ffa_encounter_service.set_game_results(
                  db_session,
                  seeded.lobby_id,
                  1,
                  _stat_lines(
                      seeded.team_ids,
                      [{"kills": 2, "deaths": 0}, {"kills": 3, "deaths": 2}, {"kills": 5, "deaths": 4}],
                  ),
                  actor_user_id=None,
                  reason=None,
              )
              lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
              return [(row.team_id, row.points) for row in lobby.rows], [
                  (cell.placement, cell.points) for row in lobby.rows for cell in row.games
              ], seeded.team_ids
          finally:
              await _drop(db_session, seeded)

      totals, cells, team_ids = asyncio.run(_run())
      # kills * 2 - deaths -> 4, 4, 6: the third team wins, the first two share 2nd.
      assert dict(totals) == {team_ids[0]: 4.0, team_ids[1]: 4.0, team_ids[2]: 6.0}
      assert sorted(cells) == [(1, 6.0), (2, 4.0), (2, 4.0)]


  def test_a_game_is_refused_when_the_formula_needs_a_place(db_session) -> None:
      """``requires_placement`` is not a flag the organizer sets, it is what the
      formula reads -- and the read says so to the dialog."""

      async def _run() -> tuple:
          seeded = await _seed(db_session, games=1, regulation=PLACEMENT_SCORING)
          try:
              lobby = await ffa_encounter_service.load_lobby(db_session, seeded.lobby_id)
              with pytest.raises(BaseAPIException) as raised:
                  await ffa_encounter_service.set_game_results(
                      db_session, seeded.lobby_id, 1, _lines(seeded.team_ids, [3, 2, 1]), actor_user_id=None,
                      reason=None,
                  )
              await db_session.rollback()
              return lobby.rules.requires_placement, [item.code for item in raised.value.detail]
          finally:
              await _drop(db_session, seeded)

      assert asyncio.run(_run()) == (True, ["ffa_result_placement_required"])
  ```

  И импорт `public_view` рядом с сервисом (`test_ffa_results_integration.py:54`):

  ```python
  from src.services.encounter.ffa import ffa_encounter_service, public_view  # noqa: E402
  ```

- [ ] **Шаг 2. Прогнать — падает.**

  ```
  cd backend && TEST_POSTGRES_DOCKER=1 uv run pytest tournament-service/tests/test_ffa_results_integration.py -v
  ```

  Ожидаемо: сбор модуля падает — `ImportError: cannot import name 'public_view' from 'src.services.encounter.ffa'`.
  После добавления `public_view` (шаг 4) и до шагов 3/5 падают чтения (`FfaRulesRead` не имеет `columns`) и записи
  (`_snapshot` читает `row.score`).

- [ ] **Шаг 3. Переписать схемы чтения/записи.** `backend/tournament-service/src/schemas/ffa.py`.

  Было (`:22-31`):

  ```python
  __all__ = (
      "FfaGameCancelInput",
      "FfaGameCellRead",
      "FfaGameResultLineInput",
      "FfaGameResultsInput",
      "FfaGamesCountInput",
      "FfaLobbyRead",
      "FfaLobbyRowRead",
      "FfaRulesRead",
  )
  ```

  Стало:

  ```python
  __all__ = (
      "FfaColumnRead",
      "FfaGameCancelInput",
      "FfaGameCellRead",
      "FfaGameResultLineInput",
      "FfaGameResultsInput",
      "FfaGamesCountInput",
      "FfaLobbyRead",
      "FfaLobbyRowRead",
      "FfaRulesRead",
  )
  ```

  Было (`:34-37`):

  ```python
  class FfaGameResultLineInput(BaseModel):
      team_id: int
      placement: int | None = Field(default=None, ge=1)
      score: int = Field(ge=0)
  ```

  Стало:

  ```python
  class FfaGameResultLineInput(BaseModel):
      team_id: int
      placement: int | None = Field(default=None, ge=1)
      #: One value per column of the stage; the service refuses a missing or
      #: unknown key, so the dialog cannot silently drop a column (plan §5.2).
      stats: dict[str, float]
  ```

  Было (`:53-56`):

  ```python
  class FfaRulesRead(BaseModel):
      placement_points: list[float]
      score_points: float
      score_label: str | None
  ```

  Стало:

  ```python
  class FfaColumnRead(BaseModel):
      key: str
      label: str
      #: False — the value is the organizer's, never sent to a public read.
      public: bool
      better: Literal["higher", "lower"]


  class FfaRulesRead(BaseModel):
      #: Public reads carry the public columns only (``public_view``).
      columns: list[FfaColumnRead]
      placement_points: list[float]
      #: The expression points are computed with, as the organizer wrote it.
      formula: str
      #: The formula reads ``place``/``place_pts``, so a game cannot be entered
      #: without places.
      requires_placement: bool
  ```

  Было (`:59-65`):

  ```python
  class FfaGameCellRead(BaseModel):
      position: int
      #: ``None`` — the game has not been opened yet.
      state: enums.EncounterGameState | None
      placement: int | None
      score: int | None
      points: float | None
  ```

  Стало:

  ```python
  class FfaGameCellRead(BaseModel):
      position: int
      #: ``None`` — the game has not been opened yet.
      state: enums.EncounterGameState | None
      placement: int | None
      points: float | None
      #: ``None`` — nothing was entered for this position at all.
      stats: dict[str, float] | None
  ```

  Было (`:82`):

  ```python
      score: int
  ```

  Стало:

  ```python
      #: Per-column sums over the played games.
      stats: dict[str, float]
  ```

  И импорт (`:15-17`):

  ```python
  from datetime import datetime
  from typing import Literal

  from pydantic import BaseModel, Field
  ```

- [ ] **Шаг 4. Перевести сервис на `stats` и добавить `public_view`.**
  `backend/tournament-service/src/services/encounter/ffa.py`.

  Импорты — было (`:57-62`):

  ```python
  from src.schemas.ffa import (
      FfaGameCellRead,
      FfaLobbyRead,
      FfaLobbyRowRead,
      FfaRulesRead,
  )
  ```

  Стало:

  ```python
  from src.schemas.ffa import (
      FfaColumnRead,
      FfaGameCellRead,
      FfaLobbyRead,
      FfaLobbyRowRead,
      FfaRulesRead,
  )
  ```

  Было (`:68`):

  ```python
  __all__ = ("FfaEncounterService", "FfaStageResults", "ffa_encounter_service")
  ```

  Стало:

  ```python
  __all__ = ("FfaEncounterService", "FfaStageResults", "ffa_encounter_service", "public_view")
  ```

  Снимок журнала — было (`:212`):

  ```python
              after=[{"team_id": i.team_id, "placement": i.placement, "score": i.score} for i in normalized],
  ```

  Стало:

  ```python
              after=[
                  {"team_id": i.team_id, "placement": i.placement, "stats": dict(i.stats)} for i in normalized
              ],
  ```

  Строки стадии — было (`:378`):

  ```python
              bucket[-1].append(FfaGameLine(team_id=row.team_id, placement=row.placement, score=row.score))
  ```

  Стало:

  ```python
              bucket[-1].append(FfaGameLine(team_id=row.team_id, placement=row.placement, stats=row.stats))
  ```

  Правила чтения — было (`:463-470`):

  ```python
          rules = ffa_rules(stage)
          # ``score_label`` is presentation, not arithmetic, so it never entered
          # ``FfaRules``; the read is the one place that needs it.
          rules_read = FfaRulesRead(
              placement_points=list(rules.placement_points),
              score_points=rules.score_points,
              score_label=stage.ffa_score_label if stage else None,
          )
  ```

  Стало:

  ```python
          rules = ffa_rules(stage)
          # The full rule set, hidden columns included: ``public_view`` is what
          # trims it for a public endpoint, so an admin read needs no second path.
          rules_read = FfaRulesRead(
              columns=[
                  FfaColumnRead(key=column.key, label=column.label, public=column.public, better=column.better)
                  for column in rules.columns
              ],
              placement_points=list(rules.placement_points),
              formula=rules.formula.source,
              requires_placement=rules.requires_placement,
          )
  ```

  Строки лобби — было (`:501`):

  ```python
              lines[row.game_id][row.team_id] = FfaGameLine(team_id=row.team_id, placement=row.placement, score=row.score)
  ```

  Стало:

  ```python
              lines[row.game_id][row.team_id] = FfaGameLine(
                  team_id=row.team_id, placement=row.placement, stats=row.stats
              )
  ```

  Итог строки — было (`:592-596`):

  ```python
                      score=total.score,
                      games=[
                          self._read_cell(position, by_position.get(position), lines, seat.team_id, rules)
                          for position in range(1, last + 1)
                      ],
  ```

  Стало:

  ```python
                      stats=dict(total.stats),
                      games=[
                          self._read_cell(position, by_position.get(position), lines, seat.team_id, rules)
                          for position in range(1, last + 1)
                      ],
  ```

  Ячейка — было (`:616-631`):

  ```python
      @staticmethod
      def _read_cell(
          position: int,
          game: models.EncounterGame | None,
          lines: dict[int, dict[int, FfaGameLine]],
          team_id: int,
          rules: FfaRules,
      ) -> FfaGameCellRead:
          line = lines.get(game.id, {}).get(team_id) if game is not None else None
          return FfaGameCellRead(
              position=position,
              state=game.state if game is not None else None,
              placement=line.placement if line is not None else None,
              score=line.score if line is not None else None,
              points=game_points(line, rules) if line is not None else None,
          )
  ```

  Стало:

  ```python
      @staticmethod
      def _read_cell(
          position: int,
          game: models.EncounterGame | None,
          lines: dict[int, dict[int, FfaGameLine]],
          team_id: int,
          rules: FfaRules,
      ) -> FfaGameCellRead:
          game_lines = lines.get(game.id, {}) if game is not None else {}
          line = game_lines.get(team_id)
          return FfaGameCellRead(
              position=position,
              state=game.state if game is not None else None,
              placement=line.placement if line is not None else None,
              # ``teams`` is a variable of the formula, so it is the count of the
              # lines THIS game holds, not the lobby's seat count: a lobby may seat
              # a team that never played this game.
              points=game_points(line, rules, len(game_lines)) if line is not None else None,
              stats=dict(line.stats) if line is not None else None,
          )
  ```

  Снимок — было (`:665-673`):

  ```python
      async def _snapshot(self, session: AsyncSession, game: models.EncounterGame) -> list[dict]:
          """A game's current result rows, in table order. ``[]`` for a fresh position."""
          if game.id is None:
              return []
          rows = await self.result_repo.list_for_games(session, [game.id])
          return [
              {"team_id": row.team_id, "placement": row.placement, "score": row.score}
              for row in sorted(rows, key=_line_order)
          ]
  ```

  Стало:

  ```python
      async def _snapshot(self, session: AsyncSession, game: models.EncounterGame) -> list[dict]:
          """A game's current result rows, in table order. ``[]`` for a fresh position."""
          if game.id is None:
              return []
          rows = await self.result_repo.list_for_games(session, [game.id])
          return [
              {"team_id": row.team_id, "placement": row.placement, "stats": dict(row.stats)}
              for row in sorted(rows, key=_line_order)
          ]
  ```

  Подтверждённые игры — было (`:684`):

  ```python
              by_game[row.game_id].append(FfaGameLine(team_id=row.team_id, placement=row.placement, score=row.score))
  ```

  Стало:

  ```python
              by_game[row.game_id].append(
                  FfaGameLine(team_id=row.team_id, placement=row.placement, stats=row.stats)
              )
  ```

  И новая модульная функция — вставить между `_line_order` и `ffa_encounter_service` (`:741-743`):

  ```python
  def public_view(lobby: FfaLobbyRead) -> FfaLobbyRead:
      """The same table with every non-public column removed (plan §7.3).

      The service builds ONE lobby read, with every column on it, and the public
      endpoints trim it here -- so a hidden column cannot leak through a read
      nobody remembered to filter, and the admin endpoints need no second builder.

      The formula is NOT trimmed: it is the rule the table is computed by, and a
      viewer seeing a hidden key's NAME there was the accepted trade (plan §2).
      """
      public_keys = {column.key for column in lobby.rules.columns if column.public}
      if len(public_keys) == len(lobby.rules.columns):
          return lobby

      def _keep(stats: dict[str, float] | None) -> dict[str, float] | None:
          if stats is None:
              return None
          return {key: value for key, value in stats.items() if key in public_keys}

      return lobby.model_copy(
          update={
              "rules": lobby.rules.model_copy(
                  update={"columns": [column for column in lobby.rules.columns if column.public]}
              ),
              "rows": [
                  row.model_copy(
                      update={
                          "stats": _keep(row.stats),
                          "games": [cell.model_copy(update={"stats": _keep(cell.stats)}) for cell in row.games],
                      }
                  )
                  for row in lobby.rows
              ],
          }
      )
  ```

- [ ] **Шаг 5. Перевести RPC и добавить админское чтение.**
  `backend/tournament-service/src/rpc/ffa.py`.

  Импорт сервиса — было (`:39`):

  ```python
  from src.services.encounter.ffa import ffa_encounter_service
  ```

  Стало:

  ```python
  from src.services.encounter.ffa import ffa_encounter_service, public_view
  ```

  Публичные чтения — было (`:84-86` и `:98`):

  ```python
              return await ffa_encounter_service.load_stage_lobbies(
                  session, _path_int(data, "stage_id"), tournament_id=tournament_id
              )
  ```
  ```python
              return await ffa_encounter_service.load_lobby(session, encounter_id)
  ```

  Стало:

  ```python
              lobbies = await ffa_encounter_service.load_stage_lobbies(
                  session, _path_int(data, "stage_id"), tournament_id=tournament_id
              )
              return [public_view(lobby) for lobby in lobbies]
  ```
  ```python
              return public_view(await ffa_encounter_service.load_lobby(session, encounter_id))
  ```

  Строка ввода — было (`:126-129`):

  ```python
                  [
                      FfaGameLine(team_id=line.team_id, placement=line.placement, score=line.score)
                      for line in body.results
                  ],
  ```

  Стало:

  ```python
                  [
                      FfaGameLine(team_id=line.team_id, placement=line.placement, stats=line.stats)
                      for line in body.results
                  ],
  ```

  Новый подписчик — вставить в конец `register` после `_ffa_games_count_set` (`:191`):

  ```python
      # ── admin read ────────────────────────────────────────────────────────
      #
      # The same lobby table the public path answers, minus ``public_view``: the
      # organizer enters the hidden columns, so the dialog and the admin group
      # page have to see them. Gated on the TOURNAMENT's workspace with the same
      # "match"/"update" permission the three writes carry -- whoever may record a
      # result may read the values behind it.

      @broker.subscriber("rpc.tournament.ffa_stage_admin")
      async def _ffa_stage_admin(data: dict, msg: RabbitMessage) -> dict:
          async def op(session: Any) -> Any:
              user = _identity(data)
              tournament_id = _require_id(data)
              ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
              ensure_workspace_permission(user, ws_id, "match", "update")
              return await ffa_encounter_service.load_stage_lobbies(
                  session, _path_int(data, "stage_id"), tournament_id=tournament_id
              )

          return await _read(logger, op)
  ```

  (Разрешение воркспейса турнира берётся тем же путём, что `rpc.tournament.report_form_get` —
  `src/rpc/admin_misc.py:260-263`: `_identity` → `_require_id` → `auth.get_tournament_workspace_id` →
  `ensure_workspace_permission`. `auth` и `ensure_workspace_permission` в `rpc/ffa.py` уже импортированы,
  строки 30 и 34.)

- [ ] **Шаг 6. Прогнать — проходит.**

  ```
  cd backend && TEST_POSTGRES_DOCKER=1 uv run pytest tournament-service/tests/test_ffa_results_integration.py -v
  ```

  Ожидаемо: PASS весь файл, включая девять параметризованных отказов и три новых теста
  (`test_a_public_read_carries_no_value_of_a_hidden_column`, `test_points_and_places_come_from_the_formula`,
  `test_a_game_is_refused_when_the_formula_needs_a_place`).

- [ ] **Шаг 7. Коммит.**

  ```
  git add backend/tournament-service/src/schemas/ffa.py \
          backend/tournament-service/src/services/encounter/ffa.py \
          backend/tournament-service/src/rpc/ffa.py \
          backend/tournament-service/tests/test_ffa_results_integration.py
  git commit -m "feat(ffa): read and write lobby games as stats, hide private columns from public reads"
  ```

---

### Задача 7. Правка `ffa_scoring` в `update_stage`: 409 после посева, `ffa_column_in_use`, пересчёт

**Files:**

- Modify: `backend/tournament-service/src/services/admin/stage.py:13` (импорт `ApiExc`),
  `:16-25` (импорт репозитория), `:99-133` (модульный `_ranking_signature` рядом с `_apply_stage_fields`),
  `:137-156` (`__init__`), `:448-475` (`update_stage`), `:1652-1675` (новый
  `assert_stage_correction_allowed` рядом с `assert_source_correction_allowed`)
- Tests: `backend/tournament-service/tests/test_admin_stage_qualification.py:273-291`
  (класс `SourceCorrectionGuardTests`), `backend/tournament-service/tests/test_ffa_results_integration.py`
  (`_drop`, новая секция тестов правки правил)

**Interfaces:**

- Consumes: `Stage.ffa_scoring` (задача 5), `EncounterGameResultRepository.stat_keys_for_stage` (задача 5),
  `schemas.StageUpdate.ffa_scoring: FfaScoring` (задача 3),
  `src.services.tournament.events.enqueue_tournament_recalculation` (импортирован в
  `admin/stage.py:78`), `AdminStageService._untouched_stage_items` (`admin/stage.py:1609`).
- Produces: `AdminStageService.assert_stage_correction_allowed(session, stage) -> None` (409);
  код ошибки 422 `ffa_column_in_use`; постановка пересчёта на любое изменение блока `ffa_scoring`.

- [ ] **Шаг 1. Написать падающий модульный тест проверки по всей стадии.**
  В `backend/tournament-service/tests/test_admin_stage_qualification.py` дописать в конец файла
  (после `test_no_downstream_inputs_short_circuits`, `:291`):

  ```python
  class StageCorrectionGuardTests(IsolatedAsyncioTestCase):
      """The same rule, asked of a whole stage: a rules edit re-ranks every group
      of it, so any one started playoff behind it blocks the edit (plan §6)."""

      def _stage(self) -> SimpleNamespace:
          return SimpleNamespace(id=1, items=[SimpleNamespace(id=100), SimpleNamespace(id=101)])

      async def test_a_started_downstream_blocks_the_rules_edit(self) -> None:
          session = _session([[200], [200]])
          with self.assertRaises(Exception) as ctx:
              await service.assert_stage_correction_allowed(session, self._stage())

          self.assertEqual(409, ctx.exception.status_code)
          self.assertIn("downstream stage already in progress", str(ctx.exception.detail))

      async def test_an_untouched_downstream_allows_it(self) -> None:
          session = _session([[200], []])
          await service.assert_stage_correction_allowed(session, self._stage())

      async def test_a_stage_nothing_plays_off_asks_one_question(self) -> None:
          session = _session([[]])
          await service.assert_stage_correction_allowed(session, self._stage())
          self.assertEqual(1, session.execute.await_count)
  ```

- [ ] **Шаг 2. Прогнать — падает.**

  ```
  cd backend && uv run pytest tournament-service/tests/test_admin_stage_qualification.py -v
  ```

  Ожидаемо: три новых теста падают с
  `AttributeError: 'AdminStageService' object has no attribute 'assert_stage_correction_allowed'`.

- [ ] **Шаг 3. Реализовать `assert_stage_correction_allowed`.**
  Вставить в `backend/tournament-service/src/services/admin/stage.py` сразу после
  `assert_source_correction_allowed` (после строки 1675):

  ```python
      async def assert_stage_correction_allowed(self, session: AsyncSession, stage: models.Stage) -> None:
          """Refuse a stage-wide re-ranking whose fallout cannot be applied.

          ``assert_source_correction_allowed`` asks this of the one group a
          corrected encounter belongs to. Editing the stage's scoring re-ranks
          EVERY group of it at once, so the question is asked of every item the
          stage has -- with the same answer and the same message, because it is the
          same impossibility: a playoff already being played cannot be re-seeded.
          """
          item_ids = [item.id for item in stage.items]
          if not item_ids:
              return
          result = await session.execute(
              select(models.StageItemInput.stage_item_id).where(
                  models.StageItemInput.source_stage_item_id.in_(item_ids),
                  models.StageItemInput.input_type == enums.StageItemInputType.FINAL,
              )
          )
          downstream_item_ids = set(result.scalars())
          if not downstream_item_ids:
              return
          untouched = await self._untouched_stage_items(session, sorted(downstream_item_ids))
          blocked = sorted(downstream_item_ids - untouched)
          if blocked:
              raise HTTPException(
                  status_code=status.HTTP_409_CONFLICT,
                  detail=(
                      "downstream stage already in progress; correct it there or deactivate it first "
                      f"(stage items {blocked})"
                  ),
              )
  ```

- [ ] **Шаг 4. Прогнать — проходит.**

  ```
  cd backend && uv run pytest tournament-service/tests/test_admin_stage_qualification.py -v
  ```

  Ожидаемо: PASS весь файл (прежние тесты не тронуты).

- [ ] **Шаг 5. Написать падающие интеграционные тесты правки правил.**
  В `backend/tournament-service/tests/test_ffa_results_integration.py`.

  Сначала — импорты. Было (`:39-49` и `:52`):

  ```python
  from shared.models.tournament import (  # noqa: E402
      Encounter,
      EncounterGame,
      EncounterResultAudit,
      Stage,
      StageItem,
      StageItemInput,
      Standing,
      Team,
      Tournament,
  )
  ```
  ```python
  from src.services.admin.stage import stage_service  # noqa: E402
  ```

  Стало:

  ```python
  from shared.models.tournament import (  # noqa: E402
      Encounter,
      EncounterGame,
      EncounterResultAudit,
      Stage,
      StageItem,
      StageItemInput,
      Standing,
      Team,
      Tournament,
      TournamentComputationJob,
  )
  ```
  ```python
  from src import schemas  # noqa: E402
  from src.services.admin.stage import stage_service  # noqa: E402
  ```

  Затем `_drop` подметает строки исходящих событий поставленных пересчётов — сейчас они переживают тест
  (тот же приём, что `tests/test_standing_pins_integration.py:120-128`). Было (`:121-134`):

  ```python
  async def _drop(session: Any, seeded: SimpleNamespace) -> None:
      await session.rollback()
      # The outbox is not workspace-scoped, so the completion and invalidation
      # rows this tournament emitted have to be swept by hand.
      await session.execute(
          sa.delete(EventOutbox).where(
              sa.or_(
                  EventOutbox.payload_json["tournament_id"].as_string() == str(seeded.tournament_id),
                  EventOutbox.routing_key == f"cache.invalidated.tournament.{seeded.tournament_id}",
              )
          )
      )
      await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
      await session.commit()
  ```

  Стало:

  ```python
  async def _drop(session: Any, seeded: SimpleNamespace) -> None:
      await session.rollback()
      # The outbox is not workspace-scoped, so the completion and invalidation
      # rows this tournament emitted have to be swept by hand -- including the
      # ones that carry only the id of a computation job the workspace delete
      # cascades away.
      job_ids = (
          await session.scalars(
              sa.select(TournamentComputationJob.id).where(
                  TournamentComputationJob.tournament_id == seeded.tournament_id
              )
          )
      ).all()
      if job_ids:
          await session.execute(
              sa.delete(EventOutbox).where(EventOutbox.payload_json["job_id"].as_integer().in_(job_ids))
          )
      await session.execute(
          sa.delete(EventOutbox).where(
              sa.or_(
                  EventOutbox.payload_json["tournament_id"].as_string() == str(seeded.tournament_id),
                  EventOutbox.routing_key == f"cache.invalidated.tournament.{seeded.tournament_id}",
              )
          )
      )
      await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
      await session.commit()
  ```

  И новая секция в конец файла:

  ```python
  # ── editing the scoring of a stage that is already being played ──────────────


  async def _jobs(session: Any, tournament_id: int) -> int:
      return (
          await session.scalar(
              sa.select(sa.func.count())
              .select_from(TournamentComputationJob)
              .where(TournamentComputationJob.tournament_id == tournament_id)
          )
      ) or 0


  def _scoring(**overrides: Any) -> dict:
      block = {
          "columns": [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}],
          "placement_points": [],
          "formula": "score",
      }
      block.update(overrides)
      return block


  async def _start_the_playoff(session: Any, seeded: SimpleNamespace) -> None:
      """Seed the bracket off the league and play a match in it: from here on the
      league's places are frozen into a playoff nobody can re-seed."""
      await stage_service.wire_from_groups(session, seeded.bracket_stage_id, seeded.stage_id, top=2, commit=True)
      for lobby_id, seats, scores in (
          (seeded.lobby_ids[0], seeded.team_ids[:3], [10, 6, 2]),
          (seeded.lobby_ids[1], seeded.team_ids[3:], [2, 6, 10]),
      ):
          await ffa_encounter_service.set_game_results(
              session, lobby_id, 1, _lines(seats, scores), actor_user_id=None, reason=None
          )
      await standings_service.recalculate_for_tournament(session, seeded.tournament_id)
      bracket_stage = await stage_service.activate_stage(session, seeded.bracket_stage_id)
      session.add(
          Encounter(
              name="Semifinal",
              home_team_id=seeded.team_ids[0],
              away_team_id=seeded.team_ids[5],
              home_score=2,
              away_score=1,
              round=1,
              tournament_id=seeded.tournament_id,
              stage_id=seeded.bracket_stage_id,
              stage_item_id=bracket_stage.items[0].id,
              status=enums.EncounterStatus.COMPLETED,
              result_status=enums.EncounterResultStatus.CONFIRMED,
          )
      )
      await session.commit()


  def test_rewriting_the_formula_after_the_playoff_started_is_refused(db_session) -> None:
      """The edit would re-rank the groups the playoff was seeded from, and there
      is nowhere to put the new order (plan §6)."""

      async def _run() -> tuple:
          seeded = await _seed_league(db_session)
          try:
              await _start_the_playoff(db_session, seeded)
              with pytest.raises(BaseAPIException) as raised:
                  await stage_service.update_stage(
                      db_session,
                      seeded.stage_id,
                      schemas.StageUpdate(ffa_scoring=_scoring(formula="score * 2")),
                  )
              await db_session.rollback()
              stage = await _reload_stage(db_session, seeded.stage_id)
              return raised.value.status_code, str(raised.value.detail), stage.ffa_formula
          finally:
              await _drop(db_session, seeded)

      status_code, detail, formula = asyncio.run(_run())
      assert status_code == 409
      assert "downstream stage already in progress" in detail
      assert formula == "score"


  def test_renaming_a_column_after_the_playoff_started_is_allowed(db_session) -> None:
      """A label moves nobody: it is editable for as long as the stage exists."""

      async def _run() -> tuple:
          seeded = await _seed_league(db_session)
          try:
              await _start_the_playoff(db_session, seeded)
              await stage_service.update_stage(
                  db_session,
                  seeded.stage_id,
                  schemas.StageUpdate(
                      ffa_scoring=_scoring(
                          columns=[{"key": "score", "label": "Kills", "public": False, "better": "higher"}]
                      )
                  ),
              )
              stage = await _reload_stage(db_session, seeded.stage_id)
              return stage.ffa_columns, stage.ffa_formula
          finally:
              await _drop(db_session, seeded)

      columns, formula = asyncio.run(_run())
      assert columns == [{"key": "score", "label": "Kills", "public": False, "better": "higher"}]
      assert formula == "score"


  def test_dropping_a_column_the_games_hold_values_for_is_refused(db_session) -> None:
      """Values are the record of the tournament; losing them would go unnoticed
      until somebody disputed a place (plan §6)."""

      async def _run() -> tuple:
          seeded = await _seed(db_session, games=1, regulation=KILLS_DEATHS)
          try:
              await ffa_encounter_service.set_game_results(
                  db_session,
                  seeded.lobby_id,
                  1,
                  _stat_lines(
                      seeded.team_ids,
                      [{"kills": 6, "deaths": 1}, {"kills": 3, "deaths": 2}, {"kills": 1, "deaths": 4}],
                  ),
                  actor_user_id=None,
                  reason=None,
              )
              with pytest.raises(BaseAPIException) as raised:
                  await stage_service.update_stage(
                      db_session,
                      seeded.stage_id,
                      schemas.StageUpdate(
                          ffa_scoring=_scoring(
                              columns=[{"key": "kills", "label": "Kills", "public": True, "better": "higher"}],
                              formula="kills * 2",
                          )
                      ),
                  )
              await db_session.rollback()
              stage = await _reload_stage(db_session, seeded.stage_id)
              return (
                  raised.value.status_code,
                  [item.code for item in raised.value.detail],
                  [column["key"] for column in stage.ffa_columns],
              )
          finally:
              await _drop(db_session, seeded)

      assert asyncio.run(_run()) == (422, ["ffa_column_in_use"], ["kills", "deaths"])


  def test_an_accepted_scoring_edit_queues_the_recalculation(db_session) -> None:
      """Points, places and the public table are all derived from the rules, so a
      rules edit has to re-run the standings -- nothing else would."""

      async def _run() -> tuple:
          seeded = await _seed(db_session, games=1)
          try:
              before = await _jobs(db_session, seeded.tournament_id)
              await stage_service.update_stage(
                  db_session,
                  seeded.stage_id,
                  schemas.StageUpdate(ffa_scoring=_scoring(formula="score * 2")),
              )
              after = await _jobs(db_session, seeded.tournament_id)
              # The same block again is not an edit and must not queue anything.
              await stage_service.update_stage(
                  db_session,
                  seeded.stage_id,
                  schemas.StageUpdate(ffa_scoring=_scoring(formula="score * 2")),
              )
              return before, after, await _jobs(db_session, seeded.tournament_id)
          finally:
              await _drop(db_session, seeded)

      before, after, again = asyncio.run(_run())
      assert after == before + 1
      assert again == after
  ```

- [ ] **Шаг 6. Прогнать — падает.**

  ```
  cd backend && TEST_POSTGRES_DOCKER=1 uv run pytest tournament-service/tests/test_ffa_results_integration.py -v -k "playoff_started or column_the_games or scoring_edit"
  ```

  Ожидаемо: `test_rewriting_the_formula_after_the_playoff_started_is_refused` падает —
  `update_stage` молча записывает новую формулу и возвращает стадию, `pytest.raises` не срабатывает;
  `test_dropping_a_column_the_games_hold_values_for_is_refused` — то же самое;
  `test_an_accepted_scoring_edit_queues_the_recalculation` — `after == before`.

- [ ] **Шаг 7. Реализовать проверки и пересчёт в `update_stage`.**
  `backend/tournament-service/src/services/admin/stage.py`.

  Импорты — было (`:13`):

  ```python
  from shared.core.errors import BaseAPIException as HTTPException
  ```

  Стало:

  ```python
  from shared.core.errors import ApiExc
  from shared.core.errors import BaseAPIException as HTTPException
  ```

  Было (`:16-25`):

  ```python
  from shared.repository import (
      EncounterRepository,
      PickBanConfigRepository,
      StageItemInputRepository,
      StageItemRepository,
      StageRepository,
      StandingRepository,
      TeamRepository,
      TournamentRepository,
  )
  ```

  Стало:

  ```python
  from shared.repository import (
      EncounterGameResultRepository,
      EncounterRepository,
      PickBanConfigRepository,
      StageItemInputRepository,
      StageItemRepository,
      StageRepository,
      StandingRepository,
      TeamRepository,
      TournamentRepository,
  )
  ```

  Добавить модульную функцию сразу после `_apply_stage_fields` (после `:133`):

  ```python
  def _ranking_signature(block: dict[str, Any]) -> tuple[Any, ...]:
      """What of ``ffa_scoring`` decides places -- everything except presentation.

      Labels and ``public`` are how the table is drawn; the formula, the placement
      points, the set of column keys and their ``better`` are what the places are
      computed from. Column ORDER counts too: with no explicit ``tiebreak_order``
      the ffa_league preset breaks ties by the sum of the FIRST column, so moving
      one can move a team.

      Compared, not merely "was it sent": saving the same form twice must not run
      into a 409.
      """
      return (
          block["formula"].strip(),
          tuple(float(points) for points in block["placement_points"]),
          tuple((column["key"], column["better"]) for column in block["columns"]),
      )
  ```

  В конструктор — было (`:147-148` и `:156`):

  ```python
          pick_ban_config_repo: PickBanConfigRepository = PickBanConfigRepository(),
      ) -> None:
  ```
  ```python
          self.pick_ban_config_repo = pick_ban_config_repo
  ```

  Стало:

  ```python
          pick_ban_config_repo: PickBanConfigRepository = PickBanConfigRepository(),
          result_repo: EncounterGameResultRepository = EncounterGameResultRepository(),
      ) -> None:
  ```
  ```python
          self.pick_ban_config_repo = pick_ban_config_repo
          self.result_repo = result_repo
  ```

  Было (`:472-475`):

  ```python
          _apply_stage_fields(stage, update_data)
          await self._publish_structure_changed(session, tournament_id)
          await session.commit()
          return await self.get_stage(session, stage.id)
  ```

  Стало:

  ```python
          ffa_before = stage.ffa_scoring if "ffa_scoring" in update_data else None
          if ffa_before is not None:
              await self._assert_ffa_scoring_editable(session, stage, ffa_before, update_data["ffa_scoring"])

          _apply_stage_fields(stage, update_data)
          # Points, places and the public table are all derived from the rules, so
          # a changed block has to re-run the standings: nothing else would, and
          # the same signal drops the gateway's cache of the lobby read.
          if ffa_before is not None and ffa_before != stage.ffa_scoring:
              await enqueue_tournament_recalculation(session, tournament_id)
          await self._publish_structure_changed(session, tournament_id)
          await session.commit()
          return await self.get_stage(session, stage.id)

      async def _assert_ffa_scoring_editable(
          self,
          session: AsyncSession,
          stage: models.Stage,
          before: dict[str, Any],
          after: dict[str, Any],
      ) -> None:
          """The two ffa_scoring edits a stage in play cannot take (plan §6).

          Re-ranking edits (the formula, the placement points, the column keys,
          their ``better``) are refused once a playoff seeded off this stage has
          started -- the same rule, and the same 409, a result correction answers
          to. Dropping a column the games hold values for is refused outright: the
          values are a record of the tournament, and no later edit brings them
          back.
          """
          if _ranking_signature(before) != _ranking_signature(after):
              await self.assert_stage_correction_allowed(session, stage)
          removed = {column["key"] for column in before["columns"]} - {column["key"] for column in after["columns"]}
          if not removed:
              return
          in_use = sorted(removed & await self.result_repo.stat_keys_for_stage(session, stage.id))
          if in_use:
              raise HTTPException(
                  status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                  detail=[
                      ApiExc(
                          code="ffa_column_in_use",
                          msg=f"Games of this stage already hold values for: {', '.join(in_use)}",
                      )
                  ],
              )
  ```

  (`ApiExc`-список, а не строка: код нужен фронту для подписи под полем — та же форма, что у
  `ffa_field_not_editable` в `src/services/admin/encounter.py:293`.)

- [ ] **Шаг 8. Прогнать — проходит.**

  ```
  cd backend && TEST_POSTGRES_DOCKER=1 uv run pytest tournament-service/tests/test_ffa_results_integration.py tournament-service/tests/test_admin_stage_qualification.py tournament-service/tests/test_admin_stage_inputs.py -v
  ```

  Ожидаемо: PASS. `test_admin_stage_inputs.py` включён потому, что его `UpdateStageTests`
  (`test_admin_stage_inputs.py:319-389`) вызывают `update_stage` на двойнике стадии: при правке без
  `ffa_scoring` новая ветка не выполняется, а фикстура `stage_regulation` уже даёт `ffa_columns`/`ffa_formula`
  (задача 5).

- [ ] **Шаг 9. Коммит.**

  ```
  git add backend/tournament-service/src/services/admin/stage.py \
          backend/tournament-service/tests/test_admin_stage_qualification.py \
          backend/tournament-service/tests/test_ffa_results_integration.py
  git commit -m "feat(ffa): guard scoring edits of a stage in play and recalculate after them"
  ```

---

### Задача 8. Шлюз: маршрут админского чтения FFA и OpenAPI

**Files:**

- Modify: `gateway/internal/tournament/admin_misc_routes.go:46-53` (блок FFA)
- Modify: `backend/tournament-service/src/openapi_schemas.py:432-437` (блок ffa-записей)
- Modify: `backend/tournament-service/src/openapi_docs.py:52-62` (описание публичного чтения),
  `:353-364` (описание записи результата), + новая запись `rpc.tournament.ffa_stage_admin`
- Modify (сгенерированный): `gateway/internal/openapi/schemas.json`
- Tests: `gateway/internal/tournament/routes_test.go` — правок не требует, но покрывает новый маршрут
  (`TestRoutesRegisterWithoutConflict`, `routes_test.go:192-211`, перечисляет `AdminMiscRoutes`)

**Interfaces:**

- Consumes: RPC-субъект `rpc.tournament.ffa_stage_admin` и схема `FfaLobbyRead` (задача 6).
- Produces: `GET /api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa`; запись
  `operations["rpc.tournament.ffa_stage_admin"]` в манифесте `schemas.json` (вместе с summary/description из
  `DOCS` — `backend/scripts/export_openapi_schemas.py:98,113`).

Ни одного ручного JSON-правки: `gateway/internal/openapi/schemas.json` собирается скриптом
`backend/scripts/export_openapi_schemas.sh` из `src/openapi_schemas.py` каждого сервиса
(`gateway/internal/openapi/openapi.go:25-29`, комментарий шапки скрипта). У скрипта есть режим `--check` — это
CI-гейт `.github/workflows/lint-backend.yml`, который падает на устаревшем манифесте.

- [ ] **Шаг 1. Написать падающую проверку манифеста.** Отдельный тест здесь не пишется: гейтом служит
  `--check`-режим экспортёра, который сравнивает закоммиченный манифест с тем, что дают модели.

  ```
  bash backend/scripts/export_openapi_schemas.sh --check
  ```

  Ожидаемо на этом шаге: `ERROR: gateway/internal/openapi/schemas.json is STALE.` — задача 6 уже изменила
  `FfaLobbyRead`/`FfaGameResultsInput` (столбцы, `stats`), и манифест их не содержит.

- [ ] **Шаг 2. Добавить маршрут в шлюз.**

  Было (`gateway/internal/tournament/admin_misc_routes.go:46-53`):

  ```go
  	// FFA lobby results (src/rpc/ffa.py) — one game of a lobby is identified by
  	// its POSITION, like the duel game correction above: a lobby may replay a
  	// cancelled position, and only the position tells the two plays apart. The
  	// games count is the lobby's own best_of. Same worker-side
  	// "match"/"update" gate as every other result write.
  	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games/{position}/results", Queue: "rpc.tournament.ffa_game_results_set", IDParam: "encounter_id", Path: []string{"position"}, Body: true, Auth: edge.AuthRequired},
  	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games/{position}/cancel", Queue: "rpc.tournament.ffa_game_cancel", IDParam: "encounter_id", Path: []string{"position"}, Body: true, Auth: edge.AuthRequired},
  	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games-count", Queue: "rpc.tournament.ffa_games_count_set", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
  ```

  Стало:

  ```go
  	// FFA lobby results (src/rpc/ffa.py) — one game of a lobby is identified by
  	// its POSITION, like the duel game correction above: a lobby may replay a
  	// cancelled position, and only the position tells the two plays apart. The
  	// games count is the lobby's own best_of. Same worker-side
  	// "match"/"update" gate as every other result write.
  	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games/{position}/results", Queue: "rpc.tournament.ffa_game_results_set", IDParam: "encounter_id", Path: []string{"position"}, Body: true, Auth: edge.AuthRequired},
  	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games/{position}/cancel", Queue: "rpc.tournament.ffa_game_cancel", IDParam: "encounter_id", Path: []string{"position"}, Body: true, Auth: edge.AuthRequired},
  	{Method: "POST", Pattern: "/api/v1/admin/encounters/{encounter_id}/ffa/games-count", Queue: "rpc.tournament.ffa_games_count_set", IDParam: "encounter_id", Body: true, Auth: edge.AuthRequired},
  	// The organizer's view of the same lobby tables the public route answers,
  	// with the columns marked non-public still on them — that is what the entry
  	// dialog fills in. NOT listed in cacheable.go: the values behind a hidden
  	// column must not sit in a shared response cache.
  	{Method: "GET", Pattern: "/api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa", Queue: "rpc.tournament.ffa_stage_admin", IDParam: "id", Path: []string{"stage_id"}, Auth: edge.AuthRequired},
  ```

- [ ] **Шаг 3. Объявить операцию в манифесте схем.**

  Было (`backend/tournament-service/src/openapi_schemas.py:432-437`):

  ```python
      # ── ffa lobby results: every write answers the settled lobby table ────
      "rpc.tournament.ffa_game_results_set": Op(
          request=ffa_schemas.FfaGameResultsInput, response=ffa_schemas.FfaLobbyRead
      ),
      "rpc.tournament.ffa_game_cancel": Op(request=ffa_schemas.FfaGameCancelInput, response=ffa_schemas.FfaLobbyRead),
      "rpc.tournament.ffa_games_count_set": Op(request=ffa_schemas.FfaGamesCountInput, response=ffa_schemas.FfaLobbyRead),
  ```

  Стало:

  ```python
      # ── ffa lobby results: every write answers the settled lobby table ────
      "rpc.tournament.ffa_game_results_set": Op(
          request=ffa_schemas.FfaGameResultsInput, response=ffa_schemas.FfaLobbyRead
      ),
      "rpc.tournament.ffa_game_cancel": Op(request=ffa_schemas.FfaGameCancelInput, response=ffa_schemas.FfaLobbyRead),
      "rpc.tournament.ffa_games_count_set": Op(request=ffa_schemas.FfaGamesCountInput, response=ffa_schemas.FfaLobbyRead),
      # Same shape as rpc.tournament.ffa_stage, minus the public_view trim.
      "rpc.tournament.ffa_stage_admin": Op(response=ffa_schemas.FfaLobbyRead, response_array=True),
  ```

- [ ] **Шаг 4. Описать операцию и поправить описания, которые пинят удалённое поле.**
  `backend/tournament-service/src/openapi_docs.py` — `DOCS` попадает в манифест тем же экспортёром
  (`backend/scripts/export_openapi_schemas.py:98,113`), поэтому без записи новый маршрут выйдет в Scalar
  без summary.

  Было (`src/openapi_docs.py:56-61`, публичное чтение стадии):

  ```python
              "Permission: public; no authentication required — a hidden tournament is visible only to its "
              "workspace's admins and users on its preview allowlist. Returns one lobby table per group of an "
              "ffa_league stage, in group order: the stage's scoring rules, every seated team with its running "
              "points, and one cell per planned game. Positions come from the group's standings, so a stage "
              "nobody has ranked yet answers null positions in seat order."
  ```

  Стало:

  ```python
              "Permission: public; no authentication required — a hidden tournament is visible only to its "
              "workspace's admins and users on its preview allowlist. Returns one lobby table per group of an "
              "ffa_league stage, in group order: the stage's scoring rules, every seated team with its running "
              "points and column sums, and one cell per planned game. Columns the organizer marked non-public "
              "are omitted here entirely — their sums and per-game values never leave the service. Positions "
              "come from the group's standings, so a stage nobody has ranked yet answers null positions in "
              "seat order."
  ```

  Было (`src/openapi_docs.py:357-362`, запись результата):

  ```python
              "Permission: workspace `match.update` on the encounter's workspace. "
              "Records one game of a lobby: a line per seated team, every team exactly once. Placements are "
              "required when the stage pays for place and derived from the score otherwise (ties share a place). "
              "Re-recording a confirmed position is a correction and needs a reason. The lobby completes itself "
              "when its confirmed games reach its games count, and reopens when they no longer do. Answers the "
              "lobby's settled table. 409 when a later stage has already been seeded from this group."
  ```

  Стало:

  ```python
              "Permission: workspace `match.update` on the encounter's workspace. "
              "Records one game of a lobby: a line per seated team, every team exactly once, carrying one value "
              "per column of the stage. Placements are required when the stage's formula reads the place and "
              "derived from the game's points otherwise (ties share a place). Re-recording a confirmed position "
              "is a correction and needs a reason. The lobby completes itself when its confirmed games reach its "
              "games count, and reopens when they no longer do. Answers the lobby's settled table, with every "
              "column on it. 409 when a later stage has already been seeded from this group."
  ```

  И новая запись — вставить после `"rpc.tournament.ffa_games_count_set"` (`src/openapi_docs.py:382`):

  ```python
      "rpc.tournament.ffa_stage_admin": {
          "summary": "Get FFA stage lobbies (organizer view)",
          "description": (
              "Permission: workspace `match.update` on the tournament's workspace — whoever may record a "
              "result may read the values behind it. The same lobby tables as the public stage read, with the "
              "columns marked non-public still on them: that is what the result-entry dialog fills in. Not "
              "cached by the gateway."
          ),
      },
  ```

- [ ] **Шаг 5. Перегенерировать манифест.**

  ```
  bash backend/scripts/export_openapi_schemas.sh
  ```

  Ожидаемо: `wrote .../gateway/internal/openapi/schemas.json (<N> bytes)`; в файле появляется
  `operations["rpc.tournament.ffa_stage_admin"]`, а схемы `FfaLobbyRead`/`FfaRulesRead`/`FfaGameCellRead`
  обновляются под задачу 6 (`columns`, `stats`, `formula`, `requires_placement`).

- [ ] **Шаг 6. Прогнать — проходит.**

  ```
  bash backend/scripts/export_openapi_schemas.sh --check
  cd gateway && go test ./internal/tournament/... ./internal/openapi/...
  ```

  Ожидаемо: `schemas.json is up to date (<N> bytes)`; `ok .../internal/tournament`, `ok .../internal/openapi`.
  Новый маршрут проходит `TestRoutesRegisterWithoutConflict` (`routes_test.go:192-211`): он регистрирует
  каждый `AdminMiscRoutes` на `http.ServeMux`, а `ServeMux` паникует на конфликтующем шаблоне — литерал
  `stages` в четвёртом сегменте разводит новый маршрут со всеми существующими
  `/api/v1/admin/tournaments/{tournament_id}/…`. Ни один go-тест не перечисляет ffa-маршруты поимённо
  (`grep ffa` по `internal/tournament/routes_test.go`, `internal/openapi/openapi_test.go`,
  `internal/edge/apiv1_guard_test.go` — пусто), так что таблицы маршрутов в тестах править не нужно.

- [ ] **Шаг 7. Коммит.**

  ```
  git add gateway/internal/tournament/admin_misc_routes.go \
          gateway/internal/openapi/schemas.json \
          backend/tournament-service/src/openapi_schemas.py \
          backend/tournament-service/src/openapi_docs.py
  git commit -m "feat(ffa): expose the organizer's lobby read at the gateway"
  ```

---

---

## Раздел C. Фронтенд: чтение, публичная таблица, диалог ввода

Задачи 9–11. Все три выходят одним релизом с задачами 2–8: после задачи 9 тип `FfaRules` уже новый, поэтому
`FfaLobbyTable` и `FfaGameResultsDialog` временно не компилируются — их чинят задачи 10 и 11. Каждая задача
проверяется своими тестами; соседние файлы до своей задачи могут быть красными.

Команды тестов выполняются из `frontend/`. Переменные окружения не нужны: `vitest` здесь гоняет happy-dom и
чистую логику, сеть замокана (`vi.mock("@/services/ffa.service")`, `vi.mock("@/lib/api/fetch")`).

---

### Задача 9. Фронт: типы, сервис, ключ кэша, админская страница лобби

**Files:**

- Modify `frontend/src/types/ffa.types.ts:15-32` (`FfaRules`, `FfaGameCell`), `:34-50` (`FfaLobbyRow`), `:68-73`
  (`FfaGameResultLineInput`)
- Modify `frontend/src/services/ffa.service.ts:16-21` (вставка нового метода после `getStage`)
- Modify `frontend/src/lib/tournament/query-keys.ts:40-41` (вставка `ffaStageAdmin` после `ffaLobby`)
- Modify `frontend/src/app/admin/tournaments/[id]/matches/lobbies/page.tsx:74-77` (чтение лобби стадии)
- Modify `frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaRoundSchedule.behavior.test.tsx:142`
  (фикстура `FfaLobby.rules`)
- Create `frontend/src/services/ffa.service.test.ts`
- Tests: `frontend/src/services/ffa.service.test.ts` (новый),
  `frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaRoundSchedule.behavior.test.tsx` (существующий,
  правится фикстура)

**Interfaces:**

_Consumes_ (задачи 6 и 8):

- `GET /api/v1/tournaments/{id}/stages/{stage_id}/ffa` → `FfaLobbyRead[]`, обрезанный `public_view`
- `GET /api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa` → `FfaLobbyRead[]` без обрезки
  (RPC `rpc.tournament.ffa_stage_admin`, право `match.update`)
- форма ответа: `rules {columns[], placement_points[], formula, requires_placement}`,
  `row.stats: dict[str,float]`, `cell.stats: dict[str,float] | None`

_Produces_:

```ts
// frontend/src/types/ffa.types.ts
export type FfaColumnBetter = "higher" | "lower";
export interface FfaColumn { key: string; label: string; public: boolean; better: FfaColumnBetter }
export interface FfaRules {
  columns: FfaColumn[];
  placement_points: number[];
  formula: string;
  requires_placement: boolean;
}
export interface FfaGameCell {
  position: number;
  state: EncounterGameState | null;
  placement: number | null;
  points: number | null;
  stats: Record<string, number> | null;
}
export interface FfaLobbyRow { /* … */ stats: Record<string, number>; games: FfaGameCell[] }
export interface FfaGameResultLineInput {
  team_id: number;
  placement?: number | null;
  stats: Record<string, number>;
}

// frontend/src/services/ffa.service.ts
ffaService.getStageAdmin(tournamentId: number, stageId: number): Promise<FfaLobby[]>

// frontend/src/lib/tournament/query-keys.ts
tournamentQueryKeys.ffaStageAdmin(tournamentId: number, stageId: number):
  readonly ["ffa", number, "stage", number, "admin"]
```

Потребители: задача 10 (`FfaLobbyTable` читает `rules.columns`, `row.stats`, `cell.stats`, `cell.points`),
задача 11 (`FfaGameResultsDialog` читает `rules.columns`, `rules.requires_placement`, пишет
`FfaGameResultLineInput.stats`).

---

- [ ] **Шаг 1. Написать падающий тест сервиса.**

Наблюдаемый контракт задачи — два РАЗНЫХ адреса чтения: публичный и админский. Адрес должен совпасть с маршрутом
шлюза из задачи 8, иначе организатор получит 404 вместо скрытых столбцов. Стиль — как у
`frontend/src/services/team.service.test.ts:1-29` (мок `@/lib/api/fetch`, запись вызовов, динамический импорт
сервиса после мока).

Создать `frontend/src/services/ffa.service.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

// What the two lobby reads address. They are NOT the same endpoint and must not
// collapse into one: the public path answers a lobby with the hidden columns
// (deaths, penalties) and their values stripped out by `public_view`, and the
// organizer's path answers the same lobby whole. A frontend that reads the
// public path on the entry screen silently loses every hidden column the
// organizer is supposed to be typing into.
const paths: string[] = [];

vi.mock("@/lib/api/fetch", () => ({
  apiFetch: (path: string) => {
    paths.push(path);
    return Promise.resolve({ json: async () => [] });
  }
}));

const { default: ffaService } = await import("@/services/ffa.service");

describe("ffa stage reads", () => {
  beforeEach(() => {
    paths.length = 0;
  });

  it("reads the organizer's stage lobbies from the admin route", async () => {
    await ffaService.getStageAdmin(84, 10);

    expect(paths).toEqual(["/api/v1/admin/tournaments/84/stages/10/ffa"]);
  });

  it("keeps the spectator's stage read on the public route", async () => {
    await ffaService.getStage(84, 10);

    expect(paths).toEqual(["/api/v1/tournaments/84/stages/10/ffa"]);
  });
});
```

- [ ] **Шаг 2. Запустить тест — падение.**

```
cd frontend && bunx vitest run src/services/ffa.service.test.ts
```

Ожидаемо: `ffa stage reads > reads the organizer's stage lobbies from the admin route` падает с
`TypeError: ffaService.getStageAdmin is not a function`. Второй тест проходит — публичный путь уже есть.

- [ ] **Шаг 3. Переписать типы под §7.3 спеки.**

`frontend/src/types/ffa.types.ts:15-32` сейчас:

```ts
15:/** The stage's `ffa_scoring`, resolved for this lobby. */
16:export interface FfaRules {
17:  /** Points for placing 1st, 2nd, … A shorter list scores the tail at zero. */
18:  placement_points: number[];
19:  /** Multiplier applied to a team's raw score in a game. */
20:  score_points: number;
21:  /** What the score column counts ("Kills", "Points", …); `null` hides it. */
22:  score_label: string | null;
23:}
24:
25:export interface FfaGameCell {
26:  position: number;
27:  /** `null` — the game has not been opened yet. */
28:  state: EncounterGameState | null;
29:  placement: number | null;
30:  score: number | null;
31:  points: number | null;
32:}
```

Заменить на:

```ts
/** Whether a bigger value of a column is the better one. */
export type FfaColumnBetter = "higher" | "lower";

/**
 * One value the organizer records per team per game: kills, deaths, damage, a
 * penalty. The key is what the stage's formula reads; the label is the only
 * thing ever printed, so the table never invents a word for a column.
 */
export interface FfaColumn {
  key: string;
  label: string;
  /** `false` — the column exists only for the organizer. A public read drops
   *  the column AND its values, so a `false` here can only arrive through the
   *  admin read. */
  public: boolean;
  better: FfaColumnBetter;
}

/** The stage's `ffa_scoring`, resolved for this lobby. */
export interface FfaRules {
  columns: FfaColumn[];
  /** Points for placing 1st, 2nd, … A shorter list scores the tail at zero. */
  placement_points: number[];
  /** The organizer's expression over the column keys, `place`, `place_pts` and
   *  `teams`. Shown as the rule the table is scored by; never evaluated here —
   *  the points on the wire are the server's (spec §11). */
  formula: string;
  /** The formula reads the place, so a game cannot be recorded without a full
   *  permutation of 1..N. Derived server-side from the formula, never a flag
   *  the organizer can desync from it. */
  requires_placement: boolean;
}

export interface FfaGameCell {
  position: number;
  /** `null` — the game has not been opened yet. */
  state: EncounterGameState | null;
  placement: number | null;
  points: number | null;
  /** What was entered for this game, by column key. `null` — nobody has played
   *  it; `{}` is a played game whose stage has no columns. A key missing from a
   *  played game scores zero (spec §3.2). */
  stats: Record<string, number> | null;
}
```

`frontend/src/types/ffa.types.ts:48` сейчас `  score: number;` — заменить на:

```ts
  /** Each column summed over the games played. A key the team never scored is
   *  absent, not zero. */
  stats: Record<string, number>;
```

`frontend/src/types/ffa.types.ts:68-73` сейчас:

```ts
68:/** One team's line of a game result. `placement` is null on a score-only lobby. */
69:export interface FfaGameResultLineInput {
70:  team_id: number;
71:  placement?: number | null;
72:  score: number;
73:}
```

Заменить на:

```ts
/** One team's line of a game result. `placement` is null when the stage's
 *  formula does not read the place, and the server derives it from the points. */
export interface FfaGameResultLineInput {
  team_id: number;
  placement?: number | null;
  /** Exactly the stage's column keys — the server rejects a missing one
   *  (`ffa_result_missing_stat`) and an extra one (`ffa_result_unknown_stat`). */
  stats: Record<string, number>;
}
```

- [ ] **Шаг 4. Добавить админское чтение в сервис.**

`frontend/src/services/ffa.service.ts:16-21` — публичный `getStage`. Вставить сразу после него (перед
`getLobby` на строке 23):

```ts
  /**
   * The organizer's read of the same lobbies.
   *
   * Identical shape, one difference that matters: the public route runs its
   * answer through `public_view` and strips the columns marked `public: false`
   * together with every value under them, in `rules`, in the row totals and in
   * the game cells. The entry dialog has to show exactly those columns, so the
   * organizer's screens read this route instead (spec §7.3).
   */
  async getStageAdmin(tournamentId: number, stageId: number): Promise<FfaLobby[]> {
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/stages/${stageId}/ffa`,
    );
    return response.json();
  },
```

Форма вызова — как у остальных админских GET репозитория (`admin.service.ts:240-243`
`getTournamentReadiness`, `report-form.service.ts:8-12`): голый `apiFetch(path)` без опций, воркспейс-заголовок
ставит сам `apiFetch`.

- [ ] **Шаг 5. Добавить ключ кэша.**

`frontend/src/lib/tournament/query-keys.ts:40-41` сейчас:

```ts
40:  ffaLobby: (tournamentId: number, encounterId: number) =>
41:    ["ffa", tournamentId, "lobby", encounterId] as const,
```

Вставить после строки 41:

```ts
  /** The organizer's read of the same stage. A separate entry on purpose: it
   *  carries the hidden columns the public read drops, and one shared key would
   *  serve whichever of the two answers landed in the cache first. Still under
   *  the `["ffa", tournamentId]` prefix, so `ffaAll` — and with it every
   *  realtime invalidation (`lib/realtime/resources.ts:67-78`) — stales it
   *  together with the public tables. */
  ffaStageAdmin: (tournamentId: number, stageId: number) =>
    ["ffa", tournamentId, "stage", stageId, "admin"] as const,
```

- [ ] **Шаг 6. Перевести админскую страницу лобби на админское чтение.**

`frontend/src/app/admin/tournaments/[id]/matches/lobbies/page.tsx:74-77` сейчас:

```tsx
74:  const lobbiesQuery = useQuery({
75:    queryKey: tournamentQueryKeys.ffaStage(tournamentId, stage.id),
76:    queryFn: () => ffaService.getStage(tournamentId, stage.id)
77:  });
```

Заменить на:

```tsx
  // The organizer's read, not the public one: this screen is where a hidden
  // column is entered and checked, and `public_view` would have deleted it from
  // the answer before the dialog below ever saw it.
  const lobbiesQuery = useQuery({
    queryKey: tournamentQueryKeys.ffaStageAdmin(tournamentId, stage.id),
    queryFn: () => ffaService.getStageAdmin(tournamentId, stage.id)
  });
```

Остальные читатели FFA-лобби остаются на публичном чтении, проверено пофайлово:

| Файл | Почему не меняется |
| --- | --- |
| `frontend/src/app/(site)/tournaments/[slug]/bracket/FfaStagePanel.tsx:36-39` | публичная сетка — зритель |
| `frontend/src/app/(site)/encounters/[id]/page.tsx:397` | публичная страница лобби — зритель |
| `frontend/src/app/admin/tournaments/[id]/bracket/components/RoundScheduleSection.tsx:138-142` | читает у лобби только `scheduled_at`/`best_of`; столбцов не показывает, `FfaLobbyTable` не рендерит |
| `frontend/src/app/(site)/tournaments/[slug]/pregame/[encounterId]/_components/FfaPregameRoom.tsx:29-32` | читает `row.slot`, `row.team_name`, `lobby.best_of`; удалённых полей не касается — изменений не требуется |

- [ ] **Шаг 7. Починить фикстуру `FfaLobby` в тесте расписания раундов.**

`frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaRoundSchedule.behavior.test.tsx:142` сейчас:

```ts
142:    rules: { placement_points: [10, 6, 3], score_points: 1, score_label: null },
```

Заменить на:

```ts
    rules: {
      columns: [{ key: "score", label: "Score", public: true, better: "higher" }],
      placement_points: [10, 6, 3],
      formula: "place_pts + score",
      requires_placement: true
    },
```

Строку 120 того же файла (`ffa_scoring: { placement_points: [], score_points: 1, score_label: null }` в фикстуре
`Stage`) **не трогать**: это поле типа `Stage`, его форму меняет задача 12 вместе с `types/tournament.types.ts` и
`stageForm.ts`. До её выхода этот тест типизационно красный по строке 120 и зелёный по поведению — он не читает
`ffa_scoring` ни в одном ожидании (ожидания файла: `getFfaStage` вызван с `(84, 10)`, подписи строк расписания,
`invalidateWorkspace`).

- [ ] **Шаг 8. Запустить тесты задачи — PASS.**

```
cd frontend && bunx vitest run src/services/ffa.service.test.ts
cd frontend && bunx vitest run stageEditor.ffaRoundSchedule
```

Ожидаемо: `ffa stage reads` — 2 passed; `stageEditor.ffaRoundSchedule` — все существующие тесты passed (фикстура
обновлена, поведение не изменилось; фильтр задан подстрокой имени файла, потому что путь содержит `[id]` —
квадратные скобки vitest разбирает как regex-класс).

Красными до своей задачи остаются `src/components/ffa/FfaLobbyTable.behavior.test.tsx` (задача 10) и
`src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx` (задача 11): их фикстуры собирают `FfaRules` и
`FfaLobbyRow` в старой форме. Это ожидаемо для промежуточного коммита релиза.

- [ ] **Шаг 9. Коммит.**

```
git add frontend/src/types/ffa.types.ts \
        frontend/src/services/ffa.service.ts \
        frontend/src/services/ffa.service.test.ts \
        frontend/src/lib/tournament/query-keys.ts \
        "frontend/src/app/admin/tournaments/[id]/matches/lobbies/page.tsx" \
        "frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaRoundSchedule.behavior.test.tsx"
git commit -m "feat(ffa): read organizer columns from the admin stage endpoint"
```

---

### Задача 10. Фронт: `FfaLobbyTable` — итоги публичных столбцов, очки игры, легенда

**Files:**

- Modify `frontend/src/components/ffa/FfaLobbyTable.tsx:11` (импорт типов), `:82-97` (подготовка столбцов и
  легенды), `:117-119` (заголовок столбца счёта), `:143-151` (пропсы `LobbyRow`), `:154` (`colSpan`),
  `:173-176` (легенда), `:204-220` (сигнатура `LobbyRow`), `:281-308` (ячейка счёта и ячейки игр)
- Modify `frontend/src/components/ffa/FfaLobbyTable.behavior.test.tsx:14-15` (шапка файла), `:31-40`
  (`game`), `:42-58` (`row`), `:60-76` (`lobby`), `:187-188` (пустая ячейка), `:214` (игра за границей серии),
  `:226-243` (блок про столбец счёта)
- Modify `frontend/src/i18n/messages/en.json:6365`, `:6377-6380`
- Modify `frontend/src/i18n/messages/ru.json:6365`, `:6377-6380`
- Tests: `frontend/src/components/ffa/FfaLobbyTable.behavior.test.tsx`,
  `frontend/src/i18n/messages.parity.test.ts`

**Interfaces:**

_Consumes_ (задача 9): `FfaLobby`, `FfaLobbyRow`, `FfaGameCell`, `FfaColumn`, `FfaRules` из
`@/types/ffa.types`.

_Produces_: `export default function FfaLobbyTable({ lobby }: Readonly<{ lobby: FfaLobby }>)` и
`export function lobbyGamePositions(lobby: FfaLobby): number[]` — публичные сигнатуры не меняются, поэтому три
её хоста (`FfaStagePanel.tsx:120`, `(site)/encounters/[id]/page.tsx:494`,
`admin/.../matches/lobbies/page.tsx:127`) правок не требуют.

i18n, итоговый набор ключей `ffa.*` после задачи: добавлены `legendCells` (новая форма, без аргумента),
`legendFormula` (аргумент `formula`, тег `code`), `legendPlacement` (аргумент `placements`); удалены
`legendPoints`, `legendPointsPlacement`, `legendPointsScore`, `colScore`.

Что важно сохранить из `66df6ed2` (переработка таблицы) — всё остаётся дословно: липкий столбец команды
(`STICKY_TEAM`, строки 186-187), непрозрачные тона строк (`ROW_TONE`, 197-202), маркер кластера `=` и
`ffa.tieCluster` (249-256), замок закреплённого места (257-265), правило «до первой сыгранной игры нет ни мест,
ни вердиктов» (`ranked`, строки 62-66 и 247), линия отсечки на `advance_count` (152-168), легенда отдельным
абзацем под таблицей (173-176).

---

- [ ] **Шаг 1. Переписать тест под новый контракт таблицы.**

Существующий блок `describe("ffa lobby score column")` (строки 226-243) пинит удалённое поведение
(`rules.score_label` и подстановку `en.ffa.colScore`) — он **удаляется целиком** и заменяется блоком про
столбцы. Фикстуры `game`/`row`/`lobby` (31-76) переводятся на `stats`. Остальные блоки (отсечка, ничьи, пустые
ячейки) сохраняются — они про другое.

Заменить `frontend/src/components/ffa/FfaLobbyTable.behavior.test.tsx:14-15`:

```
14:// 4. The score column is headed by what the organizer says it counts
15://    (`rules.score_label`, e.g. "Kills"), falling back to a translated "Score".
```

на:

```
// 4. The table totals one column per PUBLIC column of the stage, headed by the
//    organizer's own label, and never prints a hidden column — the organizer's
//    own screens render this very table from the admin read, which carries the
//    hidden values, so the component is the one place that can guarantee it.
// 5. A played cell says what it paid: the place, the points, and — for a reader
//    who cannot see two stacked numbers — the public values of that game.
```

Заменить `frontend/src/components/ffa/FfaLobbyTable.behavior.test.tsx:31-76` (`game`, `row`, `lobby`):

```tsx
function game(position: number, extra: Partial<FfaGameCell> = {}): FfaGameCell {
  return {
    position,
    state: "confirmed",
    placement: position,
    points: 5,
    stats: { kills: 10 },
    ...extra
  };
}

function row(slot: number, extra: Partial<FfaLobbyRow> = {}): FfaLobbyRow {
  return {
    team_id: slot,
    team_name: `Team ${slot}`,
    team_image_url: null,
    slot,
    position: slot,
    tie_group: null,
    is_pinned: false,
    points: 10 - slot,
    games_played: 1,
    wins: 0,
    stats: { kills: 42 },
    games: [game(1)],
    ...extra
  };
}

/** The default stage: one public column, places paid, so places are required. */
function rules(extra: Partial<FfaRules> = {}): FfaRules {
  return {
    columns: [{ key: "kills", label: "Kills", public: true, better: "higher" }],
    placement_points: [10, 6, 3],
    formula: "place_pts + kills",
    requires_placement: true,
    ...extra
  };
}

function lobby(rows: FfaLobbyRow[], extra: Partial<FfaLobby> = {}): FfaLobby {
  return {
    encounter_id: 500,
    tournament_id: 1,
    stage_id: 7,
    stage_item_id: 100,
    name: "Lobby A",
    status: "open",
    result_status: "none",
    best_of: 1,
    scheduled_at: null,
    advance_count: 2,
    rules: rules(),
    rows,
    ...extra
  };
}
```

Импорт типов на строке 22 становится:

```tsx
import type { FfaGameCell, FfaLobby, FfaLobbyRow, FfaRules } from "@/types/ffa.types";
```

Заменить `:187-188` (две строки фикстуры несыгранной игры):

```tsx
          row(1, { games: [game(1), game(2, { state: null, placement: null, points: null, stats: null })] }),
          row(2, { games: [game(1), game(2, { state: null, placement: null, points: null, stats: null })] })
```

Заменить `:214` (игра, записанная за пределами укороченной серии):

```tsx
      lobby([row(1, { games: [game(1), game(2), game(3, { placement: 1, points: 31, stats: { kills: 31 } })] })], {
```

Заменить `:226-243` целиком на:

```tsx
describe("ffa lobby stat columns", () => {
  it("totals one column per public column, headed by the organizer's label", async () => {
    await mount(
      lobby([row(1, { stats: { kills: 29, assists: 4 } })], {
        rules: rules({
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" },
            { key: "assists", label: "Assists", public: true, better: "higher" }
          ]
        })
      })
    );

    // The label the organizer wrote, verbatim, and one column per public key —
    // the header row is not pinned whole here, because the `#` and status heads
    // carry sr-only text that says nothing about columns.
    expect(headers()).toContain("Kills");
    expect(headers()).toContain("Assists");
    expect(statCell(1, "kills")).toBe("29");
    expect(statCell(1, "assists")).toBe("4");
  });

  it("prints neither the header nor the values of a hidden column", async () => {
    // The organizer's own lobby page renders this table from the ADMIN read,
    // which still carries `deaths`. The same component renders the public
    // bracket, so dropping the column here is what keeps a hidden value from
    // ever reaching a spectator's DOM.
    await mount(
      lobby([row(1, { stats: { kills: 29, deaths: 777 } })], {
        rules: rules({
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" },
            { key: "deaths", label: "Deaths", public: false, better: "lower" }
          ]
        })
      })
    );

    expect(headers()).not.toContain("Deaths");
    expect(statCell(1, "deaths")).toBeNull();
    expect(container.textContent).not.toContain("777");
  });

  it("totals a column the team never scored as zero", async () => {
    // A column added mid-stage: the games already played carry no key for it,
    // and an empty cell there would read as "not counted yet".
    await mount(lobby([row(1, { stats: {} })]));

    expect(statCell(1, "kills")).toBe("0");
  });
});

describe("ffa lobby played cells", () => {
  it("prints the place above the points the game paid", async () => {
    await mount(lobby([row(1, { games: [game(1, { placement: 3, points: 12.5 })] })]));

    const cell = container.querySelector("tbody tr [data-ffa-game='1']");
    expect(cell?.textContent).toContain("3");
    // Fractional points are the point of a custom formula; a rounded "12" or a
    // padded "12.0" would both be a different number than the one that scored.
    expect(cell?.textContent).toContain("12.5");
  });

  it("describes a cell with its place, points and public values", async () => {
    await mount(
      lobby([row(1, { games: [game(1, { placement: 3, points: 16, stats: { kills: 6, deaths: 2 } })] })], {
        rules: rules({
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" },
            { key: "deaths", label: "Deaths", public: false, better: "lower" }
          ]
        })
      })
    );

    const described = container.querySelector("tbody tr [data-ffa-game='1'] [title]");
    expect(described?.getAttribute("title")).toBe(
      `${en.ffa.colPlace} 3, ${en.ffa.colPoints} 16, Kills 6`
    );
    expect(described?.textContent).toContain(`${en.ffa.colPlace} 3, ${en.ffa.colPoints} 16, Kills 6`);
    expect(described?.getAttribute("title")).not.toContain("Deaths");
  });
});

describe("ffa lobby legend", () => {
  it("shows the formula the lobby is actually scored by", async () => {
    // The risk the legend answers (spec §12): a formula edited mid-stage moves
    // every place silently. The table prints the rule it was scored by.
    await mount(lobby([row(1)], { rules: rules({ formula: "place_pts + kills * 2 - deaths" }) }));

    expect(container.querySelector("code")?.textContent).toBe("place_pts + kills * 2 - deaths");
    expect(container.textContent).toContain("10 · 6 · 3");
  });

  it("says nothing about place points when the stage pays none", async () => {
    await mount(lobby([row(1)], { rules: rules({ placement_points: [], formula: "kills" }) }));

    expect(container.textContent).not.toContain("10 · 6 · 3");
    expect(container.querySelector("code")?.textContent).toBe("kills");
  });
});
```

Добавить рядом с хелпером `headers()` (после строки 100) читалку итоговой ячейки:

```tsx
/** The total printed for one column on one row, or null when there is none. */
function statCell(slot: number, key: string) {
  const rows = [...container.querySelectorAll("tbody tr")];
  const node = rows[slot - 1]?.querySelector(`[data-ffa-stat="${key}"]`);
  return node ? node.textContent : null;
}
```

- [ ] **Шаг 2. Запустить тест — падение.**

```
cd frontend && bunx vitest run src/components/ffa/FfaLobbyTable.behavior.test.tsx
```

Ожидаемо: файл падает на сборке — `TypeError: Cannot read properties of undefined (reading 'trim')` в
`FfaLobbyTable.tsx:83` (`lobby.rules.score_label?.trim()` — поля больше нет, но старый компонент его читает) во
всех тестах, плюс `ffa lobby stat columns`/`ffa lobby played cells`/`ffa lobby legend` не находят ни
`[data-ffa-stat]`, ни `code`.

- [ ] **Шаг 3. Переписать таблицу.**

`frontend/src/components/ffa/FfaLobbyTable.tsx:11` — импорт типов:

```ts
import type { FfaColumn, FfaGameCell, FfaLobby, FfaLobbyRow } from "@/types/ffa.types";
```

`FfaLobbyTable.tsx:82-97` сейчас:

```tsx
82:  const positions = lobbyGamePositions(lobby);
83:  const scoreLabel = lobby.rules.score_label?.trim() || t("ffa.colScore");
84:  const columnCount = 5 + positions.length + (showStatus ? 1 : 0);
85:
86:  // What turns a game cell and the points column back into numbers a reader
87:  // can check: the lobby's own rules, not a stage-wide description.
88:  const placementPoints = lobby.rules.placement_points.join(" · ");
89:  const multiplier = lobby.rules.score_points;
90:  const pointsLegend =
91:    placementPoints && multiplier
92:      ? t("ffa.legendPoints", { placements: placementPoints, label: scoreLabel, multiplier })
93:      : placementPoints
94:        ? t("ffa.legendPointsPlacement", { placements: placementPoints })
95:        : multiplier
96:          ? t("ffa.legendPointsScore", { label: scoreLabel, multiplier })
97:          : null;
```

Заменить на:

```tsx
  const positions = lobbyGamePositions(lobby);
  // Only the organizer's PUBLIC columns are printed, and the filter lives here
  // rather than at the read: this one component renders the public bracket, the
  // public lobby page AND the organizer's lobby editor, and the editor feeds it
  // the admin read, which still carries the hidden columns. Filtering at the
  // component is what makes "a spectator never sees a hidden value" a property
  // of the markup instead of a property of whoever picked the endpoint.
  const columns = lobby.rules.columns.filter((column) => column.public);
  const columnCount = 4 + columns.length + positions.length + (showStatus ? 1 : 0);

  // What turns the numbers back into something a reader can check: the rule
  // this lobby was actually scored by, printed as the organizer wrote it.
  const placementPoints = lobby.rules.placement_points.join(" · ");
```

`FfaLobbyTable.tsx:117-119` — заголовок столбца счёта:

```tsx
117:            <TableHead scope="col" className="w-20 text-right whitespace-nowrap">
118:              {scoreLabel}
119:            </TableHead>
```

Заменить на:

```tsx
            {columns.map((column) => (
              <TableHead
                key={column.key}
                scope="col"
                className="w-20 text-right whitespace-nowrap"
              >
                {column.label}
              </TableHead>
            ))}
```

`FfaLobbyTable.tsx:150` — проп строки:

```tsx
150:                scoreLabel={scoreLabel}
```

Заменить на:

```tsx
                columns={columns}
```

`FfaLobbyTable.tsx:173-176` — легенда:

```tsx
173:      <p className="flex flex-wrap gap-x-4 gap-y-1 px-2 pt-3 text-caption text-[color:var(--aqt-fg-dim)]">
174:        <span>{t("ffa.legendCells", { label: scoreLabel })}</span>
175:        {pointsLegend && <span>{pointsLegend}</span>}
176:      </p>
```

Заменить на:

```tsx
      <p className="flex flex-wrap gap-x-4 gap-y-1 px-2 pt-3 text-caption text-[color:var(--aqt-fg-dim)]">
        <span>{t("ffa.legendCells")}</span>
        <span>
          {t.rich("ffa.legendFormula", {
            formula: lobby.rules.formula,
            code: (chunks) => (
              <code className="font-[family-name:var(--aqt-data)]">{chunks}</code>
            )
          })}
        </span>
        {placementPoints && (
          <span>{t("ffa.legendPlacement", { placements: placementPoints })}</span>
        )}
      </p>
```

`FfaLobbyTable.tsx:204-220` — сигнатура `LobbyRow`:

```tsx
204:function LobbyRow({
205:  row,
206:  positions,
207:  ranked,
208:  advancing,
209:  tied,
210:  showStatus,
211:  scoreLabel
212:}: Readonly<{
213:  row: FfaLobbyRow;
214:  positions: number[];
215:  ranked: boolean;
216:  advancing: boolean;
217:  tied: boolean;
218:  showStatus: boolean;
219:  scoreLabel: string;
220:}>) {
```

Заменить на:

```tsx
function LobbyRow({
  row,
  positions,
  columns,
  ranked,
  advancing,
  tied,
  showStatus
}: Readonly<{
  row: FfaLobbyRow;
  positions: number[];
  /** The public columns, already filtered by the table. */
  columns: FfaColumn[];
  ranked: boolean;
  advancing: boolean;
  tied: boolean;
  showStatus: boolean;
}>) {
```

`FfaLobbyTable.tsx:281-308` — ячейка счёта и ячейки игр:

```tsx
281:      <TableCell className="aqt-tnum text-right text-[color:var(--aqt-fg-muted)]">
282:        {row.score}
283:      </TableCell>
284:      {positions.map((position) => {
…
308:      })}
```

Заменить на:

```tsx
      {columns.map((column) => (
        <TableCell
          key={column.key}
          data-ffa-stat={column.key}
          className="aqt-tnum text-right text-[color:var(--aqt-fg-muted)]"
        >
          {/* A key the team never scored is absent from the totals, and absent
              means zero (spec §3.2) — a column added mid-stage must not blank
              out the games already played. */}
          {formatFfaNumber(row.stats[column.key] ?? 0)}
        </TableCell>
      ))}
      {positions.map((position) => {
        const cell = gameAt.get(position);
        return (
          <TableCell key={position} className="text-center" data-ffa-game={position}>
            {/* A game nobody has entered renders NOTHING. A `0` here would read
                as "played it, scored nothing" — a different claim entirely. */}
            {cell?.state == null ? null : <GameCell cell={cell} columns={columns} />}
          </TableCell>
        );
      })}
```

Добавить после `lobbyGamePositions` (после строки 32) две новые единицы:

```tsx
/**
 * A number the organizer entered or the formula produced, printed as written.
 *
 * Game points are a custom expression rounded to four decimals server-side, so
 * a fixed width is wrong in both directions: `16.0` beside a place number is
 * noise, and `12` in place of `12.5` is a different number. Two decimals is
 * what a game cell holds; trailing zeros are dropped so the common whole number
 * stays one token wide. The Pts column keeps its own `toFixed(1)` — a season
 * total is read down a column, where a ragged decimal point is the noise.
 */
function formatFfaNumber(value: number): string {
  return String(Number(value.toFixed(2)));
}

/**
 * One played game: the place above, the points it paid below.
 *
 * Two stacked bare numbers are read aloud as "3 16" and say nothing about where
 * 16 came from, so the cell carries ONE sentence — place, points and every
 * public value of that game — as its `title` and as the only thing a screen
 * reader is given. The visible numbers are `aria-hidden` rather than labelled
 * one by one: labelled, the cell would announce the place, then the points,
 * then the very same numbers again inside the description.
 */
function GameCell({ cell, columns }: Readonly<{ cell: FfaGameCell; columns: FfaColumn[] }>) {
  const t = useTranslations();
  const parts = [`${t("ffa.colPlace")} ${cell.placement ?? "—"}`];
  if (cell.points != null) parts.push(`${t("ffa.colPoints")} ${formatFfaNumber(cell.points)}`);
  for (const column of columns) {
    const value = cell.stats?.[column.key];
    if (value != null) parts.push(`${column.label} ${formatFfaNumber(value)}`);
  }
  const description = parts.join(", ");

  return (
    <span className="inline-flex flex-col items-center leading-tight" title={description}>
      <span aria-hidden className="aqt-tnum text-caption font-semibold text-[color:var(--aqt-fg)]">
        {cell.placement ?? "—"}
      </span>
      {cell.points != null && (
        <span aria-hidden className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
          {formatFfaNumber(cell.points)}
        </span>
      )}
      <span className="sr-only">{description}</span>
    </span>
  );
}
```

- [ ] **Шаг 4. Обновить словари.**

`frontend/src/i18n/messages/en.json:6365` — удалить строку:

```json
    "colScore": "Score",
```

(ключ `ffa.colScore` больше не читается ниоткуда: единственными его читателями были `FfaLobbyTable.tsx:83` и
тест таблицы; одноимённый `users.matches.colScore` на строке 3840 — другой ключ и остаётся.)

`frontend/src/i18n/messages/en.json:6377-6380` — заменить четыре строки:

```json
    "legendCells": "Game cells: place / {label}",
    "legendPoints": "Points = place points ({placements}) + {label} × {multiplier}",
    "legendPointsPlacement": "Points = place points ({placements})",
    "legendPointsScore": "Points = {label} × {multiplier}",
```

на три:

```json
    "legendCells": "Game cells: place / points",
    "legendFormula": "Points = <code>{formula}</code>",
    "legendPlacement": "Place points: {placements}",
```

`frontend/src/i18n/messages/ru.json:6365` — удалить строку:

```json
    "colScore": "Счёт",
```

`frontend/src/i18n/messages/ru.json:6377-6380` — заменить четыре строки:

```json
    "legendCells": "Ячейка игры: место / {label}",
    "legendPoints": "Очки = очки за место ({placements}) + {label} × {multiplier}",
    "legendPointsPlacement": "Очки = очки за место ({placements})",
    "legendPointsScore": "Очки = {label} × {multiplier}",
```

на три:

```json
    "legendCells": "Ячейка игры: место / очки",
    "legendFormula": "Очки = <code>{formula}</code>",
    "legendPlacement": "Очки за место: {placements}",
```

- [ ] **Шаг 5. Запустить тесты — PASS.**

```
cd frontend && bunx vitest run src/components/ffa/FfaLobbyTable.behavior.test.tsx
cd frontend && bunx vitest run src/i18n/messages.parity.test.ts
```

Ожидаемо: таблица — все тесты passed (отсечка, ничьи, пустые ячейки, столбцы, ячейки игр, легенда);
`messages.parity` — passed (одинаковые правки в обоих словарях, `{ missingInRu: [], missingInEn: [] }`).

- [ ] **Шаг 6. Коммит.**

```
git add frontend/src/components/ffa/FfaLobbyTable.tsx \
        frontend/src/components/ffa/FfaLobbyTable.behavior.test.tsx \
        frontend/src/i18n/messages/en.json \
        frontend/src/i18n/messages/ru.json
git commit -m "feat(ffa): total the organizer's public columns in the lobby table"
```

---

### Задача 11. Фронт: `FfaGameResultsDialog` — поле на столбец, `requires_placement`

**Files:**

- Modify `frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx:15` (импорт типов), `:50-65`
  (док-комментарий), `:84-98` (правила и черновик), `:122-128` (сеттер и строки), `:140-153` (submit),
  `:167-189` (сетка полей и подсказка), `:212-250` (`FieldRow`)
- Modify `frontend/src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx:5-7` (шапка), `:52-67`
  (`row`), `:69-85` (`lobby`), `:142-161`, `:163-188`, `:190-206`, `:208-229` (все четыре теста)
- Tests: `frontend/src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx`

**Interfaces:**

_Consumes_ (задача 9): `FfaLobby.rules.columns: FfaColumn[]` (ПОЛНЫЙ набор — диалог живёт на админской
странице, которая читает `getStageAdmin`), `FfaLobby.rules.requires_placement`,
`FfaGameCell.stats: Record<string, number> | null`, `FfaGameResultLineInput`.

_Produces_: `ffaService.setGameResults(encounterId, position, { results: FfaGameResultLineInput[], reason })`
— строка `{team_id, placement, stats}` из §7.1 спеки.

Язык копирайта: диалог сегодня **англоязычный хардкодом** (`"Team"`, `"Place"`, `` `Enter game ${position}` ``,
строки 160-204) и через i18n берёт только сообщения об ошибках `ffa.errors.*`. Задача сохраняет эту границу:
новые подписи — по-английски, пометка скрытого столбца — `hidden from viewers`.

Граница с задачей 12: хук `useFfaErrorMessage` (`FfaGameResultsDialog.tsx:26-40`) в этой задаче **не
меняется** — его дорабатывает задача 12 (интерполяция `offset`/`name` для ошибок формулы). Задача 11 правит
только тело `FfaGameResultsDialog` (строки 66+) и `FieldRow`.

---

- [ ] **Шаг 1. Переписать тест диалога под столбцы.**

Все четыре существующих теста пинят удалённое поле `score` (подпись поля `"Score for Team N"`, полезная
нагрузка `{team_id, placement, score}`) — они переписываются под столбцы, а не удаляются: их утверждения
(строка на каждую команду, пустое ≠ ноль, читаемая ошибка, причина у исправления) остаются в силе.

Заменить `frontend/src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx:5-7`:

```
5:// 1. One line per participant leaves for the server, and a blank score is not
6://    one of them: a lobby is scored as a whole, so a team the organizer has not
7://    got to yet must hold the request back rather than be recorded on zero.
```

на:

```
// 1. One line per participant leaves for the server, carrying a value for every
//    column of the stage — including the columns a spectator never sees — and a
//    blank is not one of them: a lobby is scored as a whole, so a team the
//    organizer has not got to yet must hold the request back rather than be
//    recorded on zero.
```

Заменить `:52-85` (`row` и `lobby`):

```tsx
function row(slot: number, games: FfaGameCell[] = []): FfaLobbyRow {
  return {
    team_id: slot,
    team_name: `Team ${slot}`,
    team_image_url: null,
    slot,
    position: slot,
    tie_group: null,
    is_pinned: false,
    points: 0,
    games_played: games.length,
    wins: 0,
    stats: {},
    games
  };
}

/**
 * The stage as the ADMIN read answers it: one public column and one hidden one,
 * places paid. The dialog is only ever mounted from a screen that reads
 * `getStageAdmin`, which is why `deaths` is here at all.
 */
function rules(extra: Partial<FfaRules> = {}): FfaRules {
  return {
    columns: [
      { key: "kills", label: "Kills", public: true, better: "higher" },
      { key: "deaths", label: "Deaths", public: false, better: "lower" }
    ],
    placement_points: [10, 6, 3],
    formula: "place_pts + kills - deaths",
    requires_placement: true,
    ...extra
  };
}

function lobby(rows: FfaLobbyRow[], extra: Partial<FfaLobby> = {}): FfaLobby {
  return {
    encounter_id: 500,
    tournament_id: 84,
    stage_id: 7,
    stage_item_id: 100,
    name: "Lobby A",
    status: "open",
    result_status: "none",
    best_of: 3,
    scheduled_at: null,
    advance_count: 2,
    rules: rules(),
    rows,
    ...extra
  };
}
```

Импорт типов на строке 21 становится:

```tsx
import type { FfaGameCell, FfaLobby, FfaLobbyRow, FfaRules } from "@/types/ffa.types";
```

Заменить тела всех четырёх тестов, `:141-230` (блок `describe("entering an FFA game")` целиком):

```tsx
describe("entering an FFA game", () => {
  it("sends a value for every column of every team, hidden ones included", async () => {
    await mount(lobby([row(1), row(2), row(3)]), 2);

    for (const slot of [1, 2, 3]) {
      await type(field(`Place for Team ${slot}`), String(slot));
      await type(field(`Kills for Team ${slot}`), String(12 - slot));
      await type(field(`Deaths for Team ${slot}`), String(slot));
    }
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 2, {
      results: [
        { team_id: 1, placement: 1, stats: { kills: 11, deaths: 1 } },
        { team_id: 2, placement: 2, stats: { kills: 10, deaths: 2 } },
        { team_id: 3, placement: 3, stats: { kills: 9, deaths: 3 } }
      ],
      reason: null
    });
  });

  it("offers the hidden column and says it is not shown to spectators", async () => {
    await mount(lobby([row(1)]), 1);

    // The value exists and is entered here; what `public: false` buys is that
    // the public read never answers it — which the organizer has to be told,
    // because this form is the only place the column is visible at all.
    const hidden = field("Deaths for Team 1");
    expect(hidden).not.toBeNull();
    expect(document.body.textContent).toContain("hidden from viewers");
  });

  it("holds the request back while a column is blank, rather than sending a zero", async () => {
    // A forgotten value used to leave as `0` — a line the server accepts, so
    // `ffa_result_missing_stat` could never catch it. Nothing is sent until the
    // zero is typed on purpose.
    await mount(lobby([row(1), row(2)]), 2);

    await type(field("Kills for Team 1"), "10");
    await type(field("Deaths for Team 1"), "1");
    await type(field("Kills for Team 2"), "7");
    await save();

    expect(setGameResults).not.toHaveBeenCalled();
    expect(field("Deaths for Team 2").getAttribute("aria-invalid")).toBe("true");
    expect(field("Kills for Team 2").getAttribute("aria-invalid")).toBeNull();

    await type(field("Deaths for Team 2"), "0");
    await type(field("Place for Team 1"), "1");
    await type(field("Place for Team 2"), "2");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 2, {
      results: [
        { team_id: 1, placement: 1, stats: { kills: 10, deaths: 1 } },
        { team_id: 2, placement: 2, stats: { kills: 7, deaths: 0 } }
      ],
      reason: null
    });
  });

  it("asks for a place only when the stage's formula reads one", async () => {
    await mount(lobby([row(1)], { rules: rules({ formula: "kills - deaths", requires_placement: false }) }), 1);

    expect(document.body.textContent).toContain("Place (optional)");

    await type(field("Kills for Team 1"), "4");
    await type(field("Deaths for Team 1"), "0");
    await save();

    // No place typed, and none invented: the server derives it from the points.
    expect(setGameResults).toHaveBeenCalledWith(500, 1, {
      results: [{ team_id: 1, placement: null, stats: { kills: 4, deaths: 0 } }],
      reason: null
    });
  });

  it("shows the sentence for the code the server refused with", async () => {
    setGameResults.mockRejectedValue(
      new ApiError(422, [
        { msg: "Each place from 1 to N must be taken exactly once", code: "ffa_result_invalid_placement" }
      ])
    );
    await mount(lobby([row(1), row(2), row(3)]), 1);

    for (const slot of [1, 2, 3]) {
      await type(field(`Kills for Team ${slot}`), "4");
      await type(field(`Deaths for Team ${slot}`), "0");
    }
    await type(field("Place for Team 1"), "1");
    // Two firsts: the server is the one that knows this is not a permutation.
    await type(field("Place for Team 2"), "1");
    await type(field("Place for Team 3"), "2");
    await save();

    expect(document.body.textContent).toContain(en.ffa.errors.ffa_result_invalid_placement);
  });

  it("starts a correction from the values being corrected", async () => {
    const played = (slot: number) =>
      row(slot, [
        {
          position: 1,
          state: "confirmed",
          placement: slot,
          points: 5,
          stats: { kills: 5, deaths: slot }
        }
      ]);
    await mount(lobby([played(1), played(2), played(3)]), 1);

    expect(field("Kills for Team 2").value).toBe("5");
    expect(field("Deaths for Team 2").value).toBe("2");

    await save();

    expect(setGameResults).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(en.ffa.errors.ffa_reason_required);

    await type(field("Reason"), "Scoreboard screenshot was misread");
    await save();

    expect(setGameResults).toHaveBeenCalledWith(500, 1, {
      results: [
        { team_id: 1, placement: 1, stats: { kills: 5, deaths: 1 } },
        { team_id: 2, placement: 2, stats: { kills: 5, deaths: 2 } },
        { team_id: 3, placement: 3, stats: { kills: 5, deaths: 3 } }
      ],
      reason: "Scoreboard screenshot was misread"
    });
  });
});
```

- [ ] **Шаг 2. Запустить тест — падение.**

```
cd frontend && bunx vitest run src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx
```

Ожидаемо: каждый тест падает на `Error: no field labelled Kills for Team 1` (хелпер `field`, строка 107) —
диалог всё ещё рисует одно поле `Score for Team N`; тест про скрытый столбец падает на отсутствии
`hidden from viewers`.

- [ ] **Шаг 3. Переписать диалог.**

`FfaGameResultsDialog.tsx:15` — импорт типов:

```ts
import type { FfaGameResultLineInput, FfaGameResultsInput, FfaLobby } from "@/types/ffa.types";
```

`FfaGameResultsDialog.tsx:56-60` (часть док-комментария про место) сейчас:

```
56: * lobby, and an untouched row still leaves as a line scoring zero rather than
57: * as no line at all.
58: *
59: * Whether a place is required is the stage's formula, not a preference: with
60: * `placement_points` the server demands a permutation of 1..N, and without it
61: * the places are derived from the scores, which is why they are optional there.
```

Заменить строки 59-61 на:

```
 * Whether a place is required is the stage's formula, not a preference: a
 * formula that reads `place`/`place_pts` makes the server demand a permutation
 * of 1..N (`rules.requires_placement`), and a formula that does not lets the
 * server derive the places from the points, which is why they are optional
 * there. The columns are the organizer's too — every one of them, including the
 * ones a spectator never sees, because this form is where they are entered.
```

`FfaGameResultsDialog.tsx:84-98` сейчас:

```tsx
84:  const paysForPlacement = lobby.rules.placement_points.length > 0;
85:  const scoreLabel = lobby.rules.score_label?.trim() || "Score";
86:
87:  const [draft, setDraft] = useState<Record<number, { placement: number | null; score: number | null }>>(
88:    () =>
89:      Object.fromEntries(
90:        rows.map((row) => [
91:          row.team_id,
92:          {
93:            placement: cells.get(row.team_id)?.placement ?? null,
94:            score: cells.get(row.team_id)?.score ?? null
95:          }
96:        ])
97:      )
98:  );
```

Заменить на:

```tsx
  const requiresPlacement = lobby.rules.requires_placement;
  // EVERY column, not the public ones: the dialog is mounted from a screen that
  // reads `getStageAdmin`, and a hidden column is a column the organizer still
  // has to type a number into.
  const columns = lobby.rules.columns;

  const [draft, setDraft] = useState<Record<number, TeamDraft>>(() =>
    Object.fromEntries(
      rows.map((row) => {
        const recorded = cells.get(row.team_id);
        return [
          row.team_id,
          {
            placement: recorded?.placement ?? null,
            // A correction starts from the numbers being corrected. A column
            // added after this game was played has no value here, and a blank
            // is the honest answer: nobody entered one.
            stats: Object.fromEntries(
              columns.map((column) => [column.key, recorded?.stats?.[column.key] ?? null])
            )
          }
        ];
      })
    )
  );
```

Добавить рядом с `FfaGameResultsDialogProps` (после строки 47) тип черновика:

```ts
/** One row of the form. A `null` is "not entered yet", never a zero. */
type TeamDraft = { placement: number | null; stats: Record<string, number | null> };
```

`FfaGameResultsDialog.tsx:122-128` сейчас:

```tsx
122:  const setField = (teamId: number, field: "placement" | "score", value: number | null) =>
123:    setDraft((current) => ({ ...current, [teamId]: { ...current[teamId], [field]: value } }));
124:
125:  const lines = rows.map((row) => ({ team_id: row.team_id, ...draft[row.team_id] }));
126:  const scored = lines.filter(
127:    (line): line is typeof line & { score: number } => line.score !== null
128:  );
```

Заменить на:

```tsx
  const setPlacement = (teamId: number, value: number | null) =>
    setDraft((current) => ({ ...current, [teamId]: { ...current[teamId], placement: value } }));

  const setStat = (teamId: number, key: string, value: number | null) =>
    setDraft((current) => ({
      ...current,
      [teamId]: { ...current[teamId], stats: { ...current[teamId].stats, [key]: value } }
    }));

  /** The first column left blank anywhere, which is what holds the submit. */
  const blankColumn = columns.find((column) =>
    rows.some((row) => draft[row.team_id].stats[column.key] === null)
  );

  const results: FfaGameResultLineInput[] = rows.map((row) => ({
    team_id: row.team_id,
    placement: draft[row.team_id].placement,
    stats: Object.fromEntries(
      columns.map((column) => [column.key, draft[row.team_id].stats[column.key] ?? 0])
    )
  }));
```

`FfaGameResultsDialog.tsx:140-153` сейчас:

```tsx
140:    if (scored.length < lines.length) {
141:      // A blank is NOT a zero. Sending it as one would record "played, scored
142:      // nothing" for a team the organizer simply had not got to yet — and the
143:      // server's own `ffa_result_missing_team` guard can never catch that,
144:      // because the line was there.
145:      setBlanksFlagged(true);
146:      // The label is whatever the organizer named the column ("Kills", "Points"),
147:      // so it is quoted as written rather than bent into a sentence around it.
148:      setError(`Enter ${scoreLabel} for every team — type 0 for a team that scored nothing.`);
149:      return;
150:    }
151:    setBlanksFlagged(false);
152:    setError(null);
153:    mutation.mutate({ results: scored, reason: trimmed || null });
```

Заменить на:

```tsx
    if (blankColumn) {
      // A blank is NOT a zero. Sending it as one would record "played, scored
      // nothing" for a team the organizer simply had not got to yet — and the
      // server's own `ffa_result_missing_stat` guard can never catch that,
      // because the key was there. A blank PLACE needs no guard here: it leaves
      // as `null` and the server answers `ffa_result_placement_required` when
      // the formula wants one, which is the one judgement it can make itself.
      setBlanksFlagged(true);
      // The label is whatever the organizer named the column ("Kills", "Deaths"),
      // so it is quoted as written rather than bent into a sentence around it.
      setError(
        `Enter ${blankColumn.label} for every team — type 0 for a team that scored nothing.`
      );
      return;
    }
    setBlanksFlagged(false);
    setError(null);
    mutation.mutate({ results, reason: trimmed || null });
```

`FfaGameResultsDialog.tsx:167-189` сейчас:

```tsx
167:      <div className="grid grid-cols-[1fr_5rem_6rem] items-center gap-2">
168:        <span className={EYEBROW_CLASS}>Team</span>
169:        <span className={EYEBROW_CLASS}>{paysForPlacement ? "Place" : "Place (optional)"}</span>
170:        <span className={EYEBROW_CLASS}>{scoreLabel}</span>
171:        {rows.map((row) => (
172:          <FieldRow
173:            key={row.team_id}
174:            name={row.team_name}
175:            placement={draft[row.team_id].placement}
176:            score={draft[row.team_id].score}
177:            scoreLabel={scoreLabel}
178:            scoreMissing={blanksFlagged && draft[row.team_id].score === null}
179:            onPlacement={(value) => setField(row.team_id, "placement", value)}
180:            onScore={(value) => setField(row.team_id, "score", value)}
181:          />
182:        ))}
183:      </div>
184:
185:      <p className="text-xs text-muted-foreground">
186:        {paysForPlacement
187:          ? `Places run 1 to ${rows.length}, each taken exactly once — this stage pays for them.`
188:          : "Leave the places empty to derive them from the scores; teams on the same score share a place."}
189:      </p>
```

Заменить на:

```tsx
      <div
        className="grid items-center gap-2 overflow-x-auto"
        // One column per stat, sized in the grid rather than in a class: the
        // stage decides how many there are, and a Tailwind class cannot be
        // built from a number at runtime.
        style={{ gridTemplateColumns: `minmax(7rem, 1fr) 5rem repeat(${columns.length}, 7rem)` }}
      >
        <span className={EYEBROW_CLASS}>Team</span>
        <span className={EYEBROW_CLASS}>{requiresPlacement ? "Place" : "Place (optional)"}</span>
        {columns.map((column) => (
          <span key={column.key} className={EYEBROW_CLASS}>
            {column.label}
            {!column.public && (
              // The organizer has to know which of these numbers a spectator
              // will never see — this form is the only place the column shows
              // up at all, so nothing else can tell them.
              <span className="block normal-case tracking-normal text-[10px] text-muted-foreground">
                hidden from viewers
              </span>
            )}
          </span>
        ))}
        {rows.map((row) => (
          <FieldRow
            key={row.team_id}
            name={row.team_name}
            columns={columns}
            placement={draft[row.team_id].placement}
            stats={draft[row.team_id].stats}
            flagBlanks={blanksFlagged}
            onPlacement={(value) => setPlacement(row.team_id, value)}
            onStat={(key, value) => setStat(row.team_id, key, value)}
          />
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        {requiresPlacement
          ? `Places run 1 to ${rows.length}, each taken exactly once — this stage's formula pays for them.`
          : "Leave the places empty to derive them from the points; teams on the same points share a place."}
      </p>
```

`FfaGameResultsDialog.tsx:212-250` (`FieldRow`) заменить целиком на:

```tsx
function FieldRow({
  name,
  columns,
  placement,
  stats,
  flagBlanks,
  onPlacement,
  onStat
}: Readonly<{
  name: string;
  columns: FfaColumn[];
  placement: number | null;
  stats: Record<string, number | null>;
  flagBlanks: boolean;
  onPlacement: (value: number | null) => void;
  onStat: (key: string, value: number | null) => void;
}>) {
  return (
    <>
      <span className="truncate text-sm text-foreground">{name}</span>
      <NumberInput
        integer
        min={1}
        aria-label={`Place for ${name}`}
        value={placement}
        onValueChange={onPlacement}
      />
      {columns.map((column) => (
        <NumberInput
          key={column.key}
          // NOT `integer`: a column can be a damage share or a half-point
          // penalty, and the server takes any finite 0..1e9 (spec §3.2).
          min={0}
          max={1_000_000_000}
          aria-label={`${column.label} for ${name}`}
          aria-invalid={(flagBlanks && stats[column.key] === null) || undefined}
          className="aria-invalid:border-destructive"
          value={stats[column.key]}
          onValueChange={(value) => onStat(column.key, value)}
        />
      ))}
    </>
  );
}
```

Импорт `FfaColumn` добавляется в строку 15 вместе с остальными типами:

```ts
import type {
  FfaColumn,
  FfaGameResultLineInput,
  FfaGameResultsInput,
  FfaLobby
} from "@/types/ffa.types";
```

- [ ] **Шаг 4. Запустить тест — PASS.**

```
cd frontend && bunx vitest run src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx
```

Ожидаемо: 6 passed — строка на команду со всеми столбцами, пометка скрытого столбца, пустое ≠ ноль,
необязательное место при `requires_placement: false`, сообщение по коду сервера, исправление с подстановкой
`cell.stats` и обязательной причиной.

- [ ] **Шаг 5. Коммит.**

```
git add frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx \
        frontend/src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx
git commit -m "feat(ffa): enter one field per organizer column in the game dialog"
```

---

---

## Раздел D — редактор стадии, тай-брейки, i18n и документация

Задачи 12–14. Выходят одним релизом с задачами 2–11: промежуточный коммит может ломать соседние модули,
но тесты самой задачи обязаны проходить. Зависимости:

- задача 12 читает `FfaColumn` из `frontend/src/types/ffa.types.ts` — его вводит задача 9;
- задача 13 читает `StageForm.ffaColumns` — его вводит задача 12;
- задача 14 правит строки, которые вводят задачи 10–13.

---

### Задача 12. Редактор стадии: столбцы и формула

**Files:**

- Modify `frontend/src/types/tournament.types.ts:78-86` (`StageFfaScoring`)
- Modify `frontend/src/app/admin/tournaments/[id]/bracket/stageForm.ts:41-45,68-70,110-118,142-144`
- Modify `frontend/src/lib/ffa/scoring-presets.ts:1-53` (файл переписывается целиком)
- Modify `frontend/src/app/admin/tournaments/[id]/bracket/components/FfaScoringSection.tsx:1-168`
  (файл переписывается целиком)
- Modify `frontend/src/app/admin/tournaments/[id]/bracket/components/StageEditor.tsx:138-139,191-198,524-529`
- Modify `frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx:11,17-40` (только хук
  `useFfaErrorMessage` и его импорт; тело диалога — задача 11, согласовано с `PlanFrontendLobby`)
- Tests: `frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaScoring.behavior.test.tsx`
  (переписывается)

Бэкенд-часть отказа с позицией — `field_entry` кладёт `offset`/`name` плоско в запись `details["fields"]` —
делает задача 3; эта задача только читает.

**Interfaces:**

Consumes:

```ts
// frontend/src/types/ffa.types.ts (задача 9)
export type FfaColumnBetter = "higher" | "lower";
export interface FfaColumn { key: string; label: string; public: boolean; better: FfaColumnBetter }
// backend/shared/rpc/common.py (задача 3): запись details["fields"] несёт скалярный ctx плоско:
//   {"field": "ffa_scoring.formula", "msg": "…", "code": "ffa_formula_unknown_name", "offset": 13, "name": "kils"}
// frontend/src/lib/api/error.ts (существует)
export function errorBodyFields(body: unknown): Record<string, unknown>[];
export class ApiError extends Error { readonly status: number; readonly details: ApiErrorDetail[]; readonly body: unknown }
```

Produces:

```ts
// frontend/src/types/tournament.types.ts
export interface StageFfaScoring { columns: FfaColumn[]; placement_points: number[]; formula: string }

// frontend/src/app/admin/tournaments/[id]/bracket/stageForm.ts
export interface StageForm { /* … */ ffaPlacementPoints: number[]; ffaColumns: FfaColumn[]; ffaFormula: string }

// frontend/src/lib/ffa/scoring-presets.ts
export interface FfaScoringPreset { value: string; label: string; columns: FfaColumn[]; placementPoints: number[]; formula: string }
export const FFA_MAX_PLACES: 100;
export const FFA_MAX_COLUMNS: 10;
export const FFA_COLUMN_KEY_MAX: 24;
export const FFA_COLUMN_LABEL_MAX: 32;
export const FFA_FORMULA_MAX: 500;
export const FFA_FORMULA_VARIABLES: readonly ["place", "place_pts", "teams"];
export const FFA_FORMULA_FUNCTIONS: readonly ["min", "max", "abs", "round", "if"];
export const FFA_SCORING_PRESETS: readonly FfaScoringPreset[];
export function ffaScoringPresetOf(columns: readonly FfaColumn[], placementPoints: readonly number[], formula: string): string;
export function ordinalPlace(place: number): string;

// frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx
export function ffaErrorEntries(error: unknown): { code: string; offset?: number; name?: string }[];
export function useFfaErrorMessage(): (error: unknown) => string;

// frontend/src/app/admin/tournaments/[id]/bracket/components/FfaScoringSection.tsx
export function FfaScoringSection(props: Readonly<{ form: StageForm; onChange: (patch: Partial<StageForm>) => void; saveError?: unknown }>): JSX.Element;
```

- [ ] **Шаг 1. Переписать поведенческий тест редактора под новый контракт.**
      Файл `frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaScoring.behavior.test.tsx`.
      Тесты, которые пинят удаляемое поведение, — `saves the edited table, not the preset it started from` и
      `scores a place the preset never offered, and drops one it did` (оба ждут
      `{placement_points, score_points, score_label}`): переписываются под
      `{columns, placement_points, formula}`. Тест `offers the lobby tiebreakers, and only those` (строки 341-357)
      остаётся как есть — он всё ещё зелёный, потому что `ffa_score` убирает задача 13; она же его и перепишет.
      Тесты `keeps the block out of a stage that is not an FFA league`,
      `drops the FFA tiebreak order when the format stops being FFA`,
      `hides the duel-only points fields on an FFA stage`, `calls the best-of knob what it sets for a lobby`,
      `drops a per-round override the lobby would silently obey` не трогаются.

      Хунк 1 — шапка. Текущие строки 1-16:

```
// @vitest-environment happy-dom
//
// One claim: an FFA league's points table is editable, and it is saved for an
// FFA stage ONLY.
…
// there — how many games the lobby plays.
```

      Замена:

```tsx
// @vitest-environment happy-dom
//
// One claim: an FFA league's own scoring rule is editable, and it is saved for
// an FFA stage ONLY.
//
// The rule is three things the organizer writes: the columns entered per game
// (`kills`, `deaths`), the points a place pays, and the formula that turns both
// into a game's points. A preset is a starting point, not the rule — the
// organizer's real rule ("silver is worth 7 here, and deaths cost us") has to
// survive the save, which is pinned below through the REAL update mutation
// rather than through a number changing in a field.
//
// The formula is the one field of this editor the server can reject by
// POSITION, so the rejection is pinned too: it has to land on the formula
// field, naming what it stumbled over, not vanish into a toast.
//
// The rest of the editor has to agree that a lobby is not a duel: no
// win/draw/loss points (there is no opponent to beat), no Buchholz (there is no
// pairing to weigh), and the best-of knob renamed to what it actually sets
// there — how many games the lobby plays.
```

      Хунк 2 — импорты. Текущая строка 23 (`import en from "@/i18n/messages/en.json";`) дополняется строкой
      перед ней:

```tsx
import { ApiError } from "@/lib/api/error";
```

      Хунк 3 — фикстура. Текущие строки 130-141:

```tsx
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    ...regulation,
    challonge_id: null,
    challonge_slug: null,
    items: []
  };
}

/** A table left behind by a stage that used to be an FFA league. */
const SAVED_SCORING = { placement_points: [10, 6], score_points: 2, score_label: "Kills" };
```

      Замена:

```tsx
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: {
      columns: [{ key: "score", label: "Score", public: true, better: "higher" }],
      placement_points: [],
      formula: "score"
    },
    ...regulation,
    challonge_id: null,
    challonge_slug: null,
    items: []
  };
}

/** A rule left behind by a stage that used to be an FFA league. */
const SAVED_SCORING = {
  columns: [{ key: "kills", label: "Kills", public: true, better: "higher" as const }],
  placement_points: [10, 6],
  formula: "place_pts + kills"
};

/** What the server answers when the formula names a column that is not there. */
function unknownNameRejection(): ApiError {
  return new ApiError(
    422,
    [{ msg: "unknown name 'kils' at 13", code: "ffa_formula_unknown_name", field: "ffa_scoring.formula" }],
    {
      detail: "ffa_scoring.formula: unknown name 'kils' at 13",
      code: "unprocessable_entity",
      fields: [
        {
          field: "ffa_scoring.formula",
          msg: "unknown name 'kils' at 13",
          code: "ffa_formula_unknown_name",
          offset: 13,
          name: "kils"
        }
      ]
    }
  );
}
```

      Хунк 4 — хелперы ввода. Текущие строки 189-196:

```tsx
async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}
```

      Замена (тот же приём, но и для `<textarea>` — формула живёт в нём):

```tsx
async function type(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype =
    input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

/** The `<textarea>` a `<label>` points at. */
function area(label: string): HTMLTextAreaElement {
  const found = [...container.querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === label
  );
  const input = found?.htmlFor ? document.getElementById(found.htmlFor) : null;
  if (!(input instanceof HTMLTextAreaElement)) throw new Error(`no textarea labelled "${label}"`);
  return input;
}

/** The message a field points at through `aria-errormessage`. */
function errorFor(element: Element): string {
  const id = element.getAttribute("aria-errormessage");
  const node = id ? document.getElementById(id) : null;
  return (node?.textContent ?? "").trim();
}

/** The checkbox with this exact `aria-label`. */
function box(label: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`[role="checkbox"][aria-label="${label}"]`);
  if (!found) throw new Error(`no checkbox labelled "${label}"`);
  return found;
}
```

      Хунк 5 — первые два теста. Текущие строки 279-312:

```tsx
describe("Stage editor, FFA league scoring", () => {
  it("saves the edited table, not the preset it started from", async () => {
…
    expect(payload().ffa_scoring).toEqual({
      placement_points: [3],
      score_points: 1,
      score_label: null
    });
  });
```

      Замена:

```tsx
describe("Stage editor, FFA league scoring", () => {
  it("saves the edited rule, not the preset it started from", async () => {
    await mount(stage("ffa_league"));

    await click(select("Scoring preset"));
    await choose("Battle royale");
    // The organizer's own rule: silver is worth 7 here, not the preset's 6, and
    // the lobby also tracks deaths — which cost points and stay off the table.
    await type(field("2nd place"), "7");
    await click(only("Add column"));
    await type(field("Column 2 key"), "deaths");
    await type(field("Column 2 label"), "Deaths");
    await click(box("Show column 2 in the table"));
    await click(select("Column 2 direction"));
    await choose("Lower is better");
    await type(area("Points formula"), "place_pts + kills - deaths");
    await save();

    expect(updateStage).toHaveBeenCalledTimes(1);
    expect(payload().ffa_scoring).toEqual({
      columns: [
        { key: "kills", label: "Kills", public: true, better: "higher" },
        { key: "deaths", label: "Deaths", public: false, better: "lower" }
      ],
      placement_points: [10, 7, 5, 4, 3, 2, 1],
      formula: "place_pts + kills - deaths"
    });
  });

  it("scores a place the preset never offered, and drops a column it did", async () => {
    await mount(stage("ffa_league"));

    await click(select("Scoring preset"));
    await choose("Score only");
    // Score-only means no placement table at all; adding a place starts one.
    await click(only("Add place"));
    await type(field("1st place"), "3");
    // And a lobby can pay for the place alone: the column goes, the formula
    // stops reading it.
    await click(only("Remove column 1"));
    await type(area("Points formula"), "place_pts");
    await save();

    expect(payload().ffa_scoring).toEqual({
      columns: [],
      placement_points: [3],
      formula: "place_pts"
    });
  });

  it("stops at ten columns", async () => {
    await mount(
      stage("ffa_league", {
        ffa_scoring: {
          columns: Array.from({ length: 10 }, (_, index) => ({
            key: `c${index}`,
            label: `C${index}`,
            public: true,
            better: "higher" as const
          })),
          placement_points: [],
          formula: "c0"
        }
      })
    );

    // Ten is what the server stores (`FFA_MAX_COLUMNS`); an eleventh would be
    // rejected after the organizer had already typed it.
    expect(only("Add column").hasAttribute("disabled")).toBe(true);
  });

  it("puts the server's refusal on the formula field", async () => {
    await mount(stage("ffa_league"));

    await type(area("Points formula"), "place_pts + kils");
    updateStage.mockRejectedValueOnce(unknownNameRejection());
    await save();

    // A formula is refused by POSITION, and a toast cannot point at one: the
    // message belongs to the field, and has to name what the server stumbled on.
    expect(errorFor(area("Points formula"))).toContain("kils");
  });
```

- [ ] **Шаг 2. Запустить — красный.**
      `cd frontend && bunx vitest run stageEditor.ffaScoring.behavior`
      Ожидание: FAIL — `TypeError: Cannot read properties of undefined (reading 'length')` в
      `FfaScoringSection` (`form.ffaColumns` не существует), а в тестах-хелперах
      `Error: no control named "Add column"` / `no textarea labelled "Points formula"`.
      Плюс `bunx tsc --noEmit -p tsconfig.json` падает на `ffa_scoring: { columns: … }` — в
      `StageFfaScoring` нет поля `columns`.

- [ ] **Шаг 3. Тип блока стадии.** Текущие строки `frontend/src/types/tournament.types.ts:78-86`:

```ts
/** What an FFA league pays for, mirroring backend `FfaScoring`. */
export interface StageFfaScoring {
  /** What place `i + 1` is worth; a shorter list scores the tail at zero. */
  placement_points: number[];
  /** What one unit of raw score (a kill, a point) is worth. */
  score_points: number;
  /** The organizer's word for the score column ("Kills"); null keeps the default. */
  score_label: string | null;
}
```

      Замена:

```ts
/** How an FFA league is scored, mirroring backend `FfaScoring`. */
export interface StageFfaScoring {
  /** What is entered per game, in table order. `[]` — places alone decide. */
  columns: FfaColumn[];
  /** What place `i + 1` is worth; a shorter list scores the tail at zero. */
  placement_points: number[];
  /** The expression a game's points are computed with, over the column keys
   *  plus `place`, `place_pts` and `teams`. */
  formula: string;
}
```

      И импорт типа — первой строкой файла блока импортов (`tournament.types.ts` не импортирует ничего из
      `ffa.types.ts`; чтобы не заводить цикл — `ffa.types.ts` импортирует из `tournament.types.ts` — объявить
      `FfaColumn` в `ffa.types.ts` (задача 9) и здесь использовать структурный тип):

```ts
/** One column an FFA game records. Mirrors `FfaColumn` of `ffa.types.ts`, which
 *  imports FROM this module — spelled out here rather than imported back. */
export interface StageFfaColumn {
  key: string;
  label: string;
  public: boolean;
  better: "higher" | "lower";
}
```

      …и в `StageFfaScoring` — `columns: StageFfaColumn[]`. В `ffa.types.ts` задача 9 объявляет
      `export type FfaColumn = StageFfaColumn` либо свой идентичный интерфейс; формы совпадают, оба присваиваются
      друг другу структурно.

- [ ] **Шаг 4. Пресеты.** `frontend/src/lib/ffa/scoring-presets.ts` целиком:

```ts
/**
 * What an FFA league is scored by, as the stage editor offers it.
 *
 * A stage's `ffa_scoring` is read by the points adder
 * (`shared.domain.ffa_scoring.ffa_rules`): `columns` is what the organizer
 * enters for each team in each game, `placement_points[i]` is what place
 * `i + 1` is worth, and `formula` turns both into the points of that game.
 *
 * The presets below are starting points, not rules: the editor writes back
 * whatever the organizer leaves in the fields.
 */
import type { FfaColumn } from "@/types/ffa.types";

export interface FfaScoringPreset {
  value: string;
  label: string;
  columns: FfaColumn[];
  placementPoints: number[];
  formula: string;
}

/** Mirrors `FFA_MAX_LOBBY_SIZE`: a place past the lobby's size pays nobody. */
export const FFA_MAX_PLACES = 100;

/** Mirrors `FFA_MAX_COLUMNS`: what a stage will store. */
export const FFA_MAX_COLUMNS = 10;

/** `^[a-z][a-z0-9_]{0,23}$` — 24 characters, key included. */
export const FFA_COLUMN_KEY_MAX = 24;

/** Longest column label the backend stores. */
export const FFA_COLUMN_LABEL_MAX = 32;

/** `FORMULA_MAX_LENGTH` of `shared/domain/ffa_formula.py`. */
export const FFA_FORMULA_MAX = 500;

/** Names every formula may read on top of the column keys. */
export const FFA_FORMULA_VARIABLES = ["place", "place_pts", "teams"] as const;

/** The functions the parser accepts (`FUNCTIONS` of `ffa_formula.py`). */
export const FFA_FORMULA_FUNCTIONS = ["min", "max", "abs", "round", "if"] as const;

export const FFA_SCORING_PRESETS: readonly FfaScoringPreset[] = [
  {
    value: "score_only",
    label: "Score only",
    columns: [{ key: "score", label: "Score", public: true, better: "higher" }],
    placementPoints: [],
    formula: "score"
  },
  {
    value: "battle_royale",
    label: "Battle royale",
    columns: [{ key: "kills", label: "Kills", public: true, better: "higher" }],
    placementPoints: [10, 6, 5, 4, 3, 2, 1],
    formula: "place_pts + kills"
  }
];

/** The preset a rule still matches, or `"custom"` once it has been edited. */
export function ffaScoringPresetOf(
  columns: readonly FfaColumn[],
  placementPoints: readonly number[],
  formula: string
): string {
  const preset = FFA_SCORING_PRESETS.find(
    (candidate) =>
      candidate.formula === formula.trim() &&
      candidate.placementPoints.length === placementPoints.length &&
      candidate.placementPoints.every((points, index) => points === placementPoints[index]) &&
      candidate.columns.length === columns.length &&
      candidate.columns.every(
        (column, index) =>
          column.key === columns[index]?.key &&
          column.label === columns[index]?.label &&
          column.public === columns[index]?.public &&
          column.better === columns[index]?.better
      )
  );
  return preset?.value ?? "custom";
}

/** 1 -> "1st", 2 -> "2nd", 11 -> "11th". */
export function ordinalPlace(place: number): string {
  const teens = place % 100;
  if (teens >= 11 && teens <= 13) return `${place}th`;
  return `${place}${["th", "st", "nd", "rd"][place % 10] ?? "th"}`;
}
```

- [ ] **Шаг 5. Модель формы.** Текущие строки `stageForm.ts:41-45`:

```ts
  /** FFA leagues: what place `i + 1` pays, `[]` for a score-only lobby. */
  ffaPlacementPoints: number[];
  ffaScorePoints: number;
  /** The organizer's word for the score column; empty keeps the default. */
  ffaScoreLabel: string;
```

      Замена:

```ts
  /** FFA leagues: what place `i + 1` pays, `[]` for a lobby places do not pay. */
  ffaPlacementPoints: number[];
  /** What a game records per team, in table order. */
  ffaColumns: FfaColumn[];
  /** The expression a game's points are computed with. */
  ffaFormula: string;
```

      Импорт — после строки 14 (`import type { SeedRanking, … } from "@/types/tournament.types";`):

```ts
import type { FfaColumn } from "@/types/ffa.types";
```

      Текущие строки 68-70:

```ts
    ffaPlacementPoints: stage.ffa_scoring.placement_points,
    ffaScorePoints: stage.ffa_scoring.score_points,
    ffaScoreLabel: stage.ffa_scoring.score_label ?? ""
```

      Замена:

```ts
    ffaPlacementPoints: stage.ffa_scoring.placement_points,
    ffaColumns: stage.ffa_scoring.columns,
    ffaFormula: stage.ffa_scoring.formula
```

      Текущие строки 110-118:

```ts
    // Only an FFA league is scored by place and raw score; any other type leaves
    // the stored table alone rather than saving a rule its format cannot use.
    ...(isFfa && {
      ffa_scoring: {
        placement_points: form.ffaPlacementPoints,
        score_points: form.ffaScorePoints,
        score_label: form.ffaScoreLabel.trim() || null
      }
    })
```

      Замена:

```ts
    // Only an FFA league is scored by columns and a formula; any other type
    // leaves the stored rule alone rather than saving one its format cannot use.
    // The formula is trimmed, not otherwise touched: it is the organizer's text,
    // and the parser that refuses it also reports the position inside it.
    ...(isFfa && {
      ffa_scoring: {
        columns: form.ffaColumns,
        placement_points: form.ffaPlacementPoints,
        formula: form.ffaFormula.trim()
      }
    })
```

      Текущие строки 142-144:

```ts
  ffaPlacementPoints: "Points per place",
  ffaScorePoints: "Points per score unit",
  ffaScoreLabel: "Score label"
```

      Замена:

```ts
  ffaPlacementPoints: "Points per place",
  ffaColumns: "Game columns",
  ffaFormula: "Points formula"
```

      (`stageFormChanges`, строки 147-160, не трогается: `ffaColumns` — массив, и его ветка `JSON.stringify`
      уже есть в строках 153-156.)

- [ ] **Шаг 6. Хук сообщений об ошибке — читает позицию и имя из записи.** Текущая строка
      `frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx:11`:

```tsx
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
```

      Замена:

```tsx
import { ApiError, errorBodyFields, getApiErrorMessage } from "@/lib/api/error";
```

      Текущие строки 17-40 (докстринг + `useFfaErrorMessage`):

```tsx
/**
 * Turn any thrown value into the sentence for the rejection it carries.
…
export function useFfaErrorMessage(): (error: unknown) => string {
  const t = useTranslations();
  return (error: unknown) => {
    if (error instanceof ApiError) {
      for (const detail of error.details) {
        const key = `ffa.errors.${detail.code}` as "ffa.errors.ffa_reason_required";
        if (t.has(key)) return t(key);
      }
    }
    return getApiErrorMessage(error);
  };
}
```

      Замена:

```tsx
/**
 * The FFA rejections a thrown value carries, richest form first.
 *
 * `ApiError.details` is the flattened human view and keeps only the code; the
 * structured entries the worker sent ride `body` (`errorBodyFields`), and that
 * is where a formula rejection keeps the things a message has to name — the
 * position inside the formula, and the name the parser stumbled over.
 */
export function ffaErrorEntries(
  error: unknown
): { code: string; offset?: number; name?: string }[] {
  if (!(error instanceof ApiError)) return [];
  const structured = errorBodyFields(error.body)
    .filter((entry) => typeof entry.code === "string")
    .map((entry) => ({
      code: entry.code as string,
      offset: typeof entry.offset === "number" ? entry.offset : undefined,
      name: typeof entry.name === "string" ? entry.name : undefined
    }));
  return structured.length > 0 ? structured : error.details.map((detail) => ({ code: detail.code }));
}

/**
 * Turn any thrown value into the sentence for the rejection it carries.
 *
 * The FFA writes and the FFA stage rules answer a machine code
 * (`ffa_result_invalid_placement`, `ffa_formula_unknown_name`, …) with an
 * English `msg` meant for a log. The catalogue is the lookup rather than a
 * second copy of the code list here: a code with a message gets that message,
 * anything else falls back to whatever the server said, so a code added
 * backend-side degrades instead of breaking.
 *
 * `offset` is reported 0-based and shown 1-based: the organizer counts the
 * characters of their formula from one.
 */
export function useFfaErrorMessage(): (error: unknown) => string {
  const t = useTranslations();
  return (error: unknown) => {
    for (const entry of ffaErrorEntries(error)) {
      // Built from a server-supplied code, so it is none of next-intl's
      // statically known literals; the key named here stands in for the shape of
      // all of them — no `ffa.errors.*` message reads more than these two
      // arguments, and one that reads neither ignores both.
      const key = `ffa.errors.${entry.code}` as "ffa.errors.ffa_formula_unknown_name";
      if (t.has(key)) {
        return t(key, { offset: (entry.offset ?? 0) + 1, name: entry.name ?? "" });
      }
    }
    return getApiErrorMessage(error);
  };
}
```

      Примечание к шагу: до задачи 14 ключей `ffa.errors.ffa_formula_*` в `en.json`/`ru.json` нет, поэтому
      `t.has` для них ложен и сообщение — серверный `msg`. Это ровно то, что проверяет шаг 1 («сообщение названо
      именем `kils`»): и запасной, и локализованный текст его содержат. Каст ключа к
      `"ffa.errors.ffa_formula_unknown_name"` требует, чтобы этот ключ существовал в типах сообщений — его
      добавляет задача 14, поэтому в коммите этой задачи каст указывает на
      `"ffa.errors.ffa_reason_required"`, а задача 14 переводит его на `ffa_formula_unknown_name` вместе с
      добавлением строк (см. задачу 14, шаг 3). До этого `t(key, {...})` с лишними значениями корректен и в
      рантайме, и в типах: у сообщения без плейсхолдеров next-intl принимает значения и игнорирует их.

- [ ] **Шаг 7. Секция редактора.** `FfaScoringSection.tsx` целиком:

```tsx
"use client";

import { useId } from "react";
import { Trash2 } from "lucide-react";

import { ffaErrorEntries, useFfaErrorMessage } from "@/components/admin/ffa/FfaGameResultsDialog";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  FFA_COLUMN_KEY_MAX,
  FFA_COLUMN_LABEL_MAX,
  FFA_FORMULA_FUNCTIONS,
  FFA_FORMULA_MAX,
  FFA_FORMULA_VARIABLES,
  FFA_MAX_COLUMNS,
  FFA_MAX_PLACES,
  FFA_SCORING_PRESETS,
  ffaScoringPresetOf,
  ordinalPlace
} from "@/lib/ffa/scoring-presets";
import type { FfaColumn } from "@/types/ffa.types";

import type { StageForm } from "../stageForm";

/**
 * How an FFA league is scored: the stage's `ffa_scoring`.
 *
 * Three things, and the third is the rule: the columns a game records, the
 * points a place pays, and the formula that turns both into the points of that
 * game. A preset only fills them in — the organizer's own rule is what gets
 * saved.
 *
 * The formula is the one field here the server parses rather than stores, so it
 * is the one field that can be refused by position. `saveError` is the last
 * refusal of the save; the parts of it this section owns are shown under the
 * field they are about, because a toast cannot point at character 14.
 */
export function FfaScoringSection({
  form,
  onChange,
  saveError
}: Readonly<{
  form: StageForm;
  onChange: (patch: Partial<StageForm>) => void;
  saveError?: unknown;
}>) {
  const ids = useId();
  const describeError = useFfaErrorMessage();
  const columns = form.ffaColumns;
  const places = form.ffaPlacementPoints;
  const preset = ffaScoringPresetOf(columns, places, form.ffaFormula);

  const codes = ffaErrorEntries(saveError).map((entry) => entry.code);
  const formulaError = codes.some((code) => code.startsWith("ffa_formula_"))
    ? describeError(saveError)
    : null;
  const columnsError = codes.some((code) => code.startsWith("ffa_column"))
    ? describeError(saveError)
    : null;

  const setColumn = (index: number, patch: Partial<FfaColumn>) =>
    onChange({
      ffaColumns: columns.map((column, at) => (at === index ? { ...column, ...patch } : column))
    });

  const setPlace = (index: number, points: number | null) =>
    onChange({
      ffaPlacementPoints: places.map((current, at) => (at === index ? (points ?? 0) : current))
    });

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5 sm:max-w-xs">
        <Label htmlFor={`${ids}-preset`}>Scoring preset</Label>
        <Select
          value={preset}
          onValueChange={(value) => {
            const picked = FFA_SCORING_PRESETS.find((option) => option.value === value);
            if (!picked) return;
            onChange({
              ffaColumns: picked.columns.map((column) => ({ ...column })),
              ffaPlacementPoints: [...picked.placementPoints],
              ffaFormula: picked.formula
            });
          }}
        >
          <SelectTrigger id={`${ids}-preset`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FFA_SCORING_PRESETS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
            {/* Only reachable as a state, never as a choice: it IS the fields
                below once a column, a place or the formula has been edited. */}
            {preset === "custom" ? <SelectItem value="custom">Custom</SelectItem> : null}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className={EYEBROW_CLASS}>Game columns</h3>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs text-primary"
            disabled={columns.length >= FFA_MAX_COLUMNS}
            onClick={() =>
              onChange({
                ffaColumns: [...columns, { key: "", label: "", public: true, better: "higher" }]
              })
            }
          >
            Add column
          </Button>
        </div>

        {columns.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
            Nothing is entered per game: the lobby is scored on its places alone. Add a column to
            record kills, damage or a penalty.
          </p>
        ) : (
          columns.map((column, index) => (
            // The index IS the position in the table, and columns are renumbered
            // on removal — there is no stabler key, and no row state to carry.
            <div
              key={index}
              className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_auto_auto_auto]"
            >
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor={`${ids}-key-${index}`}>{`Column ${index + 1} key`}</Label>
                <Input
                  id={`${ids}-key-${index}`}
                  maxLength={FFA_COLUMN_KEY_MAX}
                  placeholder="kills"
                  className="font-mono"
                  spellCheck={false}
                  value={column.key}
                  onChange={(event) => setColumn(index, { key: event.target.value })}
                />
              </div>
              <div className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor={`${ids}-label-${index}`}>{`Column ${index + 1} label`}</Label>
                <Input
                  id={`${ids}-label-${index}`}
                  maxLength={FFA_COLUMN_LABEL_MAX}
                  placeholder="Kills"
                  value={column.label}
                  onChange={(event) => setColumn(index, { label: event.target.value })}
                />
              </div>
              <span className="flex items-center gap-2 pb-2 text-xs text-muted-foreground">
                <Checkbox
                  checked={column.public}
                  aria-label={`Show column ${index + 1} in the table`}
                  onCheckedChange={(checked) => setColumn(index, { public: checked === true })}
                />
                <span>In the table</span>
              </span>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${ids}-better-${index}`}>{`Column ${index + 1} direction`}</Label>
                <Select
                  value={column.better}
                  onValueChange={(value) =>
                    setColumn(index, { better: value as FfaColumn["better"] })
                  }
                >
                  <SelectTrigger id={`${ids}-better-${index}`} className="w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="higher">Higher is better</SelectItem>
                    <SelectItem value="lower">Lower is better</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="mb-0.5 text-muted-foreground hover:text-foreground"
                aria-label={`Remove column ${index + 1}`}
                onClick={() =>
                  onChange({ ffaColumns: columns.filter((_, at) => at !== index) })
                }
              >
                <Trash2 className="size-4" aria-hidden />
              </Button>
            </div>
          ))
        )}

        {columnsError ? (
          <p role="alert" className="text-xs text-danger">
            {columnsError}
          </p>
        ) : null}

        <p className="text-xs text-muted-foreground">
          The key is what the formula reads — lowercase letters, digits and underscores, up to{" "}
          {FFA_COLUMN_KEY_MAX} characters. A column left out of the table is still entered and still
          scored; the public lobby never shows its values. A column with values in it can be
          relabelled, but not renamed or removed. At most {FFA_MAX_COLUMNS} columns.
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${ids}-formula`}>Points formula</Label>
        <Textarea
          id={`${ids}-formula`}
          rows={2}
          maxLength={FFA_FORMULA_MAX}
          className="font-mono text-sm"
          spellCheck={false}
          placeholder="place_pts + kills * 2 - deaths"
          value={form.ffaFormula}
          onChange={(event) => onChange({ ffaFormula: event.target.value })}
          aria-describedby={`${ids}-formula-hint`}
          aria-invalid={formulaError != null || undefined}
          aria-errormessage={formulaError != null ? `${ids}-formula-error` : undefined}
        />
        {formulaError ? (
          <p id={`${ids}-formula-error`} role="alert" className="text-xs text-danger">
            {formulaError}
          </p>
        ) : null}
        <p id={`${ids}-formula-hint`} className="text-xs text-muted-foreground">
          <span className="font-mono">
            {[...columns.map((column) => column.key).filter(Boolean), ...FFA_FORMULA_VARIABLES].join(
              ", "
            )}
          </span>{" "}
          · functions <span className="font-mono">{FFA_FORMULA_FUNCTIONS.join(", ")}</span> ·
          arithmetic, comparisons and <span className="font-mono">and / or / not</span>.
        </p>
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">place</span> is the finishing place,{" "}
          <span className="font-mono">place_pts</span> what that place pays in the table below, and{" "}
          <span className="font-mono">teams</span> the size of the lobby. Reading{" "}
          <span className="font-mono">place</span> or <span className="font-mono">place_pts</span> is
          what makes a place REQUIRED when a game is entered; a formula that reads neither derives
          the places from the points instead.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className={EYEBROW_CLASS}>Points per place</h3>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs text-primary"
            disabled={places.length >= FFA_MAX_PLACES}
            onClick={() => onChange({ ffaPlacementPoints: [...places, 0] })}
          >
            Add place
          </Button>
        </div>

        {places.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
            No points for placement: <span className="font-mono">place_pts</span> is zero for
            everyone. Add a place to pay for finishing position too.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {places.map((points, index) => (
              // The index IS the place, and places are renumbered on removal —
              // there is no stabler key, and no row state to carry.
              <div key={index} className="flex items-end gap-1">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <Label
                    htmlFor={`${ids}-place-${index}`}
                  >{`${ordinalPlace(index + 1)} place`}</Label>
                  <NumberInput
                    id={`${ids}-place-${index}`}
                    min={0}
                    value={points}
                    onValueChange={(next) => setPlace(index, next)}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={`Remove ${ordinalPlace(index + 1)} place`}
                  onClick={() =>
                    onChange({ ffaPlacementPoints: places.filter((_, at) => at !== index) })
                  }
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          A place past the end of this table pays nothing, so a table shorter than the lobby is
          legal — the tail scores on its columns alone.
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Шаг 8. Редактор запоминает отказ сохранения.** Текущие строки
      `StageEditor.tsx:138-139`:

```tsx
  const [form, setForm] = useState<StageForm>(() => stageFormFromStage(stage));
  const [pendingOp, setPendingOp] = useState<PendingOp | null>(null);
```

      Замена:

```tsx
  const [form, setForm] = useState<StageForm>(() => stageFormFromStage(stage));
  const [pendingOp, setPendingOp] = useState<PendingOp | null>(null);
  // The last refusal of a save. The FFA rules are the one part of this form the
  // server rejects by position inside a field, and a toast cannot point at one.
  const [saveError, setSaveError] = useState<unknown>(null);
```

      Текущие строки 191-198:

```tsx
  const updateMutation = useMutation({
    mutationFn: () => adminService.updateStage(stage.id, buildStageUpdatePayload(stage, form)),
    onSuccess: (saved) => {
      setForm(stageFormFromStage(saved));
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: "Could not save this stage" })
  });
```

      Замена:

```tsx
  const updateMutation = useMutation({
    mutationFn: () => adminService.updateStage(stage.id, buildStageUpdatePayload(stage, form)),
    onMutate: () => setSaveError(null),
    onSuccess: (saved) => {
      setForm(stageFormFromStage(saved));
      onChanged();
    },
    onError: (error) => {
      setSaveError(error);
      notify.apiError(error, { title: "Could not save this stage" });
    }
  });
```

      Текущие строки 524-529:

```tsx
        {activeSection === "ffa-scoring" ? (
          <FfaScoringSection
            form={form}
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
          />
        ) : null}
```

      Замена:

```tsx
        {activeSection === "ffa-scoring" ? (
          <FfaScoringSection
            form={form}
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
            saveError={saveError}
          />
        ) : null}
```

- [ ] **Шаг 9. Запустить — зелёный.**
      `cd frontend && bunx vitest run stageEditor.ffaScoring.behavior`
      Ожидание: PASS, 9 passed (4 новых/переписанных + 5 нетронутых).
      Плюс `bunx vitest run stageEditor.tiebreakers.behavior stageEditor.bestOf.behavior stageEditor.roundSchedule.behavior stageEditor.ffaRoundSchedule.behavior`
      — PASS: фикстуры этих файлов не задают `ffa_scoring` вручную либо задают его через `stage()` того же файла;
      если какой-то из них собирает `Stage` со старым блоком, поправить фикстуру на
      `{ columns: [{ key: "score", label: "Счёт", public: true, better: "higher" }], placement_points: [], formula: "score" }`
      (значение по умолчанию колонок стадии, спека §3.1) в том же коммите.
      `bunx tsc --noEmit -p tsconfig.json` на этом шаге ещё может ругаться на `ffa.types.ts`, если задача 9 не
      влита: это ожидаемо (см. вступление раздела), собственные тесты задачи проходят.

- [ ] **Шаг 10. Коммит.**
      `git add frontend/src/types/tournament.types.ts frontend/src/lib/ffa/scoring-presets.ts frontend/src/app/admin/tournaments/\[id\]/bracket/stageForm.ts frontend/src/app/admin/tournaments/\[id\]/bracket/components/FfaScoringSection.tsx frontend/src/app/admin/tournaments/\[id\]/bracket/components/StageEditor.tsx frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx frontend/src/app/admin/tournaments/\[id\]/bracket/stageEditor.ffaScoring.behavior.test.tsx`
      `git commit -m "feat(ffa): edit stage columns and points formula"`

---

### Задача 13. Тай-брейки `ffa_stat:<key>`

**Files:**

- Modify `frontend/src/lib/tournament/tiebreakers.ts:1-84` (файл переписывается целиком)
- Modify `frontend/src/lib/bracket/projection.ts:94-130`
- Modify `frontend/src/app/admin/tournaments/[id]/bracket/components/StageSettingsSections.tsx:117-128,418,428,456,534,543-544`
- Modify `frontend/src/app/admin/tournaments/[id]/bracket/stageForm.ts:62`
- Modify `frontend/src/components/StandingsTable.tsx:12,225-229,516`
- Modify `frontend/src/i18n/messages/en.json:76`, `frontend/src/i18n/messages/ru.json:76`
- Tests: `frontend/src/lib/tournament/tiebreakers.test.ts` (переписывается),
  `frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaScoring.behavior.test.tsx:341-357`
  (тест `offers the lobby tiebreakers, and only those` переписывается)

**Interfaces:**

Consumes: `StageForm.ffaColumns: FfaColumn[]` (задача 12), `Stage["ffa_scoring"].columns` (задача 12).

Produces:

```ts
// frontend/src/lib/tournament/tiebreakers.ts
export const FFA_STAT_PREFIX = "ffa_stat:";
export type TiebreakerMetricId =
  | "points" | "match_wins" | "head_to_head" | "median_buchholz" | "buchholz"
  | "score_differential" | "ffa_game_wins" | "ffa_best_placement" | "ffa_last_placement";
export type TiebreakerId = TiebreakerMetricId | `ffa_stat:${string}`;
export type TiebreakerColumn = Readonly<{ key: string; label: string }>;
export const ALL_TIEBREAKERS: { id: TiebreakerId; label: string }[];
export const FFA_TIEBREAKERS: { id: TiebreakerId; label: string }[];
export function ffaStatTiebreakers(columns: readonly TiebreakerColumn[]): { id: TiebreakerId; label: string }[];
export function tiebreakersForStageType(stageType: StageType, ffaColumns?: readonly TiebreakerColumn[]): { id: TiebreakerId; label: string }[];
export function tiebreakerLabel(id: string, labelFor?: (id: string) => string | undefined, ffaColumns?: readonly TiebreakerColumn[]): string;
export function formatTiebreakOrder(order: string[] | null | undefined, labelFor?: (id: string) => string | undefined, ffaColumns?: readonly TiebreakerColumn[]): string;

// frontend/src/lib/bracket/projection.ts
export function ffaDefaultTiebreakers(columns: readonly { key: string }[]): string[];
export function defaultTiebreakOrder(stageType: StageType, ffaColumns?: readonly { key: string }[]): string[];
export function tiebreakOrderForPreset(preset: string, stageType: StageType, ffaColumns?: readonly { key: string }[]): string[];
// DEFAULT_FFA_TIEBREAKERS удалена
```

i18n: `common.tiebreakerMetrics.ffa_stat` добавлен, `common.tiebreakerMetrics.ffa_score` удалён (en + ru).

- [ ] **Шаг 1. Переписать `tiebreakers.test.ts` под новый контракт.**
      Существующие утверждения, пинящие удаляемое поведение: `ffa_score` в списке каталога (строка 24),
      `tiebreakerLabel("ffa_score")` (строки 60, 66, 67). Они переписываются, файл целиком:

```ts
import { describe, expect, it } from "vitest";

import {
  ALL_TIEBREAKERS,
  FFA_STAT_PREFIX,
  FFA_TIEBREAKERS,
  ffaStatTiebreakers,
  formatTiebreakOrder,
  tiebreakerLabel,
  tiebreakersForStageType
} from "./tiebreakers";

const COLUMNS = [
  { key: "kills", label: "Kills" },
  { key: "deaths", label: "Deaths" }
];

/**
 * The catalog the stage editor offers has to match what the backend engine can
 * actually compute for that stage type (`_metric_value`): an FFA lobby has no
 * opponent pairing, so offering head-to-head or Buchholz there would let an
 * organizer save a tie-break order the server silently drops — and the lobby's
 * own sums exist only for the columns THAT stage records.
 */
describe("tiebreakersForStageType", () => {
  it("offers the FFA metrics and no pairing metrics on an FFA stage", () => {
    const ids = tiebreakersForStageType("ffa_league").map((metric) => metric.id);

    expect(ids).toEqual([
      "points",
      "ffa_game_wins",
      "ffa_best_placement",
      "ffa_last_placement"
    ]);
    expect(ids).not.toContain("head_to_head");
    expect(ids).not.toContain("buchholz");
    expect(ids).not.toContain("median_buchholz");
  });

  it("offers a sum for every column the stage records", () => {
    const ids = tiebreakersForStageType("ffa_league", COLUMNS).map((metric) => metric.id);

    expect(ids).toContain("ffa_stat:kills");
    expect(ids).toContain("ffa_stat:deaths");
  });

  it("offers no column sums on a duel stage", () => {
    const ids = tiebreakersForStageType("round_robin", COLUMNS).map((metric) => metric.id);

    expect(ids).toEqual(ALL_TIEBREAKERS.map((metric) => metric.id));
    expect(ids.some((id) => id.startsWith(FFA_STAT_PREFIX))).toBe(false);
  });

  it("keeps the duel catalog for every non-FFA stage type", () => {
    for (const stageType of [
      "swiss",
      "round_robin",
      "single_elimination",
      "double_elimination"
    ] as const) {
      expect(tiebreakersForStageType(stageType)).toEqual(ALL_TIEBREAKERS);
    }

    expect(tiebreakersForStageType("swiss").map((metric) => metric.id)).toEqual([
      "points",
      "head_to_head",
      "median_buchholz",
      "buchholz",
      "match_wins",
      "score_differential"
    ]);
  });

  it("never offers a placement metric on a duel stage", () => {
    const duelIds = tiebreakersForStageType("round_robin").map((metric) => metric.id);

    for (const ffa of FFA_TIEBREAKERS.filter((metric) => metric.id.startsWith("ffa_"))) {
      expect(duelIds).not.toContain(ffa.id);
    }
  });
});

describe("ffaStatTiebreakers", () => {
  it("names a sum by the column's label, not its key", () => {
    expect(ffaStatTiebreakers(COLUMNS)).toEqual([
      { id: "ffa_stat:kills", label: "Sum: Kills" },
      { id: "ffa_stat:deaths", label: "Sum: Deaths" }
    ]);
  });

  it("falls back to the key while a new column has no label yet", () => {
    expect(ffaStatTiebreakers([{ key: "damage", label: "" }])).toEqual([
      { id: "ffa_stat:damage", label: "Sum: damage" }
    ]);
  });
});

describe("tiebreakerLabel", () => {
  it("labels the FFA metrics without an i18n resolver", () => {
    expect(tiebreakerLabel("ffa_game_wins")).toBe("Game Wins");
    expect(tiebreakerLabel("ffa_best_placement")).toBe("Best Placement");
    expect(tiebreakerLabel("ffa_last_placement")).toBe("Last Placement");
  });

  it("names a column sum from the columns it is given", () => {
    expect(tiebreakerLabel("ffa_stat:kills", undefined, COLUMNS)).toBe("Sum: Kills");
    // A reader that has the order but not the stage — the public standings
    // footer — still says which column decided it.
    expect(tiebreakerLabel("ffa_stat:kills")).toBe("Sum: kills");
  });

  it("prefers the resolver and falls back to the raw id", () => {
    expect(tiebreakerLabel("ffa_game_wins", () => "Победы в играх")).toBe("Победы в играх");
    expect(tiebreakerLabel("ffa_game_wins", () => undefined)).toBe("Game Wins");
    expect(tiebreakerLabel("ffa_stat:kills", () => "Сумма: Убийства")).toBe("Сумма: Убийства");
    expect(tiebreakerLabel("who_knows")).toBe("who_knows");
  });
});

describe("formatTiebreakOrder", () => {
  it("renders an FFA order the way the server stores it", () => {
    expect(
      formatTiebreakOrder(
        ["points", "ffa_game_wins", "ffa_stat:kills", "ffa_last_placement"],
        undefined,
        COLUMNS
      )
    ).toBe("Points → Game Wins → Sum: Kills → Last Placement");
  });
});
```

- [ ] **Шаг 2. Запустить — красный.**
      `cd frontend && bunx vitest run src/lib/tournament/tiebreakers.test.ts`
      Ожидание: FAIL — `SyntaxError`/`does not provide an export named 'FFA_STAT_PREFIX'` (и `ffaStatTiebreakers`)
      при импорте из `./tiebreakers`.

- [ ] **Шаг 3. Переписать `frontend/src/lib/tournament/tiebreakers.ts` целиком.**

```ts
// Shared tie-breaker metric catalog + helpers.
//
// Keeps the public StandingsTable, the admin standings page, and the admin
// stage editor in sync with the backend engine metrics (see backend
// `RULE_PRESET_DEFAULTS` / `_metric_value`).
import type { StageType } from "@/types/tournament.types";

/**
 * The metric "the sum of one FFA column", prefixed with the column's key.
 *
 * An FFA stage's columns are the organizer's, so this half of the catalogue is
 * not a list: it is built from the columns THAT stage records
 * (`shared.domain.ffa_scoring.FfaRules.columns`), and the direction is the
 * column's own `better`, decided server-side.
 */
export const FFA_STAT_PREFIX = "ffa_stat:";

export type TiebreakerMetricId =
  | "points"
  | "match_wins"
  | "head_to_head"
  | "median_buchholz"
  | "buchholz"
  | "score_differential"
  | "ffa_game_wins"
  | "ffa_best_placement"
  | "ffa_last_placement";

/** A metric a saved order can hold: a fixed one, or one column's sum. */
export type TiebreakerId = TiebreakerMetricId | `ffa_stat:${string}`;

/** What a column sum needs to be named: nothing else of an `FfaColumn`. */
export type TiebreakerColumn = Readonly<{ key: string; label: string }>;

// Default English labels. Used as a fallback when no i18n resolver is supplied.
const TIEBREAKER_LABELS: Record<string, string> = {
  points: "Points",
  match_wins: "Match Wins",
  head_to_head: "Head-to-Head",
  median_buchholz: "Median Buchholz",
  buchholz: "Buchholz",
  score_differential: "Score Differential",
  ffa_game_wins: "Game Wins",
  ffa_best_placement: "Best Placement",
  ffa_last_placement: "Last Placement"
};

// Ordered catalog presented in the stage editor.
export const ALL_TIEBREAKERS: { id: TiebreakerId; label: string }[] = [
  { id: "points", label: TIEBREAKER_LABELS.points },
  { id: "head_to_head", label: TIEBREAKER_LABELS.head_to_head },
  { id: "median_buchholz", label: TIEBREAKER_LABELS.median_buchholz },
  { id: "buchholz", label: TIEBREAKER_LABELS.buchholz },
  { id: "match_wins", label: TIEBREAKER_LABELS.match_wins },
  { id: "score_differential", label: TIEBREAKER_LABELS.score_differential }
];

/**
 * The fixed part of the FFA catalog, in `ffa_default` order (backend
 * `RULE_PRESET_DEFAULTS`).
 *
 * Disjoint from the list above on purpose: an FFA lobby has no opponent
 * pairing, so head-to-head and both Buchholz variants compute nothing there,
 * and a duel encounter has no placement.
 */
export const FFA_TIEBREAKERS: { id: TiebreakerId; label: string }[] = [
  { id: "points", label: TIEBREAKER_LABELS.points },
  { id: "ffa_game_wins", label: TIEBREAKER_LABELS.ffa_game_wins },
  { id: "ffa_best_placement", label: TIEBREAKER_LABELS.ffa_best_placement },
  { id: "ffa_last_placement", label: TIEBREAKER_LABELS.ffa_last_placement }
];

/** One "Sum: <label>" metric per column of the stage, in table order. */
export function ffaStatTiebreakers(
  columns: readonly TiebreakerColumn[]
): { id: TiebreakerId; label: string }[] {
  return columns.map((column) => ({
    id: `${FFA_STAT_PREFIX}${column.key}` as TiebreakerId,
    // A column being configured has a key before it has a label; the key is
    // what the organizer typed, so it stands in until the label arrives.
    label: `Sum: ${column.label || column.key}`
  }));
}

/** The metrics the engine can actually compute for `stageType`. */
export function tiebreakersForStageType(
  stageType: StageType,
  ffaColumns: readonly TiebreakerColumn[] = []
): { id: TiebreakerId; label: string }[] {
  return stageType === "ffa_league"
    ? [...FFA_TIEBREAKERS, ...ffaStatTiebreakers(ffaColumns)]
    : ALL_TIEBREAKERS;
}

/**
 * Resolve a single metric id to a human label, optionally via an i18n resolver.
 *
 * `ffaColumns` names a column sum by its label; a reader that has the saved
 * order but not the stage (the public standings footer) passes none, and the
 * key stands in — it still says which column decided the place.
 */
export function tiebreakerLabel(
  id: string,
  labelFor?: (id: string) => string | undefined,
  ffaColumns: readonly TiebreakerColumn[] = []
): string {
  const resolved = labelFor?.(id);
  if (resolved != null) return resolved;
  if (id.startsWith(FFA_STAT_PREFIX)) {
    const key = id.slice(FFA_STAT_PREFIX.length);
    const column = ffaColumns.find((candidate) => candidate.key === key);
    return `Sum: ${column?.label || key}`;
  }
  return TIEBREAKER_LABELS[id] ?? id;
}

/**
 * Render an ordered tie-break list as "Points → Head-to-Head → …".
 * `labelFor` lets callers plug in their i18n translator.
 */
export function formatTiebreakOrder(
  order: string[] | null | undefined,
  labelFor?: (id: string) => string | undefined,
  ffaColumns: readonly TiebreakerColumn[] = []
): string {
  if (!order || order.length === 0) return "";
  return order.map((id) => tiebreakerLabel(id, labelFor, ffaColumns)).join(" → ");
}
```

- [ ] **Шаг 4. Запустить — зелёный.**
      `cd frontend && bunx vitest run src/lib/tournament/tiebreakers.test.ts`
      Ожидание: PASS, 11 passed.

- [ ] **Шаг 5. Порядок по умолчанию строится из столбцов.** Текущие строки
      `frontend/src/lib/bracket/projection.ts:94-100`:

```ts
/** Mirrors the backend `ffa_default` preset (`RULE_PRESET_DEFAULTS`). */
export const DEFAULT_FFA_TIEBREAKERS = [
  "points",
  "ffa_game_wins",
  "ffa_score",
  "ffa_last_placement"
];
```

      Замена:

```ts
/**
 * Mirrors the backend `ffa_default` preset (`RULE_PRESET_DEFAULTS`).
 *
 * Not a constant any more: the third step is the sum of the stage's FIRST
 * column, and a stage that records nothing per game simply has no such step.
 */
export function ffaDefaultTiebreakers(columns: readonly { key: string }[] = []): string[] {
  const first = columns[0]?.key;
  return first
    ? ["points", "ffa_game_wins", `ffa_stat:${first}`, "ffa_last_placement"]
    : ["points", "ffa_game_wins", "ffa_last_placement"];
}
```

      Текущие строки 115-130:

```ts
/** The tiebreak order a stage type falls back to with no preset chosen. */
export function defaultTiebreakOrder(stageType: StageType): string[] {
  if (stageType === "ffa_league") return DEFAULT_FFA_TIEBREAKERS;
  if (stageType === "swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (stageType === "round_robin") return DEFAULT_RR_TIEBREAKERS;
  return DEFAULT_BRACKET_TIEBREAKERS;
}

/** The order a preset dictates; an unknown preset keeps the type default. */
export function tiebreakOrderForPreset(preset: string, stageType: StageType): string[] {
  if (preset === "challonge_swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (preset === "challonge_round_robin") return DEFAULT_RR_TIEBREAKERS;
  if (preset === "bracket_default") return DEFAULT_BRACKET_TIEBREAKERS;
  if (preset === "ffa_default") return DEFAULT_FFA_TIEBREAKERS;
  return defaultTiebreakOrder(stageType);
}
```

      Замена:

```ts
/** The tiebreak order a stage type falls back to with no preset chosen. */
export function defaultTiebreakOrder(
  stageType: StageType,
  ffaColumns: readonly { key: string }[] = []
): string[] {
  if (stageType === "ffa_league") return ffaDefaultTiebreakers(ffaColumns);
  if (stageType === "swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (stageType === "round_robin") return DEFAULT_RR_TIEBREAKERS;
  return DEFAULT_BRACKET_TIEBREAKERS;
}

/** The order a preset dictates; an unknown preset keeps the type default. */
export function tiebreakOrderForPreset(
  preset: string,
  stageType: StageType,
  ffaColumns: readonly { key: string }[] = []
): string[] {
  if (preset === "challonge_swiss") return DEFAULT_SWISS_TIEBREAKERS;
  if (preset === "challonge_round_robin") return DEFAULT_RR_TIEBREAKERS;
  if (preset === "bracket_default") return DEFAULT_BRACKET_TIEBREAKERS;
  if (preset === "ffa_default") return ffaDefaultTiebreakers(ffaColumns);
  return defaultTiebreakOrder(stageType, ffaColumns);
}
```

- [ ] **Шаг 6. Передать столбцы во все вызовы.**
      `frontend/src/app/admin/tournaments/[id]/bracket/stageForm.ts:62` — текущая строка:

```ts
    tiebreakOrder: stage.tiebreak_order ?? defaultTiebreakOrder(stage.stage_type),
```

      Замена:

```ts
    tiebreakOrder:
      stage.tiebreak_order ?? defaultTiebreakOrder(stage.stage_type, stage.ffa_scoring.columns),
```

      `StageSettingsSections.tsx:117` — текущая строка:

```tsx
              const catalogue = tiebreakersForStageType(stageType).map((metric) => metric.id);
```

      Замена:

```tsx
              const catalogue = tiebreakersForStageType(stageType, form.ffaColumns).map(
                (metric) => metric.id
              );
```

      `StageSettingsSections.tsx:127` — текущая строка:

```tsx
                      tiebreakOrder: defaultTiebreakOrder(stageType)
```

      Замена:

```tsx
                      tiebreakOrder: defaultTiebreakOrder(stageType, form.ffaColumns)
```

      `StageSettingsSections.tsx:418` — текущая строка:

```tsx
  const catalogue = tiebreakersForStageType(form.stageType);
```

      Замена:

```tsx
  const catalogue = tiebreakersForStageType(form.stageType, form.ffaColumns);
```

      `StageSettingsSections.tsx:456` — текущая строка:

```tsx
                tiebreakOrder: tiebreakOrderForPreset(value, form.stageType)
```

      Замена:

```tsx
                tiebreakOrder: tiebreakOrderForPreset(value, form.stageType, form.ffaColumns)
```

      `StageSettingsSections.tsx:533-535` — текущие строки:

```tsx
              onChange({
                tiebreakOrder: tiebreakOrderForPreset(form.rankingPreset, form.stageType)
              })
```

      Замена:

```tsx
              onChange({
                tiebreakOrder: tiebreakOrderForPreset(
                  form.rankingPreset,
                  form.stageType,
                  form.ffaColumns
                )
              })
```

      `StageSettingsSections.tsx:543-544` — текущие строки:

```tsx
            const metricLabel =
              catalogue.find((metric) => metric.id === metricId)?.label ?? metricId;
```

      Замена (порядок может держать сумму столбца, который организатор уже удалил из формы; подпись
      остаётся читаемой, а сам шаг отбрасывает сервер — `normalize_tiebreak_order`):

```tsx
            const metricLabel =
              catalogue.find((metric) => metric.id === metricId)?.label ??
              tiebreakerLabel(metricId, undefined, form.ffaColumns);
```

      Импорт в `StageSettingsSections.tsx:20` — текущая строка:

```tsx
import { tiebreakersForStageType } from "@/lib/tournament/tiebreakers";
```

      Замена:

```tsx
import { tiebreakerLabel, tiebreakersForStageType } from "@/lib/tournament/tiebreakers";
```

- [ ] **Шаг 7. Публичная таблица называет столбец.** Текущая строка
      `frontend/src/components/StandingsTable.tsx:12`:

```tsx
import { tiebreakerLabel, type TiebreakerMetricId } from "@/lib/tournament/tiebreakers";
```

      Замена:

```tsx
import {
  FFA_STAT_PREFIX,
  tiebreakerLabel,
  type TiebreakerMetricId
} from "@/lib/tournament/tiebreakers";
```

      Текущие строки 223-229:

```tsx
  // "Ranked by …" legend — resolve metric ids through i18n, falling back to the
  // shared English labels when a key is missing.
  const labelFor = (id: string) => {
    const key = `common.tiebreakerMetrics.${id as TiebreakerMetricId}` as const;
    const label = t(key);
    return label === key ? undefined : label;
  };
```

      Замена:

```tsx
  // "Ranked by …" legend — resolve metric ids through i18n, falling back to the
  // shared English labels when a key is missing.
  // A column sum names the organizer's column: its label comes from the stage
  // this table already loads (`stages`, line 148); the bare key stands in only
  // while that query is still in flight.
  const ffaColumns = stages.find((candidate) => candidate.id === stage?.id)?.ffa_scoring?.columns ?? [];
  const labelFor = (id: string) => {
    if (id.startsWith(FFA_STAT_PREFIX)) {
      const columnKey = id.slice(FFA_STAT_PREFIX.length);
      const column = ffaColumns.find((candidate) => candidate.key === columnKey);
      return t("common.tiebreakerMetrics.ffa_stat", { label: column?.label ?? columnKey });
    }
    const key = `common.tiebreakerMetrics.${id as TiebreakerMetricId}` as const;
    const label = t(key);
    return label === key ? undefined : label;
  };
```

      `stages` (`StandingsTable.tsx:148`) и `stage` (`:150`) объявлены выше строки 223 — новых запросов нет.
      Строка 516 (`const label = tiebreakerLabel(metricId, labelFor);`) не меняется: `labelFor` уже отвечает за
      `ffa_stat`. `frontend/src/components/StandingsTable.test.ts` (проверяет, что в исходнике есть
      `tiebreakerLabel` и `t("common.tiebreakers")`) остаётся зелёным — оба вызова на месте.
      `frontend/src/components/admin/StandingsBrowser.tsx:486` (`formatTiebreakOrder(tiebreakOrder)`) не
      меняется: без резолвера и без столбцов он покажет «Sum: kills» — служебный список админки, стадию он не
      загружает.

- [ ] **Шаг 8. i18n метрики.** `frontend/src/i18n/messages/en.json:76` — текущая строка:

```json
      "ffa_score": "Score",
```

      Замена:

```json
      "ffa_stat": "Sum: {label}",
```

      `frontend/src/i18n/messages/ru.json:76` — текущая строка:

```json
      "ffa_score": "Счёт",
```

      Замена:

```json
      "ffa_stat": "Сумма: {label}",
```

- [ ] **Шаг 9. Переписать тест каталога в редакторе.** Текущие строки
      `frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaScoring.behavior.test.tsx:341-357`:

```tsx
  it("offers the lobby tiebreakers, and only those", async () => {
    await mount(stage("ffa_league"), "tiebreakers");

    expect(offeredMetrics()).toEqual([
      "Points",
      "Game Wins",
      "Score",
      "Last Placement",
      "Best Placement"
    ]);

    await click(select("Standings preset"));
    expect(options()).toEqual([
      "System default (based on type)",
      "FFA default (game wins, then score)"
    ]);
  });
```

      Замена (порядок вывода `offeredMetrics()` — сначала включённые шаги в порядке `tiebreakOrder`, затем
      выключенные из каталога; при столбцах `kills`/`deaths` порядок по умолчанию —
      `points, ffa_game_wins, ffa_stat:kills, ffa_last_placement`):

```tsx
  it("offers a sum per column, and no metric a lobby cannot compute", async () => {
    await mount(
      stage("ffa_league", {
        ffa_scoring: {
          columns: [
            { key: "kills", label: "Kills", public: true, better: "higher" as const },
            { key: "deaths", label: "Deaths", public: false, better: "lower" as const }
          ],
          placement_points: [],
          formula: "kills * 2 - deaths"
        }
      }),
      "tiebreakers"
    );

    // The lobby's own sums are the stage's columns — including the one the
    // public table never shows, which still decides a tie.
    expect(offeredMetrics()).toEqual([
      "Points",
      "Game Wins",
      "Sum: Kills",
      "Last Placement",
      "Best Placement",
      "Sum: Deaths"
    ]);

    await click(select("Standings preset"));
    expect(options()).toEqual([
      "System default (based on type)",
      "FFA default (game wins, then score)"
    ]);
  });
```

- [ ] **Шаг 10. Запустить — зелёный.**
      `cd frontend && bunx vitest run src/lib/tournament/tiebreakers.test.ts stageEditor.ffaScoring.behavior stageEditor.tiebreakers.behavior`
      Ожидание: PASS — 11 + 9 + существующие тесты round-robin-порядка.
      Если `offeredMetrics()` вернёт другой порядок, чем в шаге 9, — привести ожидание к фактическому порядку
      рендера (включённые шаги идут в порядке `tiebreakOrder`, выключенные — в порядке каталога), не меняя
      состав.

- [ ] **Шаг 11. Коммит.**
      `git add frontend/src/lib/tournament/tiebreakers.ts frontend/src/lib/tournament/tiebreakers.test.ts frontend/src/lib/bracket/projection.ts frontend/src/app/admin/tournaments/\[id\]/bracket/stageForm.ts frontend/src/app/admin/tournaments/\[id\]/bracket/components/StageSettingsSections.tsx frontend/src/app/admin/tournaments/\[id\]/bracket/stageEditor.ffaScoring.behavior.test.tsx frontend/src/components/StandingsTable.tsx frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json`
      `git commit -m "feat(ffa): tiebreak on the sum of any stage column"`

---

### Задача 14. i18n кодов ошибок, документация, финальная проверка

**Files:**

- Modify `frontend/src/i18n/messages/en.json:6394-6401`
- Modify `frontend/src/i18n/messages/ru.json:6394-6401`
- Modify `frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx` (каст ключа в `useFfaErrorMessage`)
- Modify `frontend/src/app/(site)/docs/_content/en/dev/tournaments.mdx:72,79,81,122`
- Modify `frontend/src/app/(site)/docs/_content/ru/dev/tournaments.mdx:72,79,81,122`
- Modify `docs/plans/2026-09-24-ffa-encounters.md:3,179-180,234,251`
- Modify `docs/plans/2026-09-26-ffa-custom-scoring.md:3`
- Modify `docs/plans/2026-09-26-ffa-custom-scoring-plan.md:3` (шапка этого плана)
- Tests: `frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaScoring.behavior.test.tsx`
  (усиливается одно утверждение)

**Interfaces:**

Consumes: коды ошибок задач 1–3, 6, 7 (`ffa_formula_syntax`, `ffa_formula_unknown_name`,
`ffa_formula_unsupported`, `ffa_formula_too_complex`, `ffa_column_key_invalid`, `ffa_column_key_reserved`,
`ffa_column_duplicate`, `ffa_columns_too_many`, `ffa_column_in_use`, `ffa_result_unknown_stat`,
`ffa_result_missing_stat`, `ffa_result_invalid_stat`); `useFfaErrorMessage` (задача 12), который подставляет
`{offset}` (уже 1-based) и `{name}`.

Produces: `ffa.errors.*` (en + ru) для всех перечисленных кодов; `ffa.errors.ffa_result_invalid_score` удалён.

- [ ] **Шаг 1. Усилить утверждение теста до локализованного текста.** Текущие строки теста
      `stageEditor.ffaScoring.behavior.test.tsx` (тест `puts the server's refusal on the formula field`,
      введён задачей 12):

```tsx
    expect(errorFor(area("Points formula"))).toContain("kils");
```

      Замена:

```tsx
    // The server counts characters from zero and the organizer from one, so the
    // position shown is the one they can actually point at in the field.
    expect(errorFor(area("Points formula"))).toBe(
      "Position 14: unknown name kils. Use a column key, place, place_pts or teams."
    );
```

- [ ] **Шаг 2. Запустить — красный.**
      `cd frontend && bunx vitest run stageEditor.ffaScoring.behavior`
      Ожидание: FAIL — `expected "unknown name 'kils' at 13" to be "Position 14: unknown name kils. …"`
      (ключа `ffa.errors.ffa_formula_unknown_name` ещё нет, хук отдаёт серверный `msg`).

- [ ] **Шаг 3. Строки ошибок.** Текущие строки `frontend/src/i18n/messages/en.json:6394-6401`:

```json
      "ffa_result_unknown_team": "One of the teams is not seated in this lobby.",
      "ffa_result_duplicate_team": "A team is listed twice — every team gets exactly one line.",
      "ffa_result_missing_team": "Every team of the lobby needs a line in the game.",
      "ffa_result_invalid_score": "A score cannot be negative.",
      "ffa_result_mixed_placement": "Give a place to every team, or to none of them.",
      "ffa_result_placement_required": "This stage pays for places, so every team needs one.",
      "ffa_result_invalid_placement": "Places run from 1 to the number of teams, each taken exactly once.",
      "ffa_reason_required": "Changing a game that has been played needs a reason.",
```

      Замена:

```json
      "ffa_result_unknown_team": "One of the teams is not seated in this lobby.",
      "ffa_result_duplicate_team": "A team is listed twice — every team gets exactly one line.",
      "ffa_result_missing_team": "Every team of the lobby needs a line in the game.",
      "ffa_result_unknown_stat": "The game carries a value for a column this stage does not record. Add the column, or drop the value.",
      "ffa_result_missing_stat": "Every column of the stage needs a value — an empty field is not a zero. Type 0 for a team that scored nothing.",
      "ffa_result_invalid_stat": "A value is a number between 0 and 1000000000.",
      "ffa_result_mixed_placement": "Give a place to every team, or to none of them.",
      "ffa_result_placement_required": "This stage's formula pays for places, so every team needs one.",
      "ffa_result_invalid_placement": "Places run from 1 to the number of teams, each taken exactly once.",
      "ffa_columns_too_many": "A stage records at most 10 columns. Remove one before adding another.",
      "ffa_column_key_invalid": "A key starts with a lowercase Latin letter and holds only lowercase letters, digits and underscores, up to 24 characters.",
      "ffa_column_key_reserved": "That key is a name the formula language already uses (place, place_pts, teams, min, max, abs, round, if). Pick another one.",
      "ffa_column_duplicate": "Two columns share a key. Every key is used once.",
      "ffa_column_in_use": "Games of this stage already hold values under that key. Keep the column, or void those games first.",
      "ffa_formula_syntax": "Position {offset}: the formula cannot be read. Check the brackets and the operators.",
      "ffa_formula_unknown_name": "Position {offset}: unknown name {name}. Use a column key, place, place_pts or teams.",
      "ffa_formula_unsupported": "Position {offset}: this is not allowed in a formula. Arithmetic, comparisons, and / or / not, min, max, abs, round and if are.",
      "ffa_formula_too_complex": "The formula is too long to evaluate. Shorten it, or split the rule into fewer steps.",
      "ffa_reason_required": "Changing a game that has been played needs a reason.",
```

      Текущие строки `frontend/src/i18n/messages/ru.json:6394-6401`:

```json
      "ffa_result_unknown_team": "Одна из команд не сидит в этом лобби.",
      "ffa_result_duplicate_team": "Команда указана дважды — у каждой ровно одна строка.",
      "ffa_result_missing_team": "В игре нужна строка для каждой команды лобби.",
      "ffa_result_invalid_score": "Счёт не может быть отрицательным.",
      "ffa_result_mixed_placement": "Проставьте место каждой команде или никому.",
      "ffa_result_placement_required": "Стадия начисляет очки за место, поэтому место нужно каждой команде.",
      "ffa_result_invalid_placement": "Места идут от 1 до числа команд, каждое занято ровно один раз.",
      "ffa_reason_required": "Чтобы изменить сыгранную игру, нужна причина.",
```

      Замена:

```json
      "ffa_result_unknown_team": "Одна из команд не сидит в этом лобби.",
      "ffa_result_duplicate_team": "Команда указана дважды — у каждой ровно одна строка.",
      "ffa_result_missing_team": "В игре нужна строка для каждой команды лобби.",
      "ffa_result_unknown_stat": "В игре есть значение столбца, которого на стадии нет. Добавьте столбец или уберите значение.",
      "ffa_result_missing_stat": "Значение нужно каждому столбцу стадии — пустое поле это не ноль. Поставьте 0 команде, которая ничего не набрала.",
      "ffa_result_invalid_stat": "Значение — число от 0 до 1000000000.",
      "ffa_result_mixed_placement": "Проставьте место каждой команде или никому.",
      "ffa_result_placement_required": "Формула стадии начисляет очки за место, поэтому место нужно каждой команде.",
      "ffa_result_invalid_placement": "Места идут от 1 до числа команд, каждое занято ровно один раз.",
      "ffa_columns_too_many": "На стадии не больше 10 столбцов. Удалите один, чтобы добавить другой.",
      "ffa_column_key_invalid": "Ключ начинается со строчной латинской буквы и состоит из строчных букв, цифр и подчёркиваний — до 24 символов.",
      "ffa_column_key_reserved": "Это имя уже занято языком формулы (place, place_pts, teams, min, max, abs, round, if). Выберите другой ключ.",
      "ffa_column_duplicate": "У двух столбцов одинаковый ключ. Каждый ключ встречается один раз.",
      "ffa_column_in_use": "В играх стадии уже есть значения с этим ключом. Оставьте столбец или сначала аннулируйте эти игры.",
      "ffa_formula_syntax": "Позиция {offset}: формулу не разобрать. Проверьте скобки и знаки.",
      "ffa_formula_unknown_name": "Позиция {offset}: неизвестное имя {name}. Используйте ключ столбца, place, place_pts или teams.",
      "ffa_formula_unsupported": "Позиция {offset}: так в формуле нельзя. Доступны арифметика, сравнения, and / or / not, min, max, abs, round и if.",
      "ffa_formula_too_complex": "Формула слишком длинная для вычисления. Сократите её или разбейте правило на меньшее число шагов.",
      "ffa_reason_required": "Чтобы изменить сыгранную игру, нужна причина.",
```

      И каст ключа в `useFfaErrorMessage` (`frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx`,
      введён задачей 12) — текущая строка:

```tsx
      const key = `ffa.errors.${entry.code}` as "ffa.errors.ffa_reason_required";
```

      Замена (теперь есть ключ, чей тип значений включает оба аргумента):

```tsx
      const key = `ffa.errors.${entry.code}` as "ffa.errors.ffa_formula_unknown_name";
```

- [ ] **Шаг 4. Запустить — зелёный.**
      `cd frontend && bunx vitest run stageEditor.ffaScoring.behavior FfaGameResultsDialog.behavior FfaLobbyTable.behavior`
      Ожидание: PASS. Тесты диалога (задача 11) и таблицы (задача 10) не пинят тексты `ffa.errors.*`
      (см. §9 спеки), поэтому переименования строк их не трогают; падение здесь означает, что соседняя задача
      ещё не влита, — это допустимо (см. вступление раздела), но тест самой задачи 14
      (`stageEditor.ffaScoring.behavior`) обязан пройти.
      Плюс проверить, что удалённый ключ нигде не читается:
      `cd frontend && bunx vitest run --reporter=dot` не нужен — достаточно
      `rg -n "ffa_result_invalid_score" frontend/src backend` → пусто (бэкенд-код удалила задача 2).

- [ ] **Шаг 5. Коммит.**
      `git add frontend/src/i18n/messages/en.json frontend/src/i18n/messages/ru.json frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx frontend/src/app/admin/tournaments/\[id\]/bracket/stageEditor.ffaScoring.behavior.test.tsx`
      `git commit -m "feat(ffa): translate the column and formula rejections"`

- [ ] **Шаг 6. Документация разработчика — английская.**
      `frontend/src/app/(site)/docs/_content/en/dev/tournaments.mdx:72` — текущий абзац:

```mdx
An FFA stage never pairs teams. Its items are ordinary groups, but a group holds ONE encounter for the whole group, and that encounter carries `format: "ffa"` instead of two sides. It is a **lobby**: 2 to 100 participants, `best_of` games, and in each game every participant has exactly one placement and one score. A lobby's `home_team_id` and `away_team_id` are empty, and the encounter lists do not answer it by default — read a lobby through its own routes:
```

      Замена:

```mdx
An FFA stage never pairs teams. Its items are ordinary groups, but a group holds ONE encounter for the whole group, and that encounter carries `format: "ffa"` instead of two sides. It is a **lobby**: 2 to 100 participants, `best_of` games, and in each game every participant has one placement and one value per column the stage records. A lobby's `home_team_id` and `away_team_id` are empty, and the encounter lists do not answer it by default — read a lobby through its own routes:
```

      Строка 79 — текущий абзац:

```mdx
`GET /api/v1/tournaments/{id}/stages/{stage_id}/ffa` answers every lobby of the stage and `GET /api/v1/encounters/{encounter_id}/ffa` answers one; the shape is identical either way. It carries `advance_count` (the group's override, else the stage's number; `null` draws no cut line), `rules` and `rows`. A row is one participant: `team_id`, `slot`, `position`, `tie_group`, `points`, `games_played`, `wins`, `score` and a `games` array with one cell per game position. A game nobody has opened has `state: null` — that is not a zero, it is a game nobody has entered.
```

      Замена:

```mdx
`GET /api/v1/tournaments/{id}/stages/{stage_id}/ffa` answers every lobby of the stage and `GET /api/v1/encounters/{encounter_id}/ffa` answers one; the shape is identical either way. It carries `advance_count` (the group's override, else the stage's number; `null` draws no cut line), `rules` and `rows`. A row is one participant: `team_id`, `slot`, `position`, `tie_group`, `points`, `games_played`, `wins`, `stats` (the sum of each column) and a `games` array with one cell per game position — each cell being `placement`, `points` and its own `stats`. A game nobody has opened has `state: null` — that is not a zero, it is a game nobody has entered. These two routes are public and answer the PUBLIC columns only: a column with `public: false` is absent from `rules.columns`, from every row's `stats` and from every cell's `stats`. The organizer reads the unabridged lobby through `GET /api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa`, which needs `match.update` on the tournament's workspace.
```

      Строка 81 — текущий абзац:

```mdx
The rules are resolved from the stage's `ffa_scoring` field: `placement_points` (points for 1st, 2nd, …; a shorter list scores the tail at zero), `score_points` (the multiplier on the raw score) and `score_label` — what the score column counts ("Kills", "Points"), which the frontend prints verbatim. A game's points are `placement_points[place − 1] + score × score_points`.
```

      Замена:

```mdx
The rules are resolved from the stage's `ffa_scoring` field: `columns` (what a game records per team — `key`, `label`, `public`, `better`; at most 10), `placement_points` (points for 1st, 2nd, …; a shorter list scores the tail at zero) and `formula` — the expression a game's points are computed with. The formula reads the column keys plus `place` (the placement in that game), `place_pts` (`placement_points[place − 1]`, zero past the end) and `teams` (the size of the lobby); it supports arithmetic, comparisons, `and`/`or`/`not`, `min`, `max`, `abs`, `round` and `if(cond, then, else)`, and nothing else. It is parsed with the standard `ast` module against a whitelist of nodes — never `eval` — in `backend/shared/domain/ffa_formula.py`, and a rejected formula answers 422 with a code (`ffa_formula_syntax`, `ffa_formula_unknown_name`, `ffa_formula_unsupported`, `ffa_formula_too_complex`) and the position inside the string. A game's points are that expression, rounded to four decimals; division by zero is zero, and negative points are legal (a penalty column). Whether a placement is REQUIRED when a game is entered is not a setting: it is whether the formula reads `place` or `place_pts`. Without it, the placements are derived from the points of the game, ties sharing a place. Points are never stored — the write, the standings and the lobby read all compute them from the raw values, so correcting the formula re-scores every game of the stage. That correction is refused with 409 once any element of the stage has seeded a stage that has already started, and removing or renaming a column whose key already has values is refused with 422 `ffa_column_in_use`.
```

      Строка 122 — текущий абзац:

```mdx
An FFA stage ranks a group from its lobbies, and its metrics are different ones: a lobby has no opponent, so head-to-head and both Buchholz variants compute nothing there at all. What it does have is `ffa_game_wins` (games won from 1st place; a shared first counts), `ffa_score` (the raw score summed), `ffa_best_placement` and `ffa_last_placement` (the placement in the last game played). The placement metrics are returned negated, so one "higher is better" sort covers every metric. The default preset is `ffa_default`: `points`, `ffa_game_wins`, `ffa_score`, `ffa_last_placement`.
```

      Замена:

```mdx
An FFA stage ranks a group from its lobbies, and its metrics are different ones: a lobby has no opponent, so head-to-head and both Buchholz variants compute nothing there at all. What it does have is `ffa_game_wins` (games won from 1st place; a shared first counts), `ffa_best_placement`, `ffa_last_placement` (the placement in the last game played), and one metric per column the stage records: `ffa_stat:<key>`, the sum of that column. A column whose `better` is `lower` (deaths, penalties) sorts ascending. The placement metrics and the descending column sums are returned negated, so one "higher is better" sort covers every metric. An `ffa_stat:` entry naming a column the stage no longer records is dropped like any unknown metric. The default preset is `ffa_default`: `points`, `ffa_game_wins`, `ffa_stat:<first column>` when the stage has one, then `ffa_last_placement`.
```

- [ ] **Шаг 7. Документация разработчика — русская.**
      `frontend/src/app/(site)/docs/_content/ru/dev/tournaments.mdx:72` — текущий абзац:

```mdx
FFA-стадия не сводит команды парами: её элементы — обычные группы, но встреча в такой группе одна на всю группу и несёт `format: "ffa"` вместо двух сторон. Это **лобби**: от 2 до 100 участников, `best_of` игр, в каждой игре у каждого участника ровно одно место и один счёт. Поля `home_team_id` и `away_team_id` у лобби пустые, и списки встреч по умолчанию его не отдают — читайте лобби через его собственные маршруты:
```

      Замена:

```mdx
FFA-стадия не сводит команды парами: её элементы — обычные группы, но встреча в такой группе одна на всю группу и несёт `format: "ffa"` вместо двух сторон. Это **лобби**: от 2 до 100 участников, `best_of` игр, в каждой игре у каждого участника одно место и по одному значению на каждый столбец, который ведёт стадия. Поля `home_team_id` и `away_team_id` у лобби пустые, и списки встреч по умолчанию его не отдают — читайте лобби через его собственные маршруты:
```

      Строка 79 — текущий абзац:

```mdx
`GET /api/v1/tournaments/{id}/stages/{stage_id}/ffa` отдаёт все лобби стадии, `GET /api/v1/encounters/{encounter_id}/ffa` — одно; форма ответа в обоих случаях одна и та же. В ней приходят `advance_count` (переопределение группы, иначе число стадии; `null` — линии выхода нет), `rules` и `rows`. Каждая строка — участник: `team_id`, `slot`, `position`, `tie_group`, `points`, `games_played`, `wins`, `score` и массив `games` по одной ячейке на позицию игры. У неоткрытой игры `state` равен `null` — это не ноль очков, а игра, которую ещё никто не вводил.
```

      Замена:

```mdx
`GET /api/v1/tournaments/{id}/stages/{stage_id}/ffa` отдаёт все лобби стадии, `GET /api/v1/encounters/{encounter_id}/ffa` — одно; форма ответа в обоих случаях одна и та же. В ней приходят `advance_count` (переопределение группы, иначе число стадии; `null` — линии выхода нет), `rules` и `rows`. Каждая строка — участник: `team_id`, `slot`, `position`, `tie_group`, `points`, `games_played`, `wins`, `stats` (сумма по каждому столбцу) и массив `games` по одной ячейке на позицию игры; в ячейке — `placement`, `points` и собственный `stats`. У неоткрытой игры `state` равен `null` — это не ноль очков, а игра, которую ещё никто не вводил. Оба маршрута публичные и отдают только ПУБЛИЧНЫЕ столбцы: столбца с `public: false` нет ни в `rules.columns`, ни в `stats` строки, ни в `stats` ячейки. Организатор читает лобби целиком через `GET /api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa` — нужно право `match.update` на воркспейс турнира.
```

      Строка 81 — текущий абзац:

```mdx
Правила считаются из поля `ffa_scoring` стадии: `placement_points` (очки за 1-е, 2-е, … место; хвост за концом списка стоит ноль), `score_points` (множитель сырого счёта) и `score_label` — подпись колонки счёта («Убийства», «Очки»), которую фронтенд показывает как есть. Очки игры — `placement_points[место − 1] + счёт × score_points`.
```

      Замена:

```mdx
Правила считаются из поля `ffa_scoring` стадии: `columns` (что игра записывает по каждой команде — `key`, `label`, `public`, `better`; не больше 10), `placement_points` (очки за 1-е, 2-е, … место; за концом списка — ноль) и `formula` — выражение, по которому считаются очки игры. Формула читает ключи столбцов плюс `place` (место в этой игре), `place_pts` (`placement_points[место − 1]`, ноль за концом списка) и `teams` (размер лобби); доступны арифметика, сравнения, `and`/`or`/`not`, `min`, `max`, `abs`, `round` и `if(условие, то, иначе)` — и больше ничего. Разбор идёт стандартным модулем `ast` по белому списку узлов, без `eval` (`backend/shared/domain/ffa_formula.py`); отвергнутая формула отвечает 422 с кодом (`ffa_formula_syntax`, `ffa_formula_unknown_name`, `ffa_formula_unsupported`, `ffa_formula_too_complex`) и позицией в строке. Очки игры — значение этого выражения, округлённое до 4 знаков; деление на ноль даёт ноль, отрицательные очки допустимы (столбец-штраф). Обязательно ли место при вводе игры — не настройка, а факт: читает ли формула `place` или `place_pts`. Если не читает, места выводятся из очков игры, равные очки делят место. Очки нигде не хранятся — запись, таблица и чтение лобби считают их из сырых значений, поэтому правка формулы пересчитывает все игры стадии. Такая правка отвергается с 409, как только любой элемент стадии посеял уже начатую следующую стадию, а удаление или переименование столбца, под ключом которого уже есть значения, — с 422 `ffa_column_in_use`.
```

      Строка 122 — текущий абзац:

```mdx
На FFA-стадии таблица группы считается по её лобби, и метрики другие — у лобби нет соперника, поэтому личные встречи и обе разновидности Бухгольца там не вычисляются вовсе. Доступны `ffa_game_wins` (число игр, выигранных с 1-го места; общее первое место считается), `ffa_score` (сумма сырого счёта), `ffa_best_placement` (лучшее место) и `ffa_last_placement` (место в последней сыгранной игре). Метрики мест возвращаются со знаком минус, чтобы сортировка «больше — лучше» оставалась одна на все метрики. Пресет по умолчанию — `ffa_default`: `points`, `ffa_game_wins`, `ffa_score`, `ffa_last_placement`.
```

      Замена:

```mdx
На FFA-стадии таблица группы считается по её лобби, и метрики другие — у лобби нет соперника, поэтому личные встречи и обе разновидности Бухгольца там не вычисляются вовсе. Доступны `ffa_game_wins` (число игр, выигранных с 1-го места; общее первое место считается), `ffa_best_placement` (лучшее место), `ffa_last_placement` (место в последней сыгранной игре) и по одной метрике на каждый столбец стадии — `ffa_stat:<ключ>`, сумма этого столбца. Столбец с `better: "lower"` (смерти, штрафы) сортируется по возрастанию. Метрики мест и суммы «по возрастанию» возвращаются со знаком минус, чтобы сортировка «больше — лучше» оставалась одна на все метрики. Запись `ffa_stat:` с ключом столбца, которого на стадии больше нет, отбрасывается, как любая неизвестная метрика. Пресет по умолчанию — `ffa_default`: `points`, `ffa_game_wins`, `ffa_stat:<первый столбец>` (если он есть), `ffa_last_placement`.
```

- [ ] **Шаг 8. Пометки в плане FFA и статусы.**
      `docs/plans/2026-09-24-ffa-encounters.md:179-180` — текущие строки:

```md
`stage.settings_json` получает блок `ffa_scoring`. Валидируется на записи `StageSettings`
(`backend/tournament-service/src/schemas/admin/stage.py:29`), хранится как есть — так же, как `scoring`.
```

      Замена:

```md
> **Заменено.** Форма блока `ffa_scoring` и его хранение изменены: столбцы организатора и формула очков —
> см. [`2026-09-26-ffa-custom-scoring.md`](./2026-09-26-ffa-custom-scoring.md) §3 и §4. Ниже — исходная
> редакция, она сохранена как история решения.

`stage.settings_json` получает блок `ffa_scoring`. Валидируется на записи `StageSettings`
(`backend/tournament-service/src/schemas/admin/stage.py:29`), хранится как есть — так же, как `scoring`.
```

      `docs/plans/2026-09-24-ffa-encounters.md:234` — текущая строка:

```md
`normalize_game_lines(lines, participant_ids, rules)` (§7.2, задача 4) — одно место правил:
```

      Замена:

```md
> **Заменено.** Проверка значений игры переписана под столбцы стадии (`ffa_result_unknown_stat`,
> `ffa_result_missing_stat`, `ffa_result_invalid_stat`; `ffa_result_invalid_score` удалён), а «формула платит
> за место» стало «формула читает `place`/`place_pts`»:
> см. [`2026-09-26-ffa-custom-scoring.md`](./2026-09-26-ffa-custom-scoring.md) §5.2.

`normalize_game_lines(lines, participant_ids, rules)` (§7.2, задача 4) — одно место правил:
```

      `docs/plans/2026-09-24-ffa-encounters.md:251-252` — текущие строки:

```md
`очки игры = placement_points[place − 1] (0, если место за концом таблицы) + score × score_points`.
Итог участника в группе — сумма по подтверждённым играм всех лобби группы.
```

      Замена:

```md
> **Заменено.** Очки игры считает формула стадии, а метрика `ffa_score` заменена на `ffa_stat:<ключ>` —
> сумму любого столбца: см. [`2026-09-26-ffa-custom-scoring.md`](./2026-09-26-ffa-custom-scoring.md) §5.3
> и §5.4.

`очки игры = placement_points[place − 1] (0, если место за концом таблицы) + score × score_points`.
Итог участника в группе — сумма по подтверждённым играм всех лобби группы.
```

      `docs/plans/2026-09-24-ffa-encounters.md:3` — текущая строка:

```md
**Status:** implementing — F1 (tasks 1–3), F2 (tasks 4–9) and F3 (tasks 10–14) on `develop`; F4–F5 pending (design only)
```

      Замена:

```md
**Status:** implementing — F1 (tasks 1–3), F2 (tasks 4–9) and F3 (tasks 10–14) on `develop`; F4–F5 pending (design only).
§4.2, §5.2 и §5.3 заменены работой [«FFA: столбцы организатора и формула очков»](./2026-09-26-ffa-custom-scoring.md)
```

      `docs/plans/2026-09-26-ffa-custom-scoring.md:3` — текущая строка:

```md
**Status:** design approved (2026-09-26); план — [`2026-09-26-ffa-custom-scoring-plan.md`](./2026-09-26-ffa-custom-scoring-plan.md).
```

      Замена:

```md
**Status:** implemented (2026-09-26) — план работ [`2026-09-26-ffa-custom-scoring-plan.md`](./2026-09-26-ffa-custom-scoring-plan.md), задачи 1–14
```

      `docs/plans/2026-09-26-ffa-custom-scoring-plan.md:3` (шапка плана, который собирается из разделов A–D) —
      текущая строка:

```md
**Status:** ready to implement (2026-09-26)
```

      Замена:

```md
**Status:** implemented (2026-09-26) — задачи 1–14 выпущены одним релизом; проверки §«Финальная проверка» пройдены
```

- [ ] **Шаг 9. Коммит документации.**
      `git add frontend/src/app/\(site\)/docs/_content/en/dev/tournaments.mdx frontend/src/app/\(site\)/docs/_content/ru/dev/tournaments.mdx docs/plans/2026-09-24-ffa-encounters.md docs/plans/2026-09-26-ffa-custom-scoring.md docs/plans/2026-09-26-ffa-custom-scoring-plan.md`
      `git commit -m "docs(ffa): describe organizer columns and the points formula"`

- [ ] **Шаг 10. Финальная проверка всего релиза.** Выполняется один раз, после того как задачи 1–14 влиты.
      Команды — по порядку, каждая должна закончиться успехом:

```
cd backend && uv run ruff check . && uv run ruff format --check .
cd backend && uv run pytest shared/tests/test_ffa_formula.py shared/tests/test_ffa_scoring.py shared/tests/test_rpc_error_details.py -v
cd backend && uv run pytest tournament-service/tests/test_ffa_stage_settings.py tournament-service/tests/test_ffa_standings.py tournament-service/tests/test_standings_ranking.py -v
cd backend && uv run pytest tournament-service/tests/test_ffa_results_integration.py tournament-service/tests/test_ffa_schema_integration.py tournament-service/tests/test_ffa_containment_integration.py tournament-service/tests/test_ffa_generation.py -v
cd backend && uv run pytest shared/tests tournament-service/tests app-service/tests tests
cd backend && uv run alembic upgrade head && uv run alembic check
cd backend && uv run alembic downgrade -1 && uv run alembic upgrade head
cd backend && uv run python scripts/export_erd.py
bash backend/scripts/export_openapi_schemas.sh
python3 backend/scripts/check_rpc_docs.py
cd frontend && bun run gen:api
cd frontend && bunx vitest run src/lib/tournament/tiebreakers.test.ts src/lib/ffa src/components/ffa src/components/admin/ffa
cd frontend && bunx vitest run stageEditor.ffaScoring.behavior stageEditor.tiebreakers.behavior stageEditor.bestOf.behavior stageEditor.ffaRoundSchedule.behavior stageEditor.roundSchedule.behavior
cd frontend && bun run test:vitest
cd frontend && bunx tsc --noEmit -p tsconfig.json
cd frontend && bunx eslint src/lib/tournament/tiebreakers.ts src/lib/bracket/projection.ts src/lib/ffa/scoring-presets.ts src/types/tournament.types.ts src/types/ffa.types.ts "src/app/admin/tournaments/[id]/bracket/stageForm.ts" "src/app/admin/tournaments/[id]/bracket/components/FfaScoringSection.tsx" "src/app/admin/tournaments/[id]/bracket/components/StageEditor.tsx" "src/app/admin/tournaments/[id]/bracket/components/StageSettingsSections.tsx" src/components/StandingsTable.tsx src/components/ffa/FfaLobbyTable.tsx src/components/admin/ffa/FfaGameResultsDialog.tsx src/services/ffa.service.ts
cd frontend && node scripts/check-design-compliance.mjs
cd frontend && node scripts/check-zone-boundaries.mjs
cd gateway && go vet ./internal/tournament/... && go test -race ./internal/tournament/...
cd gateway && go test -race ./...
```

      `alembic downgrade -1` идёт на базе, где ещё НЕТ стадий с новыми столбцами: `ffa0002.downgrade` отказывает
      (`RuntimeError`), если у стадии столбцы не ровно `[score]` или формула не подходит под
      `^(place_pts \+ )?score( \* [0-9.]+)?$` (спека §3.3) — это и есть ожидаемое поведение на настроенной базе,
      и там откат делается восстановлением дампа, а не миграцией.
      `export_erd.py` меняет `docs/database_erd.md` и `frontend/src/app/(site)/docs/schema.generated.json` —
      оба идут в коммит проверки, если поменялись.

- [ ] **Шаг 11. Ручной сценарий на dev-стенде.** Один проход, целиком:

  1. Поднять стенд (`backend`: `uv run …` сервисы + `gateway`, `cd frontend && bun run dev`), войти
     администратором воркспейса.
  2. Турнир → вкладка **Bracket** → создать стадию типа **FFA League**, открыть раздел **FFA scoring**.
  3. Пресет **Battle royale** → столбец `kills` («Kills», в таблице, higher). **Add column** → ключ `deaths`,
     подпись «Deaths», снять «In the table», направление **Lower is better**. Формула:
     `kills * 2 - deaths`. Очки за место — удалить все (список пуст). **Save changes** → сохранение проходит.
  4. Раздел **Tiebreakers** → в каталоге есть «Sum: Kills» и «Sum: Deaths»; включить «Sum: Kills».
     **Save changes**.
  5. Раздел **Items** → создать группу, посадить 3 команды, сгенерировать лобби, открыть страницу лобби в
     админке → **Enter game 1**: поля `Kills` и `Deaths` на каждую команду (у `Deaths` — пометка, что зрителям
     он не виден), место не требуется (формула не читает `place`). Ввести `12/3`, `7/5`, `4/1` → сохранить.
  6. Публичная страница лобби (в другой вкладке, без сессии организатора): в таблице есть столбцы `Pts`,
     `Games`, `Kills` — и НЕТ `Deaths`; в ячейке игры сверху место, снизу очки; в легенде «Points = kills * 2 -
     deaths». Места выведены из очков: 21, 9, 7 → 1, 2, 3.
  7. `curl` публичного JSON:
     `curl -s "http://localhost:8080/api/v1/tournaments/<id>/stages/<stage_id>/ffa" | jq '.[0].rules.columns, .[0].rows[0].stats, .[0].rows[0].games[0].stats'`
     → ни в одном из трёх мест нет ключа `deaths`. Тот же запрос на
     `/api/v1/admin/tournaments/<id>/stages/<stage_id>/ffa` с куками организатора → `deaths` есть везде.
  8. Вернуться в **FFA scoring**, заменить формулу на `kills - deaths`, сохранить → публичная таблица и
     `Standing` показывают новые очки (9, 2, 3) и новые места (1, 3, 2) без ручного пересчёта; легенда
     показывает новую формулу.
  9. Ввести в формулу `kils` (опечатка) и сохранить → под полем формулы: «Позиция 14: неизвестное имя kils…»
     (в en-локали — «Position 14: unknown name kils…»), стадия не сохранена.
  10. Попробовать удалить столбец `kills` и сохранить → 422, сообщение «В играх стадии уже есть значения с этим
      ключом…». Вернуть столбец.
  11. Активировать следующую стадию (посев из этой) → правка формулы отвечает 409 с текстом про уже посеянную
      стадию; правка подписи столбца и флажка «In the table» при этом по-прежнему сохраняется.

- [ ] **Шаг 12. Коммит артефактов проверки (если что-то изменилось).**
      `git add docs/database_erd.md frontend/src/app/\(site\)/docs/schema.generated.json frontend/src/types/api.generated.ts gateway/docs`
      `git commit -m "chore(ffa): refresh generated schemas after the scoring rework"`

---

---

## Приложение. Отклонения разделов от контракта

Контракт задач составлялся до сверки с кодом; ниже — где и почему разделы от него отошли. Всё перечисленное уже
учтено в задачах выше.

### Раздел A (задачи 1–4)

1. **`settings_json` не существует.** Спека §3.1 хранит блок в `stage.settings_json.ffa_scoring`, но ревизия
   `stjson01` (`backend/migrations/versions/stjson01_stage_settings_columns.py:1-29`) уже сняла эту колонку и
   разложила регламент по колонкам `stage`. Подтверждено `Main`: блок API остаётся `ffa_scoring`, хранение —
   колонки `ffa_columns jsonb` + `ffa_formula varchar(500)` (+ существующая `ffa_placement_points`), их добавляет
   задача 5.

2. **`parse_ffa_rules(settings)` → `ffa_rules(stage)`.** В коде функция называется `ffa_rules(stage: Any | None)`
   (`backend/shared/domain/ffa_scoring.py:52-63`), её импортирует `standings/service.py:15`;
   `parse_ffa_rules` не существует. По решению `Main` имя и сигнатура сохранены, функция читает
   `stage.ffa_columns` / `stage.ffa_placement_points` / `stage.ffa_formula`.

3. **`FfaScoring` живёт в `src/schemas/stage.py:55-71`, а не в `schemas/admin/stage.py`.** `admin/stage.py:6`
   только импортирует её (`from src.schemas.stage import FfaScoring, ...`). Задача 3 правит `schemas/stage.py`.

4. **`columns` и `formula` не обязательны, а имеют дефолт.** Контракт требует «ОБА поля обязательны», но
   `StageCreate.ffa_scoring` / `StageUpdate.ffa_scoring` / `_StageRegulationRead.ffa_scoring` объявлены как
   `Field(default_factory=FfaScoring)` (`schemas/admin/stage.py:36,61`, `schemas/stage.py:87`) — модель обязана
   конструироваться без аргументов. Дефолты выбраны ровно те, что спека §3.1 называет поведением стадии без блока:
   `columns = [{"key": "score", "label": "Счёт"}]`, `formula = "score"`. Частично заданный блок по-прежнему
   отвергается: `{"columns": [{"key": "kills", ...}]}` без формулы даёт 422 `ffa_formula_unknown_name`.

5. **Добавлено публичное имя `round_half_up` в `ffa_formula.py`.** Контракт его не перечисляет. Оно нужно и
   функции `round()` формулы, и округлению очков игры до 4 знаков в `game_points`/`team_totals`: иначе в одной
   фиче было бы два разных правила округления (банковское у встроенного `round`, арифметическое у формулы).
   Также добавлены `Formula.node` (проверенное дерево, `compare=False`) и константы `DEFAULT_FORMULA`,
   `GAME_POINTS_DIGITS` в `ffa_scoring.py` — они не конфликтуют с контрактом.

6. **`field_entry` пришлось расширить.** Контракт говорит, что 422 несёт `ctx.offset`, но
   `shared/rpc/common.py:178-189` выбрасывал `ctx` из ответа. Задача 3 добавляет проброс скалярного `ctx`
   (не-скаляры отбрасываются: `ctx` ошибки `value_error` содержит сам объект `ValueError` и не сериализуется).

7. **`_tiebreak_order` получил keyword-only `rules`.** Контракт описывает только `normalize_tiebreak_order`.
   Без этого `_build_ffa_stage_standings` компилировал бы формулу стадии дважды за построение таблицы.

8. **Пресет `ffa_default` хранится без `ffa_stat:<key>`.** Ключ первого столбца зависит от стадии, поэтому он
   вставляется в `_tiebreak_order`, а не лежит в `RULE_PRESET_DEFAULTS`. Итоговый порядок совпадает с контрактом:
   `["points", "ffa_game_wins", "ffa_stat:<первый ключ>", "ffa_last_placement"]`, а при пустых столбцах — те же три
   метрики без третьей.

### Раздел B (задачи 5–8)

1. **`settings_json` больше нет — хранение в колонках стадии.** Контракт (и спека §3.1/§3.3) описывает
   `stage.settings_json.ffa_scoring`; колонка удалена миграцией `stjson01`
   (`backend/migrations/versions/stjson01_stage_settings_columns.py:187`, коммит `35416163`). По решению
   главного агента блок API остаётся `ffa_scoring`, а хранение — колонки `stage.ffa_columns jsonb NOT NULL
   DEFAULT '[{"key":"score","label":"Счёт","public":true,"better":"higher"}]'` и
   `stage.ffa_formula varchar(500) NOT NULL DEFAULT 'score'`; `ffa_placement_points` остаётся.
   Поэтому §3.3 шаг 2 в задаче 5 — не цикл по `settings_json`, а `ALTER TABLE` + цикл `UPDATE` по колонкам,
   и та же миграция удаляет `ffa_score_points`, `ffa_score_label` и CHECK `ck_stage_ffa_score_points`.
2. **`parse_ffa_rules(settings)` → `ffa_rules(stage)`.** В текущем коде функция домена называется
   `ffa_rules(stage)` и импортируется в `services/encounter/ffa.py:41` и `services/standings/service.py:15`.
   Имя и сигнатура сохраняются (подтверждено главным агентом); задача 6 не меняет `FfaEncounterService._rules`
   (`services/encounter/ffa.py:661-663`).
3. **`FfaScoring` живёт в `src/schemas/stage.py:55-71`,** а не в `schemas/admin/stage.py` (тот её только
   импортирует, `schemas/admin/stage.py:6`). Для раздела B это ничего не меняет — только адрес для задачи 3.
4. **`_merge_stage_settings` не существует.** Контракт ссылается на `admin/stage.py:101`; сегодня это
   `_apply_stage_fields` (`admin/stage.py:99-133`), и именно туда попадает запись блока `ffa_scoring` (задача 5,
   шаг 6) и сравнение «до/после» (задача 7).
5. **`tiebreak_order` — колонка `text[]`, а не ключ JSON.** Замена `ffa_score` → `ffa_stat:score` в миграции
   делается `array_replace(...)` по `tournament.stage.tiebreak_order` (обе стороны, вперёд и назад).
6. **Подпись ранжирования учитывает порядок столбцов.** Контракт говорит «набор ключей столбцов, `better`»;
   `_ranking_signature` сравнивает столбцы как упорядоченный кортеж `(key, better)`, потому что при пустом
   `tiebreak_order` пресет `ffa_league` (задача 4) берёт ПЕРВЫЙ ключ — перестановка столбцов способна
   переставить команды. Строже контракта, в ту же сторону.
7. **`game_points` получает третий аргумент.** Сегодня `game_points(line, rules)`
   (`services/encounter/ffa.py:630`); по контракту задачи 2 — `game_points(line, rules, teams)`. В `_read_cell`
   `teams` — число строк ИМЕННО этой игры (`len(game_lines)`), а не число мест в лобби.
8. **Маршрут шлюза использует `{id}`,** как написано в контракте, хотя соседние админские маршруты турнира
   пишут `{tournament_id}` (`admin_misc_routes.go:57-77`). Конфликта нет; форма совпадает с публичным
   `/api/v1/tournaments/{id}/stages/{stage_id}/ffa` (`routes.go:29`).
9. **`schemas.json` не правится руками** — генерируется `backend/scripts/export_openapi_schemas.sh`
   (режим `--check` — CI-гейт). Ручная JSON-вставка была бы затёрта следующей регенерацией.

### Раздел C (задачи 9–11)

1. **Фильтр `public` живёт в `FfaLobbyTable`, а не только в `public_view` (задача 10).** Контракт и §7.3 спеки
   описывают обрезку на бэкенде. Причина добавить её и на фронте: `FfaLobbyTable` — один компонент на три
   хоста, и один из них (`admin/.../matches/lobbies/page.tsx`) после задачи 9 кормит его АДМИНСКИМ чтением со
   скрытыми столбцами. Без фильтра тот же код, который рисует публичный бракет, печатал бы скрытые значения —
   разница была бы только в том, кто выбрал эндпоинт. Бэкендная обрезка остаётся и остаётся главной; это второй
   рубеж, и именно его проверяет тест «Итоги только публичных столбцов» из §9 спеки.

2. **Ключ `ffa.colScore` удаляется (контракт допускал «удалить, если больше не используется»).** Проверено: после
   задачи 10 его не читает никто — заголовки столбцов берутся из `column.label`. Одноимённый
   `users.matches.colScore` (en/ru `:3840`) — другой ключ и остаётся.

3. **Форматирование чисел (задача 10) — `String(Number(value.toFixed(2)))` для очков игры и итогов столбцов;
   `row.points.toFixed(1)` у колонки Pts остаётся как есть.** Контракт формат не задаёт. Обоснование в коде:
   очки игры — результат произвольной формулы, округлённый сервером до 4 знаков, и должны читаться как `12.5`,
   а не `12` или `12.0`; итог столбца — сумма введённых значений, у которой `42.0` вместо `42` было бы шумом;
   а вот колонка Pts читается вертикально, где рваная десятичная точка мешает, поэтому её `toFixed(1)` не
   трогаем.

4. **Скрытые столбцы в админской таблице лобби не показываются** (следствие п. 1). Организатор видит и вводит их
   в диалоге (задача 11) — там, где они и заводятся; §8.4 спеки описывает публичную таблицу и скрытых столбцов
   в ней не предполагает.

5. **Клиентской проверки «место обязательно» нет, хотя `requires_placement` теперь известен фронту.** Диалог
   меняет подпись и подсказку, но пустое место всё так же уезжает как `null`, и 422
   `ffa_result_placement_required` / `ffa_result_invalid_placement` отвечает сервер — как сегодня. Пустое
   ЗНАЧЕНИЕ столбца, наоборот, держится на клиенте: его сервер отличить не может, потому что нолик пришёл бы
   как настоящий ноль. Дублировать серверное правило про перестановку мест на клиенте — второй источник правды
   о формуле.

6. **`frontend/src/app/admin/tournaments/[id]/bracket/stageEditor.ffaRoundSchedule.behavior.test.tsx` правится
   двумя задачами.** Строку 142 (`FfaLobby.rules`) чинит задача 9, строку 120 (`Stage.ffa_scoring`) — задача 12
   вместе с типом `Stage`. Согласовано с `PlanFrontendEditorDocs`; между задачами 9 и 12 файл типизационно
   красный по строке 120 и поведенчески зелёный.

7. **`useFfaErrorMessage` (`FfaGameResultsDialog.tsx:26-40`) вынесен из задачи 11** — его правит задача 12
   (позиция и имя в ошибке формулы). Согласовано с `PlanFrontendEditorDocs`; хук остаётся в том же файле, в
   отдельный модуль не выносится.

8. **`FfaPregameRoom.tsx` и `(site)/encounters/[id]/page.tsx` изменений не требуют.** Проверено построчно: оба
   читают у лобби только `name`, `best_of`, `rows[].slot`, `rows[].team_name`, `rows[].team_image_url` и
   передают лобби в `FfaLobbyTable` целиком; ни `score`, ни `score_label`, ни `score_points` в них не
   встречаются.

### Раздел D (задачи 12–14)

1. **`backend/shared/rpc/common.py::field_entry`** — проброс скалярного `ctx` плоско в запись
   `details["fields"]` (по прецеденту `http_error`, `common.py:250-251`) делает задача 3; задача 12 его только
   читает (`entry.offset`, `entry.name`).
2. **`StageFfaScoring.columns` объявлен структурно в `types/tournament.types.ts` (`StageFfaColumn`), а не
   импортом `FfaColumn` из `types/ffa.types.ts`.** Причина: `ffa.types.ts:1` импортирует из
   `tournament.types.ts` (`EncounterGameState`, `EncounterResultStatus`), обратный импорт замкнул бы цикл.
   Формы идентичны и присваиваются структурно; публичное имя `FfaColumn` (контракт, задача 9) не меняется.
3. **Метрика `ffa_stat:` в публичной `StandingsTable` берёт подпись столбца из уже загруженных `stages`**
   (задача 13, шаг 7); ключ показывается, только пока запрос стадий не вернулся. Служебный `StandingsBrowser`
   админки стадию не грузит и показывает ключ.
4. **`DEFAULT_FFA_TIEBREAKERS` (`lib/bracket/projection.ts:95`) удалена, а не отредактирована** — заменена
   функцией `ffaDefaultTiebreakers(columns)`: пресет по умолчанию содержит `ffa_stat:<первый ключ>`, который
   зависит от стадии и константой быть не может. `defaultTiebreakOrder` и `tiebreakOrderForPreset` получили
   третий необязательный параметр; все четыре вызова в репозитории обновлены (шаг 6 задачи 13).
5. **Тест `offers the lobby tiebreakers, and only those` (`stageEditor.ffaScoring.behavior.test.tsx:341-357`)
   переписывает задача 13, а не 12**, хотя файл теста принадлежит задаче 12: в задаче 12 `ffa_score` ещё в
   каталоге и тест зелёный, ломает его именно задача 13. Оба места названы явно (задача 12 шаг 1, задача 13
   шаг 9).
