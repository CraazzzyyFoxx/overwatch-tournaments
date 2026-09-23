# Frontend zones

The frontend is **one** Next deployable (`frontend/`, `output: standalone`, one container
behind nginx). It is not a micro-frontend architecture and does not need to be: Next already
route-splits the client bundle, a cold `next build` is ~75 s and a cold `tsc --noEmit` ~45 s.
What it *is* is a large tree — ~1.4k files, ~270k lines — cut into route zones whose seams are
checked, so that separating them later is a move of directories rather than an archaeology
project.

`bun run lint:zones` (`frontend/scripts/check-zone-boundaries.mjs`) is the gate. It runs in CI
next to the linter and fails the build on any violation.

## The zones

| Zone | Owns | Size |
| --- | --- | --- |
| `web` | `src/app/(site)/**` — home, tournaments, users/stats, docs, legal, invite, scrims | 315 files / 65k lines |
| `admin` | `src/app/admin/**` **and** `src/components/admin/**` | 359 files / 80k lines |
| `tools` | `src/app/balancer/**`, `src/app/draft/**` | 81 files / 21k lines |
| *shared* | everything below | 657 files / 104k lines |

`src/app/api/**` (route handlers) and `src/app/actions/**` (server actions) are Next's
server-entry conventions, not zones: any zone may call them.

Everything else is **shared**, importable by every zone, and forbidden from importing any zone:

```
src/lib  src/hooks  src/stores  src/services  src/types  src/utils  src/i18n  src/config
src/components/ui           shadcn primitives
src/components/kit          cross-zone application kit (SaveBar, StatusPill, Inspector,
                            FilterBar, Combobox, ConfirmDialog, WizardShell, tone, …)
src/components/data-table   the sortable/filterable/selectable table
src/components/*            every other feature component library (balancer, draft,
                            registration, bracket, roster-shape, tournaments, match, …)
```

## The three rules

**Z1 — a route zone must not import another route zone.**
`app/(site)/…` may not import `app/admin/…`, and vice versa. Cross-zone navigation is a full
page load in any future split, so anything two zones both need is shared code, not a reach
across the fence. `app/balancer` and `app/draft` are one zone (`tools`) and may import each
other.

**Z2 — nothing outside `src/app` may import from `src/app`.**
A `lib/` module that imports a route inverts the dependency: the shared layer then cannot be
built, tested, or moved without the route tree. This is the rule that was broken when
`lib/realtime/resources.ts` imported the admin tournament workspace's query keys.

**Z3 — `src/components/admin` is admin-private.**
Only `app/admin/**` (and `components/admin/**` itself) may import it. `components/admin` is
allowed to import `app/admin` — it is that zone's own component library and the exception is
declared in the gate.

## How to satisfy them

Two zones need the same thing. In order of preference:

1. **It is pure logic** (a model, a projection, a formatter, a query-key factory) → `src/lib/`.
2. **It is a hook** → `src/hooks/`.
3. **It is a presentational primitive with no domain knowledge** → `src/components/kit/`.
4. **It is a feature component** → `src/components/<feature>/`, imported by both zones.
5. **It is genuinely one zone's screen** and the other zone wants to embed it → the screen
   moves to `src/components/<feature>/` and both routes render it. `app/admin/…/registration/*`
   renders `components/balancer/*` this way.

Never: a relative `../../admin/…` climb, and never a re-export shim to launder the direction.

## Historical names

`components/kit/` still contains `Admin`-prefixed exports (`AdminFilterBar`, `AdminInspector`,
`AdminTabs`, `AdminCombobox`, `useAdminFilters`), and `components/data-table/` exports
`AdminDataTable` / `adminColumnMeta`. They were the admin surface's kit before three other
zones started using them. The prefix is historical, not a scope claim; the directory is the
scope. Renaming the symbols is a mechanical pass nobody has needed badly enough to pay the
review cost for.

## What a split would still have to solve

If a real trigger ever appears (build > 8 min, a second team blocked on deploys, admin on a
separate host, divergent framework versions), the cheapest shape is Next multi-zone —
`basePath` + `assetPrefix` per zone, nginx routing the prefixes, no Module Federation. Four
things in this codebase are single-instance today and would need an owner first:

1. **QueryClient** — a module singleton in `app/providers.tsx`. Separate zones mean separate
   caches; realtime invalidation (`lib/realtime/resources.ts`) stops crossing zones.
2. **The realtime WebSocket** — one `/ws` per tab today. Per-zone sockets multiply against the
   gateway's origin check and nginx's rate-limit zones.
3. **Proactive token refresh** — `hooks/use-proactive-token-refresh.ts` rotates the refresh
   token. Two zones rotating concurrently race and log the user out. Needs a single writer
   (Web Locks / `BroadcastChannel`).
4. **Host → workspace resolution** — `src/middleware.ts` resolves the request host to a
   workspace and injects `x-owt-workspace-id`, with its own 60 s TTL cache. N zones would run
   N copies of that lookup and N caches. Moving it to the gateway is the obvious answer *then*
   and deliberately not now: the rule it implements (platform subdomain, or a custom domain
   whose DNS TXT verification has completed) lives in Python
   (`backend/app-service/src/rpc/workspaces.py` `by_host`, `backend/shared/tenancy/hostnames.py`),
   and a second Go implementation on the hot path of every page view would silently render
   tenants as the platform site the day the two drift. What *did* move to the edge is header
   hygiene: `gateway/internal/proxy` strips the whole `x-owt-*` prefix from inbound requests,
   so the trust boundary — not the app being scoped — is what refuses a spoofed
   `x-owt-workspace-id`. The middleware still deletes before setting; two independent barriers.

## Message payload

`NextIntlClientProvider` serialises its `messages` into the RSC payload, and given no
`messages` prop it serialises the **entire** tree. Every anonymous visitor was therefore
downloading the admin draft console's strings, the quota editor's, and the registration form
builder's. Two namespaces (`mapVeto`, `mapVetoAdmin`, 9 kB of `ru`) turned out to be read by
nothing at all and are gone; each zone ships its own slice of the rest:

| Zone | Namespaces | Compact `en` | Compact `ru` |
| --- | --- | --- | --- |
| full tree | 49 | 201 kB | 213 kB |
| `root` | 21 | 89 kB | 94 kB (−56%) |
| `web` | 40 | 158 kB | 167 kB (−22%) |
| `admin` | 40 | 178 kB | 188 kB (−12%) |
| `tools` | 32 | 130 kB | 138 kB (−35%) |

**The bundle is mounted by the layout that owns the zone**, not chosen from the request path.
`src/i18n/ZoneIntlProvider.tsx` takes a zone and hands that slice to the client; `app/layout.tsx`
mounts `root` for the chrome it renders outside `{children}` (auth modal, account settings,
cookie notice, toaster) and `app/(site)`, `app/admin`, `app/balancer` and `app/draft` each mount
their own inside it. Rule Z5 of the gate checks that every zone does.

This is not a style preference. A client-side navigation re-renders only the segments below the
deepest *shared* layout, so the first version — one provider in the root layout, fed by an
`x-owt-zone` header the middleware set from the pathname — kept whatever bundle the first page
load picked, for the life of the tab. Clicking through from a tournament page to its draft room
rendered 20 raw `draftRedesign.*` keys, because the root layout never re-rendered and the tab
was still holding the `web` bundle. A zone's own layout re-renders exactly when its zone is
entered, which is exactly when the bundle must change. `src/i18n/request.ts` now returns the
whole tree: server rendering pays no payload for a message it does not render, and narrowing
where it is *observable* is what the split needed all along.

Because `use-intl`'s `IntlProvider` replaces `messages` rather than merging with the parent,
every zone bundle is generated as a superset of `root`.

`src/i18n/zone-namespaces.json` is **generated**: `bun run lint:zones --write-i18n` walks the
import graph from each zone's route entries and collects every namespace any reachable module
could address. Rule Z4 of the gate recomputes it and fails on drift, so the map cannot rot as
code moves. A directory import (`@/components/data-table` → `…/index`) resolves to its index
file; before it did, the edge dangled and 29 modules behind it were invisible to Z4.

The collection is deliberately over-inclusive. The dominant call-site idiom is a bare
`useTranslations()` plus absolute dotted keys — `t("users.profile.title")` — and some of those
keys are built from template literals, so no analysis can *prove* which namespaces a module
needs. An extra namespace in a bundle costs payload; a missing one renders the raw dotted key
to a user. Only the safe direction of that error is acceptable, which is also why
`request.ts` now warns on `MISSING_MESSAGE` outside production instead of swallowing it.
