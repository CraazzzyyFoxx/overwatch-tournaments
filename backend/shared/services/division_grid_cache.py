from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from cashews import cache

from shared.division_grid import DivisionGrid, DivisionTier

GRID_CACHE_TTL_SECONDS = 60 * 60
CACHE_KEY_PREFIX = "backend:"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DivisionGridTierSnapshot:
    id: int | None
    slug: str | None
    number: int
    name: str
    rank_min: int
    rank_max: int | None
    icon_url: str

    @classmethod
    def from_model(cls, tier: Any) -> DivisionGridTierSnapshot:
        return cls(
            id=tier.id,
            slug=tier.slug,
            number=int(tier.number),
            name=str(tier.name),
            rank_min=int(tier.rank_min),
            rank_max=int(tier.rank_max) if tier.rank_max is not None else None,
            icon_url=str(tier.icon_url),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DivisionGridTierSnapshot:
        return cls(
            id=payload["id"],
            slug=payload["slug"],
            number=int(payload["number"]),
            name=str(payload["name"]),
            rank_min=int(payload["rank_min"]),
            rank_max=int(payload["rank_max"]) if payload["rank_max"] is not None else None,
            icon_url=str(payload["icon_url"]),
        )

    def to_runtime_tier(self) -> DivisionTier:
        return DivisionTier(
            id=self.id,
            slug=self.slug,
            number=self.number,
            name=self.name,
            rank_min=self.rank_min,
            rank_max=self.rank_max,
            icon_url=self.icon_url,
        )


@dataclass(frozen=True)
class DivisionGridVersionSnapshot:
    id: int
    tiers: tuple[DivisionGridTierSnapshot, ...]

    @classmethod
    def from_model(cls, version: Any) -> DivisionGridVersionSnapshot:
        tiers = tuple(
            sorted(
                (DivisionGridTierSnapshot.from_model(tier) for tier in version.tiers),
                key=lambda tier: tier.rank_min,
                reverse=True,
            )
        )
        return cls(id=int(version.id), tiers=tiers)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DivisionGridVersionSnapshot:
        return cls(
            id=int(payload["id"]),
            tiers=tuple(DivisionGridTierSnapshot.from_payload(tier) for tier in payload["tiers"]),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tiers": [asdict(tier) for tier in self.tiers],
        }

    def to_runtime_grid(self) -> DivisionGrid:
        return DivisionGrid(
            version_id=self.id,
            tiers=tuple(tier.to_runtime_tier() for tier in self.tiers),
        )


@dataclass(frozen=True)
class DivisionGridMappingRuleSnapshot:
    source_tier_id: int
    target_tier_id: int
    weight: float
    is_primary: bool

    @classmethod
    def from_model(cls, rule: Any) -> DivisionGridMappingRuleSnapshot:
        return cls(
            source_tier_id=int(rule.source_tier_id),
            target_tier_id=int(rule.target_tier_id),
            weight=float(rule.weight),
            is_primary=bool(rule.is_primary),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DivisionGridMappingRuleSnapshot:
        return cls(
            source_tier_id=int(payload["source_tier_id"]),
            target_tier_id=int(payload["target_tier_id"]),
            weight=float(payload["weight"]),
            is_primary=bool(payload["is_primary"]),
        )


@dataclass(frozen=True)
class DivisionGridMappingSnapshot:
    id: int
    source_version_id: int
    target_version_id: int
    is_complete: bool
    rules: tuple[DivisionGridMappingRuleSnapshot, ...]

    @classmethod
    def from_model(cls, mapping: Any) -> DivisionGridMappingSnapshot:
        return cls(
            id=int(mapping.id),
            source_version_id=int(mapping.source_version_id),
            target_version_id=int(mapping.target_version_id),
            is_complete=bool(mapping.is_complete),
            rules=tuple(DivisionGridMappingRuleSnapshot.from_model(rule) for rule in mapping.rules),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DivisionGridMappingSnapshot:
        return cls(
            id=int(payload["id"]),
            source_version_id=int(payload["source_version_id"]),
            target_version_id=int(payload["target_version_id"]),
            is_complete=bool(payload["is_complete"]),
            rules=tuple(DivisionGridMappingRuleSnapshot.from_payload(rule) for rule in payload["rules"]),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_version_id": self.source_version_id,
            "target_version_id": self.target_version_id,
            "is_complete": self.is_complete,
            "rules": [asdict(rule) for rule in self.rules],
        }


def _version_key(version_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}division_grid:version:{version_id}"


def _workspace_default_key(workspace_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}division_grid:workspace:{workspace_id}:default_version"


def _tournament_effective_key(tournament_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}division_grid:tournament:{tournament_id}:effective_version"


def _mapping_key(source_version_id: int, target_version_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}division_grid:mapping:{source_version_id}:{target_version_id}"


def _workspace_source_versions_key(workspace_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}division_grid:workspace:{workspace_id}:source_versions"


async def _get(key: str) -> Any | None:
    if not cache.is_setup():
        return None
    try:
        return await cache.get(key)
    except Exception as exc:
        logger.debug("Division grid cache get failed for %s: %s", key, exc)
        return None


async def _set(key: str, value: Any, ttl: int = GRID_CACHE_TTL_SECONDS) -> None:
    if not cache.is_setup():
        return
    try:
        await cache.set(key, value, expire=ttl)
    except Exception as exc:
        logger.debug("Division grid cache set failed for %s: %s", key, exc)


async def get_grid_version_snapshot(version_id: int) -> DivisionGridVersionSnapshot | None:
    payload = await _get(_version_key(version_id))
    if payload is None:
        return None
    return DivisionGridVersionSnapshot.from_payload(payload)


async def set_grid_version_snapshot(snapshot: DivisionGridVersionSnapshot) -> None:
    await _set(_version_key(snapshot.id), snapshot.to_payload())


async def get_workspace_default_version_id(workspace_id: int) -> int | None:
    value = await _get(_workspace_default_key(workspace_id))
    return int(value) if value is not None else None


async def set_workspace_default_version_id(workspace_id: int, version_id: int | None) -> None:
    await _set(_workspace_default_key(workspace_id), version_id)


async def get_tournament_effective_version_id(tournament_id: int) -> int | None:
    value = await _get(_tournament_effective_key(tournament_id))
    return int(value) if value is not None else None


async def set_tournament_effective_version_id(tournament_id: int, version_id: int | None) -> None:
    await _set(_tournament_effective_key(tournament_id), version_id)


async def get_mapping_snapshot(
    source_version_id: int,
    target_version_id: int,
) -> DivisionGridMappingSnapshot | None:
    payload = await _get(_mapping_key(source_version_id, target_version_id))
    if payload is None:
        return None
    return DivisionGridMappingSnapshot.from_payload(payload)


async def set_mapping_snapshot(snapshot: DivisionGridMappingSnapshot) -> None:
    await _set(
        _mapping_key(snapshot.source_version_id, snapshot.target_version_id),
        snapshot.to_payload(),
    )


async def get_workspace_source_version_ids(workspace_id: int) -> set[int] | None:
    value = await _get(_workspace_source_versions_key(workspace_id))
    if value is None:
        return None
    return {int(version_id) for version_id in value}


async def set_workspace_source_version_ids(workspace_id: int, version_ids: set[int]) -> None:
    await _set(_workspace_source_versions_key(workspace_id), sorted(version_ids))


async def invalidate_grid_version(version_id: int) -> None:
    if not cache.is_setup():
        return
    try:
        await cache.delete(_version_key(version_id))
        await cache.delete_match(f"{CACHE_KEY_PREFIX}division_grid:mapping:{version_id}:*")
        await cache.delete_match(f"{CACHE_KEY_PREFIX}division_grid:mapping:*:{version_id}")
    except Exception as exc:
        logger.debug("Division grid cache invalidation failed for version %s: %s", version_id, exc)


async def invalidate_workspace(workspace_id: int) -> None:
    if not cache.is_setup():
        return
    try:
        await cache.delete(_workspace_default_key(workspace_id))
        await cache.delete(_workspace_source_versions_key(workspace_id))
        await cache.delete_match(f"{CACHE_KEY_PREFIX}division_grid:tournament:*:effective_version")
    except Exception as exc:
        logger.debug("Division grid cache invalidation failed for workspace %s: %s", workspace_id, exc)


async def invalidate_tournament(tournament_id: int) -> None:
    if not cache.is_setup():
        return
    try:
        await cache.delete(_tournament_effective_key(tournament_id))
    except Exception as exc:
        logger.debug("Division grid cache invalidation failed for tournament %s: %s", tournament_id, exc)


async def invalidate_mapping(source_version_id: int, target_version_id: int) -> None:
    if not cache.is_setup():
        return
    try:
        await cache.delete(_mapping_key(source_version_id, target_version_id))
    except Exception as exc:
        logger.debug(
            "Division grid cache invalidation failed for mapping %s -> %s: %s",
            source_version_id,
            target_version_id,
            exc,
        )
