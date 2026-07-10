# MVP Impact Scoring — Runbook выката

> **Оператору:** этот документ НЕ исполняется автоматически. Порядок шагов
> обязателен. Пункты 2 → 3 нельзя менять местами: бэкфилл падает на
> preflight-проверке, если базлайны ещё не посчитаны.
>
> Реализация: ветка `feature/mvp-impact-scoring` (Tasks 1–9). Спека:
> `docs/superpowers/specs/2026-07-10-mvp-impact-scoring-design.md`.
> Прод: `anakq.xyz` → `72.56.118.90`, стек в `/root/overwatch-tournaments`.

## Что именно катим

- Миграция `mvpimp0001`: 7 новых значений enum `logstatsname`
  (`FirstPicks/FirstDeaths/UltimateKills/SupportKills/ImpactPoints/ImpactRank/OverperformanceScore`)
  + таблица `matches.stat_baselines`.
- parser: событийные статы из kill_feed + impact-скоринг в пайплайне лога;
  сервис базлайнов; CLI бэкфилла; RPC пересчёта.
- app-service: поля `impact_rank/impact_points/overperformance_score/overperformance_badge`
  в user-эндпоинтах.
- frontend: MVP-пилюли на `impact_rank`, бейдж «Сверх ожиданий», колонка
  «Impact» + «Очки (классика)».

Формула версионируется константой `FORMULA_VERSION = "impact_v1"`
(`backend/shared/core/impact.py`). Старые `PerformancePoints`/`Performance`
сохраняются и показываются рядом — фронт использует `impact_rank` с
фолбэком на `performance`, так что до сидирования/бэкфилла UI не ломается.

---

## Шаг 1 — Deploy backend

1. Смёржить `feature/mvp-impact-scoring` → `develop` → выкат по обычному
   процессу. Миграция `mvpimp0001` применяется штатно на деплое
   (`down_revision = wsbrand0002`).
2. После деплоя — **обязательный `restart nginx`** (иначе 502, гоча прод-хоста
   `72.56.118.90`).
3. Санити после миграции (read-only):
   ```sql
   -- новые значения enum на месте (persist = ИМЯ члена, не .value):
   SELECT unnest(enum_range(NULL::logstatsname))::text
   WHERE unnest(enum_range(NULL::logstatsname))::text IN
     ('FirstPicks','FirstDeaths','UltimateKills','SupportKills',
      'ImpactPoints','ImpactRank','OverperformanceScore');
   -- ожидаемо: 7 строк.

   SELECT to_regclass('matches.stat_baselines');  -- не NULL
   ```

> Примечание: **не** применять миграцию из dev-окружения (`alembic upgrade`),
> env dev указывает на прод. Миграция едет только штатным деплоем.

## Шаг 2 — Сид базлайнов (ДО бэкфилла)

Базлайны должны существовать до бэкфилла и до того, как пайплайн начнёт
писать impact-статы (без базлайнов пайплайн грациозно пропускает impact и
пишет только Performance — см. `_calculate_and_add_derived_stats`).

**Вариант A (предпочтительно) — RPC суперюзером:** вызвать
`rpc.parser.impact.recompute_baselines` из-под аккаунта с `is_superuser`.
Ответ: `{"rows": N, "formula_version": "impact_v1"}`.

**Вариант B — на хосте (надёжно, без UI):**
```bash
cd /root/overwatch-tournaments
docker compose exec parser-worker uv run python -c "
import asyncio
from src.core.caching import configure_cache
from src.core import db
from src.services.baselines import flows

async def main():
    configure_cache()                      # обязателен: cashews в отдельном процессе
    async with db.async_session_maker() as session:
        n = await flows.recompute(session)
        print('baseline rows:', n)

asyncio.run(main())
"
```
> Уточните реальное имя compose-сервиса parser-воркера (`docker compose ps`);
> в этом стеке фоновые сервисы имеют суффикс `-worker`.
> `recompute` атомарно заменяет строки версии `impact_v1` и инвалидирует кэш;
> при пустом результате он бросает `RuntimeError` (защита от затирания
> базлайнов), а не оставляет таблицу пустой.

## Шаг 3 — Бэкфилл истории

Идемпотентный CLI (можно гонять повторно и по турнирам):
```bash
docker compose exec parser-worker uv run python backfill_impact.py
# или по одному турниру:
docker compose exec parser-worker uv run python backfill_impact.py --tournament-id <ID>
```
- CLI сам зовёт `configure_cache()` и падает на preflight, если базлайны не
  посчитаны (Шаг 2).
- Коммит на каждый матч; `backfill_match` идемпотентен (удаляет 7 новых
  статов матча перед вставкой).
- **Circuit breaker:** при 10 падениях подряд `backfill_all` прерывается с
  `RuntimeError` (признак системной ошибки, а не единичных плохих матчей).
- По завершении проверить сводку: **`failed` должно быть 0** (или объяснимо
  малым). Ненулевой `failed` — разобрать логи по `match_id`.

## Шаг 4 — Верификация SQL (read-only)

```sql
-- 1) базлайны: 3 роли × 4 бакета(-1,0,1,2) × 17 статов ≈ 204
SELECT count(*) FROM matches.stat_baselines WHERE formula_version = 'impact_v1';
SELECT role, rank_bucket, count(*) FROM matches.stat_baselines
  WHERE formula_version = 'impact_v1' GROUP BY role, rank_bucket ORDER BY role, rank_bucket;

-- 2) ImpactRank посчитан примерно на всех матчах со статами (~6.9k):
SELECT count(DISTINCT match_id) FROM matches.statistics WHERE name = 'ImpactRank';
--    сравнить с:
SELECT count(DISTINCT match_id) FROM matches.statistics WHERE name = 'Performance';

-- 3) выборочно 2-3 матча: ImpactRank=1 осмыслен, сравнить со старым Performance=1
SELECT match_id, user_id, name, value FROM matches.statistics
  WHERE match_id = <MATCH_ID> AND name IN ('ImpactRank','Performance','ImpactPoints','OverperformanceScore')
    AND hero_id IS NULL AND round = 0
  ORDER BY user_id, name;
```
> Все имена статов в SQL — **ИМЕНА членов** enum (SQLAlchemy персистит имя, не
> `.value`): `'ImpactRank'`, а не `'impact_rank'`.

### 4a — Проверки, отложенные из код-ревью (untested-DB код)

Эти пути покрыты юнит-тестами только в чистой части; их SQL проверяется
здесь, на живых данных:

- **Идемпотентность бэкфилла:** прогнать `backfill_impact.py` на одном
  турнире **дважды подряд** и убедиться, что строки 7 новых статов
  побайтово идентичны (нет дублей/сдвигов):
  ```sql
  SELECT name, count(*) FROM matches.statistics
    WHERE match_id IN (SELECT id FROM matches.match WHERE encounter_id IN (
      SELECT id FROM tournament.encounter WHERE tournament_id = <ID>))
      AND name IN ('FirstPicks','FirstDeaths','UltimateKills','SupportKills',
                   'ImpactPoints','ImpactRank','OverperformanceScore')
    GROUP BY name;
  ```
  Счётчики после 1-го и 2-го прогона должны совпасть.
- **Роль/ранг джойн (`_load_player_refs` / `_load_stats_frame`):** выборочно
  проверить матч с заменами/ротацией состава — у «сиротских»
  `(team_id, user_id)` без ростер-строки `OverperformanceScore` должен быть 0
  (роль=None → нулевой скор), а не мусорный скор против элитного бакета.
  `ImpactPoints` (общероль-бакет −1) от этого не зависит.
- **Ранговые бакеты:** убедиться, что `meta.bucket_bounds` заморожены и
  осмысленны:
  ```sql
  SELECT DISTINCT meta->'bucket_bounds' FROM matches.stat_baselines
    WHERE formula_version = 'impact_v1';
  ```

## Шаг 5 — Deploy frontend

Стандартный выкат фронта. Чистить Turbopack-кэш **не** требуется — дизайн-токены
не менялись.

## Шаг 6 — Smoke на проде

1. Профиль игрока: MVP-пилюли отображаются (ранг по `impact_rank`); у игрока с
   `overperformance_badge` — вторая пилюля «Сверх ожиданий».
2. Страница матча: колонки «Impact» и «Очки (классика)» на месте, значения
   осмысленны.
3. Матч без impact-строк (если остался незабэкфилленный) — пилюля падает на
   legacy `performance`, UI не ломается.
4. app-service читает поля без ошибок (эндпоинты профиля/турниров отвечают
   200, не 500).

### 6a — Прогон app-service тестов против живой БД

Интеграционные тесты app-service локально пропускаются (нет `anak_dev`).
Перед/после выката прогнать против населённой dev-БД:
```bash
cd backend && uv run pytest app-service/tests/api/routes/test_user_impact.py \
  app-service/tests/api/routes/test_user.py -v
```
Ожидаемо зелёные (не skip). Гоча: в `test_user.py` есть пред-существующая
устаревшая фикстура `_ensure_compare_division_fixture` (ссылается на
`Player.div`/`user_id`, не передаёт `Tournament.workspace_id`) — это карантинный
тест из прошлой CI-починки, к этой фиче отношения не имеет.

## Наблюдение после выката

- **Perf-watch (Path A):** `overperf_cte` в неоплаченном (unpaginated)
  read-path строит оконный `rank()` по ВСЕЙ популяции `OverperformanceScore`
  (round=0, hero NULL) на каждый запрос. При росте таблицы — при необходимости
  ограничить окно матчами пользователя (как в paginated-path). Следить за
  латентностью профиля/`get_tournaments`.
- **RPC:** подтвердить, что `rpc.parser.impact.recompute_baselines` реально
  проходит через живой RabbitMQ + БД (локально проверялся только ast/import).

## Откат

- Фронт: откат деплоя (поля опциональны, backend-совместим).
- Backend: impact-статы аддитивны; при необходимости отключить их запись можно
  через отсутствие базлайнов (пайплайн грациозно пропускает impact). Полное
  удаление строк:
  ```sql
  DELETE FROM matches.statistics WHERE name IN
    ('FirstPicks','FirstDeaths','UltimateKills','SupportKills',
     'ImpactPoints','ImpactRank','OverperformanceScore');
  DELETE FROM matches.stat_baselines WHERE formula_version = 'impact_v1';
  ```
  Значения enum и таблицу `stat_baselines` удалять не нужно (миграция
  `downgrade` умеет дропнуть таблицу; значения enum PG не удаляет).
