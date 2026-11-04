"""What the code knows about a discipline, beside what the DB stores.

Pure declarations and validation, no DB: the pick-ban engine, ruleset validator and game writer read it, and none may do
IO to answer "does this game have sides". The role ontology and the team-format presets declared here are projected into
``catalog.role_dimension``/``catalog.role`` at startup (``shared.services.ontology``) and copied into
``roster.team_format`` (``shared.services.team_format``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pydantic import BaseModel
    from sqlalchemy.ext.asyncio import AsyncSession

    from shared.catalog_sync import CatalogImageMirror, CatalogSyncProgress
    from shared.disciplines.analytics import AnalyticsExports
    from shared.disciplines.ingest import Decoder, DeriveMatch, MatchFetcher, MatchSearcher
    from shared.disciplines.lobby import IngestClient, IngestStatusSource, LobbyBotSpec
    from shared.domain.achievements.context import EvalContext
    from shared.domain.pick_ban_rules.presets import Preset
    from shared.models.achievements.achievement import AchievementGrain, AchievementRule
    from shared.models.catalog.entity import CatalogEntity
    from shared.models.identity.auth_user import AuthUser

#: Pull the module's catalog source into ``catalog.entity`` (commits itself), reporting its stages on the progress.
CatalogSync = Callable[["AsyncSession", "CatalogImageMirror", "CatalogSyncProgress"], Awaitable[None]]

#: A game's native rank layer: ``players.user`` ids -> ``{user_id: {role code: rank}}``, the best rank a player
#: holds per role of the rated dimension on the game's own ladder; the core places it on a division grid. Reads only.
NativeRanks = Callable[["AsyncSession", Sequence[int]], Awaitable[dict[int, dict[str, int]]]]

#: The admin rank overview's SQL twin of ``native_ranks``: ``(members CTE with player_id, CTE name suffix)`` -> a CTE of
#: the newest ranked snapshot per account and role with the columns ``user_id, handle (the account label), platform,
#: role, rank_value, division, tier, captured_at, snapshot_id``. ``None``: the core's OverFast twin.
NativeRankRows = Callable[[Any, str], Any]

#: A collection RPC the module serves (``rank.collect``): ``(session, caller or None for a public read, gateway data)``.
#: The handler validates its own payload and authorizes the caller; it returns what the RPC envelope serializes.
CollectionHandler = Callable[["AsyncSession", "AuthUser | None", dict[str, Any]], Awaitable[object]]

#: ``configure_runtime(broker, *, session_factory, redis)``: give the module's collection handlers the process wiring
#: (DB sessions, Redis, broker) in a process that registers no consumers and starts no schedule (the RPC process).
ConfigureRuntime = Callable[..., None]

#: ``register_jobs(broker, *, session_factory, redis, logger)``: bind the module's consumers on the worker broker.
RegisterJobs = Callable[..., None]

#: ``start_jobs(*, session_factory, redis, logger)``: declare the module's dead-letter queues, start its schedules and
#: clients, once the broker is connected.
StartJobs = Callable[..., Awaitable[None]]

#: ``stop_jobs()``: the call itself stops the module's schedules; awaiting the result releases its clients. The worker
#: calls it when shutdown begins and awaits it once consumers have drained.
StopJobs = Callable[[], Awaitable[None]]

#: ``settings_schema(key)``: the model a write to one of the module's own ``Settings`` keys is validated against
#: (imported on call), ``None`` for a key the module does not own.
SettingsSchema = Callable[[str], "type[BaseModel] | None"]

#: ``achievement_conditions()``: import the module's leaf conditions, which register themselves with
#: ``shared.domain.achievements.registry`` under the module's code. Imports its own implementation only when called.
AchievementConditions = Callable[[], None]

#: ``achievement_catalog(workspace_id, characters)``: the module's built-in rules for one workspace, each carrying its
#: own ``discipline`` and, for hero rules, the linked ``entity_id`` of one of ``characters``.
AchievementCatalog = Callable[[int, Sequence["CatalogEntity"]], list["AchievementRule"]]

#: ``achievement_eligible_keys(session, context, grain)``: every key a rule of ``grain`` could award in
#: ``context.workspace_id`` for this discipline - the universe ``NOT`` complements against.
AchievementEligibleKeys = Callable[["AsyncSession", "EvalContext", "AchievementGrain"], Awaitable[set[tuple[int, ...]]]]

#: ``analytics()``: the module's analytics package itself (features, models, canonical scale), imported only when called -
#: it loads pandas and the estimators. The value satisfies ``shared.domain.analytics.AnalyticsExports`` structurally.
AnalyticsModule = Callable[[], "AnalyticsExports"]

__all__ = (
    "AchievementCatalog",
    "AchievementConditions",
    "AchievementEligibleKeys",
    "AnalyticsModule",
    "CATALOG_KINDS",
    "CatalogSync",
    "CollectionHandler",
    "ConfigureRuntime",
    "DimensionSpec",
    "DisciplineSpec",
    "EventTypeSpec",
    "FormatDimensionSpec",
    "FormatRuleSpec",
    "NativeRanks",
    "NativeRankRows",
    "NativeTier",
    "RegisterJobs",
    "RoleSpec",
    "SettingsSchema",
    "StartJobs",
    "StopJobs",
    "StatAggregation",
    "StatDefSpec",
    "StatFormat",
    "TeamFormatPreset",
)

#: The core's catalog vocabulary: ``catalog.entity.kind`` and every kind-constant column spell these and
#: nothing else. What a kind is called in a game's UI is the module's label, not a new kind.
CATALOG_KINDS: tuple[str, ...] = ("character", "map", "mode")


SelectionMode = Literal["single", "multi"]
DimensionMode = Literal["off", "informational", "preference", "enforced"]
StatFormat = Literal["integer", "decimal", "percent", "duration"]
StatAggregation = Literal["sum", "max", "min", "avg", "last"]


@dataclass(frozen=True, slots=True)
class StatDefSpec:
    code: str
    name: str
    value_format: StatFormat = "integer"
    aggregation: StatAggregation = "sum"
    group: str | None = None


@dataclass(frozen=True, slots=True)
class EventTypeSpec:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class RoleSpec:
    """A role the module declares: projected into ``catalog.role`` with ``workspace_id IS NULL``.

    ``attrs`` carries presentation (``icon``, ``color``) into ``catalog.role.attrs``; it never confers membership.
    """

    code: str
    name: str
    attrs: Mapping[str, str | None] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class DimensionSpec:
    """One axis of a game's roles: ``single``/``multi``, and whether ranks hang off it."""

    code: str
    name: str
    selection_mode: SelectionMode
    rated: bool
    roles: tuple[RoleSpec, ...]


@dataclass(frozen=True, slots=True)
class FormatDimensionSpec:
    dimension: str
    mode: DimensionMode
    player_min_assignments: int | None = None
    player_max_assignments: int | None = None


@dataclass(frozen=True, slots=True)
class FormatRuleSpec:
    """A quota on one role. ``None`` is "no rule", never zero."""

    dimension: str
    role: str
    hard_min: int | None = None
    hard_max: int | None = None
    recommended_min: int | None = None
    recommended_max: int | None = None
    include_descendants: bool = True


@dataclass(frozen=True, slots=True)
class TeamFormatPreset:
    """A team format the module offers; an owner gets a copy, never a reference."""

    code: str
    name: str
    starter_min: int
    starter_max: int
    substitute_min: int = 0
    substitute_max: int = 0
    dimensions: tuple[FormatDimensionSpec, ...] = ()
    rules: tuple[FormatRuleSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class NativeTier:
    """One sub-tier of a game's native ladder, numbered 1 from the top.

    ``native_division``/``native_tier`` are the names the game's rank source reports. ``native_tier`` is ``None`` for an
    unsplit tier (LoL apex).
    """

    number: int
    slug: str
    name: str
    rank_min: int
    rank_max: int | None
    icon_url: str
    native_division: str
    native_tier: int | None


@dataclass(frozen=True, slots=True)
class DisciplineSpec:
    code: str
    name: str
    #: Side codes a game of this discipline starts on, in declaration order; ``()`` when the game has no sides. A
    #: ``side_pick`` step is legal only when this has exactly as many entries as the game has participants.
    sides: tuple[str, ...] = ()
    #: The catalog kinds this game has, each with its UI label ("Hero", "Champion").
    kinds: dict[str, str] = field(default_factory=dict, hash=False)
    #: Allowed ``attrs.class`` values of a ``character``; ``()`` leaves the class unchecked.
    character_classes: tuple[str, ...] = ()
    catalog_sync: CatalogSync | None = field(default=None, compare=False)
    #: Where a player's rank on the game's own ladder comes from; ``None`` when the organiser enters ranks.
    native_ranks: NativeRanks | None = field(default=None, compare=False)
    #: The game's own ladder, top tier first; ``()`` when the organiser enters ranks.
    native_ladder: tuple[NativeTier, ...] = ()
    #: See ``NativeRankRows``; only a module with ``native_ranks`` declares it.
    native_rank_rows: NativeRankRows | None = field(default=None, compare=False)
    #: The role ontology; exactly one dimension is ``rated``.
    dimensions: tuple[DimensionSpec, ...] = ()
    #: Team-format presets; the first is what an owner without a format of its own gets.
    team_format_presets: tuple[TeamFormatPreset, ...] = ()
    #: Whether the game has open slots and Full flex players -- one flag, both meanings. ``False``: a format's open
    #: starters go to the single rated role (``shared.domain.team_format.slot_shape``) and nobody may be Full flex.
    flex: bool = True
    #: Whether one hero may be played twice (spec §11.2): ``match`` -- once per match, ``team`` -- once per team,
    #: ``none`` -- freely. Hero pick steps exist only for ``match`` games (an entry per item per round already makes a
    #: picked hero unavailable to both teams); an unknown game says ``none``.
    character_uniqueness: Literal["match", "team", "none"] = "none"
    #: The provider used for default form identities, roster names and log matching.
    identity_provider: str | None = None
    #: Projected SMALLINT dictionaries; historical definitions are deactivated, never deleted.
    stat_defs: tuple[StatDefSpec, ...] = ()
    event_types: tuple[EventTypeSpec, ...] = ()
    #: The whole-match member totals the game's match renderer ranks the viewer against (stat codes of ``stat_defs``);
    #: user-scoped match reads ship only these.
    member_total_stats: tuple[str, ...] = ()
    #: Process lifecycle hooks (optional plain callables): ``configure_runtime`` wires the collection handlers (every
    #: process serving them), ``register_jobs`` binds consumers on the worker's broker, ``start_jobs`` declares the
    #: module's dead-letter queues and starts schedules and clients, ``stop_jobs`` stops them. A worker runs only the selected
    #: disciplines' hooks, so a game without background jobs triggers none.
    configure_runtime: ConfigureRuntime | None = field(default=None, compare=False)
    register_jobs: RegisterJobs | None = field(default=None, compare=False)
    start_jobs: StartJobs | None = field(default=None, compare=False)
    stop_jobs: StopJobs | None = field(default=None, compare=False)
    #: RPC suffix (``rank.collect``) -> handler for the collection operations the module serves.
    collection_handlers: dict[str, CollectionHandler] = field(default_factory=dict, compare=False, hash=False)
    #: The models of the module's own ``Settings`` keys (``shared.schemas.settings.settings_schema`` asks it).
    settings_schema: SettingsSchema | None = field(default=None, compare=False)
    #: Raw producers the module decodes: source kind -> ``decode(raw, ctx)``. ``shared.disciplines.INGESTORS`` keys
    #: them by ``(code, kind)``; a kind not listed here is unsupported, never routed to another producer.
    ingestors: dict[str, Decoder] = field(default_factory=dict, compare=False, hash=False)
    #: Producers stats core can pull a match from by external id: source kind -> ``fetch(external_id) -> bytes``, the
    #: bytes ``ingestors[kind]`` decodes. A kind not listed here cannot be imported by id (``unsupported_ingestor``).
    match_fetchers: dict[str, MatchFetcher] = field(default_factory=dict, compare=False, hash=False)
    #: Producers stats core can find a pickup mix round's match in by its players: source kind (one of
    #: ``match_fetchers``) -> ``search(query) -> candidates``. The id it settles on is fetched by that kind.
    match_searchers: dict[str, MatchSearcher] = field(default_factory=dict, compare=False, hash=False)
    #: The module's bot lobby for a pickup mix (a bot opens the in-game lobby and reports its match id); ``None`` when
    #: the game has none.
    lobby_bot: LobbyBotSpec | None = field(default=None, compare=False)
    #: Whether players' own clients upload their matches (what ``match_searchers`` depends on); ``None`` when unknown.
    ingest_status: IngestStatusSource | None = field(default=None, compare=False)
    #: Where a player gets the client ``ingest_status`` asks about; ``None`` when the game names none.
    ingest_client: IngestClient | None = field(default=None, compare=False)
    #: Facts that need the bound match (baselines, registration ranks); ``None`` when nothing derives after binding.
    derive_match: DeriveMatch | None = field(default=None, compare=False)
    #: Achievement kernel hooks, all lazy and all ``None`` for a game with no conditions (LoL): a missing hook is
    #: unsupported, never an empty set (a ``NOT`` over an empty universe would otherwise be vacuous).
    achievement_conditions: AchievementConditions | None = field(default=None, compare=False)
    achievement_catalog: AchievementCatalog | None = field(default=None, compare=False)
    achievement_eligible_keys: AchievementEligibleKeys | None = field(default=None, compare=False)
    #: The analytics module: ``None`` for a game with no features or models (LoL), which is unsupported by
    #: analytics - never served another game's module.
    analytics: AnalyticsModule | None = field(default=None, compare=False)
    #: ``pick_ban_presets()``: the module's built-in pick/ban rulesets, imported only when called; ``None`` for a game
    #: that offers none.
    pick_ban_presets: Callable[[], tuple[Preset, ...]] | None = field(default=None, compare=False)
    #: Balancer solver role weights (``impact``, ``line_gap_weight``, ``line_std_weight``, ``mix_weight``) by preset:
    #: ``"default"`` seeds every run of this game, a named balancer preset's entries are partial overrides it applies.
    #: A role (or game) without an entry weighs neutrally.
    balancer_role_settings: Mapping[str, Mapping[str, Mapping[str, float]]] = field(
        default_factory=dict, compare=False, hash=False
    )
    #: The game's short mark ("OW"): the monogram a ``GameMark`` draws when there is no icon. Empty falls back to
    #: ``name`` on the wire.
    short_name: str = ""
    #: The game's official icon as an ``assets/<code>/icon.<svg|png|webp>`` object key, published from
    #: ``frontend/public/disciplines/<code>/`` by ``scripts/publish_discipline_assets.py``; the descriptor serves its
    #: public URL. ``None``: the monogram is drawn.
    icon: str | None = None

    @property
    def rated_dimension(self) -> DimensionSpec:
        rated = [dimension for dimension in self.dimensions if dimension.rated]
        if len(rated) != 1:
            raise LookupError(
                f"discipline {self.code!r} declares {len(rated)} rated dimensions; exactly one is required (D32)"
            )
        return rated[0]

    def preset(self, code: str | None = None) -> TeamFormatPreset:
        """The preset called ``code``; ``None`` is the module's default, its first."""
        if not self.team_format_presets:
            raise LookupError(f"discipline {self.code!r} declares no team-format preset")
        if code is None:
            return self.team_format_presets[0]
        for preset in self.team_format_presets:
            if preset.code == code:
                return preset
        raise LookupError(f"discipline {self.code!r} has no team-format preset {code!r}")

    def validate_attrs(self, kind: str, attrs: Mapping[str, object]) -> None:
        """Reject catalog values that the public projections cannot read; absent optional keys use defaults."""
        if kind == "character" and self.character_classes and attrs.get("class") not in self.character_classes:
            raise ValueError(f"attrs.class must be one of: {', '.join(self.character_classes)}")
        if "color" in attrs and not isinstance(attrs["color"], str):
            raise ValueError("attrs.color must be a string")
        if "in_competitive" in attrs and not isinstance(attrs["in_competitive"], bool):
            raise ValueError("attrs.in_competitive must be a boolean")
