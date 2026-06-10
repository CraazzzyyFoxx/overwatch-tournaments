# Frontend

The OWT frontend is a [Next.js](https://nextjs.org/) application that presents tournament history,
player statistics, registration, and admin tooling on top of the OWT backend API.

## Tech stack

- [Next.js 16](https://nextjs.org/) (App Router) + [React 19](https://react.dev/) + TypeScript
- [Tailwind CSS 4](https://tailwindcss.com/) with [Shadcn/UI](https://ui.shadcn.com/) and Radix primitives
- [TanStack Query](https://tanstack.com/query) and [TanStack Table](https://tanstack.com/table) for data
- [Zustand](https://github.com/pmndrs/zustand) for client state
- [Recharts](https://recharts.org/) and [XYFlow](https://reactflow.dev/) for visualizations
- [Playwright](https://playwright.dev) for End-to-End tests, [Sentry](https://sentry.io/) for monitoring

## Getting started

Install dependencies and start the development server:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Branding via .env

The site name and main icon/logo are configurable via environment variables.

- Copy `frontend/.env.example` to `frontend/.env` (or `frontend/.env.local`)
- Set `NEXT_PUBLIC_SITE_NAME` (e.g. "Moonrise Tournaments")
- Set `NEXT_PUBLIC_SITE_ICON` (e.g. "/logo.webp")
- (Optional) Set `NEXT_PUBLIC_SITE_FAVICON` (e.g. "/favicon.ico")
- Point `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_AUTH_SERVICE_URL` at the backend
- Restart `npm run dev`

> **Note:** When self-hosting a **modified** version of OWT, the license requires a visible link back to
> the original project and author on the running site (see the repository [LICENSE](../LICENSE), AGPL §7
> Additional Terms). Rebranding via the variables above does not remove that requirement.

## Favicon replacement (Docker)

The app serves the browser favicon from `frontend/public/favicon.ico`. In production you can replace it by
bind-mounting your own file into the container:

`./conf/favicon.ico:/app/public/favicon.ico:ro`

## Docker workflow (breaking change)

- `docker-compose.override.yml` is removed; dev behavior is defined in the root `docker-compose.yml`.
- Start the core frontend/backend stack with:

```bash
docker compose up -d --wait
```

- Enable the Kong gateway and workers when needed:

```bash
docker compose --profile gateway --profile workers up -d --wait
```

Production image builds use explicit Docker build args/env values and no longer copy `.env` into image layers.

## UI/UX

Design principles and UI patterns used across the app are documented in `frontend/DESIGN.md`.
