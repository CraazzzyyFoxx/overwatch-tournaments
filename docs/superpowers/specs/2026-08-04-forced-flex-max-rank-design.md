# Forced-Flex турниры и макс-ранг для баланса — Design

**Статус:** дизайн согласован, к имплементации не приступали.
**Дата:** 2026-08-04
**Скоуп:** форма регистрации, балансер (чтение), драфт (чтение).

---

## Understanding Summary

- **Что строим.** Режим турнира «все игроки всегда флексы»: новое значение
  `built_in_fields.flex_role.mode: "optional" | "forced"` в конфиге формы
  регистрации. В forced-режиме форма не спрашивает приоритет ролей, все роли
  уходят как `is_primary`, и сила игрока для баланса и драфта считается как
  **максимальный ранг по всем его ролям**, применённый ко всем трём роям.
- **Зачем.** Планируется турнир, где роль игрока не имеет значения. Сегодня это
  невыразимо: право играть роль в балансере определяется наличием ранга именно
  на этой роли, а не флагом флекса, поэтому игрок с рангом только на DPS
  физически не может быть поставлен танком.
- **Для кого.** Организатор (конфиг формы, балансер, драфт) и игрок
  (упрощённый шаг ролей без выбора приоритетов).
- **Ключевые ограничения.** Payload балансера собирается фронтендом и
  загружается файлом; страница балансера сейчас не читает конфиг формы;
  balancer-service никогда не читал `BalancerRegistrationForm`; автозаполнение
  рангов пишет по-ролевые значения, поэтому сплющивание в БД нежизнеспособно.
- **Не-цели.** Не меняем поведение турниров с добровольным флексом; не
  устраняем расхождение семантики флекса драфт↔балансер в `optional`; не
  трогаем Rust-ядро `tournament_balancer`; не вводим новых колонок в БД; не меняем
  `is_flex_computed`.

## Допущения

1. В forced-режиме `is_active = false` у роли **игнорируется** — все три роли
   становятся играбельными с эффективным рангом. Источник максимума — любая
   роль с непустым `rank_value`, независимо от `is_active`.
2. Игрок исключается из пула только если рангов нет вообще (текущее правило
   `playerHasRankedRole`).
3. Чтение режима **fail-closed**: недоступен конфиг формы → считаем `optional`.
   Лучше не сплющить ранги, чем неожиданно их раздуть.
4. Нагрузка: +1 запрос на загрузку страницы балансера, +1 на сид драфта,
   сплющивание O(игроков). Пул ограничен `max_players` подписки.
5. Новых поверхностей доступа нет: конфиг формы уже читается админом и уже
   отдаётся публичному read формы целиком.

---

## Текущее состояние (что выяснено в коде)

### Флекс уже существует, но только как выбор игрока

| Место | Факт |
|---|---|
| `backend/shared/models/registration/registration.py:200` | `is_flex_computed` — hybrid property, не колонка: `len(roles) > 1 and all(is_primary)`. Хранимую `is_flex` дропнули в `purge0001`. |
| `frontend/src/components/balancer/form/_components/formConfig.ts:92` | Встроенное поле `flex_role`, `defaultEnabled: true`, `supportsRequired: false`. |
| `frontend/src/components/registration/RoleStep.tsx:156-172` | Кнопка-пресет «Играю на любой роли» ставит всем ролям `priority: "main"`. |
| `backend/tournament-service/src/services/registration/validation.py:404-406` | Бэкенд умеет только **запретить** флекс при `flex_role.enabled = false`. Режима «принудительно» нет. |

### Балансер: флаг флекса не даёт права играть роль

```
AdminRegistration
  → createSyntheticPlayerFromRegistration   (workspace-helpers.ts:445)
  → buildBalancerInput                      (workspace-helpers.ts:386)
  → JSON-файл                               (balancer.service.ts:137)
  → parse_player_data                       (request_parser.py:17)
  → parse_player_node                       (player_loader.py:11)
  → Player                                  (entities.py:6)
  → Context                                 (context.rs:79)
```

- `player_loader.py:27-35`: роль попадает в `ratings` только при
  `isActive && rank > 0`.
- `context.rs:100`: `can_play[role] = ratings.contains_key(role)`.
- `context.rs:105`: `is_flex` лишь **обнуляет discomfort** для ролей, которые
  игрок уже может играть.

Отсюда и вывод: сплющивание рангов до максимума одновременно решает
eligibility и силу, не требуя правок ядра.

### Драфт: другая семантика флекса

- `selection.py:288-290`, `draft.py:420-422`: для флекса
  `playable_roles = frozenset(DraftRole)` — **без** требования ранга на роль.
- `suggestions.py:38`: `rank_for(role) = role_ranks.get(role, rank_value)`.
- `lifecycle.py:455`: `rank_value = primary.rank_value or max(ranks)` — берёт
  ранг primary, даже если другая роль выше.

### Запись ролей: ДВЕ воронки, не одна

| Путь | Функция | Вызовы |
|---|---|---|
| Публичная заявка | `build_registration_roles` (`service.py:113-151`) | `service.py:695` |
| Админка + Google Sheets | `replace_registration_roles` (`_common.py:121`) | `lifecycle.py:220,320`, `sheet_sync.py:426,575` |

Докстринг `build_registration_roles` прямо называет себя зеркалом админского
пути («mirroring the admin write path»), но это две независимые функции.
Нормализация forced-flex нужна в обеих.

**Значения `is_active` по путям** (модельный default — `True`,
`registration.py:220`):

- публичный путь `is_active` не задаёт вовсе → **`True`**, при `rank_value = NULL`
  (публичная форма ранги не отправляет, `UnifiedRegistrationForm.tsx:451-460`);
- админский/Sheets путь задаёт явно:
  `is_active = bool(role.get("is_active", rank_value is not None))`
  (`_common.py:147`). Админка всегда присылает `is_active: true`
  (`UnifiedRegistrationForm.tsx:532`); Sheets-синк — только если ранг распарсился,
  иначе роль приходит с `is_active = False`.

Отсюда: игнорировать `is_active` в forced-режиме нужно ради **Sheets-пути**, где
роль без распарсенного ранга становится неактивной. Публичные заявки активны
сразу, просто без рангов.

### Последствия all-flex для MOO

`objectives.rs:384-387`:

```
comfort = avg_discomfort·w
        + global_max_pain·w
        + avg_team_max_pain·w
        + avg_subrole_collisions·w
```

При all-flex первые три члена = 0 — остаётся только коллизия сабролей.

- NaN не будет: `normalize_objectives` страхует нулевой размах через
  `.max(1e-6)` (`objectives.rs:554-555`).
- Фронт Парето сжимается: варианты станут почти одинаковыми,
  `rank_comfort_tilt` управляет только сабролями, `structural_min_off_role` и
  счётчики off-role всегда 0 (`result_serializer.py:72`, `feasibility_analyzer.py`).
- При плоских рейтингах перестановка ролей не влияет на balance — задача
  сводится к разбиению N чисел на k групп, поиск может рано выйти на плато.

**Поэтому саброли в forced-режиме сохраняются** — иначе второй объектив
умирает полностью и MOO становится однокритериальным.

---

## Decision Log

### D1. Переключатель живёт в конфиге формы регистрации

`built_in_fields.flex_role.mode: "optional" | "forced"`, отсутствие ключа и
`None` = `optional`.

Альтернативы: отдельный флаг турнира в `balancer.tournament_config.config_json`;
две ручки (форма для UI + конфиг балансера для политики рангов).

Почему так: forced-режим — это в первую очередь свойство формы. Поскольку он
делает все роли primary, `is_flex_computed` становится истинным автоматически —
новых колонок в БД и плумбинга флекса вниз по течению не требуется.
Отдельный флаг турнира пришлось бы синхронизировать с формой, а рассинхрон
дал бы турнир, где форма спрашивает приоритеты, а балансер их игнорирует.

### D2. Макс-ранг применяется только к forced-турнирам

Альтернативы: к любому `is_flex` игроку везде; отдельная ортогональная опция
`flex_rank_mode: primary | max`.

Почему так: ноль регрессий для существующих и текущих турниров с добровольным
флексом. Ортогональная опция дала бы комбинаторику режимов без спроса на неё.

### D3. Подход A — производные эффективные ранги на двух границах чтения

Альтернативы:

- **B.** Перенести сборку payload балансера на бэкенд (`serialize_registration_for_export`
  уже умеет строить xv-1 на сервере, `export.py:33`), сделать джоб «по
  `tournament_id`». Одна точка истины структурно, попутно уходит 25 МБ
  base64-аплоада (`rpc/jobs.py:58-62`). Отклонено сейчас как кратно больший
  скоуп: рефакторинг контракта джоба, API-ключей, лимитов игроков и публичного
  API балансера. **Зафиксировано как следующий шаг** (см. ниже).
- **C.** Политика внутри солвера через `config_overrides` + сплющивание в
  `player_loader`. Отклонено: не решает драфт (драфт не проходит через солвер),
  требует зеркалить режим формы в конфиг турнира, и таблица пула не покажет
  сплющенные ранги.

Почему A: минимальный скоуп, Rust и Python-солвер не трогаются, все решения
D1/D2/D4/D5 удовлетворяются. Плата — дубль логики TS/Python под паритет-тестом.

### D4. Разделение слоёв: роли нормализуются при записи, ранги производны при чтении

Forced-flex — факт о **ролях**: дешёвый, стабильный, без потери данных →
нормализуется при записи общим хелпером, который вызывают оба пути записи
(`build_registration_roles` и `replace_registration_roles`).
Макс-ранг — **политика** о рангах: производная и обратимая → вычисляется на
чтении.

Почему не сплющивать ранги в БД: публичная форма ранги не присылает вовсе, а
автозаполнение (`rank_autofill.py`) пишет по-ролевые значения и перезаписало бы
сплющенные. Плюс переключение режима обратно должно быть неразрушающим.

Почему нормализация ролей, а не реджект не-флекс payload: нормализация сильнее.
Она покрывает устаревший клиент, админку, API-ключи и Google Sheets синк, который
про режим ничего не знает.

### D5. Таблица пула показывает сплющенные ранги (WYSIWYG)

Альтернативы: показывать реальные, сплющивать только в payload; реальные плюс
отдельная колонка «эффективный ранг».

Почему так: сплющивание в `buildBalancerPageCollections` — одна точка вставки на
всю страницу, таблица/валидация/payload видят одно и то же. Реальные по-ролевые
ранги остаются доступны в редакторе заявки.

### D6. `ow_rank_value` несёт роль-источник, а не все три

`computeRankDeltasByRole` (`workspace-helpers.ts:274`) сравнивает `rank_value` с
`ow_rank_value` по каждой роли. Сплющивание только `rank_value` дало бы три
ложных `rank_delta_warning`, а `readyPlayers` фильтрует `issues.length === 0`, и
`runBalanceMutation` (`useBalancerMutations.ts:414`) отказывается запускаться при
непустых `invalidPlayerStates` — то есть **наивный вариант сломал бы запуск
баланса**.

**Решение исправлено при имплементации.** Первоначальный вариант —
`effOwRank = max(ow_rank_value)` на все три роли — при проверке оказался неверен:
сплющивание уравнивает delta, но **не сворачивает три строки**, поэтому
`getPlayerValidationIssues` выдавал одну и ту же плашку трижды.

Финальный вариант: `effOwRank = max(ow_rank_value)` присваивается **только той
роли, которая его дала**, на остальных двух остаётся `null`.
`computeRankDeltasByRole` требует оба значения (`:276`), поэтому получается ровно
одна плашка с осмысленным числом на информативной роли.

Отклонено: оставить `ow_rank_value` по-ролевым — тогда эффективный ранг
сравнивается с OW-рангом чужой роли и даёт ложную плашку. Отклонено: отключить
проверку в forced-режиме — теряется защита от заведомо неверных рангов.

### D7. Драфт применяет политику в `_map_registration` при сиде

Альтернатива: `FitPlayer.rank_for` возвращает `max(rank_by_role)` при forced —
реагирует на переключение режима на лету, но требует протаскивать флаг в каждый
вызов скоринга и в UI-отображение рангов.

Почему так: одна точка, а `_build_role_rows` (`lifecycle.py:132-167`) уже берёт
объединение primary + secondaries + ролей с рангом, поэтому три строки
`draft_player_role` создаются сами, включая капитанов, которым `secondary_roles`
передаётся пустым (`lifecycle.py:317`). Правок ниже по течению нет.

Принятое следствие: состояние сессии замораживается на момент сида —
переключение `flex_role.mode` после старта драфта его не пересчитывает.

### D8. Расхождение драфт↔балансер в `optional` остаётся

В `optional` драфт разрешает флекс-игроку роль без ранга, балансер — нет.
Расхождение существующее, в проде на него не жаловались. Закрывать его —
поведенческая правка в живых турнирах и отдельный риск. Оставлено как известный
долг.

---

## Финальный дизайн

### 1. Контракт и запись

**Схема.** `BuiltInFieldConfig` (`backend/tournament-service/src/schemas/registration.py:33`)
получает `mode: Literal["optional","forced"] | None = None` — значимо только для
ключа `flex_role`, по образцу уже существующих полей «только для одного поля»
`max_heroes` и `require_verified`. Зеркало в
`frontend/src/types/registration.types.ts:18`. Публичный read формы отдаёт
`built_in_fields` целиком, поэтому до формы игрока `mode` доезжает без правок
эндпоинта.

**Нормализация при записи.** Общий хелпер
`apply_forced_flex(entries) -> list[BalancerRegistrationRole]` в `_common.py`:
ставит `is_primary = True` каждой роли и досоздаёт отсутствующие роли из
`{tank, dps, support}` пустыми строками. `is_active` **не трогается** — остаётся
как его выставил конкретный путь записи.

Вызывается из обеих воронок под флагом `forced_flex: bool = False`:

- `build_registration_roles` (`service.py:113`) — публичная заявка. Форма уже
  загружена вызывающим (`service.py:663`), флаг выводится из неё.
- `replace_registration_roles` (`_common.py:121`) — админка (`lifecycle.py:220,320`,
  форма резолвится выше через `_resolve_top_heroes_config`,
  `registration_build.py:76`) и Google Sheets (`sheet_sync.py:426,575`).
  **`sheet_sync` конфиг формы сейчас не читает вообще** — ему нужен новый
  `get_registration_form(session, tournament_id)`; `tournament_id` в скоупе есть.

Результат: `is_flex_computed` истинно для любой заявки forced-турнира независимо
от источника.

**Валидация.** `validation.py:404-406` остаётся как есть. Новых проверок нет —
см. D4.

**Админ-UI конфига.** `BuiltInFieldDef` (`formConfig.ts:11`) получает
`supportsMode?: boolean`, выставленный только для `flex_role` (`:92`).
В `BuiltInFieldsCard` (`:82`) правый слот строки у `flex_role` свободен, потому
что у поля `supportsRequired: false` — там рендерится Select из двух значений
`опциональный / принудительный` под условием `def.supportsMode && cfg.enabled`.
Хендлер главного Switch сбрасывает `mode` вместе с `required` при выключении
поля (шаблон `:58`), поэтому противоречивое `enabled: false, mode: forced`
недостижимо через UI, а бэкенд читает `mode` только при `enabled`.

**Побочный эффект для сабролей.** `getSubroleOptions(form, roleCode, priority === "main" ? "primary_role" : "additional_roles")`
(`RoleStep.tsx:71-72`): в forced-режиме все роли `main`, поэтому allowlist
сабролей всегда берётся из `primary_role`, а настройка сабролей у
`additional_roles` перестаёт влиять на что-либо. Организатору это стоит показать
в описании режима.

### 2. Форма регистрации

- `createRoleSelections(forced = false)` (`types.ts:35`) при `forced` возвращает
  `main` для всех трёх ролей вместо `off`. Обязательно: `orderedActiveRoles`
  фильтрует `priority !== "off"` (`UnifiedRegistrationForm.tsx:444`), иначе
  улетит `roles: undefined`.
- `RoleStep`: проп `flexEnabled: boolean` → `flexMode: "off" | "optional" | "forced"`.
  При `forced` колонка «Приоритет» и кнопка-пресет не рендерятся, `columnClass`
  (`RoleStep.tsx:141`) теряет один трек, `setPriority` недостижим. `setSubrole`
  и `setHeroes` только повышают приоритет, поэтому `off` недостижим в принципе —
  инвариант держится без дополнительных проверок. `normalize()`
  (`RoleStep.tsx:79`) при `forced` — тождественная функция.
- Хелпер-текст меняется на объяснение режима.
- Если у forced-турнира выключены и саброли, и топ-герои, шаг ролей нечего
  показывать → он выпадает из `STEPS` (`UnifiedRegistrationForm.tsx:182`), а роли
  досоздаются нормализацией на бэкенде.
- Админ-редактор правок не требует: `is_primary → "main"`
  (`UnifiedRegistrationForm.tsx:234-259`), поля ранга остаются.

### 3. Балансер (чтение)

`buildBalancerPageCollections(registrations, divisionGrid, forcedFlex)`
(`balancer-page-selectors.ts:33`) — единственная точка вставки.
`BalancerMainPageClient` добавляет query конфига формы по образцу
`RegistrationsTable.tsx:324`; `forcedFlex = built_in_fields?.flex_role?.mode === "forced"`,
при ошибке или `undefined` → `false`.

Сплющивание в `createSyntheticPlayerFromRegistration` (`workspace-helpers.ts:445`):

```
effRank   = max(rank_value)      по ролям с rank_value != null
effOwRank = max(ow_rank_value)   по ролям с ow_rank_value != null
```

`role_entries_json` собирается на все три роли:
`rank_value = effRank`, `ow_rank_value = effOwRank` **только на роли-источнике**,
`is_active = effRank != null`,
`division_number = resolveDivisionFromRank(effRank, grid)`,
`subtype` и `priority` — из исходной роли.

Дальше по течению правок нет:

- `playerHasRankedRole` (`:107`) → true при наличии хоть одного ранга.
- `roleSequencesMatch` (`:234`) проходит: `left` = все три роли, `right` для
  флекс-заявки тоже все три (`createSyntheticApplicationFromRegistration:482`).
- `buildBalancerInput` (`:386`) отдаёт `isActive: true, rank: effRank` на все три
  класса → три ключа в `ratings` → `can_play` истинно везде, discomfort нулевой.

**Python-солвер и Rust-ядро не изменяются.**

### 4. Драфт (чтение)

`seed_from_pool` (`lifecycle.py:567`) грузит `BalancerRegistrationForm` по
`tournament_id` — первое обращение balancer-service к этой модели; модель
шарится (`shared.models.registration.registration`), запрос один на сид.

`_map_registration(reg, *, forced_flex: bool = False)` при `forced_flex`:

- набор ролей = все три `{tank, dps, support}`, **без фильтра по `is_active`**
  (нужно ради Sheets-заявок: роль без распарсенного ранга приходит с
  `is_active = False`, `_common.py:147`);
- `effRank = max(r.rank_value for r in reg.roles if r.rank_value is not None)`,
  иначе `None`;
- `rank_value = effRank` (вместо `primary.rank_value or max(ranks)`,
  `lifecycle.py:455`);
- `role_ranks = {role: effRank for role in all_three}` при `effRank != None`,
  иначе `{}` — **пересмотрено 2026-08-12, см. ревизию ниже**;
- `primary_role` = первая роль по `priority`, `secondary_roles` = остальные две —
  на скоринг не влияет (`selection.py:288`), но держит данные консистентными;
- `sub_role` — из primary-строки, без изменений.

Оба вызова внутри `seed_from_pool` (`:599` капитаны, `:634` пул) получают один
флаг. `_build_role_rows` создаёт три строки сам.

**Ревизия 2026-08-12.** `role_ranks` больше не затирает ранг, который заявитель
указал на роли: `role_ranks = {role: заявленный_ранг_роли или effRank}`. Причина —
драфт **показывает** это число: чузер роли в Player Inspector рисует ранг на
каждой из трёх ролей, и плоский каталог превращал панель в одно значение,
напечатанное трижды (капитан пикал на рейтинг, которого у игрока на этой роли
нет). Всё, ради чего вводилось расплющивание, сохранено: каждая играбельная роль
по-прежнему **несёт** рейтинг (допуск в балансере — это `role in ratings`), а
сила игрока `rank_value` по-прежнему `effRank`. Незаявленные роли получают
`effRank` — единственное доступное для них значение. Итоговый ранг пика, ростер и
экспорт берут максимум через `services.draft.ranks.slot_rank`, так что политика
«роль не важна → сила = максимум» не изменилась ни в одной точке записи.
Пул балансера (`flattenRolesToMaxRank`) остаётся плоским: расхождение
намеренное и прибито в `tests/test_forced_flex_parity.py`.

Ниже по течению: `suggestions.rank_for` (`:38`) вернёт `effRank` для любой роли,
`feasibility.py:133` уже отдаёт все роли для флекса, `order_captain_ids` (`:602`)
получит эффективный ранг.

---

## Краевые случаи

| Случай | Поведение |
|---|---|
| Рангов нет ни на одной роли | `effRank = null` → `is_active = false` на всех ролях → `missing_ranked_role`, игрок вне пула. |
| Ранг только на одной роли | `effRank` = он же, применяется ко всем трём. Целевой случай. |
| Роль неактивна (Sheets без ранга или снято админом) | В forced-режиме игнорируется (допущение №1). |
| `ow_rank_value` есть, `rank_value` нет | `effRank = null`, delta не считается (`:276` требует оба). |
| Переключение `forced → optional` | Хранимые ранги целы, пересчёт страницы вернёт по-ролевые значения. Начатый драфт не пересчитывается (D7). |
| Заявка из Google Sheets | Нормализация делает её флекс-заявкой, ранги сплющиваются на чтении. |
| Автозаполнение рангов | Пишет по-ролевые ранги как раньше, конфликта нет (D4). |

## Ожидаемая телеметрия forced-турниров

`total_discomfort = 0`, `off_role_count = 0`, `structural_min_off_role = 0`,
дисперсия рейтингов близка к нулю, число различимых вариантов резко падает.
Это норма режима, а не регресс в солвере.

## План тестов

- `_common.py` / `service.py`: `apply_forced_flex` ставит `is_primary` всем ролям
  и досоздаёт отсутствующие; `is_active` не тронут; вызов срабатывает на обоих
  путях записи (публичный `submit_registration` и админский `create/update`).
- `sheet_sync.py`: forced-турнир нормализует заявку из таблицы (новый read формы).
- `workspace-helpers.test.ts` (правка `:413-415`): сплющивание `rank_value` и
  `ow_rank_value`; одна плашка delta вместо трёх; `is_active` при `effRank = null`.
- `RoleStep.behavior.test.tsx` (правка `:173-182`): в `forced` контрола
  приоритета нет, все три роли `main`, саброля и герои работают, `off`
  недостижим.
- `test_registration_role_validation.py` (рядом с `:257-282`): forced-турнир
  принимает и нормализует не-флекс payload.
- `test_draft_integration.py`: сид forced-турнира даёт три `draft_player_role` с
  одинаковым `effRank`; `rank_value` = max, а не ранг primary.
- **Паритет-тест** (обязателен, цена подхода A): один набор
  `(role, rank_value, ow_rank_value)` даёт идентичный `effRank`/`effOwRank` в
  TS-хелпере и в `_map_registration`. Фикстуры в общем JSON, по тесту с каждой
  стороны. Прецедент документированного зеркалирования в репо есть —
  `role_discomfort` (`suggestions.py:59`).

### Инфраструктура тестов (проверено запуском)

Во фронтенде **два раннера**, и это влияет на то, куда писать тест:

| Раннер | Команда | Файлы этой задачи |
|---|---|---|
| bun | `cd frontend && bun test <файл>` | `workspace-helpers.test.ts` (свой самописный харнесс), `RoleStep.behavior.test.tsx` (`import ... from "bun:test"`) |
| vitest | `cd frontend && bunx vitest run <файл>` | `balancer-page-selectors.test.ts` и остальные из allowlist |

`vitest.config.ts:19-63` — это **allowlist**: файл вне него никогда не запустится,
а suite всё равно отрапортует зелёным (комментарий на `:30-32` предупреждает
именно об этом). Любой новый vitest-тест обязан быть добавлен в `include`.
Каталог `src/components/registration/` перечислен **по файлам**, а не глобом,
именно потому что содержит тесты обоих раннеров (`:58-62`).

Пакетный менеджер — bun (`frontend/bun.lock`, pnpm-lock отсутствует), поэтому
`pnpm exec` из плана `2026-06-12-balancer-rank-comfort-tilt.md` больше не
применим: `bunx tsc --noEmit`, `bunx eslint <path>`.

Бэкенд: `cd backend/<service> && uv run pytest <файл>`.

## Известный долг

1. **Дубль логики сплющивания TS/Python.** Закрывается подходом B: перенести
   сборку payload балансера на бэкенд (`serialize_registration_for_export`,
   `export.py:33`), сменить контракт джоба с `player_data_file` на
   `tournament_id` (`rpc/jobs.py:58`, `jobs.create_job:126`). Попутно уходит
   25 МБ base64-аплоада и появляется структурный паритет с драфтом. Затрагивает
   API-ключи, лимиты игроков и публичный API балансера — отдельная задача.
2. **Расхождение семантики флекса драфт↔балансер в `optional`** (D8).
3. **Состояние драфт-сессии не реагирует на переключение режима после сида** (D7).
