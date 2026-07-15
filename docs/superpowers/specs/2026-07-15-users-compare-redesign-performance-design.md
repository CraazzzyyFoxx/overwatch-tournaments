# `/users/compare`: редизайн и ускорение — согласованный дизайн

**Дата:** 2026-07-15
**Статус:** согласован
**Область:** frontend `/users/compare`, RPC `rpc.app.users.compare`, RPC `rpc.app.users.compare_heroes`, Redis/cashews-инвалидация

## 1. Контекст

Страница `/users/compare` функционально поддерживает сравнение общей статистики и Hero/Map-метрик, но визуально отстаёт от остальных публичных вкладок. Вместо общего `PageHero` она выводит локальный `h1` внутри `CardSurface`.

Backend global/cohort comparison строит широкую выборку пользователей с множеством коррелированных scalar subquery. Затем Python загружает всю популяцию, вычисляет средние и повторно сортирует значения для каждой метрики. Hero/Map comparison выполняет несколько последовательных запросов к статистике и каталогам. Frontend дополнительно загружает справочники героев и карт даже в Overall scope.

## 2. Понимание задачи

- Перевести `/users/compare` на существующую Editorial Tactical дизайн-систему.
- Добавить общий `PageHero`, согласованный с `/users` и `/users/heroes-compare`.
- Сохранить фильтры, URL-параметры, формулы и публичные API-контракты.
- Ускорить cold request через set-based SQL.
- Ускорить повторные запросы через существующий Redis/cashews.
- Сохранить корректность global, cohort, target-user и Hero/Map режимов.
- Не менять дизайн остальных страниц и не вводить новую инфраструктуру.

## 3. Предположения и NFR

- Целевой P95 критического compare endpoint — менее 1 секунды на текущем объёме данных.
- Решение должно оставаться приемлемым при удвоении текущего объёма.
- Warm request обслуживается из Redis; допустимая устарелость — до 60 секунд.
- Недоступность Redis не должна делать compare endpoint недоступным.
- Endpoint остаётся публичным с текущей optional-auth политикой.
- Новые персональные данные не добавляются.
- Владение и сопровождение остаются в app-service/frontend.
- Production load test не входит в задачу.
- Индексы разрешены, но добавляются только по результату `EXPLAIN ANALYZE`.
- Frontend проверяется lint/tests; `next build` не запускается.

## 4. Выбранный подход

Используется комбинация двух подходов:

1. Set-based SQL для ускорения первого запроса.
2. Кеширование готового ответа для максимального ускорения повторных запросов.

Отдельная materialized view для всего compare-домена не вводится: её операционная сложность не оправдана текущим scope.

## 5. Frontend

### 5.1 Структура страницы

```text
ComparePage
├─ ComparePageHero
├─ CompareFiltersPanel
└─ CompareUnifiedTable / CompareEmptyState / CompareErrorState
```

`ComparePageHero` строится на общем `PageHero` и содержит:

- breadcrumb «Игроки → Сравнение»;
- локализованный заголовок с `<em>`-акцентом;
- короткое описание;
- существующий guide popover как действие;
- status-блоки scope, baseline, sample size и metrics count.

Фильтры остаются самостоятельной рабочей поверхностью под Hero. Старый `ComparePageHeader` и дублирующий `h1` удаляются.

### 5.2 Состояния и загрузка

- До выбора игрока Hero и empty state показывают осмысленные `—` и инструкцию.
- Первичная загрузка использует скелетон геометрии таблицы.
- При смене фильтров предыдущий результат остаётся видимым, получает `aria-busy` и приглушённое состояние.
- Superseded-запросы отменяются через `AbortSignal`.
- Ошибка выводится в области результата с retry action.
- Empty state различает отсутствие выбранного игрока и отсутствие статистики.
- Heroes/maps catalogs включаются только в Hero/Map scope.
- Tournament catalog остаётся доступным в обоих режимах.
- На mobile hero status-блоки складываются в 2×2, таблица сохраняет горизонтальный scroll.
- Новые строки добавляются одновременно в `ru.json` и `en.json`.

## 6. Overall comparison SQL

Новая реализация начинает с `candidate_users` CTE:

- target-user: только subject и target;
- cohort: пользователи, прошедшие role/division/tournament scope;
- global: текущая глобальная популяция без изменения семантики.

Отдельные агрегирующие CTE группируют данные по `user_id`:

- tournaments и achievements;
- maps won/total/winrate;
- average placement, playoff placement и group placement;
- average closeness;
- per-10 eliminations, final blows, damage, healing;
- MVP score.

CTE соединяются с кандидатами через `LEFT JOIN`. Финальная агрегация возвращает subject value, baseline average, sample size, rank и percentile без передачи всей популяции в Python.

Семантика остаётся прежней:

- `None` не участвует в среднем и rank;
- ноль участвует;
- ties получают одинаковый rank;
- percentile использует текущую формулу `(total - rank) / (total - 1) * 100`;
- ascending/direction правила не меняются.

Старая реализация временно остаётся тестовым oracle.

## 7. Hero/Map comparison SQL

Одна агрегирующая выборка вычисляет playtime и запрошенные stats по каждому кандидату. Условия hero, map, tournament, role и division применяются единообразно. Порог 600 секунд применяется до построения baseline.

Target mode ограничивает вычисление двумя пользователями. Cohort/global агрегируют только candidate set. Subject hero, target hero и map читаются пакетно вместо трёх последовательных каталог-запросов.

## 8. Кеш

Используются существующие Redis backend и cashews:

- `backend:user_compare:v2:*`;
- `backend:user_hero_compare:v2:*`;
- TTL 60 секунд;
- cache key содержит endpoint, subject, baseline, target, нормализованные фильтры, отсортированный список stats и версию division grid;
- идентичные cold requests объединяются single-flight lock;
- кешируются только успешные ответы;
- Redis failure приводит к SQL fallback;
- namespace version позволяет менять схему ключа без миграции Redis.

Инвалидация добавляется в:

- `TournamentChangedEvent` consumer;
- user merge;
- изменение division grid.

## 9. Ошибки и edge cases

- `div_min > div_max` продолжает возвращать validation error.
- Target mode без target user не выполняет SQL compare.
- Subject без статистики сохраняет текущий 404-контракт.
- Пустая cohort и Hero/Map выборка сохраняют текущие 404-контракты.
- Нулевой baseline не создаёт `delta_percent`.
- Hero stats с playtime менее 600 секунд не входят в baseline.
- Cache не хранит validation, 404 или 500 ответы.
- Redis timeout не меняет HTTP/RPC-ответ.
- Устаревший frontend response не может заменить результат более нового набора фильтров.

## 10. Проверка производительности и корректности

До изменения фиксируются wall time, SQL query count и число возвращённых строк для global, cohort, target-user и Hero/Map.

Проверки:

- parity старой и новой реализаций на одинаковых fixtures;
- `None`, zero, ties, ascending stats;
- division/tournament filters;
- Hero playtime threshold;
- SQL query-count regression tests;
- cache hit/miss, normalized key, single-flight и Redis fallback;
- invalidation pattern tests;
- существующие RPC contract tests;
- frontend loading/error/empty/scope tests;
- frontend Vitest и lint;
- backend targeted pytest.

Индекс добавляется отдельной миграцией только при доказанном sequential scan на критическом участке.

## 11. Rollout и rollback

Новые query helpers и cache namespace получают суффикс `v2`. Старая реализация удаляется только после parity-проверки. Кеш можно отключить независимо от SQL-оптимизации. Миграция индекса, если понадобится, остаётся отдельной и обратимой.

## 12. Риски

- Ошибка в set-based переписывании может изменить одну из исторических формул.
- Большая global population всё ещё требует cold aggregation, хотя без коррелированного fan-out.
- TTL создаёт ограниченную 60-секундную устарелость.
- Неполная инвалидация может продлить устарелость до TTL.

Меры: old-vs-new oracle, query-count tests, versioned cache namespace, короткий TTL и явные invalidation patterns.

## 13. Decision Log

| Решение | Альтернативы | Причина |
|---|---|---|
| Общий `PageHero` | Локальный новый Hero; оставить старый header | Соответствует дизайн-системе остальных вкладок |
| Фильтры вне Hero | Перенести форму в Hero | Сохраняет стабильную рабочую область и адаптивность |
| Set-based CTE | Оставить correlated subqueries | Убирает fan-out на каждого пользователя |
| SQL averages/rank | Загружать всю population в Python | Снижает объём данных и CPU приложения |
| Redis response cache | Только SQL; materialized view | Максимальный warm gain при существующей инфраструктуре |
| TTL 60 секунд | Длинный TTL; бессрочный кеш | Совпадает с user cache и ограничивает stale window |
| Явная инвалидация | Только TTL | Быстрее отражает изменения матчей и division grid |
| Lazy heroes/maps catalogs | Загружать при каждом открытии | Сокращает сетевую и backend-нагрузку Overall режима |
| Сохранить API contract | Новый endpoint/response | Минимизирует blast radius |
| Индекс только после `EXPLAIN` | Добавить заранее | Избегает необоснованной write/storage стоимости |
| Старый расчёт как oracle | Немедленно удалить | Позволяет доказать parity |

## 14. Критерии готовности

- Страница визуально использует тот же `PageHero` и токены, что соседние вкладки.
- Loading, empty, error и mobile состояния завершены.
- Все прежние API-поля и формулы сохранены.
- Parity-набор полностью проходит.
- DB round trips не растут с числом пользователей.
- Cold request быстрее baseline; warm request приходит из Redis.
- Targeted backend tests, frontend tests и lint проходят.
