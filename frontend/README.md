# Frontend

The OWT frontend is a [Next.js](https://nextjs.org/) application that presents tournament history,
player statistics, registration, and admin tooling on top of the OWT backend API. See
[../docs/architecture.md](../docs/architecture.md) for the overall system architecture.

## Tech stack

- [Next.js 16](https://nextjs.org/) (App Router) + [React 19](https://react.dev/) + TypeScript
- [Tailwind CSS 4](https://tailwindcss.com/) with [Shadcn/UI](https://ui.shadcn.com/) and Radix primitives
- [TanStack Query](https://tanstack.com/query) and [TanStack Table](https://tanstack.com/table) for data
- [Zustand](https://github.com/pmndrs/zustand) for client state
- [Recharts](https://recharts.org/) and [XYFlow](https://reactflow.dev/) for visualizations
- [Vitest](https://vitest.dev) (happy-dom) for unit / smoke tests, [Sentry](https://sentry.io/) for monitoring

## Getting started

Install dependencies and start the development server:

```bash
bun install
bun run dev
```

The repository uses [Bun](https://bun.sh/) (`bun.lock`); `npm install` / `npm run dev` also work.

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Route zones

`src/app` is cut into three zones — `web` (`(site)`), `admin`, and `tools`
(`balancer` + `draft`) — with three import rules: a zone never imports another zone, nothing
outside `src/app` imports from `src/app`, and `src/components/admin` is admin-private.
`bun run lint:zones` enforces them and runs in CI. The contract, and what would still have to
be solved to turn the zones into separate deployables, is in
[`../docs/frontend-zones.md`](../docs/frontend-zones.md).

## Internationalization

The app is localized with [next-intl](https://next-intl.dev/) (English and Russian). Translation
messages and the terminology glossary live under `frontend/src/i18n` (see
`frontend/src/i18n/GLOSSARY.md` for the shared glossary; runtime config is in
`frontend/src/i18n/request.ts`).

Messages are shipped to the client **per zone**, not whole: `NextIntlClientProvider` serialises
everything it is given into the RSC payload, so an anonymous visitor used to download the admin
console's strings too. `src/i18n/zone-namespaces.json` is the generated zone → namespace map —
regenerate it with `bun run lint:zones --write-i18n`; rule Z4 of the same gate fails CI if it
drifts from the import graph.

## Backend integration

One API: one origin, one process (the Go gateway), one dispatcher
(`edge.RouteSpec` → RabbitMQ RPC queue), one error envelope, one OpenAPI generator, and one
URL shape. The HTTP parser/analytics/balancer services are decommissioned — nothing behind the
gateway speaks HTTP.

**Every gateway path is `/api/v{n}/<domain>/...`.** One version axis, always the second
segment; no namespace sits beside it.

| Domain | Covers |
| --- | --- |
| `/api/v1/{tournaments,users,workspaces,admin,me,…}` | app + tournament + parser reads/writes |
| `/api/v1/auth/*` | identity, RBAC, sessions, API keys |
| `/api/v1/balancer/*` | team balancing and draft |
| `/api/v1/analytics/*` | post-tournament analytics |
| `/api/v1/streams/*` | tournament live streams |
| `/api/v1/notifications*`, `/api/v1/announcements/*` | the per-user inbox and feed |
| `/api/v1/realtime/ws` | realtime WebSocket stream |

`/api/v2/*` is the same paths, handlers and statuses with the RPC envelope as the body;
`internal/apiver` rewrites it onto v1 before routing and `internal/apierr` picks the shape. It
is a response version, not a second route table — which is why it now covers the whole surface
instead of everything-except-auth.

Three things live outside the version, on purpose:

- `/api/docs`, `/api/openapi*.json` — the generated reference. It *describes* the versions, so
  it cannot sit inside one.
- `/api/health` — the frontend container's probe (`docker-compose` healthcheck, TLS runbooks).
- `/bff/*` — **this app's own** endpoints: cookie-authenticated Next route handlers that hold
  the access token server-side so the browser never sees it (`/bff/account/api-keys`,
  `/bff/account/sessions`). Served by Next, never by the gateway. It used to be `/api/account`,
  which made a second resource API hide inside the gateway's namespace.

### Migrating off the old prefixes

`auth`, `analytics`, `balancer`, `streams`, `notifications` and `announcements` used to sit
beside the version (`/api/auth/me`). Those spellings still answer — `apiver.LegacyPrefixes`
rewrites them onto the canonical path — and every such response carries `Deprecation: true`, a
`Sunset` date (`apiver.SunsetDate`) and `Link: <canonical>; rel="successor-version"`. Move the
prefix; nothing else changes. Nothing in this app uses them any more, and
`frontend/src/lib/api/fetch.ts` keys its per-domain behaviour off the domain segment, so a
legacy path would silently lose workspace injection here even while the gateway still served it.

The browser uses **relative same-origin paths**; SSR and the proxy use `NEXT_INTERNAL_API_URL`
(the gateway, e.g. `http://gateway:8080`). The URL contract is documented once in
`frontend/src/lib/api/routes.ts`. Multidomain / white-label tenancy is resolved in
`frontend/src/proxy.ts`, which maps the request `Host` to a workspace.

## Community viewing scope

The platform defaults to **All communities**. `owt-stats-scope` remembers the viewing
filter (`all` or `workspace`); `owt-workspace-id` remembers the selected community.
Switching refreshes the current route without adding a workspace to its URL. Tabs,
search and compatible filters stay selected; affected lists restart from page one.

The viewing filter is separate from the opened entity's `entityWorkspaceId`.
Community, tournament, encounter, match, scrim and mix reads resolve their actual owner without
overwriting the saved viewing preference. Permissions and writes use that owner.
The switcher names the page's community separately; opening a community is an
explicit link, not a filter-selection side effect.

Global mixes combine public community lists and keep leaderboards separate by
community. Global scrims list the signed-in viewer's memberships, with staff
visibility checked per community. Creation in global mode requires selecting an
authorized community. Tenant/custom domains stay locked to their community and
offer a separate link to the platform.

Mix detail reads use `GET /api/v1/balancer/custom-games/{custom_game_id}`. Its optional
`workspace_id` restricts a tenant-host read; a different viewing filter must not
replace the opened mix. Deploy the frontend, gateway and balancer service together
for this route cutover.

## Pre-game room refresh

Map and hero state share one 250–749 ms realtime batch. Ordinary pick/ban changes refresh the
two authoritative states without rereading full encounter/parsed-match details. Game, series,
session-control and local upload changes refresh those details; tournament encounter invalidations
also refresh the room when their `encounter_ids` include it, preserving remote parsed-log history.
Reconnect acknowledgements trigger a full catch-up.

Incomplete active sessions retain lazy-timeout polling at independently jittered 4000–6499 ms
intervals. Paused sessions do not poll while realtime is connected and both room subscriptions
have no errors; disconnected/error states use a 30000–32499 ms fallback to recover missed resumes.
Polling-driven progression also refreshes the other phase. WebSocket reconnect uses exponential
backoff with equal jitter, capped at 30 seconds; per-IP protective limits are unchanged.

BO2 accepts a final 1:1 draw as well as 2:0 or 0:2. Even-length series show their best-of
format on the scoreboard rather than a first-to-win target; odd-length series retain that
target. Without a series summary, reaching the map limit also closes the pre-game loop.

Captains can submit or update the series report after an organizer confirms the result,
from the bracket, encounter page, or pre-game room. The form explains that late reports
are saved without changing the official score; confirmation no longer hides the form.

## Pre-game hero history and match log folders

The **One ban per opponent player** board shows each opponent's logged heroes inside their
roster row, below the name and role. Heroes come only from the immediately previous series
position in this encounter, deduplicated across that map's rounds. Captain-report placeholders
and other players' heroes are excluded. The first map, a missing previous log, or legacy rows
without enough position information show no history rather than falling back to older maps
or account-wide statistics. Long hero lists scroll within the row.
The board reuses the match-detail cache; room refreshes invalidate parsed match details.
Displaying history does not change ban eligibility.

**Upload match logs** uses the File System Access API (`showDirectoryPicker`, read-only).
The first click selects a folder; its native `FileSystemDirectoryHandle` is structured-cloned
into IndexedDB, keyed by the signed-in account and isolated by browser origin. Later clicks
reuse it and request read permission if needed. This requires Chrome or Edge on HTTPS or
localhost; unsupported browsers show an explanation rather than a different import method.

Profile settings show the folder name and offer change, view/refresh and forget actions.
Browsers do not expose its absolute path. Forgetting removes only the saved handle, not files.
Folder scans include immediate `.log`, `.txt` and `.csv` files, not subdirectories. The upload
list is ordered by the local filesystem's `File.lastModified`, newest first; equal timestamps
use filename order. Only the newest file starts selected. Selection remains editable and
nothing uploads automatically. Partial failures keep failed files selected without resending
successful files. Uploading still requires the existing `log.create` permission.

The parser resolves map aliases to a catalog map, then validates the effective encounter map
pool before roster, match or statistics writes. Scope precedence is stage + round, stage, then
tournament; an empty rules template does not replace a parent's pool. Slot candidates and
reserve maps are accepted. Maps outside the pool fail with `map_not_in_pool`, preserving
existing data. Without a configured pool, any catalog-resolved map remains allowed.
This checks the configured pool, not the current veto's chosen map or next series position.

## Notifications

The header carries the inbox bell (`src/components/notifications/NotificationBell.tsx`, hidden
without an identity): it reads `GET /api/v1/notifications` and refetches when the
`user:{id}:notifications` realtime topic signals, so the badge is the server's unread count and
never a client-side tally. A load failure renders its own retry state inside the panel (never the
empty-inbox copy), and a row can be marked read on its own — following a row's link never marks it
read, because a read mark is also how an announcement is dismissed. A system row carries
`kind` plus a payload snapshot and no text — the wording comes from `notifications.kinds.*` in
`src/i18n/messages/*.json`, so a copy fix reaches rows written months ago; row destinations come
from `src/lib/notifications/href.ts`, never from payload URLs. The two kinds one click resolves —
`check_in.opened` and `team_invite.received` (`ACTIONABLE_RANK` in `notification-kinds.ts`) —
carry their action buttons on the row.

A row can also be deleted from the inbox (`POST /api/v1/notifications/delete`), one at a time or as
"clear read" for everything already marked. That deletion is per viewer — the server writes
`notification_read.deleted_at` and keeps the row — so throwing away a platform-wide announcement
never takes it out of anybody else's inbox. Deleting counts as reading, so the badge drops with it.

Under the header, on every page and for anonymous visitors too, the floating stack
(`src/components/notifications/FloatStack.tsx`) shows the newest active announcement from
`GET /api/v1/announcements/active` (read server-side in the layouts, so it is in the first paint)
and, for a signed-in viewer, the one pending action — an open check-in before a team invite, scoped
to the community on a community page or host. Below 640px they are cards at the bottom of the
screen, above that slim bars sticky under the header. Closing the announcement writes a read mark
for a signed-in viewer and a dismissed id for everyone else; hiding the action card lasts for the
visit, the item stays in the bell. Operators publish announcements at `/admin/announcements`.

`/admin/notifications` is the other side of the same table: the system notifications *this*
workspace produced (`notification.source_workspace_id`), filtered by kind through the URL, with a
retire for one row or for a whole kind. Retiring expires the rows rather than deleting them —
they leave every recipient's inbox while the records and their read marks stay — and it needs
`notification.delete` in the workspace, a separate grant from the `notification.read` that opens
the screen.

## Branding via .env

The site name and main icon/logo are configurable via environment variables.

- Copy `frontend/.env.example` to `frontend/.env` (or `frontend/.env.local`)
- Set `NEXT_PUBLIC_SITE_NAME` (e.g. "Overwatch Tournaments") — the deployment's name in page
  metadata and the sign-in dialog. The header and footer wordmark is the fixed `BRAND_NAME` ("OWT")
  in `src/config/site.ts`.
- Set `NEXT_PUBLIC_SITE_ICON` (e.g. "/logo.webp")
- (Optional) Set `NEXT_PUBLIC_SITE_FAVICON` (e.g. "/favicon.ico")
- For a host-run dev server, set `NEXT_INTERNAL_API_URL` to the gateway
  (e.g. `http://localhost:8080`); the browser uses relative same-origin paths
- Restart `bun run dev`

> **Note:** When self-hosting a **modified** version of OWT, the license requires a visible link back to
> the original project and author on the running site (see the repository [LICENSE](../LICENSE), AGPL §7
> Additional Terms). Rebranding via the variables above does not remove that requirement.

## Favicon replacement (Docker)

The app serves the browser favicon from `frontend/public/favicon.ico`. In production you can replace it by
bind-mounting your own file into the container:

`./conf/favicon.ico:/app/public/favicon.ico:ro`

## Docker workflow

- Dev behavior is defined in the root `docker-compose.yml`.
- Start the core frontend/backend stack with:

```bash
docker compose up -d --wait
```

- Enable background workers when needed:

```bash
docker compose --profile workers up -d --wait
```

Production image builds use explicit Docker build args/env values; no `.env` is copied into image layers.

## UI/UX

Design principles and UI patterns used across the app are documented in `frontend/DESIGN.md`.
