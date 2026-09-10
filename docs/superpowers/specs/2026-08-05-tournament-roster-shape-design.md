# Форма ростера на уровне турнира — дизайн

**Дата:** 2026-08-05
**Статус:** согласован (Understanding Lock подтверждён)
**Метод:** superpowers:brainstorming

---

## 1. Проблема

Форма ростера сегодня не существует как понятие. Вместо неё — восемь независимых
реализаций одного правила «сколько игроков какой роли в команде», в трёх разных
словарях ролей, и ни одна не умеет выразить ростер без ролей.

| Где | Что хранит/считает | Словарь |
|---|---|---|
| `balancer.draft_session.team_size` (колонка, `shared/models/balancer/draft.py:71`) | одно число | — |
| `draft/feasibility.py:82` `role_targets_for_team_size` | хардкод: `>=5` → 1 tank / 2 dps / `max(2, n-3)` support | `tank/dps/support` |
| `draft/selection.py:177` `role_targets`, `:254` `_role_capacity` | обёртки над тем же хардкодом | `tank/dps/support` |
| `draft/lifecycle.py:93` `validate_roster_shape` | `rounds == team_size - 1` | — |
| `balancer/config/defaults.py:23` `role_mask` | `{"Tank":1,"Damage":2,"Support":2}` | **`Tank/Damage/Support`** |
| `balancer/config/presets.py:23` `DEFAULT["role_mask"]` | вторая копия того же дефолта | **`Tank/Damage/Support`** |
| `shared/balancer/types.py:48` `RoleMask` + `:62 overwatch_5v5()` | `{"tank":1,"dps":2,"support":2}` | `tank/dps/support` |
| `frontend/src/lib/draft-workspace-model.ts:157` `roleTargetsForTeamSize` | построчный порт хардкода | `tank/dps/support` |
| `frontend/.../draft/setup-model.ts:80` `roleTargets` | **второй** порт того же хардкода | `tank/dps/support` |
| `frontend/src/components/draft/TeamRosters.tsx:23` `ROSTER_ROLES` | литерал `["tank","dps","support"]` | `tank/dps/support` |

Плюс четвёртая копия словаря ролей: `tournament-service/src/schemas/admin/balancer.py:10`
объявляет собственный `BalancerRole = Literal["tank","dps","support"]`.

### Почему ростер без ролей невозможен сейчас

| Барьер | Место |
|---|---|
| Роль игрока в экспорте — обязательный `Literal` | `tournament-service/src/schemas/team.py:30` `BalancerTeamMember.role` |
| Rust отвергает пустую маску | `tournament_balancer/src/context.rs:14-16` `"role_mask cannot be empty"` |
| Игрок без рейтинга под роль из маски отбрасывается целиком | `balancer/algorithm/player_loader.py:33-42` |
| Драфт считает цели слотов из числа, а не из конфигурации | `draft/feasibility.py:82` |
| Фронт рисует ровно три ролевых счётчика | `TeamRosters.tsx:169-175`, `:288-296` |

### Прецеденты, которые задают решение

| Прецедент | Что даёт |
|---|---|
| `division_grid`: `workspace.default_division_grid_version_id` + override `tournament.division_grid_version_id` + `shared/services/division_grid_access.py` `get_effective_division_grid_version_id` + Redis-кеш | Готовая, работающая, закешированная трёхуровневая цепочка конфигурации уровня турнира |
| Реестр зеркал, строка 239: **server-driven конфиг** — `REPORT_BUILT_IN_FIELDS`/`DEFAULT_BUILT_IN_FIELDS` живут только на бэке и приходят на фронт готовым конфигом (`tournament-service/src/schemas/encounter_report_form.py:32,64`) | Образец для класса D: зеркало не синхронизируется, а **удаляется** |
| `shared/domain/player_sub_roles.py:22` `REGISTRATION_ROLE_CODES` | Живой канон словаря ролей; импортируется из tournament-, parser-, balancer-service и shared |
| `docs/architecture/p3-strategic-refactors.md:171` | `shared/domain/` объявлен местом бизнес-логики |

---

## 2. Что строим

Форма ростера — карта `slot_code → count` уровня турнира, где `flex` —
зарезервированный код «слот под любую роль».

```
{"tank": 1, "dps": 2, "support": 2}   OW 5v5
{"flex": 6}                            шесть флексов, роли не учитываются
{"tank": 1, "flex": 5}                 один танк, остальные любые
```

`team_size` = сумма значений. `has_role_slots` = в карте есть хоть один не-`flex`
код; это и есть выключатель ролевого UI и ролевых валидаций.

### Не входит в объём

- Именованные шаблоны-сущности и история версий формы.
- Требования на отдельный слот (роль + сабролль + диапазон ранга).
- Автоправка регистрационной формы под форму ростера.
- Изменение семантики `DraftPlayer.is_flex`.
- Удаление мёртвого `shared/balancer/{types,protocol}.py` — отдельная задача.

### Допущения

| Допущение | Обоснование |
|---|---|
| `flex` **не** добавляется в `DraftRole` | 42 потребителя `DraftRole`; `frozenset(DraftRole)` используется как «все роли» в `draft/feasibility.py:133`, `draft/selection.py:289`, `rpc/draft.py:420`. Добавление члена поменяло бы смысл всех трёх |
| Слот-`flex` и игрок-`is_flex` — ортогональны | `is_flex` = «играет что угодно, дискомфорт 0» (`entities.py:46-47`). Слот-`flex` = «сюда годится любой». Композируются без правок |
| Канон — lowercase `tank/dps/support/flex` | Совпадает с `REGISTRATION_ROLE_CODES`. Мост `input_roles.resolve_input_role_name`/`STANDARD_ROLE_CODES` остаётся только для легаси-конфигов балансера с `Tank/Damage/Support` |
| Архивные балансы не ломаются | Фактический состав команд лежит в `balance.result_json`; историческая форма восстанавливается из результата, а не из `config_json` |
| Резолвер не на горячем пути | Вызывается на setup-операциях драфта/баланса и на чтении турнира. Redis-кеш как у division_grid |
| Границы | `1 ≤ Σslots ≤ 12`; счётчики `≥ 0`; неизвестный код слота отвергается |
| Права | Правка формы — то же право, что `tournament.update` |

---

## 3. Модель данных

### 3.1 Канон: `backend/shared/domain/roster_shape.py`

Новый модуль рядом с `player_sub_roles.py`. Чистые функции, ноль I/O, ноль
импортов из сервисов.

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES

FLEX_SLOT_CODE: Final = "flex"
ROSTER_SLOT_CODES: Final[tuple[str, ...]] = (*REGISTRATION_ROLE_CODES, FLEX_SLOT_CODE)
DEFAULT_ROSTER_SLOTS: Final[Mapping[str, int]] = MappingProxyType(
    {"tank": 1, "dps": 2, "support": 2}
)
# A team is a captain plus at least one drafted player: a one-slot roster has
# nothing to draft and nothing to balance.
MIN_TEAM_SIZE: Final = 2
# Upper bound inherited from the pre-existing draft validator
# (balancer-service DraftSessionCreateRequest._team_size_range allowed 1..12).
MAX_TEAM_SIZE: Final = 12


class RosterShapeError(ValueError):
    """Invalid roster slot map. Carries a machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RosterShape:
    """Per-team slot counts, normalized: canonical order, no zero entries.

    Built through ``parse_roster_slots``. The stored field is a tuple of pairs,
    not a mapping, so the shape stays hashable, JSON-serializable, deep-copyable
    and picklable -- see D13.
    """

    entries: tuple[tuple[str, int], ...]

    @property
    def slots(self) -> dict[str, int]: ...           # fresh dict every access
    @property
    def team_size(self) -> int: ...
    @property
    def flex_slots(self) -> int: ...
    @property
    def role_slots(self) -> dict[str, int]: ...      # slots without ``flex``
    @property
    def has_role_slots(self) -> bool: ...            # bool(role_slots)
    @property
    def draft_rounds(self) -> int: ...               # team_size - 1

    def __post_init__(self) -> None: ...             # guards the invariants


DEFAULT_ROSTER_SHAPE: Final[RosterShape] = parse_roster_slots(DEFAULT_ROSTER_SLOTS)


def parse_roster_slots(raw: Any) -> RosterShape: ...
def resolve_roster_shape(
    tournament_slots: Any, workspace_slots: Any
) -> RosterShape: ...
```

`parse_roster_slots` — единственная точка валидации:

| Вход | Результат |
|---|---|
| не `Mapping` | `RosterShapeError("roster_slots_not_a_map", …)` |
| ключ не из `ROSTER_SLOT_CODES` | `RosterShapeError("roster_slots_unknown_code", …)` — с перечислением валидных |
| значение не `int` или `< 0` | `RosterShapeError("roster_slots_invalid_count", …)` |
| нули в карте | выбрасываются: `{"tank":1,"dps":0}` → `{"tank":1}` |
| карта пуста после нормализации | `RosterShapeError("roster_slots_empty", …)` |
| `Σ` вне `2..12` | `RosterShapeError("roster_slots_out_of_range", …)` |

Ноль не хранится — это убирает вопрос «а `{"tank":0,"flex":6}` это ростер с
ролями или без». `has_role_slots` становится однозначным.

`RosterShape.__post_init__` держит те же инварианты, что и `parse_roster_slots`:
конструктор публичен, и без проверки `RosterShape(entries=(("healer", -3),))`
создавался бы молча, давая `team_size == -3`. Две точки входа с разными
гарантиями в модуле-каноне — источник тихих багов.

`resolve_roster_shape` — чистая трёхуровневая цепочка: `tournament_slots` →
`workspace_slots` → `DEFAULT_ROSTER_SHAPE` (готовый объект, без повторного
парсинга). `None` и пустая карта на каждом уровне означают «нет значения, идём
дальше»; невалидное значение поднимает ошибку, а не проглатывается.

### 3.2 Резолвер: `backend/shared/services/roster_shape_access.py`

Зеркало `division_grid_access.py` по структуре и по кешированию:

```python
async def get_tournament_roster_slots(session, tournament_id) -> dict | None
async def get_workspace_roster_slots(session, workspace_id) -> dict | None
async def get_effective_roster_shape(
    session, *, tournament_id: int | None, workspace_id: int | None
) -> RosterShape
async def invalidate_roster_shape_cache(*, tournament_id=None, workspace_id=None) -> None
```

Кеш — тот же Redis-слой и тот же TTL, что у `division_grid_cache`; ключи
`roster_slots:tournament:{id}` и `roster_slots:workspace:{id}`. Инвалидация — на
записи в `tournament.roster_slots_json` / `workspace.default_roster_slots_json`.

### 3.3 Миграция

**Две ревизии, а не одна.** Добавление колонок и снятие `team_size` разнесены,
потому что балансер перестаёт читать `team_size` только в Task 9: снять колонку
раньше означало бы красный `balancer-service/tests` на протяжении шести задач —
его тесты конструируют `DraftSession(..., team_size=3)` напрямую.

Ревизия 1 (Task 3) — только добавление, полностью обратимая:

```python
op.add_column("tournament", sa.Column("roster_slots_json", JSONB, nullable=True),
              schema="tournament")
op.add_column("workspace", sa.Column("default_roster_slots_json", JSONB, nullable=True))
```

Ревизия 2 (Task 9), после того как код перестал обращаться к колонке:

```python
op.drop_column("draft_session", "team_size", schema="balancer")
```

Обе новые колонки `NULL` для всех существующих строк → через fallback это в
точности сегодняшнее `{"tank":1,"dps":2,"support":2}`, что совпадает с
`role_targets_for_team_size(5)`. Бэкфилл не нужен: ни одна существующая сессия
не имела формы, отличной от производной от `team_size`, а `team_size` у всех
живых сессий = `rounds + 1`, что и даёт `draft_rounds`. Downgrade второй ревизии
восстанавливает колонку тем же выражением `rounds + 1` — без потери данных.

Колонка снимается, а не остаётся «на всякий случай», потому что после перехода
драфта на резолвер она становится источником рассинхрона: два места, где
написан размер команды.

---

## 4. Контракты API

### 4.1 Чтение

`TournamentRead` (`tournament-service/src/schemas/tournament.py`) отдаёт и сырую
колонку, и **разрешённую** форму — фронт не должен воспроизводить цепочку
fallback:

```python
class RosterShapeRead(BaseModel):
    slots: dict[str, int]           # нормализованная карта
    team_size: int
    flex_slots: int
    has_role_slots: bool
    draft_rounds: int
    source: Literal["tournament", "workspace", "default"]


class TournamentRead(BaseRead):
    ...
    roster_slots_json: dict[str, int] | None   # сырой override, из колонки
    roster_shape: RosterShapeRead | None = None  # opt-in entity, см. ниже
```

`source` нужен админке, чтобы честно показать «Наследуется от workspace» вместо
молчаливого отображения дефолта как собственной настройки.

**`roster_shape` — opt-in entity, а не обязательное поле.** Это следует из
устройства `tournament-service`, а не из вкуса: `TournamentRead` вложен в
`EncounterRead.tournament`, `TeamRead.tournament`, `PlayerRead.tournament`,
`StandingRead.tournament`, `AchievementRead.tournaments`, `OwalStandings.days` и
ещё несколько схем, и все они собираются из ORM-строк без сессии под рукой.
Обязательное поле заставило бы резолвить форму в каждом из них.

Механизм в репозитории уже есть и применяется к точно такому же случаю:
`tournament/flows.py:to_pydantic` принимает список `entities` и заполняет
`division_grid_version` только когда `_entity_requested(entities, "division_grid_version")`.
`roster_shape` заполняется там же и так же — при `"roster_shape" in entities`, —
вызовом `get_effective_roster_shape`. Потребители, которым форма нужна
(админский сериализатор `_ser_tournament`, вкладка Settings), запрашивают её
явно; вложенные и списочные чтения за неё не платят. `get_read` кеширован ключом
`tournaments/{id}:{entities}`, поэтому opt-in не отравляет кеш.

`roster_slots_json` — обычная колонка, всегда присутствует, `from_attributes`
заполняет её сам.

`WorkspaceRead` получает `default_roster_slots_json: dict[str,int] | None`;
разрешённая форма воркспейса отдельным полем не нужна — у воркспейса нет уровня
выше, кроме встроенного дефолта, и админка воркспейса показывает сырую карту
плюс тот же встроенный дефолт как подсказку.

### 4.2 Запись

`TournamentCreate`/`TournamentUpdate` (`schemas/admin/tournament.py`) и
`WorkspaceCreate`/`WorkspaceUpdate` получают `roster_slots_json` /
`default_roster_slots_json` как `dict[str,int] | None`, валидируемые через
`parse_roster_slots` в `field_validator`. `None` = «наследовать».

### 4.3 Драфт

| Было | Стало |
|---|---|
| `DraftSessionCreateRequest.team_size: int = 5` | поле удалено |
| `DraftSessionCreateRequest.rounds` + валидатор `rounds == team_size - 1` | `rounds` удалён из запроса; выводится как `shape.draft_rounds` |
| `DraftSessionRead.team_size: int` | `DraftSessionRead.roster_shape: RosterShapeRead` |
| `DraftSlotRead.role: DraftRole` | `DraftSlotRead.slot_code: str` |
| `DraftRoleDeficitRead.role: DraftRole` | `DraftSlotDeficitRead.slot_code: str` |

`DraftPick.target_role` остаётся `DraftRole | None`; для flex-слота — `None`.

### 4.4 Балансер

`role_mask` уходит из `EDITABLE_CONFIG_FIELD_KEYS` и из
`PUBLIC_CONFIG_KEYS` — это больше не настройка балансера, а свойство турнира.
`AlgorithmConfig.role_mask` остаётся как внутреннее поле, но заполняется
резолвером на входе в прогон, а не дефолтом `{"Tank":1,...}`. Дефолт в
`defaults.py:23` и `presets.py:23` заменяется на `DEFAULT_ROSTER_SLOTS`
(lowercase). Легаси-конфиги с `Tank/Damage/Support` продолжают читаться через
`input_roles.resolve_input_role_name`.

---

## 5. Драфт: изменения

### 5.1 Слоты вместо ролей в feasibility

`draft/feasibility.py` уже решает задачу назначения максимальным паросочетанием
(`maximum_bipartite_matching`). Расширение минимально: словарь слотов вместо
словаря ролей.

```python
@dataclass(frozen=True)
class DraftFeasibilityState:
    team_ids: tuple[int, ...]
    slot_targets: dict[str, int]         # было role_targets: dict[DraftRole, int]
    players: tuple[EligiblePlayer, ...]
    assignments: tuple[DraftAssignment, ...]
```

`role_targets_for_team_size(team_size)` **удаляется**. `build_feasibility_state`
принимает `shape: RosterShape` и берёт `shape.slots`.

Правило пригодности слота, единственное новое:

```
слот с кодом ``flex``            → пригоден любому доступному игроку
слот с ролевым кодом ``r``       → пригоден игроку, у которого ``r`` в playable_roles
```

`EligiblePlayer.playable_roles` не меняется. `DraftAssignment.role: DraftRole`
становится `DraftAssignment.slot_code: str`; для занятого flex-слота — `"flex"`.

### 5.2 Валидация пика

`draft/selection.py`:

- `role_targets()` и `_role_capacity()` удаляются.
- `_team_role_counts` → `_team_slot_counts(players, picks, team_id, shape)`:
  ролевые слоты считаются по `pick.target_role or player.primary_role`, flex-слоты
  — как остаток `всего_взято − Σзанятых_ролевых`.
- Жёсткая проверка `role_filled` заменяется на:

```
capacity(role) == 0 and capacity(flex) == 0  → 422 slot_filled
```

Пик, чья роль переполнена, но у команды есть свободный flex-слот, — легален и
занимает flex-слот. Глобальную выполнимость по-прежнему подтверждает
`feasibility.analyze_session` и ошибка `pick_makes_draft_infeasible`; это уже
есть и не меняется.

- `target_role` при `has_role_slots == False` игнорируется на входе: 422 не
  выдаётся, значение не пишется.

### 5.3 Раунды и создание сессии

`lifecycle.validate_roster_shape(rounds, team_size)` заменяется на
`validate_draft_rounds(rounds, shape)` с тем же правилом `rounds == team_size - 1`,
но `team_size` берётся из формы. `create_session` теряет параметры `team_size` и
`rounds`, получает `shape: RosterShape`, пишет `rounds=shape.draft_rounds`.

### 5.4 Блокировка правки формы

`_ACTIVE_STATUSES` уже есть в `lifecycle.py` (`assert_no_active_draft`).
tournament-service при записи `roster_slots_json` делает read-only SELECT по
`balancer.draft_session` (модели видны через `shared.models`, тот же инстанс БД,
как app-service уже читает домен турниров в `dashboard/readiness.py`):

```
существует draft_session со status ∈ _ACTIVE_STATUSES → 422 roster_locked_by_draft
```

Тот же признак едет на фронт как `Tournament.roster_locked_by_draft: bool`,
чтобы поле в Settings было `disabled` с внятным пояснением, а не падало на save.

### 5.5 Экспорт в `Player.role`

При flex-слоте пишется фактическая роль игрока из регистрации
(`pick.target_role or player.primary_role`), если она известна, иначе `NULL`.
`Player.role` уже nullable. Ролевая аналитика не теряет разрез на flex-турнирах.

---

## 6. Балансер: изменения

### 6.1 Синтез flex-рейтинга — единственное содержательное место

`balancer/algorithm/player_loader.py:32-42` фильтрует рейтинги по
`algorithm_role in mask`. При маске `{"flex": 6}` `resolve_input_role_name("tank", mask)`
вернёт `None`, `ratings` останется пуст, `parse_player_node` вернёт `None` —
и Rust упадёт на `context.rs:41` `"player count must equal total roster slots"`.

Правка в `parse_player_node`, после существующего цикла по `raw_classes`:

```
если FLEX_SLOT_CODE в mask:
    ratings[FLEX_SLOT_CODE] = max(rank по всем активным ролям игрока)
    preferences = [FLEX_SLOT_CODE, *preferences]
```

Собранные ролевые рейтинги при этом **не** выбрасываются, даже если ролевых
слотов в маске нет: они не мешают (`Team`/`Player` смотрят только на роли из
маски), а `all_ratings` в результате остаётся полным для админской панели.

Почему `max`, а не средний или primary: это уже действующая политика проекта для
«готов играть что угодно» — `_all_roles_required` / `ratesByMaxRank`, закреплённая
паритет-тестами `test_forced_flex_parity.py` ↔ `forced-flex-parity.test.ts` на
общих фикстурах `docs/superpowers/fixtures/forced-flex-eff-rank.json`.

`FLEX_SLOT_CODE` первым в `preferences` даёт два корректных следствия без правок:
`entities.py:48-49` `discomfort_map["flex"] = 0` (flex-слот не причиняет
дискомфорта) и `result_serializer.py:72` не считает такое назначение off-role.

### 6.2 Источник маски

`role_mask` в `AlgorithmConfig` заполняется из `get_effective_roster_shape` на
входе в прогон (`admin/balancer.py`, `runtime.py`), а не берётся из дефолта.
`ConfigBuilder.with_role_mask` (`presets.py:143`) сохраняет свою валидацию, но
дополнительно прогоняет карту через `parse_roster_slots`.

`input_roles.resolve_input_role_name` учит `flex`: код `flex` в маске
резолвится только из литерала `flex`, и `STANDARD_ROLE_CODES` его не касается —
`flex` не роль, и «damage → flex» было бы ложью.

---

## 7. Фронтенд

### 7.1 Удаляемые зеркала

| Удаляется | Чем заменяется |
|---|---|
| `lib/draft-workspace-model.ts:157` `roleTargetsForTeamSize` + тест `:122-135` | `board.session.roster_shape.slots` с API |
| `draft/setup-model.ts:80` `roleTargets` | то же |
| `components/draft/TeamRosters.tsx:23` `ROSTER_ROLES` | `Object.keys(shape.slots)` в каноническом порядке |
| `draft/setup-model.ts:76` `roundsForTeamSize` | `shape.draft_rounds` |

Ни одна из формул не переносится на фронт. Это ровно образец 239 из реестра
зеркал: правило живёт на бэке, на фронт приезжает готовый конфиг.

### 7.2 Отображение ростера

`TeamRosters.tsx` (`computeTeamRosterView`) переходит на слоты:

- Счётчики строятся по `shape.slots`, а не по трём захардкоженным ролям.
- Flex-слот показывается своей иконкой/подписью «Flex», без ролевой иконки.
- При `has_role_slots === false` строка счётчиков ролей (`:168-175`, `:287-297`)
  и ролевые фильтры пула **не рендерятся** вовсе, а не показывают `1/0 2/0 2/0`.
- Колонка «Роль» в таблице ростера при `has_role_slots === false` схлопывается;
  роль игрока, если известна, уезжает в tooltip имени.

`DraftConfigStep.tsx`: поле «Team size» удаляется, «Rounds» становится read-only
производным от `shape.draft_rounds`, рядом — строка «Форма ростера: 1 Tank ·
2 DPS · 2 Support · всего 5» со ссылкой на Settings турнира.

### 7.3 Админский контрол

Живёт в `TournamentSettingsTab.tsx`, в существующей карточке
«Rules & grid configuration», под `team_formation` и `division_grid_version` —
там, где админ уже настраивает правила турнира.

Устройство:

1. **Селект пресетов.** Хардкодный список в одном модуле
   `frontend/src/lib/roster-shape.ts`: `Overwatch 5v5 · 1/2/2`,
   `6 флексов`, `Своя форма`. Плюс опция `Наследовать от workspace`, активная
   когда `roster_shape.source !== "tournament"`. Пресет — это UI-сахар над той же
   картой, не сущность.
2. **Степперы.** В режиме «Своя форма» — строка на каждый код из
   `ROSTER_SLOT_CODES`: Tank, DPS, Support, Flex. `NumberInput`, как у
   `win_points`, диапазон `0..12`.
3. **Живой итог.** `Итого: 6 слотов · раундов в драфте: 5`. Пересчитывается
   локально из карты (`Σ`, `Σ-1`) — это арифметика ввода, не правило домена, и
   бэк её всё равно перевалидирует.
4. **Предпросмотр.** Мини-карточка ростера теми же слотами, что увидит капитан:
   для `{tank:1,flex:5}` — одна ролевая строка и пять строк «Flex». Это отвечает
   на вопрос «что я только что настроил» без запуска драфта.
5. **Предупреждение о конфликте с регистрацией.** Если `has_role_slots` и
   регистрационная форма турнира не собирает роли (`built_in_fields.flex_role`
   отсутствует или роли не спрашиваются) — inline-warning со ссылкой на форму
   регистрации. Не блокирует сохранение: формы настраиваются в разном порядке.
6. **Блокировка.** При `roster_locked_by_draft` весь блок `disabled` с текстом
   «Драфт уже идёт — форма ростера зафиксирована. Завершите или отмените
   сессию». Тот же паттерн, что `configLocked` в визарде драфта
   (`i18n` ключ `draftAdmin.configLocked`).

Workspace-дефолт — тот же компонент, переиспользованный в настройках workspace,
без опции «Наследовать».

### 7.4 i18n

Новые ключи в `en.json`/`ru.json`: `roster.title`, `roster.preset.*`,
`roster.slot.tank|dps|support|flex`, `roster.total`, `roster.inherited`,
`roster.lockedByDraft`, `roster.registrationConflict`. Удаляются
`draftAdmin.teamSize` и `draftRedesign.hero.teamSize`/`rosterSize` в пользу
`roster.total`.

---

## 8. Тесты

| Уровень | Что закрепляем |
|---|---|
| `shared/tests/test_roster_shape.py` | `parse_roster_slots`: каждый код ошибки; выброс нулей; границы `2..12` включая позитивный граничный `{flex: MAX_TEAM_SIZE}`; нормализованный порядок; **производность `ROSTER_SLOT_CODES` от `REGISTRATION_ROLE_CODES`**, а не только её значение. `RosterShape`: сериализуемость (`json.dumps(slots)`, `asdict`, `deepcopy`), хешируемость, `FrozenInstanceError`, `__post_init__` отвергает ненормализованный вход. `resolve_roster_shape`: все три уровня цепочки. `has_role_slots` для `{flex:6}` vs `{tank:1,flex:5}`. `draft_rounds` |
| `shared/tests/test_roster_shape_migration_matches_models.py` | Колонки миграции совпадают с моделями — по образцу существующих `test_subscription_migration_matches_models.py` |
| `balancer-service/tests/test_draft_feasibility.py` | flex-слот пригоден игроку, который не играет ни одну ролевую роль; `{tank:1,flex:5}` матчится; `{flex:6}` матчится всегда при достаточном пуле |
| `balancer-service/tests/test_draft_selection_slots.py` (новый) | Пик с переполненной ролью уходит в свободный flex-слот; `slot_filled` только когда и роль, и flex исчерпаны; `target_role` игнорируется при `has_role_slots == False` |
| `balancer-service/tests/test_player_loader_flex.py` (новый) | При маске с `flex` игрок с ролевыми рейтингами получает `ratings["flex"] == max(...)`, `preferences[0] == "flex"`, и **не** отбрасывается; дискомфорт 0; не off-role |
| `balancer-service/tests/test_draft_schemas.py` | `team_size`/`rounds` больше не принимаются; `rounds` выводится |
| `tournament-service/tests/test_roster_shape_api.py` (новый) | `TournamentRead.roster_shape.source` = tournament/workspace/default; PATCH невалидной карты → 422 с кодом; PATCH при активном драфте → `roster_locked_by_draft` |
| `frontend/src/lib/roster-shape.test.ts` (новый) | Пресет ↔ карта в обе стороны; итог и раунды; порядок кодов |
| Удаляется | `draft-workspace-model.test.ts:122-135` (`roleTargetsForTeamSize`) — вместе с функцией |

Смоук: локальный запуск драфта на `{flex: 6}` от создания сессии до экспорта
команд, и один прогон балансера на той же форме — именно эти два пути падали бы
раньше всего.

---

## 9. Decision Log

| № | Решение | Альтернативы | Почему так |
|---|---|---|---|
| D1 | Форма ростера — карта `slot_code → count` с зарезервированным `flex` | (а) упорядоченный список слотов с `role: null`; (б) дискриминированный union `{mode:"roles"}` / `{mode:"flex"}` | Карта — ровно та форма, которую уже ждут Rust (`mask`) и bipartite matching. `null` в списке протёк бы в TS и Rust; union плодит два кодовых пути в четырёх местах и не выражает `{tank:1,flex:5}` |
| D2 | JSONB-колонка на tournament + дефолт на workspace + резолвер | (а) сущность `roster_template` с версиями; (б) только колонка на турнире | Копирует работающий `division_grid_access`. Версионирование не нужно: после турнира состав уже зафиксирован в `Player`-строках. Workspace-дефолт нужен, чтобы «у нас всегда 5v5» задавалось один раз |
| D3 | Форма управляет только вместимостью; `has_role_slots` выводится из неё | (а) единый выключатель ролевой механики, включая регистрационную форму; (б) влияние только на валидацию бэка | Один источник конфигурации без второго mode-флага. Автоправка регистрации тихо перезаписывала бы уже настроенную форму, а роли в регистрации нужны аналитике даже на flex-турнире. Вариант (б) оставил бы админа с бессмысленными `1/0 2/0 2/0` |
| D4 | Единый источник: локальные копии удаляются | Снапшот формы в сессию драфта и в конфиг баланса | Выбор владельца. Воспроизводимость архивных балансов сохраняется через `balance.result_json`, где лежит фактический состав; риск компенсируется D5 |
| D5 | Правка формы блокируется при любой незавершённой сессии драфта | (а) блокировать только `active`, на паузе разрешать с подтверждением; (б) всегда разрешать с предупреждением | Форма фиксируется в момент старта драфта — предсказуемо и не требует ревалидации уже сделанных пиков и пересчёта раундов на живой сессии |
| D6 | `rounds == Σslots - 1`, поле read-only | Развязать раунды и размер ростера | Правило уже существует (`validate_roster_shape`), меняется только источник числа. Развязка легализовала бы недобранные ростеры как нормальное состояние |
| D7 | `Player.role` при flex-слоте = фактическая роль из регистрации, иначе `NULL` | Всегда `NULL` | Ролевая аналитика и статистика не обнуляются на flex-турнирах; `role` трактуется как метаданные игрока, а не как слот |
| D8 | Новый модуль `shared/domain/roster_shape.py` | (а) расширить `shared/balancer/types.py RoleMask`; (б) держать канон в balancer-service и отдавать по RPC | `RoleMask` — мёртвый код: у `BalancerAlgorithm` ноль реализаций, ни один сервис не импортирует `shared.balancer.types`. `shared/domain/` — объявленное место бизнес-логики, рядом с живым `player_sub_roles.py`. RPC-хоп в балансер за чтением своей же колонки — регресс |
| D9 | `flex` не добавляется в `DraftRole` | Добавить член `FLEX` | `frozenset(DraftRole)` означает «все роли» в трёх местах; новый член поменял бы смысл каждого, задев 42 потребителя |
| D10 | Ноль не хранится в карте | Хранить явные нули | Снимает двусмысленность `{"tank":0,"flex":6}` и делает `has_role_slots` однозначным |
| D11 | Флекс-рейтинг = `max` по активным ролям | Средний; рейтинг primary-роли | Действующая политика проекта для «готов играть что угодно», закреплённая паритет-тестами `forced-flex-parity` на общих фикстурах |
| D12 | Оба TS-порта `roleTargets` удаляются, а не синхронизируются | Контракт-тест на паритет | Реестр зеркал, строка 239: server-driven конфиг — предписанное лекарство для этого класса. Паритет-тест нужен только там, где дедуп невозможен (Python↔Rust) |
| D13 | `RosterShape` хранит `entries: tuple[tuple[str,int],...]`; `slots`/`role_slots` — property, отдающие свежий `dict`; `to_dict()` удалён | (а) поле `Mapping` со значением `MappingProxyType`; (б) поле — обычный `dict` | `MappingProxyType` в публичном поле ломает `json.dumps`, `dataclasses.asdict`, `copy.deepcopy`, `pickle` и Pydantic `model_dump_json`/`model_copy(deep=True)` — ровно те пути, по которым форма едет в JSONB в задачах 5-6, причём pyright молчит, потому что `Mapping[str,int]` типизируется корректно. Кортеж пар решает всё сразу: хешируемость без ручного `__hash__`, сериализуемость, неизменяемость. Обычный `dict` в поле вернул бы мутабельность канона. `to_dict()` после этого побайтово дублировал `slots` — два имени для одного действия |
| D14 | `MIN_TEAM_SIZE = 2`, `draft_rounds = team_size - 1` без клампа | `MIN_TEAM_SIZE = 1` с `max(1, team_size - 1)` | Ростер из одного слота нечего драфтить и нечего балансировать: капитан занимает единственный слот, корректный ответ — 0 пиков, а кламп возвращал 1 и заставил бы драфт пикать в укомплектованную команду. `max(1, …)` был перенесён из фронтового `roundsForTeamSize`, где это кламп поля ввода, а не доменное правило. Побочно: нижняя граница проверки диапазона перестаёт быть недостижимой |
| D15 | Все константы модуля помечены `Final`; `DEFAULT_ROSTER_SLOTS` — `MappingProxyType`; добавлен готовый `DEFAULT_ROSTER_SHAPE` | Оставить обычные модульные значения | `DEFAULT_ROSTER_SLOTS["flex"] = 99` молча отравлял канон на всю жизнь процесса, а в задаче 2 он — хвост fallback-цепочки. Конвенция в репозитории уже есть: `shared/core/enums.py:206`. `DEFAULT_ROSTER_SHAPE` проверяет инвариант «дефолт сам валиден» на импорте и снимает повторный парсинг у задач 2-16 |
| D16 | `TournamentRead.roster_shape` — opt-in entity (`RosterShapeRead \| None`), заполняемая в `to_pydantic` при `"roster_shape" in entities` | (а) обязательное поле; (б) вычисляемое поле из одной колонки без резолва | `TournamentRead` вложен минимум в шесть других схем (`EncounterRead`, `TeamRead`, `PlayerRead`, `StandingRead`, `AchievementRead`, `OwalStandings`), которые собираются из ORM-строк без сессии — обязательное поле потребовало бы резолвить форму в каждой. Вычисляемое поле не умеет fallback на воркспейс, потому что для него нужен запрос к БД. Механизм opt-in уже применяется в этом же файле к `division_grid_version`, а `get_read` кеширован ключом `tournaments/{id}:{entities}`, так что opt-in не отравляет кеш |

---

## 10. Риски

| Риск | Митигация |
|---|---|
| `DROP COLUMN draft_session.team_size` необратим для отката кода | Снятие вынесено в отдельную ревизию (Task 9), которая применяется только после того, как код перестал читать колонку. Ревизия Task 3 — чистое добавление и обратима полностью. Downgrade второй ревизии восстанавливает колонку с `server_default="5"` и бэкфиллом `rounds + 1`, что точно воспроизводит прежние значения |
| Прогон балансера на `{flex:N}` уронит Rust, если синтез рейтинга не сработал | Тест `test_player_loader_flex.py` + смоук-прогон на `{flex:6}` до мержа. Rust-сторона не меняется вовсе |
| Легаси-конфиги балансера с `Tank/Damage/Support` в `balance.config_json` | `input_roles.resolve_input_role_name` остаётся и продолжает их резолвить; `role_mask` уходит только из **редактируемых** ключей |
| Активный драфт во время деплоя ревизии | Форма живых сессий совпадает с дефолтом (`rounds + 1 == 5` → `1/2/2`), потому что другой формы до этой фичи не существовало |
| Четвёртая копия словаря ролей (`schemas/admin/balancer.py:10`) останется | Вне объёма, но `ROSTER_SLOT_CODES` даёт ей канон для будущей замены |
