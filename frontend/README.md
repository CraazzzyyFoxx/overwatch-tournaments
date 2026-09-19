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
`frontend/src/lib/api-fetch.ts` keys its per-domain behaviour off the domain segment, so a
legacy path would silently lose workspace injection here even while the gateway still served it.

The browser uses **relative same-origin paths**; SSR and middleware use `NEXT_INTERNAL_API_URL`
(the gateway, e.g. `http://gateway:8080`). The URL contract is documented once in
`frontend/src/lib/api-routes.ts`. Multidomain / white-label tenancy is resolved in
`frontend/src/middleware.ts`, which maps the request `Host` to a workspace.

## Notifications

The header carries the inbox bell (`src/components/notifications/NotificationBell.tsx`, hidden
without an identity): it reads `GET /api/v1/notifications` and refetches when the
`user:{id}:notifications` realtime topic signals, so the badge is the server's unread count and
never a client-side tally. A load failure renders its own retry state inside the panel (never the
empty-inbox copy), and a row can be marked read on its own — following a row's link never marks it
read, because a read mark is also how the announcement banner is dismissed. A system row carries
`kind` plus a payload snapshot and no text — the wording comes from `notifications.kinds.*` in
`src/i18n/messages/*.json`, so a copy fix reaches rows written months ago; row destinations come
from `src/lib/notification-href.ts`, never from payload URLs.

A row can also be deleted from the inbox (`POST /api/v1/notifications/delete`), one at a time or as
"clear read" for everything already marked. That deletion is per viewer — the server writes
`notification_read.deleted_at` and keeps the row — so throwing away a platform-wide announcement
never takes it out of anybody else's inbox. Deleting counts as reading, so the badge drops with it.

Under the header, centred in the content column, on every page and for anonymous visitors too,
`AnnouncementBanner.tsx` shows the newest active announcement from `GET /api/v1/announcements/active`
(read server-side in both
layouts, so it is in the first paint). Closing it writes a read mark for a signed-in viewer and a
`localStorage` id for everyone else. Operators publish them at `/admin/announcements`.

`/admin/notifications` is the other side of the same table: the system notifications *this*
workspace produced (`notification.source_workspace_id`), filtered by kind through the URL, with a
retire for one row or for a whole kind. Retiring expires the rows rather than deleting them —
they leave every recipient's inbox while the records and their read marks stay — and it needs
`notification.delete` in the workspace, a separate grant from the `notification.read` that opens
the screen.

## Branding via .env

The site name and main icon/logo are configurable via environment variables.

- Copy `frontend/.env.example` to `frontend/.env` (or `frontend/.env.local`)
- Set `NEXT_PUBLIC_SITE_NAME` (e.g. "Overwatch Tournaments")
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
