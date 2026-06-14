# Runbook: пересчёт shift-сигнала на merit (Performance v2 → shift v2 → Linear)

Цель: после правок методики (merit-таргет shift v2, индивидуальный Linear, дивизион-нормализованный fallback) привести prod-данные в порядок, чтобы сигнал отражал **индивидуальный merit с поправкой на контекст команды**, а не командный результат и не дивизион-слепой fallback.

> Почему так: `local_zscore` Performance v2 — это контекст-adjusted личный вклад, нормированный по бэнду дивизиона (DivisionGrid). Он кормит и merit-таргет shift v2, и `perf_merit` в Linear. Сейчас Performance v2 материализован лишь для ~10% турниров → большинство идёт на дивизион-слепой fallback → «1 место → −ранг» и схлопывание. Лечится тем, что **сначала** материализуем Performance v2 по всей истории, **потом** переобучаем shift v2 и пересчитываем.

## Предусловия
- Образ `registry.craazzzyyfoxx.me/aqt-analytics:latest` собран/задеплоен с коммитами этой ветки (Фазы A/B/C + дивизион-fallback).
- Артефакты ML живут в named-volume `analytics-models:/opt/anak/models`, **общем** для сервисов `analytics` и `analytics-worker`. Любой из них видит артефакты; запускать ML лучше в `analytics-worker` (8 CPU / 4 ГБ против 2 CPU / 1.5 ГБ).
- БД и креды берутся из `env/common.env` + `env/analytics.env` (уже в контейнере через `env_file`). Тяжёлые шаги — `train`/`backfill` — пишут в prod, выполнять **только на prod-хосте**.
- `latest tournament id = 73`, всего 63 турнира (id разрежены) — далее `CUTOFF=73`, диапазон `--from 1 --to 73`.

## Как запускать CLI из Docker

Все ML-операции — это `python -m src.services.ml.cli <cmd>` (WORKDIR контейнера `/app/analytics-service`, PYTHONPATH настроен). Запускаем в **уже работающем** `analytics-worker` (там живые БД-коннект, прокси, volume моделей):

```bash
# на prod-хосте, из каталога с docker-compose.production.yml, ВНУТРИ tmux/screen
# (exec умрёт, если оборвётся SSH; train/backfill идут минутами)
COMPOSE="docker compose -f docker-compose.production.yml"

$COMPOSE exec analytics-worker python -m src.services.ml.cli --help
```

Альтернатива — одноразовый изолированный контейнер (не мешает воркеру, тот же volume/env):
```bash
$COMPOSE run --rm --no-deps analytics-worker python -m src.services.ml.cli <cmd>
```
Рекомендация: `exec` в работающий воркер (заведомо рабочая сеть/прокси/БД).

## Шаги

### 0. Снимок «до» (read-only, с лаптопа)
```bash
cd backend/analytics-service && uv run python scripts/diagnose_performance_coverage.py
```
Запомнить покрытие Performance v2 и распределение `local_zscore`. (Скрипт читает `env/common.env` и коннектится к prod напрямую — поэтому с лаптопа, не из контейнера.)

### 1. Материализовать Performance v2 по всей истории (источник merit)
Артефакт Performance v2 уже обучен (cutoff=73) — переобучать не обязательно; нужно **доинферить** недостающие турниры:
```bash
$COMPOSE exec analytics-worker python -m src.services.ml.cli \
  backfill --from 1 --to 73 --models performance
```
(При желании пересобрать модель: `... train --cutoff 73 --models performance` перед backfill.)

### 2. Переобучить shift v2 на merit
Обязательно (старый артефакт обучен на realised-переходе; новый таргет — merit из `local_zscore`, который теперь есть после шага 1):
```bash
$COMPOSE exec analytics-worker python -m src.services.ml.cli \
  train --cutoff 73 --models shift
```

### 3. Доинферить v2 по всей истории (shift / standings / anomalies / match_quality)
```bash
$COMPOSE exec analytics-worker python -m src.services.ml.cli \
  backfill --from 1 --to 73
```
Идемпотентно (удаляет+переписывает по турниру/алгоритму). Обновляет «OpenSkill + ML».

### 4. Пересчитать v1 (Linear / Points)
ML-CLI **не** трогает v1 — отображаемый «Linear» обновляется только пересчётом v1 (`recalculate_analytics`), который читает свежий `perf_merit`/`local_zscore`. Запускается **compute-джобом по турниру** (он делает v1 + v2 вместе) через API (auth `analytics.update`):
```bash
# подставить реальный хост/токен; повторить для нужных tournament_id
curl -X POST https://<api-host>/v2/jobs \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"kind":"compute","tournament_id":73}'
```
(Либо штатной кнопкой пересчёта в админке, если ей пользуются.) Без этого шага «Linear» останется на старых значениях.

### 5. (Опционально) выровнять шкалу Linear под merit v2
```bash
$COMPOSE exec analytics-worker python -m src.services.ml.cli fit-weights
```
Взять `suggested_linear_shift_scale` → выставить `LINEAR_SHIFT_SCALE=<value>` в `backend/env/analytics.env` → перезапустить `analytics` и `analytics-worker` → повторить шаг 4 (v1 пересчёт). `SHIFT_MERIT_SCALE` (дефолт 0.5) тоже env-настраиваемый, если merit слишком слабый/сильный.

### 6. Верификация
- Покрытие: повторить шаг 0 — Performance v2 должно быть ~100%, `local_zscore` с разбросом (не все 0).
- Метрики: `... cli backtest --window 5` (после Фазы D появятся merit-метрики: монотонность, carry-тест, smurf-recall, антисхлопывание; пока — realised-метрики как справка).
- Спот-чек в UI на свежем турнире:
  - игрок с флагом **smurf** → заметный `+`;
  - **коастер на чемпионской команде** (лично ниже когорты своего дивизиона) → ~0/слабый минус, **не** большой `+`;
  - **сильный игрок низкого дивизиона** → `+`, а не штраф за абсолютные цифры.

## Откат
- Артефакты версионируются в реестре (`analytics.ml_model_artifact`, `is_active`): прежний активный shift-артефакт можно вернуть, пометив его `is_active=true` (и деактивировав новый) — без передеплоя кода.
- Шифты в `analytics.shifts` пересчитываются идемпотентно: повторный `backfill` со старым артефактом вернёт прежние значения.
- Откат кода — обычный git-revert ветки + передеплой.

## Заметки/риски
- Порядок критичен: Performance v2 (шаг 1) **до** train shift (шаг 2) и **до** v1-пересчёта (шаг 4) — иначе merit/`perf_merit` снова на fallback.
- `t#59` в снимке: perf-строки есть, но `local_zscore=0` (когорта не построилась, `ref_n=0`). Если повторится после backfill — смотреть, резолвится ли дивизион/хватает ли когорты по роли.
- Тяжёлый шаг — `train` (LightGBM/XGBoost). Воркер 8 CPU/4 ГБ; backfill идёт по-турнирно, память ок.
- Прокси/сеть: предпочесть `exec` в работающий `analytics-worker` (а не `run`), чтобы гарантированно были БД-доступ и `ss-local`.
```
