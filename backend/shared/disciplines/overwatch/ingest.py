"""The Workshop CSV decoder and Overwatch's post-binding derivation.

``decode`` turns the bytes of one finished Workshop log into a canonical ``MatchDoc`` of keyed facts and typed
events. It is pure CPU (no session, S3 client or roster callback) and
creates no alias, player or row: a hero it cannot resolve is handed on under its log spelling so the one semantic
validator reports every miss, and an unresolvable map/mode raises ``DecodeError`` carrying both misses.

``derive_match`` adds the facts that need what only binding knows -- the active baselines and each seat's rank
quintile (``rank_quintiles``): the ``impact_v2`` facts ``impact_points``, ``impact_rank``, ``overperformance_score``
and, for the whole map, ``overperformance_badge`` and ``contrib_*`` (design 2026-10-31). It runs on decoded documents
only; a producer's own document is never derived twice.

The pandas numerics are frozen. Participants are numbered in the order the document lists them and heroes in catalog
id order, so every reduction sums in a fixed order; every rank is computed in ``derive_match``'s scorer.
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Callable
from datetime import datetime

import pandas as pd
from loguru import logger
from pydantic import ValidationError

from shared.core import impact as impact_consts
from shared.core import impact_weights
from shared.core.enums import HeroClass, LogStatsName, MatchEvent
from shared.core.social import SocialProvider
from shared.disciplines.ingest import BoundMatch, DecodeContext, DecodeError
from shared.disciplines.overwatch import PLAYER_ROLE, baselines, impact
from shared.disciplines.overwatch.enums import LogEventType
from shared.disciplines.overwatch.event_models import KillEvent, MatchEventRow, PlayerStatRow
from shared.disciplines.overwatch.rank_quintiles import match_quintiles
from shared.disciplines.overwatch.settings import settings
from shared.schemas.match_doc import IngestIssue, MatchDoc, MatchDocError

__all__ = ("decode", "derive_match", "placements")

_COLUMNS = ["event_type", "time", "data", "round_number"]
_LOG_EVENT_TYPE_BY_VALUE = {member.value: member for member in LogEventType}
#: Log row types that become typed events (everything but kills, which carry their own payload).
_EVENT_TYPES = {LogEventType[name.name]: name for name in MatchEvent}
#: Rows naming a participant: the first columns are (team, player) in these positions.
_TEAMED_EVENTS = frozenset(
    {
        LogEventType.OffensiveAssist,
        LogEventType.DefensiveAssist,
        LogEventType.UltimateCharged,
        LogEventType.UltimateStart,
        LogEventType.UltimateEnd,
        LogEventType.MercyRez,
        LogEventType.HeroSwap,
        LogEventType.EchoDuplicateStart,
        LogEventType.EchoDuplicateEnd,
    }
)
_STAT_BY_CODE = {stat.value: stat for stat in LogStatsName}
_DERIVED_AFTER_BINDING = frozenset(
    stat.value
    for stat in (
        LogStatsName.ImpactPoints,
        LogStatsName.ImpactRank,
        LogStatsName.OverperformanceScore,
        LogStatsName.OverperformanceBadge,
        *impact_consts.CONTRIBUTION_STATS.values(),
    )
)
_HOME, _AWAY = "home", "away"


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


class _Log:
    """The rows of one Workshop log, indexed by row type, with the round each row belongs to."""

    def __init__(self, lines: list[str], label: str) -> None:
        self.label = label
        self.started_at: datetime | None = None
        self.df = self._parse(lines)
        self._by_type = {} if self.df.empty else dict(iter(self.df.groupby("event_type", sort=False)))

    def _parse(self, lines: list[str]) -> pd.DataFrame:
        cap = settings().max_match_log_lines
        if len(lines) > cap:
            raise DecodeError("match_log_too_large", f"Match log exceeds the maximum of {cap} lines")
        valid_lines = [line for line in lines if line.strip()]
        if not valid_lines:
            logger.warning(f"Match log {self.label} has no valid lines.")
            return _empty()

        parsed: list[tuple[LogEventType, float, list[str]]] = []
        for line, row_parts in zip(valid_lines, csv.reader(valid_lines), strict=True):
            if len(row_parts) < 3:
                logger.warning(f"Skipping malformed row in {self.label}: {line}")
                continue
            raw_event_type = row_parts[1].strip()
            if raw_event_type.lower() == "meta":
                continue
            event_type = _LOG_EVENT_TYPE_BY_VALUE.get(raw_event_type)
            if event_type is None:
                logger.warning(f"Skipping row with unknown event type '{raw_event_type}' in {self.label}")
                continue
            try:
                time = float(row_parts[2])
            except ValueError:
                logger.warning(f"Skipping row with invalid time '{row_parts[2]}' in {self.label}")
                continue
            if event_type == LogEventType.MercyRez and not (len(row_parts) > 4 and row_parts[4].strip()):
                # A revive no Mercy cast (Anran's) is logged as mercy_rez with an empty reviver: no participant and
                # no Mercy resurrect, so the row says nothing the log can keep.
                logger.warning(f"Skipping resurrection without a reviver in {self.label}: {line}")
                continue
            if event_type == LogEventType.MatchStart and self.started_at is None:
                self.started_at = _aware(row_parts[0])
            parsed.append((event_type, time, row_parts[3:]))

        if not parsed:
            logger.warning(f"Match log {self.label} resulted in an empty DataFrame.")
            return _empty()
        df = pd.DataFrame(parsed, columns=["event_type", "time", "data"])
        df["round_number"] = (df["event_type"] == LogEventType.RoundStart).cumsum()
        return df

    def rows(self, event_type: LogEventType) -> pd.DataFrame:
        return self._by_type.get(event_type, _empty())

    def validate(self) -> None:
        if self.df.empty:
            raise DecodeError("match_log_empty", "Match log is empty or unparseable.")
        if self.rows(LogEventType.MatchEnd).empty:
            raise DecodeError("match_not_finished", "MatchEnd event missing")

    def start(self) -> list[str]:
        starts = self.rows(LogEventType.MatchStart)
        if starts.empty or len(starts.iloc[0]["data"]) < 4:
            raise DecodeError("match_log_corrupt", "MatchStart event missing")
        return starts.iloc[0]["data"]

    def teams(self) -> dict[str, list[str]]:
        """Home then away, each in first-seen order; an endpoint of any event counts even with no PlayerStat row."""
        data = self.start()
        names = {data[2]: _HOME, data[3]: _AWAY}
        if len(names) != 2:
            raise DecodeError("match_log_corrupt", "MatchStart declares the same name for both teams")
        teams: dict[str, list[str]] = {_HOME: [], _AWAY: []}
        side: dict[str, str] = {}

        def add(name: str, declared: str) -> None:
            if not name:
                raise DecodeError("match_log_corrupt", f"A player of team {declared!r} has an empty name")
            if declared not in names:
                home, away = names
                raise DecodeError(
                    "match_log_corrupt",
                    f"Player {name!r} is on team {declared!r}, but MatchStart declares only {home!r} and {away!r}",
                )
            team = names[declared]
            if name in side and side[name] != team:
                raise DecodeError("match_log_corrupt", f"Player {name!r} appears on both teams")
            side[name] = team
            if name not in teams[team]:
                teams[team].append(name)

        for row in self.df.itertuples(index=False):
            data, kind = row.data, row.event_type
            if kind == LogEventType.PlayerJoined and len(data) >= 2:
                add(data[0], data[1])
            elif kind == LogEventType.PlayerStat and len(data) >= 4:
                add(data[2], data[1])
            elif kind == LogEventType.Kill and len(data) >= 6:
                add(data[1], data[0])
                add(data[4], data[3])
            elif kind in _TEAMED_EVENTS and len(data) >= 3:
                add(data[1], data[0])
                if kind == LogEventType.MercyRez and len(data) > 4 and data[4]:
                    add(data[4], data[0])
        return teams

    def score_and_time(self) -> tuple[float, int, int]:
        end = self.rows(LogEventType.MatchEnd).iloc[0]
        return float(end["time"]), int(end["data"][1]), int(end["data"][2])


def _aware(text: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def placements(home: int, away: int) -> tuple[int, int]:
    """Higher observed score places first; equal scores share first place."""
    if home == away:
        return 1, 1
    return (1, 2) if home > away else (2, 1)


class _Heroes:
    """Log spelling -> canonical code, and a stable integer per code in catalog id order for the pandas pivots."""

    def __init__(self, ctx: DecodeContext) -> None:
        self._characters = ctx.characters
        self.order = {code: index for index, code in enumerate(ctx.attrs)}
        self.types: dict[int, HeroClass] = {}
        for code, attrs in ctx.attrs.items():
            hero_class = HeroClass.__members__.get(str(attrs.get("class")))
            if hero_class is not None:
                self.types[self.order[code]] = hero_class

    def code(self, name: str) -> str:
        return self._characters.get(name, name)

    def index(self, code: str) -> int:
        return self.order.setdefault(code, len(self.order))

    def codes(self) -> dict[int, str]:
        return {index: code for code, index in self.order.items()}


def _kills(log: _Log, pid_of: dict[str, int], heroes: _Heroes) -> list[tuple[impact.KillRow, str, str]]:
    kills = []
    for row in log.rows(LogEventType.Kill).sort_values(by="time", kind="stable").itertuples(index=False):
        kill = KillEvent.from_data(row.data)
        attacker_hero, victim_hero = heroes.code(kill.attacker_hero), heroes.code(kill.victim_hero)
        kills.append(
            (
                impact.KillRow(
                    t=float(row.time),
                    segment=int(row.round_number),
                    actor_member_id=pid_of[kill.attacker],
                    target_member_id=pid_of[kill.victim],
                    related_entity_id=heroes.index(victim_hero),
                    entity_id=heroes.index(attacker_hero),
                    data={
                        "fight": 0,
                        "ability": kill.ability.value if kill.ability is not None else None,
                        "damage": kill.damage,
                        "is_critical_hit": kill.is_critical_hit,
                        "is_environmental": kill.is_environmental,
                    },
                ),
                attacker_hero,
                victim_hero,
            )
        )
    impact.assign_fights([kill for kill, _, _ in kills])
    return kills


Emit = Callable[[LogStatsName, int, int, int | None, float], None]


def _derived(df: pd.DataFrame, emit: Emit) -> None:
    """KD/KDA/... for a pivot; adds its columns to ``df``."""
    for stat_col in (
        LogStatsName.Eliminations,
        LogStatsName.Deaths,
        LogStatsName.OffensiveAssists,
        LogStatsName.DefensiveAssists,
        LogStatsName.HeroDamageDealt,
        LogStatsName.DamageTaken,
        LogStatsName.FinalBlows,
        LogStatsName.DamageBlocked,
        LogStatsName.HealingDealt,
    ):
        if stat_col not in df.columns:
            df[stat_col] = 0.0

    df["KD"] = df[LogStatsName.Eliminations] / df[LogStatsName.Deaths].replace(0, 1)
    df["Assists"] = df[LogStatsName.OffensiveAssists] + df[LogStatsName.DefensiveAssists]
    df["KDA"] = (df[LogStatsName.Eliminations] + df["Assists"]) / df[LogStatsName.Deaths].replace(0, 1)
    df["DamageDelta"] = df[LogStatsName.HeroDamageDealt] - df[LogStatsName.DamageTaken]
    df["FBE"] = df[LogStatsName.FinalBlows] / df[LogStatsName.Eliminations].replace(0, 1)
    df["DamageFB"] = df[LogStatsName.HeroDamageDealt] / df[LogStatsName.FinalBlows].replace(0, 1)

    def emit_column(column: str, stat: LogStatsName, frame: pd.DataFrame) -> None:
        for r in frame[["player_id", "round", "hero_id", column]].to_dict(orient="records"):
            emit(stat, r["player_id"], r["round"], r.get("hero_id"), r[column])

    for column, stat in (
        ("KD", LogStatsName.KD),
        ("KDA", LogStatsName.KDA),
        ("DamageDelta", LogStatsName.DamageDelta),
        ("FBE", LogStatsName.FBE),
        ("DamageFB", LogStatsName.DamageFB),
        ("Assists", LogStatsName.Assists),
    ):
        emit_column(column, stat, df)


def _stat_rows(log: _Log, pid_of: dict[str, int], heroes: _Heroes) -> pd.DataFrame:
    records = []
    for row in log.rows(LogEventType.PlayerStat).itertuples(index=False):
        stat_row = PlayerStatRow.from_data(row.data)
        player, hero = pid_of[stat_row.player], heroes.index(heroes.code(stat_row.hero))
        for stat_name, value in stat_row.stat_values.items():
            records.append(
                {
                    "player_id": player,
                    "hero_id": hero,
                    "round": int(row.round_number),
                    "stat_name": stat_name,
                    "value": value,
                }
            )
    return pd.DataFrame(records)


def _facts(
    log: _Log, pid_of: dict[str, int], heroes: _Heroes, kills: list[impact.KillRow], emit: Emit
) -> dict[int, str]:
    """Every player/hero/round fact except the baseline-dependent ones; returns observed roles (role codes)."""
    cumulative = _stat_rows(log, pid_of, heroes)
    if cumulative.empty:
        logger.info("No PlayerStat events found. Skipping stat creation.")
        return {}

    cumulative = cumulative.sort_values(by=["player_id", "hero_id", "stat_name", "round"])
    cumulative["discrete_value"] = (
        cumulative.groupby(["player_id", "hero_id", "stat_name"])["value"].diff().fillna(cumulative["value"])
    )

    discrete_per_hero = cumulative[cumulative["round"] > 0].copy()
    for r in discrete_per_hero[["stat_name", "player_id", "round", "hero_id", "discrete_value"]].to_dict(
        orient="records"
    ):
        emit(r["stat_name"], r["player_id"], r["round"], r["hero_id"], r["discrete_value"])

    discrete_per_round = discrete_per_hero.groupby(["player_id", "round", "stat_name"], as_index=False)[
        "discrete_value"
    ].sum()
    for r in discrete_per_round[["player_id", "stat_name", "round", "discrete_value"]].to_dict(orient="records"):
        emit(r["stat_name"], r["player_id"], r["round"], None, r["discrete_value"])

    final_cumulative = cumulative[cumulative["round"] == cumulative["round"].max()].copy()
    for r in final_cumulative[["stat_name", "player_id", "hero_id", "value"]].to_dict(orient="records"):
        emit(r["stat_name"], r["player_id"], 0, r["hero_id"], r["value"])

    final_all_heroes = final_cumulative.groupby(["player_id", "stat_name"], as_index=False)["value"].sum()
    for r in final_all_heroes[["player_id", "stat_name", "value"]].to_dict(orient="records"):
        emit(r["stat_name"], r["player_id"], 0, None, r["value"])

    hero_derived = discrete_per_hero.pivot_table(
        index=["player_id", "round", "hero_id"], columns="stat_name", values="discrete_value", fill_value=0
    ).reset_index()
    round_derived = discrete_per_round.pivot_table(
        index=["player_id", "round"], columns="stat_name", values="discrete_value", fill_value=0
    ).reset_index()
    round_derived["hero_id"] = None
    match_hero_derived = final_cumulative.pivot_table(
        index=["player_id", "hero_id"], columns="stat_name", values="value", fill_value=0
    ).reset_index()
    match_hero_derived["round"] = 0
    match_derived = final_all_heroes.pivot_table(index=["player_id"], columns="stat_name", values="value", fill_value=0)
    match_derived = match_derived.reset_index()
    match_derived["round"] = 0
    match_derived["hero_id"] = None

    # Kill-feed counts (first picks, ...) are emitted per participant and round without a hero; round 0 is the
    # match-total sentinel, so the per-round rows are the only input and the match total is their sum.
    events = impact.build_event_counts(kills, heroes.types, member_user_ids={pid: pid for pid in pid_of.values()})
    if not events.empty:
        stat_cols = list(impact_consts.EVENT_STATS)
        events = events[events["segment"] > 0].groupby(["player_id", "segment"], as_index=False)[stat_cols].sum()
    if not events.empty:
        totals = events.groupby("player_id", as_index=False)[stat_cols].sum()
        for stat_name in impact_consts.EVENT_STATS:
            member = LogStatsName[stat_name]
            for r in events.itertuples(index=False):
                emit(member, r.player_id, int(r.segment), None, float(getattr(r, stat_name)))
        for stat_name in impact_consts.EVENT_STATS:
            member = LogStatsName[stat_name]
            for r in totals.itertuples(index=False):
                emit(member, r.player_id, 0, None, float(getattr(r, stat_name)))

    playtime = final_cumulative[final_cumulative["stat_name"] == LogStatsName.HeroTimePlayed][
        ["player_id", "hero_id", "value"]
    ].rename(columns={"value": "seconds"})
    playtime["role"] = [
        hero_class.name if hero_class is not None and hero_class is not HeroClass.flex else None
        for hero_class in map(heroes.types.get, playtime["hero_id"])
    ]
    roles = impact.dominant_roles(playtime)

    _derived(hero_derived, emit)
    _derived(round_derived, emit)
    _derived(match_hero_derived, emit)
    _derived(match_derived, emit)
    return roles


def decode(raw: bytes, ctx: DecodeContext) -> MatchDoc:
    """One finished Workshop log -> its canonical document."""
    label = ctx.source.external_id or ctx.source.kind
    log = _Log(raw.decode("utf-8").splitlines(), label)
    log.validate()
    teams = log.teams()
    start = log.start()
    gamemode, map_name = start[1], start[0]
    if (gamemode, map_name) in ctx.ambiguous_maps:
        raise DecodeError("ambiguous_map", f"Map {map_name!r} / mode {gamemode!r} matches more than one catalog map")
    map_code = ctx.maps.get((gamemode, map_name))
    if map_code is None:
        raise DecodeError(
            "not_found",
            f"Map {map_name!r} / mode {gamemode!r} not found",
            misses={"map": (map_name,), "mode": (gamemode,)},
        )
    duration, home_score, away_score = log.score_and_time()

    handles = [(name, team) for team, names in teams.items() for name in names]
    pid_of = {name: index for index, (name, _) in enumerate(handles)}
    heroes = _Heroes(ctx)
    kills = _kills(log, pid_of, heroes)

    cells: list[tuple[str, int, int, int | None, float]] = []

    def emit(stat: LogStatsName, pid: int, segment: int, hero: int | None, value: float) -> None:
        cells.append((stat.value, int(pid), int(segment), None if hero is None else int(hero), float(value)))

    roles = _facts(log, pid_of, heroes, [kill for kill, _, _ in kills], emit)
    codes, by_pid = heroes.codes(), {index: name for name, index in pid_of.items()}

    facts = [
        {
            "participant": by_pid[pid],
            "entity": None if hero is None else codes[hero],
            "stat": stat,
            "value": value,
            "segment": segment,
        }
        for stat, pid, segment, hero, value in cells
    ]
    facts.extend(
        {"team": team, "stat": "score", "value": float(score), "segment": 0}
        for team, score in ((_HOME, home_score), (_AWAY, away_score))
    )

    events = [
        {
            "t": kill.t,
            "type": "kill",
            "actor": by_pid[kill.actor_member_id],
            "target": by_pid[kill.target_member_id],
            "entity": attacker_hero,
            "related_entity": victim_hero,
            "segment": kill.segment,
            "data": kill.data,
        }
        for kill, attacker_hero, victim_hero in kills
    ]
    for row in log.df.itertuples(index=False):
        event_name = _EVENT_TYPES.get(row.event_type)
        if event_name is None:
            continue
        event = MatchEventRow.from_data(row.data, event_name)
        events.append(
            {
                "t": float(row.time),
                "type": event_name.value,
                "actor": event.player,
                "target": event.related_player or None,
                "entity": heroes.code(event.hero) if event.hero else None,
                "related_entity": heroes.code(event.related_hero) if event.related_hero else None,
                "segment": int(row.round_number),
            }
        )

    segments = sorted({row["segment"] for row in (*facts, *events) if row["segment"] > 0})
    # Workshop writes 0:0 for Push/Clash whoever won: an artifact, not a tie, so no result is claimed.
    home_place, away_place = (None, None) if gamemode in ctx.objectiveless_modes else placements(home_score, away_score)
    document = {
        "protocol": "owt.match/1",
        "discipline": ctx.discipline,
        "source": ctx.source,
        "hint": ctx.hint,
        "played_at": log.started_at or ctx.received_at,
        "duration_s": duration,
        "map": map_code,
        "teams": [{"key": _HOME, "placement": home_place}, {"key": _AWAY, "placement": away_place}],
        "participants": [
            {
                "key": name,
                "team": team,
                "identity": {"provider": str(SocialProvider.BATTLENET), "id": name},
                "role": (
                    {"dimension": PLAYER_ROLE.code, "role": roles[pid_of[name]]} if pid_of[name] in roles else None
                ),
            }
            for name, team in handles
        ],
        "segments": [{"index": number, "kind": "round"} for number in segments],
        "facts": facts,
        "events": events,
    }
    return _validated(document)


def _validated(document: dict) -> MatchDoc:
    try:
        return MatchDoc.model_validate(document)
    except ValidationError as exc:
        raise MatchDocError(
            [IngestIssue(list(error["loc"]), error["type"], error["msg"]) for error in exc.errors()]
        ) from None


async def derive_match(session, doc: MatchDoc, binding: BoundMatch) -> MatchDoc:  # noqa: ANN001
    """Add the impact facts (``impact_points``, ``impact_rank``, ``overperformance_score``/``_badge``, ``contrib_*``),
    replacing any present. Unscored players get none; no baselines, no impact facts at all."""
    kept = [fact for fact in doc.facts if fact.stat not in _DERIVED_AFTER_BINDING]
    unbound = {f.participant for f in kept if f.participant} - binding.participants.keys()
    if unbound:
        raise ValueError(f"participant {min(unbound)!r} is not bound")
    baseline_set = await baselines.get_active(session, discipline=doc.discipline)
    derived: list[dict] = []
    if baseline_set is None:
        logger.warning(f"Impact baselines missing for {doc.discipline} -- skipping impact stats")
    else:
        catalog = await baselines.hero_catalog(session, discipline=doc.discipline)
        stints, roles = await asyncio.to_thread(_stints, doc, kept, binding, catalog)
        quintiles = await match_quintiles(
            session, [(binding.encounter_id, member, role) for member, role in roles.items()]
        )
        derived = await asyncio.to_thread(
            _impact_facts,
            doc,
            binding,
            baseline_set,
            stints,
            roles,
            {member: quintile for (_, member), quintile in quintiles.items()},
        )
    return _validated({**doc.model_dump(), "facts": [fact.model_dump() for fact in kept] + derived})


def _stints(
    doc: MatchDoc, kept: list, binding: BoundMatch, catalog: dict[str, tuple[int, HeroClass | None]]
) -> tuple[pd.DataFrame, dict[int, str]]:
    """Hero stints of every segment (player = workspace member id) and each player's dominant role on the map."""
    hero_types = {hero_id: hero_class for hero_id, hero_class in catalog.values() if hero_class is not None}
    member = {key: seat.member_id for key, seat in binding.participants.items()}
    stat_rows = pd.DataFrame(
        [
            (member[fact.participant], fact.segment, catalog[fact.entity][0], _STAT_BY_CODE[fact.stat].name, fact.value)
            for fact in kept
            if fact.participant is not None and fact.entity in catalog and fact.stat in _STAT_BY_CODE
        ],
        columns=["player_id", "segment", "hero", "name", "value"],
    )
    feed = [
        impact.KillRow(
            t=event.t,
            segment=event.segment,
            actor_member_id=None if event.actor is None else member[event.actor],
            target_member_id=None if event.target is None else member[event.target],
            related_entity_id=catalog[event.related_entity][0] if event.related_entity in catalog else None,
            data=dict(event.data or {}),
            entity_id=catalog[event.entity][0] if event.entity in catalog else None,
        )
        for event in doc.events
        if event.type == "kill"
    ]
    events = impact.build_event_counts(feed, hero_types, member_user_ids={m: m for m in member.values()})
    stints = impact.build_stints(stat_rows, events, hero_types)
    return stints, impact.dominant_roles(stints[stints["segment"] == 0])


def _impact_facts(
    doc: MatchDoc,
    binding: BoundMatch,
    baseline_set: impact.BaselineSet,
    stints: pd.DataFrame,
    roles: dict[int, str],
    quintiles: dict[int, int],
) -> list[dict]:
    key_of = {seat.member_id: key for key, seat in binding.participants.items()}
    scored = impact.score_match(
        stints,
        baseline_set,
        impact_weights.IMPACT_WEIGHTS,
        has_killfeed=any(event.type == "kill" for event in doc.events),
        roles=roles,
        quintiles=quintiles,
    )
    return [
        {
            "participant": key_of[int(row.player_id)],
            "stat": row.stat.value,
            "value": float(row.value),
            "segment": int(row.segment),
        }
        for row in scored.itertuples(index=False)
    ]
