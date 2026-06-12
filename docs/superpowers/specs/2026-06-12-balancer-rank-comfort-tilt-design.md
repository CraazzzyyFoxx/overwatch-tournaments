# Balancer: настраиваемый баланс/комфорт тилт в ранге вариантов

**Дата:** 2026-06-12
**Статус:** approved (design)
**Ветка реализации:** `feature/balancer-rank-comfort-tilt` (от `develop`)

## Проблема

После прогона балансера пользователь сравнивает варианты по колонкам 🔶 off-role и
📊 StdDev, но порядок вариантов («лучший → худший») определяется `composite_score` —
евклидовым расстоянием до идеальной точки по двум **агрегированным** целям `balance` и
`comfort`. Из-за этого «лучший» по composite вариант может выглядеть хуже по тем двум
метрикам, которые пользователь реально читает:

- `comfort` строится из непрерывной «боли» (`avg_discomfort`, `max_pain`,
  sub-role коллизии), а не из счётчика off-role.
- `balance` — сумма ~7 членов; `mmr_std` (колонка StdDev) — лишь один из них.
- Ранг жёстко комбинирует `balance` и `comfort` 50/50, и веса оптимизатора это
  соотношение **в ранге** не сдвигают (мешает пер-фронтовая нормализация + фиксированный 50/50).

Пользователь хочет управлять соотношением баланс/комфорт **именно в ранжировании**
вариантов (какой вариант считается «лучшим» и идёт первым), не трогая оптимизатор.

## Цель

Дать одну настраиваемую из UI ручку, которая сдвигает соотношение баланс/комфорт
в `composite_score`-**ранге**. Оптимизатор (objective-функции, поиск, archive-операции)
остаётся неизменным — quality-harness не должен регрессировать.

### Вне области (Non-goals)

- Не меняем objective-функции (`objective_balance` / `objective_comfort`) и веса поиска.
- Не делаем ранг по «сырым» off-role-счётчику / mmr_std напрямую (отклонено пользователем).
- Не меняем какие решения находит солвер — только их порядок/выбор primary и
  отображаемое число composite.

## Решение

### Параметр

`rank_comfort_tilt: float ∈ [0, 1]`, дефолт **0.5**.

- `0.5` — текущее поведение (50/50): порядок вариантов идентичен сегодняшнему.
- `→ 1.0` — комфорт (off-role/боль) важнее в ранге; варианты с меньшим off-role поднимаются.
- `→ 0.0` — баланс (StdDev/total) важнее в ранге.

### Формула ранга

```
composite = sqrt( (1 - tilt) * balance_norm²  +  tilt * comfort_norm² )
```

где `balance_norm`, `comfort_norm` — текущая пер-фронтовая min-max нормализация
([objectives.rs::normalize_objectives](../../../backend/balancer-service/native/moo_core/src/objectives.rs)).

**Инвариант дефолта:** при `tilt = 0.5` формула даёт
`sqrt(0.5)·sqrt(balance_norm² + comfort_norm²)` — монотонная (×const) трансформация
текущего `composite`. Поэтому **порядок и выбор primary при дефолте идентичны
сегодняшним**; меняется лишь абсолютное отображаемое число composite (×≈0.707).
Это сознательный трейд-офф выбранного «слайдер»-варианта.

### Изоляция от поиска (harness-safe)

`knee_scores` используется в двух классах мест:

`knee_scores` параметризуется двумя весами: `knee_scores(objectives, w_balance, w_comfort)`,
формула `sqrt(w_balance·balance_norm² + w_comfort·comfort_norm²)`.

1. **Финальный ранг** ([runner.rs:280](../../../backend/balancer-service/native/moo_core/src/runner.rs)):
   порядок возвращаемых вариантов, выбор primary, отображаемый `score`.
   → передаёт `(1.0 - tilt, tilt)`, где `tilt = ctx.config.rank_comfort_tilt`.
2. **Внутренние archive-операции** во время поиска
   ([archive.rs::archive_selection_order](../../../backend/balancer-service/native/moo_core/src/archive.rs),
   `archive_select_elites`): прунинг архива и инжекция элит.
   → передают единичные веса `(1.0, 1.0)` — формула `sqrt(b² + c²)`, **байт-идентичная**
   текущей. Поведение поиска и элит не меняется вообще (не только порядок), любые тесты
   на абсолютные значения knee-скоров остаются валидны, quality-harness зелёный.

## Изменения по компонентам

### Rust (`backend/balancer-service/native/moo_core`)

| Файл | Изменение |
|---|---|
| `archive.rs` | `knee_scores(objectives, w_balance: f64, w_comfort: f64)`. Внутренние вызовы (`archive_selection_order`, `archive_select_elites`) передают `(1.0, 1.0)`. |
| `runner.rs` | Финальный `knee_scores(&objs, 1.0 - tilt, tilt)` с `tilt = ctx.config.rank_comfort_tilt`; `knee_order` получает уже взвешенные `scores`. Отображаемый `scores[idx]` (VariantResponse.score) — взвешенный. |
| `lib.rs` | `ConfigSpec`: поле `rank_comfort_tilt: f64` с `#[serde(default = "default_rank_comfort_tilt")]` (= 0.5). |
| `bench_api.rs`, `tests.rs` | Добавить `rank_comfort_tilt: 0.5` в литералы `ConfigSpec`. |

### Python (`backend/balancer-service/src/services/balancer/config`)

| Файл | Изменение |
|---|---|
| `defaults.py` | `rank_comfort_tilt: float = Field(default=0.5, ge=0.0, le=1.0, description=...)`. |
| `schemas/balancer.py` | `ConfigOverrides` (`extra="forbid"`!) — добавить `rank_comfort_tilt: float | None = Field(None, ge=0, le=1, ...)`, иначе персист падает/дропается. |
| `provider.py` | Ключ в `EDITABLE_CONFIG_FIELD_KEYS`; запись в `CONFIG_FIELD_DEFINITIONS` (label «Rank tilt (balance ↔ comfort)», group «Quality weights», `type: "slider"`, **без `applies_to`**); запись в `CONFIG_LIMITS` `{"min": 0.0, "max": 1.0}` (step `0.05` — константа в slider-ветке фронта, т.к. тип `limits` = `{min,max}`). |
| `public_contract.py` | Ключ в `PUBLIC_CONFIG_KEYS` (персист/сериализация). |

`moo_backend.py` (`algorithm/`): прокинуть `"rank_comfort_tilt": config.rank_comfort_tilt`
в payload `config`.

### Frontend

| Файл | Изменение |
|---|---|
| `package.json` | Зависимость `@radix-ui/react-slider` (под существующую конвенцию индивидуальных radix-пакетов, как `@radix-ui/react-switch`). |
| `src/components/ui/slider.tsx` | **Новый** — канонический shadcn Slider, адаптированный под `@radix-ui/react-slider` (а не unified `radix-ui`) и стиль проекта (`cn`, токены `bg-primary`/`bg-muted`/`ring-ring`). |
| `src/services/balancer.service.ts` | Добавить `"slider"` в `SUPPORTED_CONFIG_FIELD_TYPES` (иначе `normalizeConfigField` дропнет поле). |
| `src/app/balancer/components/balancer-config-helpers.ts` | Добавить `rank_comfort_tilt` в `NUMERIC_CONFIG_KEYS`. |
| `src/app/balancer/components/BalancerConfigDrawer.tsx` | Новая ветка `field.type === "slider"` в `ConfigFieldControl` → `<Slider min max step value=[v] onValueChange>` + текущее значение и подписи «balance ↔ comfort». |
| `src/types/balancer.types.ts` | Добавить `"slider"` в `BalancerConfigFieldType`; `"rank_comfort_tilt"` в `SUPPORTED_BALANCER_CONFIG_KEYS` (драйвит `BalancerConfigKey`); `rank_comfort_tilt?: number` в интерфейс `BalancerConfig`. |

`onValueChange` у radix-slider отдаёт `number[]` — оборачиваем (`[value] → value`) под существующий
`onChange(field.key, nextValue)`.

### Сопутствующая чистка: удаление `applies_to`

Алгоритм теперь один (`moo`), поэтому per-field `applies_to` — мёртвая метаданность.
Удаляется вместе с фичей, чтобы новое поле его не несло.

| Файл | Изменение |
|---|---|
| `provider.py` | Убрать `"applies_to": ["moo"]` из всех записей `CONFIG_FIELD_DEFINITIONS`. |
| `tests/test_balancer_config.py` | Убрать ассерт `assert field["applies_to"]`. |
| `src/types/balancer.types.ts` | Убрать `applies_to: BalancerAlgorithm[]` из `BalancerConfigField`. |
| `src/services/balancer.service.ts` | Убрать `applies_to` из `RawBalancerConfigField`, фильтр `appliesTo`/`if (appliesTo.length === 0) return null` и `applies_to: appliesTo` из возврата `normalizeConfigField`. |
| `src/app/balancer/components/BalancerConfigDrawer.tsx` | Убрать бейдж `<span>Applies: {field.applies_to.join(", ")}</span>`. |

Out of scope: сам выбор `algorithm` (ключ конфига, `SUPPORTED_BALANCER_ALGORITHMS`) не трогаем —
убираем только per-field `applies_to`.

### Тесты

- **Rust unit** (`tests.rs`): на синтетическом фронте с >1 не-доминируемыми точками —
  `tilt > 0.5` ставит вариант с меньшим `comfort` раньше; `tilt = 0.5` воспроизводит
  текущий порядок; крайние `0.0`/`1.0` детерминированы (тай-брейк через
  лексикографический fallback в `knee_order`).
- **Python** (`test_config_consistency.py`): новый ключ проходит существующие инварианты
  (присутствует как поле `AlgorithmConfig`, в `EDITABLE_CONFIG_FIELD_KEYS`, валидный для
  `CONFIG_LIMITS`, определён в `CONFIG_FIELD_DEFINITIONS`). При необходимости — обновить
  локальную копию `PUBLIC_CONFIG_KEYS` в тестовом файле.
- **Регресс harness:** `cargo test harness` (включая `--ignored` 40t) — медианы метрик
  верхнего варианта не регрессируют (дефолтный `tilt=0.5` гарантирует идентичность).

## Поток данных

```
UI slider (rank_comfort_tilt)
  → persisted tournament/workspace config (PUBLIC_CONFIG_KEYS)
  → AlgorithmConfig (defaults.py)
  → moo_backend.py payload.config.rank_comfort_tilt
  → Rust ConfigSpec.rank_comfort_tilt
  → runner.rs final knee_scores(objs, tilt)
  → VariantResponse.score (взвешенный) + порядок вариантов + primary
  → frontend: порядок карточек, авто-выбор лучшего (уже сделано), composite в карточке
```

## Риски и смягчение

| Риск | Смягчение |
|---|---|
| Регресс quality-harness | Дефолт `0.5` порядко-идентичен; внутренние archive-вызовы на `0.5`. |
| Дрейф конфиг-инвариантов | `test_config_consistency.py` ловит пропуск ключа в любом из источников. |
| Отображаемое число composite сменило масштаб | Ожидаемо (трейд-офф слайдера); тултип «lower = better» остаётся верен. |
| Старые сохранённые конфиги без поля | `#[serde(default)]` (Rust) + `Field(default=0.5)` (Python) → 0.5. |

## Критерии приёмки

1. Дефолтный прогон (`tilt=0.5`) даёт тот же порядок вариантов и тот же primary, что и до изменения.
2. Слайдер виден в UI (группа «Quality weights»), диапазон 0..1, шаг 0.05, дефолт 0.5.
3. `tilt → 1` поднимает варианты с меньшим off-role/болью вверх; `tilt → 0` — с меньшим StdDev/балансом.
4. `cargo test` (вкл. harness) и `pytest` зелёные; `test_config_consistency.py` проходит.
5. Отображаемый `composite_score` монотонно растёт сверху вниз в гриде/селекторе при любом tilt.
