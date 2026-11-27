"""One account's pickup-mix settings: read and full replacement.

Shaped like ``BalancerAdminService``'s workspace-config pair (one row per owner,
upsert owns its commit), but there is no workspace and no permission: these are
the caller's own knobs, and the only gate is being signed in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.balancer import UserBalancerConfig
from shared.repository import UserBalancerConfigRepository
from src.domain.balancer.config.public_contract import normalize_config_payload

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
        role_settings: Mapping[str, Mapping[str, float]] | None,
        max_result_variants: int | None,
        open_slot_settings: Mapping[str, float] | None,
        points_per_win: int | None,
        rating_mode: str,
        hero_ban_presets: Mapping[str, str],
        formation_defaults: Mapping[str, Mapping[str, Any]],
        mix_rules: Mapping[str, Any] | None,
    ) -> UserBalancerConfig:
        """Replace the account's settings, splitting them the way the row stores them.

        ``config_json`` is the solver-override blob itself, not a translation of
        one: ``CustomGameService.balance`` passes it straight through. So an
        unset knob is an absent key rather than an explicit null -- a stored
        ``{"mix_comfort_tilt": null}`` would override the engine default with
        nothing -- and the blob goes through the same ``ConfigOverrides``
        validation a saved tournament config does, so no key the solver does not
        recognise can ever be persisted into its input.

        Points and rating mode are columns beside the solver blob.
        Zero points stores as NULL, the single spelling of "off".
        The per-game ban defaults are a column of their own: they are not solver input.
        The per-game formation defaults are a column of their own as well.
        """
        raw: dict[str, Any] = {
            "mix_comfort_tilt": mix_comfort_tilt,
            "role_settings": {code: dict(settings) for code, settings in role_settings.items()}
            if role_settings
            else None,
            "max_result_variants": max_result_variants,
            "open_slot_settings": dict(open_slot_settings) if open_slot_settings else None,
            "mix_rules": dict(mix_rules) if mix_rules else None,
        }
        payload = normalize_config_payload({key: value for key, value in raw.items() if value is not None})
        fields: dict[str, Any] = {
            "config_json": payload,
            "points_per_win": points_per_win or None,
            "rating_mode": rating_mode,
            "hero_ban_presets": dict(hero_ban_presets),
            "formation_defaults": {code: dict(value) for code, value in formation_defaults.items()},
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
