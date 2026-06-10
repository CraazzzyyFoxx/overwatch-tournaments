"""Typed payload models for the key-namespaced ``Settings`` table.

These are the single source of truth for the JSON shape of each settings key:
the admin write layer validates incoming payloads against them, and the runtime
settings provider parses stored rows through them (falling back to the model
defaults on missing/corrupt data). The JSON column itself has no DB-level
schema, so all guarantees live here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

__all__ = (
    "SETTINGS_KEY_RANK_COLLECTION",
    "SETTINGS_KEY_RANK_MAPPING",
    "SETTINGS_SCHEMAS",
    "RankCollectionConfig",
    "RankCollectionScope",
    "RankMappingConfig",
    "RankMappingEntry",
)

SETTINGS_KEY_RANK_COLLECTION = "parser.rank_collection"
SETTINGS_KEY_RANK_MAPPING = "parser.rank_mapping"

RankCollectionScope = Literal["registrations_only", "all"]


class RankCollectionConfig(BaseModel):
    """Operational config for the periodic OverFast rank collector.

    Defaults are deliberately safe: ``enabled=False`` so a missing/empty key can
    never start unbounded parsing, and bounded interval/rate so a misconfig
    cannot hammer the OverFast instance.
    """

    enabled: bool = False
    interval_seconds: int = Field(default=900, ge=60, le=86_400)
    batch_size: int = Field(default=50, ge=1, le=1000)
    rate_limit_per_minute: int = Field(default=30, ge=1, le=6000)
    scope: RankCollectionScope = "registrations_only"
    # Self-pace each scheduler tick to cover the in-scope population once per
    # ``interval_seconds`` instead of claiming a fixed ``batch_size`` per tick.
    # ``False`` restores the legacy fixed-batch behaviour (rollback switch).
    auto_pace: bool = True
    # Fraction of the interval used as a random spread when (re)scheduling a tag,
    # so tags processed together don't recur together. 0 = exact recurrence.
    jitter_fraction: float = Field(default=0.15, ge=0.0, le=1.0)
    # Optional hard ceiling on per-tick claims under ``auto_pace``. ``None`` =
    # derive the ceiling from ``rate_limit_per_minute`` (and ``batch_size``) only.
    max_per_tick: int | None = Field(default=None, ge=1, le=10_000)
    # Under ``registrations_only``: besides the tags entered in a registration
    # (main + smurfs), also collect up to this many of the registrant's *other*
    # battle.net accounts. 0 = only the registered pool.
    extra_accounts_per_registration: int = Field(default=0, ge=0, le=50)
    max_consecutive_failures: int = Field(default=5, ge=1, le=100)
    backoff_base_seconds: int = Field(default=60, ge=1, le=86_400)


class RankMappingEntry(BaseModel):
    """One native division+tier → integer rank_value mapping row."""

    division: str = Field(..., min_length=1, max_length=32)
    tier: int = Field(..., ge=1, le=5)
    rank_value: int = Field(..., ge=0, le=100_000)


class RankMappingConfig(BaseModel):
    """Override for the OverFast division+tier → rank_value mapping.

    An empty ``entries`` list means "use the code default" — the parser-side
    mapping module merges these entries over its built-in default, so editing a
    single division+tier here only overrides that one cell.
    """

    version: str = Field(default="ow2-default-v1", min_length=1, max_length=64)
    entries: list[RankMappingEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_division_tier(self) -> RankMappingConfig:
        seen: set[tuple[str, int]] = set()
        for entry in self.entries:
            key = (entry.division.lower(), entry.tier)
            if key in seen:
                raise ValueError(
                    f"duplicate mapping entry for division={entry.division!r} tier={entry.tier}"
                )
            seen.add(key)
        return self


#: Registry consumed by the admin layer to validate writes per key.
SETTINGS_SCHEMAS: dict[str, type[BaseModel]] = {
    SETTINGS_KEY_RANK_COLLECTION: RankCollectionConfig,
    SETTINGS_KEY_RANK_MAPPING: RankMappingConfig,
}
