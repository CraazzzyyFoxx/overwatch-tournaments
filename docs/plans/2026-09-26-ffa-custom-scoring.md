# FFA: столбцы организатора и формула очков

**Status:** design approved (2026-09-26); implementation plan — следующий шаг.

**Goal:** организатор FFA-стадии сам задаёт, что вносится за игру (убийства, смерти, урон, штрафы…), и формулу,
по которой из этих значений и места считаются очки. Очки, места в `Standing` и публичная таблица пересчитываются
автоматически при каждой записи результата и каждой правке формулы.

**Architecture:** сырые значения игры — `encounter_game_result.stats jsonb` (`{"kills": 12, "deaths": 3}`) рядом с
`placement`; описание столбцов и формула — данные стадии (`settings_json.ffa_scoring`). Формула — выражение над
ключами столбцов и местом, разбирается стандартным `ast` Python с белым списком узлов (без `eval`) в новом чистом
модуле `shared/domain/ffa_formula.py` и вызывается из `shared/domain/ffa_scoring.py`. Очки нигде не хранятся: запись
результата, расчёт `Standing` и чтение лобби считают их одной функцией из сырых значений, как сейчас.

**Tech Stack:** Python 3.14 / SQLAlchemy 2 / Alembic / pydantic (backend), Go gateway (маршрут, кэш), Next.js 16 /
react-query / next-intl / vitest (frontend).

**Связанные документы.** Меняет §4.2 (формула очков), §5.2 (проверка игры) и §5.3 (тай-брейки)
[`2026-09-24-ffa-encounters.md`](./2026-09-24-ffa-encounters.md); остальное там в силе.

---

## 0. Область

**Делаем:** до 10 столбцов на стадию (ключ, подпись, «в таблице», «больше/меньше — лучше»); свободная формула;
тай-брейк по сумме любого столбца; скрытие непубличных столбцов в публичном API; админское чтение со всеми
столбцами; редактор стадии, диалог ввода и публичная таблица под новую модель; миграция существующих стадий и
результатов.

**Не делаем** — §11.

**Сценарии приёмки:**

1. Королевская битва: столбец `kills`, `placement_points = [10, 6, 5, 4, 3, 2, 1]`, формула `place_pts + kills`.
   Место обязательно при вводе; таблица показывает Σ убийств и очки за каждую игру.
2. OW FFA по счёту: столбцы `kills`, `deaths` (меньше — лучше, скрыт), формула `kills * 2 - deaths`. Место не
   вводится и выводится из очков игры; тай-брейк «сумма kills». Зритель видит очки и Σ kills, но не смерти — ни в
   таблице, ни в ответе API.
3. Посреди стадии организатор исправляет формулу — очки и места всех лобби пересчитываются; после посева следующей
   стадии правка формулы отвечает 409.

---

## 1. Что есть сейчас

| Факт | Где | Следствие |
| --- | --- | --- |
| Формула зашита: `placement_points[место−1] + score × score_points` | `backend/shared/domain/ffa_scoring.py:123-127` | Заменяется вызовом скомпилированной формулы |
| Правила — `FfaRules(placement_points, score_points)`; `parse_ffa_rules` только конвертирует | `ffa_scoring.py:39-61` | Правила получают столбцы и скомпилированную формулу |
| Место обязательно, если формула платит за место; иначе выводится из сырого `score` | `ffa_scoring.py:92-120` | Условие — «формула читает `place`/`place_pts`»; вывод — из очков игры |
| Итоги команды: `score: int` | `ffa_scoring.py:130-167` | `stats: dict[str, float]` |
| Результат участника: `placement int`, `score int`, CHECK `score >= 0` | `backend/shared/models/tournament/encounter_game_result.py:21-41` | `score` → `stats jsonb` |
| Настройки проверяет `FfaScoring(placement_points, score_points, score_label)`, `extra="forbid"` | `backend/tournament-service/src/schemas/admin/stage.py:32-48` | Новая форма и компиляция формулы на записи |
| Строка ввода `{team_id, placement?, score}` | `backend/tournament-service/src/schemas/ffa.py:34-37` | `{team_id, placement?, stats}` |
| Чтение: `FfaRulesRead`, `FfaGameCellRead.score`, `FfaLobbyRowRead.score`; `score_label` пробрасывается мимо `FfaRules` | `schemas/ffa.py:53-81`, `src/services/encounter/ffa.py:463-470` | Новые поля; фильтр непубличных столбцов |
| `score` читают только FFA-сервис, репозиторий и тесты | `services/encounter/ffa.py:378,501,682`, `backend/shared/repository/encounter.py:192`, `rpc/ffa.py:127` | Внешних читателей нет — миграция локальна |
| Тай-брейки FFA: `ffa_game_wins`, `ffa_score`, `ffa_best_placement`, `ffa_last_placement`; пресет по умолчанию с `ffa_score` | `backend/tournament-service/src/services/standings/service.py:57-87,300-309,717-720` | `ffa_score` → `ffa_stat:<key>` |
| Фронтовое зеркало тай-брейков — статический список | `frontend/src/lib/tournament/tiebreakers.ts:14-61`, `frontend/src/lib/bracket/projection.ts:101-105` | Пункты `ffa_stat:<key>` строятся из столбцов стадии |
| `update_stage` сливает `settings_json` и публикует «структура изменилась», но **не** ставит пересчёт мест | `backend/tournament-service/src/services/admin/stage.py:432-467` | Правка `placement_points` сегодня не переранжирует `Standing`; новая правка формулы обязана ставить пересчёт |
| Правка результата после посева следующей стадии запрещена (409) — проверка на одно лобби | `admin/stage.py:1640-1663`, вызов `rpc/ffa.py:61-63` | Нужна та же проверка на всю стадию |
| Обновление стадии идёт через CRUD-реестр админки (журнал до/после) | `backend/tournament-service/src/services/admin/registry.py:269` | Журнал правок формулы уже есть |
| Шлюз кэширует `GET /tournaments/{id}/stages/{stage_id}/ffa` до сигнала пересчёта турнира | `gateway/internal/tournament/cacheable.go:45-52` | Пересчёт после правки формулы сбрасывает кэш сам |
| Фронт сбрасывает `["ffa", id]` по ресурсам `tournament.encounters` и `tournament.standings` | `frontend/src/lib/realtime/resources.ts:62-75` | Новое админское чтение кладём под тот же префикс |
| Редактор стадии: пресет, «очки за единицу счёта», «подпись счёта», таблица очков за место | `frontend/src/app/admin/tournaments/[id]/bracket/components/FfaScoringSection.tsx`, `frontend/src/lib/ffa/scoring-presets.ts` | Переделывается под столбцы и формулу |
| Диалог ввода: место + одно поле счёта | `frontend/src/components/admin/ffa/FfaGameResultsDialog.tsx:84-183` | Поле на каждый столбец |

---

## 2. Журнал решений

| Решение | Отклонено | Почему |
| --- | --- | --- |
| Свободное выражение | Веса столбцов; веса + продвинутый режим | Выбор пользователя: нужны потолки (`min`), бонусы (`if`), нелинейные правила |
| Сырые значения в `stats jsonb`, очки считаются при чтении | Хранить очки в строке + задача пересчёта; нормализованная таблица `…_stat` | Один источник правды; правка формулы пересчитывает всё без фоновой задачи; значения всегда читаются вместе со строкой. Лобби ≤100 × ≤50 игр пересчитывается мгновенно |
| `placement` остаётся колонкой | Место как обычный столбец | На место опираются победы в играх, лучшее/последнее место, общие места и CHECK `placement >= 1` |
| Разбор стандартным `ast` + белый список | `eval`; библиотека (`simpleeval`); свой парсер | Без зависимостей; `eval` небезопасен. Ключевое слово `if` переименовывается до разбора (§4.3) |
| Место обязательно ⇔ формула читает `place`/`place_pts` | Отдельный флаг «место обязательно» | Требование выводится из формулы — его нельзя рассинхронизировать с ней |
| Без места место выводится из очков игры | Из первого столбца | Столбцов несколько; очки — единственная общая мера игры |
| Тай-брейк `ffa_stat:<key>` по любому столбцу; направление — `better` столбца | Только встроенные; один «главный» столбец | Выбор пользователя |
| Итоги в таблице — только столбцы с `public: true` | Все столбцы; только очки | Выбор пользователя |
| Непубличные значения не отдаются публичным API; отдельное админское чтение | `public` только для отображения | Выбор пользователя: скрытые столбцы (штрафы, смерти) не видны зрителю |
| Формула в публичном ответе — как есть | Прятать формулу со скрытыми ключами | Правило — не данные; зритель видит имя ключа, но не значения |
| Правки, меняющие места (формула, `placement_points`, ключи, `better`), — до посева следующей стадии | Замок после 1-й игры; всегда | Выбор пользователя. Подписи и `public` места не меняют и редактируются всегда |
| Нельзя удалить/переименовать ключ со значениями | Удалять вместе со значениями | Значения — запись турнира; потеря незаметна до спора |
| Деление на 0 → 0 | Ошибка игры | `kills / deaths` не должно ломать игру без смертей |
| `round` — арифметическое (0.5 вверх) | Банковское `round` Python | Организатор ждёт `round(2.5) = 3` |
| Очки игры округляются до 4 знаков | Float как есть | `0.1 + 0.2 ≠ 0.3` не должно давать ложных неравенств в тай-брейке |
| Поле `score` в API удаляется без переходного периода | Поддерживать оба поля | Фронт и бэкенд выходят одним релизом; внешних клиентов записи FFA нет |

---

## 3. Модель данных

### 3.1. `stage.settings_json.ffa_scoring`

```json
{
  "columns": [
    {"key": "kills",  "label": "Убийства", "public": true,  "better": "higher"},
    {"key": "deaths", "label": "Смерти",   "public": false, "better": "lower"}
  ],
  "placement_points": [10, 6, 5, 4, 3, 2, 1],
  "formula": "place_pts + kills * 2 - deaths"
}
```

| Поле | Правило | Код ошибки (422) |
| --- | --- | --- |
| `columns` | 0–10 элементов | `ffa_columns_too_many` |
| `columns[].key` | `^[a-z][a-z0-9_]{0,23}$` | `ffa_column_key_invalid` |
| | не служебное имя: `place`, `place_pts`, `teams`, `min`, `max`, `abs`, `round`, `if`, `if_`, `and`, `or`, `not` | `ffa_column_key_reserved` |
| | уникален в стадии | `ffa_column_duplicate` |
| `columns[].label` | 1–32 символа после trim | стандартная ошибка pydantic |
| `columns[].public` | bool, по умолчанию `true` | — |
| `columns[].better` | `higher` \| `lower`, по умолчанию `higher` | — |
| `placement_points` | как сейчас: ≥ 0, не длиннее `FFA_MAX_LOBBY_SIZE` | как сейчас |
| `formula` | 1–500 символов; компилируется (§4) | `ffa_formula_*` |

Ошибки — `PydanticCustomError(type=<код>, ctx={"offset": n, "name": …})`, чтобы фронт показал позицию под полем.
Блок не задан → `columns = [{"key": "score", "label": "Счёт"}]`, `formula = "score"` — сегодняшнее поведение
стадии без `ffa_scoring`; подпись та же, что миграция ставит стадиям без `score_label` (§3.3).

### 3.2. `tournament.encounter_game_result`

```
  - score integer NOT NULL DEFAULT 0, CHECK score >= 0
  + stats jsonb NOT NULL DEFAULT '{}'
  + ck_encounter_game_result_stats CHECK (jsonb_typeof(stats) = 'object')
```

Значения — конечные числа `0 ≤ v ≤ 1e9`, дробные допустимы; проверяются на записи (§5.2). Ключа, которого нет в
`stats`, при расчёте равен 0: столбец, добавленный посреди стадии, не ломает сыгранные игры.

### 3.3. Миграция `ffa0002` (одна ревизия, с обратным ходом)

Вперёд:

1. `stats = jsonb_build_object('score', score)`; снять CHECK и колонку `score`; добавить CHECK `stats`.
2. Каждая стадия с `settings_json ? 'ffa_scoring'` (цикл в Python — стадий единицы):
   `columns = [{"key": "score", "label": score_label or "Счёт", "public": true, "better": "higher"}]`;
   `formula` = `place_pts + score * k` при непустом `placement_points`, иначе `score * k`; при `k = 1` без `* 1`.
   `score_points` и `score_label` удаляются.
3. `tiebreak_order`: `ffa_score` → `ffa_stat:score`.
4. Снимки в `encounter_result_audit.ffa_results_json` не трогаем: это история, новые строки пишутся в новой форме.

Назад: отказ (`RuntimeError`, как у `ffa0001`), если у какой-то стадии столбцы — не ровно `[score]` или формула не
совпадает с `^(place_pts \+ )?score( \* [0-9.]+)?$`. Иначе обратное преобразование:
`score = round((stats->>'score')::numeric)`, `score_points`/`score_label` восстанавливаются из формулы и подписи.

---

## 4. Язык формулы

### 4.1. Грамматика

Формула считается для каждой команды в каждой подтверждённой игре; очки команды — сумма по играм.

| Элемент | Что это |
| --- | --- |
| Числа | `2`, `0.5`, `1_000`. Без экспоненты-бесконечности, без `True/False/None`, без комплексных |
| Ключ столбца | значение столбца у команды в этой игре; нет значения → 0 |
| `place` | место команды в этой игре (после вывода, §5.2) |
| `place_pts` | `placement_points[place − 1]`, 0 за концом списка |
| `teams` | число команд в игре |
| `+ − * /`, унарный `−`, скобки | арифметика |
| `== != < <= > >=` | сравнение, результат 1 или 0; цепочки `a < b < c` допустимы |
| `and`, `or`, `not` | логика над «не ноль = истина», результат 1 или 0 |
| `min(a, b, …)`, `max(a, b, …)` | ≥ 2 аргумента |
| `abs(x)` | модуль |
| `round(x)`, `round(x, n)` | арифметическое округление, `0 ≤ n ≤ 6` |
| `if(условие, то, иначе)` | ровно 3 аргумента |

Всё остальное — `**`, `%`, `//`, строки, индексы, атрибуты, срезы, именованные аргументы, прочие вызовы, лямбды,
генераторы — `ffa_formula_unsupported`.

### 4.2. Семантика

- Все значения — `float`. Деление на 0 даёт 0.
- Очки игры = результат формулы, округлённый до 4 знаков. Отрицательные допустимы (штрафы).
- Результат не конечный (переполнение) → 0.

### 4.3. Разбор (`shared/domain/ffa_formula.py`)

```python
class FfaFormulaError(ValueError):
    code: str          # ffa_formula_syntax | ffa_formula_unknown_name | ffa_formula_unsupported | ffa_formula_too_complex
    offset: int        # позиция в исходной строке, 0-based
    name: str | None   # для unknown_name

@dataclass(frozen=True)
class Formula:
    source: str
    names: frozenset[str]          # переменные, которые формула читает
    def evaluate(self, values: Mapping[str, float]) -> float: ...

def compile_formula(source: str, columns: Iterable[str]) -> Formula: ...
```

1. `if(` → `if_(` регулярным выражением `\bif(?=\s*\()` с таблицей вставок для пересчёта позиций ошибок обратно в
   исходную строку. Ключи столбцов не могут быть `if`/`if_` (§3.1), строк в языке нет — замена однозначна.
2. `ast.parse(source, mode="eval")`; `SyntaxError` → `ffa_formula_syntax` с позицией.
3. Обход дерева: разрешены только узлы из §4.1; > 100 узлов → `ffa_formula_too_complex`; имя вне
   `columns ∪ {place, place_pts, teams}` и не функция → `ffa_formula_unknown_name`.
4. `evaluate` — рекурсивный интерпретатор по проверенному дереву; `eval`/`compile` не вызываются.

---

## 5. Расчёт (`shared/domain/ffa_scoring.py`)

### 5.1. Правила

```python
@dataclass(frozen=True, slots=True)
class FfaColumn:
    key: str
    label: str
    public: bool = True
    better: Literal["higher", "lower"] = "higher"

@dataclass(frozen=True, slots=True)
class FfaRules:
    columns: tuple[FfaColumn, ...]
    placement_points: tuple[float, ...]
    formula: Formula

    @property
    def requires_placement(self) -> bool:
        return bool(self.formula.names & {"place", "place_pts"})
```

`parse_ffa_rules(settings)` компилирует формулу один раз на стадию. Блок уже проверен на записи, поэтому ошибка
компиляции здесь — повреждённые данные: исключение, а не молчаливый ноль.

### 5.2. Проверка игры — `normalize_game_lines(lines, participant_ids, rules)`

`FfaGameLine(team_id, placement, stats: Mapping[str, float])`.

1. Команды — как сейчас: `ffa_result_unknown_team`, `ffa_result_duplicate_team`, `ffa_result_missing_team`.
2. Значения: у каждой строки ровно ключи `rules.columns` — лишний ключ `ffa_result_unknown_stat`, недостающий
   `ffa_result_missing_stat`; значение не число, не конечное, `< 0` или `> 1e9` — `ffa_result_invalid_stat`.
   `ffa_result_invalid_score` удаляется.
3. Места:
   - `rules.requires_placement` → место у всех, строго перестановка `1..N` (`ffa_result_placement_required`,
     `ffa_result_invalid_placement`), как сейчас у формулы с очками за место;
   - иначе места либо у всех (`1..N`, общие допустимы), либо ни у кого (`ffa_result_mixed_placement`). Нет мест →
     очки игры считаются без `place`/`place_pts` (формула их не читает) и места выводятся из очков по убыванию,
     общие места при равенстве: 10, 7, 7, 3 → 1, 2, 2, 4.

### 5.3. Очки и итоги

- `game_points(line, rules, teams) = round(formula.evaluate({**stats, place, place_pts, teams}), 4)`.
- `FfaTeamTotals`: `score: int` → `stats: dict[str, float]` (сумма по каждому столбцу); `games`, `points`, `wins`,
  `best_placement`, `last_placement` — как сейчас.
- `team_totals` не меняет сигнатуру по смыслу: игры, команды, правила.

### 5.4. Тай-брейки (`standings/service.py`)

- Метрика `ffa_stat:<key>`: сумма столбца; `better = "lower"` сортирует по возрастанию (значение отрицается, как
  уже сделано у `ffa_last_placement`).
- `normalize_tiebreak_order(order, *, ffa_columns=())` пропускает `ffa_stat:<key>` только для существующих ключей,
  остальное — как сейчас. `ffa_score` из `KNOWN_TIEBREAK_METRICS` удаляется.
- Порядок по умолчанию для `ffa_league`: `points`, `ffa_game_wins`, `ffa_stat:<первый столбец>` (если есть),
  `ffa_last_placement`.
- `RankedTeam.ffa_score` → `ffa_stats: dict[str, float]`.

---

## 6. Правка правил посреди стадии

- **Меняют места:** `formula`, `placement_points`, набор ключей столбцов, `better`. Разрешены, пока ни один
  элемент стадии не посеял уже начатую следующую стадию: новая `assert_stage_correction_allowed(session, stage)` —
  та же логика, что `assert_source_correction_allowed` (`admin/stage.py:1640-1663`), по всем элементам стадии; 409 с
  тем же текстом. Сравнение «до/после» — по нормализованному блоку, чтобы повторное сохранение той же формы не
  упиралось в 409.
- **Не меняют места:** `label`, `public` — разрешены всегда.
- **Ключ со значениями:** удалить столбец или сменить его `key`, если у результатов стадии есть этот ключ, —
  422 `ffa_column_in_use` (`… stats ? :key` по играм стадии).
- **После успешной правки:** `enqueue_tournament_recalculation(session, tournament_id)` — пересчёт `Standing`,
  сигнал `tournament.standings`, сброс кэша шлюза и фронтовых ключей `["ffa", id]`. Журнал — CRUD-реестр (§1).

---

## 7. API

### 7.1. Запись результата

`POST /api/v1/admin/encounters/{id}/ffa/games/{position}/results` — маршрут и права без изменений:

```json
{"results": [{"team_id": 17, "placement": 2, "stats": {"kills": 12, "deaths": 3}}], "reason": null}
```

`FfaGameResultLineInput`: `team_id`, `placement: int | None (ge=1)`, `stats: dict[str, float]`. Снимок журнала —
`{team_id, placement, stats}`.

### 7.2. Сохранение стадии

`StageUpdate.settings_json` через CRUD-реестр, как сейчас. `FfaScoring` проверяет форму и компилирует формулу;
`update_stage` при изменении `ffa_scoring` выполняет §6.

### 7.3. Чтение

**Публичное** — `GET /tournaments/{id}/stages/{stage_id}/ffa`, `GET /encounters/{encounter_id}/ffa`:

```jsonc
{
  "rules": {
    "columns": [{"key": "kills", "label": "Убийства", "public": true, "better": "higher"}], // только public
    "placement_points": [10, 6, 5],
    "formula": "place_pts + kills * 2 - deaths",
    "requires_placement": true
  },
  "rows": [{
    "…": "…",
    "points": 53.0,
    "stats": {"kills": 29},                                   // суммы, только public
    "games": [{"position": 1, "state": "confirmed", "placement": 3, "points": 16.0, "stats": {"kills": 6}}]
  }]
}
```

`FfaLobbyRead` строится один раз со всеми столбцами; публичные обработчики обрезают `rules.columns`, `row.stats` и
`cell.stats` до `public` одной функцией `public_view(lobby)` в `services/encounter/ffa.py`.

**Админское** — новый `GET /api/v1/admin/tournaments/{id}/stages/{stage_id}/ffa`:

- RPC `rpc.tournament.ffa_stage_admin`, право `match.update` на воркспейс турнира (как у записи результата);
- тот же `FfaLobbyRead`, без обрезки;
- маршрут в `gateway/internal/tournament/admin_misc_routes.go` рядом с записями FFA, `Auth: edge.AuthRequired`;
  в `cacheable.go` **не** добавляется;
- описание в OpenAPI шлюза — как у остальных `rpc.tournament.ffa_*`.

---

## 8. Интерфейс

### 8.1. Редактор стадии (`FfaScoringSection.tsx`, `stageForm.ts`)

- Поля формы: `ffaScorePoints`, `ffaScoreLabel` → `ffaColumns`, `ffaFormula`; `ffaPlacementPoints` остаётся.
- Список столбцов: ключ, подпись, «в таблице», «больше/меньше — лучше», удалить; «Добавить столбец» (≤ 10).
- Пресеты (`lib/ffa/scoring-presets.ts`) заполняют столбцы, очки за место и формулу: «Только счёт» — `score`,
  `score`; «Королевская битва» — `kills`, `[10, 6, 5, 4, 3, 2, 1]`, `place_pts + kills`.
- Формула — моноширинное поле; под ним переменные (ключи столбцов, `place`, `place_pts`, `teams`) и функции.
  Ошибка сервера — под полем: «Позиция 14: неизвестное имя `kils`».

### 8.2. Тай-брейки

`lib/tournament/tiebreakers.ts`: тип метрики — `TiebreakerMetricId | \`ffa_stat:${string}\``; пункты
«Сумма: <подпись>» строятся из столбцов стадии; `ffa_score` удаляется из списка, подписей и
`lib/bracket/projection.ts`. `tiebreakerLabel` получает подписи столбцов.

### 8.3. Диалог ввода (`FfaGameResultsDialog.tsx`)

- Данные — из админского чтения (`ffaService.getStageAdmin`), им же пользуется страница лобби в админке.
- Колонки: команда, место (обязательно при `rules.requires_placement`, иначе «необязательно»), поле на каждый
  столбец, включая скрытые (у скрытых — пометка «не видно зрителям»).
- Исправление подставляет внесённые значения; пустое поле — не ноль (как сейчас, текст ошибки называет столбец).

### 8.4. Публичная таблица (`FfaLobbyTable.tsx`)

- Колонки: `#`, Команда, Очки, Игры, итог каждого `public`-столбца (подпись столбца), И1…Иn, Статус.
- Ячейка игры: место сверху, очки игры снизу. Публичные значения игры — в `title` и скрытой подписи для диктора:
  «Место 3, Очки 16, Убийства 6».
- Легенда: «Ячейка игры: место / очки» · «Очки = `<формула>`» · «Очки за место: 10 · 6 · 5…» при непустом
  `placement_points`. Строки `ffa.legendPoints*`, `ffa.legendCells` из коммита `66df6ed2` заменяются.
- Типы `frontend/src/types/ffa.types.ts` — зеркало §7.3.

---

## 9. Тесты

Правило репозитория: тест защищает наблюдаемый контракт; проводку, дефолты и тексты не пиним.

| Файл | Что доказывает |
| --- | --- |
| `backend/shared/tests/test_ffa_formula.py` (новый) | Каждая конструкция §4.1 считает правильно; запрещённые — `ffa_formula_unsupported` с позицией в **исходной** строке (в том числе после `if(`); неизвестное имя — код и имя; деление на 0 → 0; `round(2.5) = 3`; > 100 узлов — `too_complex`; `formula.names` |
| `backend/shared/tests/test_ffa_scoring.py` | Место обязательно ⇔ формула читает место; вывод мест из очков с общими местами; `missing/unknown/invalid_stat`; суммы `stats`; отсутствующий ключ = 0 |
| `backend/tournament-service/tests/test_standings_ranking.py` | `ffa_stat` ранжирует в обе стороны; `normalize_tiebreak_order` отбрасывает ключ удалённого столбца |
| `backend/tournament-service/tests/test_ffa_stage_settings.py` | Коды §3.1; формула с ошибкой не сохраняется |
| `backend/tournament-service/tests/test_ffa_results_integration.py` | Запись со `stats`; правка формулы пересчитывает `Standing`; `ffa_column_in_use`; 409 после посева; публичное чтение не содержит непубличных значений ни в `rules`, ни в строках, ни в ячейках; админское — содержит |
| Миграция | `upgrade`/`downgrade` на копии dev: `score` ↔ `stats.score`, формулы §3.3, отказ `downgrade` на новой форме |
| `frontend/src/components/ffa/FfaLobbyTable.behavior.test.tsx` | Итоги только публичных столбцов; ячейка — место и очки игры; скрытая подпись со значениями |
| `frontend/src/components/admin/ffa/FfaGameResultsDialog.behavior.test.tsx` | Поле на каждый столбец включая скрытые; место обязательно по `requires_placement`; пустое ≠ 0 |

---

## 10. Выпуск и документация

- Один релиз: миграция `ffa0002` + бэкенд + шлюз + фронт (поле `score` удаляется сразу).
- `frontend/src/app/(site)/docs/_content/{en,ru}/dev/tournaments.mdx`: абзац о формуле (строка 81) и о метриках
  FFA (строка 122).
- `docs/plans/2026-09-24-ffa-encounters.md` §4.2/§5.2/§5.3 — пометка «заменено, см. этот документ».
- i18n `ffa.errors.*` (en/ru) — новые коды §3.1, §4.3, §5.2, `ffa_column_in_use`; удалить `ffa_result_invalid_score`.

---

## 11. Не сейчас

- Статистика по игрокам внутри команды: значения — на участника лобби, как `score` сегодня.
- Предпросмотр очков в диалоге ввода и отдельная ручка «проверить формулу»: ошибку с позицией возвращает сохранение
  стадии, игру можно исправить.
- Вычисление формулы на фронте (TS-двойник разборщика).
- FFA-статистика в профилях, рейтингах, аналитике (план FFA §11).
- Защита от правки `tiebreak_order` после посева — тот же класс проблемы, но существует и вне этой работы.

---

## 12. Риски

| Риск | Мера |
| --- | --- |
| Опечатка в формуле посреди стадии молча переставит места | Правка пишется в журнал; после посева — 409; легенда таблицы показывает действующую формулу |
| Шум `float` создаёт ложное неравенство очков | Очки игры округляются до 4 знаков (§4.2) |
| Разбор через `ast` пропустит новую конструкцию будущего Python | Белый список узлов: всё, чего нет в списке, отвергается |
| Зритель узнаёт имя скрытого ключа из формулы | Принято (§2): правило публично, значения — нет |
| Downgrade после настройки новых столбцов теряет данные | `ffa0002.downgrade` отказывает, как `ffa0001` |
