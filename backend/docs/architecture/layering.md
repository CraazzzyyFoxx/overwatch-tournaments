# Service Layering (app-service)

Enforced by `backend/app-service/.importlinter`. Run from `backend/`:

```bash
uv run lint-imports --config app-service/.importlinter
```

## Layers (high → low)

| Layer | Modules | Role |
|---|---|---|
| L5 | `services.achievements` | Aggregates user/encounter/tournament |
| L4 | `services.user`, `services.dashboard` | Cross-domain read APIs |
| L3 | `services.encounter`, `services.standings` | Derive from L2 + match data |
| L2 | `services.team`, `services.tournament` | Tournament-lifecycle entities |
| L1 | `services.hero`, `services.map`, `services.gamemode`, `services.registration`, `services.statistics`, `services.division_grid`, `services.workspace` | Leaf domains, no cross-domain deps |

**Rule:** higher layers may import lower; the reverse is forbidden.

## Known debt (grandfathered)

`.importlinter` `ignore_imports` lists existing reverse-direction imports
that pre-date this contract. They must not grow. Migration targets:

### `tournament/team/encounter/map → user.flows`

Caused by `user_flows.to_pydantic` and `user_flows.get` being called by
lower layers for shared serialization helpers.

**Fix:** extract a `services.user_core` module containing the bare model
→ schema converter and the ID-lookup helpers. Lower layers depend on
`user_core` (L1); only `services.user` (L4) keeps the aggregate flows.

Effort: ~2 days. Touches `team/flows.py:67,116`, `tournament/flows.py:394,444`,
`encounter/flows.py:408`, `map/flows.py:124,194`.

### `map → hero`

`map_flows` does hero-aware aggregations. Either:
- Move the hero-aware map endpoints to a new `services.user_maps`
  (L3-like) module, or
- Lift the hero call to L4 (caller of map_flows) and pass hero IDs down.

Effort: ~1 day.

## Contract 2: routes → flows

`src.routes.*` may not import `services.*.service` directly. All DB-touching
work goes through `flows.py`. This is what makes workspace scoping
consistent (see P1-#12 cross-tenant leak).

Grandfathered violations:
- `routes.tournament` composes raw `sa.select` for the `/lookup` endpoint
- `routes.registration` calls service directly in `/workspaces/{id}/...`
- `routes.workspace`, `routes.division_grid` — small admin routes

Each should be wrapped in a `flows.get_lookup`/`flows.list_*` helper.

## How to add a new domain

1. Pick the lowest layer that's compatible with its dependencies.
2. Add its package name to that layer in `.importlinter`.
3. Run `lint-imports`. If it fails, either:
   - Restructure to fit the layering, or
   - Argue for moving up a layer (must not create cycles).
