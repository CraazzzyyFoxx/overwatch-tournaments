# Workspace-scoping главной страницы (+ /statistics) на tenant-хостах

**Дата:** 2026-07-11
**Статус:** Одобрено (brainstorming), готово к плану реализации
**Связано:** [[project_workspace_multidomain]], [[project_workspace_branding]]

## Проблема

На tenant-хосте (сабдомен `team.owt.craazzzyyfoxx.me` **или** кастомный домен
`tourney.customer.com`) весь сайт залочен на один workspace (white-label hard
lock — см. multidomain-спеку). Но **главная страница** (`(site)/(home)/page.tsx`)
и страница **`/statistics`** (`(site)/statistics/page.tsx`) показывают
**платформенные (глобальные) данные** — по всем workspace сразу, а не по тому,
которому принадлежит домен.

Причина: каждый data-fetch на этих двух страницах жёстко передаёт
`skipWorkspace: true`, что отключает автоматическое workspace-скоупинг.

## Почему так сделано и почему это правильно НЕ везде

`skipWorkspace: true` корректен для **апекс/платформенного хоста**
(`owt.craazzzyyfoxx.me`), где главная = обзор всей платформы (агрегат по всем
сообществам). На tenant-хосте это поведение ошибочно — нужен срез по одному
workspace.

## Ключевое наблюдение: механизм уже есть

Скоупинг по workspace **уже реализован и работает** для остального сайта:

- `frontend/src/middleware.ts` резолвит host → workspace и ставит заголовки
  `x-owt-workspace-id` + `x-owt-host-mode: tenant` (одинаково для сабдоменов и
  кастомных доменов; на апексе оба заголовка срезаются).
- `frontend/src/lib/api-fetch.ts` для путей `/api/v1/*` **авто-инжектит**
  `workspace_id` из `x-owt-workspace-id` (SSR) — но только если `skipWorkspace`
  не выставлен.
- Бэкенд фильтрует по `workspace_id` на **всех** задействованных эндпоинтах:
  - `rpc.tournament.list_tournaments` (`tournament-service/src/rpc/reads.py:201`)
  - `rpc.tournament.statistics_overall|_history|_division` (reads.py:71-102)
  - `rpc.app.statistics.champion|winrate|won_maps`
    (`app-service/src/rpc/statistics.py`, докстринг: «all public,
    workspace-filtered»)

Единственное, что мешает, — намеренный opt-out `skipWorkspace: true`.

## Решение

Одно правило: **`skipWorkspace = !isTenantHost()`**. На апексе поведение не
меняется; на tenant-хосте включается уже существующая авто-инжекция
`workspace_id`, и страница скоупится на нужный workspace.

Изменения затрагивают **только фронтенд** (бэкенд трогать не нужно).

### 1. Новый хелпер `frontend/src/lib/tenant-host.ts`

```ts
import { headers } from "next/headers";

/**
 * True, когда запрос обслуживается на white-label tenant-хосте
 * (сабдомен или кастомный домен), согласно заголовку x-owt-host-mode,
 * который выставляет middleware. Fail-safe: false при любой ошибке.
 */
export async function isTenantHost(): Promise<boolean> {
  try {
    return (await headers()).get("x-owt-host-mode") === "tenant";
  } catch {
    return false;
  }
}
```

Дедуплицирует строковый литерал, сейчас инлайненный в `(home)/page.tsx:42` и
`layout.tsx:38`. Каждая dashboard-карточка вычисляет
`const skipWorkspace = !(await isTenantHost())` локально — без prop-drilling,
каждый Suspense-блок остаётся самодостаточным.

### 2. `frontend/src/services/tournament.service.ts`

`getActive()` → `getActive(opts?: { skipWorkspace?: boolean })` с дефолтом
`skipWorkspace: true` (`opts?.skipWorkspace ?? true`).

Дефолт `true` сохраняет **байт-в-байт** поведение двух других вызывающих:
`(site)/workspace/[slug]/page.tsx:244` и клиентский
`components/ActiveEvents.tsx:36`. Явное значение передаёт только главная.

### 3. `frontend/src/app/(site)/(home)/page.tsx`

Заменить `skipWorkspace: true` на вычисленное значение в 6 источниках данных:

| Компонент | Вызов |
|---|---|
| `LiveEventsSection` | `tournamentService.getActive({ skipWorkspace })` |
| `StatsGrid` | `getOverallStatistics({ skipWorkspace })` |
| `TournamentActivityCard` | `getTournaments({ skipWorkspace })` |
| `DivisionRingsCard` | `getTournamentsDivision({ skipWorkspace })` |
| `ChampionsCard` | `getChampions({ skipWorkspace })` |
| `TopWinRateCard` | `getTopWinratePlayers({ skipWorkspace })` |

Верхний `tenantMode` (уже используется для тумблера communities + PageIntro)
переиспользует `isTenantHost()` ради единообразия.

**Плюс полировка:** скрыть per-event **workspace-name badge** в `EventCard`,
когда `isTenantHost()` — на white-label сайте он избыточен (все карточки = один
и тот же workspace). Проброс флага в `EventCard` (у него уже есть проп
`workspace`).

### 4. `frontend/src/app/(site)/statistics/page.tsx`

Тот же свап в 6 источниках: `OverallStats`, `ActivityTrendCard`,
`DivisionTrendCard`, `ChampionsLeaderboard`, `WinRateLeaderboard`,
`WonMapsLeaderboard`.

## Что намеренно НЕ меняется

- **Апекс/платформенный хост** → `isTenantHost()` = false → `skipWorkspace: true`
  → глобальный агрегат, как сейчас.
- **Communities section** на главной — уже скрыта в tenant-режиме; не трогаем.
- **`workspace/[slug]` и `ActiveEvents`** — сохранены через дефолт опции.
  (Замечание: `workspace/[slug]` тоже показывает глобальные active-турниры —
  это преэкзистинг, вне скоупа этой задачи.)
- Бэкенд — без изменений.

## Edge cases

- Пустой/новый tenant-workspace → легитимно нулевые статы; существующие
  empty/error-фолбэки (`NoEventsState`, `loadError`, `noData`) это уже
  обрабатывают.
- `x-owt-host-mode` и `x-owt-workspace-id` middleware ставит вместе → они всегда
  консистентны. Если id вдруг отсутствует, `apiFetch` деградирует к глобальному
  срезу, а не падает.
- `LiveEventsSection` продолжает звать `workspaceService.getAll()` для
  name-lookup бейджей — на tenant-хосте это безвредно (map найдёт нужный
  workspace); менять не нужно.

## Верификация

- `bunx tsc --noEmit` + `rtk lint` (TS-фаза `next build` маскирует ошибки на
  первом файле — см. lesson_nextintl_returntype_constraint; проверять через
  `tsc --noEmit`).
- Тонкий unit-тест для `isTenantHost()` — только если мок `next/headers` в
  `bun test` выходит чистым; иначе полагаемся на tsc/eslint + ручной E2E.
- Ручной E2E: открыть главную + `/statistics` на кастом-домене; убедиться, что
  счётчики/лидерборды соответствуют этому workspace и отличаются от апекс-вида.

## Вне скоупа

- Скоупинг `workspace/[slug]` active-турниров (преэкзистинг-баг).
- Прочие `(site)`-страницы (tournaments/teams/users/matches и т.д.) — они уже
  скоупятся авто-инжекцией, т.к. не передают `skipWorkspace`.
