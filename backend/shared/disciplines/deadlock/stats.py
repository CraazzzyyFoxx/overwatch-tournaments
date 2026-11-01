"""Deadlock's per-participant stat vocabulary (integers) and its event types."""

from __future__ import annotations

from shared.disciplines.spec import EventTypeSpec, StatDefSpec

__all__ = ("EVENT_TYPES", "GOLD_SOURCE_STATS", "SNAPSHOT_STATS", "STAT_DEFS")

#: ``EGoldSource`` -> the stat its souls add to; the item and ability sources share one.
GOLD_SOURCE_STATS: dict[int, str] = {
    1: "souls_players",
    2: "souls_lane_creeps",
    3: "souls_neutrals",
    4: "souls_bosses",
    5: "souls_treasure",
    6: "souls_assists",
    7: "souls_denies",
    8: "souls_team_bonus",
    9: "souls_items",
    10: "souls_items",
    11: "souls_items",
    12: "souls_breakables",
    13: "souls_items",
}
#: The ``stats[]`` counters a ``snapshot`` event carries: the time series the match view draws.
SNAPSHOT_STATS = (
    "net_worth",
    "kills",
    "deaths",
    "assists",
    "creep_kills",
    "neutral_kills",
    "denies",
    "player_damage",
    "player_damage_taken",
    "player_healing",
    "boss_damage",
    "level",
)

STAT_DEFS: tuple[StatDefSpec, ...] = (
    StatDefSpec("kills", "Kills"),
    StatDefSpec("deaths", "Deaths"),
    StatDefSpec("assists", "Assists"),
    StatDefSpec("net_worth", "Souls"),
    StatDefSpec("last_hits", "Last hits"),
    StatDefSpec("denies", "Denies"),
    #: A hero level is reached, not accumulated: summing it across games means nothing.
    StatDefSpec("level", "Level", aggregation="max"),
    StatDefSpec("player_damage", "Player damage"),
    StatDefSpec("boss_damage", "Objective damage"),
    StatDefSpec("player_healing", "Healing"),
    StatDefSpec("player_damage_taken", "Damage taken"),
    StatDefSpec("shots_hit", "Shots hit"),
    StatDefSpec("shots_missed", "Shots missed"),
    StatDefSpec("hero_bullets_hit", "Hero hits"),
    StatDefSpec("hero_bullets_hit_crit", "Headshots"),
    StatDefSpec("self_healing", "Self healing"),
    StatDefSpec("teammate_healing", "Ally healing"),
    StatDefSpec("player_barriering", "Barriers given"),
    StatDefSpec("damage_absorbed", "Damage absorbed"),
    StatDefSpec("damage_mitigated", "Damage mitigated"),
    StatDefSpec("heal_prevented", "Healing prevented"),
    StatDefSpec("creep_kills", "Creeps killed"),
    StatDefSpec("neutral_kills", "Neutrals killed"),
    StatDefSpec("souls_players", "Souls from heroes"),
    StatDefSpec("souls_lane_creeps", "Souls from lane creeps"),
    StatDefSpec("souls_neutrals", "Souls from neutrals"),
    StatDefSpec("souls_bosses", "Souls from bosses"),
    StatDefSpec("souls_treasure", "Souls from treasure"),
    StatDefSpec("souls_assists", "Souls from assists"),
    StatDefSpec("souls_denies", "Souls from denies"),
    StatDefSpec("souls_team_bonus", "Souls from team bonuses"),
    StatDefSpec("souls_breakables", "Souls from breakables"),
    StatDefSpec("souls_items", "Souls from items and abilities"),
    StatDefSpec("souls_lost", "Souls lost on death"),
)
EVENT_TYPES: tuple[EventTypeSpec, ...] = (
    EventTypeSpec("kill", "Kill"),
    #: One ``players[].items[]`` entry: a shop item or an ability point spent; ``data.item_id`` tells which.
    EventTypeSpec("purchase", "Purchase"),
    #: One ``stats[]`` sample of a player: ``data`` holds ``SNAPSHOT_STATS`` as they stood at ``t``.
    EventTypeSpec("snapshot", "Snapshot"),
    #: The lane a player was assigned (``data.lane``, ``CMsgLaneColor``), at ``t`` 0.
    EventTypeSpec("lane", "Lane"),
    #: A team's objective destroyed: the owner is the target team, ``data.objective`` its ``ECitadelTeamObjective``.
    EventTypeSpec("objective", "Objective destroyed"),
    #: The mid boss: the team that killed it acts, the team that claimed its buff is the target.
    EventTypeSpec("mid_boss", "Mid boss"),
    #: A player's whole-match damage to one enemy hero (``data.amount``), at the match's end.
    EventTypeSpec("damage", "Damage to a hero"),
    #: A player's whole-match damage to heroes from one source (``data.source``, ``data.amount``), at the match's end.
    EventTypeSpec("damage_source", "Damage by source"),
)
