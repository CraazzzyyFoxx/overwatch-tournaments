# Форма ростера на уровне турнира — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Заменить восемь независимых реализаций «сколько игроков какой роли в команде» одной конфигурацией уровня турнира — картой `slot_code → count` с зарезервированным кодом `flex`, — так чтобы ростер без ролей («N флексов») стал выразим сквозь драфт, балансер и UI.

**Architecture:** Канон живёт в `shared/domain/roster_shape.py` рядом с `player_sub_roles.py`. Разрешается трёхуровневой цепочкой `tournament.roster_slots_json` → `workspace.default_roster_slots_json` → встроенный дефолт через `shared/services/roster_shape_access.py` — структурное зеркало уже работающего `division_grid_access.py`. Все локальные копии правила удаляются, включая обе TS-функции: фронт получает готовую форму с API (образец «server-driven конфиг», реестр зеркал стр. 239).

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic / Pydantic v2 (7 сервисов в uv-workspace), Next.js 15 / React 19 / TypeScript / Vitest, Rust `tournament_balancer` (не меняется).

**Design doc:** `docs/superpowers/specs/2026-08-05-tournament-roster-shape-design.md` — читать перед началом, там Decision Log с обоснованием каждого выбора.

---

## Команды проекта

| Действие | Команда |
|---|---|
| Тест одного файла (shared) | `cd backend && uv run pytest shared/tests/test_roster_shape.py -v` |
| Тест одного файла (сервис) | `cd backend && uv run pytest balancer-service/tests/test_x.py -v` |
| Все suites бэкенда | `cd backend && for svc in shared app-service parser-service balancer-service tournament-service analytics-service identity-service discord-service; do uv run pytest "$svc/tests"; done` |
| **Ре-экспорт манифеста гейтвея** | `cd backend && UV=<путь-к-uv> bash scripts/export_openapi_schemas.sh` |
| Проверка манифеста (как в CI) | `cd backend && UV=<путь-к-uv> bash scripts/export_openapi_schemas.sh --check` |
| Тест фронта | `cd frontend && bunx vitest run src/lib/roster-shape.test.ts` |
| Линт фронта | `cd frontend && bun run lint` |
| Миграция | `make migrate` |

**Важно:** сервисы — отдельные пакеты uv-workspace с собственным `src`. Один `pytest` по всем сразу упадёт на коллизии top-level `src`. Всегда по одному пакету.

**Важно:** CI проверяет закоммиченный `gateway/internal/openapi/schemas.json` против Pydantic-моделей. Любая правка схем требует ре-экспорта в том же коммите.

---

**Грабли с `UV`.** На Git-for-Windows bash дочерний шелл скрипта не видит `uv` в PATH, и скрипт падает на `line 49: uv: command not found`. Скрипт это предусматривает переменной `UV` (`uv_bin="${UV:-uv}"`, строка 32), но передать её через `export` из родительского шелла в этой среде не удалось. Рабочий способ — воспроизвести шаги скрипта напрямую (`uv run python backend/scripts/export_openapi_schemas.py` в каждом сервисе, затем `merge_openapi_schemas.py`), либо запустить в среде, где `uv` виден дочерним процессам. В CI переменная не нужна.

**Wire-facing `WorkspaceRead` живёт в app-service, не в tournament-service.** `backend/app-service/src/schemas/workspace.py:36` — это та схема, которую читает фронтенд, и там же `WorkspaceCreate`/`WorkspaceUpdate` с `default_division_grid_version_id`. Копия в `tournament-service/src/schemas/workspace.py` обслуживает внутренние чтения. Поле `default_roster_slots_json` нужно в ОБЕИХ: в tournament-service (сделано в Task 5) и в app-service (Task 6, вместе с записью).

# Фаза 1. Канон в shared

## Task 1: `RosterShape` и парсер

**Files:**
- Create: `backend/shared/domain/roster_shape.py`
- Test: `backend/shared/tests/test_roster_shape.py`

> **Task 1 исправлен после ревью качества** (коммит `fix(shared): make RosterShape serializable, drop the draft_rounds clamp`). Код ниже — исходная редакция; итоговый контракт отличается шестью пунктами, см. D13-D15 в design doc:
> 1. Поле хранения — `entries: tuple[tuple[str, int], ...]`; `slots` и `role_slots` — property, отдающие свежий `dict`. `to_dict()` удалён как дубликат `slots`, ручной `__hash__` удалён как ненужный.
> 2. `MIN_TEAM_SIZE = 2`, `draft_rounds = team_size - 1` без `max(1, …)`. `{"flex": 1}` теперь отвергается.
> 3. Все константы под `Final`; `DEFAULT_ROSTER_SLOTS` — `MappingProxyType`; добавлен `DEFAULT_ROSTER_SHAPE`.
> 4. Добавлен `__post_init__`, держащий инварианты и для публичного конструктора.
> 5. Тест сторожит производность `ROSTER_SLOT_CODES` от `REGISTRATION_ROLE_CODES`, а не только её значение.
> 6. Добавлены пробы сериализуемости: `json.dumps(slots)`, `asdict`, `deepcopy`, `hash`.
>
> **Задачи 2-16 опираются на итоговый контракт**: везде `shape.slots`, нигде `shape.to_dict()`.

**Step 1: Написать падающий тест**

```python
# backend/shared/tests/test_roster_shape.py
import pytest

from shared.domain.roster_shape import (
    DEFAULT_ROSTER_SLOTS,
    FLEX_SLOT_CODE,
    ROSTER_SLOT_CODES,
    RosterShapeError,
    parse_roster_slots,
)


def test_slot_codes_are_registration_roles_plus_flex() -> None:
    assert ROSTER_SLOT_CODES == ("tank", "dps", "support", "flex")
    assert FLEX_SLOT_CODE == "flex"
    assert DEFAULT_ROSTER_SLOTS == {"tank": 1, "dps": 2, "support": 2}


def test_parses_overwatch_five_v_five() -> None:
    shape = parse_roster_slots({"tank": 1, "dps": 2, "support": 2})

    assert shape.slots == {"tank": 1, "dps": 2, "support": 2}
    assert shape.team_size == 5
    assert shape.flex_slots == 0
    assert shape.role_slots == {"tank": 1, "dps": 2, "support": 2}
    assert shape.has_role_slots is True
    assert shape.draft_rounds == 4


def test_parses_role_less_roster() -> None:
    shape = parse_roster_slots({"flex": 6})

    assert shape.team_size == 6
    assert shape.flex_slots == 6
    assert shape.role_slots == {}
    assert shape.has_role_slots is False
    assert shape.draft_rounds == 5


def test_parses_hybrid_roster() -> None:
    shape = parse_roster_slots({"tank": 1, "flex": 5})

    assert shape.team_size == 6
    assert shape.flex_slots == 5
    assert shape.role_slots == {"tank": 1}
    assert shape.has_role_slots is True


def test_drops_zero_counts_so_has_role_slots_is_unambiguous() -> None:
    shape = parse_roster_slots({"tank": 0, "dps": 0, "support": 0, "flex": 6})

    assert shape.slots == {"flex": 6}
    assert shape.has_role_slots is False


def test_normalizes_key_order_to_canonical() -> None:
    shape = parse_roster_slots({"flex": 1, "support": 2, "tank": 1})

    assert list(shape.slots) == ["tank", "support", "flex"]


def test_single_slot_roster_still_drafts_one_round() -> None:
    # team_size 1 means the captain fills the only slot; rounds must stay >= 1.
    assert parse_roster_slots({"flex": 1}).draft_rounds == 1


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, "roster_slots_not_a_map"),
        ([("tank", 1)], "roster_slots_not_a_map"),
        ({"healer": 2}, "roster_slots_unknown_code"),
        ({"Tank": 1}, "roster_slots_unknown_code"),
        ({"tank": -1}, "roster_slots_invalid_count"),
        ({"tank": 1.5}, "roster_slots_invalid_count"),
        ({"tank": True}, "roster_slots_invalid_count"),
        ({}, "roster_slots_empty"),
        ({"tank": 0}, "roster_slots_empty"),
        ({"flex": 13}, "roster_slots_out_of_range"),
        ({"tank": 6, "dps": 7}, "roster_slots_out_of_range"),
    ],
)
def test_rejects_invalid_maps_with_machine_readable_codes(raw: object, code: str) -> None:
    with pytest.raises(RosterShapeError) as exc_info:
        parse_roster_slots(raw)

    assert exc_info.value.code == code


def test_shape_is_hashable_and_frozen() -> None:
    shape = parse_roster_slots({"flex": 6})

    with pytest.raises(Exception):
        shape.slots = {"tank": 1}  # type: ignore[misc]
    assert hash(shape) == hash(parse_roster_slots({"flex": 6}))
```

Заметь `{"tank": True}` в списке отказов: `bool` — подкласс `int` в Python, и без явной проверки `True` прошло бы как `1`.

**Step 2: Запустить тест, убедиться что падает**

Run: `cd backend && uv run pytest shared/tests/test_roster_shape.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.domain.roster_shape'`

**Step 3: Минимальная реализация**

```python
# backend/shared/domain/roster_shape.py
"""Per-team roster shape: how many slots of which kind one team has.

The single source of truth for team composition across draft, balancer and UI.
A slot code is either a registration role (``tank``/``dps``/``support``) or the
reserved ``flex`` code, meaning "any role fits this slot".

Deliberately pure: no I/O, no service imports. The tournament/workspace lookup
and its cache live in ``shared.services.roster_shape_access``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES

__all__ = (
    "DEFAULT_ROSTER_SLOTS",
    "FLEX_SLOT_CODE",
    "MAX_TEAM_SIZE",
    "MIN_TEAM_SIZE",
    "ROSTER_SLOT_CODES",
    "RosterShape",
    "RosterShapeError",
    "parse_roster_slots",
    "resolve_roster_shape",
)

FLEX_SLOT_CODE = "flex"
ROSTER_SLOT_CODES: tuple[str, ...] = (*REGISTRATION_ROLE_CODES, FLEX_SLOT_CODE)
DEFAULT_ROSTER_SLOTS: dict[str, int] = {"tank": 1, "dps": 2, "support": 2}
MIN_TEAM_SIZE = 1
MAX_TEAM_SIZE = 12


class RosterShapeError(ValueError):
    """An invalid roster slot map, carrying a machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RosterShape:
    """Normalized per-team slot counts: canonical key order, no zero entries."""

    slots: Mapping[str, int]

    @property
    def team_size(self) -> int:
        return sum(self.slots.values())

    @property
    def flex_slots(self) -> int:
        return self.slots.get(FLEX_SLOT_CODE, 0)

    @property
    def role_slots(self) -> Mapping[str, int]:
        return MappingProxyType(
            {code: count for code, count in self.slots.items() if code != FLEX_SLOT_CODE}
        )

    @property
    def has_role_slots(self) -> bool:
        """False only when every slot is ``flex`` — the role-less roster.

        This is the switch that hides role counters, role filters and role
        validation. Zero counts are dropped by ``parse_roster_slots``, so it can
        never be confused by ``{"tank": 0, "flex": 6}``.
        """
        return bool(self.role_slots)

    @property
    def draft_rounds(self) -> int:
        """Draft rounds for this shape: the captain already fills one slot."""
        return max(1, self.team_size - 1)

    def to_dict(self) -> dict[str, int]:
        return dict(self.slots)

    def __hash__(self) -> int:
        return hash(tuple(self.slots.items()))


def parse_roster_slots(raw: Any) -> RosterShape:
    """Validate and normalize a raw slot map into a ``RosterShape``."""
    if not isinstance(raw, Mapping):
        raise RosterShapeError(
            "roster_slots_not_a_map",
            f"Roster slots must be a mapping of slot code to count, got {type(raw).__name__}",
        )

    counts: dict[str, int] = {}
    for code, value in raw.items():
        if code not in ROSTER_SLOT_CODES:
            raise RosterShapeError(
                "roster_slots_unknown_code",
                f"Unknown roster slot code {code!r}; valid codes are {', '.join(ROSTER_SLOT_CODES)}",
            )
        # bool is an int subclass — True would silently pass as 1.
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RosterShapeError(
                "roster_slots_invalid_count",
                f"Roster slot {code!r} must be a non-negative integer, got {value!r}",
            )
        if value > 0:
            counts[code] = value

    if not counts:
        raise RosterShapeError(
            "roster_slots_empty",
            "A roster shape needs at least one slot with a positive count",
        )

    team_size = sum(counts.values())
    if not MIN_TEAM_SIZE <= team_size <= MAX_TEAM_SIZE:
        raise RosterShapeError(
            "roster_slots_out_of_range",
            f"Roster size {team_size} is outside {MIN_TEAM_SIZE}..{MAX_TEAM_SIZE}",
        )

    ordered = {code: counts[code] for code in ROSTER_SLOT_CODES if code in counts}
    return RosterShape(slots=MappingProxyType(ordered))
```

**Step 4: Запустить тест**

Run: `cd backend && uv run pytest shared/tests/test_roster_shape.py -v`
Expected: PASS, все кроме `resolve_roster_shape` (её тесты — Task 2)

**Step 5: Commit**

```bash
git add backend/shared/domain/roster_shape.py backend/shared/tests/test_roster_shape.py
git commit -m "feat(shared): add RosterShape canon with flex slot code"
```

---

## Task 2: Цепочка fallback

**Files:**
- Modify: `backend/shared/domain/roster_shape.py`
- Modify: `backend/shared/domain/__init__.py`
- Test: `backend/shared/tests/test_roster_shape.py`

**Step 1: Написать падающий тест** (добавить в конец файла)

```python
from shared.domain.roster_shape import resolve_roster_shape


def test_tournament_override_wins() -> None:
    shape = resolve_roster_shape({"flex": 6}, {"tank": 1, "dps": 2, "support": 2})

    assert shape.slots == {"flex": 6}


def test_falls_back_to_workspace_default() -> None:
    shape = resolve_roster_shape(None, {"tank": 1, "flex": 5})

    assert shape.slots == {"tank": 1, "flex": 5}


def test_falls_back_to_builtin_default_when_nothing_is_set() -> None:
    shape = resolve_roster_shape(None, None)

    assert shape.slots == DEFAULT_ROSTER_SLOTS


def test_empty_map_at_a_level_means_no_value_not_an_error() -> None:
    # A cleared override must inherit, not blow up the tournament read.
    assert resolve_roster_shape({}, {"flex": 6}).slots == {"flex": 6}
    assert resolve_roster_shape({}, {}).slots == DEFAULT_ROSTER_SLOTS


def test_invalid_value_at_a_level_still_raises() -> None:
    # Corrupt stored config must surface, not silently degrade to the default.
    with pytest.raises(RosterShapeError):
        resolve_roster_shape({"healer": 6}, None)
```

**Step 2: Запустить, убедиться что падает**

Run: `cd backend && uv run pytest shared/tests/test_roster_shape.py -v -k resolve`
Expected: FAIL — `ImportError: cannot import name 'resolve_roster_shape'`

**Step 3: Реализация** (добавить в `roster_shape.py`)

```python
def resolve_roster_shape(tournament_slots: Any, workspace_slots: Any) -> RosterShape:
    """Tournament override -> workspace default -> built-in Overwatch 5v5.

    ``None`` and an empty map both mean "no value at this level, keep looking"
    (a cleared override inherits). Anything else is validated: corrupt stored
    config raises instead of silently degrading to the default.
    """
    for candidate in (tournament_slots, workspace_slots):
        if candidate is None:
            continue
        if isinstance(candidate, Mapping) and not candidate:
            continue
        return parse_roster_slots(candidate)
    return DEFAULT_ROSTER_SHAPE
```

Реэкспорт в `backend/shared/domain/__init__.py` — добавить к существующему блоку `from .player_sub_roles import (...)`:

```python
from .roster_shape import (
    DEFAULT_ROSTER_SLOTS,
    FLEX_SLOT_CODE,
    ROSTER_SLOT_CODES,
    RosterShape,
    RosterShapeError,
    parse_roster_slots,
    resolve_roster_shape,
)
```
и соответствующие имена в `__all__`.

**Step 4: Запустить тест**

Run: `cd backend && uv run pytest shared/tests/test_roster_shape.py -v`
Expected: PASS, все

**Step 5: Commit**

```bash
git add backend/shared/domain/roster_shape.py backend/shared/domain/__init__.py backend/shared/tests/test_roster_shape.py
git commit -m "feat(shared): resolve roster shape through tournament/workspace fallback"
```

---

# Фаза 2. Хранение и резолвер

## Task 3: Модели и миграция (только добавление колонок)

> **Изменено относительно первой редакции плана.** `DROP COLUMN balancer.draft_session.team_size` здесь НЕ делается. Балансер перестаёт читать эту колонку только в Task 9, и если снять её сейчас, то между Task 3 и Task 9 весь `balancer-service/tests` красный: тесты конструируют `DraftSession(..., team_size=3)` напрямую (`test_draft_role_edit.py:42`, `test_draft_integration.py:160` и далее). Drop переехал в Task 9 отдельной ревизией — туда, где код перестаёт писать колонку. Каждый промежуточный коммит остаётся зелёным.

**Files:**
- Modify: `backend/shared/models/tournament/tournament.py` (после `division_grid_version_id`, ~строка 80)
- Modify: `backend/shared/models/tenancy/workspace.py` (после `default_division_grid_version_id`, ~строка 68)
- Create: `backend/migrations/versions/<rev>_add_roster_slots.py`
- Test: `backend/shared/tests/test_roster_slots_migration_matches_models.py`

Не трогать: `backend/shared/models/balancer/draft.py` — `team_size` остаётся до Task 9.

**Step 1: Написать падающий тест**

По образцу существующего `backend/shared/tests/test_subscription_migration_matches_models.py` — прочитать его первым и повторить структуру (он парсит `op.add_column` из ревизии и сверяет с моделью). Тест должен утверждать:

- `tournament.roster_slots_json` — JSONB, nullable, есть и в модели, и в ревизии;
- `workspace.default_roster_slots_json` — JSONB, nullable, есть в обоих;
- ревизия НЕ содержит `op.drop_column` — это гарантия обратимости и того, что колонка `team_size` не снята раньше времени.

**Step 2: Запустить, убедиться что падает**

Run: `cd backend && uv run pytest shared/tests/test_roster_slots_migration_matches_models.py -v`
Expected: FAIL — колонок нет

**Step 3: Модели**

`tournament.py`:
```python
    roster_slots_json: Mapped[dict[str, int] | None] = mapped_column(
        JSONB, nullable=True
    )
```

`workspace.py`:
```python
    default_roster_slots_json: Mapped[dict[str, int] | None] = mapped_column(
        JSONB, nullable=True
    )
```

Проверить, как `JSONB` уже импортируется в этих файлах — в репозитории есть и `sqlalchemy.JSON`, и `postgresql.JSONB`; повторить локальную конвенцию файла, а не вводить свою.

**Step 4: Ревизия**

Взять `down_revision` из текущего head: `cd backend && uv run alembic heads`.

```python
def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("roster_slots_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "workspace",
        sa.Column("default_roster_slots_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace", "default_roster_slots_json")
    op.drop_column("tournament", "roster_slots_json", schema="tournament")
```

Обе колонки `NULL` для всех существующих строк, что через fallback даёт в точности сегодняшнее `{"tank":1,"dps":2,"support":2}`. Бэкфилл не нужен.

**Step 5: Запустить тест и миграцию**

Run: `cd backend && uv run pytest shared/tests/test_roster_slots_migration_matches_models.py -v`
Expected: PASS
Run: `make migrate`
Expected: `Running upgrade ... -> <rev>, add_roster_slots`

**Step 6: Commit**

```bash
git add backend/shared/models backend/migrations/versions backend/shared/tests/test_roster_slots_migration_matches_models.py
git commit -m "feat(db): add roster_slots columns to tournament and workspace"
```

---

## Task 4: Резолвер с кешем

**Files:**
- Create: `backend/shared/services/roster_shape_access.py`
- Test: `backend/shared/tests/test_roster_shape_access.py`

**Step 1: Прочитать образец**

Прочитать `backend/shared/services/division_grid_access.py` целиком и найти его Redis-слой (`division_grid_cache`). Новый модуль повторяет структуру: публичные `get_*` функции, кеш с теми же TTL-настройками, явная инвалидация.

**Step 2: Написать падающий тест**

```python
# backend/shared/tests/test_roster_shape_access.py
```
Тесты (кеш замокан, БД через существующий тестовый фикстур-паттерн этого пакета):
- `get_effective_roster_shape` с override на турнире → override;
- без override, с дефолтом workspace → дефолт workspace;
- без обоих → `DEFAULT_ROSTER_SLOTS`;
- `tournament_id=None` и `workspace_id=None` → `DEFAULT_ROSTER_SLOTS` без запросов к БД;
- второй вызов не делает второго SELECT (кеш);
- `invalidate_roster_shape_cache` заставляет перечитать.

**Step 3: Запустить, убедиться что падает**

Run: `cd backend && uv run pytest shared/tests/test_roster_shape_access.py -v`
Expected: FAIL — модуля нет

**Step 4: Реализация**

```python
async def get_tournament_roster_slots(session, tournament_id: int | None) -> dict | None
async def get_workspace_roster_slots(session, workspace_id: int | None) -> dict | None
async def get_effective_roster_shape(
    session, *, tournament_id: int | None, workspace_id: int | None
) -> RosterShape
async def invalidate_roster_shape_cache(*, tournament_id=None, workspace_id=None) -> None
```

`get_effective_roster_shape` читает оба уровня и отдаёт их в `resolve_roster_shape`. Кеш-ключи `roster_slots:tournament:{id}`, `roster_slots:workspace:{id}`; кешируется **сырая карта**, а не `RosterShape` — так инвалидация остаётся по-уровневой, а сборка формы дешёвая.

**Step 5: Запустить тест**

Run: `cd backend && uv run pytest shared/tests/test_roster_shape_access.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/shared/services/roster_shape_access.py backend/shared/tests/test_roster_shape_access.py
git commit -m "feat(shared): add cached roster shape resolver"
```

---

# Фаза 3. API турнира

## Task 5: Чтение формы в `TournamentRead`

**Files:**
- Create: `backend/tournament-service/src/schemas/roster_shape.py`
- Modify: `backend/tournament-service/src/schemas/__init__.py` — реэкспорт
- Modify: `backend/tournament-service/src/schemas/tournament.py:42-67` — два поля в `TournamentRead`
- Modify: `backend/tournament-service/src/schemas/workspace.py:21-23` — `default_roster_slots_json` в `WorkspaceRead`
- Modify: `backend/tournament-service/src/services/tournament/flows.py:48-147` — заполнение в `to_pydantic`
- Modify: `backend/tournament-service/src/services/admin/registry.py:101-102` — `_ser_tournament` запрашивает entity
- Test: `backend/tournament-service/tests/test_roster_shape_api.py`

**Step 1: Написать падающий тест**

- `to_pydantic(..., entities=["roster_shape"])` для турнира без override и без дефолта воркспейса → `roster_shape.source == "default"`, `slots == {"tank":1,"dps":2,"support":2}`;
- только дефолт воркспейса → `source == "workspace"`;
- override на турнире → `source == "tournament"`, и он побеждает дефолт;
- `{"flex": 6}` на турнире → `has_role_slots is False`, `team_size == 6`, `draft_rounds == 5`;
- **`entities` без `"roster_shape"` → поле `None` и НИ ОДНОГО обращения к резолверу.** Это главный тест opt-in: без него следующий человек сделает поле обязательным и уронит вложенные чтения;
- `roster_slots_json` присутствует всегда, независимо от `entities`, потому что это обычная колонка;
- повреждённое значение в колонке при запрошенном `roster_shape` → `RosterShapeError` наружу, а не тихий дефолт.

**Step 2: Запустить** → FAIL

Run: `cd backend && uv run pytest tournament-service/tests/test_roster_shape_api.py -v`

**Step 3: Схема**

```python
# backend/tournament-service/src/schemas/roster_shape.py
class RosterShapeRead(BaseModel):
    """A resolved roster shape. The frontend never recomputes the fallback chain."""

    slots: dict[str, int]
    team_size: int
    flex_slots: int
    has_role_slots: bool
    draft_rounds: int
    source: Literal["tournament", "workspace", "default"]

    @classmethod
    def from_shape(cls, shape: RosterShape, *, source: str) -> RosterShapeRead: ...
```

`TournamentRead` получает:
```python
    roster_slots_json: dict[str, int] | None = None
    # Opt-in entity (D16): TournamentRead is nested in six other schemas that are
    # built from ORM rows without a session, so this cannot be required.
    roster_shape: RosterShapeRead | None = None
```
`WorkspaceRead` получает `default_roster_slots_json: dict[str, int] | None`. Разрешённая форма воркспейса отдельным полем НЕ нужна — у воркспейса нет уровня выше встроенного дефолта.

**Step 4: Заполнение**

`to_pydantic` в `flows.py` уже устроен как opt-in по `entities` — повтори ровно то, что рядом делает `division_grid_version` (строки 108-115):

```python
    roster_shape = None
    if _entity_requested(entities, "roster_shape"):
        # Both levels explicitly, so `source` is known rather than reverse-engineered
        # from the result. Both getters are cache-backed, so this is not an extra query.
        tournament_slots = await get_tournament_roster_slots(session, tournament.id)
        workspace_slots = await get_workspace_roster_slots(session, tournament.workspace_id)
        shape = resolve_roster_shape(tournament_slots, workspace_slots)
        source = (
            "tournament" if tournament_slots
            else "workspace" if workspace_slots
            else "default"
        )
        roster_shape = RosterShapeRead.from_shape(shape, source=source)
```

НЕ вычисляй `source` сравнением разрешённой формы с колонками: override, совпадающий по значению с дефолтом воркспейса, всё равно остаётся override, и админка обязана показать это честно, а не «наследуется».

`_ser_tournament` в `registry.py:101-102` меняет `["stages"]` на `["stages", "roster_shape"]` — иначе админское чтение вернёт `None` и Settings нечего будет показать.

**Step 5: Запустить**

Run: `cd backend && uv run pytest tournament-service/tests/test_roster_shape_api.py -v` → PASS
Run: `cd backend && uv run pytest tournament-service/tests -q` → 0 failed

**Step 6: Ре-экспорт манифеста гейтвея**

Схемы изменились, а CI сверяет закоммиченный манифест:
```bash
cd backend && bash scripts/export_openapi_schemas.sh
```

**Step 7: Commit**

```bash
git add backend/tournament-service backend/shared gateway/internal/openapi/schemas.json
git commit -m "feat(tournament): expose resolved roster shape as an opt-in entity"
```

---

## Task 6: Запись формы и блокировка драфтом

**Files:**
- Modify: `backend/tournament-service/src/schemas/admin/tournament.py` (`TournamentCreate`, `TournamentUpdate`)
- Modify: `backend/tournament-service/src/schemas/workspace.py` (`WorkspaceCreate`, `WorkspaceUpdate`)
- Modify: сервис обновления турнира (найти через `codegraph_explore "tournament admin update service division_grid_version_id"`)
- Test: `backend/tournament-service/tests/test_roster_shape_api.py`

**Step 1: Написать падающий тест**

- PATCH `{"roster_slots_json": {"flex": 6}}` → 200, `roster_shape.source == "tournament"`, `has_role_slots is False`;
- PATCH `{"roster_slots_json": {"healer": 2}}` → 422, код `roster_slots_unknown_code`;
- PATCH `{"roster_slots_json": null}` → 200, наследование;
- PATCH при существующей `draft_session` со `status ∈ _ACTIVE_STATUSES` → 422, код `roster_locked_by_draft`;
- PATCH при завершённой сессии → 200.

**Step 2: Запустить** → FAIL

**Step 3: Реализация**

Валидатор на схемах:
```python
    @field_validator("roster_slots_json")
    @classmethod
    def _validate_roster_slots(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        try:
            return parse_roster_slots(value).slots
        except RosterShapeError as exc:
            raise ValueError(exc.code) from exc
```

Блокировка — в сервисе обновления, до записи. Read-only SELECT по `balancer.draft_session` (модели видны через `shared.models`, та же БД — так же, как app-service читает домен турниров в `dashboard/readiness.py`):

```python
    if payload.roster_slots_json is not ... and _differs_from_stored(...):
        active = await session.scalar(
            sa.select(models.DraftSession.id).where(
                models.DraftSession.tournament_id == tournament_id,
                models.DraftSession.status.in_(DRAFT_ACTIVE_STATUSES),
            )
        )
        if active is not None:
            raise HTTPException(422, [ApiExc(code="roster_locked_by_draft", msg=...)])
```

`DRAFT_ACTIVE_STATUSES` — поднять из приватного `lifecycle._ACTIVE_STATUSES` в публичную константу в `shared/core/enums.py` (или рядом), чтобы оба сервиса читали один список, а не два.

После успешной записи — `await invalidate_roster_shape_cache(tournament_id=...)`.

Тот же признак на чтении: `TournamentRead.roster_locked_by_draft: bool`.

**Step 4: Запустить тест** → PASS

**Step 5: Commit**

```bash
git commit -am "feat(tournament): accept roster slots, lock while a draft is unfinished"
```

---

# Фаза 4. Драфт

## Task 7: Слоты вместо ролей в feasibility

**Files:**
- Modify: `backend/balancer-service/src/services/draft/feasibility.py:74-158`
- Test: `backend/balancer-service/tests/test_draft_feasibility.py`

**Step 1: Написать падающий тест**

```python
def test_flex_slot_fits_a_player_who_plays_no_role_slot_role() -> None:
    # {"tank": 1, "flex": 1}: a support-only player cannot take the tank slot but
    # must be placeable in the flex slot.
    ...


def test_role_less_shape_matches_any_pool() -> None:
    # {"flex": 6} is feasible for any 6 available players regardless of roles.
    ...


def test_role_slots_still_constrain_in_hybrid_shape() -> None:
    # {"tank": 1, "flex": 1} with two support-only players is infeasible: the
    # tank slot has no eligible player.
    ...
```

**Step 2: Запустить** → FAIL

**Step 3: Реализация**

- Удалить `role_targets_for_team_size` (строки 82-97) и убрать из `__all__` (строка 447).
- `DraftFeasibilityState.role_targets: dict[DraftRole, int]` → `slot_targets: dict[str, int]`.
- `DraftAssignment.role: DraftRole` → `slot_code: str`.
- `build_feasibility_state(*, team_size: int, ...)` → `build_feasibility_state(*, shape: RosterShape, ...)`, `slot_targets=shape.to_dict()`.
- В построении слотов для `maximum_bipartite_matching`: слот с кодом `FLEX_SLOT_CODE` пригоден любому игроку из `players`; слот с ролевым кодом — только игроку, у которого этот код в `playable_roles`.
- `state_from_snapshot` (строка ~200) берёт форму через `get_effective_roster_shape` вместо `draft_session.team_size`.
- `DraftSlotRead.role` → `slot_code: str`, `DraftRoleDeficitRead` → `DraftSlotDeficitRead.slot_code: str` в `schemas/draft.py:320-336`.

**Step 4: Запустить тест**

Run: `cd backend && uv run pytest balancer-service/tests/test_draft_feasibility.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git commit -am "feat(draft): match roster slots instead of hardcoded role targets"
```

---

## Task 8: Валидация пика по слотам

**Files:**
- Modify: `backend/balancer-service/src/services/draft/selection.py:177-256, 355-370, 405-420, 485-495`
- Modify: `backend/balancer-service/src/rpc/draft.py:413-414`
- Create: `backend/balancer-service/tests/test_draft_selection_slots.py`

**Step 1: Написать падающий тест**

```python
def test_pick_overflowing_its_role_takes_a_free_flex_slot() -> None:
    # {"tank": 1, "flex": 5}: the second tank pick is legal and occupies flex.
    ...


def test_slot_filled_only_when_both_role_and_flex_are_exhausted() -> None:
    ...


def test_target_role_is_ignored_when_shape_has_no_role_slots() -> None:
    # {"flex": 6}: a target_role on the request must neither 422 nor be stored.
    ...
```

**Step 2: Запустить** → FAIL

**Step 3: Реализация**

- Удалить `role_targets` (177-178) и `_role_capacity` (254-256).
- `_team_role_counts` → `_team_slot_counts(players, picks, team_id, shape)`: ролевые слоты по `pick.target_role or player.primary_role`, flex-слоты как остаток `всего_взято − Σзанятых_ролевых`.
- Проверку `role_filled` (355-365, 485-493) заменить на:
```python
    if role_capacity == 0 and flex_capacity == 0:
        raise _err("slot_filled", f"No slot left for {chosen_role.value} on this team", 422)
```
- При `not shape.has_role_slots` — не писать `target_role` и не проверять его.
- `_role_capacity` в `rpc/draft.py:413-414` заменить на новый расчёт capacity по слотам.

**Step 4: Запустить оба файла**

Run: `cd backend && uv run pytest balancer-service/tests/test_draft_selection_slots.py balancer-service/tests/test_draft_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git commit -am "feat(draft): allow overflow picks into flex slots"
```

---

## Task 9: Раунды и создание сессии

**Files:**
- Modify: `backend/balancer-service/src/services/draft/lifecycle.py:93-99, 182-216`
- Modify: `backend/balancer-service/src/schemas/draft.py:65-96, 275-276`
- Modify: `backend/balancer-service/src/rpc/draft.py:474-475, 602-603`
- Modify: `backend/shared/models/balancer/draft.py:71` — удалить `team_size`
- Create: `backend/migrations/versions/<rev>_drop_draft_session_team_size.py`
- Test: `backend/balancer-service/tests/test_draft_schemas.py`

> **Колонка снимается здесь, а не в Task 3.** Это последняя точка, где код перестаёт читать и писать `team_size`; снять её раньше означало бы красный `balancer-service/tests` на протяжении шести задач, потому что тесты конструируют `DraftSession(..., team_size=3)` напрямую.

**Step 1: Написать падающий тест**

- `DraftSessionCreateRequest` больше не принимает `team_size` и `rounds` (лишние ключи отвергаются);
- `create_session` с `shape={"flex": 6}` даёт `rounds == 5`;
- `validate_draft_rounds(rounds=3, shape={"flex": 6})` → 422 `invalid_roster_shape`;
- `DraftSessionRead` отдаёт `roster_shape`, не `team_size`.

Удалить устаревшие тесты `test_draft_schemas.py:48-61` (`rounds must equal team_size - 1` в старой формулировке) — они закрепляли удалённый параметр.

**Step 2: Запустить** → FAIL

**Step 3: Реализация**

- `validate_roster_shape(rounds, team_size)` → `validate_draft_rounds(*, rounds: int, shape: RosterShape)`, правило `rounds == shape.draft_rounds`, код ошибки `invalid_roster_shape` сохраняется.
- `create_session`: убрать `team_size` и `rounds` из параметров, добавить `shape: RosterShape`, писать `rounds=shape.draft_rounds`.
- `DraftSessionCreateRequest`: удалить `team_size`, `rounds` и валидаторы `_team_size_range` (85-90) и `_rounds_match_roster_size` (92-96).
- `DraftSessionRead.team_size: int` → `roster_shape: RosterShapeRead`.
- `rpc/draft.py:602-603`: `validate_roster_shape(rounds=payload.rounds, team_size=draft.team_size)` → форма из резолвера.

**Step 4: Запустить весь suite балансера**

Run: `cd backend && uv run pytest balancer-service/tests -v`
Expected: PASS

**Step 4b: Ревизия — снять колонку**

Отдельная ревизия, `down_revision` = ревизия из Task 3 (или текущий head, если между ними легли чужие). `cd backend && uv run alembic heads`.

```python
def upgrade() -> None:
    op.drop_column("draft_session", "team_size", schema="balancer")


def downgrade() -> None:
    op.add_column(
        "draft_session",
        sa.Column("team_size", sa.Integer(), server_default="5", nullable=False),
        schema="balancer",
    )
    # Every pre-feature session had rounds == team_size - 1 by construction, so
    # the column is reconstructible without data loss.
    op.execute("UPDATE balancer.draft_session SET team_size = rounds + 1")
```

Затем удалить `team_size: Mapped[int] = mapped_column(...)` из `backend/shared/models/balancer/draft.py:71` и прогнать `make migrate`.

Порядок внутри задачи важен: сначала код перестаёт обращаться к колонке и тесты зелёные, только потом снимается колонка и модель. Иначе между двумя шагами сьют красный.

**Step 5: Commit**

```bash
git commit -am "feat(draft): derive rounds from the tournament roster shape"
```

---

# Фаза 5. Балансер

## Task 10: Синтез flex-рейтинга

**Files:**
- Modify: `backend/balancer-service/src/services/balancer/algorithm/player_loader.py:26-46`
- Modify: `backend/balancer-service/src/services/balancer/algorithm/input_roles.py:20-43`
- Create: `backend/balancer-service/tests/test_player_loader_flex.py`

Это самое содержательное место фичи. Без него прогон на `{flex: N}` уронит Rust на `context.rs:41`: `resolve_input_role_name("tank", {"flex": 6})` вернёт `None`, `ratings` останется пуст, `parse_player_node` вернёт `None`, и число игроков не сойдётся с числом слотов.

**Step 1: Написать падающий тест**

```python
def test_flex_mask_synthesizes_a_flex_rating_from_the_max_role_rank() -> None:
    player = parse_player_node(
        "u1",
        {
            "identity": {"name": "P"},
            "stats": {"classes": {
                "tank": {"isActive": True, "rank": 2600, "priority": 1},
                "support": {"isActive": True, "rank": 3100, "priority": 2},
            }},
        },
        mask={"flex": 6},
    )

    assert player is not None, "a flex mask must not drop players"
    assert player.ratings["flex"] == 3100
    assert player.preferences[0] == "flex"
    assert player.discomfort_map["flex"] == 0


def test_role_ratings_survive_alongside_the_flex_rating() -> None:
    # all_ratings feeds the admin panel; a flex mask must not blank it.
    ...


def test_hybrid_mask_keeps_both_role_and_flex_ratings() -> None:
    # mask {"tank": 1, "flex": 5}
    ...


def test_player_with_no_active_role_is_still_dropped() -> None:
    # No ranks at all -> nothing to synthesize from.
    ...
```

**Step 2: Запустить** → FAIL (`player is None`)

**Step 3: Реализация**

В `parse_player_node`, между циклом по `raw_classes` и проверкой `if not ratings` (строка 41):

```python
        # A flex slot accepts anybody, so the player needs a rating for it or the
        # role filter above drops them and the Rust core's slot/player count
        # check fails. Max across roles is the project's standing policy for
        # "ready to play anything" (see _all_roles_required / ratesByMaxRank).
        if FLEX_SLOT_CODE in mask and ratings:
            ratings[FLEX_SLOT_CODE] = max(ratings.values())
            # First in preferences => discomfort 0 and never counted off-role.
            preferences_prefix = [FLEX_SLOT_CODE]
        else:
            preferences_prefix = []
```
и `preferences = [*preferences_prefix, *(role for _, role in role_priorities)]`.

Порядок важен: `ratings` собирается по ролям **до** синтеза, поэтому `max` берётся по фактическим ролевым рангам, а не по уже добавленному flex.

В `input_roles.resolve_input_role_name`: код `flex` резолвится только из литерала `flex`; `STANDARD_ROLE_CODES` его не касается — «damage → flex» было бы ложью.

**Step 4: Запустить тест**

Run: `cd backend && uv run pytest balancer-service/tests/test_player_loader_flex.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git commit -am "feat(balancer): synthesize flex ratings so flex slots accept anyone"
```

---

## Task 11: Маска из резолвера, не из дефолта

**Files:**
- Modify: `backend/balancer-service/src/services/balancer/config/defaults.py:23-26`
- Modify: `backend/balancer-service/src/services/balancer/config/presets.py:23, 143-147`
- Modify: `backend/balancer-service/src/services/balancer/config/provider.py:53-54, 100-106`
- Modify: `backend/balancer-service/src/services/balancer/config/public_contract.py:11`
- Modify: `backend/balancer-service/src/services/admin/balancer.py`, `.../algorithm/runtime.py:70, 193`
- Test: `backend/balancer-service/tests/test_public_balancer_architecture.py`

**Step 1: Написать падающий тест**

- прогон для турнира с `{flex: 6}` получает `config.role_mask == {"flex": 6}`;
- `role_mask` не входит в `EDITABLE_CONFIG_FIELD_KEYS` и `PUBLIC_CONFIG_KEYS`;
- легаси-конфиг с `{"Tank":1,"Damage":2,"Support":2}` в `balance.config_json` всё ещё резолвится через `resolve_input_role_name`.

**Step 2: Запустить** → FAIL

**Step 3: Реализация**

- Дефолты `defaults.py:24` и `presets.py:23` → `DEFAULT_ROSTER_SLOTS` (lowercase).
- `role_mask` убрать из `EDITABLE_CONFIG_FIELD_KEYS` (`provider.py:54`), из `PUBLIC_CONFIG_KEYS` (`public_contract.py:11`) и из списка описаний полей (`provider.py:100-106`).
- `ConfigBuilder.with_role_mask` дополнительно прогоняет карту через `parse_roster_slots`.
- В точке запуска прогона (`admin/balancer.py`, `runtime.py`) заполнять `config.role_mask` из `get_effective_roster_shape(...).to_dict()`.

**Step 4: Запустить весь suite**

Run: `cd backend && uv run pytest balancer-service/tests -v`
Expected: PASS

**Step 5: Ре-экспорт манифеста и линт**

```bash
cd backend && bash scripts/export_openapi_schemas.sh && uv run bash scripts/lint.sh
```

**Step 6: Commit**

```bash
git add -A && git commit -m "feat(balancer): take the role mask from the tournament roster shape"
```

---

# Фаза 6. Фронтенд

## Task 12: Типы и модуль формы

**Files:**
- Modify: `frontend/src/types/tournament.types.ts:105+` (`Tournament`), `frontend/src/types/draft.types.ts:8, 20-21, 105-125`
- Create: `frontend/src/lib/roster-shape.ts`
- Create: `frontend/src/lib/roster-shape.test.ts`

**Step 1: Написать падающий тест**

```typescript
// frontend/src/lib/roster-shape.test.ts
describe("roster shape presets", () => {
  it("maps the 5v5 preset to its slot map and back", () => { ... });
  it("maps the role-less preset to {flex: 6} and back", () => { ... });
  it("falls back to custom for a hybrid map", () => { ... });
  it("computes the total and the derived draft rounds", () => { ... });
  it("orders slot codes canonically", () => { ... });
});
```

**Step 2: Запустить** → FAIL

Run: `cd frontend && bunx vitest run src/lib/roster-shape.test.ts`

**Step 3: Реализация**

`roster-shape.ts` содержит **только UI-сахар**, никаких правил домена:

```typescript
export type RosterSlotCode = "tank" | "dps" | "support" | "flex";
export const ROSTER_SLOT_CODES: RosterSlotCode[] = ["tank", "dps", "support", "flex"];

export interface RosterShape {
  slots: Partial<Record<RosterSlotCode, number>>;
  team_size: number;
  flex_slots: number;
  has_role_slots: boolean;
  draft_rounds: number;
  source: "tournament" | "workspace" | "default";
}

export const ROSTER_PRESETS = [
  { id: "ow5v5", slots: { tank: 1, dps: 2, support: 2 } },
  { id: "flex6", slots: { flex: 6 } }
] as const;

export function presetForSlots(slots): PresetId | "custom"
export function slotsTotal(slots): number          // Σ — арифметика ввода
export function draftRoundsForSlots(slots): number // Σ-1, только для превью
export function orderSlotCodes(slots): RosterSlotCode[]
```

`slotsTotal`/`draftRoundsForSlots` — не зеркало правила, а живой пересчёт поля ввода; авторитет остаётся за `roster_shape.team_size`/`draft_rounds` с API, и бэк всё равно перевалидирует.

Типы: `Tournament` получает `roster_slots_json`, `roster_shape`, `roster_locked_by_draft`. `DraftSession.team_size` → `roster_shape`. `DraftSlot.role` → `slot_code`, `DraftRoleDeficit` → `DraftSlotDeficit.slot_code`.

**Step 4: Запустить тест** → PASS

**Step 5: Commit**

```bash
git commit -am "feat(frontend): add roster shape types and presets"
```

---

## Task 13: Удалить зеркала правила

**Files:**
- Modify: `frontend/src/lib/draft-workspace-model.ts:151-167` — удалить `roleTargetsForTeamSize`
- Modify: `frontend/src/lib/draft-workspace-model.test.ts:122-135` — удалить тест
- Modify: `frontend/src/app/admin/tournaments/[id]/components/draft/setup-model.ts:76-78, 80-87, 89-108, 188-192` — удалить `roundsForTeamSize` и `roleTargets`, `derivePoolReadiness` принимает `shape`
- Modify: `frontend/src/components/draft/TeamRosters.tsx:23, 49-75, 168-175, 287-297`
- Modify: `frontend/src/app/admin/tournaments/[id]/components/draft/DraftConfigStep.tsx:36-79`, `DraftReviewStep.tsx:107-131`, `DraftReadyStep.tsx:74`, `DraftSetupWizard.tsx:73-88, 176-179, 208-211, 316-317, 489-490`, `AdminControlRoom.tsx:62`
- Modify: `frontend/src/components/draft/DraftPageHero.tsx:173`, `CaptainDraftWorkspace.tsx:164, 270`, `SpectatorDraftWorkspace.tsx:42`

**Step 1: Убедиться, что тесты падают после удаления**

Удалить функции, запустить: `cd frontend && bunx vitest run` — ожидаются падения в `draft-workspace-model.test.ts`, `setup-model.test.ts`, `draft-logic.test.ts` на отсутствующих символах и на `team_size` в фикстурах.

**Step 2: Переключить потребителей на `roster_shape`**

- `computeTeamRosterView`: принимает `shape: RosterShape` вместо `teamSize: number`; счётчики строятся по `orderSlotCodes(shape.slots)`; `openSlots = shape.team_size - roster.length`.
- Ряды счётчиков (`:168-175`, `:287-297`): при `!shape.has_role_slots` **не рендерятся** — не показывать `1/0 2/0 2/0`.
- Flex-слот рисуется подписью «Flex» без ролевой иконки; колонка «Роль» при `!has_role_slots` схлопывается, роль игрока (если известна) уезжает в tooltip имени.
- `DraftConfigStep`: убрать поле «Team size», «Rounds» сделать read-only из `shape.draft_rounds`, добавить строку «Форма ростера: …» со ссылкой на Settings.
- Фикстуры тестов: `team_size: 3` → `roster_shape: { slots: {...}, team_size: 3, ... }`.

**Step 3: Запустить весь фронт-suite**

Run: `cd frontend && bunx vitest run`
Expected: PASS

**Step 4: Commit**

```bash
git commit -am "refactor(frontend): consume server roster shape, delete role target mirrors"
```

---

## Task 14: Админский контрол

**Files:**
- Create: `frontend/src/components/admin/tournaments/RosterShapeEditor.tsx`
- Modify: `frontend/src/app/admin/tournaments/[id]/components/TournamentSettingsTab.tsx` (карточка «Rules & grid configuration», после `division_grid_version`, ~строка 329)
- Modify: настройки workspace (тот же компонент, без опции «Наследовать»)
- Modify: `frontend/src/i18n/messages/en.json`, `ru.json`

**Step 1: Собрать компонент**

1. Селект: `Наследовать от workspace` (только для турнира) · `Overwatch 5v5 · 1/2/2` · `6 флексов` · `Своя форма`.
2. В режиме «Своя форма» — `NumberInput` на каждый код из `ROSTER_SLOT_CODES` (Tank, DPS, Support, Flex), диапазон `0..12`, как у `win_points`.
3. Живой итог: `Итого: {n} слотов · раундов в драфте: {n-1}`.
4. Предпросмотр: мини-карточка ростера теми же слотами, что увидит капитан.
5. Warning при конфликте: `has_role_slots` и регистрационная форма не собирает роли → inline-ссылка на форму регистрации. Не блокирует сохранение.
6. При `roster_locked_by_draft` — блок `disabled` с текстом по образцу `draftAdmin.configLocked`.

Сохранение идёт существующей мутацией `TournamentSettingsTab` (`adminService.updateTournament`), новое поле добавляется в `payload` рядом с `division_grid_version_id` (строка 171).

**Step 2: Прогнать вживую**

```
make dev-up
```
Открыть `/admin/tournaments/<id>` → Settings. Проверить: переключение пресетов, «Своя форма» со степперами, итог, предпросмотр, сохранение, перезагрузка страницы отдаёт сохранённое, `Наследовать` возвращает `source: "workspace"`.

**Step 3: i18n**

Новые ключи `roster.*` в оба файла. Удалить `draftAdmin.teamSize` (`en.json:2997`) и `draftRedesign.hero.rosterSize`/`teamSize` (`:519`, `:3176`) — их потребители сняты в Task 13.

**Step 4: Линт**

Run: `cd frontend && bun run lint`
Expected: чисто

**Step 5: Commit**

```bash
git add -A && git commit -m "feat(admin): add roster shape editor to tournament settings"
```

---

# Фаза 7. Верификация

## Task 15: Смоук на форме без ролей

Это главная проверка фичи: до неё `{flex: N}` падал в трёх местах независимо.

**Step 1: Турнир с `{flex: 6}`**

`make dev-up`, создать турнир, в Settings выбрать «6 флексов», сохранить.

**Step 2: Прогон балансера**

Запустить баланс на этом турнире. Ожидается: прогон завершается, ни один игрок не отброшен, в результате шесть игроков на команду, off-role = 0, дискомфорт = 0. Это путь, который раньше падал на `context.rs:41`.

**Step 3: Драфт от создания до экспорта**

Создать сессию драфта: поле «Team size» отсутствует, «Rounds» = 5 и read-only. Засидить пул, стартовать, сделать пики без указания роли, экспортировать команды.

Ожидается: ролевые счётчики и фильтры ролей **не** отрисованы; `slot_filled` не выстреливает; экспорт пишет `Player.role` = фактическая роль из регистрации, где она есть.

**Step 4: Блокировка**

При живой сессии открыть Settings → блок формы ростера `disabled` с пояснением. Через API PATCH `roster_slots_json` → 422 `roster_locked_by_draft`.

**Step 5: Гибрид**

Переключить второй турнир на `{tank: 1, flex: 5}`. Проверить, что второй танк-пик легален и занимает flex-слот, а танк-слот при пустом пуле танков даёт `role_shortage`.

## Task 16: Полная проверка

**Step 1: Все suites бэкенда**

```bash
cd backend && for svc in shared app-service parser-service balancer-service tournament-service analytics-service identity-service discord-service; do
  echo "== $svc"; uv run pytest "$svc/tests" -q || break
done
```

**Step 2: Манифест гейтвея**

```bash
cd backend && bash scripts/export_openapi_schemas.sh --check
```
Expected: чисто. Если нет — `bash scripts/export_openapi_schemas.sh` и закоммитить `gateway/internal/openapi/schemas.json`.

**Step 3: Линт бэкенда и фронта**

```bash
cd backend && uv run bash scripts/lint.sh
cd ../frontend && bunx vitest run && bun run lint
```

**Step 4: Проверить, что зеркала действительно мертвы**

```bash
rg -n "roleTargetsForTeamSize|role_targets_for_team_size|roundsForTeamSize|team_size" backend frontend/src
```
Expected: ни одного попадания вне миграции (`downgrade`) и легаси-теста на `resolve_input_role_name`. Любое другое попадание — недоделанная задача.

**Step 5: Commit**

```bash
git add -A && git commit -m "chore: re-export gateway manifest for roster shape schemas"
```

---

## Порядок и параллелизм

Фазы 1→2→3 строго последовательны: канон, потом хранение, потом API.
Фазы 4 (драфт) и 5 (балансер) независимы друг от друга и могут идти параллельно после фазы 2 — они не пересекаются по файлам, но обе зависят от `RosterShape` и резолвера.
Фаза 6 требует готового API из фазы 3 (типы) и фазы 4 (`DraftSessionRead.roster_shape`).
Фаза 7 — только после всех.

## Чего не делать

- Не добавлять `FLEX` в `DraftRole` (D9): `frozenset(DraftRole)` означает «все роли» в трёх местах.
- Не воскрешать `shared/balancer/types.py RoleMask` (D8): мёртвый код, ноль потребителей.
- Не переносить формулы слотов на фронт (D12): правило живёт на бэке, на фронт едет готовый конфиг.
- Не хранить нули в карте слотов (D10).
- Не чинить `tournament-service/src/schemas/admin/balancer.py:10` (четвёртая копия словаря ролей) — вне объёма, отдельная задача.
- Не удалять мёртвый `shared/balancer/{types,protocol}.py` — вне объёма.

---

## Статус исполнения (2026-08-05)

Реализация закончена и закоммичена на `develop`. Задачи 7+8, 12+13 и 10+11 были объединены по ходу: в каждой паре первая удаляла символ, который использовала вторая, поэтому по отдельности пакет не собирался.

### Проверено в этой среде

| Проверка | Результат |
|---|---|
| `shared` | 523 passed, 9 skipped |
| `app-service` | 245 passed, 172 skipped |
| `parser-service` | 253 passed |
| `tournament-service` | 855 passed, 44 skipped |
| `analytics-service` | 155 passed |
| `identity-service` | 143 passed, 8 skipped |
| `discord-service` | 12 passed |
| `balancer-service` | 384 passed, 29 skipped, 1 failed — предсуществующее `test_api_key_limits_and_policy.py::test_workspace_policy_limits_api_key_to_own_workspace_and_jobs`; ни тест, ни `core/security/workspace_access.py` не входят в диапазон коммитов фичи (последняя правка — `88f9244b`, 2026-07-06) |
| `ruff check` по файлам фичи | чисто |
| `ruff format` по файлам фичи | приведено (коммит `42d3a692`); остальные 68 дрейфующих файлов репозитория — чужие, не тронуты |
| `bunx tsc --noEmit` | чисто |
| `bunx vitest run` | 59 файлов / 471 тест, 0 failed |
| `bun run lint` | 0 ошибок; 8 предупреждений в предсуществующих файлах |
| `bunx next build` | успешно, 65/65 страниц |
| Манифест гейтвея | был устаревшим, ре-экспортирован (`282feb64`): ушли `team_size`, `role_deficits`, `DraftSlot.role`; пришли `RosterShapeRead`, `slot_code`, `slot_deficits`, `default_roster_slots_json` |
| Зеркала правила | `grep` по `backend` и `frontend/src` не даёт ни одного живого вхождения `role_targets_for_team_size`, `selection.role_targets`, `_role_capacity`, `role_filled`, `roleTargetsForTeamSize`, `roundsForTeamSize`, `ROSTER_ROLES`, `role_deficits` |

Смоук без Docker: `load_players_from_dict` на `{"flex": 6}` и `{"tank": 1, "flex": 5}` сохраняет всех игроков с синтезированным max-рейтингом и `flex` первым в preferences; на ролевой маске поведение прежнее побайтово. Балансерный прогон прогнан сквозь заглушку нативного модуля, повторяющую валидацию `context.rs`: 12 игроков размещены, `off_role_count = 0`, дискомфорт 0.

### Осталось на живую среду (Task 15)

Docker Desktop в этой среде не поднимается (демон недоступен по `npipe:////./pipe/dockerDesktopLinuxEngine`), поэтому три пункта НЕ выполнены и обязательны перед релизом:

1. **`make migrate`** — ревизии `roster0001` (две nullable JSONB-колонки) и `roster0002` (`DROP COLUMN balancer.draft_session.team_size`) написаны и проверены AST-тестами против моделей, но НИ РАЗУ не применялись к реальной базе. Единственный head — `roster0002`.
2. **Пересборка Rust `tournament_balancer` под Linux.** В `native/tournament_balancer/src/context.rs` изменена одна строка: `dps_role_idx` теперь принимает и `"Damage"`, и `"dps"`. Без пересборки нативного модуля правка не вступит в силу, и `dps_impact_weight` продолжит молча игнорироваться при lowercase-маске. Расхождение стережёт `test_config_consistency.py::test_rust_recognizes_every_canonical_role_code`, но он проверяет ИСХОДНИК, а не собранный артефакт.
3. **Браузерная проверка:** вкладка Settings турнира → редактор формы ростера (пресеты, степперы, живой итог, предпросмотр, наследование, блокировка при живом драфте); затем полный прогон драфта на `{"flex": 6}` от создания сессии до экспорта команд и один прогон балансера на той же форме.
