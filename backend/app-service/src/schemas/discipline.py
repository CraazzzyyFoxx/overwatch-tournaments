"""Public native metadata of an installed discipline: descriptor, scoped ontology, vocabularies, ladder."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from shared.schemas.team_format import TeamFormatRead

__all__ = (
    "CatalogKind",
    "DisciplineCapabilities",
    "DisciplineDescriptor",
    "DisciplineMetadata",
    "EventTypeRead",
    "IngestClientRead",
    "LobbyBotRead",
    "NativeTierRead",
    "OntologyRole",
    "RoleDimensionRead",
    "StatDefinition",
)

CatalogKind = Literal["character", "map", "mode"]


class DisciplineCapabilities(BaseModel):
    """Declaration presence only: a hook is never invoked to answer."""

    catalog_sync: bool
    native_rank_collection: bool
    native_ladder: bool
    #: A match can be imported by its external id (``DisciplineSpec.match_fetchers``).
    match_fetch: bool
    #: A mix round's match is looked up by its players (a ``match_searchers`` kind it can fetch, and an identity).
    match_search: bool
    #: An uploaded match-log file is parsed (an ``upload`` entry in ``DisciplineSpec.ingestors``).
    log_upload: bool
    #: A bot can open the in-game lobby of a pickup mix (``DisciplineSpec.lobby_bot``).
    lobby_bot: bool
    #: A player's match-upload (ingest) status can be read (``DisciplineSpec.ingest_status``).
    ingest_status: bool
    achievement_conditions: bool
    analytics: bool


class IngestClientRead(BaseModel):
    """Mirrors ``shared.disciplines.lobby.IngestClient``."""

    instructions_url: str
    installer_url: str


class DisciplineDescriptor(BaseModel):
    code: str
    name: str
    enabled: bool
    #: A kind the game does not declare is absent (LoL has no ``mode``).
    kinds: dict[CatalogKind, str]
    character_classes: list[str]
    #: ``None``: the game has no identity input/upsert.
    identity_provider: str | None
    #: The game has open slots and Full flex players (``DisciplineSpec.flex``); ``False`` hides Full flex.
    flex: bool
    capabilities: DisciplineCapabilities
    #: The game's monogram ("OW"); the module's ``short_name``, else its name.
    short_name: str
    #: The icon's public URL, or ``None`` (the frontend draws the monogram).
    icon: str | None
    #: Where a player gets the client that uploads their matches; ``None`` when the game names none.
    ingest_client: IngestClientRead | None


class RoleDimensionRead(BaseModel):
    id: int
    code: str
    name: str
    selection_mode: Literal["single", "multi"]
    rated: bool
    active: bool
    sort_order: int


class OntologyRole(BaseModel):
    id: int
    #: Dimension code.
    dimension: str
    code: str
    name: str
    parent_id: int | None
    #: ``None``: a module role.
    workspace_id: int | None
    active: bool
    selectable: bool
    sort_order: int
    #: Raw keys preserved; a stored ``assets/`` icon key is resolved to its public URL.
    attrs: dict[str, Any]


class StatDefinition(BaseModel):
    id: int
    code: str
    name: str
    value_format: Literal["integer", "decimal", "percent", "duration"]
    aggregation: Literal["sum", "max", "min", "avg", "last"]
    #: Serialized from ``stats.stat_def.stat_group``.
    group: str | None
    active: bool
    sort_order: int


class EventTypeRead(BaseModel):
    id: int
    code: str
    name: str
    active: bool


class NativeTierRead(BaseModel):
    """Mirrors ``shared.disciplines.spec.NativeTier``."""

    number: int
    slug: str
    name: str
    rank_min: int
    rank_max: int | None
    icon_url: str
    native_division: str
    native_tier: int | None


class LobbyBotRead(BaseModel):
    """Mirrors ``shared.disciplines.lobby.LobbyBotSpec``'s declarations."""

    regions: list[str]
    default_region: str


class DisciplineMetadata(BaseModel):
    discipline: DisciplineDescriptor
    #: ``None``: the global view (module roles only).
    workspace_id: int | None
    #: History dictionary: inactive rows included, ``(sort_order, code)`` order.
    dimensions: list[RoleDimensionRead]
    roles: list[OntologyRole]
    stat_defs: list[StatDefinition]
    event_types: list[EventTypeRead]
    team_format_presets: list[TeamFormatRead]
    #: ``None``: the game has no bot lobby.
    lobby_bot: LobbyBotRead | None
    #: Top tier first; empty for a game whose organiser enters ranks.
    native_ladder: list[NativeTierRead]
