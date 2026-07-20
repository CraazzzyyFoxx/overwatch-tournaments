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

## Internationalization

The app is localized with [next-intl](https://next-intl.dev/) (English and Russian). Translation
messages and the terminology glossary live under `frontend/src/i18n` (see
`frontend/src/i18n/GLOSSARY.md` for the shared glossary; runtime config is in
`frontend/src/i18n/request.ts`).

## Backend integration

The app talks to a **single gateway origin** via path-namespaced routes:

- `/api/v1` — app, tournament, and parser reads/writes
- `/api/balancer` — team balancing and draft
- `/api/analytics` — post-tournament analytics
- `/api/auth` — identity (auth, RBAC, workspace membership)
- `/api/realtime/ws` — realtime WebSocket stream

The browser uses **relative same-origin paths**; SSR and middleware use `NEXT_INTERNAL_API_URL`
(the gateway, e.g. `http://gateway:8080`). Route definitions are the source of truth in
`frontend/src/lib/api-routes.ts`. Multidomain / white-label tenancy is resolved in
`frontend/src/middleware.ts`, which maps the request `Host` to a workspace.

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
