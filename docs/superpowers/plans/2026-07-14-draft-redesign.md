# Draft Redesign — Implementation Plan

**Дата:** 2026-07-14  
**Основание:** [согласованная спецификация](../specs/2026-07-14-draft-redesign-design.md)  
**Статус:** готов к реализации

## Подход

Сначала сделать backend единственным источником истины для достижимости role-составов и закрыть инварианты тестами. Затем провести новые данные через typed RPC, gateway, OpenAPI и realtime, после чего перестроить admin и public draft UI на Editorial Tactical. Включать защиту поэтапно: `shadow → warn → enforce`, сохранив старую live-страницу под временным флагом на один турнирный цикл.

## Scope

**Входит:**

- глобальная feasibility-проверка всех незаполненных `(team, role)` slots;
- safe-only select/autopick/override и системная пауза при отсутствии safe option;
- аварийное добавление роли в snapshot игрока с preview и admin-only аудитом;
- новые feasibility/options/role-edit API и честный realtime/presence;
- пошаговая настройка и live control room в админке;
- отдельные captain/spectator режимы, shortlist и объяснимые блокировки;
- полная миграция draft-поверхностей на Editorial Tactical, включая mobile и WCAG AA;
- тесты, метрики производительности и управляемый rollout.

**Не входит:**

- изменение исходной регистрации при аварийном role edit;
- замена алгоритма обычного team balancer;
- новый основной lifecycle-статус `blocked`;
- публикация shortlist, registration notes или admin reason;
- переработка общей навигации админки и добавление новых UI-библиотек.

## Неподвижные инварианты

- Для обычного draft `rounds = team_size - 1`; независимые значения не принимаются скрыто.
- Safe pick означает, что после гипотетического назначения оставшихся игроков всё ещё можно сматчить со всеми открытыми `(team_id, role)` slots.
- Сервер повторяет feasibility-проверку внутри транзакции и не доверяет ранее полученному `options`.
- Autopick не имеет fallback на «первого доступного»: при пустом safe-наборе сессия становится `paused`, причина — `role_shortage`.
- Role edit разрешён только в `setup`, `ready` и `paused`, только добавляет роль в текущий `DraftPlayerRole` snapshot и требует причину.
- Публичные board/events не содержат `additional_info.notes`, audit reason и других организаторских данных.
- Текущий Alembic head на момент планирования — `iwrefac09`; новая миграция должна продолжить его и оставить один head.

## Задачи

### 1. Выделить переиспользуемое matching-ядро и реализовать draft feasibility

**Файлы:**

- создать `backend/balancer-service/src/services/role_matching.py`;
- создать `backend/balancer-service/src/services/draft/feasibility.py`;
- изменить `backend/balancer-service/src/services/balancer/algorithm/feasibility_analyzer.py`;
- создать `backend/balancer-service/tests/test_draft_feasibility.py`;
- сохранить зелёным `backend/balancer-service/tests/test_feasibility_analyzer.py`.

- [ ] Сначала зафиксировать тестами: недостаточный pool, Hall-deficit при достаточных счётчиках ролей, один flex на несколько критичных slots, safe/unsafe hypothetical pick и полное покрытие slots.
- [ ] Вынести из текущего balancer analyzer обобщённый augmenting-path matcher, принимающий произвольные candidate/slot edges; не связывать ядро с `Player` или ORM.
- [ ] В draft-адаптере строить открытые `(team_id, role)` slots из team size, капитанов и завершённых picks, а eligibility — из `DraftPlayerRole` доступных игроков.
- [ ] Возвращать структурированный report: `is_feasible`, unmatched slots, role deficits, blocking players/roles и безопасные варианты гипотетического назначения.
- [ ] Добавить performance-тест на 12 команд/~150 игроков с целевым p95 менее 300 мс для feasibility/options.

### 2. Встроить feasibility в lifecycle и все способы назначения игрока

**Файлы:**

- изменить `backend/balancer-service/src/schemas/draft.py`;
- изменить `backend/balancer-service/src/services/draft/lifecycle.py`;
- изменить `backend/balancer-service/src/services/draft/selection.py`;
- изменить `backend/balancer-service/src/services/draft/suggestions.py`;
- изменить `backend/balancer-service/src/services/draft/clock.py`;
- расширить `backend/balancer-service/tests/test_draft_schemas.py`, `test_draft_suggestions.py`, `test_draft_clock.py`, `test_draft_integration.py`.

- [ ] Валидировать `rounds = team_size - 1` и согласованность количества captains/picks как в Pydantic schema, так и в lifecycle service.
- [ ] Запрещать `start`/`resume` при неразрешимом preflight и возвращать машинный код с деталями дефицита.
- [ ] В `select` и `override` под существующим expected-version/locking повторно вычислять hypothetical feasibility до `_finalize`.
- [ ] Фильтровать suggestions по safe options, сохраняя score и человекочитаемое объяснение.
- [ ] Удалить autopick fallback `available[0]`; при пустом safe-наборе атомарно поставить `paused` и вернуть structured `role_shortage` outcome для clock/RPC.
- [ ] После rollback/re-seed/role mutation пересчитывать feasibility; resume оставлять явным действием администратора.

### 3. Добавить приватный аудит и безопасный role-edit workflow

**Файлы:**

- изменить `backend/shared/models/balancer/draft.py`;
- создать `backend/migrations/versions/draft0005_add_draft_audit_events.py` с `down_revision = "iwrefac09"`;
- создать `backend/balancer-service/src/services/draft/role_edit.py`;
- расширить `backend/balancer-service/tests/test_draft_models.py` и `test_draft_integration.py`.

- [ ] Добавить `DraftAuditEvent(session_id, actor_auth_user_id, action, entity_type, entity_id, reason, before_json, after_json, created_at)` с индексами по session/time и FK с подходящей delete-семантикой.
- [ ] Реализовать preview и commit одним endpoint-контрактом через `preview_only`: preview выполняет те же проверки без записи, commit повторяет их в транзакции.
- [ ] Разрешить только новую роль, допустимый canonical role, состояния `setup/ready/paused`, обязательную непустую причину и явное подтверждение отсутствующего rank.
- [ ] На commit вставить `DraftPlayerRole`, обновить typed role-rank snapshot при наличии значения и записать before/after/reason в audit.
- [ ] Не изменять BalancerRegistration и не помещать reason в `WorkspaceEvent`.
- [ ] Проверить upgrade/downgrade миграции и единственный Alembic head.

### 4. Провести контракты через RPC, gateway, OpenAPI и realtime

**Файлы:**

- изменить `backend/balancer-service/src/schemas/draft.py`, `src/rpc/draft.py`, `src/openapi_schemas.py`, `src/openapi_docs.py`;
- изменить `backend/balancer-service/src/services/draft/board.py` и `realtime.py`;
- изменить `gateway/internal/balancer/routes.go`, `routes_test.go`;
- изменить `gateway/internal/ws/topic.go`, `handler.go`, `handler_test.go`;
- перегенерировать `gateway/internal/openapi/schemas.json` через `backend/scripts/export_openapi_schemas.sh`;
- при необходимости расширить `gateway/internal/apidocs/groups_test.go` и `gateway/internal/edge/apiv1_guard_test.go`.

- [ ] Добавить typed RPC/routes для `GET .../feasibility`, `GET .../picks/{pick_id}/options`, `POST .../players/{player_id}/roles` с admin/captain permission matrix из спецификации.
- [ ] Добавить `preview_only` также в seed request, чтобы re-seed diff в UI считался сервером без мутации, а commit повторно проверял исходную версию.
- [ ] Расширить `draft.pick_made` полями `target_role`, `target_rank_value`, `pick_version`; добавить `draft.player_updated` и `draft.blocked` без приватных данных.
- [ ] Расширить gateway presence с `:balancer` на `:draft`, выдавая `draft.presence` с реальными auth user IDs и отдельным anonymous viewer count либо честно не показывая неподдерживаемый счётчик.
- [ ] Удалить инъекцию registration notes в публичный board snapshot и добавить regression-тест на отсутствие notes/reason в board/events.
- [ ] Проверить отсутствие конфликтов ServeMux и наличие request/response schemas в сгенерированном OpenAPI.

### 5. Расширить frontend data layer и явную модель состояний

**Файлы:**

- изменить `frontend/src/types/draft.types.ts`;
- изменить `frontend/src/services/draft.service.ts`;
- изменить `frontend/src/lib/tournament-query-keys.ts`;
- изменить `frontend/src/app/(site)/tournaments/[id]/draft/_hooks/useDraftData.ts`;
- изменить `frontend/src/app/(site)/tournaments/[id]/draft/_lib/draft-logic.ts` и `.test.ts`;
- добавить `vitest` и `test` script в `frontend/package.json`/`bun.lock`.

- [ ] Типизировать feasibility, options, blocked reason, role-edit preview/result, enriched events и presence.
- [ ] Добавить узкие query keys для feasibility/current-pick options и методы сервиса для новых endpoints/preview.
- [ ] На realtime обновлять или инвалидировать только затронутые board/options/feasibility queries; на reconnect восстанавливать snapshot + cursor.
- [ ] Хранить реальную presence map и connection state; удалить игнорирование `draft.presence` и любые вычисленные фальшивые online/viewer значения.
- [ ] Не очищать выбранного игрока/роль до успешной mutation; stale/conflict errors должны refetch-нуть данные и сохранить понятное объяснение.
- [ ] Блокировать confirm при reconnecting/stale version до получения актуального options response.

### 6. Перестроить настройку draft в guided setup wizard

**Файлы:**

- оставить `frontend/src/app/admin/tournaments/[id]/components/DraftSessionDashboard.tsx` тонким orchestrator;
- создать компоненты в `frontend/src/app/admin/tournaments/[id]/components/draft/` для `DraftSetupWizard`, шагов config/pool/captains/order/review/ready и preview;
- изменить `frontend/src/i18n/messages/en.json` и `ru.json`.

- [ ] Реализовать шесть согласованных шагов с сохранением локального draft формы и серверной валидацией при переходах.
- [ ] Связать team size и rounds, добавить pick-time presets, format preview, autopick explanation и сворачиваемый Advanced.
- [ ] Показать pool readiness: required/actual players, role coverage, ranks/accounts/exclusions и blocking feasibility deficits.
- [ ] Реализовать выбор captains, inline team names, фиксированный счётчик и manual order через установленный `dnd-kit`; random order сохраняет seed.
- [ ] На review показывать итоговый snake/custom schedule, privacy checklist и все blocker/warning состояния.
- [ ] Перед re-seed запрашивать dry-run, показывать diff teams/players/picks и требовать подтверждение; после start запрещать re-seed.

### 7. Реализовать admin live control room и разрешение role conflicts

**Файлы:**

- создать в admin draft-каталоге `AdminControlRoom.tsx`, `FeasibilityStatus.tsx`, `CaptainPresence.tsx`, `LifecycleControls.tsx`, `ResolveRoleConflictDialog.tsx`;
- изменить `DraftSessionDashboard.tsx`, frontend draft service/types и i18n catalogs.

- [ ] После start заменить редактируемый wizard на read-only summary + lifecycle controls + ссылку на live board.
- [ ] Показать реальную готовность/подключение captains, текущий pick, clock, feasibility и системную причину паузы.
- [ ] В conflict dialog показать unmatched team-role slots, оставшихся игроков и declared roles; потребовать role, rank или явное «без rank», и reason.
- [ ] До подтверждения вызвать role-edit preview и показать before/after feasibility; commit разрешить только по актуальной версии.
- [ ] Для override/rollback/cancel/export показывать последствия, обязательные confirmations и mutation errors; после role edit не делать auto-resume.
- [ ] Не добавлять public audit read: в этом релизе история остаётся в admin-only таблице, а UI показывает результат конкретной mutation без выдачи чужих причин.

### 8. Разделить public live page на captain и spectator workspaces

**Файлы:**

- изменить `frontend/src/app/(site)/tournaments/[id]/draft/page.tsx`;
- заменить монолит `DraftBoard.tsx` компонентами `DraftPageHero`, `DraftConnectionStatus`, `CaptainDraftWorkspace`, `SpectatorDraftWorkspace`, `DraftOrder`, `PlayerPool`, `PlayerInspector`, `CaptainShortlist`, `PickCommandBar`, `CurrentPick`, `TeamRosters`, `DraftEventFeed`;
- оставить `DraftClock.tsx` только как изолированную clock primitive либо адаптировать её к новой композиции.

- [ ] Выбирать captain/spectator режим по серверным правам; admin controls не смешивать с публичной иерархией.
- [ ] Для captain загрузить options, визуально исключить unsafe player-role choices и показывать структурированную причину блокировки.
- [ ] Сделать shortlist приватным локальным состоянием; filters/sort хранить в URL, selection/inspector — в transient state.
- [ ] Выполнять pick через review/confirm, сохраняя выбор при ошибке и объявляя success/error через спокойный `aria-live`.
- [ ] Для spectator показать current pick, полные rosters и event feed без интерактивных обещаний и приватной стратегии.
- [ ] Покрыть loading, empty, error, reconnecting, paused, role_shortage, completed и no-filter-results состояния.

### 9. Полностью перевести draft UI на Editorial Tactical

**Файлы:**

- заменить `frontend/src/app/(site)/tournaments/[id]/draft/_components/DraftBoard.module.css` на минимальный module только для timer geometry/realtime animation либо удалить после декомпозиции;
- использовать `frontend/src/components/site/PageHero.tsx`, глобальные tokens из `frontend/src/app/globals.css` и правила `docs/design-book.md`;
- применить ту же схему к новым admin wizard/control-room компонентам.

- [ ] Удалить локальные `--draft-*`, hex background, избыточные glow, condensed-uppercase hierarchy, fake telemetry и старую фиксированную bottom panel.
- [ ] Собрать header через `PageHero/HeroFrame`, `HeroCoord`, `HeroStat`, `HeroStamp`; ограничить контент `max-width: 1400px`.
- [ ] Использовать Onest/Inter/JetBrains Mono по проектной схеме, один teal UI-accent, semantic role colors и принцип `Air over boxes`.
- [ ] На notebook сворачивать order в sidebar; на mobile дать tabs `Пул / Моя команда / Порядок`, compact timer bar и safe-area bottom sheet; не использовать `100vh`.
- [ ] Обеспечить `focus-visible`, `aria-pressed`, настоящие links, нецветовые статусы, touch targets ≥44 px, reduced motion и WCAG AA contrast.
- [ ] Визуально проверить обе локали и все состояния на desktop 1440, notebook 1024, mobile 390 и узком mobile 320.

### 10. Добавить rollout controls, наблюдаемость и финальную проверку

**Файлы:**

- изменить `backend/balancer-service/src/core/config.py` и env example/config documentation;
- добавить draft feasibility metrics через существующую observability abstraction;
- обновить `backend/balancer-service/README.md` и draft runbook/release notes;
- удалить legacy компоненты/tokens только после согласованного турнирного цикла.

- [ ] Ввести `DRAFT_FEASIBILITY_MODE=shadow|warn|enforce` и отдельный временный frontend flag для old/new draft UI; неизвестное значение должно fail-fast.
- [ ] В shadow/warn логировать unsafe decisions, duration, pool/team sizes и deficit category без PII; в enforce включить hard-block только для новых sessions.
- [ ] Добавить counters для blocked picks, role edits, autopick pauses и reconnect/stale conflicts; latency histogram должен подтверждать p95 target.
- [ ] Прогнать один тестовый draft end-to-end, затем один реальный цикл с возможностью быстрого возврата UI-флага; backend invariant не откатывать в обход сохранённых данных.
- [ ] После стабильного цикла удалить старый `DraftBoard.tsx`, legacy CSS/`--draft-*`, временный UI flag и shadow compatibility code.

## Validation

- Backend unit/integration: `cd backend && uv run pytest balancer-service/tests/test_draft_feasibility.py balancer-service/tests/test_draft_schemas.py balancer-service/tests/test_draft_suggestions.py balancer-service/tests/test_draft_clock.py balancer-service/tests/test_draft_models.py balancer-service/tests/test_draft_integration.py -q`.
- Migration: `cd backend && uv run alembic heads` возвращает один head; на тестовой БД выполнить upgrade, downgrade на одну revision и повторный upgrade.
- OpenAPI: `bash backend/scripts/export_openapi_schemas.sh`, затем проверить отсутствие diff после повторного запуска.
- Gateway: `cd gateway && go test ./internal/balancer ./internal/ws ./internal/apidocs ./internal/edge`.
- Frontend logic: `cd frontend && bun run test --run` после добавления script/dependency.
- Frontend static: `cd frontend && bun run lint`; `next build` не запускать.
- Manual E2E: setup → seed/re-seed preview → start → safe captain picks → forced role shortage → pause → role-edit preview/commit → manual resume → complete → idempotent export.
- Privacy: anonymous spectator snapshot/event payload не содержит notes, shortlist, audit reason; options недоступен постороннему капитану.
- Accessibility/visual: keyboard-only flow, screen reader announcements, reduced motion, contrast, 44 px touch targets и согласованные viewport checks.

## Открытые вопросы

Блокирующих вопросов нет. Для preview используется тот же mutation endpoint с `preview_only`, а rollout-флаги вводятся в balancer settings, поскольку общего feature-flag framework в репозитории сейчас нет.
