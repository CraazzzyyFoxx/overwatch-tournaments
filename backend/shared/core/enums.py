from collections.abc import Mapping
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Final, Literal


class HeroClass(StrEnum):
    """An Overwatch character's class.

    Player roles and native baseline keys use catalog role ids, not this enum.
    Character classes live in ``catalog.entity.attrs``. Member names are stored
    labels; values are display names.
    ``flex`` is retained only for legacy inputs; no character or player assignment
    has that class.
    """

    tank = "Tank"
    damage = "Damage"
    support = "Support"
    flex = "Flex"

    @property
    def slot_code(self) -> str:
        """Draft/balancer/registration wire spelling: ``tank``/``damage``/``support``/``flex``.

        Identical to the member name -- kept as a named boundary because it is
        the wire/storage contract (``RegistrationRole.role``,
        roster-slot projection keys, the Rust ``tournament_balancer``
        payload), not merely a Python detail.
        """
        return self.name

    @classmethod
    def parse(cls, value: object) -> HeroClass | None:
        """Lenient parse: case-insensitive, accepts ``Enum`` members and the
        canonical name/value (which is also :attr:`slot_code`). No other aliases
        -- this is the strict boundary for the single role vocabulary; a caller
        needing free-text synonyms (e.g. sheet-import value maps) owns that
        mapping itself instead of this parser silently widening it.
        ``None`` for missing/unrecognised input -- never raises.
        """
        if value is None:
            return None
        if isinstance(value, Enum):
            value = value.value
        return cls.__members__.get(str(value).strip().lower())


#: The classes a *hero* can have -- ``HeroClass`` minus ``flex``. Use these
#: wherever the subject is a catalog character's class or a baseline keyed off it,
#: so an admin cannot type a hero as "flex" through an existing endpoint and
#: silently poison ``dominant_roles``, the stat baselines and impact scoring.
HERO_TYPE_CLASSES: Final[tuple[HeroClass, ...]] = (HeroClass.tank, HeroClass.damage, HeroClass.support)
HeroTypeClass = Literal[HeroClass.tank, HeroClass.damage, HeroClass.support]


class RankPlatform(StrEnum):
    """Overwatch competitive platform as exposed by OverFast."""

    pc = "pc"
    console = "console"


class RankDivision(StrEnum):
    """Native Overwatch 2 competitive divisions (OverFast values).

    Stored as a plain string in the DB so future Blizzard additions don't
    require a migration; this enum documents the known values and powers the
    ladder's division+tier -> rank_value table.
    """

    bronze = "bronze"
    silver = "silver"
    gold = "gold"
    platinum = "platinum"
    emerald = "emerald"
    diamond = "diamond"
    master = "master"
    grandmaster = "grandmaster"
    # OverFast labels the top division "ultimate" (in-game "Champion").
    ultimate = "ultimate"


class RankCollectionStatus(StrEnum):
    """Per-battle-tag collection state for the OverFast rank poller."""

    pending = "pending"
    ok = "ok"
    private = "private"
    not_found = "not_found"
    error = "error"
    rate_limited = "rate_limited"
    disabled = "disabled"


class RankCollectionSource(StrEnum):
    """What triggered a rank snapshot."""

    scheduled = "scheduled"
    registration = "registration"
    manual = "manual"


class SubscriptionCheckState(StrEnum):
    """Outcome of one persisted subscription check.

    The first three mirror ``shared.services.subscriptions.SubscriptionState`` (the
    tri-state admission contract). ``error`` exists only in the check log: the
    resolver deliberately answers ``unknown`` and persists nothing when a
    provider strategy throws, so without a distinct log value an outage would be
    indistinguishable from a misconfigured provider.
    """

    active = "active"
    inactive = "inactive"
    unknown = "unknown"
    error = "error"


class SubscriptionCollectionSource(StrEnum):
    """What triggered a subscription check."""

    scheduled = "scheduled"
    registration = "registration"
    check_in = "check_in"
    manual = "manual"
    redeem = "redeem"


class SubscriptionEnforcementStage(StrEnum):
    """The EARLIEST admission gate a subscription requirement blocks at.

    Ordered, not a set: ``registration`` implies check-in too. Requiring a
    subscription to sign up while admitting an unsubscribed player at check-in
    would be incoherent, so there is no "registration only" value to pick wrongly.

    Off is not a member -- that is the registration node's ``require_subscription``
    being false. Same shape as ``require_open_profile`` + ``open_profile_scope``
    in the same table: one flag for whether, one value for how.
    """

    #: Blocks at sign-up (and at check-in). Only the automatically provable part
    #: refuses at sign-up; anything a challenge code could still fix is deferred,
    #: because that field is only offered at check-in.
    registration = "registration"
    #: Blocks at check-in only. Sign-up stays open to everybody, which is the
    #: default: a roster is built at check-in, so that is where the answer matters.
    check_in = "check_in"


class LogStatsName(StrEnum):
    Eliminations = "eliminations"
    FinalBlows = "final_blows"
    Deaths = "deaths"
    AllDamageDealt = "all_damage_dealt"
    BarrierDamageDealt = "barrier_damage_dealt"
    HeroDamageDealt = "hero_damage_dealt"
    HealingDealt = "healing_dealt"
    HealingReceived = "healing_received"
    SelfHealing = "self_healing"
    DamageTaken = "damage_taken"
    DamageBlocked = "damage_blocked"
    DefensiveAssists = "defensive_assists"
    OffensiveAssists = "offensive_assists"
    UltimatesEarned = "ultimates_earned"
    UltimatesUsed = "ultimates_used"
    MultikillBest = "multikill_best"
    Multikills = "multikills"
    SoloKills = "solo_kills"
    ObjectiveKills = "objective_kills"
    EnvironmentalKills = "environmental_kills"
    EnvironmentalDeaths = "environmental_deaths"
    CriticalHits = "critical_hits"
    CriticalHitAccuracy = "critical_hit_accuracy"
    ScopedAccuracy = "scoped_accuracy"
    ScopedCriticalHitAccuracy = "scoped_critical_hit_accuracy"
    ScopedCriticalHitKills = "scoped_critical_hit_kills"
    ShotsFired = "shots_fired"
    ShotsHit = "shots_hit"
    ShotsMissed = "shots_missed"
    ScopedShotsFired = "scoped_shots_fired"
    ScopedShotsHit = "scoped_shots_hit"
    WeaponAccuracy = "weapon_accuracy"
    HeroTimePlayed = "hero_time_played"

    # Derived from kill_feed (parser writes them like any other stat).
    FirstPicks = "first_picks"
    FirstDeaths = "first_deaths"
    UltimateKills = "ultimate_kills"
    SupportKills = "support_kills"

    KD = "kd"  # self calculated
    KDA = "kda"  # self calculated
    DamageDelta = "damage_delta"  # self calculated
    FBE = "fbe"  # self calculated
    DamageFB = "damage_fb"  # self calculated
    Assists = "assists"  # self calculated
    ImpactPoints = "impact_points"  # self calculated (impact formula)
    ImpactRank = "impact_rank"  # self calculated (1 = MVP; absent for an unscored player)
    OverperformanceScore = "overperformance_score"  # self calculated (role x rank-quintile expectation)
    OverperformanceBadge = "overperformance_badge"  # self calculated (1 = above expectations, top of the map)

    # Per-feature impact contributions (segment 0 only): one per ``shared.core.impact.IMPACT_FEATURES`` entry.
    ContribEliminations = "contrib_eliminations"
    ContribFinalBlows = "contrib_final_blows"
    ContribDeaths = "contrib_deaths"
    ContribHeroDamageDealt = "contrib_hero_damage_dealt"
    ContribHealingDealt = "contrib_healing_dealt"
    ContribDamageBlocked = "contrib_damage_blocked"
    ContribDamageTaken = "contrib_damage_taken"
    ContribBarrierDamageDealt = "contrib_barrier_damage_dealt"
    ContribOffensiveAssists = "contrib_offensive_assists"
    ContribDefensiveAssists = "contrib_defensive_assists"
    ContribUltimatesEarned = "contrib_ultimates_earned"
    ContribUltimatesUsed = "contrib_ultimates_used"
    ContribMultikills = "contrib_multikills"
    ContribSoloKills = "contrib_solo_kills"
    ContribObjectiveKills = "contrib_objective_kills"
    ContribEnvironmentalKills = "contrib_environmental_kills"
    ContribFirstPicks = "contrib_first_picks"
    ContribFirstDeaths = "contrib_first_deaths"
    ContribUltimateKills = "contrib_ultimate_kills"
    ContribSupportKills = "contrib_support_kills"


StatDirection = Literal["asc", "desc"]


_log_stats_default_direction: dict[LogStatsName, StatDirection] = dict.fromkeys(LogStatsName, "desc")
_log_stats_default_direction.update(
    {
        LogStatsName.Deaths: "asc",
        LogStatsName.DamageTaken: "asc",
        LogStatsName.EnvironmentalDeaths: "asc",
        LogStatsName.ShotsMissed: "asc",
        LogStatsName.DamageFB: "asc",
        LogStatsName.FirstDeaths: "asc",
        LogStatsName.ImpactRank: "asc",
    }
)

LOG_STATS_DEFAULT_DIRECTION: Final[Mapping[LogStatsName, StatDirection]] = MappingProxyType(
    _log_stats_default_direction
)


def is_ascending_stat(stat: LogStatsName) -> bool:
    return LOG_STATS_DEFAULT_DIRECTION.get(stat, "desc") == "asc"


class TournamentStatus(StrEnum):
    # First phase: the tournament exists and is public, but nothing can be done
    # with it yet. It ends when the REGISTRATION schedule row comes due.
    ANNOUNCEMENT = "announcement"
    REGISTRATION = "registration"
    DRAFT = "draft"
    CHECK_IN = "check_in"
    LIVE = "live"
    PLAYOFFS = "playoffs"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class FlowNodeKind(StrEnum):
    REGISTRATION = "registration"
    FORMATION = "formation"
    STAGE = "stage"
    FILTER = "filter"
    MERGE = "merge"
    SPLIT = "split"
    AGGREGATE = "aggregate"
    LEADERBOARD = "leaderboard"


class FlowNodeStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CHECK_IN = "check_in"
    CLOSED = "closed"
    FORMING = "forming"
    COMPLETED = "completed"
    READY = "ready"
    LIVE = "live"
    PENDING = "pending"
    TENTATIVE = "tentative"
    FINAL = "final"


class FlowResultState(StrEnum):
    TENTATIVE = "tentative"
    FINAL = "final"


class FlowUnit(StrEnum):
    PLAYERS = "players"
    TEAMS = "teams"


class MixStatus(StrEnum):
    DRAFT = "draft"
    BALANCED = "balanced"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MixParticipation(StrEnum):
    MUST_PLAY = "must_play"
    POOL = "pool"
    BENCHED = "benched"


class MixSelfSignup(StrEnum):
    """Who may put themselves on a mix roster, and where they land.

    One column, three states: ``closed`` is no self-signup at all, ``pool``
    seats a self-signed player straight into the pool, ``benched`` parks them
    for the host to promote. A bool plus a destination enum would admit a
    fourth, meaningless pair ("closed, but onto the bench").
    """

    CLOSED = "closed"
    POOL = "pool"
    BENCHED = "benched"


class MixRoleSelectionMode(StrEnum):
    ALL_RANKED = "all_ranked"
    EXPLICIT = "explicit"


class MixRatingMode(StrEnum):
    """How recording a mix match moves the host's rank book.

    ``points`` is the flat ``points_per_win``; ``ranker`` moves each seat by the
    mix ranker (``balancer-service/src/domain/mix_ranker.py``) and balances on
    the effective rating. The hidden rating is kept up to date in both.
    """

    POINTS = "points"
    RANKER = "ranker"


class DraftStatus(StrEnum):
    SETUP = "setup"
    READY = "ready"
    LIVE = "live"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DraftFormat(StrEnum):
    SNAKE = "snake"
    LINEAR = "linear"
    CUSTOM = "custom"


class DraftRoundRule(StrEnum):
    LINEAR = "linear"
    REVERSE = "reverse"
    WEAKEST_FIRST = "weakest_first"
    STRONGEST_FIRST = "strongest_first"
    TEAM_AVG_ASC = "team_avg_asc"
    TEAM_AVG_DESC = "team_avg_desc"


class DraftCaptainOrder(StrEnum):
    """How captains are seeded into draft seats (who picks first)."""

    MANUAL = "manual"  # selection order
    WEAKEST_FIRST = "weakest_first"  # lowest-rated captain picks first
    STRONGEST_FIRST = "strongest_first"  # highest-rated captain picks first
    RANDOM = "random"  # deterministic shuffle (settings_json seed)


class DraftPoolSource(StrEnum):
    BALANCER_BALANCE = "balancer_balance"
    MANUAL = "manual"


class DraftAutopickStrategy(StrEnum):
    BEST_FIT = "best_fit"
    BEST_AVAILABLE = "best_available"
    ROLE_NEED = "role_need"


class DraftPlayerStatus(StrEnum):
    AVAILABLE = "available"
    PICKED = "picked"
    REMOVED = "removed"


class DraftPickStatus(StrEnum):
    UPCOMING = "upcoming"
    ON_CLOCK = "on_clock"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    AUTOPICKED = "autopicked"


class StageType(StrEnum):
    ROUND_ROBIN = "round_robin"
    SINGLE_ELIMINATION = "single_elimination"
    DOUBLE_ELIMINATION = "double_elimination"
    SWISS = "swiss"
    #: Scored by lobby placement and raw score, not head-to-head: its rules are
    #: the stage's ``ffa_*`` columns (``shared.domain.encounter_scoring``).
    FFA_LEAGUE = "ffa_league"
    #: Every round reshuffles the pool into new teams (no ``tournament.team``);
    #: the personal table in ``tournament.player_standing`` decides the playoff.
    INDIVIDUAL_SWISS = "individual_swiss"


class StagePairingMode(StrEnum):
    """How an ``individual_swiss`` round forms its lobbies."""

    SCORE = "score"
    BALANCE = "balance"


class EncounterResultSource(StrEnum):
    """Where an encounter's official result came from.

    ``games`` is the aggregate of the confirmed games and is the only one a
    rule recalculation may overwrite; the other four are decisions and are
    changed only by a reopen. ``host`` -- a mix host or co-host recorded the
    round directly; a decision like the other three.
    """

    GAMES = "games"
    SERIES_CLAIM = "series_claim"
    ADMIN = "admin"
    IMPORT = "import"
    HOST = "host"


class AuditSnapshotScope(StrEnum):
    """What a ``encounter.result_audit`` row's before/after snapshot describes."""

    ENCOUNTER = "encounter"
    GAME = "game"


class StageItemType(StrEnum):
    GROUP = "group"
    BRACKET_UPPER = "bracket_upper"
    BRACKET_LOWER = "bracket_lower"
    SINGLE_BRACKET = "single_bracket"


class StageItemInputType(StrEnum):
    FINAL = "final"
    TENTATIVE = "tentative"
    EMPTY = "empty"


class EncounterResultStatus(StrEnum):
    NONE = "none"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"


class EncounterResultAuditAction(StrEnum):
    """What moved an encounter's result. One row per transition.

    ``confirm``/``reopen`` are admin actions; ``auto_confirm``/``auto_dispute``
    are derived from the captains' series reports, and ``auto_pending`` is the
    first of them arriving while the others are still owed; ``import`` is
    Challonge pulling a remote result in; ``cascade_reset`` is the bracket
    un-playing an encounter whose team slots changed upstream.
    """

    CONFIRM = "confirm"
    REOPEN = "reopen"
    AUTO_CONFIRM = "auto_confirm"
    AUTO_DISPUTE = "auto_dispute"
    AUTO_PENDING = "auto_pending"
    IMPORT = "import"
    CASCADE_RESET = "cascade_reset"
    # Per-map decisions (Vertical 1). Score columns on the audit row carry the
    # GAME's accepted score for these three actions, see EncounterResultAudit.
    GAME_CONFIRM = "game_confirm"
    GAME_CORRECT = "game_correct"
    GAME_CANCEL = "game_cancel"


class MapPoolEntryStatus(StrEnum):
    AVAILABLE = "available"
    PICKED = "picked"
    BANNED = "banned"
    PROTECTED = "protected"


class PickBanActorKind(StrEnum):
    """Who performed a pick-ban board action.

    ``team`` is the only kind that names a participation; the others are the
    engine resolving a step, an organizer overriding one, or a tiebreak.
    """

    TEAM = "team"
    DECIDER = "decider"
    ADMIN = "admin"
    SYSTEM = "system"


class MapVetoSessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EncounterGameState(StrEnum):
    """Lifecycle of one position of a series (``encounter.game``)."""

    PLANNED = "planned"  # position exists, map not chosen yet (freeplay)
    AWAITING_RESULT = "awaiting_result"  # map known; waiting for both captains' claims
    DISPUTED = "disputed"  # two claims that disagree
    CONFIRMED = "confirmed"  # accepted score present
    CANCELLED = "cancelled"  # kept as history after undo/reset; never revived


class EncounterGameResultSource(StrEnum):
    CAPTAIN_AGREEMENT = "captain_agreement"
    ADMIN = "admin"
    ADMIN_LOG = "admin_log"
    HOST = "host"


class VetoSeedSource(StrEnum):
    BRACKET_SLOT = "bracket_slot"
    STANDINGS = "standings"
    #: Neither participation could be seeded; the first slot opens by default.
    FALLBACK_FIRST_SLOT = "fallback_first_slot"
    ADMIN = "admin"


class FirstPickRule(StrEnum):
    HIGHER_SEED = "higher_seed"


class MapVetoMode(StrEnum):
    POOL = "pool"
    SLOTS = "slots"


class FirstBanRotation(StrEnum):
    FIXED = "fixed"
    ALTERNATE = "alternate"
    RESULT_WINNER_FIRST = "result_winner_first"
    RESULT_LOSER_FIRST = "result_loser_first"
    RESULT_LOSER_CHOICE = "result_loser_choice"


class PickBanKind(StrEnum):
    """Which catalog a :class:`PickBanConfig`/session pool draws from."""

    MAP = "map"
    HERO = "hero"


class EncounterStatus(StrEnum):
    COMPLETED = "completed"
    PENDING = "pending"
    OPEN = "open"


class MatchEvent(StrEnum):
    OffensiveAssist = "offensive_assist"
    DefensiveAssist = "defensive_assist"
    UltimateCharged = "ultimate_charged"
    UltimateStart = "ultimate_start"
    UltimateEnd = "ultimate_end"
    HeroSwap = "hero_swap"
    MercyRez = "mercy_rez"
    EchoDuplicateStart = "echo_duplicate_start"
    EchoDuplicateEnd = "echo_duplicate_end"


class RouteTag(StrEnum):
    """Canonical FastAPI route-classification tags.

    app-service, tournament-service, and balancer-service defined this exact
    14-member enum three times (copy-pasted, byte-identical). Services with a
    genuinely different tag set (stats-service, analytics-service) keep their
    own local ``RouteTag`` — only the identical one lives here.
    """

    ENCOUNTER = "🎮 Encounter"
    MATCH = "🎮 Match"
    TEAMS = "🎮 Teams"
    TOURNAMENT = "🏆 Tournament"
    STANDINGS = "🏆 Standings"
    STATISTICS = "📊 Statistics"
    HERO = "🦸 Hero"
    USER = "👤 User"
    LOGS = "📜 Logs"
    ACHIEVEMENTS = "🏅 Achievements"
    MAP = "🗺️ Map"
    GAMEMODE = "🎮 Gamemode"
    UTILITY = "🔧 Utility"
    ANALYTICS = "📈 Analytics"


# Explicit public surface so ``from shared.core.enums import *`` (used by every
# service's ``core/enums.py`` and by ``shared/core/__init__.py``) exports only
# these names and never leaks re-imported stdlib/typing helpers.
__all__ = [
    "HeroClass",
    "HERO_TYPE_CLASSES",
    "HeroTypeClass",
    "RankPlatform",
    "RankDivision",
    "RankCollectionStatus",
    "RankCollectionSource",
    "SubscriptionCheckState",
    "SubscriptionCollectionSource",
    "SubscriptionEnforcementStage",
    "LogStatsName",
    "StatDirection",
    "LOG_STATS_DEFAULT_DIRECTION",
    "is_ascending_stat",
    "TournamentStatus",
    "DraftStatus",
    "DraftFormat",
    "DraftRoundRule",
    "DraftCaptainOrder",
    "DraftPoolSource",
    "DraftAutopickStrategy",
    "DraftPlayerStatus",
    "DraftPickStatus",
    "StageType",
    "EncounterResultSource",
    "AuditSnapshotScope",
    "StageItemType",
    "StageItemInputType",
    "EncounterResultStatus",
    "EncounterResultAuditAction",
    "EncounterGameState",
    "EncounterGameResultSource",
    "MapPoolEntryStatus",
    "PickBanActorKind",
    "MapVetoSessionStatus",
    "VetoSeedSource",
    "FirstPickRule",
    "MapVetoMode",
    "FirstBanRotation",
    "PickBanKind",
    "EncounterStatus",
    "MatchEvent",
    "RouteTag",
]
