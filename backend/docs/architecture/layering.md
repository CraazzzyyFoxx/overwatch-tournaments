# Service Layering (app-service)

This is `app-service`'s specific, enforced sub-domain hierarchy inside the `services/` layer.
For the general rpc → services → domain → repository → models layering every service follows,
see [`backend/ARCHITECTURE.md`](../../ARCHITECTURE.md).

Enforced by `backend/app-service/.importlinter`. Run from `backend/`:

```bash
uv run lint-imports --config app-service/.importlinter
```

## Contracts

| Contract | Rule |
|---|---|
| `services-layers` | Inside `src.services`, high → low: `achievements` → `dashboard`, `user` → `hero`, `map`, `statistics`, `workspace`. A higher layer may import a lower one, never the reverse. |
| `rpc-goes-through-services` | `src.rpc` never imports a query class (`user`, `hero`, `statistics`, `achievements` `.queries`); it calls one service. |
| `user-privates` | `user.queries` and `user._mappers` are private to `services.user`. |
| `achievements-privates` | `achievements._mappers` is private to `services.achievements`. |

Existing reverse imports are listed by name under `ignore_imports` in `services-layers`
(`map.service` → `hero.queries`, `hero.service`, `user.service`). The list must only shrink.

## How to add a new domain

1. Pick the lowest layer that's compatible with its dependencies.
2. Add its package name to that layer in `.importlinter`.
3. Run `lint-imports`. If it fails, either:
   - Restructure to fit the layering, or
   - Argue for moving up a layer (must not create cycles).
