"""The caller's own pickup-mix settings over typed RPC.

``rpc.balancer.prefs.{get,upsert}``. No workspace and no permission check: these
are the signed-in account's own mix settings, and every mix it hosts runs with
them. Being authenticated is the whole gate -- there is no "somebody else's
preferences" to authorize against.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared import models
from src import schemas
from src.core import db
from src.rpc import _common as c
from src.services.user_prefs import user_mix_prefs_service

_SF = db.async_session_maker


def _to_read(cfg: models.UserBalancerConfig | None) -> schemas.UserMixPreferencesRead:
    """The stored row spelled out field by field; all-null when nothing is saved.

    ``config_json`` holds only the keys the user actually set, so an absent one
    reads back as ``null`` -- the wire's word for "use the engine default".
    """
    payload = (cfg.config_json or {}) if cfg is not None else {}
    return schemas.UserMixPreferencesRead(
        mix_comfort_tilt=payload.get("mix_comfort_tilt"),
        role_settings=payload.get("role_settings"),
        max_result_variants=payload.get("max_result_variants"),
        open_slot_settings=payload.get("open_slot_settings"),
        points_per_win=cfg.points_per_win if cfg is not None else None,
        rating_mode=cfg.rating_mode if cfg is not None else "points",
        hero_ban_presets=dict(cfg.hero_ban_presets or {}) if cfg is not None else {},
        formation_defaults=dict(cfg.formation_defaults or {}) if cfg is not None else {},
        mix_rules=payload.get("mix_rules"),
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
                role_settings={code: settings.model_dump() for code, settings in (body.role_settings or {}).items()}
                or None,
                max_result_variants=body.max_result_variants,
                open_slot_settings=body.open_slot_settings.model_dump() if body.open_slot_settings else None,
                points_per_win=body.points_per_win,
                rating_mode=body.rating_mode,
                hero_ban_presets=body.hero_ban_presets,
                formation_defaults={code: value.model_dump() for code, value in body.formation_defaults.items()},
                mix_rules=body.mix_rules.model_dump() if body.mix_rules else None,
            )
            # The service owns the commit, like the workspace-config upsert.
            return _to_read(cfg)

        return await c.envelope(logger, "prefs.upsert", op, session_factory=_SF)
