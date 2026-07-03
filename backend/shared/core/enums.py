from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal


class HeroClass(StrEnum):
    tank = "Tank"
    damage = "Damage"
    support = "Support"


class RankPlatform(StrEnum):
    """Overwatch competitive platform as exposed by OverFast."""

    pc = "pc"
    console = "console"


class RankRole(StrEnum):
    """Competitive role keys as returned by OverFast (lowercase)."""

    tank = "tank"
    damage = "damage"
    support = "support"


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

    Performance = "performance"  # self calculated
    PerformancePoints = "performance_points"  # self calculated
    KD = "kd"  # self calculated
    KDA = "kda"  # self calculated
    DamageDelta = "damage_delta"  # self calculated
    FBE = "fbe"  # self calculated
    DamageFB = "damage_fb"  # self calculated
    Assists = "assists"  # self calculated


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
    }
)

LOG_STATS_DEFAULT_DIRECTION: Final[Mapping[LogStatsName, StatDirection]] = MappingProxyType(
    _log_stats_default_direction
)


def is_ascending_stat(stat: LogStatsName) -> bool:
    return LOG_STATS_DEFAULT_DIRECTION.get(stat, "desc") == "asc"


class TournamentStatus(StrEnum):
    REGISTRATION = "registration"
    DRAFT = "draft"
    CHECK_IN = "check_in"
    LIVE = "live"
    PLAYOFFS = "playoffs"
    COMPLETED = "completed"
    ARCHIVED = "archived"


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


class DraftRole(StrEnum):
    TANK = "tank"
    DPS = "dps"
    SUPPORT = "support"


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


class MapPoolEntryStatus(StrEnum):
    AVAILABLE = "available"
    PICKED = "picked"
    BANNED = "banned"
    PLAYED = "played"


class MapPickSide(StrEnum):
    HOME = "home"
    AWAY = "away"
    DECIDER = "decider"
    ADMIN = "admin"


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


# Explicit public surface so ``from shared.core.enums import *`` (used by every
# service's ``core/enums.py`` and by ``shared/core/__init__.py``) exports only
# these names and never leaks re-imported stdlib/typing helpers.
__all__ = [
    "HeroClass",
    "RankPlatform",
    "RankRole",
    "RankDivision",
    "RankCollectionStatus",
    "RankCollectionSource",
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
    "DraftRole",
    "DraftPlayerStatus",
    "DraftPickStatus",
    "StageType",
    "StageItemType",
    "StageItemInputType",
    "EncounterResultStatus",
    "MapPoolEntryStatus",
    "MapPickSide",
    "EncounterStatus",
    "EncounterLinkRole",
    "EncounterLinkSlot",
    "MatchEvent",
    "AbilityEvent",
]
