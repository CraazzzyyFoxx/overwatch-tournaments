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

import sqlalchemy as sa
from cashews import cache
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.schemas.settings import (
    SETTINGS_KEY_RANK_COLLECTION,
    SETTINGS_KEY_RANK_MAPPING,
    RankCollectionConfig,
    RankMappingConfig,
)

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "backend:"
SETTINGS_CACHE_TTL_SECONDS = 30


def _cache_key(key: str) -> str:
    return f"{CACHE_KEY_PREFIX}settings:{key}"


async def get_setting_value(session: AsyncSession, key: str) -> dict:
    """Return the raw JSON value for ``key`` (``{}`` if absent), short-cached."""
    cache_key = _cache_key(key)
    if cache.is_setup():
        try:
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached
        except Exception as exc:  # pragma: no cover - cache is best-effort
            logger.debug("settings cache get failed for %s: %s", key, exc)

    result = await session.execute(sa.select(models.Settings.value).where(models.Settings.key == key))
    value = result.scalar_one_or_none() or {}

    if cache.is_setup():
        try:
            await cache.set(cache_key, value, expire=SETTINGS_CACHE_TTL_SECONDS)
        except Exception as exc:  # pragma: no cover - cache is best-effort
            logger.debug("settings cache set failed for %s: %s", key, exc)
    return value


async def invalidate_setting(key: str) -> None:
    """Drop the cached value for ``key`` (call after a write)."""
    if not cache.is_setup():
        return
    try:
        await cache.delete(_cache_key(key))
    except Exception as exc:  # pragma: no cover - cache is best-effort
        logger.debug("settings cache invalidate failed for %s: %s", key, exc)


async def get_rank_collection_config(session: AsyncSession) -> RankCollectionConfig:
    raw = await get_setting_value(session, SETTINGS_KEY_RANK_COLLECTION)
    try:
        return RankCollectionConfig.model_validate(raw)
    except ValidationError as exc:
        logger.warning("invalid %s settings, using defaults: %s", SETTINGS_KEY_RANK_COLLECTION, exc)
        return RankCollectionConfig()


async def get_rank_mapping_config(session: AsyncSession) -> RankMappingConfig:
    raw = await get_setting_value(session, SETTINGS_KEY_RANK_MAPPING)
    try:
        return RankMappingConfig.model_validate(raw)
    except ValidationError as exc:
        logger.warning("invalid %s settings, using defaults: %s", SETTINGS_KEY_RANK_MAPPING, exc)
        return RankMappingConfig()
