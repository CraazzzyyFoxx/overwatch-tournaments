"""One account's pickup-mix settings: read and full replacement.

Shaped like ``BalancerAdminService``'s workspace-config pair (one row per owner,
upsert owns its commit), but there is no workspace and no permission: these are
the caller's own knobs, and the only gate is being signed in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.balancer import UserBalancerConfig
from shared.repository import UserBalancerConfigRepository
from shared.schemas.roster_slots import normalize_roster_slots
from src.services.balancer.config.public_contract import normalize_config_payload

__all__ = ("UserMixPrefsService", "user_mix_prefs_service")


class UserMixPrefsService:
    def __init__(
        self,
        *,
        configs: UserBalancerConfigRepository = UserBalancerConfigRepository(),
    ) -> None:
        self.configs = configs

    async def get(self, session: AsyncSession, user_id: int) -> UserBalancerConfig | None:
        return await self.configs.get_by_user(session, user_id)

    async def upsert(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        mix_comfort_tilt: float | None,
        mix_role_weights: Mapping[str, float] | None,
        max_result_variants: int | None,
        role_mask: Mapping[str, int] | None,
        points_per_win: int | None,
    ) -> UserBalancerConfig:
        """Replace the account's settings, splitting them the way the row stores them.

        ``config_json`` is the solver-override blob itself, not a translation of
        one: ``CustomGameService.balance`` passes it straight through. So an
        unset knob is an absent key rather than an explicit null -- a stored
        ``{"mix_comfort_tilt": null}`` would override the engine default with
        nothing -- and the blob goes through the same ``ConfigOverrides``
        validation a saved tournament config does, so no key the solver does not
        recognise can ever be persisted into its input.

        The roster shape and the points knob are columns beside it, never keys
        inside it: neither is a solver override (see ``UserBalancerConfig``).
        The mask is normalized here rather than at the wire so the column can
        never hold a zero count, and ``0`` points stores as NULL -- "off" has one
        spelling in the column, whichever of the two the client sent.
        """
        raw: dict[str, Any] = {
            "mix_comfort_tilt": mix_comfort_tilt,
            "mix_role_weights": dict(mix_role_weights) if mix_role_weights else None,
            "max_result_variants": max_result_variants,
        }
        payload = normalize_config_payload({key: value for key, value in raw.items() if value is not None})
        try:
            slots = normalize_roster_slots(dict(role_mask) if role_mask else None)
        except ValueError as exc:
            # ``normalize_roster_slots`` prefixes the machine-readable
            # ``RosterShapeError`` code into the message; the frontend localizes
            # off that, so it must survive into the 422 body.
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        fields: dict[str, Any] = {
            "config_json": payload,
            "role_slots_json": slots or None,
            "points_per_win": points_per_win or None,
        }
        config = await self.get(session, user_id)
        if config is None:
            config = await self.configs.create(session, UserBalancerConfig(user_id=user_id, **fields))
        else:
            await self.configs.update_fields(session, config, fields)
        await session.commit()
        # expire_on_commit=False keeps attributes (incl. the flushed PK) live after
        # commit, so no refresh round-trip is needed.
        return config


user_mix_prefs_service = UserMixPrefsService()
