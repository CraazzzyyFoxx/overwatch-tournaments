"""The caller's own pickup-mix settings over typed RPC.

``rpc.balancer.prefs.{get,upsert}``. No workspace and no permission check: these
are the signed-in account's own mix settings, and every mix it hosts runs with
them. Being authenticated is the whole gate -- there is no "somebody else's
preferences" to authorize against.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.domain.roster_shape import resolve_roster_shape
from shared.schemas.roster_slots import RosterShapeRead
from src import models, schemas
from src.core import db
from src.rpc import _common as c
from src.services.user_prefs import user_mix_prefs_service

_SF = db.async_session_maker


def _to_read(cfg: models.UserBalancerConfig | None) -> schemas.UserMixPreferencesRead:
    """The stored row spelled out field by field; all-null when nothing is saved.

    ``config_json`` holds only the keys the user actually set, so an absent one
    reads back as ``null`` -- the wire's word for "use the engine default".

    ``roster_shape`` is derived, never stored: the same resolved object a mix
    hands its board, so the settings screen previews the exact shape it is about
    to balance into without re-implementing the fallback chain. No workspace is
    in scope here (these preferences are not workspace-bound), so the chain is
    only "this account's mask, else the built-in Overwatch 5v5".
    """
    payload = (cfg.config_json or {}) if cfg is not None else {}
    role_mask = cfg.role_slots_json if cfg is not None else None
    return schemas.UserMixPreferencesRead(
        mix_comfort_tilt=payload.get("mix_comfort_tilt"),
        mix_role_weights=payload.get("mix_role_weights"),
        max_result_variants=payload.get("max_result_variants"),
        role_mask=role_mask or None,
        points_per_win=cfg.points_per_win if cfg is not None else None,
        roster_shape=RosterShapeRead.from_shape(
            resolve_roster_shape(role_mask or None, None),
            source="user" if role_mask else "default",
        ),
    )


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.prefs.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            return _to_read(await user_mix_prefs_service.get(session, user.id))

        return await c.envelope(logger, "prefs.get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.prefs.upsert")
    async def _upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            body = schemas.UserMixPreferencesUpsert.model_validate(c.payload(data))
            cfg = await user_mix_prefs_service.upsert(
                session,
                user_id=user.id,
                mix_comfort_tilt=body.mix_comfort_tilt,
                mix_role_weights=body.mix_role_weights,
                max_result_variants=body.max_result_variants,
                role_mask=body.role_mask,
                points_per_win=body.points_per_win,
            )
            # The service owns the commit, like the workspace-config upsert.
            return _to_read(cfg)

        return await c.envelope(logger, "prefs.upsert", op, session_factory=_SF)
