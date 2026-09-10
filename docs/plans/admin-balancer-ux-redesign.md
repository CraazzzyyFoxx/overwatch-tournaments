# Дизайн v3.1 (APPROVED): редизайн UX админки и балансера + tournament wizard

> Дата: 2026-07-28. Статус: **APPROVED** — дельта-ревью пройдено (SkepticDelta, GuardianDelta, AdvocateDelta: 1 blocker, 8 major, 9 minor — все разрешены, §9; АрбитрДельты: APPROVED с тремя формулировочными правками, внесены).
> История: v2 — APPROVED полным multi-agent review; v3 — пересмотр интеграции балансера по запросу стейкхолдера (без сайдбара); v3.1 — ревизии по дельта-ревью.
> Основа: инвентаризация `docs/plans/admin-balancer-ux-inventory.md`.
> Смежные доки: `docs/redesign-plan.md` (публичный сайт), `docs/design-book.md` (токены Editorial Tactical).
> **Фаза 1 — РЕАЛИЗОВАНА** (2026-07-29, ветка `feat/admin-balancer-ux-phase1`, 24 коммита). План: `docs/plans/2026-07-29-admin-balancer-ux-phase1.md`. Верификация: 203+ vitest, полный tsc, eslint (новые файлы чистые), production build, backend 19/19 целевых + full-suite паритет с develop, финальное spec+quality ревью (все находки исправлены).
> Зафиксированные отклонения реализации: (1) «Create now» оставляет турнир Unpublished — публикация осознанная через Review/Settings (безопаснее «эквивалента диалога», принято); (2) шаг 4 wizard'а — тумблеры информационные, применяются в form builder (PUT формы требует built_in_fields — авто-запись рисковала дефолтами; Review-шаг проговаривает это явно); (3) resume-детект без фильтра created_by (упрощение плана). **Перед деплоем**: миграционная проверка organizer-бандлов (D26) — роли, модерирующие регистрации, должны содержать tournament.read + team.read.

## Understanding Summary

- **Что**: реорганизация IA/UX админки и балансера вокруг жизненного цикла турнира + wizard создания + living checklist сопровождения. Упрощение **без потери функциональности**.
- **Для кого**: организаторы турниров (admin / tournament_organizer), ведущие цикл «создать → набрать → сбалансировать → провести → закрыть».
- **v3-принцип**: балансер — сугубо инструмент балансировки, без собственного shell/сайдбара; всё турнирно-скоупное живёт в турнирном хабе.
- **Ограничения**: текущий стек; опора на существующую state machine; backend меняем точечно (§7).
- **Не-цели**: публичный сайт, RBAC-модель (кроме политики бандлов, D26), алгоритм балансировки, i18n-стратегия.

## Assumptions

1. Кросс-турнирные страницы (Teams/Players/Encounters/Standings) остаются; демотируются в «Data browser».
2. Отдельным route-простором остаётся только инструмент балансировки (`/balancer`); registrations/form/autofill/feed — в хабе.
3. Визуальные токены design-book — последняя фаза.
4. Realtime-механика (топики, серверная часть) не меняется; клиентские подписки на существующие топики — допустимы. `useTournamentRealtime` — один маунт в layout хаба; хаб дополнительно подписывается на существующий топик `tournament:{id}:balancer` для refetch'а readiness (G-O6).
5. Серверная авторизация не меняется: registrations-эндпоинты гейтятся `team.*` и резолвят workspace из path-id независимо от расположения страниц и от инжектируемого `workspace_id` (проверено: `registration_admin.py`).
6. **Транспортный слой**: `apiFetch` авто-инжектит `workspace_id` из zustand-store во все вызовы → любой экран, работающий с турниром чужого workspace, обязан сначала выровнять store (механизм D29). Это факт кода, который дизайн обязан уважать (SK-O2).

## Финальный дизайн

### §1. Турнирный хаб `/admin/tournaments/[id]/{tab}`

#### §1.1 Каркас

- **Client-layout хаба** забирает из текущего page.tsx: header, Unauthorized-гейт, `useTournamentRealtime` (один маунт) + подписку на `tournament:{id}:balancer` (readiness-refetch), общие запросы с общими query-keys.
- **Гейт хаба — базовый `tournament.read`** (без изменений; ревизия D26 после blocker G-O1): центральный запрос layout'а (admin-get tournament) серверно требует `tournament.read` — «вход по одному team.read» невозможен без изменения серверной матрицы, что вне scope. `team.read` — **только сигнал видимости registration-вкладки**, НЕ дополнительный флаг входного гейта хаба. **Политика бандлов**: роль, модерирующая регистрации из хаба, должна включать `tournament.read` + `team.read`; бандлы настраиваются в Access→Roles; при внедрении — проверить существующие organizer-бандлы (миграционная заметка Фазы 1).
- **Route-guards per tab**: `settings` → `canUpdateTournament`; `stages` (veto) → `canUpdateEncounter`; `registration` → `team.read`; нет права = redirect на `overview` + скрытие таба.
- Императивные переключения → `router.push`; `/[id]` → redirect на `overview`.
- **URL-схема финальна с Фазы 1**: `overview | registration | teams | stages | matches | settings` (+ временные `draft`/`veto`/`logs`, ретирящиеся в Фазе 2 с постоянными redirect'ами).
- Per-tab запросы условны по pathname; dynamic-импорты по route-сегментам.

#### §1.2 Вкладки

| Вкладка | Содержимое |
|---|---|
| `overview` | Пайплайн-stepper по эффективной цепочке фаз (D19); TournamentStatusControl; **living checklist** (§3); метрики; сводка синков; баннер «Draft live → Teams» при live-драфте |
| `registration` | **Полноценная таблица регистраций** (перенос текущей `/balancer/registrations` целиком). Контекст: path-param; workspace-каталоги (статусы, саброли) — от workspace турнира (в хабе store уже выровнен по нему). Гейт `team.read`. **Sub-routes**: `registration/form`, `registration/rank-autofill`, `registration/feed`. Счётчики для checklist — readiness-endpoint (§7) |
| `teams` | Ручной CRUD всегда (substitutions). Mode-панель по `team_formation` (`balancer | draft`): *balancer* — готовность пула, saved balance, exported_at, **«Open balancer»**; *draft* — DraftSetupWizard / AdminControlRoom / Previous draft + бейдж «Draft live». Challonge team-sync. Импорт балансa из JSON живёт только в балансере («Load balance JSON»). Guard смены `team_formation` при активной draft-сессии (§7.4) |
| `stages` | StageManager (Фаза 1 as-is; Фаза 2 — декомпозиция) + Map Veto секцией |
| `matches` | Sub-tabs: Results · Logs |
| `settings` | Как сейчас + Integrations (Challonge); чекбокс `is_finished` удаляется (§7) |

Header: имя, статус, метрики, Analytics; «Mark as Finished» → superuser force-override state machine.

### §2. Wizard создания `/admin/tournaments/new`

| Шаг | Поля | Обязательность |
|---|---|---|
| 1. Basics | имя, тип, даты; Manual / From Challonge | **обязателен**; далее доступен **«Create now»** (эквивалент текущего диалога) |
| 2. Schedule | phase schedule, auto-transitions, late registration | опционален |
| 3. Rules | `team_formation` (balancer/draft), grid version, scoring | опционален |
| 4. Registration | приём, auto-approve, built-in поля | опционален; виден при `team.import`; полный form builder — **внутренняя ссылка** на `registration/form` хаба |
| 5. Review & Create | сводка + создание/публикация | — |

Черновик: лениво при первом действии, требующем id; «Unpublished»-бейдж в списке; resume-prompt; «New Tournament» продолжает существующий черновик; ActiveTournamentCard исключает `is_hidden`. Терминология: Unpublished / Draft phase / Team Draft. Create-диалог и edit-диалог списка удаляются; delete остаётся.

### §3. Living checklist (Overview)

Применимость (D22): предикаты на пункт; неприменимое скрыто/«—». Состояния: done / todo / warn / skipped / no-access.

| Фаза | Пункт | Применим когда |
|---|---|---|
| Setup | расписание · grid | всегда |
| Setup | форма · приём открыт | не «полностью Challonge-импорт» |
| Registration | approved (информационно, без порога) · ранги покрыты · check-in | check-in — при фазе в phase schedule |
| Formation | пул ready · balance сохранён · экспорт / драфт completed | по `team_formation` |
| Bracket | стадии · слоты · bracket · активация | всегда |
| Live | логи покрывают матчи | при ≥1 логе (иначе «Logs: not used») |
| Finish | completed | всегда; archived — опционально |

Данные: readiness-endpoint (§7.1), серверный гейт ANY(`tournament.read`, `team.read`), поля маскируются по правам вызывающего; «покрытие рангами» — по сохранённым rank-данным. Refetch: события `tournament:{id}:balancer` + `bracket` (существующие топики, клиентская подписка — A4) + window focus; FAT-списки вне поллинга.

### §4. Балансер = инструмент (v3.1)

- **`/balancer` — единственная страница**: пул / run / варианты / редактор / export. Сайдбар и switcher удаляются.
- **Shell инструмента — тонкий top-bar**, который обязан предоставить (SK-O4): (1) контейнер `#balancer-header-slot` — PresetRunPanel рендерит Run-контролы только через портал, без fallback; (2) хост для presence — `BalancerPresenceStack` переделывается: снимается зависимость `useSidebar()` (бросает вне SidebarProvider), рендер в top-bar; (3) «← Tournament hub» → **вкладка `teams` хаба** (источник «Open balancer»; A-O2); (4) имя турнира + статус; (5) кнопка **«Rank autofill»** → `registration/rank-autofill` хаба (замещает потерянную сайдбарную affordance; A-O3 — перенос существующего входа, не новая фича). Двух-вкладочный workflow (хаб-registration ‖ инструмент) поддержан: инвалидация пула по `balancer.registrations_changed` уже работает (проверено кодом).
- **Разрешение контекста (D29, замена «растворения» D18)**: контекст = `?tournament={id}`. Инструмент резолвит турнир через **balancer-summary endpoint** (§7.3): `team.read`, возвращает id/имя/статус/`workspace_id` (не-nullable), видит Unpublished (workspace резолвится из турнира серверно — публичный endpoint не годится: 404 на hidden; admin-get не годится: требует tournament.read). Затем — **одностороннее выравнивание store**: `workspace_id` турнира → zustand-store существующим механизмом (прецедент — `useSyncActiveWorkspace` в хабе). Факт кода: при смене workspace `WorkspaceBootstrap` выполняет глобальную инвалидацию кэша + `router.refresh()` — это сегодняшнее рабочее поведение, приемлемое для Фазы 1; точечная инвалидация — опциональная оптимизация, требующая модификации WorkspaceBootstrap. Выравнивание обязательно: `apiFetch` инжектит store-workspace во все вызовы, а `useDivisionGrid`/статус-каталог/presence читают store (A6, G-O3). Честно: D18 не «растворился» — он сократился с двустороннего контракта до одного направленного правила: инструмент выравнивает store по турниру из URL.
- **Гейт инструмента**: после резолва summary — `adminEntryPermissions ∨ isOrganizer` по workspace турнира. Без валидного `?tournament=` — экран-указатель: заголовок + одна ссылка «Open a tournament» → `/admin/tournaments` (без собственного списка; A-O5).
- **Переезды**: registrations/form/rank-autofill/feed → хаб (§1.2). **Statuses** → `/admin/balancer`, пункт «Balancer Statuses» в сайдбаре; **клиентский префикс-гейт меняется `team.import` → `team.read`** — по серверной матрице (чтение team.read, мутации team.update) — организатор-читатель не теряет доступ (G-O4, закрывает регрессию CG-O8 без дуального маунта).
- **Rank-delta (`WorkspaceBalancerConfigDialog`)** остаётся в пуле инструмента — это конфиг поведения пула; фиксируется как осознанная диспозиция (A-O4).
- **Redirects (D28)**: `/balancer/registrations[...]` → соответствующие адреса хаба, **с переносом маппящихся query-фильтров** (`status`, `source`, `group`; SK-O5); id — из `?tournament=`, без него → `/admin/tournaments`. `/balancer/statuses` → `/admin/balancer`. `/pool`, `/applications` — обновить цели.
- **Глобальный Header (D27-ревизия, SK-O3)**: пункт «balancer» удаляется **только после** расширения предиката видимости пункта «admin» до `canAccessAdmin ∨ isOrganizer` (тот же предикат, что открывал балансер). Честно: для ролевого organizer'а без workspace-permissions это **видимый вход-указатель** — внутри админки клиентский гейт (`AdminLayoutClient`, без ветки isOrganizer) покажет Unauthorized с запросом доступа; функциональная дельта нулевая (такой organizer и сегодня серверно беспомощен без бандла) — политика бандлов из §1.1 первична.
- Удаляются: `BalancerTournamentSelect.tsx` (мёртвый), `BalancerSidebar.tsx`, `balancer-navigation.ts`, sidebar-cookie.

### §5. Админ-навигация

| Группа | Пункты |
|---|---|
| Overview | Dashboard |
| Tournaments | Tournaments |
| Data browser | Teams, Players, Encounters, Standings |
| Workspace | Divisions, Balancer Statuses, Achievements, Members, Branding |
| Game Content | Heroes, Gamemodes, Maps (superuser) |
| Administration | Access (один пункт → табы), Player Identities, Rank Collection, Workspaces |

Rank config → `/admin/rank` + redirect `/admin/settings`; переименования + алиасы Command Palette; breadcrumbs с именами; CTA «New Tournament» → wizard.

### §6. Паттерн-свод

Row-click = detail; «…»-меню = действия; AlertDialog везде; Sheet = quick-edit, Dialog = короткая форма, full-page = builders; серверная пагинация по мере рефакторинга; `--aqt-*` → токены (Фаза 3); `workspaceService` вместо сырого fetch.

### §7. Backend

1. **Readiness-endpoint (Фаза 1)**: `GET /api/v1/admin/tournaments/{id}/readiness`; гейт ANY(`tournament.read`, `team.read`), масштаб полей по правам вызывающего.
2. **`is_finished`-дедупликация (Фаза 3, средний объём)**: derived write-through; удаление из обеих admin-update-схем; реконсиляционная миграция; 4 фронтовых писателя.
3. **Balancer tournament-summary endpoint (Фаза 1)**: `team.read`, возвращает `{id, name, status, workspace_id}` (не-nullable), видит hidden своего workspace — резолвер контекста инструмента (D29). Возможная реализация — доукомплектование существующего `tournament_config_get`.
4. Guard смены `team_formation` при активной draft-сессии.

## Decision Log

| # | Решение | Альтернативы | Обоснование / ревизия |
|---|---|---|---|
| D1 | v3: балансер = инструмент без shell; турнирно-скоупные страницы в хабе | гибрид v2; полное слияние | Запрос стейкхолдера; растворяет UA-O1/O2/O8/CG-O5 v2 по построению |
| D2 | Табы хаба в URL | useState | §1.1 |
| D3 | Wizard + checklist; «Create now» | только wizard | UA-O10 |
| D4 | Ленивый Unpublished-черновик + resume | eager; client-only | SK-O4, UA-O11 |
| D5 | Draft — режим-панель Teams; CRUD всегда; guard смены режима | отдельная вкладка; «manual» | SK-O1/O2/O3, UA-O5/O9 |
| D6–D11 | Veto→Stages; Logs→Matches; Challonge→Integrations; Users не сливаем; Access-пункт; Rank+redirect | — | Подтверждены v2-ревью |
| D12 | Statuses: единственный маунт `/admin/balancer` + пункт сайдбара; **клиентский гейт `team.read`** (мутации по серверной матрице) | redirect (v1); дуальный маунт (v2); гейт team.import (v3) | v3.1: G-O4 — team.import сужал чтение против серверной матрицы (регрессия CG-O8) |
| D13 | Readiness-endpoint в Фазе 1 | клиентская агрегация | SK-O5, CG-O4 (v2) |
| D14 | `is_finished` derived write-through, средний объём | UI-заплатка | SK-O8, CG-O6 (v2) |
| D15 | Паттерн-свод | точечные фиксы | — |
| D16 | `registration`-вкладка = `team.read`; checklist no-access | показывать всем | CG-O1, SK-O6, UA-O3 (v2) |
| D17 | Wizard шаг 4 скрыт без `team.import` | read-only | SK-O7 (v2) |
| D18 | **v3.1**: одно направленное правило — инструмент выравнивает store-workspace по турниру из `?tournament=` (резолв через summary-endpoint; выравнивание существующим механизмом, глобальная инвалидация WorkspaceBootstrap — приемлемое сегодняшнее поведение) | двусторонний контракт v2; «растворение» v3 | G-O2/O3, SK-O2: apiFetch/каталоги/grid читают store — выравнивание обязательно; «растворение» v3 было преувеличением |
| D19–D24 | Stepper эффективных фаз; финальные URL; терминология; предикаты checklist; тесты StageManager; Data browser | — | Подтверждены v2-ревью |
| D25 | Registrations/form/autofill/feed → хаб; перенос компонентов + перепроводка контекста (path-param, store-выравнивание хаба) | оставить в балансере | Турнирно-скоупные; серверная авторизация не меняется (A5). v3.1: «механический перенос» уточнён — включает перепроводку store-зависимостей (SK-O2) |
| D26 | **v3.1**: гейт хаба — базовый `tournament.read` (не расширяется); + политика бандлов: модерация регистраций из хаба требует `tournament.read`+`team.read` в роли; миграционная проверка бандлов в Фазе 1 | ANY(tournament.read, team.read) на префиксе (v3) | Blocker G-O1: layout-запрос хаба серверно требует tournament.read — клиентское расширение впускало персону в 403-витрину; серверная матрица вне scope |
| D27 | **v3.1**: Header-пункт «balancer» удаляется после расширения предиката пункта «admin» до `canAccessAdmin ∨ isOrganizer`; для organizer'а без бандла это видимый вход-указатель (внутри — Unauthorized с запросом доступа) | просто удалить (v3) | SK-O3: ролевой organizer без workspace-permissions терял видимый вход; серверно он беспомощен при любой конфигурации — первична политика бандлов (D26) |
| D28 | Постоянные redirect'ы `/balancer/*` **с переносом query-фильтров** | 404; без фильтров | SK-O5 |
| D29 | **Новое**: summary-endpoint (§7.3) + одностороннее store-выравнивание в инструменте (существующий механизм; точечная инвалидация — опциональная оптимизация) | резолв публичным getTournament (404 на hidden); admin-get (требует tournament.read); двусторонний синк | G-O2: цикл «гейт требует данные, данные требуют прав» разрывается endpoint'ом team.read |
| D30 | **Новое**: top-bar инструмента предоставляет `#balancer-header-slot`, хост presence (без useSidebar), back-link на `teams`, кнопку Rank autofill | оставить порталы без хоста | SK-O4, A-O2, A-O3 |

## Фазирование (v3.1)

| Фаза | Состав | Риски/стоимость |
|---|---|---|
| **1. Каркас** | Внутренний порядок жёсткий (SK-O7): **(а)** layout-shell хаба + URL-табы + route-guards + realtime (вкл. balancer-топик); **(б)** readiness- и summary-endpoints (backend); **(в)** переезд registrations/form/autofill/feed в хаб (D25) — период dual availability со старыми роутами; **(г)** redirect'ы D28; **(д)** снос shell балансера + top-bar инструмента (D30) + store-выравнивание (D29) + Header-ревизия (D27) + Statuses в сайдбар (D12); параллельно: Overview (stepper+checklist), wizard, nav-чистки, CTA, ActiveTournamentCard-фильтр, миграционная проверка organizer-бандлов (D26) | Перепроводка workspace-деривации (D29 + store-зависимости переезжающих страниц) — самая тонкая часть; объём переезда честно включает её, не только роутинг |
| **2. Консолидация** | Teams mode-панель + guard + Draft-слияние (redirect `draft→teams`); StageManager: извлечение + характеризационные тесты → декомпозиция + Veto (redirect `veto→stages`); Matches+Logs; Challonge → Integrations | StageManager (D23); Control Room → fallback `/draft-live` |
| **3. Полировка** | Паттерн-свод; `is_finished`; токены design-book | Дублированные admin-схемы двух сервисов |

## §9. Review-история

**v2** (полный цикл, Арбитр: APPROVED): 31 возражение — 30 принято, 1 отклонено (клонирование — YAGNI). Разрешения инкорпорированы в текст (ссылки SK-/CG-/UA-O#).

**v3-дельта** (SkepticDelta, GuardianDelta, AdvocateDelta): 1 blocker, 8 major, 9 minor — все разрешены в v3.1:

| Возражение | Sev | Разрешение |
|---|---|---|
| G-O1 (+SK-O1): гейт-расширение D26 впускает в 403 — layout хаба серверно требует tournament.read | blocker | **Принято** → D26-ревизия: базовый гейт не меняется; политика бандлов + миграционная проверка |
| G-O2 / SK-O2: цикл резолва workspace; store-coupling до транспортного слоя; «растворение» D18 преувеличено | major | **Принято** → D29 (summary-endpoint + одностороннее выравнивание); D18/D25 переформулированы честно |
| G-O3: useDivisionGrid/каталоги/presence читают store | major | **Принято** → покрыто D29 |
| SK-O3: ролевой organizer теряет единственный Header-вход | major | **Принято** → D27-ревизия (предикат admin-пункта) |
| G-O4 (+SK-O6): гейт /admin/balancer team.import строже серверной матрицы — регрессия CG-O8 | major/minor | **Принято** → D12: team.read |
| A-O2: цель back-link не специфицирована | major | **Принято** → D30: вкладка `teams` |
| A-O3: потеря bulk-autofill affordance из инструмента | major | **Принято** → D30: кнопка в top-bar (перенос существующего входа) |
| SK-O4: порталы без хоста; BalancerPresenceStack ← useSidebar | minor | **Принято** → D30 |
| SK-O5: redirect'ы без query-фильтров | minor | **Принято** → D28 |
| SK-O7: порядок работ Фазы 1 | minor | **Принято** → фазирование (а)–(д) |
| G-O5: nav-гейт Tournaments vs расширенный префикс | minor | **Снят** вместе с отменой расширения (D26) |
| G-O6: checklist-refetch — хаб не слушает balancer-топик | minor | **Принято** → A4/§3: клиентская подписка на существующий топик |
| A-O1: смена турнира 2 → ~5 кликов | minor | **Принято как осознанный трейдофф** → Риск 5; митигация — двух-вкладочный workflow (realtime-инвалидация подтверждена кодом) |
| A-O4: rank-delta диалог без диспозиции | minor | **Принято** → §4: остаётся в пуле, зафиксировано |
| A-O5: двусмысленный экран-указатель | minor | **Принято** → §4: одна ссылка на список турниров |

## Риски (v3.1)

1. **Перепроводка workspace-деривации** (D29 + store-зависимости D25) — самая тонкая часть Фазы 1; store-выравнивание обязано случиться до первого apiFetch-вызова инструмента.
2. **StageManager-декомпозиция** — характеризационные тесты до рефакторинга (D23).
3. **Control Room в Teams** — fallback route `/draft-live`.
4. **Data browser-демоция** — Cmd+K, QuickAccess, неизменные URL.
5. **Смена турнира для мульти-турнирного оператора**: 2 взаимодействия → ~5 кликов — осознанный трейдофф за снятие целого shell; митигация: двух-вкладочный workflow (хаб ‖ инструмент) с работающей realtime-инвалидацией.
6. **Гейт-матрица переехавших страниц**: per-route гейты воспроизводят серверную матрицу (form-запись = team.import) — проверка в реализации.
