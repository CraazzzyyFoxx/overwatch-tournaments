# Map Pool / Veto Redesign

Статус: дизайн утверждён (brainstorming), реализация не начата.
Дата: 2026-07-18

## Проблема

Текущий механизм вето мёртв:
- `MapVetoConfig` нигде не создаётся (нет ни одного writer'а) → `get_veto_config()` всегда `None` → `map-pool/state` и `veto` отвечают 400.
- Пул на энкаунтер админ назначает руками (`encounter_assign_map_pool`) на каждый матч, без автоинициализации.
- Последовательность — жёсткие токены `ban_home`/`pick_away`; правил посева нет.
- UI — маленькая панель `MapVeto.tsx` внутри `encounters/[id]`.

## Понимание (зафиксировано)

- Организатор задаёт пул карт и правила вето; капитаны пикают/банят в realtime-комнате; зрители смотрят без авторизации.
- Конфиг: каскад турнир → этап → раунд (специфичный выигрывает).
- Первый ход: «выше посев ходит первым»; посев: `StageItemInput.slot` → `Standing.position` предыдущего этапа → fallback home; фиксируется снапшотом при инициализации.
- Последовательность: пресеты Bo1/Bo3/Bo5 + кастомный конструктор шагов.
- Пул матча создаётся автоматически из конфига, когда известны обе команды.
- UI: отдельная страница-комната по образцу драфта.
- Таймер: только индикатор; админ может сделать ход за команду.

### Допущения
- Масштаб — комьюнити-турниры, десятки одновременных комнат.
- Realtime — существующий hub (thin signal `encounter:{id}:map-veto` + refetch).
- Конкурентные ходы защищаются на уровне БД (`FOR UPDATE`).
- Пик стороны (attack/defense) не нужен — только карты.

### Не-цели
- Челлонж-синк не трогаем; авторасстановка карт в игровом лобби — нет; чат в комнате — нет; ready-check — нет.

## Архитектура (Вариант A — явная Veto Session)

### Модель данных

**`MapVetoConfig` (расширение):**
- `+ round: int | null` — третий уровень каскада; CHECK: `round IS NULL OR stage_id IS NOT NULL`; UNIQUE `(tournament_id, stage_id, round)`.
- `+ first_pick_rule: enum('higher_seed')` — задел, пока одно значение.
- `+ turn_timer_seconds: int | null`.
- `+ preset: str | null` — метка шаблона (`bo1`/`bo3`/`bo5`/`custom`) для UI.
- `veto_sequence_json` — side-агностичные токены: `ban_first | ban_second | pick_first | pick_second | decider`.
- Пул — как есть (`map_veto_config_map`).

Каскад резолва: `(stage, round)` → `(stage, null)` → `(null, null)`.

**`EncounterVetoSession` (новая, 1:1 с encounter):**

| поле | назначение |
|---|---|
| `encounter_id` UNIQUE FK | привязка |
| `config_id` FK nullable (SET NULL) | информационная ссылка; снапшот делает удаление конфига безопасным |
| `first_side` enum(home/away) | результат резолва посева |
| `seed_source` enum(bracket_slot/standings/fallback_home/admin) | аудит «почему» |
| `home_seed`, `away_seed` int null | снапшот посевов |
| `resolved_sequence_json` JSON | `first/second` → `home/away`, зафиксировано на старте |
| `status` enum(active/completed/cancelled) | lifecycle комнаты |
| `started_at`, `current_step_started_at` | опора для таймера-индикатора |

**`EncounterMapPool`:** `+ action_index: int | null` — глобальный порядок действий для таймлайна (сейчас `order` перезаписывается только у пиков, история банов теряется).

### Бэкенд API и флоу

Admin RPC (workspace-scoped):
- `rpc.tournament.admin_veto_config_upsert` — конфиг уровня (tournament|stage|round): пул, последовательность, таймер. Валидация: pick-шагов + decider ≤ пул; банов+пиков ≤ пул; последовательность непустая.
- `rpc.tournament.admin_veto_config_list` / `_delete`.
- `rpc.tournament.admin_veto_session_reset` — drop session + pool, пересоздание с пере-резолвом посева.
- `rpc.tournament.admin_veto_act` — ход за сторону `{encounter_id, side, map_id, action}`.

`ensure_veto_session` (идемпотентно):
1. Резолв конфига по каскаду; нет конфига → сессии нет, комната показывает `not_configured`.
2. Резолв посева: slot → standings предыдущего этапа → fallback home (tie → home). Источник и seed'ы в сессию.
3. Маппинг `first/second` → `home/away`; копия пула в `encounter_map_pool`; `status=active`.
4. Точки вызова: хук назначения обеих команд + лениво из read-путей комнаты.

`perform_veto_action` (переработка):
- `SELECT … FOR UPDATE` на сессию.
- Последовательность из `session.resolved_sequence_json`; валидации очереди/доступности/типа как сейчас.
- Запись: статус карты, `picked_by`, `action_index`, `current_step_started_at = now()`; decider авто-резолв; последний шаг → `status=completed`.
- Realtime: существующий thin-signal + refetch, без изменений.

`captain_map_pool_state` дополняется: `first_side`, seeds, `seed_source`, `session_status`, `turn_timer_seconds`, `current_step_started_at`, таймлайн действий.

### Фронтенд

1. **Admin-редактор конфига** (админка турнира): вкладки каскада (турнир/этап/раунд, индикатор наследования); грид карт с мультивыбором и сортировкой; пресеты Bo1/Bo3/Bo5, генерируемые от размера пула; кастомный конструктор шагов (действие + очередь first/second, drag, живая валидация); поле таймера.
2. **Комната** `tournaments/[id]/veto/[encounterId]` (по образцу драфт-страницы):
   - Hero: команды с seed-бейджами, «первым ходит X (посев #N)», статус сессии.
   - Грид карт: изображения, статусы, кто действовал; итоговый порядок карт.
   - Таймлайн шагов + таймер-индикатор (отсчёт от `current_step_started_at`; по нулю — подсветка, без форса).
   - Капитан: двухшаговое подтверждение хода (паттерн PickCommandBar). Зритель — read-only без авторизации. Админ: «ход за команду», «reset вето».
   - Realtime: `useRealtimeTopic` + refetch.
3. **Интеграция:** в списке матчей/бракете — компактный чип статуса вето + переход в комнату. Страница `encounters/[id]`: панель `MapVeto` **удаляется полностью** (компонент тоже), в Header/Hero добавляется ссылка «Комната вето» (видна при существующей сессии).

### Edge cases

- Команды сменились после инициализации → хук смены команд сбрасывает сессию (drop + пересоздание).
- Конфиг изменён во время вето → сессия на снапшоте, не затрагивается.
- Нет конфига → `not_configured`, ссылка в Hero скрыта.
- Пул меньше последовательности → отклонено валидацией при сохранении конфига.
- Tie посева / нет stage_item / нет standings → fallback home, `seed_source=fallback_home`.
- Конкурентные ходы → `FOR UPDATE`; проигравший получает 400, UI refetch по realtime.
- Encounter завершён/отменён → действия блокируются по статусу энкаунтера.

### Тестирование

- Unit: каскад конфигов; резолв посева (slot/standings/fallback/tie); маппинг токенов; валидация последовательности; шаговый движок (по образцу `test_map_veto_state.py`).
- Service: идемпотентность `ensure_veto_session`; полный флоу Bo3; admin reset; admin act.
- Frontend: contract-тесты состояний комнаты (капитан/зритель/админ) по паттернам драфт-страницы.

## Decision Log

| Решение | Альтернативы | Почему |
|---|---|---|
| Явная `EncounterVetoSession` (Вариант A) | B: поля на encounter; C: event-sourced engine | чистый lifecycle/reset/аудит за одну таблицу; C — YAGNI |
| Каскад турнир→этап→раунд | только турнир / турнир+этап | запрошено; round требует stage_id |
| Посев: slot→standings→home, снапшот при старте | явный seed; live standings | без миграции команд; порядок не «плывёт» во время вето |
| Side-агностичные токены `first/second` | оставить `home_*`/`away_*` | правило посева иначе невыразимо |
| Таймер — индикатор без форса | авто-действие | запрошено; admin act закрывает зависших |
| Комната — отдельная страница | модалка | запрошено; паттерн драфта, зрители/стримы |
| `encounters/[id]`: панель удаляется, ссылка в Hero | read-only сводка | запрошено пользователем |
| Автосоздание сессии `active` без ready-check | ручной старт админом | YAGNI: таймер не форсит, reset есть |
