"""The caller's own mix-balancer preferences over typed RPC.

``rpc.balancer.prefs.{get,upsert}``. No workspace and no permission check: these
are the signed-in account's own solver knobs, and every mix it hosts balances
with them. Being authenticated is the whole gate -- there is no "somebody else's
preferences" to authorize against.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from src import models, schemas
from src.core import db
from src.rpc import _common as c
from src.services.user_prefs import user_mix_prefs_service

_SF = db.async_session_maker


def _to_read(cfg: models.UserBalancerConfig | None) -> schemas.UserMixPreferencesRead:
    """The stored blob spelled out key by key; all-null when nothing is saved.

    ``config_json`` holds only the keys the user actually set, so an absent one
    reads back as ``null`` -- the wire's word for "use the engine default".
    """
    payload = (cfg.config_json or {}) if cfg is not None else {}
    return schemas.UserMixPreferencesRead(
        mix_comfort_tilt=payload.get("mix_comfort_tilt"),
        mix_role_weights=payload.get("mix_role_weights"),
        max_result_variants=payload.get("max_result_variants"),
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
            )
            # The service owns the commit, like the workspace-config upsert.
            return _to_read(cfg)

        return await c.envelope(logger, "prefs.upsert", op, session_factory=_SF)
