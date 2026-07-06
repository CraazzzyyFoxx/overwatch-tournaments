# Комплексный review бэкенда `anak-tournaments`

**Дата:** 2026-07-03
**Ветка:** `feature/identity-workspace-refactor`
**Область:** 7 Python-сервисов (~120k строк) + `shared/` + Go-gateway (~9.5k строк) + edge (nginx)
**Метод:** 6 параллельных специализированных ревьюеров (безопасность identity/auth, безопасность Go-gateway, производительность/БД, качество `shared/`+RPC, безопасность parser/balancer, архитектура) + независимая проверка edge-слоя и верификация ключевых находок.

**Вердикт: 🚫 BLOCK** — до релиза обязательно закрыть 5 CRITICAL (три из них — обход аутентификации / изоляции данных) и HIGH-группу по безопасности.

---

## ✅ Статус исправлений (2026-07-03)

Все находки CRITICAL→LOW исправлены (кроме двух архитектурных, сознательно отложенных). Правки выполнены 5 параллельными агентами по файл-непересекающимся областям + миграции вручную. Верификация зелёная.

| Область | Статус | Верификация |
|---|---|---|
| Perf-миграции (C4 + initcap) | ✅ | `perfidx01`+`perfidx02`, единый alembic-head |
| Gateway + nginx | ✅ | `go build`/`go vet` чисто, `nginx -t` ок, тесты зелёные |
| shared/ (crud, s3, circuit-breaker, гигиена) | ✅ | ruff чисто, 75 тестов |
| identity-service (C1/C2/H3 + RBAC/session/HKDF) | ✅ | 67 passed / 8 skipped(DB) |
| tournament + app (C5/H8/H11/H13) | ✅ | tournament 185, app 30 (целевые) |
| parser + balancer (C3/H5/H12) | ✅ | parser 15, balancer 235 (2 тест-регрессии H5 починены) |

**Ключевые security-диффы проверены вручную:** C1/C2 (OAuth-матчинг только по `provider_user_id`, `UNIQUE(email)`→409), C3 (S3-ключ ограничен префиксом + allow-list + анти-traversal), H8 (fail-closed sentinel `ALL_WORKSPACES`, `require_workspace_scope` → 400 на `None`).

**Отложено как архитектурные решения (требуют выбора владельца, не механический фикс):**
- **H9** — дедупликация app↔tournament: нужно решить, какой сервис — owner каждого ресурса (изменение routing), затем удалить байт-идентичные копии.
- **H10** — split `shared/` на `shared-core`/`shared-models`/`shared-domain`: квартальная задача, когда независимые деплои станут требованием.

**Follow-up (требуют миграции/инфры, отмечены в диффах):**
- C1 — полноценный pending-email flow (колонка + почта); пока разорван вектор захвата + сброс `is_verified`.
- Отзыв access-JWT — при переходе gateway на чисто локальный JWT продублировать блэклист `sid` на edge.
- HKDF — legacy-ветки проверки refresh/api-key убрать после ротации (≤30 дней).
- IP за Traefik — для точного клиентского IP включить nginx `realip`-модуль или проставлять `X-Real-IP` в Traefik (иначе rate-limit/аудит схлопываются в IP Traefik).
- Пре-существующие 3 падения в `app-service/tests/test_user_profile_flows.py` — из WIP ветки (тест патчит несуществующий `flows.encounter_service`), НЕ связаны с фиксами.

Изменения НЕ закоммичены — оставлены для ревью.

---

## Оглавление

- [Сводка по severity](#сводка-по-severity)
- [🔴 CRITICAL](#-critical)
- [🟠 HIGH](#-high)
- [🟡 MEDIUM](#-medium)
- [🟢 LOW](#-low)
- [⚙️ Edge / инфраструктура](#️-edge--инфраструктура)
- [✅ Что сделано хорошо](#-что-сделано-хорошо)
- [📋 Приоритетный план действий](#-приоритетный-план-действий)
- [Приложение: сводная таблица по файлам](#приложение-сводная-таблица-по-файлам)

---

## Сводка по severity

| Severity | Кол-во | Суть |
|---|---|---|
| 🔴 CRITICAL | 5 | 2× захват аккаунта (email/OAuth), S3-IDOR межтенантная утечка, отсутствующий индекс, гонка кэша |
| 🟠 HIGH | 13 | DoS gateway, нет rate-limit на auth, fail-open авторизация/скоупинг, N+1, дубли доменной логики |
| 🟡 MEDIUM | ~18 | лимиты тела запроса, спуфинг IP, key-separation, отсутствие индексов, псевдо-GraphQL |
| 🟢 LOW | ~17 | мёртвый код, логирование, курсорная пагинация, конфиг-дефолты |

> Часть находок пересекается между агентами (content-type аватаров, rate-limiting, лимиты тела запроса, fail-open скоупинг) — ниже они сведены в единые пункты.

---

## 🔴 CRITICAL

### C1. Захват аккаунта: смена email без подтверждения + OAuth-матчинг по email

- **Файлы:** `backend/identity-service/src/services/auth_flows.py:256-271` (`update_me`); `backend/identity-service/src/services/oauth_service.py:546-567` (`_find_existing_auth_user_by_email`), `:809-975` (`find_or_create_oauth_user`); `serve.py:270-279` (`rpc.identity.update_me`).
- **Проблема:** `update_me` меняет `AuthUser.email` без верификации владения новым адресом — только проверка уникальности. Одновременно OAuth-логин находит существующий `AuthUser` по **точному совпадению email** и логинит вызывающего под ним.
- **Сценарий эксплуатации:**
  1. Атакующий регистрирует обычный аккаунт по паролю (`rpc.identity.register`, открыт всем).
  2. Через `update_me` меняет `email` на email жертвы (подтверждение не требуется).
  3. Теперь у атакующего есть аккаунт с `email == victim@example.com`, пароль которого он знает.
  4. Когда жертва впервые логинится через Discord/Twitch/Battle.net с тем же email — её OAuth-подключение привязывается к аккаунту **атакующего** → полный захват identity, включая `players.user`, воркспейсы, роли.
  5. Побочно: email-сквоттинг блокирует легитимную регистрацию жертвы.
- **Фикс:** менять `AuthUser.email` только через flow подтверждения (письмо со ссылкой/кодом на новый адрес; коммит поля только после подтверждения). До подтверждения хранить pending-email отдельно, сбрасывать `is_verified=False`, не давать менять email OAuth-only учёткам без re-auth.

### C2. Захват аккаунта: OAuth-email трактуется как верифицированный при отсутствии флага

- **Файл:** `backend/identity-service/src/services/oauth_service.py:546-567`.
- **Проблема:** проверка отклоняет только при явном `raw_data.get("verified") is False` / `email_verified is False`. Discord кладёт `verified`, но **Twitch** (`oauth_service.py:203-258`) и, вероятно, **Battle.net** (`:322-373`) не кладут ни `verified`, ни `email_verified` → `.get()` вернёт `None`, что ≠ `False`, и проверка молча пропускает email как «верифицированный».
- **Сценарий эксплуатации:** если провайдер отдаёт email без явного статуса верификации (или его можно подделать на стороне провайдера), атакующий, привязавший к своему Twitch/Battle.net профилю email жертвы, логинится под существующим паролированным аккаунтом жертвы **без знания пароля** — полный обход аутентификации. В отличие от C1, предварительный сквоттинг не нужен.
- **Фикс:** fail-closed — если провайдер не даёт явного признака верификации, **не** матчить по email вообще (только по `provider_user_id`/существующей `OAuthConnection`), либо требовать re-auth перед слиянием по email. Проверить по докам каждого провайдера, гарантируют ли Twitch/Battle.net верифицированность email.

### C3. S3-IDOR: межтенантное чтение любых объектов через импорт достижений

- **Файлы:** `backend/parser-service/src/services/achievement/import_export.py:112-131` (`extract_s3_key_from_public_url`), `:161-198` (`copy_workspace_achievement_image`), `:225-296` (`import_portable_rules`); `backend/parser-service/src/rpc/achievements.py:252-284` (`rpc.parser.ach.import`); `backend/parser-service/src/schemas/admin/achievement_rule.py:94-108` (`image_url: str | None` без валидации).
- **Проблема:** RPC `ach.import` требует лишь `achievement.import` на целевом воркспейсе + членство в заявленном `source_workspace`. Поле `image_url` каждого правила — произвольная строка. `extract_s3_key_from_public_url` отрезает известный публичный base URL бакета и берёт **весь остаток пути как S3-ключ** без проверки принадлежности. Затем `copy_workspace_achievement_image` делает `s3.get_object(source_key)` и переиздаёт объект как публичный ассет target-воркспейса. Бакет общий (`shared/clients/s3/client.py`, default `"aqt"`): match-логи `logs/{tournament_id}/...`, аватары, командные данные.
- **Сценарий эксплуатации:** пользователь с правом `achievement.import` указывает `source_workspace = {id: <свой>}` (проходит self-membership) и `rules[0].image_url = "<public_s3_base>/logs/<чужой_tournament_id>/<known_filename>"` (или `.../avatars/users/<id>/...`) → сервис скачивает чужой приватный объект и публикует его копию в своём воркспейсе.
- **Фикс:** валидировать, что извлечённый ключ находится под ожидаемым префиксом `assets/achievements/{source_workspace.slug}/` (или тем, что вернул `find_workspace_achievement_asset_key` через `list_objects`), отклонять произвольный клиентский URL.

### C4. Отсутствует индекс `workspace_member.player_id` (schema drift) — ✅ верифицировано

- **Файлы:** `backend/shared/models/workspace.py:51-53` (модель декларирует `player_id ... index=True`); `backend/migrations/versions/iwrefac04_member_player.py` (создаёт только `UniqueConstraint("workspace_id", "player_id")` — одиночного индекса нет); `iwrefac08` — текущий HEAD ветки миграций, индекс так и не добавлен.
- **Верификация:** grep по всем `migrations/versions` — единственный `create_index` на `workspace_member` был в `a7634c02717d_initial_v5.py` и на **старой** колонке `auth_user_id` (её `iwrefac04` дропнул). На `player_id` отдельного btree нет.
- **Проблема:** модель говорит `index=True`, БД имеет только составной unique `(workspace_id, player_id)`, где `player_id` — второй столбец. На PostgreSQL 16 (`docker-compose.yml: postgres:16-alpine`; index skip scan появился только в PG18) такой индекс **не** обслуживает поиск по одному `player_id` → seq scan O(N) по всей таблице.
- **Масштаб:** один из самых горячих паттернов (100+ вхождений `WorkspaceMember.player_id`). Критичные пути:
  - `tournament-service/src/services/user/service.py:1734-1741, 1772-1807, 1856, 1891, 1945, 1992, 2021` — профиль пользователя (`/users/[slug]/tournaments|teams|roles`), дублируется в `app-service/src/services/user/service.py`.
  - `shared/services/achievement_effective.py:93,105,128-129,142` — эффективные достижения (почти каждая страница ачивок/оверьвью).
  - `analytics-service/src/services/ml/features/extractors.py:211,572`, `mvp_dominance.py:94` — тяжёлые ML-фичи.
  - `balancer-service/src/services/team.py:91,101,109`; `app-service/src/services/admin/user_merge.py:407-416`.
- **Фикс:** миграция `create_index("ix_workspace_member_player_id", "workspace_member", ["player_id"])` (обычный btree). ~5 минут, немедленный эффект на десятках путей. Заодно закрывает разрыв модель↔БД.

### C5. Гонка `cache.disabling()` на публичном эндпоинте

- **Файл:** `backend/tournament-service/src/rpc/public_rpc.py:563` (`rpc.tournament.reg_pub_list`, `_reg_pub_list`).
- **Проблема:** `cashews` `disabling()` мутирует флаг на **процесс-глобальном** singleton backend'а (не `contextvar`, не per-request). Пока публичный эндпоинт внутри `with`-блока — все конкурентные корутины на воркере, читающие/пишущие кэш через `backend:`-префикс (включая несвязанные `division_grid_cache`, `settings_provider`), молча теряют кэш. При пересечении двух запросов `finally: enable()` одного преждевременно включает кэш, пока другой ещё рассчитывает на отключённый.
- **Влияние:** эндпоинт публичный, конкурентный трафик (много зрителей смотрят список регистраций) → случайные «холодные» промахи на несвязанных ручках и деградация division-grid кэша именно под нагрузкой. Задокументированный в памяти проекта баг-класс (`lesson_cashews_disabling_shared_cache`), живой в новом месте после рефакторинга.
- **Фикс:** не использовать `cache.disabling()` для точечного «не кэшируй эту выборку». Вместо этого — не оборачивать в `@cache.cached`, либо передавать явный `bypass`-параметр в конкретную функцию, либо `cache.get`/`cache.set` напрямую без глобального disable-флага.

---

## 🟠 HIGH

### Безопасность

**H1. Паника в фоновых горутинах роняет весь процесс gateway (полный DoS)**
- **Файлы:** `gateway/internal/ws/hub.go:187-198` (`Hub.Route` — `go func(c *Conn){...c.send(payload)}(c)` на каждый таргет фан-аута, без `recover`); `gateway/internal/rpc/rpc.go:71` (`go c.run()`), `:170` (`go c.dispatchReplies(...)`); `gateway/cmd/gateway/main.go:317-321` (Redis relay), `:325-331` (`activeUsers.Run`, `mtr.Sampler`, `mtr.Serve`).
- **Проблема:** единственная защита от паник — `sentry.RecoverWithContext` вокруг цепочки хендлера и `sentryhttp{Repanic:true}` (полагается на встроенный recover `net/http` для per-connection горутин). Ни один вариант не покрывает **самостоятельно запущенные** `go ...` горутины. Непойманная паника в такой горутине завершает **весь Go-процесс**, а не одну горутину.
- **Сценарий:** любой неучтённый edge-кейс (nil-разыменование, index out of range, редкая гонка, неожиданный формат сообщения из Redis/RabbitMQ) в высоконагруженном `Hub.Route` (работает на каждое realtime-сообщение для сотен подписчиков) → полный отказ обслуживания для всех пользователей.
- **Фикс:** обернуть каждую `go ...` горутину в общий хелпер `safego.Go(fn)` с `defer recover()` + `slog.Error`/`sentry.CaptureException`.

**H2. Нет rate-limiting / anti-brute-force на auth-эндпоинтах** *(gateway + identity, сведено)*
- **Файлы:** `gateway/cmd/gateway/main.go:132-201` (`/api/auth/login|register|refresh`, `oauth/*/callback`); `identity-service/serve.py:144-379` (`rpc_login`, `rpc_register`, `rpc_refresh`, `rpc_oauth_callback`); `nginx/nginx.conf` (нет `limit_req`).
- **Проблема:** во всём gateway нет rate-limiting на HTTP-уровне (только внутренний WS-throttling `MaxPublishPerSecond=60`). Нет блокировки после N неудач, CAPTCHA, per-IP/per-account throttling ни на gateway, ни на nginx, ни в identity-svc.
- **Сценарий:** credential stuffing / brute-force по `login` (401 без задержки/лока), спам-регистрации, злоупотребление `refresh`.
- **Фикс:** token-bucket в Go-gateway (по IP и/или IP+email) для `login`/`register`/`refresh`/`oauth callback`, либо `limit_req_zone` в nginx; прогрессивная задержка/временный лок после серии неудач + метрики/алерты на всплески 401.

**H3. Захват player-профиля через матчинг по display name**
- **Файлы:** `identity-service/src/services/oauth_service.py:569-633` (`_find_player_by_provider_record`), `:710-729` (`_link_player_if_unowned`), `:739-770` (`_attach_verified_social_account`).
- **Проблема:** помимо надёжного матчинга по `provider_user_id`, код матчит игрока по нормализованному хэндлу из `username`+`display_name` (Discord `global_name` — свободно редактируемый; Battle.net `preferred_username`/`battle_tag`). Если найден ровно один игрок с таким хэндлом без `auth_user_id` (частая ситуация — игроки создаются из логов/регистраций) — связь `player.auth_user_id` ставится автоматически, хэндл помечается `is_verified=True`.
- **Сценарий:** атакующий ставит Discord-ник = чужому неподтверждённому хэндлу → логинится через Discord → присваивает чужую турнирную идентичность (история матчей, статистика, роли/`workspace_member`).
- **Фикс:** авто-привязка `player.auth_user_id` только по криптографически проверенному `provider_user_id`; матчинг по имени — только как подсказка для ручного подтверждения.

**H4. Content-type аватаров/ассетов не проверяется по байтам файла** *(identity + shared, сведено)*
- **Файлы:** `backend/shared/clients/s3/upload.py:30-36` (`_validate_image`), используется в `upload_avatar` (`:39-70`), `upload_asset` (`:73-104`); точки вызова `identity-service/serve.py:873-897` (`rpc_me_avatar_set`), `app-service/src/rpc/users_admin.py:335`, `app-service/src/rpc/binary.py:42-69`.
- **Проблема:** `content_type` берётся из RPC-payload (клиент контролирует), проверяются только строка MIME и размер; magic bytes файла не сверяются. Объект сохраняется публично (`ACL=public-read`) с клиентским `ContentType`.
- **Сценарий:** загрузка произвольного бинарного/HTML/SVG-контента под видом `image/png`, публикация под публичным URL → S3 как открытый файлообменник; при отсутствии `X-Content-Type-Options: nosniff` — риск content-sniffing; нет защиты от decompression-bomb для downstream-кода.
- **Фикс:** валидировать реальный формат (`PIL.Image.open(BytesIO(data)).verify()` + сверка с `content_type` и re-encode) до `put_object`; проверить `nosniff` на раздаче из S3/CDN.

**H5. DoS балансировщика: нет лимитов входа/нагрузки для сессионных (не-API-key) пользователей**
- **Файлы:** `balancer-service/src/services/balancer/jobs.py:72-105` (`_enforce_api_key_upload_limit`, `_enforce_api_key_player_limit` — ранний `return` для не-API-key), `:356-359` (`run_balance` без `wait_for`); `core/security/api_key_limiter.py:105-141`; `services/balancer/config/defaults.py:96-106` (`time_limit_ms: int | None = None`).
- **Проблема:** `max_upload_bytes`/`max_players`/rate-limit/concurrent-jobs применяются только к `api_key`-принципалам. Сессионные пользователи (право `team.import`) не ограничены. `time_limit_ms` по умолчанию `None`, единственные пределы — `population_size≤1000`, `generation_count≤5000`, `island_count≤64` (до ~3.2·10⁸ оценок генома). `execute_balance_job` не оборачивает `run_balance` в таймаут.
- **Сценарий:** участник workspace с `team.import` создаёт job с большим ростером + `config_overrides={population_size:1000, generation_count:5000, island_count:64}` без `time_limit_ms`; несколько параллельных таких job'ов исчерпывают CPU (нет cap на конкурентность вне API-key).
- **Фикс:** применять лимиты и к сессионным пользователям (конечные пороги); обязательный дефолтный `time_limit_ms` (наследовать от `CONFIG_LIMITS["time_limit_ms"]["max"]`); обернуть `run_balance` в `asyncio.wait_for` как страховку.

**H6. Fail-open авторизация в `CrudDispatcher._list`**
- **Файл:** `backend/shared/rpc/crud.py:222-232` (сравнить с корректным `:234-238`).
- **Проблема:** `_get`/`_update`/`_delete` резолвят workspace через `_ws_from_id`, который бросает `HTTPException(400)` при отсутствии резолвера (fail-closed). А `_list` при отсутствующем `resolve_ws_for_list` **пропускает** `ensure_workspace_permission` — нужна только аутентификация, не конкретное право. Сегодня все реальные реестры резолвер задают (дыры нет), но это footgun в общей инфраструктуре: одна забытая строка в конфиге новой сущности откроет её на чтение любому авторизованному пользователю в любом workspace.
- **Фикс:** сделать `_list` симметричным — при `not public_read` требовать `resolve_ws_for_list is not None`, иначе `HTTPException(400)`.

**H7. `MissingIdentityError` → 403 вместо 401 в общем CRUD-движке**
- **Файл:** `backend/shared/rpc/crud.py:244-245` (`return rpc_error("forbidden", ...)`).
- **Проблема:** все остальные сервисы маппят `MissingIdentityError` → `"unauthorized"` (`app-service/src/rpc/_common.py:135-136`, `balancer-service/src/rpc/_common.py:56,154-155`, аналогично parser/tournament/analytics). Только `CrudDispatcher` возвращает 403 (закреплено тестом `shared/tests/test_rpc_crud.py:171-174`).
- **Сценарий:** истёкший/отсутствующий токен на `rpc.app.admin.update`/`rpc.tournament.admin.*` → клиент получает 403 вместо 401. Фронтенд-логика проактивного refresh/логаута (`project_frontend_token_refresh_fix`) ждёт 401 как «сессия мертва» → вместо relogin пользователь видит «нет доступа».
- **Фикс:** привести `_envelope` в `crud.py` к `rpc_error("unauthorized", "Not authenticated")`.

### Архитектура

**H8. Fail-open workspace-скоупинг (риск утечки данных между воркспейсами)**
- **Файлы:** `app-service/src/core/workspace.py` (`workspace_filter(None) → []`, `apply_workspace_filter(query, None) → query без фильтра`); `app-service/src/rpc/users.py:34-35` (`_ws_id(data) = c.q1(data, "workspace_id", int)` с дефолтом `None`) → `resolve_workspace_context(session, None)` = глобальный grid + нулевая фильтрация.
- **Проблема:** любой read-путь, где забыли протянуть `workspace_id`, тихо возвращает данные всех воркспейсов. Не теоретический риск: последние 4 коммита ветки — фиксы этого класса (`d0a1201f`, `32957261`, `975380b3`, `7f0d3676`), утечки доезжали до прод-путей.
- **Фикс:** инвертировать на fail-closed — `workspace_id` обязателен в доменных read-flow; «все воркспейсы» — только явный типобезопасный sentinel (`ALL_WORKSPACES`, не `None`); тест-контракт (по аналогии с `test_repository_boundaries.py`), что каждый не-`public_read` read принимает и применяет `workspace_id`.

**H9. Дублирование доменной логики app↔tournament (P3-A не завершён)**
- **Файлы:** `app-service/src/services/statistics/flows.py` vs `tournament-service/src/services/statistics/flows.py` — байт-в-байт идентичны; то же по `services/hero`, `services/user`, `services/map`, `schemas/gamemode`, `schemas/map`.
- **Проблема:** оба сервиса — headless-RPC-воркеры, читающие одни таблицы через shared ORM. Первопричина не устранена — удвоена поверхность поддержки и сохранён неизбежный schema-drift (два воркера могут вернуть разные формы для одного ресурса). `docs/architecture/p3-strategic-refactors.md` описывает решение через удалённый Kong.
- **Фикс:** один сервис — owner каждого ресурса (напр. tournament-service — write+read турнирного домена, app-service — только агрегирующие reads); удалить байт-идентичные копии; обновить доку.

**H10. `shared/` — «скрытый 9-й сервис» с доменной логикой и deploy-coupling**
- **Файлы:** `shared/services/bracket/*`, `shared/services/achievement_effective.py`, `shared/services/tournament_computation.py`, `shared/services/division_grid_*`, `shared/services/realtime_publisher.py`, `shared/domain/*`; `shared/models/__init__.py` (импорт 33 модулей через `*`).
- **Проблема:** `shared/` содержит бизнес-логику + всю ORM. Любой фикс в `shared.services.bracket` требует пересборки образов всех 8 сервисов; wildcard-импорт всех таблиц означает, что каждый сервис линкует полную схему БД. Все сервисы делят один PostgreSQL и одно дерево миграций → де-факто распределённый монолит (P3-D, отложено).
- **Фикс (квартальная задача):** split на `shared-core` (observability/errors/clients/messaging), `shared-models` (ORM+schemas), `shared-domain` (bracket/achievement/computation) с per-service pin. До тех пор — не наращивать `shared.services.*`.

### Производительность

**H11. Некэшируемый полный пересчёт rarity на каждый просмотр профиля**
- **Файлы:** `app-service/src/services/achievements/service_v2.py:155-173` (`get_all_rules_with_rarity`), вызывается из `flows_v2.py:158` (`get_user_achievements`), RPC `rpc/achievements.py:33-58`.
- **Проблема:** `get_rarity_subq(workspace_id=...)` без `rule_ids`/`user_ids` агрегирует `build_effective_achievement_rows_subquery` (UNION ALL + коррелированный EXISTS + GROUP BY) **по всем правилам и всей истории воркспейса** + отдельный подзапрос для знаменателя. Вызывается на каждый просмотр вкладки «Достижения» (`include_locked=True`), но результат **не зависит** от того, чей профиль открыт → N просмотров = N идентичных пересчётов. `achievements_cache_ttl` здесь не применяется.
- **Фикс:** кэшировать `get_all_rules_with_rarity(workspace_id)` через cashews с TTL + инвалидация по событию пересчёта, либо материализовать rarity в таблицу/MV (как `mv_hero_global_stats`).

**H12. N+1 + одна долгая транзакция в импорте команд балансировщика**
- **Файл:** `balancer-service/src/services/team.py:37-133` (`bulk_create_from_balancer`).
- **Проблема:** на каждого игрока — ~5 последовательных запросов (`find_by_battle_tag`, `existing_player`, `existing_globally` без tournament-scope, `existing_role`, `get_or_create_workspace_member`). 20 команд × 6 игроков = ≥600 последовательных запросов в одной транзакции с единственным `commit()` в конце. Под pgBouncer (transaction-pooling) держит pooled backend-коннекшн на всё время.
- **Фикс:** предзагрузить кандидатов батчем (`user.id IN (...)`, `WorkspaceMember.player_id IN (...)`), построить in-memory индексы, делать только `INSERT`ы (`add_all`); либо разбить на мелкие транзакции.

**H13. ORDER BY по коррелированному скалярному подзапросу в Users Overview**
- **Файлы:** `tournament-service/src/services/user/service.py:810-858` (`get_overview_users`, сортировка `:838-852`); дубль `app-service/src/services/user/service.py:853-905`.
- **Проблема:** при `sort=tournaments_count|achievements_count|avg_placement` в `ORDER BY` подставляется коррелированный `scalar_subquery` (джойнит `Player→Team→Tournament→WorkspaceMember` по `player_id`). `ORDER BY <corr.subquery> LIMIT n OFFSET m` вычисляет выражение для **всей** отфильтрованной популяции, а не только для страницы. Публичный каталог/лидерборд. Усугубляется C4.
- **Фикс:** предвычислять поля в материализованном срезе (обновлять по событию) или кэшировать порядок id на короткий TTL; как минимум — индекс из C4.

---

## 🟡 MEDIUM

### Лимиты тела запроса / DoS
- **JSON identity-эндпоинты без лимита размера** — `gateway/internal/identity/handler.go:619-661` декодит `r.Body` напрямую без `http.MaxBytesReader` (в отличие от `edge/dispatch.go:24,118` с 12 MiB). Спасает только дефолт nginx 1MB при лимите памяти контейнера 128MB (`docker-compose.production.yml:551-558`). **Фикс:** явный `client_max_body_size` в nginx + `MaxBytesReader` в Go.
- **`ParseMultipartForm` без `MaxBytesReader`** — `gateway/internal/{app,balancer,parser,identity}/binary.go` спиллят избыток на диск без предела → исчерпание диска. Отдельно `identity/binary.go:42-51` (`AvatarSet`) парсит multipart **до** реальной валидации токена (проверяется лишь наличие `Bearer <непусто>`). **Фикс:** обернуть `r.Body` в `MaxBytesReader`; для identity — валидировать токен до парсинга.
- **Match-логи parser без cap** — `parser-service/src/rpc/logs.py:156-225` (`base64.b64decode` без лимита), `services/match_logs/flows.py:101-142` (DataFrame из всего файла без cap на строки). **Фикс:** верхний предел размера/строк до парсинга.
- **Аватар декодится в память до проверки размера** — `identity-service/serve.py:873-897` (`base64.b64decode` до `_validate_image`).

### Gateway / сеть
- **Спуфинг клиентского IP** — `gateway/internal/identity/handler.go:672-701` (`clientMeta`) берёт **первый** (левый, клиентский) элемент `X-Forwarded-For`, а не последний доверенный хоп; nginx использует `$proxy_add_x_forwarded_for` (добавляет, не перезаписывает). Плюс доверие `CF-Connecting-IP`/`True-Client-IP`/`X-Client-IP`. Пишется в `ip_address` сессий (login/oauth). **Фикс:** брать `X-Real-IP` (nginx перезаписывает через `$remote_addr`) либо последний элемент XFF; убрать доверие CF-заголовкам, если Cloudflare не обязателен.
- **Нет `ReadTimeout` на HTTP-сервере** — `gateway/cmd/gateway/main.go:364-371` задаёт только `ReadHeaderTimeout`; чтение тела не ограничено по времени → slowloris по телу. **Фикс:** `ReadTimeout` 30-60s для обычных запросов, длинные таймауты только для WS/balancer.
- **WS без проверки Origin (CSWSH)** — `gateway/internal/ws/handler.go:54-58` (`InsecureSkipVerify:true`); nginx (`server_name _`) проксирует `/ws` для любого Origin. Смягчено `sameSite=lax` на фронте (`frontend/src/lib/auth-tokens.ts:46-48`), но это вне контроля gateway. **Фикс:** `OriginPatterns` со списком легитимных origin.

### RBAC / сессии
- **`role.assign/create/update` без потолка прав назначающего** — `identity-service/src/services/rbac_flows.py:496-545, 337-384, 283-334`. Проверяется только наличие `role.assign` и т.п., без сравнения с эффективными правами actor'а. Плюс `shared/models/auth_user.py:183-191, 242-274` хардкодит имя роли `"admin"` как полный байпас, а `create_role` не резервирует системные имена → с `role.create`+`role.assign` без superuser можно создать роль `admin`. **Фикс:** требовать, чтобы у actor'а были все permission целевой роли; резервировать имена (`admin`/`owner`/`member`/`player`); не опираться на имя роли как маркер доверия.
- **Отзыв сессии не инвалидирует access-JWT** — `auth_flows.py:164-201` отзывает только refresh; access-JWT (TTL 15 мин) с `sid` не проверяется на отзыв в `auth_token_helpers.py:159-181`. **Фикс:** Redis-блэклист отозванных `sid` (TTL = остаток жизни токена) или короче TTL access.
- **Workspace-scoped deny молча не работает для self-service** — `rbac_flows.py:765-897` даёт навесить deny на `account.avatar` с `workspace_id`, но `serve.py:878` вызывает `is_denied("account","avatar")` без `workspace_id` → матчит только глобальные denies. Админ видит запись, но она не применяется. **Фикс:** запретить `workspace_id` для permission без ws-контекста, либо прокидывать актуальный ws_id.
- **Единый секрет для всего** — `JWT_SECRET_KEY` подписывает access/service JWT (`auth_service.py:233-250`), хэширует refresh (`:224-231`), OAuth state (`oauth_service.py:458-466`), API-key secrets (`api_key_service.py:55-60`). Нет domain separation. **Фикс:** HKDF от мастер-секрета с разным `info` на назначение.

### Прочее качество / БД
- **`CircuitBreaker.call()` принимает coroutine, а не фабрику** — `shared/clients/circuit_breaker.py:76-116` (`raise CircuitBreakerOpen()` на `:101` до `await` на `:111`); `shared/clients/http_client.py:145-149` создаёт coroutine заранее → `RuntimeWarning: coroutine never awaited` при открытой цепи (реально на OverFast rank-fetch, `parser-service/src/services/overwatch_rank/client.py:99`). **Фикс:** принимать `Callable[[], Awaitable[T]]`, вызывать фабрику после проверки состояния.
- **`initcap(name)` без функционального индекса** — `balancer-service/src/services/user.py:108-123` (`find_by_battle_tag`); `ix_user_name_trgm` (GIN) обслуживает ILIKE, но не `initcap(name) == x` → seq scan. **Фикс:** `CREATE INDEX ON players.user (initcap(name))` или нормализованная колонка.
- **Постадийный цикл в `calculate_for_tournament`** — `tournament-service/src/services/standings/service.py:942-975` (запрос на каждую стадию). Число стадий мало, но на пути пересчёта стендингов после каждого матча. **Фикс:** один `get_by_tournament_id` + `groupby(stage_id)`.
- **`list_registrations` без пагинации** — `tournament-service/src/services/registration/admin.py:1093-1131` (5-уровневый eager-load без LIMIT). **Фикс:** `PaginationParams`/явный cap.
- **OFFSET-пагинация в общем движке** — `shared/core/pagination.py:99-105`, `shared/repository/base.py:67-94`; для безграничных каталогов (Users overview, achievement earners `service_v2.py:199-229`) стоит O(offset). **Фикс:** курсорная пагинация (`WHERE id > :cursor`) для 2-3 реально безграничных списков.
- **BattleTag не валидируется перед подстановкой в URL OverFast** — `parser-service/src/services/overwatch_rank/client.py:36-38,107-111` (`f"/players/{player_id}/summary"`); `shared/services/social_identity.py:116-211` сохраняет `username` без `battle_tag_regex` (применяется только в CSV-импорте). Произвольные символы (`/`, `..`) в пути исходящего запроса к доверенному хосту. **Фикс:** применять валидатор при создании/обновлении social account с `BATTLENET`.

### Архитектура (MEDIUM)
- **Outbox дренит только tournament-service** — `parser-service/.../match_logs/flows.py:54,65,78` пишет в `event_outbox`, но дренера в `parser-service/serve.py` нет; единственный `drain_outbox` — в `tournament-service/serve.py`. Работает только т.к. БД одна. Нет колонки-владельца в `EventOutbox` → нельзя партиционировать. SPOF для parser-событий. **Фикс:** выделить дренаж в отдельный воркер или добавить `source_service`.
- **`.importlinter` только у app-service и устарел** — `app-service/.importlinter` ссылается на несуществующие `src.routes`; остальные 5 сервисов без контроля слоёв. **Фикс:** обновить контракты под RPC, развернуть на все сервисы, добавить `lint-imports` + `alembic heads == 1` в CI.
- **Псевдо-GraphQL `entities=list[str]`** — строковые проекции без whitelist/cost-cap/типизации (P3-B, ~44 эндпоинта). **Фикс:** типизированная проекция с cost-cap.
- **Незавершённая Phase C** — модели на `workspace_member_id`, но `workspace_member_id != player_id`; полу-мигрированные читатели с путаницей → утечка или пустые данные. `user_merge.py` должен мёржить per-workspace members. `.user_id` в 417 местах / 96 файлах. **Фикс:** прогнать инварианты ТЗ + cross-workspace-проверку на копии прода; аудит оставшихся `Player`/`registration`/`achievement` читателей; деплой «миграция+код вместе» с планом отката до `iwrefac04`.

---

## 🟢 LOW

| # | Файл | Суть |
|---|---|---|
| L1 | `shared/clients/auth_client.py` | Мёртвый код (auth-service decommissioned) — удалить/пометить reference-only |
| L2 | `identity-service/src/core/config.py:55` | `ALLOWED_ORIGINS` — мёртвая настройка HTTP-эры |
| L3 | root `pyproject.toml` | `mixtura-balancer-tournament` в workspace-members, среди сервисов нет — шум в резолве |
| L4 | `shared/messaging/outbox.py:91-95` | Сбой publish фиксируется в БД без `logger.warning` → видимость только через SELECT |
| L5 | `shared/core/enums.py:151,154` | Дубль ключа `LogStatsName.ShotsMissed` в dict-литерале; включить lint F601 |
| L6 | `shared/core/__init__.py:1-3` | Wildcard-импорты без `__all__` в `db.py`/`enums.py` → namespace pollution |
| L7 | `identity-service/.../auth_service.py:344-354` | User enumeration через разные сообщения register (login защищён) |
| L8 | `shared/clients/s3/client.py:69-78,130-138` | `get_object`/`head_object` схлопывают все `ClientError` (кроме NoSuchKey) в `None` → «нет доступа» неотличимо от «не найдено» |
| L9 | `shared/clients/s3/client.py:187-194` | `delete_prefix` по одному объекту вместо батч `delete_objects` |
| L10 | `shared/core/pagination.py:130-141` | Ветка `model=None`: sort через regex, не whitelist колонок (сегодня прикрыто `Literal` выше) |
| L11 | `shared/rpc/crud.py:111-113` | `EntityConfig.repo` создаёт новый `BaseRepository` на каждый вызов → `cached_property` |
| L12 | `shared/rpc/crud.py:8-12` | Docstring учит неаннотированному `msg` (баг-класс `lesson_faststream_rpc_msg_annotation`) |
| L13 | `parser-service/.../achievement/engine/evaluator.py:26-65`, `validation.py:104-140` | Условное дерево правил без лимита глубины → `RecursionError` |
| L14 | `parser-service/.../match_logs/flows.py:254-283,348-373` | N+1 при сопоставлении игроков лога (батчится IN) |
| L15 | `app-service/.../admin/user_merge.py:390-780` | Циклы запросов при мёрдже (админ, редко) |
| L16 | `gateway/internal/config/config.go:93,130` | Дефолт `guest:guest` для RabbitMQ; `sslmode=disable` для Postgres |
| L17 | `gateway/internal/config/config.go:85,115` | Fail-open дефолт `GATEWAY_DOCS_ADMIN` при непредвиденном окружении; JWT без `iss`/`aud`, нет проверки длины секрета; nginx access-log пишет query string (`?token=`) |

---

## ⚙️ Edge / инфраструктура

- **`nginx/nginx.conf`** — нет `limit_req`/`limit_conn`/`client_max_body_size`; `proxy_read_timeout 3600s` + `proxy_send_timeout 3600s` + `proxy_buffering off` на **всех** запросах = поверхность slowloris/DoS (медленный клиент держит соединение час). Access-log не настроен → дефолтный `combined` пишет query string (включая `?token=` на `/ws`). **Фикс:** `limit_req_zone` для auth-путей, `client_max_body_size`, разумные таймауты для не-WS location, `log_format` без query string.
- **`test.py` в корне репозитория** — рабочий PoC HTTP/2 HPACK-bomb DoS против nginx (untracked, «for authorized testing only»; 59:1 амплификация памяти + window-stall). Сигнал, что уязвимость edge реально тестировалась. **Действие:** убрать из корня (в `scripts/security/` или отдельный приватный репо), закрыть саму уязвимость на уровне Traefik/nginx (лимиты HTTP/2 concurrent streams, header table size).
- **Позитив по gateway:** метрики (`:9110`) не публикуются наружу (нет `ports:` в compose); admin-доки в проде выключены (`SENTRY_ENVIRONMENT=production`); `.env` с реальными секретами не закоммичены (`.gitignore` корректен).

---

## ✅ Что сделано хорошо

- **Транзакционный outbox** (`shared/messaging/outbox.py`) — событие пишется в ту же транзакцию, дренаж через `FOR UPDATE SKIP LOCKED` + экспоненциальный backoff; обходит проблему pgBouncer с LISTEN/NOTIFY.
- **JWT** жёстко зафиксирован на HS256 (`gateway/internal/auth/auth.go:41-46`) с тестом против `alg=none`; `exp`/подпись проверяются.
- **WS-ACL superuser-байпас** исправлен и покрыт тестами (`acl_test.go`) — прошлый инцидент из памяти не воспроизводится; неизвестные топики — deny (fail-closed).
- **Identity передаётся в теле RPC**, а не заголовками — классический header-injection в upstream архитектурно неприменим (транспорт — RabbitMQ RPC, не HTTP).
- **Пароли** — bcrypt + timing-safe (`bcrypt.checkpw`); API-key/service secrets — `hmac.compare_digest`.
- **OAuth `state`** — HMAC + TTL + `compare_digest` (полноценная CSRF-защита callback).
- **Refresh-токены** хранятся хэшированными (HMAC-SHA256) с reuse-detection и точечным отзывом сессии; idempotency-кэш на конкурентный refresh.
- **IDOR по сессиям/ключам/OAuth-подключениям** закрыт (везде проверка `owner_id == current_user.id`).
- **Идемпотентность аналитики** восстановлена (delete-by-`(tournament_id, algorithm_id)` → insert; `match_quality_runner` больше не ломается на backfill).
- **SQL-инъекций нет** — параметризованный SQLAlchemy; сортировка через whitelist ORM-колонок.
- **FFI-граница pyo3/Rust** корректна — `panic = "abort"` не задан (unwind → Python-исключение), вход валидируется в `Context::from_request`, `.unwrap()` только в тестах.
- **Единый generic CRUD-движок** и **transaction-neutral репозитории** (flush, не commit); `EntityConfig` — frozen dataclass без мутабельных дефолтов.
- **Осознанный техдолг задокументирован** (`docs/architecture/layering.md`, `repository-boundaries.md`, `p3-strategic-refactors.md`).

---

## 📋 Приоритетный план действий

### Этап 1 — блокеры до релиза
1. **C4** — миграция `ix_workspace_member_player_id` (быстрый безопасный фикс, немедленный эффект).
2. **C1 + C2** — email-верификация + fail-closed OAuth email-matching (самые опасные: полный захват аккаунта).
3. **C3** — валидация S3-ключа по префиксу в импорте достижений.
4. **C5** — убрать глобальный `cache.disabling()` из `public_rpc.py:563`.
5. **H2** — rate-limiting на `/api/auth/*`.
6. **H1** — `recover` во всех фоновых горутинах gateway.

### Этап 2 — ближайшая итерация
- **H8** — fail-closed workspace-скоуп + тест-контракт (закрывает рецидивирующий класс утечек).
- **H4** — content-type аватаров по magic bytes.
- **MEDIUM-группа лимитов** — `MaxBytesReader` (JSON + multipart), `ReadTimeout`, cap на match-логи, лимиты балансировщика (**H5**).
- **H6 + H7** — fail-closed `_list` и 401-вместо-403 в `crud.py`.
- **H3** — авто-привязка player только по `provider_user_id`.
- Спуфинг IP, отзыв access-JWT, WS Origin, key-separation (HKDF).

### Этап 3 — техдолг (спланировать)
- **H9** — дедупликация app↔tournament (один owner на ресурс).
- **H10** — split `shared/` (квартальная задача).
- **H11 + H13** — материализация rarity и полей Users Overview; **H12** — батчинг импорта команд.
- Завершение/валидация Phase C одним атомарным выкатом.
- `.importlinter` на все сервисы + CI-гейт `alembic heads == 1`.
- Разведение дренажа outbox; удаление `test.py` из корня + закрытие nginx/HTTP-2 DoS.

---

## Приложение: сводная таблица по файлам

| Файл | Находки |
|---|---|
| `identity-service/src/services/auth_flows.py` | C1, M (отзыв access-JWT) |
| `identity-service/src/services/oauth_service.py` | C1, C2, H3 |
| `identity-service/src/services/rbac_flows.py` | M (role ceiling, ws-deny) |
| `identity-service/serve.py` | H2, H4, M (avatar mem) |
| `parser-service/src/services/achievement/import_export.py` | C3 |
| `parser-service/src/services/overwatch_rank/client.py` | M (battletag URL), circuit breaker |
| `parser-service/src/rpc/logs.py`, `services/match_logs/flows.py` | M (log cap), L14 |
| `balancer-service/src/services/balancer/jobs.py` | H5 |
| `balancer-service/src/services/team.py` | H12 |
| `balancer-service/src/services/user.py` | M (initcap index) |
| `shared/models/workspace.py` + `migrations/.../iwrefac04*` | C4 |
| `shared/rpc/crud.py` | H6, H7, L11, L12 |
| `shared/clients/s3/upload.py` | H4 |
| `shared/clients/s3/client.py` | L8, L9 |
| `shared/clients/circuit_breaker.py` + `http_client.py` | M (unawaited coroutine) |
| `shared/messaging/outbox.py` | M (parser SPOF), L4 |
| `shared/core/__init__.py`, `enums.py`, `pagination.py` | L5, L6, L10 |
| `app-service/src/core/workspace.py` + `rpc/users.py` | H8 |
| `app-service/src/services/achievements/service_v2.py` | H11 |
| `app-service` ↔ `tournament-service` (statistics/hero/user/map) | H9 |
| `tournament-service/src/rpc/public_rpc.py` | C5 |
| `tournament-service/src/services/user/service.py` | C4, H13 |
| `tournament-service/src/services/standings/service.py` | M (per-stage loop) |
| `tournament-service/src/services/registration/admin.py` | M (no pagination) |
| `gateway/internal/ws/hub.go`, `rpc/rpc.go`, `cmd/gateway/main.go` | H1 |
| `gateway/internal/identity/handler.go` | M (IP spoof), M (body limit) |
| `gateway/internal/*/binary.go` | M (multipart limit) |
| `gateway/internal/ws/handler.go` | M (WS Origin) |
| `gateway/cmd/gateway/main.go` | H2, M (ReadTimeout) |
| `gateway/internal/config/config.go` | L16, L17 |
| `nginx/nginx.conf` | Edge (limits, timeouts, log) |
| `test.py` (корень) | Edge (HPACK-bomb PoC) |

---

*Отчёт составлен на основе 6 параллельных ревью-агентов. Детали любого пункта могу развернуть; ключевые находки (C4, fail-open скоупинг, schema-drift) верифицированы напрямую.*
