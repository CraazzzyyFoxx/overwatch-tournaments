# Аудит слоя Roster / роли / ранги / flex

**Status:** implemented (2026-09-10)

Аудит бизнес‑логики «какие роли играет игрок, с каким рангом на каждой, что такое flex» —
от записи регистрации до балансера, драфта и пикап‑миксов. §1–§3 — состояние на момент аудита
(ссылки `file:line` — до правок); §4 — что и как исправлено.

Дата: 2026‑09‑10. Все ссылки `file:line` — на состояние рабочего дерева в этот день.

---

## 1. Карта слоя

### 1.1 Схемы и источники данных

| Сущность | Где | Что хранит | Замечание |
|---|---|---|---|
| `BalancerRegistration` | `shared/models/registration/registration.py:140` | регистрация; `team_slot_code` (tank/dps/support/**flex**); `is_flex_computed` hybrid | `is_flex_computed = len(roles)>1 and all(is_primary)` по **сырым** строкам |
| `BalancerRegistrationRole` | там же `:254` | `role` (str), `is_primary`, `priority`, `rank_value`, `is_active`, `subrole` | `is_primary` и `is_active` никак не связаны на записи |
| `registration_form.built_in_fields_json.flex_role` | форма | `{enabled, mode: optional/all_roles/forced}` | единственный читатель — `flex_role_mode()` |
| `MemberRank` | `shared/models/...member_rank` | `(workspace_member_id, role, rank_value, author_user_id)`; `author NULL` = канон воркспейса | ключ роли — `slot_code` (`dps`) |
| `UserRankSnapshot` (OW) | parser‑service | ранги по аккаунтам, роль `damage` | приводится к `dps` в `rank_snapshots.canonical_to_registration_role` |
| `DivisionGrid` | `shared/division_grid.py` | сетка дивизионов; OW‑ранг нормализуется на неё | mix намеренно использует глобальную (`workspace_id=None`) |
| `RosterShape` | `shared/domain/roster_shape.py:84` | `{tank,dps,support,flex}: count`; `team_size`, `flex_slots`, `has_role_slots` | чистый, без I/O |
| `HeroClass` | `shared/core/enums.py:7` | tank/damage/support/**flex**; `slot_code` (`damage→dps`) | `flex` — только «нет фиксированной роли» |
| `DraftPick.target_role / target_rank_value` | `shared/models/balancer/draft.py` | единственная **замороженная** производная (роль, ранг) пика | по дизайну |

### 1.2 Единый движок

`shared/services/roster.py::RosterEngine`

```
for_tournament(pool_only?, registration_ids?, include_deleted?)
  └─ resolve(registrations, workspace_id, form?, grid?, order=TOURNAMENT_ORDER)
       ├─ _declared_roles(reg, mode)        # набор и ПОРЯДОК ролей
       │     optional      → активные строки, по priority
       │     all_roles/forced → все три; отсутствующие синтезируются (bare HeroClass)
       ├─ _resolve_ranks(...)                # MemberRankService.resolve
       │     registration > workspace > ow   # pick_rank: первый не-None
       └─ _build(reg, declared, resolved, mode) → PlayerRoster
             non-optional: rank None → best_rank
             is_full_flex = reg.is_flex_computed        ← обход движка (см. F5)
```

`shared/domain/roster.py::PlayerRoster` — value object. Инвариант (`:13`):
**роль играбельна ⇔ объявлена активной И резолвер нашёл число.** Производные: `playable`,
`playable_roles`, `primary` (flag → первая играбельная), `best_rank`, `rank_on(role|None)`,
`covers(role|flex|None)`, `is_ranked_complete`, `is_draftable`.

Проекции движка: `balancer_input()` (xv‑1) и `full_export()` (owt‑1).

### 1.3 Потребители

| Поток | Вход | Ключевые функции |
|---|---|---|
| Балансер турнира | `balancer_input` → `run_balance` | `player_loader.parse_player_node` → `entities.Player` → `runtime._prepare_balance_context` (trim) → backend (`tournament_balancer` Rust / python) → `result_serializer.teams_to_json` + `feasibility_analyzer` |
| Пикап‑микс | `custom_game.balance()` собирает xv‑1 **вручную** | `MemberRankService.resolve(order=MIX_ORDER)`, `mix_balancer` C++ (`priority_for_role`) |
| Драфт | `DraftRosterService.load` → `for_tournament(include_deleted=True)` | `feasibility.build_feasibility_state`, `fit.FitPlayer`, `rules.resolve_pick_slot` → `covers()`, `ranks.slot_rank()` |
| Экспорт зарег. команд | `team_export/registered.py` | `rank_on(_slot_role(team_slot_code))` |
| Admin read | `tournament-service/.../serializers.py` | свой `is_flex` (см. F3) |
| Public read | `registration_build._reg_to_read` | итерирует `reg.roles` (DB), ранг — `rank_on` |
| Frontend | `RoleStep.tsx`, `draft-workspace-model.ts`, `pickup-lineup.ts`, `balance-editor-helpers.ts` | своя копия discomfort; `playerRoles` расширяет flex до 3 ролей |

### 1.4 Семантика `flex` по слоям

| Слой | Что значит `flex` | Как считается ранг |
|---|---|---|
| Регистрация | `is_flex_computed`: >1 роли, все primary | — |
| Форма | `mode=forced` ⇒ все роли primary на записи | — |
| `PlayerRoster` | `is_full_flex` (из ORM); `covers(flex)` = `is_draftable` | `rank_on(None)` = `best_rank` |
| `RosterShape` | код **слота** «любая роль» | — |
| Балансер (`player_loader`) | псевдо‑роль в `ratings`/`preferences`, если `flex` в маске | `ratings["flex"] = max(ratings)` — включая роли **вне** маски |
| Балансер (`Player.is_flex`) | `isFullFlex` ⇒ discomfort 0 на всех `ratings` | — |
| Mix (`priority_for_role`) | `is_flex` ⇒ max priority везде | — |
| Драфт | слот `flex` в feasibility (spill); `slot_rank(role=None)` для role‑less shape | `best_rank` |
| Frontend draft | `is_flex` ⇒ можно пикнуть на любую из 3 ролей | — |

Четыре несовместимых определения одного слова — корень большинства находок ниже.

---

## 2. Находки

Формат: **ID. [severity] заголовок** — файл:строка — суть — сценарий.

### HIGH

**F1. [HIGH] Flex‑слот в маске ломает off‑role и feasibility для всех игроков**
`balancer-service/src/domain/balancer/player_loader.py:55-65`. При `FLEX_SLOT_CODE in mask`
каждому игроку (не только `is_flex`) ставится `preferences = ["flex", ...]`.
- `result_serializer.py:73`: `player.preferences[0] != role` → игрок на своей primary‑роли `tank`
  считается off‑role.
- `feasibility_analyzer.py:84-86, 135-136`: `supply[tank|dps|support] = 0`, `structural_min_off_role`
  завышен, `off_role_above_minimum` бессмыслен.
Сценарий: shape `{tank:1, flex:4}` или `{tank:1,dps:2,support:2,flex:1}` → `off_role_rate ≈ 1.0`
при идеальной рассадке. Чистый all‑flex shape не задет (все слоты `flex`).
Корень: «flex‑слот» закодирован псевдо‑ролью в том же списке, что и реальные роли.

**F2. [HIGH] Порядок вторичных ролей в `all_roles`/`forced` — из `HERO_TYPE_CLASSES`, не от игрока**
`shared/services/roster.py:_declared_roles` (`ordered = (lead, *(r for r in HERO_TYPE_CLASSES if r is not lead))`).
Регистрант support(0, primary) → dps(1) → tank(2); движок выдаёт support, **tank(1), dps(2)**.
Docstring `all_roles` обещает «registrant still names a priority». Уходит в `balancer_input.priority`
→ `Player.discomfort_map` инвертирован. `tests/test_draft_forced_flex.py:328` признаёт это как
«row order the registrant never expressed», но не считает багом.

**F3. [HIGH] Admin `is_flex` без `len > 1`**
`tournament-service/src/services/registration/serializers.py:113`:
`is_flex=bool(sorted_roles) and all(role.is_primary ...)`. Любая одноролевая регистрация = flex в
админке. Третья реализация предиката; две другие (`is_flex_computed`, `validation._is_flex_submission`)
имеют `len > 1`.

**F4. [HIGH] Валидация «additional role required» — тавтология**
`validation.py:385-391`: `not is_flex and not any(not is_primary)` ≡ `¬P ∧ P` для непустого списка.
Тумблер `additional_roles.required` не работает никогда.

**F5. [HIGH] `is_flex_computed` — сырые строки, без `is_active`, без `mode`, вне движка**
`shared/models/registration/registration.py:249-251` → `shared/services/roster.py:355`.
- a) optional: tank(primary, active) + dps(primary, **inactive**) → `is_full_flex=True` при одной
  играбельной роли → `isFullFlex` → `discomfort=0` в балансере, `FitPlayer.is_flex` в драфте.
- b) смена формы `optional → forced` не переписывает строки; контракт `PlayerRoster` (`roster.py:120`
  «under forced the write path makes this true for everybody») нарушен для всех ранних регистраций.
- c) `_common.replace_registration_roles:112-157` не связывает `is_primary` и `is_active`.
- d) `hybrid_property` без `.expression` — использование в запросе упадёт.

**F6. [HIGH] Frontend разрешает flex‑игроку любую роль, сервер — только `playable_roles`**
`frontend/src/lib/draft-workspace-model.ts:85-94` расширяет `is_flex` до tank/dps/support, ссылаясь на
несуществующий `rules.role_is_legal`. Сервер: `domain/draft/rules.py:363 roster.covers(requested)`
→ `wanted in playable_roles`, `is_flex` не учитывается. Full‑flex с рангами на 2 ролях → UI
предлагает третью → 422 `illegal_role`.

**F7. [HIGH] Исключённый из пула игрок остаётся драфтуемым**
`balancer-service/src/services/draft/rosters.py::DraftRosterService.load` —
`for_tournament(include_deleted=True)` без `pool_only`, без проверки `status`/`balancer_status`.
`build_feasibility_state`, `resolve_pick_slot`, autopick смотрят только на `playable_roles`. Бан во
время live‑драфта ничего не меняет для `available`‑мест.

### MEDIUM

**F8. [MED → не баг] Mix: `ALL_RANKED` игроки получают tank‑уклон**
`custom_game.py:597-607` — `role_order = REGISTRATION_ROLE_CODES`, priority 1/2/3 →
`backends/mix_balancer.py:priority_for_role` даёт support `max_priority-2`.
Снято при фиксе: UI пикапа (`pickup-lineup.ts:resolveRoleOrder`, `PickupPlayerSheet`) показывает
хосту ровно этот порядок как приоритет («position is the balancer's priority», первая роль
помечена primary) и даёт переключатель «Full flex» для «без предпочтений». Сервер и UI согласны;
менять только сервер — рассинхрон.

**F9. [MED] Rank = 0: драфт — играбелен, балансер — молча выбрасывает**
`roster.py:95 is_playable = rank is not None` vs `player_loader.py:33 if rank <= 0: continue`;
`team_export/registered.py:192 rank_on(role) or 0`. Игрок `ready` в пуле, но исчезает из
`run_balance` (или валит `No players can play required role`).

**F10. [MED] `parse_player_node` глотает любое исключение → игрок исчезает**
`player_loader.py:82-84`. `{"isActive": true, "rank": null}` → `TypeError` → warning → баланс
«успешен» без игрока.

**F11. [MED] Дефолт `HeroClass.damage`**
`roster.py:_declared_roles` (регистрация без строк в forced/all_roles → lead=damage, priority 0) и
`draft/rules.py:366`. То самое «rankless player labelled damage», которое docstring
`PlayerRoster.primary` объявляет исправленным.

**F12. [MED] Public read не видит синтезированные роли**
`registration_build.py:233-250` итерирует `reg.roles` (DB): в forced/all_roles публичная таблица
показывает 1 роль, движок и балансер работают с 3; `is_primary` — из строки, не из ростера.

**F13. [MED] Комментарий о направлении trim инвертирован**
`custom_game.py:566-568` «benches lowest rotation_priority»; `runtime.py:169-172` бенчит **хвост**
сортировки по возрастанию (highest). Код прав; комментарий провоцирует «фикс» с инверсией fairness.

**F14. [MED] Один неранжированный игрок → 422 на весь mix**
`custom_game.py:608-609`. Осознанно, но несимметрично с overflow‑trim, который бенчит поштучно.

### LOW

**F15.** `entities.py:72 Player.max_rating` = рейтинг `preferences[0]`: при flex в маске = max, без —
primary. Меняет выбор капитана (`captain_assignment_service.py:16`) и `assigned_rating` бенча в
зависимости от shape.
**F16.** `roster.py:66 flex_role_mode`: `enabled` проверяется только `is False`; `0`/`"false"` не выключают.
**F17.** `_declared_roles` optional: `'DPS'`/`'dps'` обходят unique‑constraint → две `RosterRole` одной
роли, `role_ranks` last‑wins.
**F18.** `frontend/src/lib/roles.ts:97 getRoleIconName('flex')` → Support (latent; все вызовы guarded).
**F19.** `feasibility_analyzer`/`result_serializer` используют `preferences[0]` как прокси «primary»
вместо явного поля — именно это делает F1 возможным.

### Дизайн‑риски (не баги, но проверить намерение)

- `roster.py:_build` non‑optional: роль без ранга наследует `best_rank` → tank‑only 3000
  балансируется как dps 3000 / support 3000. Плюс `forced ⇒ is_full_flex ⇒ discomfort 0` — второй
  objective солвера вырождается (`test_draft_forced_flex.py:230-233` это фиксирует).
- `player_loader:61 ratings["flex"] = max(ratings.values())` берёт максимум **по всем** ролям, включая
  те, которых нет в маске (например, dps в `{tank:1, flex:4}`). Для «любой роли» это верно; для
  hybrid‑shape с ограниченными ролями — спорно.
- `_max_ow_by_user` — максимум по всем аккаунтам пользователя (умышленно, docstring).
- Mix берёт глобальный `DivisionGrid` (`get_effective_division_grid(session, None)`) — умышленно,
  подтверждено `PickupPlayerSheet.behavior.test.tsx:218-222`.

### Проверено, багов нет

Спеллинг ролей по слоям (`dps` через `slot_code`, OW `damage→dps`); `pick_rank`; fallback на
собственный слой при чужом воркспейсе (`_resolve_ranks`); overflow‑trim в `runtime.py`;
`RatingNormalizer`; `find_feasible_role_assignment`; `resolve_input_role_name`; draft
`_remaining_capacity`/flex‑spill; `slot_rank` для role‑less shape; `FitPlayer.rank_for` (fallback
недостижим); `RoleStep.tsx` (forced/all_roles); `apply_all_roles`/`replace_registration_roles`
(приоритеты, дедуп); `DEFAULT_ROLE_IMPACT` = tournament_balancer; `WorkspaceMember.player_id` NOT NULL.

---

## 3. Оценка декомпозиции

### 3.1 Что сделано правильно

- **Один движок для «роли + ранг».** `RosterEngine` + `PlayerRoster` действительно заменили пять
  независимых предикатов (docstring `roster.py:1-23`); все read‑пути турнира (`_reg_to_read`,
  admin list, export, draft, balancer input) резолвят ранг через `rank_on`. Единственная хранимая
  производная — замороженный `DraftPick` — обоснована.
- **Слоистый резолвер рангов.** `pick_rank(layers)` с порядком от вызывающего
  (`TOURNAMENT_ORDER` / `MIX_ORDER`) — честная модель наследования «отсутствие строки = fall‑through».
- **`RosterShape` — чистый домен**, без I/O; `flex` как код слота отделён от `HeroClass.flex` как
  «нет роли».
- **Один словарь ролей** — `HeroClass` + `slot_code`; `dps` объявлен wire‑форматом, а не второй ролью.
- **Одна точка легальности пика** — `resolve_pick_slot` для select/autopick/override; один
  `slot_rank`; один `flex_role_mode`.
- **Тесты‑свидетели** (`TestDiscomfortDivergesFromTheBalancer`) честно фиксируют известные расхождения.

Ядро домена — уверенные 8/10.

### 3.2 Где декомпозиция протекает

Считаем **независимые реализации одного понятия** (каждая лишняя — будущее расхождение):

| Понятие | Реализаций | Где |
|---|---|---|
| «игрок — full flex» | **4** | `is_flex_computed` (ORM), `serializers.py:113`, `validation._is_flex_submission`, `validation.py:389` inline |
| discomfort роли | **5** | `entities.Player.discomfort_map`, `draft/fit.role_discomfort`, `mix_balancer.priority_for_role`, frontend `deriveRoleDiscomfort`, `tournament_balancer` (Rust) |
| «ранг flex‑слота» | **3** | `player_loader` (`max(ratings)`), `PlayerRoster.rank_on(None)`/`slot_rank`, `full_export.flex_rating` |
| role‑impact веса | **2** | `draft/entities.DEFAULT_ROLE_IMPACT`, `tournament_balancer` (pinned тестом) |
| сборка xv‑1 payload | **2** | `RosterEngine.balancer_input`, `custom_game.balance` вручную |
| «primary роль» игрока | **3** | `PlayerRoster.primary`, `preferences[0]` в балансере, `reg.roles[is_primary]` в `_reg_to_read` |
| легальность роли на пике | **2** | сервер `covers()`, фронт `playerRoles()` (расходятся, F6) |
| default‑роль при пустоте | **2** | `HeroClass.damage` в `_declared_roles` и `rules.py:366` |

Конкретные разломы:

1. **`is_full_flex` обходит движок.** `PlayerRoster` — value object домена, но одно его поле
   читается напрямую из ORM‑свойства по сырым строкам, игнорируя `mode` и `is_active`, которые
   `_build` уже держит в руках. Это единственное место, где «инвариант играбельности» не применён —
   и оно даёт F3/F5 и половину flex‑расхождений.
2. **Flex закодирован как псевдо‑роль в балансере.** `Player.ratings`/`preferences` — плоский список
   строк, и «слот без роли» добавлен в него хаком с комментарием на три абзаца. Все потребители
   (`result_serializer`, `feasibility_analyzer`, `captain_assignment`, `max_rating`) читают
   `preferences[0]` как «primary» и ломаются (F1, F15, F19). Правильная граница — явные поля
   `primary_role` / `flex_rating` на `Player`, а слот — отдельная сущность в `Team.roster`.
3. **Порядок ролей размазан.** `_declared_roles` в non‑optional режиме подменяет приоритет игрока
   порядком enum (F2); `custom_game.balance` подменяет «любая роль» порядком `REGISTRATION_ROLE_CODES`
   (F8); `HERO_TYPE_CLASSES` используется и как канонический список, и как дефолтное предпочтение.
   Домен не различает «нет предпочтения» и «предпочтение в каноническом порядке».
4. **Write‑path не нормализует.** `is_primary`/`is_active`/`priority` пишутся независимо, а
   `mode` формы применяется только в момент записи. Read‑side (`_declared_roles`) чинит это на лету,
   но не для `is_full_flex`, не для public read (F12) и не для валидации (F4). Смена `flex_role.mode`
   на живом турнире не имеет обработчика.
5. **Читатели за пределами движка снова ходят в `reg.roles`.** `_reg_to_read`, `serializers.py`,
   `validation.py` — три места, где контракт «никто не трогает строки напрямую» (`roster.py:19-21`)
   нарушен.
6. **Mix живёт отдельной жизнью.** `custom_game.balance` — вторая сборка xv‑1, свой резолв рангов,
   свой порядок ролей, свои 422. `MixRoleSelectionMode.ALL_RANKED` не отображается на
   `is_flex`/«без предпочтений», хотя семантически это одно и то же.
7. **`PlayerRoster` дрейфует в god‑object.** Поля `discord_nick`, `twitch_nick`, `checked_in`,
   `smurf_tags`, `custom_fields` «carried so a pool export is a full snapshot» — экспорт диктует
   форму доменного объекта. Пока безвредно, но это тот же паттерн, что породил пять предикатов до
   рефакторинга.
8. **Frontend хранит второй словарь и вторую логику.** Две параллельные семьи типов
   (`RoleCode`/`RosterRoleSlotCode` и `PlayerRoleOption`/`PlayerRoleSlotCode`), копия discomfort,
   собственная «легальность пика» (F6). Guard'ы `isRoleSlotCode` спасают сегодня, но по конвенции, не
   по типу.

Границы слоя — 5/10: ядро одно, но каждый потребитель на входе или выходе что‑то пересчитывает сам.

### 3.3 Порядок работ (как планировался)

Сначала корни, потом симптомы; каждый шаг убирает класс багов, не один баг.

1. `is_full_flex` считать в `_build` от `declared`/`mode`; удалить `is_flex_computed`; убрать копии
   предиката в `serializers.py`/`validation.py`. (F3, F5, F6)
2. Явная `Player.primary_role` в балансере; отчёты/feasibility/капитаны читают её. (F1, F15, F19)
3. `_declared_roles`: сохранять `priority` регистранта; убрать `HeroClass.damage` дефолт. (F2, F11)
4. Единый порог играбельности `rank > 0`; loader не глотает исключения. (F9, F10)
5. `DraftRosterService.load`: available‑места через `pool_only`. (F7)
6. Frontend: `playerRoles` из играбельных ролей сервера; `getRoleIconName(RoleCode)`. (F6, F18)
7. Однострочники: F4, F12, F13, F16, F17.

---

## 4. Что исправлено (2026-09-10)

| ID | Статус | Где | Что сделано |
|---|---|---|---|
| F1 | fixed | `entities.Player.primary_role`; `result_serializer._is_off_role`; `feasibility_analyzer` | Wire‑кодировка для солвера (`preferences=[flex, …]`, читается Rust‑ядром) оставлена; всё, что означает «главная роль» (off‑role, supply, matching, капитан, `max_rating`) читает `primary_role` = первая не‑flex роль. Flex‑слот никогда не off‑role; в matching каждый non‑flex игрок eligible на свою главную роль **и** на flex‑слоты. |
| F2 | fixed | `roster.py:_declared_roles` | non‑optional: строки в порядке регистранта (primary первой, затем `priority`), синтезированные роли — хвостом в каноническом порядке. |
| F3 | fixed | `tournament-service/serializers.py` | `is_flex` = `roster.is_full_flex`; без ростера — `is_flex_submission` (бывший `_is_flex_submission`, сделан публичным). Третья копия удалена. |
| F4 | fixed | `validation.py` | `covers_additional = is_flex_submission(roles) or any(not is_primary)`; тест `AdditionalRolesRequiredTests`. |
| F5 | fixed | `roster.py:_build`; ORM | `is_full_flex` считается движком: >1 играбельной **объявленной** (из строк) роли, все primary; `forced` ⇒ True при >1 играбельной. `BalancerRegistration.is_flex_computed` удалён. |
| F6 | fixed | `frontend/src/lib/draft-workspace-model.ts` | `playerRoles` = `[primary_role, …secondary_roles]` (= `playable` сервера); расширение по `is_flex` и ссылка на несуществующий `rules.role_is_legal` удалены. |
| F7 | fixed | `services/draft/rosters.py` | `load`: available‑места → `for_tournament(pool_only=True)`, picked/removed → `include_deleted=True`. Regression‑тест в `test_draft_integration.py` (требует Postgres). |
| F9 | fixed | `domain/roster.py:RosterRole.is_playable` | `rank > 0` — тот же порог, что у `player_loader`. |
| F10 | fixed | `player_loader.parse_player_node` | `rank: null` → unranked; любое другое исключение → `ValueError("Failed to parse player <uuid>")` → 422, игрок не исчезает молча. |
| F11 | fixed | `roster.py:_declared_roles`, `draft/rules.py:resolve_pick_slot` | Дефолт `HeroClass.damage` убран в обоих местах: пустая регистрация — без lead; в пике `primary is None` → `player_unranked`. |
| F12 | fixed | `registration_build._reg_to_read`, `_public_rosters` | При наличии ростера роли строятся из `roster.roles` (синтезированные видны). `_public_rosters` резолвит всегда (`show_ranks` гейтит только печать числа). |
| F13 | fixed | `custom_game.py` | Комментарий о направлении trim исправлен. |
| F15 | fixed | `entities.Player.max_rating` | Рейтинг на `primary_role` независимо от наличия flex‑слота в маске. |
| F16 | fixed | `domain/roster.py:flex_role_mode` | `enabled` ∈ {`false`, `"false"`, `0`, `"0"`} выключает. |
| F17 | fixed | `roster.py:_declared_roles` | Дедуп по распарсенному `HeroClass` в обоих режимах. |
| F18 | fixed | `frontend/src/lib/roles.ts` | `getRoleIconName(roleCode: RoleCode)`, fallback удалён; `RoleMatrixRow` типизирован. |
| F19 | fixed | вместе с F1 | `preferences[0]` больше не используется как «primary». |
| F8 | не баг | — | см. §2 F8: UI и сервер согласованы. |
| F14 | оставлено | `custom_game.balance` | Осознанное поведение (422 на весь mix при неранжированном игроке). |

Не тронуто (осознанно): Rust `tournament_balancer` — читает `preferences`/`is_flex` как раньше;
`_recompute_variant_stats` (mix, flex‑слотов нет); `PlayerRoster` как снапшот экспорта (§3.2 п.7).

### Проверка

- `backend/shared`: 987 passed, 12 skipped.
- `backend/balancer-service`: полный прогон зелёный до `test_registered_export_integration.py`
  (ждёт Postgres, локально недоступен); хвост прогнан отдельно — 92 passed, 9 skipped.
- `backend/tournament-service`: 1390 passed, 50 skipped.
- Throwaway smoke (удалён): hybrid mask `{1,2,2,flex:1}` — tank‑main на tank даёт `off_role_count=0`,
  на dps — 1; `structural_min_off_role` = слоты − matched по главным ролям + flex; `rank: null`
  → пропуск роли, мусорный узел → `ValueError` с uuid; `all_roles` сохраняет порядок
  support→dps→tank; optional tank(primary)+dps(primary, inactive) → `is_full_flex=False`;
  forced с одной строкой → 3 играбельные, `is_full_flex=True`; пустая регистрация → `primary is None`;
  rank 0 → не draftable.
- Frontend: `draft-workspace-model.test.ts` 15 passed; `PlayerInspector.behavior.test.tsx` 6 pass;
  `tsc --noEmit` — без новых диагностик в `src/`.

После правок таблица §3.2: «full flex» — 1 реализация (`RosterEngine._build`); «primary роль» в
балансере — 1 (`Player.primary_role`); «легальность пика» — сервер единственный источник.
Discomfort остаётся в 5 копиях (Python/draft/mix/frontend/Rust) — это следующий кандидат.
