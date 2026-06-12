# Balancer Rank Comfort Tilt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать настраиваемую из UI ручку `rank_comfort_tilt`, сдвигающую соотношение баланс/комфорт в ранжировании вариантов балансера (какой вариант «лучший» и идёт первым), не меняя оптимизатор; попутно убрать мёртвую метаданность `applies_to`.

**Architecture:** `composite_score` (knee-distance) параметризуется двумя весами `(w_balance, w_comfort)`. Внутренние archive-операции поиска зовут с `(1.0, 1.0)` — байт-идентично текущему. Финальный ранг в `runner.rs` зовёт с `(1 - tilt, tilt)`, где `tilt ∈ [0,1]` (дефолт `0.5` = текущее поведение). Значение `tilt` прокидывается из UI-слайдера через Python-конфиг и JSON в Rust `ConfigSpec`.

**Tech Stack:** Rust (pyo3 / `moo_core`), Python (FastAPI, Pydantic, pytest), TypeScript/React (Next.js, shadcn/ui + `@radix-ui/react-slider`), vitest/eslint/tsc.

**Спецификация:** [docs/superpowers/specs/2026-06-12-balancer-rank-comfort-tilt-design.md](../specs/2026-06-12-balancer-rank-comfort-tilt-design.md)

**Команды (справочно):**
- Rust: `cargo test --manifest-path backend/balancer-service/native/moo_core/Cargo.toml`
- Rust fmt/lint: `cargo fmt --manifest-path .../Cargo.toml` / `cargo clippy --manifest-path .../Cargo.toml`
- Python: из `backend/balancer-service` → `uv run pytest tests/test_config_consistency.py tests/test_balancer_config.py -v`
- Frontend: из `frontend` → `pnpm exec tsc --noEmit`, `pnpm exec eslint <path>`

---

## Подготовка

- [ ] **Создать ветку от `develop`**

```bash
git checkout develop
git pull
git checkout -b feature/balancer-rank-comfort-tilt
```

---

## Task 1: Backend — убрать `applies_to` из конфиг-полей

**Files:**
- Modify: `backend/balancer-service/src/services/balancer/config/provider.py` (все записи `CONFIG_FIELD_DEFINITIONS`)
- Modify: `backend/balancer-service/tests/test_balancer_config.py:84`

- [ ] **Step 1: Убрать ассерт в тесте**

В `tests/test_balancer_config.py` удалить строку:

```python
        assert field["applies_to"]
```

- [ ] **Step 2: Запустить тест — должен пройти (ассерта нет), но поля ещё содержат applies_to**

Run: `cd backend/balancer-service && uv run pytest tests/test_balancer_config.py -v`
Expected: PASS

- [ ] **Step 3: Удалить `"applies_to": ["moo"],` из каждой записи `CONFIG_FIELD_DEFINITIONS`**

В `provider.py` в списке `CONFIG_FIELD_DEFINITIONS` удалить строку `"applies_to": ["moo"],` из всех записей (их ~30). После правки ни одна запись не должна содержать ключ `applies_to`.

Проверка отсутствия:

```bash
rg "applies_to" backend/balancer-service/src/services/balancer/config/provider.py
```

Expected: пусто.

- [ ] **Step 4: Запустить конфиг-тесты**

Run: `cd backend/balancer-service && uv run pytest tests/test_balancer_config.py tests/test_config_consistency.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/src/services/balancer/config/provider.py backend/balancer-service/tests/test_balancer_config.py
git commit -m "refactor(balancer): drop dead per-field applies_to metadata (backend)"
```

---

## Task 2: Frontend — убрать `applies_to` из типов/сервиса/UI

**Files:**
- Modify: `frontend/src/types/balancer.types.ts:156`
- Modify: `frontend/src/services/balancer.service.ts:27-30,76-107`
- Modify: `frontend/src/app/balancer/components/BalancerConfigDrawer.tsx:335`

- [ ] **Step 1: Убрать поле из типа `BalancerConfigField`**

В `frontend/src/types/balancer.types.ts` удалить строку:

```ts
  applies_to: BalancerAlgorithm[];
```

- [ ] **Step 2: Убрать `applies_to` из `RawBalancerConfigField`**

В `frontend/src/services/balancer.service.ts` заменить:

```ts
type RawBalancerConfigField = Omit<BalancerConfigField, "key" | "applies_to"> & {
  key: string;
  applies_to: string[];
};
```

на:

```ts
type RawBalancerConfigField = Omit<BalancerConfigField, "key"> & {
  key: string;
};
```

- [ ] **Step 3: Убрать фильтр по `applies_to` из `normalizeConfigField`**

В том же файле заменить тело `normalizeConfigField` так, чтобы убрать блок `appliesTo` и `applies_to: appliesTo` из возврата:

```ts
function normalizeConfigField(
  field: RawBalancerConfigField,
  defaults: BalancerConfig
): BalancerConfigField | null {
  if (
    !SUPPORTED_BALANCER_CONFIG_KEY_SET.has(field.key) ||
    !SUPPORTED_CONFIG_FIELD_TYPES.has(field.type as string)
  ) {
    return null;
  }

  const options =
    field.key === "algorithm"
      ? (field.options ?? []).filter((option) => SUPPORTED_BALANCER_ALGORITHM_SET.has(option))
      : field.options;

  return {
    ...field,
    key: field.key as BalancerConfigField["key"],
    options,
    default: defaults[field.key as keyof BalancerConfig] ?? field.default
  };
}
```

(`SUPPORTED_BALANCER_ALGORITHM_SET` остаётся используемым в фильтре опций `algorithm` и в `normalizeAlgorithm` — не станет unused.)

- [ ] **Step 4: Убрать бейдж «Applies» в drawer**

В `frontend/src/app/balancer/components/BalancerConfigDrawer.tsx` удалить строку:

```tsx
                              <span>Applies: {field.applies_to.join(", ")}</span>
```

- [ ] **Step 5: Проверить типы и lint**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint src/services/balancer.service.ts src/types/balancer.types.ts src/app/balancer/components/BalancerConfigDrawer.tsx`
Expected: без ошибок.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/balancer.types.ts frontend/src/services/balancer.service.ts frontend/src/app/balancer/components/BalancerConfigDrawer.tsx
git commit -m "refactor(balancer): drop dead per-field applies_to metadata (frontend)"
```

---

## Task 3: Rust — поле `rank_comfort_tilt` в `ConfigSpec`

**Files:**
- Modify: `backend/balancer-service/native/moo_core/src/lib.rs` (default-fn + `ConfigSpec`)
- Modify: `backend/balancer-service/native/moo_core/src/bench_api.rs:7-43` (`bench_config`)
- Modify: `backend/balancer-service/native/moo_core/src/tests.rs:12-...` (`regression_config` и любые другие литералы `ConfigSpec`)

- [ ] **Step 1: Добавить default-функцию рядом с остальными `default_*` в `lib.rs`**

```rust
fn default_rank_comfort_tilt() -> f64 {
    0.5
}
```

- [ ] **Step 2: Добавить поле в `ConfigSpec`**

В `struct ConfigSpec` (после `time_limit_ms` или рядом с прочими `#[serde(default)]`-полями) добавить:

```rust
    /// Сдвиг ранга баланс↔комфорт при упорядочивании вариантов (0.5 = текущее
    /// 50/50). Влияет ТОЛЬКО на финальный ранг/primary/отображаемый score, не на
    /// objective-поиск. Старые сохранённые конфиги без поля → 0.5.
    #[serde(default = "default_rank_comfort_tilt")]
    rank_comfort_tilt: f64,
```

- [ ] **Step 3: Добавить поле во ВСЕ литералы `ConfigSpec`**

Найти литералы:

```bash
rg -n "ConfigSpec \{" backend/balancer-service/native/moo_core/src
```

В каждом (`bench_api.rs::bench_config`, `tests.rs::regression_config`, и любых других) добавить строку:

```rust
        rank_comfort_tilt: 0.5,
```

- [ ] **Step 4: Собрать — должно компилироваться**

Run: `cargo build --manifest-path backend/balancer-service/native/moo_core/Cargo.toml`
Expected: OK (нет ошибки «missing field rank_comfort_tilt»).

- [ ] **Step 5: Commit**

```bash
git add backend/balancer-service/native/moo_core/src/lib.rs backend/balancer-service/native/moo_core/src/bench_api.rs backend/balancer-service/native/moo_core/src/tests.rs
git commit -m "feat(balancer): add rank_comfort_tilt field to native ConfigSpec (default 0.5)"
```

---

## Task 4: Rust — взвешенный `knee_scores` + проводка в ранг

**Files:**
- Modify: `backend/balancer-service/native/moo_core/src/archive.rs` (`knee_scores`, два внутренних вызова)
- Modify: `backend/balancer-service/native/moo_core/src/runner.rs:280`
- Test: `backend/balancer-service/native/moo_core/src/tests.rs`

- [ ] **Step 1: Написать падающий unit-тест**

Добавить в `tests.rs` (в крейте, `use super::*` уже есть):

```rust
#[test]
fn knee_scores_weights_shift_priority() {
    // Невырожденный фронт: A — лучший баланс/худший комфорт, C — наоборот, B — колено.
    let objectives = vec![
        Objectives { balance: 0.0, comfort: 10.0 },
        Objectives { balance: 5.0, comfort: 5.0 },
        Objectives { balance: 10.0, comfort: 0.0 },
    ];

    // Чистый вес баланса → лучший баланс (idx 0) ранжируется первым.
    let balance_tilt = knee_scores(&objectives, 1.0, 0.0);
    assert!(
        balance_tilt[0] < balance_tilt[1] && balance_tilt[1] < balance_tilt[2],
        "balance-weighted scores must rank best-balance first"
    );

    // Чистый вес комфорта → лучший комфорт (idx 2) первым.
    let comfort_tilt = knee_scores(&objectives, 0.0, 1.0);
    assert!(
        comfort_tilt[2] < comfort_tilt[1] && comfort_tilt[1] < comfort_tilt[0],
        "comfort-weighted scores must rank best-comfort first"
    );

    // Нейтральные веса (1,1) = прежняя формула sqrt(b²+c²) → колено (idx 1) первым.
    let neutral = knee_scores(&objectives, 1.0, 1.0);
    assert!(
        neutral[1] < neutral[0] && neutral[1] < neutral[2],
        "neutral weights keep the knee point first (legacy behaviour)"
    );
}
```

> Примечание: `Objectives` — `pub(crate)` структура с полями `balance: f64, comfort: f64`; конструируется в тестах того же крейта напрямую.

- [ ] **Step 2: Запустить — тест падает (сигнатура `knee_scores` ещё одноаргументная)**

Run: `cargo test --manifest-path backend/balancer-service/native/moo_core/Cargo.toml knee_scores_weights_shift_priority`
Expected: FAIL компиляции — `knee_scores` принимает 1 аргумент, передано 3.

- [ ] **Step 3: Сменить сигнатуру/формулу `knee_scores` в `archive.rs`**

Заменить:

```rust
pub(crate) fn knee_scores(objectives: &[Objectives]) -> Vec<f64> {
    let normed = normalize_objectives(objectives);
    normed
        .iter()
        .map(|o| (o.balance * o.balance + o.comfort * o.comfort).sqrt())
        .collect()
}
```

на:

```rust
pub(crate) fn knee_scores(objectives: &[Objectives], w_balance: f64, w_comfort: f64) -> Vec<f64> {
    let normed = normalize_objectives(objectives);
    normed
        .iter()
        .map(|o| (w_balance * o.balance * o.balance + w_comfort * o.comfort * o.comfort).sqrt())
        .collect()
}
```

- [ ] **Step 4: Обновить внутренние вызовы в `archive.rs` на нейтральные веса**

В `archive_selection_order` и `archive_select_elites` заменить оба вхождения:

```rust
    let scores = knee_scores(&objectives);
```

на:

```rust
    let scores = knee_scores(&objectives, 1.0, 1.0);
```

- [ ] **Step 5: Проводка веса в финальный ранг (`runner.rs`)**

В `runner.rs` заменить (около строки 280):

```rust
    let scores = knee_scores(&objs);
```

на:

```rust
    let tilt = ctx.config.rank_comfort_tilt;
    let scores = knee_scores(&objs, 1.0 - tilt, tilt);
```

- [ ] **Step 6: Запустить новый тест + весь набор Rust**

Run: `cargo test --manifest-path backend/balancer-service/native/moo_core/Cargo.toml`
Expected: PASS (включая `knee_scores_weights_shift_priority`).

- [ ] **Step 7: Регресс quality-harness (дефолтный tilt=0.5 в литералах → идентичность)**

Run: `cargo test --manifest-path backend/balancer-service/native/moo_core/Cargo.toml harness -- --ignored --nocapture`
Expected: PASS, медианы метрик не регрессируют.

- [ ] **Step 8: fmt + clippy**

Run: `cargo fmt --manifest-path backend/balancer-service/native/moo_core/Cargo.toml && cargo clippy --manifest-path backend/balancer-service/native/moo_core/Cargo.toml -- -D warnings`
Expected: чисто.

- [ ] **Step 9: Commit**

```bash
git add backend/balancer-service/native/moo_core/src/archive.rs backend/balancer-service/native/moo_core/src/runner.rs backend/balancer-service/native/moo_core/src/tests.rs
git commit -m "feat(balancer): weight balance/comfort in variant ranking via rank_comfort_tilt"
```

---

## Task 5: Python — проводка `rank_comfort_tilt` через конфиг

**Files:**
- Modify: `backend/balancer-service/src/services/balancer/config/defaults.py`
- Modify: `backend/balancer-service/src/schemas/balancer.py` (`ConfigOverrides`)
- Modify: `backend/balancer-service/src/services/balancer/config/public_contract.py` (`PUBLIC_CONFIG_KEYS`)
- Modify: `backend/balancer-service/src/services/balancer/config/provider.py` (`CONFIG_LIMITS`, `EDITABLE_CONFIG_FIELD_KEYS`, `CONFIG_FIELD_DEFINITIONS`)
- Modify: `backend/balancer-service/src/services/balancer/algorithm/moo_backend.py`
- Test: `backend/balancer-service/tests/test_balancer_config.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_balancer_config.py`:

```python
def test_rank_comfort_tilt_field_exposed() -> None:
    from src.services.balancer.config.provider import get_balancer_config_payload

    payload = get_balancer_config_payload()
    fields_by_key = {field["key"]: field for field in payload["fields"]}

    assert payload["defaults"]["rank_comfort_tilt"] == 0.5
    field = fields_by_key["rank_comfort_tilt"]
    assert field["type"] == "slider"
    assert field["group"] == "Quality weights"
    assert field["limits"] == {"min": 0.0, "max": 1.0}
```

- [ ] **Step 2: Запустить — падает (поля/ключа ещё нет)**

Run: `cd backend/balancer-service && uv run pytest tests/test_balancer_config.py::test_rank_comfort_tilt_field_exposed -v`
Expected: FAIL (KeyError `rank_comfort_tilt`).

- [ ] **Step 3: Добавить поле в `AlgorithmConfig` (`defaults.py`)**

В классе `AlgorithmConfig`, в секции cost-весов:

```python
    rank_comfort_tilt: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Ranking tilt between balance and comfort when ordering result "
            "variants. 0.5 = balanced (legacy); toward 1 favours comfort/off-role, "
            "toward 0 favours team balance (StdDev). Affects only variant ordering "
            "and primary selection, not the optimizer search."
        ),
    )
```

- [ ] **Step 4: Добавить в `ConfigOverrides` (`schemas/balancer.py`, `extra="forbid"`!)**

Рядом с прочими весами:

```python
    rank_comfort_tilt: float | None = Field(
        None, ge=0, le=1, description="Ranking tilt between balance and comfort (0.5 = balanced)"
    )
```

- [ ] **Step 5: Добавить ключ в `PUBLIC_CONFIG_KEYS` (`public_contract.py`)**

В множество `PUBLIC_CONFIG_KEYS` добавить:

```python
    "rank_comfort_tilt",
```

- [ ] **Step 6: `provider.py` — лимиты, editable-ключ, определение поля**

В `CONFIG_LIMITS` добавить:

```python
    "rank_comfort_tilt": {"min": 0.0, "max": 1.0},
```

В `EDITABLE_CONFIG_FIELD_KEYS` добавить:

```python
    "rank_comfort_tilt",
```

В конец списка `CONFIG_FIELD_DEFINITIONS` добавить запись (без `applies_to`):

```python
    {
        "key": "rank_comfort_tilt",
        "label": "Rank tilt (balance ↔ comfort)",
        "description": (
            "Shifts how result variants are ranked: 0.5 weighs team balance "
            "(StdDev) and comfort (off-role) equally; toward 1 prioritises "
            "comfort/off-role, toward 0 prioritises balance. Ordering only — "
            "does not change the optimizer search."
        ),
        "type": "slider",
        "group": "Quality weights",
    },
```

- [ ] **Step 7: Прокинуть в Rust-payload (`moo_backend.py`)**

В словарь `"config": { ... }` (рядом с прочими весами) добавить:

```python
            "rank_comfort_tilt": config.rank_comfort_tilt,
```

- [ ] **Step 8: Запустить конфиг-тесты**

Run: `cd backend/balancer-service && uv run pytest tests/test_balancer_config.py tests/test_config_consistency.py -v`
Expected: PASS (включая новый тест и инварианты консистентности).

- [ ] **Step 9: Commit**

```bash
git add backend/balancer-service/src/services/balancer/config/defaults.py backend/balancer-service/src/schemas/balancer.py backend/balancer-service/src/services/balancer/config/public_contract.py backend/balancer-service/src/services/balancer/config/provider.py backend/balancer-service/src/services/balancer/algorithm/moo_backend.py backend/balancer-service/tests/test_balancer_config.py
git commit -m "feat(balancer): expose rank_comfort_tilt through python config + native payload"
```

---

## Task 6: Frontend — shadcn Slider компонент

**Files:**
- Modify: `frontend/package.json` (зависимость)
- Create: `frontend/src/components/ui/slider.tsx`

- [ ] **Step 1: Добавить зависимость**

Run: `cd frontend && pnpm add @radix-ui/react-slider`
Expected: пакет добавлен в `dependencies`, lock обновлён.

- [ ] **Step 2: Создать компонент Slider (адаптация shadcn под индивидуальный radix-пакет и стиль проекта)**

Создать `frontend/src/components/ui/slider.tsx`:

```tsx
"use client";

import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";

const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn(
      "relative flex w-full touch-none select-none items-center",
      className,
    )}
    {...props}
  >
    <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted">
      <SliderPrimitive.Range className="absolute h-full bg-primary" />
    </SliderPrimitive.Track>
    <SliderPrimitive.Thumb className="block h-4 w-4 rounded-full border border-primary bg-white shadow-sm transition-colors hover:ring-4 hover:ring-ring/40 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-50" />
  </SliderPrimitive.Root>
));
Slider.displayName = SliderPrimitive.Root.displayName;

export { Slider };
```

- [ ] **Step 3: Проверить типы**

Run: `cd frontend && pnpm exec tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/components/ui/slider.tsx
git commit -m "feat(ui): add shadcn slider component (radix-ui/react-slider)"
```

---

## Task 7: Frontend — регистрация ключа `rank_comfort_tilt` и рендер слайдера

**Files:**
- Modify: `frontend/src/types/balancer.types.ts` (`SUPPORTED_BALANCER_CONFIG_KEYS`, `BalancerConfig`, `BalancerConfigFieldType`)
- Modify: `frontend/src/services/balancer.service.ts` (`SUPPORTED_CONFIG_FIELD_TYPES`)
- Modify: `frontend/src/app/balancer/components/balancer-config-helpers.ts` (`NUMERIC_CONFIG_KEYS`)
- Modify: `frontend/src/app/balancer/components/BalancerConfigDrawer.tsx` (`ConfigFieldControl` + импорт)
- Test: `frontend/src/app/balancer/components/balancer-config-helpers.test.ts`

- [ ] **Step 1: Написать падающий vitest на allowlist**

Добавить в `frontend/src/app/balancer/components/balancer-config-helpers.test.ts` тест, что `rank_comfort_tilt` не вырезается санитайзером:

```ts
import { sanitizeBalancerConfig } from "./balancer-config-helpers";

it("keeps rank_comfort_tilt in sanitized config", () => {
  const result = sanitizeBalancerConfig({ rank_comfort_tilt: 0.8 });
  expect(result.rank_comfort_tilt).toBe(0.8);
});
```

> Если в файле уже есть импорт `sanitizeBalancerConfig` — переиспользовать его, не дублировать.

- [ ] **Step 2: Запустить — падает (ключ не в allowlist)**

Run: `cd frontend && pnpm exec vitest run src/app/balancer/components/balancer-config-helpers.test.ts`
Expected: FAIL — `result.rank_comfort_tilt` is `undefined`.

- [ ] **Step 3: Зарегистрировать ключ и тип в `balancer.types.ts`**

В массив `SUPPORTED_BALANCER_CONFIG_KEYS` добавить (рядом с прочими weight-ключами):

```ts
  "rank_comfort_tilt",
```

В интерфейс `BalancerConfig` добавить:

```ts
  rank_comfort_tilt?: number;
```

В `BalancerConfigFieldType` добавить `"slider"`:

```ts
export type BalancerConfigFieldType =
  | "boolean"
  | "float"
  | "integer"
  | "role_mask"
  | "select"
  | "slider";
```

- [ ] **Step 4: Разрешить тип `slider` в сервисе**

В `frontend/src/services/balancer.service.ts` в `SUPPORTED_CONFIG_FIELD_TYPES` добавить `"slider"`:

```ts
const SUPPORTED_CONFIG_FIELD_TYPES = new Set<string>([
  "boolean",
  "float",
  "integer",
  "role_mask",
  "select",
  "slider"
]);
```

- [ ] **Step 5: Добавить ключ в `NUMERIC_CONFIG_KEYS`**

В `frontend/src/app/balancer/components/balancer-config-helpers.ts` в `NUMERIC_CONFIG_KEYS` добавить:

```ts
  "rank_comfort_tilt",
```

- [ ] **Step 6: Запустить vitest — должен пройти**

Run: `cd frontend && pnpm exec vitest run src/app/balancer/components/balancer-config-helpers.test.ts`
Expected: PASS.

- [ ] **Step 7: Рендер слайдера в `BalancerConfigDrawer.tsx`**

Добавить импорт рядом с другими UI-импортами:

```tsx
import { Slider } from "@/components/ui/slider";
```

В функции `ConfigFieldControl`, перед финальным `return <NumericConfigInput ... />`, добавить ветку:

```tsx
  if (field.type === "slider") {
    const numeric =
      typeof value === "number" ? value : Number(value ?? field.default ?? 0);
    const min = field.limits?.min ?? 0;
    const max = field.limits?.max ?? 1;
    return (
      <div className="flex flex-col gap-2">
        <Slider
          min={min}
          max={max}
          step={0.05}
          value={[numeric]}
          onValueChange={(next) => onChange(next[0])}
        />
        <div className="flex justify-between text-[11px] text-white/45">
          <span>balance</span>
          <span className="tabular-nums text-white/70">{numeric.toFixed(2)}</span>
          <span>comfort</span>
        </div>
      </div>
    );
  }
```

- [ ] **Step 8: Типы + lint**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint src/app/balancer/components/BalancerConfigDrawer.tsx src/services/balancer.service.ts src/types/balancer.types.ts src/app/balancer/components/balancer-config-helpers.ts`
Expected: без ошибок.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/balancer.types.ts frontend/src/services/balancer.service.ts frontend/src/app/balancer/components/balancer-config-helpers.ts frontend/src/app/balancer/components/balancer-config-helpers.test.ts frontend/src/app/balancer/components/BalancerConfigDrawer.tsx
git commit -m "feat(balancer): rank tilt slider control in config drawer"
```

---

## Task 8: Интеграционная проверка (e2e через пересборку нативного модуля)

**Files:** нет правок — только сборка и ручная проверка.

- [ ] **Step 1: Пересобрать нативный модуль `moo_core` для Python**

Из `backend/balancer-service/native/moo_core`:

```bash
maturin develop --release
```

> Если в репо используется иной build-механизм для нативного модуля (justfile / make / docker), применить его. Цель — чтобы установленный `moo_core` содержал поле `rank_comfort_tilt`.

- [ ] **Step 2: Поднять стек и прогнать баланс**

Поднять `balancer-service` + фронт (как обычно в проекте), открыть Balancer, выбрать турнир, открыть Balancer settings → группа «Quality weights» → убедиться, что есть слайдер «Rank tilt (balance ↔ comfort)» (дефолт 0.5), и нет бейджей «Applies:».

- [ ] **Step 3: Проверить эффект tilt**

Прогнать баланс при `tilt=0.5` — зафиксировать порядок вариантов (должен совпасть с прежним). Сдвинуть слайдер к 1.0, прогнать снова — варианты с меньшим off-role/болью должны подняться выше; к 0.0 — варианты с меньшим StdDev/балансом. Отображаемый `composite_score` в карточках монотонно растёт сверху вниз при любом значении.

- [ ] **Step 4 (опц.): зафиксировать наблюдение**

Если есть e2e-набор для балансера — добавить сценарий «слайдер виден, сдвиг меняет порядок». Иначе достаточно ручной проверки выше.

---

## Self-Review (выполнено при написании плана)

- **Покрытие спека:** ранг-формула (Task 4), параметр/проводка Python↔Rust (Tasks 3,5), UI-слайдер (Tasks 6,7), удаление `applies_to` (Tasks 1,2), harness-регресс (Task 4 Step 7), критерии приёмки (Task 8) — покрыто.
- **Плейсхолдеры:** нет TODO/«добавить тесты» без кода; весь код приведён.
- **Согласованность типов:** `knee_scores(objectives, w_balance, w_comfort)` единообразно (archive внутренние = `(1.0,1.0)`, runner = `(1.0 - tilt, tilt)`); ключ `rank_comfort_tilt` и тип поля `"slider"` согласованы во всех Python/TS allowlist'ах.
