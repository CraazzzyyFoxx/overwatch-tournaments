# Forced-Flex турниры и макс-ранг для баланса — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать организатору режим турнира «все игроки всегда флексы»
(`flex_role.mode = "forced"` в конфиге формы регистрации) и считать в таком
турнире силу игрока как максимальный ранг по всем его ролям — и в балансере, и в
драфте.

**Architecture:** Forced-flex — факт о **ролях**: нормализуется при записи общим
хелпером на обоих путях записи (`build_registration_roles` публичный,
`replace_registration_roles` админка+Sheets), после чего `is_flex_computed`
истинно автоматически. Макс-ранг — **политика** о рангах: производная на двух
границах чтения (`createSyntheticPlayerFromRegistration` на фронте,
`_map_registration` в драфте). Python-солвер и Rust-ядро `tournament_balancer` **не
изменяются**: право играть роль в балансере это наличие ключа роли в `ratings`
(`context.rs:100`), поэтому сплющивание рангов на все три роли даёт eligibility
бесплатно.

**Tech Stack:** Python (FastAPI, Pydantic, SQLAlchemy, pytest), TypeScript/React
(Next.js, shadcn/ui, next-intl), bun test + vitest.

**Спецификация:** [docs/superpowers/specs/2026-08-04-forced-flex-max-rank-design.md](../specs/2026-08-04-forced-flex-max-rank-design.md)

**Команды (проверены запуском):**
- Backend: `cd backend/tournament-service && uv run pytest <файл>` /
  `cd backend/balancer-service && uv run pytest <файл>`
- Frontend типы/lint: `cd frontend && bunx tsc --noEmit`, `bunx eslint <path>`
- Frontend bun-тесты: `cd frontend && bun test <файл>`
- Frontend vitest-тесты: `cd frontend && bunx vitest run <файл>`

**Две ловушки, о которых обязательно помнить:**
1. `vitest.config.ts:19-63` — allowlist. Новый vitest-тест вне `include` **не
   запустится, а suite отрапортует зелёным**. `workspace-helpers.test.ts` и
   `RoleStep.behavior.test.tsx` идут через `bun test`, не через vitest.
2. Сплющивать `rank_value` **обязательно вместе с** `ow_rank_value`, иначе
   `computeRankDeltasByRole` даёт ложные `rank_delta_warning`, и
   `runBalanceMutation` (`useBalancerMutations.ts:414`) откажется запускать баланс.

---

## Подготовка

- [ ] **Создать ветку от `develop`**

```bash
git checkout develop
git pull
git checkout -b feature/forced-flex-max-rank
```

---

## Task 1: Backend — контракт `flex_role.mode` и хелпер нормализации ролей

**Files:**
- Modify: `backend/tournament-service/src/schemas/registration.py:33-43`
- Modify: `backend/tournament-service/src/services/registration/_common.py`
- Create: `backend/tournament-service/tests/test_forced_flex_roles.py`

- [ ] **Step 1: Добавить `mode` в `BuiltInFieldConfig`**

В `schemas/registration.py` в класс `BuiltInFieldConfig` дописать поле рядом с
`require_verified` (тот же паттерн «поле только для одного ключа»):

```python
    # ``flex_role`` field only: "optional" (игрок сам решает) or "forced"
    # (турнир, где каждый играет любую роль — все роли пишутся as is_primary).
    # None/absent == "optional", so existing forms keep working untouched.
    mode: Literal["optional", "forced"] | None = None
```

Убедиться, что `Literal` импортирован (иначе добавить в существующий
`from typing import ...`).

- [ ] **Step 2: Написать падающий тест на хелперы**

Создать `backend/tournament-service/tests/test_forced_flex_roles.py`:

```python
from src.schemas.registration import BuiltInFieldConfig
from src.services.registration import _common


def _form(built_in: dict) -> object:
    class _F:
        built_in_fields_json = built_in

    return _F()


class TestForcedFlexEnabled:
    def test_absent_key_is_optional(self) -> None:
        assert _common.forced_flex_enabled(_form({})) is False

    def test_explicit_optional(self) -> None:
        assert _common.forced_flex_enabled(_form({"flex_role": {"mode": "optional"}})) is False

    def test_forced(self) -> None:
        assert _common.forced_flex_enabled(_form({"flex_role": {"mode": "forced"}})) is True

    def test_forced_ignored_when_field_disabled(self) -> None:
        form = _form({"flex_role": {"enabled": False, "mode": "forced"}})
        assert _common.forced_flex_enabled(form) is False

    def test_none_form_is_optional(self) -> None:
        assert _common.forced_flex_enabled(None) is False


class TestApplyForcedFlex:
    def test_promotes_every_role_to_primary(self) -> None:
        entries = [
            _common.models.BalancerRegistrationRole(role="dps", is_primary=True, priority=0),
            _common.models.BalancerRegistrationRole(role="tank", is_primary=False, priority=1),
        ]
        result = _common.apply_forced_flex(entries)
        assert all(entry.is_primary for entry in result)

    def test_backfills_missing_roles(self) -> None:
        entries = [_common.models.BalancerRegistrationRole(role="dps", is_primary=True, priority=0)]
        result = _common.apply_forced_flex(entries)
        assert {entry.role for entry in result} == {"tank", "dps", "support"}

    def test_keeps_priority_sequential_and_preserves_existing_order(self) -> None:
        entries = [
            _common.models.BalancerRegistrationRole(role="support", is_primary=False, priority=0),
            _common.models.BalancerRegistrationRole(role="tank", is_primary=True, priority=1),
        ]
        result = _common.apply_forced_flex(entries)
        assert [entry.role for entry in result[:2]] == ["support", "tank"]
        assert [entry.priority for entry in result] == [0, 1, 2]

    def test_does_not_touch_is_active_or_rank(self) -> None:
        entries = [
            _common.models.BalancerRegistrationRole(
                role="dps", is_primary=True, priority=0, is_active=False, rank_value=3500
            )
        ]
        result = _common.apply_forced_flex(entries)
        dps = next(entry for entry in result if entry.role == "dps")
        assert dps.is_active is False
        assert dps.rank_value == 3500

    def test_backfilled_roles_have_no_rank(self) -> None:
        entries = [
            _common.models.BalancerRegistrationRole(role="dps", is_primary=True, priority=0, rank_value=3500)
        ]
        result = _common.apply_forced_flex(entries)
        assert all(entry.rank_value is None for entry in result if entry.role != "dps")
```

Run: `cd backend/tournament-service && uv run pytest tests/test_forced_flex_roles.py -v`
Expected: FAIL (`AttributeError`: нет `forced_flex_enabled` / `apply_forced_flex`).

- [ ] **Step 3: Реализовать `forced_flex_enabled` и `apply_forced_flex`**

В `_common.py` рядом с `replace_registration_roles` добавить:

```python
def forced_flex_enabled(form: Any | None) -> bool:
    """True when the tournament forces every registration to be full flex.

    ``flex_role.mode == "forced"`` and the field itself enabled. Absent key,
    ``None`` and ``"optional"`` all mean the registrant chooses, so every
    existing form keeps its current behaviour.
    """
    if form is None:
        return False
    config = (getattr(form, "built_in_fields_json", None) or {}).get("flex_role")
    if not isinstance(config, dict):
        return False
    if config.get("enabled", True) is False:
        return False
    return config.get("mode") == "forced"


def apply_forced_flex(
    entries: list[models.BalancerRegistrationRole],
) -> list[models.BalancerRegistrationRole]:
    """Promote every role to primary and backfill the missing ones.

    A forced-flex tournament must yield ``is_flex_computed`` (>1 role, all
    primary) no matter which write path produced the entries — public form,
    admin panel, API key or Google Sheets sync. Only the role *set* and
    ``is_primary`` are normalized here: ``is_active`` and ``rank_value`` stay
    exactly as the calling path set them, because the max-rank policy is
    derived at read time (see the design doc, D4).
    """
    present = {entry.role for entry in entries}
    result = list(entries)
    for role_code in REGISTRATION_ROLE_CODES:
        if role_code not in present:
            result.append(models.BalancerRegistrationRole(role=role_code))
    for priority, entry in enumerate(result):
        entry.is_primary = True
        entry.priority = priority
    return result
```

`REGISTRATION_ROLE_CODES` импортировать из `shared.domain.player_sub_roles`
(там он определён как `("tank", "dps", "support")`), если он ещё не в скоупе
модуля.

- [ ] **Step 4: Прогнать тест**

Run: `cd backend/tournament-service && uv run pytest tests/test_forced_flex_roles.py -v`
Expected: PASS.

- [ ] **Step 5: Убедиться, что существующие тесты регистрации целы**

Run: `cd backend/tournament-service && uv run pytest tests/test_registration_role_validation.py -v`
Expected: PASS (31 тест).

- [ ] **Step 6: Commit**

```bash
git add backend/tournament-service/src/schemas/registration.py \
        backend/tournament-service/src/services/registration/_common.py \
        backend/tournament-service/tests/test_forced_flex_roles.py
git commit -m "feat(registration): add flex_role.mode contract and forced-flex role normalizer"
```

---

## Task 2: Backend — подключить нормализацию к обоим путям записи

**Files:**
- Modify: `backend/tournament-service/src/services/registration/_common.py:121-162`
- Modify: `backend/tournament-service/src/services/registration/service.py:113-151,695-699`
- Modify: `backend/tournament-service/src/services/registration/lifecycle.py:220,320`
- Modify: `backend/tournament-service/src/services/registration/sheet_sync.py:426,575`
- Modify: `backend/tournament-service/src/services/registration/admin.py` (реэкспорт)
- Modify: `backend/tournament-service/tests/test_forced_flex_roles.py`

**Контекст:** воронок записи ролей **две**, и они не синхронизированы:

| Путь | Функция | Вызовы |
|---|---|---|
| Публичная заявка | `build_registration_roles` (`service.py:113`) | `service.py:695` |
| Админка + Sheets | `replace_registration_roles` (`_common.py:121`) | `lifecycle.py:220,320`, `sheet_sync.py:426,575` |

- [ ] **Step 1: Дописать тесты на прокидывание флага**

В `tests/test_forced_flex_roles.py` добавить класс:

```python
class TestWritePathsHonourForcedFlex:
    def test_build_registration_roles_forced(self) -> None:
        from src.services.registration.service import build_registration_roles

        class _Role:
            role = "dps"
            subrole = None
            is_primary = True
            top_heroes = None

        entries = build_registration_roles([_Role()], forced_flex=True)
        assert {e.role for e in entries} == {"tank", "dps", "support"}
        assert all(e.is_primary for e in entries)

    def test_build_registration_roles_optional_unchanged(self) -> None:
        from src.services.registration.service import build_registration_roles

        class _Role:
            role = "dps"
            subrole = None
            is_primary = True
            top_heroes = None

        entries = build_registration_roles([_Role()])
        assert [e.role for e in entries] == ["dps"]

    def test_replace_registration_roles_forced(self) -> None:
        registration = _common.models.BalancerRegistration()
        registration.roles = []
        _common.replace_registration_roles(
            registration,
            [{"role": "support", "is_primary": False, "rank_value": 2900}],
            forced_flex=True,
        )
        assert {r.role for r in registration.roles} == {"tank", "dps", "support"}
        assert all(r.is_primary for r in registration.roles)
        support = next(r for r in registration.roles if r.role == "support")
        assert support.rank_value == 2900
        assert support.is_active is True
```

Run: `cd backend/tournament-service && uv run pytest tests/test_forced_flex_roles.py -v`
Expected: FAIL (обе функции не принимают `forced_flex`).

- [ ] **Step 2: Добавить kwarg в `replace_registration_roles`**

В `_common.py` в подпись `replace_registration_roles` добавить
`forced_flex: bool = False`, а перед финальным `registration.roles[:] = next_roles`
(строка 162) применить хелпер:

```python
    if forced_flex:
        next_roles = apply_forced_flex(next_roles)

    registration.roles[:] = next_roles
```

- [ ] **Step 3: Добавить kwarg в `build_registration_roles`**

В `service.py` в подпись `build_registration_roles` добавить
`forced_flex: bool = False`, и перед `return entries` (строка 151):

```python
    if forced_flex:
        entries = apply_forced_flex(entries)
    return entries
```

Импортировать `apply_forced_flex` из `src.services.registration._common`.

- [ ] **Step 4: Прокинуть флаг в публичный submit**

В `service.py` рядом с `hero_catalog, max_heroes = await _resolve_top_heroes_config(session, form)`
(строка 664) `form` уже в скоупе. В вызов на строке 695 добавить:

```python
    role_entries = build_registration_roles(
        body.roles,
        hero_catalog=hero_catalog,
        max_heroes=max_heroes,
        forced_flex=forced_flex_enabled(form),
    )
```

- [ ] **Step 5: Прокинуть флаг в админский create/update**

В `lifecycle.py` в обеих функциях (вызовы на строках 220 и 320) добавить
`forced_flex=forced_flex_enabled(form)`. Если `form` в скоупе функции нет —
принять его параметром от вызывающего (там же, где резолвятся
`hero_catalog`/`max_heroes` через `_resolve_top_heroes_config`,
`schemas/registration_build.py:76`), а не грузить отдельным запросом.

- [ ] **Step 6: Прокинуть флаг в Google Sheets синк**

`sheet_sync.py` конфиг формы **не читает вообще**. В обеих точках
(строки 426 и 575) нужен доступ к форме. Загрузить её один раз на вызов
синка (не в цикле по строкам таблицы) через существующий
`get_registration_form(session, tournament_id)` из `_common.py` и передать флаг:

```python
    replace_registration_roles(
        registration,
        build_registration_role_payloads(parsed_fields),
        forced_flex=forced_flex,
    )
```

- [ ] **Step 7: Реэкспортировать новые имена из фасада**

В `admin.py` в блок импортов из `_common` добавить `apply_forced_flex` и
`forced_flex_enabled`, и оба имени — в `__all__` (рядом с
`"replace_registration_roles"`).

- [ ] **Step 8: Прогнать тесты**

Run: `cd backend/tournament-service && uv run pytest tests/test_forced_flex_roles.py tests/test_registration_role_validation.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/tournament-service/src/services/registration backend/tournament-service/tests/test_forced_flex_roles.py
git commit -m "feat(registration): normalize forced-flex roles on both write paths"
```

---

## Task 3: Frontend — типы и админ-UI конфига формы

**Files:**
- Modify: `frontend/src/types/registration.types.ts:18-31`
- Modify: `frontend/src/types/balancer-admin.types.ts:323-336`
- Modify: `frontend/src/components/balancer/form/_components/formConfig.ts:11-26,91-96`
- Modify: `frontend/src/components/balancer/form/_components/BuiltInFieldsCard.tsx:52-90`
- Modify: `frontend/src/i18n/messages/en.json`, `frontend/src/i18n/messages/ru.json`

**Контекст:** `BuiltInFieldConfig` существует в **трёх** зеркалах — Pydantic
(Task 1), публичный TS-тип и админский TS-тип. Поле нужно во всех трёх.

- [ ] **Step 1: Добавить `mode` в оба TS-типа**

В `registration.types.ts` и `balancer-admin.types.ts` в `BuiltInFieldConfig`
дописать:

```ts
  /** `flex_role` field only: "forced" makes every registration full flex. */
  mode?: "optional" | "forced" | null;
```

- [ ] **Step 2: Добавить `supportsMode` в `BuiltInFieldDef`**

В `formConfig.ts` в интерфейс `BuiltInFieldDef`:

```ts
  /** `flex_role`: shows an optional/forced mode select. */
  supportsMode?: boolean;
```

и в запись `flex_role` (строки 91-96) дописать `supportsMode: true`.

- [ ] **Step 3: Отрендерить селект режима**

В `BuiltInFieldsCard.tsx` правый слот строки у `flex_role` свободен
(`supportsRequired: false`, условие на строке 82 не срабатывает). Рядом с этим
блоком добавить:

```tsx
                  {cfg.enabled && def.supportsMode && (
                    <label className="flex shrink-0 select-none items-center gap-2 text-xs text-muted-foreground">
                      {t("mode")}
                      <Select
                        value={cfg.mode ?? "optional"}
                        onValueChange={(value) =>
                          onUpdate(def.key, { mode: value as "optional" | "forced" })
                        }
                      >
                        <SelectTrigger className="h-8 w-[11rem]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="optional">{t("modeOptional")}</SelectItem>
                          <SelectItem value="forced">{t("modeForced")}</SelectItem>
                        </SelectContent>
                      </Select>
                    </label>
                  )}
```

Импортировать `Select`/`SelectTrigger`/`SelectValue`/`SelectContent`/`SelectItem`
из `@/components/ui/select`.

- [ ] **Step 4: Сбрасывать `mode` при выключении поля**

В хендлере главного `Switch` (строки 55-63) расширить сброс по образцу `required`:

```tsx
                      onUpdate(def.key, {
                        enabled: checked,
                        ...(checked ? {} : { required: false, mode: null })
                      });
```

- [ ] **Step 5: Добавить i18n-ключи**

В `en.json` и `ru.json` в `registrationFormAdmin.builtInFields` добавить `mode`,
`modeOptional`, `modeForced`, и обновить
`registrationFormAdmin.builtInFields.defs.flex_role.description`, упомянув, что
в принудительном режиме поле приоритета у игрока скрыто, сила считается по
максимальному рангу, а настройка сабролей `additional_roles` перестаёт влиять
(все роли становятся основными, allowlist берётся из `primary_role`).

- [ ] **Step 6: Проверить типы, lint и i18n-тест билдера формы**

Run: `cd frontend && bunx tsc --noEmit && bunx eslint src/types/registration.types.ts src/types/balancer-admin.types.ts src/components/balancer/form`
Expected: без ошибок.

Run: `cd frontend && bunx vitest run src/components/balancer/form/RegistrationFormBuilder.i18n.test.tsx`
Expected: PASS (тест ловит незакрытые ключи `registrationFormAdmin.*`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types frontend/src/components/balancer/form frontend/src/i18n/messages
git commit -m "feat(registration-form): expose flex_role optional/forced mode in the admin builder"
```

---

## Task 4: Frontend — форма регистрации в forced-режиме

**Files:**
- Modify: `frontend/src/components/registration/types.ts:35-41`
- Modify: `frontend/src/components/registration/RoleStep.tsx:20-31,43-53,79-91,140-173`
- Modify: `frontend/src/components/registration/UnifiedRegistrationForm.tsx:79-82,180,704`
- Modify: `frontend/src/components/registration/RoleStep.behavior.test.tsx`
- Modify: `frontend/src/i18n/messages/en.json`, `frontend/src/i18n/messages/ru.json`

**Внимание:** этот тест идёт через `bun test`, не через vitest
(`import { ... } from "bun:test"`, см. `vitest.config.ts:58-62`).

- [ ] **Step 1: Написать падающие тесты**

В `RoleStep.behavior.test.tsx` добавить кейсы, отражающие forced-режим:

- рендер с `flexMode="forced"` не содержит контрола приоритета и кнопки-пресета
  (`[aria-pressed]`);
- начальные `createRoleSelections(true)` дают `priority === "main"` для всех
  трёх ролей, `isFlexSelection` истинно;
- выбор саброли и топ-героя не понижает приоритет и не делает роль `off`;
- при `flexMode="optional"` поведение прежнее (существующие кейсы `:173-182`
  должны продолжать проходить).

Run: `cd frontend && bun test src/components/registration/RoleStep.behavior.test.tsx`
Expected: FAIL.

- [ ] **Step 2: Параметризовать `createRoleSelections`**

В `types.ts`:

```ts
export function createRoleSelections(forced = false): RoleSelections {
  const priority: RolePriority = forced ? "main" : "off";
  return {
    tank: { ...EMPTY_ROLE_SELECTION, priority },
    dps: { ...EMPTY_ROLE_SELECTION, priority },
    support: { ...EMPTY_ROLE_SELECTION, priority },
  };
}
```

Обязательно: `orderedActiveRoles` фильтрует `priority !== "off"`
(`UnifiedRegistrationForm.tsx:444`), поэтому без этого шага forced-заявка ушла
бы с `roles: undefined`.

- [ ] **Step 3: Заменить `flexEnabled` на `flexMode` в `RoleStep`**

В `RoleStep.tsx`:
- в `RoleStepProps` заменить `flexEnabled: boolean` на
  `flexMode: "off" | "optional" | "forced"`;
- завести `const isForced = flexMode === "forced"`;
- в `normalize` (строка 79) при `isForced` возвращать `next` без изменений;
- кнопку-пресет рендерить только при `flexMode === "optional"`;
- при `isForced` не рендерить колонку приоритета: убрать её из `columnClass`
  (строка 141) и передать в `RoleMatrixRow` признак скрытия контрола
  (`showPriority={!isForced}`), добавив соответствующий проп в
  `role-step/RoleMatrixRow.tsx`;
- заголовок колонки «Приоритет» (строка 189) рендерить по тому же условию;
- хелпер-текст при `isForced` брать из нового ключа
  `registration.roles.matrix.hintForced`.

- [ ] **Step 4: Прокинуть режим из `UnifiedRegistrationForm`**

Заменить строку 180:

```tsx
  const flexConfig = formConfig.built_in_fields?.flex_role;
  const flexMode: "off" | "optional" | "forced" =
    flexConfig?.enabled === false ? "off" : flexConfig?.mode === "forced" ? "forced" : "optional";
```

Передать `flexMode={flexMode}` в `RoleStep` (строка 704). Начальное состояние
(строки 79-82) должно использовать `createRoleSelections(flexMode === "forced")` —
включая ветку `mode === "public"` для нового заявителя.

- [ ] **Step 5: Добавить i18n-ключ**

`registration.roles.matrix.hintForced` в `en.json` и `ru.json`: объяснение, что
на этом турнире каждый играет любую роль, поэтому приоритеты не выбираются.

- [ ] **Step 6: Прогнать тесты, типы, lint**

Run: `cd frontend && bun test src/components/registration/RoleStep.behavior.test.tsx`
Expected: PASS.

Run: `cd frontend && bunx tsc --noEmit && bunx eslint src/components/registration`
Expected: без ошибок.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/registration frontend/src/i18n/messages
git commit -m "feat(registration): hide role priority and force full flex in forced mode"
```

---

## Task 5: Frontend — балансер читает эффективные ранги

**Files:**
- Modify: `frontend/src/app/balancer/components/workspace-helpers.ts:445-471`
- Modify: `frontend/src/app/balancer/components/balancer-page-selectors.ts:33-42`
- Modify: `frontend/src/app/balancer/components/BalancerMainPageClient.tsx:184-193,271-274`
- Modify: `frontend/src/app/balancer/components/workspace-helpers.test.ts`

**Внимание:** `workspace-helpers.test.ts` идёт через `bun test` (самописный
харнесс, без импорта раннера).

- [ ] **Step 1: Написать падающие тесты**

В `workspace-helpers.test.ts` добавить кейсы:

- `createSyntheticPlayerFromRegistration(reg, grid, { forcedFlex: true })` для
  заявки с рангами `dps: 3900`, `support: 2400` даёт три роли, у каждой
  `rank_value === 3900` и `is_active === true`;
- `ow_rank_value` сплющивается своим максимумом: при `dps.ow = 4100`,
  `support.ow = 2000` у всех трёх ролей `ow_rank_value === 4100`;
- `getPlayerValidationIssues` для такого игрока при
  `rank_delta_threshold = 300` даёт **одну** плашку `rank_delta_warning`
  (delta = |3900 − 4100| = 200 → плашек ноль; отдельный кейс с
  `dps.ow = 4400` → одна плашка), а **не три**;
- заявка без рангов вовсе: все роли `is_active === false`,
  `getPlayerValidationIssues` содержит `missing_ranked_role`;
- при `forcedFlex: false` результат байт-в-байт прежний (существующие кейсы
  `:372-443` не меняются).

Run: `cd frontend && bun test src/app/balancer/components/workspace-helpers.test.ts`
Expected: FAIL.

- [ ] **Step 2: Реализовать сплющивание**

В `workspace-helpers.ts` добавить экспортируемый хелпер и опциональный параметр:

```ts
const REGISTRATION_ROLE_CODES: BalancerRoleCode[] = ["tank", "dps", "support"];

/** Effective strength of a forced-flex registrant: the max across all roles.
 *
 *  `ow_rank_value` is flattened by the SAME rule on purpose. Flattening only
 *  `rank_value` would make `computeRankDeltasByRole` compare an effective rank
 *  against a per-role OW rank and emit bogus `rank_delta_warning` chips — and
 *  `runBalanceMutation` refuses to start while any player has issues.
 */
export function flattenRolesToMaxRank(
  roles: AdminRegistrationRole[],
  grid: DivisionGrid
): BalancerPlayerRoleEntry[] {
  const maxOf = (pick: (role: AdminRegistrationRole) => number | null | undefined) => {
    const values = roles.map(pick).filter((value): value is number => value != null);
    return values.length > 0 ? Math.max(...values) : null;
  };
  const effRank = maxOf((role) => role.rank_value);
  const effOwRank = maxOf((role) => role.ow_rank_value);
  const byRole = new Map(roles.map((role) => [role.role, role]));

  return REGISTRATION_ROLE_CODES.map((code, index) => {
    const source = byRole.get(code);
    return {
      role: code,
      subtype: source?.subrole ?? null,
      priority: source?.priority ?? index,
      division_number: resolveDivisionFromRankHelper(effRank, grid),
      rank_value: effRank,
      is_active: effRank !== null,
      ow_rank_value: effOwRank
    };
  });
}
```

и в `createSyntheticPlayerFromRegistration` добавить третий параметр
`options: { forcedFlex?: boolean } = {}`, подменяющий `role_entries_json`:

```ts
    role_entries_json: options.forcedFlex
      ? flattenRolesToMaxRank(registration.roles, grid)
      : registration.roles.map((role) => ({ /* существующий маппинг без изменений */ })),
```

- [ ] **Step 3: Прокинуть флаг через селекторы**

В `balancer-page-selectors.ts` добавить третий параметр
`forcedFlex = false` в `buildBalancerPageCollections` и передать его в
`createSyntheticPlayerFromRegistration(registration, divisionGrid, { forcedFlex })`
(строка 41). Это единственная точка вставки: таблица пула, валидация и
`buildBalancerInput` получают одни и те же значения (WYSIWYG, решение D5).

- [ ] **Step 4: Загрузить конфиг формы на странице балансера**

В `BalancerMainPageClient.tsx` рядом с остальными query (строки 184-193):

```tsx
  const registrationFormQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null
  });
```

(тот же ключ, что в `RegistrationsTable.tsx:324` — кэш переиспользуется.)

Далее:

```tsx
  const forcedFlex =
    registrationFormQuery.data?.built_in_fields?.flex_role?.enabled !== false &&
    registrationFormQuery.data?.built_in_fields?.flex_role?.mode === "forced";
```

и в `useMemo` (строки 271-274) передать третий аргумент, добавив `forcedFlex` в
массив зависимостей. Дефолт `false` при ошибке или незагруженном запросе —
fail-closed (допущение №3 спеки).

- [ ] **Step 5: Прогнать тесты, типы, lint**

Run: `cd frontend && bun test src/app/balancer/components/workspace-helpers.test.ts`
Expected: PASS.

Run: `cd frontend && bunx vitest run src/app/balancer/components/balancer-page-selectors.test.ts src/app/balancer/components/BalancingPoolSidebar.behavior.test.tsx`
Expected: PASS.

Run: `cd frontend && bunx tsc --noEmit && bunx eslint src/app/balancer/components`
Expected: без ошибок.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/balancer/components
git commit -m "feat(balancer): use max-rank effective ranks for forced-flex tournaments"
```

---

## Task 6: Backend — драфт читает эффективные ранги

**Files:**
- Modify: `backend/balancer-service/src/services/draft/lifecycle.py:436-498,567-651`
- Create: `backend/balancer-service/tests/test_draft_forced_flex.py`

**Контекст:** `_build_role_rows` (`lifecycle.py:132-167`) уже берёт объединение
primary + secondaries + ролей с рангом, поэтому три строки `draft_player_role`
создадутся сами — включая капитанов, которым `secondary_roles` передаётся пустым
(`lifecycle.py:317`). Правок в `_build_role_rows` не нужно.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_draft_forced_flex.py` по образцу `test_draft_integration.py`
(там уже есть хелпер `_build_balancer_pool`, строка 651):

- `_map_registration(reg, forced_flex=True)` для заявки с рангами
  `dps: 3900` (primary), `support: 2400` возвращает
  `rank_value == 3900` и `role_ranks == {"tank": 3900, "dps": 3900, "support": 3900}`;
- обратный случай, ловящий текущий баг выбора ранга: primary — `support: 2400`,
  а `dps: 3900` вторичный → `rank_value == 3900` (сейчас вернулось бы `2400`);
- неактивная роль (Sheets без ранга, `is_active = False`) всё равно попадает в
  набор ролей;
- заявка без рангов вовсе: `rank_value is None`, `role_ranks == {}`;
- `forced_flex=False` даёт прежний результат;
- интеграционно: `seed_from_pool` в forced-турнире создаёт по три
  `draft_player_role` на игрока и на капитана, с одинаковым `rank_value`.

Run: `cd backend/balancer-service && uv run pytest tests/test_draft_forced_flex.py -v`
Expected: FAIL.

- [ ] **Step 2: Параметризовать `_map_registration`**

В `lifecycle.py` в подпись добавить `*, forced_flex: bool = False`. В forced-ветке:

```python
    if forced_flex:
        # Sheets rows without a parsed rank arrive with is_active=False, so the
        # active filter would silently drop playable roles here.
        roles = [DraftRole.TANK, DraftRole.DPS, DraftRole.SUPPORT]
        ranks = [r.rank_value for r in (reg.roles or []) if r.rank_value is not None]
        eff_rank = max(ranks) if ranks else None
        role_ranks = {role.value: eff_rank for role in roles} if eff_rank is not None else {}
        rank_value = eff_rank
```

`primary` берётся как первая роль по `priority` из `reg.roles`, `secondary` — две
остальные, `sub_role` — из primary-строки, `role_top_heroes` собирается как сейчас
(по всем ролям, не только активным).

- [ ] **Step 3: Прочитать форму в `seed_from_pool`**

В `seed_from_pool` перед построением капитанов:

```python
    form = await session.scalar(
        sa.select(BalancerRegistrationForm).where(
            BalancerRegistrationForm.tournament_id == draft_session.tournament_id
        )
    )
    forced_flex = _forced_flex_enabled(form)
```

Добавить локальный `_forced_flex_enabled(form)` — зеркало
`tournament-service/_common.forced_flex_enabled` (тот же контракт: `enabled`
не false и `mode == "forced"`), с docstring-ссылкой на оригинал. Импортировать
`BalancerRegistrationForm` из `shared.models.registration.registration` — это
первое обращение balancer-service к этой модели.

Передать `forced_flex=forced_flex` в оба вызова `_map_registration`
(строки 599 и 634).

- [ ] **Step 4: Прогнать тесты**

Run: `cd backend/balancer-service && uv run pytest tests/test_draft_forced_flex.py tests/test_draft_integration.py -v`
Expected: PASS (24 существующих теста в `test_draft_integration.py` не должны сломаться).

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/services/draft/lifecycle.py backend/balancer-service/tests/test_draft_forced_flex.py
git commit -m "feat(draft): seed forced-flex tournaments with max-rank effective ranks"
```

---

## Task 7: Паритет-тест TS↔Python и финальная верификация

**Files:**
- Create: `docs/superpowers/fixtures/forced-flex-eff-rank.json`
- Create: `frontend/src/app/balancer/components/forced-flex-parity.test.ts`
- Create: `backend/balancer-service/tests/test_forced_flex_parity.py`
- Modify: `frontend/vitest.config.ts:19-63`

**Зачем:** это цена подхода A — правило `effRank` живёт в двух языках.
Прецедент документированного зеркалирования в репо есть
(`suggestions.py:59` — «Mirror of balancer `Player.discomfort_map`»).

- [ ] **Step 1: Завести общие фикстуры**

`docs/superpowers/fixtures/forced-flex-eff-rank.json` — список кейсов:

```json
[
  {
    "name": "single ranked role",
    "roles": [{ "role": "dps", "rank_value": 3900, "ow_rank_value": 4100, "is_active": true }],
    "expected": { "eff_rank": 3900, "eff_ow_rank": 4100 }
  },
  {
    "name": "primary is not the strongest",
    "roles": [
      { "role": "support", "rank_value": 2400, "ow_rank_value": 2500, "is_active": true },
      { "role": "dps", "rank_value": 3900, "ow_rank_value": null, "is_active": true }
    ],
    "expected": { "eff_rank": 3900, "eff_ow_rank": 2500 }
  },
  {
    "name": "inactive role still contributes",
    "roles": [{ "role": "tank", "rank_value": 3100, "ow_rank_value": null, "is_active": false }],
    "expected": { "eff_rank": 3100, "eff_ow_rank": null }
  },
  {
    "name": "no ranks at all",
    "roles": [{ "role": "dps", "rank_value": null, "ow_rank_value": null, "is_active": true }],
    "expected": { "eff_rank": null, "eff_ow_rank": null }
  }
]
```

- [ ] **Step 2: TS-сторона паритета**

`frontend/src/app/balancer/components/forced-flex-parity.test.ts` (vitest):
читает JSON, гоняет `flattenRolesToMaxRank`, проверяет, что все три роли
получили `expected.eff_rank` / `expected.eff_ow_rank` и что
`is_active === (eff_rank !== null)`.

- [ ] **Step 3: Добавить файл в vitest allowlist**

В `frontend/vitest.config.ts` в массив `include` дописать:

```ts
      "src/app/balancer/components/forced-flex-parity.test.ts",
```

**Обязательный шаг:** `include` — allowlist, файл вне него не запускается, а
suite рапортует зелёным (комментарий `vitest.config.ts:30-32`).

- [ ] **Step 4: Python-сторона паритета**

`backend/balancer-service/tests/test_forced_flex_parity.py`: читает тот же JSON,
собирает фейковую `BalancerRegistration` с ролями и проверяет, что
`_map_registration(reg, forced_flex=True)` даёт `rank_value == expected.eff_rank`
и `role_ranks` на все три роли с тем же значением (или `{}` при `None`).

- [ ] **Step 5: Прогнать паритет**

Run: `cd frontend && bunx vitest run src/app/balancer/components/forced-flex-parity.test.ts`
Expected: PASS, и в выводе видно, что файл действительно найден (не «No test files found»).

Run: `cd backend/balancer-service && uv run pytest tests/test_forced_flex_parity.py -v`
Expected: PASS.

- [ ] **Step 6: Финальная верификация всего затронутого**

```bash
cd backend/tournament-service && uv run pytest tests/test_forced_flex_roles.py tests/test_registration_role_validation.py
cd ../balancer-service && uv run pytest tests/test_draft_forced_flex.py tests/test_draft_integration.py tests/test_forced_flex_parity.py
cd ../../frontend && bunx tsc --noEmit
bun test src/app/balancer/components/workspace-helpers.test.ts src/components/registration/RoleStep.behavior.test.tsx
bunx vitest run
bunx eslint src/app/balancer/components src/components/registration src/components/balancer/form src/types
```

Expected: всё зелёное.

- [ ] **Step 7: Смоук-тест руками (обязателен)**

1. В админке турнира выставить `flex_role` = принудительный, сохранить форму.
2. Открыть публичную регистрацию: колонки приоритета нет, кнопки-пресета нет,
   саброли и топ-герои выбираются.
3. Подать заявку, одобрить её, выставить ранг **только на одной роли**.
4. Открыть балансер: у игрока три роли с одинаковым рангом, плашек
   `rank_delta_warning` не больше одной, кнопка запуска баланса активна.
5. Запустить баланс: джоб доходит до `succeeded`, `total_discomfort = 0`,
   игрок оказывается в составе (в том числе на роли, где ранга не было).
6. Засидить драфт: у игрока три роли в инспекторе, эффективный ранг одинаковый,
   он предлагается на любую открытую роль.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/fixtures frontend/src/app/balancer/components/forced-flex-parity.test.ts \
        frontend/vitest.config.ts backend/balancer-service/tests/test_forced_flex_parity.py
git commit -m "test(forced-flex): pin TS/Python parity of the max-rank rule"
```

---

## Ожидаемая телеметрия forced-турниров (не баг)

`total_discomfort = 0`, `off_role_count = 0`, `structural_min_off_role = 0`,
дисперсия рейтингов близка к нулю, число различимых вариантов резко падает.
Причина — comfort-объектив при all-flex сводится к одним коллизиям сабролей
(`objectives.rs:384-387`), а при плоских рейтингах перестановка ролей не влияет
на объектив баланса. Деления на ноль не будет: `normalize_objectives` страхует
нулевой размах через `.max(1e-6)` (`objectives.rs:554`).

## Что НЕ входит в этот план

- Перенос сборки payload балансера на бэкенд (подход B спеки) — закрывает дубль
  логики TS/Python, но требует смены контракта балансер-джоба.
- Расхождение семантики флекса драфт↔балансер в `optional`-режиме (D8).
- Пересчёт уже засиженной драфт-сессии при переключении режима (D7).

---

## Статус выполнения (2026-08-05)

Задачи 1-7 реализованы в ветке `feature/forced-flex-max-rank`. Ниже — что
проверено и что осталось.

### Проверено запуском

| Проверка | Результат |
|---|---|
| `tournament-service`: `test_forced_flex_roles.py` + `test_registration_role_validation.py` | 55 passed |
| `balancer-service`: `test_forced_flex_parity.py` + `test_draft_forced_flex.py` + `test_config_consistency.py` | 53 passed |
| `balancer-service`: `test_draft_integration.py` + `test_draft_suggestions.py` + `test_draft_feasibility.py` | 27 passed, 24 skipped |
| `parser-service` полный прогон | 221 passed |
| Фронтенд bun: `workspace-helpers.test.ts` + `RoleStep.behavior.test.tsx` | 38 passed |
| Фронтенд vitest полный прогон | 49 файлов, 371 passed |
| `bunx tsc --noEmit` | чисто |
| `ruff check .` по всему workspace | чисто |
| Паритет-тест ловит расхождение | подтверждено инъекцией `min()` вместо `max()` в `_map_registration` → 3 падения, откат → 25 passed |

### Дополнение: третий режим `all_roles` (2026-08-05)

План описывал два режима (`optional`, `forced`). `forced` вырожден: он убивает
comfort-объектив MOO — при all-flex discomfort нулевой везде, второй объектив
сводится к одним коллизиям сабролей, варианты становятся почти неразличимы, и
`rank_comfort_tilt` теряет смысл. Добавлен третий режим `all_roles`: все роли
обязательны (та же eligibility по макс-ранку, что у `forced`), но игрок называет
**одну** приоритетную роль либо «Флекс». Неприоритетные роли остаются играбельными
и менее комфортными, поэтому trade-off баланс↔комфорт снова живой.

Реализовано: `flex_role.mode` расширен до трёх значений; предикат раздвоен на
«роль не ограничение» (`all_roles_required` / `_all_roles_required`, оба режима) и
«приоритет форсится» (`force_primary`, только `forced`); валидация требует ровно
одну приоритетную роль либо все три; в форме один radiogroup Танк/DPS/Саппорт/Флекс
вместо трёх построчных контролов; балансер сплющивает ранги в обоих режимах за
именованным `ratesByMaxRank`.

| Проверка | Результат |
|---|---|
| `tournament-service` полный прогон | 775 passed, 44 skipped |
| `balancer-service` полный прогон (включая 24-минутные интеграционные) | 341 passed, 29 skipped |
| `parser-service` полный прогон | 221 passed |
| Фронтенд vitest полный прогон | 50 файлов, 379 passed |
| Фронтенд bun: `workspace-helpers` + `RoleStep.behavior` | 48 passed |
| `bunx tsc --noEmit` | чисто |
| `bunx eslint src` | 7 warnings, все pre-existing `react-hooks/incompatible-library` в файлах, которые фича не трогает |
| `ruff check .` по всему workspace | чисто |
| `export_openapi_schemas.sh --check` | зелёный после регенерации (+1 enum-вариант) |

Смоук-чеклист ниже относится и к `all_roles`, с одним отличием в п. 2: колонка
приоритета скрыта, но появляется один общий radiogroup, и без выбора в нём заявка
должна отвергаться.

### Отклонение от плана: решение D6 исправлено

План (Task 5, Step 2) предписывал сплющивать `ow_rank_value` максимумом на все
три роли, обещая «одну плашку delta вместо трёх». При прогоне выяснилось, что это
неверно: сплющивание уравнивает delta, но **не сворачивает три строки**, и
`getPlayerValidationIssues` выдавал одну и ту же плашку трижды. А игрок с любым
issue отвергается `runBalanceMutation`, так что это не косметика.

Реализовано иначе: эффективный OW-ранг присваивается **только роли-источнику**,
на остальных двух `null`. `computeRankDeltasByRole` требует оба значения, поэтому
выходит ровно одна плашка с осмысленным числом. Спека обновлена (D6).

### НЕ пройдено: браузерный смоук (Task 7, Step 7)

Попытка повторена после появления третьего режима `all_roles`. Docker на этот раз
работает, исходники сервисов смонтированы томами (пересборка не нужна, Rust не
менялся), но смоук блокируют **две независимые pre-existing причины**:

1. **Dev-стек сконфигурирован на удалённый production-Postgres.** Сервисы берут
   настройки БД из корневого `.env`, который указывает на `95.179.157.197:6432`
   (pgbouncer), а не на локальный контейнер. У локального `postgres` нет
   host-порта — он доступен только изнутри compose-сети по имени сервиса. Писать
   тестовые заявки в production недопустимо, поэтому нужен локальный инстанс.
2. **Цепочка alembic не применяется к пустой БД.** `alembic upgrade head` с нуля
   падает детерминированно: `m3h5i7j1k2l3` (`normalize_balancer_3nf`) создаёт
   `balancer.registration_form` уже с колонкой `built_in_fields_json`, а его
   прямой потомок `n4i6j8k2l3m4` выполняет `ADD COLUMN` той же колонки →
   `DuplicateColumn`. На production не стреляет, потому что там состояние колонки
   старше конфликта. Транзакция откатывается целиком, БД остаётся пустой.

Из (1) следует, что нужна локальная БД; из (2) — что создать её нельзя. Ни то, ни
другое не вызвано этой фичей и не лечится внутри неё. Шесть пунктов остаются
непройденными — **фича не проверена end-to-end**:

- [ ] 1. В админке турнира выставить `flex_role` = «Все флексы», сохранить форму.
- [ ] 2. Публичная регистрация: колонки приоритета нет, кнопки-пресета нет,
      саброли и топ-герои выбираются.
- [ ] 3. Подать заявку, одобрить, выставить ранг **только на одной роли**.
- [ ] 4. Балансер: у игрока три роли с одинаковым рангом, плашек
      `rank_delta_warning` не больше одной, кнопка запуска баланса активна.
- [ ] 5. Запустить баланс: джоб доходит до `succeeded`, `total_discomfort = 0`,
      игрок в составе — **в том числе на роли, где ранга не было**.
- [ ] 6. Засидить драфт: у игрока три роли в инспекторе, эффективный ранг
      одинаковый, он предлагается на любую открытую роль.

Пункты 5 и 6 — единственная проверка того, что механизм действительно работает:
юнит-тесты подтверждают, что три роли получают одинаковый ранг, но не то, что
солвер и драфт реально ставят игрока на роль, где ранга не было.

### Примечание о ветке

В `feature/forced-flex-max-rank` перемешаны два независимых потока работы: шесть
коммитов forced-flex и восемь коммитов «subscription requirement → workspace» из
параллельной сессии. Содержимое корректно, атрибуция смешана. Коммит `b60ba79a`
(forced-flex) дополнительно захватил `RegistrationFormBuilder.tsx` из второго
потока — застейджен каталогом.

Девять падающих тестов в `tests/test_registration_form_subscription.py`
принадлежат второму потоку: `RegistrationFormUpsert` потерял
`subscription_requirement_json`, а тест-файл под это не обновлён. Слова `flex` в
файле не встречается.
