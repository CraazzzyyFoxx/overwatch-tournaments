"""Runtime reader for the key-namespaced ``Settings`` table.

Provides typed, short-TTL-cached accessors over the JSON settings rows. Any
service that has called ``cache.setup(...)`` (cashews is process-global) gets
cross-pod cache sharing via Redis; the short TTL bounds staleness even if an
explicit invalidation is missed. Every accessor falls back to the typed model
defaults when a key is absent or its JSON is malformed, so callers always get a
valid config (and, by default, ``enabled=False`` — fail safe).
"""

from __future__ import annotations

import logging

from cashews import cache
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.repository import SettingsRepository
from shared.schemas.settings import (
    SETTINGS_KEY_RANK_COLLECTION,
    SETTINGS_KEY_RANK_MAPPING,
    SETTINGS_KEY_SCRIM,
    SETTINGS_KEY_STREAM_COLLECTION,
    SETTINGS_KEY_SUBSCRIPTION_COLLECTION,
    SETTINGS_KEY_WORKSPACE_CREATION,
    RankCollectionConfig,
    RankMappingConfig,
    ScrimConfig,
    StreamCollectionConfig,
    SubscriptionCollectionConfig,
    WorkspaceCreationConfig,
)

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "backend:"
SETTINGS_CACHE_TTL_SECONDS = 30

__all__ = (
    "CACHE_KEY_PREFIX",
    "SETTINGS_CACHE_TTL_SECONDS",
    "SettingsProvider",
    "settings_provider",
)


def _cache_key(key: str) -> str:
    return f"{CACHE_KEY_PREFIX}settings:{key}"


class SettingsProvider:
    def __init__(self, *, repo: SettingsRepository = SettingsRepository()) -> None:
        self._repo = repo

    async def get_setting_value(self, session: AsyncSession, key: str) -> dict:
        """Return the raw JSON value for ``key`` (``{}`` if absent), short-cached."""
        cache_key = _cache_key(key)
        if cache.is_setup():
            try:
                cached = await cache.get(cache_key)
                if cached is not None:
                    return cached
            except Exception as exc:  # pragma: no cover - cache is best-effort
                logger.debug("settings cache get failed for %s: %s", key, exc)

        row = await self._repo.get_by_key(session, key)
        value = (row.value if row is not None else None) or {}

        if cache.is_setup():
            try:
                await cache.set(cache_key, value, expire=SETTINGS_CACHE_TTL_SECONDS)
            except Exception as exc:  # pragma: no cover - cache is best-effort
                logger.debug("settings cache set failed for %s: %s", key, exc)
        return value

    async def invalidate_setting(self, key: str) -> None:
        """Drop the cached value for ``key`` (call after a write)."""
        if not cache.is_setup():
            return
        try:
            await cache.delete(_cache_key(key))
        except Exception as exc:  # pragma: no cover - cache is best-effort
            logger.debug("settings cache invalidate failed for %s: %s", key, exc)

    async def get_rank_collection_config(self, session: AsyncSession) -> RankCollectionConfig:
        return await self._typed(session, SETTINGS_KEY_RANK_COLLECTION, RankCollectionConfig)

    async def get_rank_mapping_config(self, session: AsyncSession) -> RankMappingConfig:
        return await self._typed(session, SETTINGS_KEY_RANK_MAPPING, RankMappingConfig)

    async def get_subscription_collection_config(self, session: AsyncSession) -> SubscriptionCollectionConfig:
        return await self._typed(session, SETTINGS_KEY_SUBSCRIPTION_COLLECTION, SubscriptionCollectionConfig)

    async def get_stream_collection_config(self, session: AsyncSession) -> StreamCollectionConfig:
        return await self._typed(session, SETTINGS_KEY_STREAM_COLLECTION, StreamCollectionConfig)

    async def get_scrim_config(self, session: AsyncSession) -> ScrimConfig:
        return await self._typed(session, SETTINGS_KEY_SCRIM, ScrimConfig)

    async def get_workspace_creation_config(self, session: AsyncSession) -> WorkspaceCreationConfig:
        return await self._typed(session, SETTINGS_KEY_WORKSPACE_CREATION, WorkspaceCreationConfig)

    async def _typed(self, session: AsyncSession, key: str, model: type):
        raw = await self.get_setting_value(session, key)
        try:
            return model.model_validate(raw)
        except ValidationError as exc:
            logger.warning("invalid %s settings, using defaults: %s", key, exc)
            return model()


settings_provider = SettingsProvider()
