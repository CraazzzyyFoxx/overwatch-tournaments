# План: Полный редизайн платформы турниров (OWT-handoff) + Live Draft

## Context

Пользователь передал дизайн-хэндофф (`D:\Downloads\OWT-handoff.zip` → распакован в `C:\Users\andre\AppData\Local\Temp\owt-handoff\owt\`). Исходная Claude-Design ссылка была мёртвой (404), источник истины — файлы из zip.

Изначально я ошибочно сузил задачу до одной страницы драфта. На самом деле хэндофф — это **редизайн всей платформы**: 12 страниц на единой новой дизайн-системе (`project/tournament-shell.css` + `project/redesign/styles.css`) плюс componentized React-референс (`project/redesign/*.jsx`), скриншоты (`project/screenshots/`) и моки (`project/data.js`). Страницы: Tournaments, Standings, Teams, Bracket, Encounters, Matches, Participants, Player, Analytics, Heroes, Users, **Draft** (новый живой драфт).

**Запрос пользователя:** перенести **весь новый дизайн** (не только драфт); продумать backend и схемы БД для тех мест, где нужен новый бэкенд; составить план **с ресурсоёмкостью**; дать критику дизайна (что плохо, где текущий интерфейс лучше).

**Существующий фронт:** Next.js 16 App Router, route-group `(site)`, Tailwind **v3** + shadcn/ui, React Query v5. Маршруты почти под все страницы уже есть. Стилизация — inline-Tailwind с **захардкоженными цветами** в компонентах (`StandingsTable.tsx` и др.) → главный долг при рескине. Realtime-стек (WS `realtime-service` + Redis pub-sub + JWT + replay через `WorkspaceEvent`) уже есть; топик `tournament:{id}:draft` зарезервирован, но намеренно отключён (`_deny_draft_until_implemented` в `shared/services/realtime_topics.py`).

---

## Решение по scope (подтверждено пользователем)

1. **Рескин сейчас, бэкенд фазами.** Фаза 1 — портируем всю новую дизайн-систему на 12 страниц поверх **существующих** данных. Новые бэкенд-фичи (closeness, predicted finish/hottest hero, hero-мета, ачивки/featured, head-to-head, cut-lines) и **Draft** — отдельными фазами; **схемы проектируем уже сейчас** (ниже).
2. **Новый глобальный токен-слой.** Палитра редизайна вносится как CSS-переменные + расширение `tailwind.config`; захардкоженные цвета заменяются постепенно. `.aqt-player`/`.admin-theme` пока не трогаем (миграция/удаление — отдельно, по желанию).

---

## Карта: redesign-страница → существующий route → классификация

| Redesign HTML | Существующий route | Фаза 1 (рескин) | Новый бэкенд (фаза) |
|---|---|---|---|
| Tournaments Redesign | `(site)/tournaments/page.tsx` | да | featured live-strip — позже (P-Matches) |
| Standings Redesign | `(site)/tournaments/[id]/standings/page.tsx` | да | head-to-head + cut-lines (P-Standings) |
| Teams Redesign | `(site)/tournaments/[id]/teams/page.tsx` | да | — (роли/дивизионы/«new» уже есть) |
| Bracket Redesign | `(site)/tournaments/[id]/bracket/page.tsx` | да | — (bracket realtime уже есть) |
| Matches Redesign | `(site)/tournaments/[id]/matches/page.tsx` | да | predicted finish + hottest hero (P-Matches) |
| Encounters Redesign | `(site)/encounters/*` | да | closeness-скоринг + saved views (P-Encounters) |
| Participants Redesign | `(site)/tournaments/[id]/participants/page.tsx` | да | — (smurf/division уже есть) |
| Player Redesign | `(site)/users/[slug]/page.tsx` | да | — (профиль/статы есть) |
| Analytics Redesign | `(site)/tournaments/analytics/page.tsx` | да | — (`TournamentAnalytics` ↔ `analytics.types.ts` уже совпадают с моками) |
| Heroes Redesign | `(site)/tournaments/[id]/heroes/page.tsx` | да | hero-мета агрегация + meta movers (P-Heroes) |
| Users Redesign | `(site)/users/*` (каталог) | да | achievements + featured curation (P-Users) |
| **Draft Redesign** | **NEW** `(site)/tournaments/[id]/draft/` | каркас | **полный бэкенд (P-Draft, крупнейшая)** |

Принцип Фазы 1: рескин поверх существующих данных; поля, которых ещё нет (closeness %, predicted finish, hero-winrate, achievements, H2H, cut-lines), рендерим как graceful-placeholder или прячем за фиче-флагом до своей бэкенд-фазы.

---

## Фаза 0 — Дизайн-система (фундамент)

**Токены** (новый глобальный слой). Источник: `tournament-shell.css`.
- В `globals.css` добавить CSS-переменные: фоны `--bg/--bg-2/--card`, текст `--fg/--fg-muted/--fg-dim/--fg-faint`, акценты `--teal: hsl(174 72% 46%)`, `--rose: hsl(340 75% 58%)`, `--amber`, `--emerald`, `--violet`, `--blue`, `--gold`; роли `--tank/--damage/--support`; группы `--group-a..d`; `--radius: 14px`, `--radius-sm: 8px`.
- `tailwind.config.ts`: завести эти цвета в `theme.extend.colors`, добавить шрифты **Inter** (sans) и **JetBrains Mono** (mono) — `Barlow Condensed` уже есть (display). Подключить Google Fonts через `next/font`.
- Статус-классы: `.status-pill.{live|upcoming|finished|draft}`, density-варианты.

**Shell-компоненты** (новые, `src/components/tournament-shell/`), по `redesign/components.jsx`:
- `TournamentShell` (`.tn-shell`, max-width 1600), `ShellNav` (`.nav`), `Breadcrumb` (`.crumb`), `TournamentHero` (`.tn-hero` со статус-зависимыми бордерами/glow), `SectionTabs` (`.tabs`).

**Atom-примитивы** (`src/components/ui-redesign/`), по `components.jsx`:
- `RoleGlyph`, `DivBadge`, `ConfChip`, `PointsPill`, `GroupBand`, `ShiftBar`, `AnomalyChip`, `StatusPill`.
- Цель: вынести цветовую логику из JS (как в `StandingsTable.tsx`) в эти токенизированные атомы — паттерн для всего рескина.

---

## Фаза 1 — Рескин 12 страниц (поверх существующих данных)

Кластеры (можно вести параллельно после Фазы 0):
- **A. Core tournaments:** Tournaments (featured live-cards + all-tournaments table), Standings (group-карточки, W/L, form-чипы; H2H/cut-lines — заглушка), Teams (3-колоночный roster-grid: роль/тег/дивизион/«new»).
- **B. Match-вокабуляр:** Bracket (group↔playoff свитчер, live-strip), Matches (timeline по стадиям, live-row expand; predicted/hottest — заглушка), Encounters (KPI-strip, таблица; closeness/saved-views — заглушка).
- **C. People:** Participants (5-шаговая воронка статусов, smurf-флаги), Player (профиль, career-grid, табы), Users (Analytics/Catalog режимы; achievements/featured — заглушка).
- **D. Meta:** Heroes (top-3 карточки, бар-чарт ролей; данные hero-меты — заглушка/частично), Analytics (placement/shift/confidence/anomaly — данные уже есть).

Подход: переиспользуем существующие data-хуки/сервисы и React Query query-keys; меняем разметку/классы на shell + атомы. На <1280px колоночные раскладки → табы/аккордеоны (адаптив, см. критику).

---

## Бэкенд-фазы (схемы проектируем сейчас, реализуем позже)

### P-Draft (крупнейшая) — живой змейковый драфт
Альтернативный режим формирования команд: авто-балансер остаётся, драфт добавляется. Балансер/регистрация даёт пул + ранги + FIT + капитанов → капитаны драфтят вживую → экспорт в `tournament.Team`/`Player`. Параметры из дизайна: 12 капитанов, 4 раунда, 48 пиков, ростер 5, 45с/пик, автопик, snake.

**Где живёт:** balancer-service (владеет пулом, рангами, objective-скорингом, экспортом).

**Схема `draft`** (новый `backend/shared/models/draft.py`, Alembic):
- **DraftSession**: id, tournament_id, workspace_id, `status` (SETUP/READY/LIVE/PAUSED/COMPLETED/CANCELLED), `format` (SNAKE/LINEAR), rounds=4, pick_time_seconds=45, team_size=5, current_pick_id?, `pool_source` (BALANCER_BALANCE/MANUAL), source_balance_id?, `autopick_strategy` (BEST_FIT/BEST_AVAILABLE/ROLE_NEED), allow_admin_override, exported_at, timestamps, settings_json.
- **DraftTeam**: id, session_id, captain_user_id, name, draft_position (seed), exported_team_id?.
- **DraftPlayer** (`draft_player`): id, session_id, user_id, primary_role, sub_role, is_flex, division_number, rank_value, source_balancer_player_id?, `status` (AVAILABLE/PICKED/REMOVED), is_captain, drafted_by_team_id?, anomaly_flags(jsonb).
- **DraftPick** (предсоздаются все 48 на READY): id, session_id, overall_no(1..48), round_no, pick_in_round, draft_team_id, target_role?, `status` (UPCOMING/ON_CLOCK/COMPLETED/SKIPPED/AUTOPICKED), picked_player_id?, picked_by_user_id?, is_autopick, is_admin_override, clock_started_at?, clock_expires_at?.
- Без отдельного DraftEvent (реюз `WorkspaceEvent` для replay); presence — эфемерно в Redis (set + TTL heartbeat); snake-порядок детерминированно из seed+round.

**REST** (balancer-service, роутер `draft`, проксируется через tournament-service):
чтение `GET /sessions/{id}`, `/board`, `/tournaments/{tid}/draft`; админ `POST /sessions`, `/seed`, `PATCH`, `/order`, `/start`, `/pause`, `/resume`, `/cancel`, `/export`; действия `POST /picks/{id}/select|autopick|override`, `GET /suggestions`. FIT — серверный реюз objective-функции балансера.

**Realtime** (топик `tournament:{id}:draft`): снять deny в `realtime_topics.py`/`topic_acl.py`; публиковать `draft.session_updated|pick_started|pick_made|paused|resumed|completed|presence` через `realtime_publisher`. WS — только read-relay, все мутации через REST. Часы — server-authoritative loop + Redis-lock + DB-resumable `clock_expires_at`; фронт считает локально от `clock_expires_at`. Экспорт — реюз `export_balance` (`balancer-service/src/services/admin/balancer.py`).

### P-Standings — head-to-head + cut-lines
Новое: H2H между командами группы, отметки advancement/«top N advance». Схема: либо вычисляемый сервис поверх `Encounter`, либо таблица `standing_h2h`(stage_id, team_a, team_b, wins, maps) + поле `advance_slots` в стадии/группе. Эндпоинт расширяет существующий standings-сервис.

### P-Encounters — closeness-скоринг + saved views
Новое: метрика «closeness» серии (по картам/счёту) и сохранённые фильтры. Схема: `encounter_closeness`(encounter_id, score 0..1, computed_at) — фон.задача парсера/аналитики; `user_saved_view`(user_id, scope, filters_json, name). Реюз parser-метрик.

### P-Matches — predicted finish + hottest hero (live)
Новое: предсказание исхода live-матча и «горячий герой». Схема/пайплайн в analytics-service: `match_prediction`(encounter_id, predicted_winner, prob, updated_at), `match_hot_hero`(encounter_id, hero_id, metric). Live-обновления через существующий bracket/encounter realtime-топик.

### P-Heroes — hero-мета агрегация + meta movers
Новое: per-tournament pickrate/winrate/playtime по героям и дельта к прошлому ивенту. Схема: материализованное представление/таблица `tournament_hero_stats`(tournament_id, hero_id, picks, wins, playtime, pickrate, winrate) + `delta_vs_prev`. Источник — существующие match-логи парсера.

### P-Users — achievements + featured curation
Новое: трекинг разблокировки ачивок и подбор featured-игроков. Реюз существующего Achievement Engine (см. MEMORY `project_achievement_engine.md`). Схема: `user_achievement`(user_id, achievement_id, unlocked_at) если ещё нет; `featured_player`(scope, user_id, reason, rank) или алгоритм-выборка.

---

## Карта переиспользования (что НЕ пишем заново)

| Нужное | Существующее | Путь |
|---|---|---|
| Шрифт display | Barlow Condensed уже подключён | `tailwind.config.ts`, `globals.css` |
| UI-примитивы | shadcn/ui (Radix+CVA) | `frontend/src/components/ui/` |
| Data-fetch | apiFetch (6 сервисов) | `frontend/src/lib/api-fetch.ts` |
| Query-keys | tournamentQueryKeys | `frontend/src/lib/tournament-query-keys.ts` |
| Сервисы | tournament/encounter/analytics/user/team/hero | `frontend/src/services/*.service.ts` |
| Realtime фронт | RealtimeClient + Zustand | `frontend/src/services/realtime.service.ts`, `src/stores/realtime.store.ts` |
| Realtime бэк | WS+pub-sub+replay | `realtime-service/src/routes/ws.py`, `services/pubsub_listener.py`, `event_replay.py`; `shared/services/realtime_publisher.py`, `realtime_topics.py`, `topic_acl.py` |
| Replay-хранилище | WorkspaceEvent | `backend/shared/models/` |
| Пул/ранги/FIT/scoring + экспорт | balancer | `backend/balancer-service/src/services/...`, `admin/balancer.py: export_balance`, `shared/models/balancer.py` |
| Аналитика-типы | TournamentAnalytics | `frontend/src/types/analytics.types.ts` (совпадают с `data.js`) |
| Achievement Engine | условный движок | MEMORY `project_achievement_engine.md` |

---

## Ресурсоёмкость (оценка трудозатрат)

| Фаза | Содержание | Оценка |
|---|---|---|
| **0. Дизайн-система** | токены→`globals.css`+`tailwind.config`, шрифты, shell-компоненты, atom-примитивы, паттерн замены хардкода | 5–8 д |
| **1. Рескин 12 страниц** | 4 кластера поверх существующих данных + адаптив + замена хардкод-цветов (40–60 файлов) | 18–28 д |
| **P-Standings** | H2H + cut-lines (схема+сервис+UI-включение) | 4–6 д |
| **P-Encounters** | closeness-скоринг + saved views | 6–9 д |
| **P-Matches** | predicted finish + hottest hero (live) | 6–9 д |
| **P-Heroes** | hero-мета агрегация + meta movers | 5–8 д |
| **P-Users** | achievements + featured | 5–8 д |
| **P-Draft** | схема+оркестрация+clock+realtime+экспорт+UI драфта | 33–48 д |
| **Хардненинг/тесты** | reconnect/replay, нагрузка, e2e, покрытие ≥80%, a11y | 6–10 д |

**Итого ориентир:** Фаза 0+1 (видимый рескин) ≈ **23–36 чел-дней**; полная программа со всеми бэкенд-фазами ≈ **88–134 чел-дня**. P-Draft — крупнейший единичный бэкенд-блок.

---

## Критика дизайна (что плохо / где текущий интерфейс лучше)

**Проблемы редизайна:**
1. **Тёмная-only тема.** Хэндофф не предусматривает светлую тему, а в проде есть light/dark. Нужно решить: редизайн только dark или адаптировать токены под обе схемы.
2. **3-колоночные раскладки** (Draft, Teams, Standings-groups) тяжелы на планшете/мобиле. Текущие single-focus страницы на малых экранах удобнее → обязательный адаптив (на <1280px — табы/аккордеоны, а не 3 колонки).
3. **Перегруз hero-strip** (особенно Draft): round/pick pips + timer-ring + presence + spectator + on-the-clock в одной полосе. Свернуть presence/spectator в поповер на узких экранах.
4. **Состояние через классы, не данные.** В макете статусы/режимы — CSS-классы (`.live`, `density-*`). Доменные правила (`format` snake/linear, `team_size`, advancement) должны жить в БД/типах, а не как визуальный твик. Чисто визуальное → `settings_json`/локально.
5. **`clock_tick` по WS** (если слать ежесекундно) — лишний трафик/рассинхрон. Лучше локальный отсчёт от `clock_expires_at`.
6. **Точный spectator-count** при росте зрителей даёт дёрганье/нагрузку — троттлинг/округление («120+»).
7. **Не нарисованы пустые/paused/cancelled/empty-состояния** (особенно Draft) — спроектированы только «live»-кадры.
8. **Захардкоженная цветовая логика** в редизайне останется долгом, если просто скопировать классы — поэтому Фаза 0 выносит цвета в токены/атомы.

**Где текущий подход лучше и стоит сохранить:**
- **Авто-балансер не заменять.** Драфт — альтернатива; балансер даёт детерминированный, воспроизводимый результат и сидирует драфт.
- **Существующая аналитика богаче моков** (`TournamentAnalytics`: shift/confidence/anomalies) — переиспользовать, а не переизобретать поля.
- **Серверная objective-функция** балансера для FIT лучше клиентских эвристик из `data.js`.
- **Готовый realtime-стек** (replay/JWT/ACL) — переиспользуем целиком, новый транспорт не нужен.
- **shadcn/ui + чистый Tailwind** на фронте → рескин это в основном swap классов + расширение конфига, а не переписывание.

---

## Допущения и открытые вопросы

- Дефолты драфта (12/4/48/5/45с) берём из дизайна, делаем настраиваемыми в `DraftSession`.
- Один активный драфт на турнир (MVP).
- Тёмная-only тема vs адаптация под light — **открыто** (см. критику #1).
- `.aqt-player`/`.admin-theme`: оставить рядом или мигрировать — отложено (пользователь выбрал «новый глобальный токен-слой», старые темы пока не трогаем).
- Encounters/Users — глобальные (cross-tournament) или в контексте турнира: уточнить маршрутизацию.
- Автопик по умолчанию `BEST_FIT`; приоритет role-need vs best-available — уточнить.
- Кто зритель драфта (участник воркспейса vs публично) — уточнить ACL.

---

## Верификация

- **Фаза 0/1 (рескин):** визуальное сравнение со скриншотами `project/screenshots/`; проверка, что страницы рендерят существующие данные без регрессий; адаптив на xs/sm/md/lg; light/dark (по решению #1). Прогон через Claude Preview / Playwright MCP.
- **Бэкенд-фазы:** unit (snake-порядок, валидация select, clock-resume, FIT, closeness, H2H, hero-агрегация); integration (полный прогон Draft SETUP→…→export; автопик; override; pause/resume; reconnect+replay по `after_event_id`); realtime (капитан+зритель видят события синхронно).
- **E2E (Playwright):** ключевые флоу (список турниров → standings → teams → bracket; драфт-пик в окне; экспорт создаёт `tournament.Team`/`Player`).
- **Покрытие ≥80%.** Команды через `rtk` (`rtk pytest`, `rtk vitest run`, `rtk playwright test`, `rtk next build`).

---

## Критические файлы

**Создать (Фаза 0/1):**
- `frontend/src/components/tournament-shell/` (TournamentShell, ShellNav, Breadcrumb, TournamentHero, SectionTabs)
- `frontend/src/components/ui-redesign/` (RoleGlyph, DivBadge, ConfChip, PointsPill, GroupBand, ShiftBar, AnomalyChip, StatusPill)
- `frontend/src/app/(site)/tournaments/[id]/draft/` (+ `/admin`) — каркас в Ф1, наполнение в P-Draft

**Изменить (Фаза 0/1):**
- `frontend/src/app/globals.css` — новый токен-слой (палитра/роли/группы/radius)
- `frontend/tailwind.config.ts` — colors + шрифты (Inter, JetBrains Mono)
- `frontend/src/app/layout.tsx` — подключение шрифтов
- 12 page.tsx под `(site)/tournaments/*`, `(site)/encounters/*`, `(site)/users/*` + их компоненты (`StandingsTable.tsx` и др.) — замена хардкод-классов на атомы/токены

**Создать/изменить (бэкенд-фазы):**
- `backend/shared/models/draft.py` + Alembic (P-Draft)
- `backend/balancer-service/src/routes/draft.py` + services (оркестрация, clock-воркер, suggestions) (P-Draft)
- `backend/shared/services/realtime_topics.py`, `topic_acl.py` — снять `_deny_draft_until_implemented` + ACL (P-Draft)
- `backend/balancer-service/src/services/admin/balancer.py` — реюз `export_balance` для DraftTeam (P-Draft)
- standings/encounter/matches/heroes/users сервисы + модели/миграции под соответствующие P-фазы (H2H, closeness, prediction, hero-stats, achievements)
- tournament-service gateway — проксирование `/api/v1/draft`
- `frontend/src/lib/tournament-query-keys.ts`, `src/services/realtime.service.ts`, `src/stores/realtime.store.ts` — ключи/подписки драфта
