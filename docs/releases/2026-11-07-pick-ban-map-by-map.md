# Map-by-map pool: release note

A map veto either settled the whole series up front (one shared pool) or banned each map's own group down to one
survivor (one group per match). A third pool shape plays one shared pool a map at a time: bans and the first map before
match 1, each next map after the previous match, out of what is left.

## What changed

- **`MapVetoMode.PROGRESSIVE`** (`progressive`, migration `pbprog01_progressive_pool_mode`): a flat map pool whose
  rounds grow one per map like slot mode. Round N+1 opens after position N is confirmed; maps picked in earlier rounds
  leave the candidates (`advance_to_next_round`), bans carry by their `lifetime` as before.
- **Validation**: map kind only (`progressive_map_only`); every phase settles exactly one map with one pick or one
  decider (`progressive_phase_one_map`); generators are refused as in any non-matching mode.
- **Pool size**: the series preview reports `pool_exhausted` (error) on the first map the pool cannot supply; the admin
  upsert refuses with 422 `pool_too_small` when the generated bracket at the config's scope plays a series the pool
  cannot last (encounters served by a narrower pooled config are not counted). Before the bracket exists only the
  preview checks it.
- **Preset `map_by_map`**: each side bans one map for the series, the opener picks map 1, then the previous loser picks.
  The editor opens a new map-by-map pool on these rules.
- **Editor**: **Pool shape** → **One shared pool, map by map** (map kind only). Switching into or out of it resets the
  rules to that shape's default.

## Rollout

1. `alembic upgrade head` before the new services start: the config column must accept `progressive`.
2. Nothing changes for existing configs. Downgrade turns progressive configs back into flat pools (PostgreSQL keeps the
   enum label).
