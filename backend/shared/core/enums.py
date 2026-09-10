from collections.abc import Mapping
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Final, Literal


class HeroClass(StrEnum):
    """A roster role OR a hero's class -- two concepts on one Postgres type.

    ``tank``/``damage``/``support`` mean both things at once, which is why the
    same ``heroclass`` type backs ``overwatch.hero.type``,
    ``matches.stat_baselines.role`` and ``tournament.player.role``. ``flex``
    only ever means the third: a player who holds no fixed role, which is what
    a role-less (all-``flex``) roster shape drafts and balances for. No hero has
    a class of "flex", so the two hero-side columns are narrowed back to
    :data:`HERO_TYPE_CLASSES` / :data:`HeroTypeClass` in the schema layer and by
    CHECK constraints in the database (migration ``heroflex0001``).

    Member NAMES are the stored Postgres labels (SQLAlchemy ``Enum`` default),
    so the DB sees ``flex`` while the Python value is ``"Flex"``.

    THE single role enum for the whole backend (frontend mirror:
    ``PlayerRoleOption`` in ``lib/player-role.ts``). Draft/balancer/registration
    code historically spelled ``damage`` as ``dps`` -- that spelling is a wire
    format, not a second role vocabulary, and lives on as :attr:`slot_code`.
    """

    tank = "Tank"
    damage = "Damage"
    support = "Support"
    flex = "Flex"

    @property
    def slot_code(self) -> str:
        """Draft/balancer/registration wire spelling: ``tank``/``dps``/``support``/``flex``.

        Diverges from the canonical value only for ``damage`` -> ``dps``. This is
        what ``DraftPlayerRole.role``, ``BalancerRegistrationRole.role``,
        ``Tournament.roster_slots_json`` keys and the Rust ``tournament_balancer`` payload
        already persist/expect -- unchanged by this being one enum instead of three.
        """
        return "dps" if self is HeroClass.damage else self.name

    @classmethod
    def from_slot_code(cls, code: str) -> HeroClass:
        """Inverse of :attr:`slot_code`. Raises ``ValueError`` for an unknown code."""
        if code == "dps":
            return cls.damage
        return cls(code.capitalize())

    @classmethod
    def parse(cls, value: object) -> HeroClass | None:
        """Lenient parse: case-insensitive, accepts ``Enum`` members, the canonical
        name/value, and the :attr:`slot_code` spelling. No other aliases --
        this is the strict boundary for the single role vocabulary; a caller
        needing free-text synonyms (e.g. sheet-import value maps) owns that
        mapping itself instead of this parser silently widening it.
        ``None`` for missing/unrecognised input -- never raises.
        """
        if value is None:
            return None
        if isinstance(value, Enum):
            value = value.value
        key = str(value).strip().lower()
        if key in ("damage", "dps"):
            return cls.damage
        if key == "support":
            return cls.support
        if key == "tank":
            return cls.tank
        if key == "flex":
            return cls.flex
        return None


#: The classes a *hero* can have -- ``HeroClass`` minus ``flex``. Use these
#: wherever the subject is ``overwatch.hero.type`` or a baseline keyed off it,
#: so an admin cannot type a hero as "flex" through an existing endpoint and
#: silently poison ``dominant_roles``, the stat baselines and impact scoring.
HERO_TYPE_CLASSES: Final[tuple[HeroClass, ...]] = (HeroClass.tank, HeroClass.damage, HeroClass.support)
HeroTypeClass = Literal[HeroClass.tank, HeroClass.damage, HeroClass.support]


class CatalogEntityType(StrEnum):
    """Catalog entity an alias (or an unresolved-name miss) belongs to.

    Match logs carry map/gamemode/hero names in the reporting client's locale,
    so every catalog entity keeps a list of alternative names it answers to.
    """

    hero = "hero"
    map = "map"
    gamemode = "gamemode"


class RankPlatform(StrEnum):
    """Overwatch competitive platform as exposed by OverFast."""

    pc = "pc"
    console = "console"


class RankDivision(StrEnum):
    """Native Overwatch 2 competitive divisions (OverFast values).

    Stored as a plain string in the DB so future Blizzard additions don't
    require a migration; this enum documents the known values and powers the
    default rank mapping.
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

    Off is not a member -- that is ``registration_form.require_subscription``
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


class LogEventType(StrEnum):
    MatchStart = "match_start"
    MatchEnd = "match_end"
    PlayerJoined = "player_joined"
    RoundStart = "round_start"
    RoundEnd = "round_end"
    SetupComplete = "setup_complete"
    PointProgress = "point_progress"
    ObjectiveUpdated = "objective_updated"
    ObjectiveCaptured = "objective_captured"
    PayloadProgress = "payload_progress"
    PlayerStat = "player_stat"
    Meta = "meta"
    HeroSpawn = "hero_spawn"
    Kill = "kill"
    OffensiveAssist = "offensive_assist"
    DefensiveAssist = "defensive_assist"
    UltimateCharged = "ultimate_charged"
    UltimateStart = "ultimate_start"
    UltimateEnd = "ultimate_end"
    MercyRez = "mercy_rez"
    HeroSwap = "hero_swap"
    EchoDuplicateStart = "echo_duplicate_start"
    EchoDuplicateEnd = "echo_duplicate_end"
    GraviticFlux = "gravitic_flux"
    Earthshatter = "earthshatter"
    ServerLoad = "server_load"
    ChainHook = "chain_hook"


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

    Performance = "performance"  # self calculated
    PerformancePoints = "performance_points"  # self calculated
    KD = "kd"  # self calculated
    KDA = "kda"  # self calculated
    DamageDelta = "damage_delta"  # self calculated
    FBE = "fbe"  # self calculated
    DamageFB = "damage_fb"  # self calculated
    Assists = "assists"  # self calculated
    ImpactPoints = "impact_points"  # self calculated (impact formula)
    ImpactRank = "impact_rank"  # self calculated (1 = MVP)
    OverperformanceScore = "overperformance_score"  # self calculated (role x rank baseline)


StatDirection = Literal["asc", "desc"]


_log_stats_default_direction: dict[LogStatsName, StatDirection] = dict.fromkeys(LogStatsName, "desc")
_log_stats_default_direction.update(
    {
        LogStatsName.Deaths: "asc",
        LogStatsName.DamageTaken: "asc",
        LogStatsName.EnvironmentalDeaths: "asc",
        LogStatsName.ShotsMissed: "asc",
        LogStatsName.DamageFB: "asc",
        LogStatsName.Performance: "asc",
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


class MixStatus(StrEnum):
    DRAFT = "draft"
    BALANCED = "balanced"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MixParticipation(StrEnum):
    MUST_PLAY = "must_play"
    POOL = "pool"
    BENCHED = "benched"


class MixRoleSelectionMode(StrEnum):
    ALL_RANKED = "all_ranked"
    EXPLICIT = "explicit"


class CasualTeamSide(StrEnum):
    HOME = "home"
    AWAY = "away"


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
    are derived from the two captain reports; ``import`` is Challonge pulling a
    remote result in; ``cascade_reset`` is the bracket un-playing an encounter
    whose team slots changed upstream.
    """

    CONFIRM = "confirm"
    REOPEN = "reopen"
    AUTO_CONFIRM = "auto_confirm"
    AUTO_DISPUTE = "auto_dispute"
    IMPORT = "import"
    CASCADE_RESET = "cascade_reset"


class MapPoolEntryStatus(StrEnum):
    AVAILABLE = "available"
    PICKED = "picked"
    BANNED = "banned"
    PLAYED = "played"
    PROTECTED = "protected"


class MapPickSide(StrEnum):
    HOME = "home"
    AWAY = "away"
    DECIDER = "decider"
    ADMIN = "admin"


class MapVetoSessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VetoSeedSource(StrEnum):
    BRACKET_SLOT = "bracket_slot"
    STANDINGS = "standings"
    FALLBACK_HOME = "fallback_home"
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


class PickBanNoRepeatScope(StrEnum):
    """Cross-round BAN memory rule for :class:`EncounterPickBanLedger`
    exclusion. Protects are never recorded there, so they neither exclude nor
    are excluded by anything under any scope.

    ``NONE``: no cross-round memory (today's flat/slot veto behavior).
    ``ENCOUNTER``: an item banned by EITHER side, anywhere earlier in this
    encounter's series, is excluded from every later round's pool.
    ``ENCOUNTER_SAME_SIDE``: excluded only for the side that banned it; the
    opponent may still target it.
    """

    NONE = "none"
    ENCOUNTER = "encounter"
    ENCOUNTER_SAME_SIDE = "encounter_same_side"


class MatchSource(StrEnum):
    """Provenance of a :class:`~shared.models.matches.match.Match` row.

    ``LOG_PARSER``: written by ``MatchLogFlow`` from an uploaded OW log —
    ``time``/``log_name`` are populated, kill-feed/stats may follow.
    ``CAPTAIN_REPORT``: written from a per-map dual captain confirmation with
    no log — ``time``/``log_name`` stay NULL, there is no kill-feed/stats.
    """

    LOG_PARSER = "log_parser"
    CAPTAIN_REPORT = "captain_report"


class EncounterStatus(StrEnum):
    COMPLETED = "completed"
    PENDING = "pending"
    OPEN = "open"


class EncounterLinkRole(StrEnum):
    """Role of the source encounter relative to the target encounter."""

    WINNER = "winner"
    LOSER = "loser"


class EncounterLinkSlot(StrEnum):
    """Which slot in the target encounter this link fills."""

    HOME = "home"
    AWAY = "away"


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


class AbilityEvent(StrEnum):
    PrimaryFire = "Primary Fire"
    SecondaryFire = "Secondary Fire"
    Ability1 = "Ability 1"
    Ability2 = "Ability 2"
    Ultimate = "Ultimate"
    Melee = "Melee"
    Crouch = "Crouch"


class RouteTag(StrEnum):
    """Canonical FastAPI route-classification tags.

    app-service, tournament-service, and balancer-service defined this exact
    14-member enum three times (copy-pasted, byte-identical). Services with a
    genuinely different tag set (parser-service, analytics-service) keep their
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
    "CatalogEntityType",
    "RankPlatform",
    "RankDivision",
    "RankCollectionStatus",
    "RankCollectionSource",
    "SubscriptionCheckState",
    "SubscriptionCollectionSource",
    "SubscriptionEnforcementStage",
    "LogEventType",
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
    "StageItemType",
    "StageItemInputType",
    "EncounterResultStatus",
    "EncounterResultAuditAction",
    "MapPoolEntryStatus",
    "MapPickSide",
    "MapVetoSessionStatus",
    "VetoSeedSource",
    "FirstPickRule",
    "MapVetoMode",
    "FirstBanRotation",
    "PickBanKind",
    "PickBanNoRepeatScope",
    "EncounterStatus",
    "EncounterLinkRole",
    "EncounterLinkSlot",
    "MatchEvent",
    "AbilityEvent",
    "MatchSource",
    "RouteTag",
]
