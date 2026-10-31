"""The Overwatch module. Core reaches it only through ``shared.disciplines``."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from typing import TYPE_CHECKING, Any

from shared.core.social import SocialProvider
from shared.disciplines.overwatch.ladder import NATIVE_LADDER
from shared.disciplines.overwatch.stats import EVENT_TYPES, STAT_DEFS
from shared.disciplines.spec import (
    DimensionSpec,
    DisciplineSpec,
    FormatDimensionSpec,
    FormatRuleSpec,
    RoleSpec,
    TeamFormatPreset,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from shared.catalog_sync import CatalogImageMirror, CatalogSyncProgress
    from shared.disciplines.analytics import AnalyticsExports
    from shared.disciplines.ingest import BoundMatch, DecodeContext
    from shared.disciplines.spec import CollectionHandler
    from shared.domain.achievements.context import EvalContext
    from shared.domain.pick_ban_rules.presets import Preset
    from shared.models.achievements.achievement import AchievementGrain, AchievementRule
    from shared.models.catalog.entity import CatalogEntity
    from shared.models.identity.auth_user import AuthUser
    from shared.schemas.match_doc import MatchDoc

__all__ = ("SPEC",)


async def _catalog_sync(session: AsyncSession, images: CatalogImageMirror, progress: CatalogSyncProgress) -> None:
    # Imported on call: the registry is imported by the pure pick-ban domain, which must not load repositories and an
    # HTTP client to answer "does this game have sides".
    from shared.disciplines.overwatch.catalog_sync import sync_catalog

    await sync_catalog(session, images, progress)


async def _native_ranks(session: AsyncSession, user_ids: Sequence[int]) -> dict[int, dict[str, int]]:
    # Imported on call, like the catalog sync: the snapshot read loads models the pure domain must not.
    from shared.disciplines.overwatch.ranks import native_ranks

    return await native_ranks(session, user_ids)


#: The collection RPCs the collector serves (``collector.handlers.HANDLERS`` holds the bodies).
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
    from shared.disciplines.overwatch.collector import runtime

    runtime.configure(session_factory=session_factory, redis=redis, broker=broker)


def _register_jobs(broker: Any, *, session_factory: Any, redis: Any, logger: Any) -> None:
    # Imported on call, like the catalog sync: the collector pulls in the broker, an HTTP client and the scheduler.
    from shared.disciplines.overwatch.collector.jobs import register_jobs

    register_jobs(broker, session_factory=session_factory, redis=redis, logger=logger)


async def _start_jobs(*, session_factory: Any, redis: Any, logger: Any) -> None:
    from shared.disciplines.overwatch.collector.jobs import start_jobs

    await start_jobs(session_factory=session_factory, redis=redis, logger=logger)


def _stop_jobs() -> Awaitable[None]:
    from shared.disciplines.overwatch.collector.jobs import stop_jobs

    return stop_jobs()


def _collection_handler(name: str) -> CollectionHandler:
    async def handle(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
        from shared.disciplines.overwatch.collector.handlers import HANDLERS

        return await HANDLERS[name](session, user, data)

    return handle


def _achievement_conditions() -> None:
    # Imported on call: the conditions load every SQL query builder of the game, which a service that never
    # evaluates achievements must not pay for. Module import registers them once.
    import shared.disciplines.overwatch.achievements.conditions  # noqa: F401


def _achievement_catalog(workspace_id: int, characters: Sequence[CatalogEntity]) -> list[AchievementRule]:
    from shared.disciplines.overwatch.achievements.catalog import all_default_rules

    return all_default_rules(workspace_id, characters)


async def _achievement_eligible_keys(
    session: AsyncSession, context: EvalContext, grain: AchievementGrain
) -> set[tuple[int, ...]]:
    from shared.disciplines.overwatch.achievements.eligibility import eligible_keys

    return await eligible_keys(session, context, grain)


def _analytics() -> AnalyticsExports:
    # Imported on call: the package loads pandas, scikit-learn, LightGBM and XGBoost, which a service that never runs
    # analytics must not pay for. The module itself is the exports object.
    from shared.disciplines.overwatch import analytics

    return analytics


async def _recompute_baselines(session: AsyncSession, user: AuthUser | None, data: dict[str, Any]) -> object:
    from shared.core.impact import FORMULA_VERSION
    from shared.disciplines.overwatch.baselines import recompute

    return {"rows": await recompute(session, discipline="overwatch"), "formula_version": FORMULA_VERSION}


#: A Workshop CSV reaches the parser as a browser/API upload, a Discord attachment or an administrator's manual upload.
_WORKSHOP_SOURCES = ("upload", "discord", "manual")


def _decode(raw: bytes, ctx: DecodeContext) -> MatchDoc:
    # Imported on call: the decoder needs pandas, which every service loading the registry must not pay for.
    from shared.disciplines.overwatch.ingest import decode

    return decode(raw, ctx)


async def _derive_match(session: AsyncSession, doc: MatchDoc, binding: BoundMatch) -> MatchDoc:
    from shared.disciplines.overwatch.ingest import derive_match

    return await derive_match(session, doc, binding)


def _pick_ban_presets() -> tuple[Preset, ...]:
    # Imported on call: the presets parse their rulesets through the pick-ban domain, which imports this registry.
    from shared.disciplines.overwatch.pick_ban_presets import pick_ban_presets

    return pick_ban_presets()


PLAYER_ROLE = DimensionSpec(
    "player_role",
    "Role",
    "single",
    True,
    # Design-book role hues (tank 209°, damage 337°, support 150°), the same as frontend overwatch/role-hues.css.
    (
        RoleSpec("tank", "Tank", {"icon": "/disciplines/overwatch/roles/tank.svg", "color": "#5da8ef"}),
        RoleSpec("damage", "Damage", {"icon": "/disciplines/overwatch/roles/damage.svg", "color": "#ef6298"}),
        RoleSpec("support", "Support", {"icon": "/disciplines/overwatch/roles/support.svg", "color": "#3fca85"}),
    ),
)

#: Today's built-in 5v5 (ex ``DEFAULT_ROSTER_SLOTS``): one tank, two damage, two support, hard.
ROLE_QUEUE_5V5 = TeamFormatPreset(
    "role_queue_5v5",
    "5v5 role queue",
    5,
    5,
    dimensions=(FormatDimensionSpec("player_role", "enforced"),),
    rules=(
        FormatRuleSpec("player_role", "tank", hard_min=1, hard_max=1),
        FormatRuleSpec("player_role", "damage", hard_min=2, hard_max=2),
        FormatRuleSpec("player_role", "support", hard_min=2, hard_max=2),
    ),
)

#: Balancer solver weights of the three roles (ex ``DEFAULT_ROLE_SETTINGS``) and what each balancer preset changes on
#: them (ex ``ConfigPresets.*.role_settings``): the tank line is the one whose gap and spread are penalized.
BALANCER_ROLE_SETTINGS = {
    "default": {
        "tank": {"impact": 1.4, "line_gap_weight": 0.8, "line_std_weight": 1.5, "mix_weight": 1.0},
        "damage": {"impact": 1.0, "line_gap_weight": 0.0, "line_std_weight": 0.0, "mix_weight": 1.0},
        "support": {"impact": 1.1, "line_gap_weight": 0.0, "line_std_weight": 0.0, "mix_weight": 1.0},
    },
    "HIGH_QUALITY": {"tank": {"line_gap_weight": 0.25, "line_std_weight": 0.75}},
    "PREFERENCE_FOCUSED": {"tank": {"line_gap_weight": 1.0, "line_std_weight": 1.5}},
    "COMBINED": {"tank": {"line_gap_weight": 0.8}},
}


SPEC = DisciplineSpec(
    "overwatch",
    "Overwatch",
    # A map is played attack/defence per round, not per team: no sides.
    (),
    kinds={"character": "Hero", "map": "Map", "mode": "Mode"},
    # Never "flex": flex is a slot without a constraint, not a hero's class.
    character_classes=("tank", "damage", "support"),
    character_uniqueness="team",
    catalog_sync=_catalog_sync,
    native_ranks=_native_ranks,
    native_ladder=NATIVE_LADDER,
    dimensions=(PLAYER_ROLE,),
    team_format_presets=(ROLE_QUEUE_5V5,),
    identity_provider=SocialProvider.BATTLENET,
    stat_defs=STAT_DEFS,
    event_types=EVENT_TYPES,
    # The MVP badge is a stored fact (``overperformance_badge``): no member totals are ranked at read time.
    member_total_stats=(),
    configure_runtime=_configure_runtime,
    register_jobs=_register_jobs,
    start_jobs=_start_jobs,
    stop_jobs=_stop_jobs,
    collection_handlers={
        **{name: _collection_handler(name) for name in _COLLECTION_HANDLERS},
        "impact.recompute_baselines": _recompute_baselines,
    },
    ingestors=dict.fromkeys(_WORKSHOP_SOURCES, _decode),
    derive_match=_derive_match,
    achievement_conditions=_achievement_conditions,
    achievement_catalog=_achievement_catalog,
    achievement_eligible_keys=_achievement_eligible_keys,
    analytics=_analytics,
    pick_ban_presets=_pick_ban_presets,
    balancer_role_settings=BALANCER_ROLE_SETTINGS,
    short_name="OW",
    #: Blizzard's Forge design-system mark (forge.akamaized.net/icons/overwatch.svg), the dark-background variant.
    icon="assets/overwatch/icon.svg",
)
