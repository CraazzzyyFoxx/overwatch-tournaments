"""The Deadlock module. Core reaches it only through ``shared.disciplines``."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from typing import TYPE_CHECKING, Any

from shared.core.social import SocialProvider
from shared.disciplines.deadlock.ladder import NATIVE_LADDER
from shared.disciplines.deadlock.stats import EVENT_TYPES, STAT_DEFS
from shared.disciplines.lobby import IngestClient, LobbyBotSpec
from shared.disciplines.spec import DimensionSpec, DisciplineSpec, FormatDimensionSpec, RoleSpec, TeamFormatPreset

if TYPE_CHECKING:
    from pydantic import BaseModel
    from sqlalchemy.ext.asyncio import AsyncSession

    from shared.catalog_sync import CatalogImageMirror, CatalogSyncProgress
    from shared.disciplines.ingest import DecodeContext, MatchCandidate, MatchQuery
    from shared.disciplines.lobby import BotLobbyParty, BotLobbyRequest, IngestStatus
    from shared.disciplines.spec import CollectionHandler
    from shared.domain.pick_ban_rules.presets import Preset
    from shared.models.identity.auth_user import AuthUser
    from shared.schemas.match_doc import MatchDoc

__all__ = ("SPEC",)

#: deadlock-api match metadata; ``external_id`` is the match id.
SOURCE_KIND = "deadlock_api"


async def _catalog_sync(session: AsyncSession, images: CatalogImageMirror, progress: CatalogSyncProgress) -> None:
    # Imported on call: the registry is imported by the pure pick-ban domain, which must not load repositories and an
    # HTTP client to answer "does this game have sides".
    from shared.disciplines.deadlock.catalog_sync import sync_catalog

    await sync_catalog(session, images, progress)


def _pick_ban_presets() -> tuple[Preset, ...]:
    # Imported on call: the preset parses its ruleset through the pick-ban domain, which imports this registry.
    from shared.disciplines.deadlock.pick_ban import PRESETS

    return PRESETS


async def _native_ranks(session: AsyncSession, user_ids: Sequence[int]) -> dict[int, dict[str, int]]:
    # Imported on call: the snapshot read loads models the pure domain must not.
    from shared.disciplines.deadlock.ranks import native_ranks

    return await native_ranks(session, user_ids)


def _native_rank_rows(members: Any, game: str) -> Any:
    from shared.disciplines.deadlock.ranks import latest_rank_rows

    return latest_rank_rows(members, game)


def _decode(raw: bytes, ctx: DecodeContext) -> MatchDoc:
    # Imported on call, like Overwatch's: the decoder loads the match-document schema.
    from shared.disciplines.deadlock.ingest import decode

    return decode(raw, ctx)


async def _fetch_match(external_id: str) -> bytes:
    # Imported on call: the fetcher opens an HTTP client.
    from shared.disciplines.deadlock.fetch import fetch_match

    return await fetch_match(external_id)


async def _search_matches(query: MatchQuery) -> Sequence[MatchCandidate]:
    # Imported on call, like the fetcher: the search opens an HTTP client.
    from shared.disciplines.deadlock.search import search_matches

    return await search_matches(query)


#: deadlock-api ``ServerRegion``: the bot lobby's ``server_region``.
SERVER_REGIONS = (
    "europe",
    "eu_amsterdam",
    "eu_poland",
    "eu_stockholm",
    "eu_helsinki",
    "eu_falkenstein",
    "eu_spain",
    "eu_east",
    "eu_london",
    "south_africa",
    "us_west",
    "us_east",
    "us_north_central",
    "us_south_central",
    "us_south_east",
    "us_south_west",
    "australia",
    "singapore",
    "japan",
    "hong_kong",
    "mp_hong_kong",
    "seoul",
    "chile",
    "peru",
    "argentina",
    "south_america",
)


async def _create_lobby(request: BotLobbyRequest) -> BotLobbyParty:
    # Imported on call: the bot lobby opens an HTTP client.
    from shared.disciplines.deadlock.lobby import create_party

    return await create_party(request)


async def _lobby_match_id(party_id: str) -> str | None:
    from shared.disciplines.deadlock.lobby import party_match_id

    return await party_match_id(party_id)


async def _ingest_status(account_ids: Sequence[str]) -> dict[str, IngestStatus | None]:
    # Imported on call, like the fetcher: the status read opens an HTTP client.
    from shared.disciplines.deadlock.ingest_status import ingest_status

    return await ingest_status(account_ids)


#: The collection RPCs the collector serves (``handlers.HANDLERS`` holds the bodies) — LoL's set.
_COLLECTION_HANDLERS = (
    "rank.user_history",
    "rank.game_account_history",
    "rank.user_current",
    "rank.fetch_log",
    "rank.stats",
    "rank.user_collection",
    "rank.collect",
    "rank.reenable_disabled",
)


def _configure_runtime(broker: Any, *, session_factory: Any, redis: Any) -> None:
    from shared.disciplines.deadlock import collector

    collector.configure(session_factory=session_factory, redis=redis, broker=broker)


def _register_jobs(broker: Any, *, session_factory: Any, redis: Any, logger: Any) -> None:
    # Imported on call: the collector pulls in the broker, an HTTP client and the scheduler.
    from shared.disciplines.deadlock.jobs import register_jobs

    register_jobs(broker, session_factory=session_factory, redis=redis, logger=logger)


async def _start_jobs(*, session_factory: Any, redis: Any, logger: Any) -> None:
    from shared.disciplines.deadlock.jobs import start_jobs

    await start_jobs(session_factory=session_factory, redis=redis, logger=logger)


def _stop_jobs() -> Awaitable[None]:
    from shared.disciplines.deadlock.jobs import stop_jobs

    return stop_jobs()


def _collection_handler(name: str) -> CollectionHandler:
    async def handle(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
        from shared.disciplines.deadlock.handlers import HANDLERS

        return await HANDLERS[name](session, user, data)

    return handle


def _settings_schema(key: str) -> type[BaseModel] | None:
    # Imported on call, like the jobs: the collector's config sits beside its broker queues and HTTP client.
    from shared.disciplines.deadlock import collector

    return collector.DeadlockRankCollectionConfig if key == collector.SETTINGS_KEY else None


#: Deadlock ranks are per player, not per position: one rated dimension with one role, and no open slot (``flex``).
AGENT = DimensionSpec("agent", "Agent", "single", True, (RoleSpec("agent", "Agent"),))
OPEN_6V6 = TeamFormatPreset("open_6v6", "6v6", 6, 6, dimensions=(FormatDimensionSpec("agent", "off"),))
#: Street Brawl.
OPEN_4V4 = TeamFormatPreset("open_4v4", "4v4 without roles", 4, 4, dimensions=(FormatDimensionSpec("agent", "off"),))


SPEC = DisciplineSpec(
    "deadlock",
    "Deadlock",
    #: Index 0 = Team0 (Hidden King), 1 = Team1 (Archmother): labels only, no side-pick step anywhere.
    sides=("hidden_king", "archmother"),
    kinds={"character": "Hero", "map": "Map", "mode": "Mode"},
    #: deadlock-api ``hero_type``.
    character_classes=("marksman", "mystic", "brawler", "assassin"),
    #: Public sources say a Deadlock match never fields one hero twice (spec §11.6 R4-10; the release note carries the
    #: staging check).
    character_uniqueness="match",
    catalog_sync=_catalog_sync,
    native_ranks=_native_ranks,
    native_ladder=NATIVE_LADDER,
    native_rank_rows=_native_rank_rows,
    configure_runtime=_configure_runtime,
    register_jobs=_register_jobs,
    start_jobs=_start_jobs,
    stop_jobs=_stop_jobs,
    collection_handlers={name: _collection_handler(name) for name in _COLLECTION_HANDLERS},
    settings_schema=_settings_schema,
    ingestors={SOURCE_KIND: _decode},
    match_fetchers={SOURCE_KIND: _fetch_match},
    match_searchers={SOURCE_KIND: _search_matches},
    lobby_bot=LobbyBotSpec(
        regions=SERVER_REGIONS, default_region="europe", create=_create_lobby, match_id=_lobby_match_id
    ),
    ingest_status=_ingest_status,
    ingest_client=IngestClient(
        instructions_url="https://deadlock-api.com/ingest-cache",
        installer_url="https://github.com/deadlock-api/deadlock-api-ingest/releases/latest/download/deadlock-api-ingest-setup.exe",
    ),
    dimensions=(AGENT,),
    team_format_presets=(OPEN_6V6, OPEN_4V4),
    flex=False,
    identity_provider=SocialProvider.STEAM,
    short_name="Deadlock",
    #: Published from frontend/public/disciplines/deadlock/icon.png (scripts/publish_discipline_assets.py).
    icon="assets/deadlock/icon.png",
    stat_defs=STAT_DEFS,
    event_types=EVENT_TYPES,
    pick_ban_presets=_pick_ban_presets,
)
