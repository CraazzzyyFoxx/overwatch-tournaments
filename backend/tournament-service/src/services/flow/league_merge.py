"""League merge (spec §15): the mapping file, the season planner and the day merge.

`plan_leagues` proposes `league_merge.json` from the legacy `is_league` tournaments; the owner completes the
`aggregate` of every entry by hand and `load_mapping` refuses a file that still lacks one. `merge_league` re-points one
league's day tournaments to the earliest day inside the caller's transaction.
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.core.chrono import chrono_sort_key
from shared.core.enums import FlowNodeKind, FlowNodeStatus
from shared.domain.flow.config import AggregateNodeConfig, LeaderboardNodeConfig
from shared.domain.flow.validate import validate_flow
from shared.models.tournament.flow import FlowEdge, FlowNode
from shared.services.participant_result import write_participant_results
from src.services.flow.engine import flow_engine
from src.services.flow.lifecycle import flow_node_service
from src.services.flow.service import load_flow_specs

__all__ = (
    "REGISTRATION_FKS",
    "TOURNAMENT_FKS",
    "Dropped",
    "LeagueDay",
    "LeagueEntry",
    "LeagueSourceRow",
    "MappingError",
    "MergeError",
    "MergeLog",
    "apply_mapping",
    "fetch_league_rows",
    "load_mapping",
    "merge_league",
    "plan_leagues",
)

LEAGUE_NAME_SEPARATOR = " | "


class MappingError(ValueError):
    """The mapping file is unusable."""


class MergeError(RuntimeError):
    """The data does not allow the merge."""


class LeagueDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tournament_id: int
    day: int = Field(ge=1)
    division: str | None = None


class LeagueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league: str
    season: int = Field(ge=1)
    name: str = Field(min_length=1)
    target_tournament_id: int
    aggregate: AggregateNodeConfig
    days: list[LeagueDay] = Field(min_length=1)

    @model_validator(mode="after")
    def _days_are_consistent(self) -> LeagueEntry:
        ids = [d.tournament_id for d in self.days]
        if len(set(ids)) != len(ids):
            raise ValueError("a tournament is listed twice")
        slots = [(d.day, d.division) for d in self.days]
        if len(set(slots)) != len(slots):
            raise ValueError("(day, division) must be unique")
        earliest = min(d.day for d in self.days)
        if not any(d.tournament_id == self.target_tournament_id and d.day == earliest for d in self.days):
            raise ValueError("target must be a tournament of the earliest day")
        return self

    @property
    def days_in_order(self) -> list[LeagueDay]:
        return sorted(self.days, key=lambda d: (d.day, d.division or ""))

    @property
    def days_latest_first(self) -> list[int]:
        return [d.tournament_id for d in reversed(self.days_in_order)]

    @property
    def others(self) -> list[int]:
        return [d.tournament_id for d in self.days if d.tournament_id != self.target_tournament_id]


def load_mapping(text: str) -> list[LeagueEntry]:
    raw = json.loads(text)
    if not isinstance(raw, list):
        raise MappingError("the mapping must be a JSON list")
    entries: list[LeagueEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise MappingError("the mapping must be a JSON list of objects")
        where = f"league {item.get('league')!r} season {item.get('season')}"
        if item.get("aggregate") is None:
            raise MappingError(f"{where}: aggregate is required")
        try:
            entries.append(LeagueEntry.model_validate(item))
        except ValidationError as exc:
            raise MappingError(f"{where}: {exc}") from exc
    seen: set[int] = set()
    for league in entries:
        for day in league.days:
            if day.tournament_id in seen:
                raise MappingError(f"tournament {day.tournament_id} is mapped twice")
            seen.add(day.tournament_id)
    return entries


@dataclass(frozen=True)
class LeagueSourceRow:
    id: int
    workspace_id: int
    discipline: str
    name: str
    start_date: datetime | None
    end_date: datetime | None
    created_at: datetime


def plan_leagues(rows: Iterable[LeagueSourceRow], *, season_gap_days: int = 21) -> list[dict[str, Any]]:
    """Group by workspace, game and name prefix; a gap above `season_gap_days` starts a new season."""
    groups: dict[tuple[int, str, str], list[LeagueSourceRow]] = defaultdict(list)
    for r in rows:
        groups[(r.workspace_id, r.discipline, r.name.split(LEAGUE_NAME_SEPARATOR)[0])].append(r)
    planned: list[dict[str, Any]] = []
    for (_, _, league), members in groups.items():
        members.sort(key=chrono_sort_key)
        seasons: list[list[LeagueSourceRow]] = [[members[0]]]
        for previous, current in itertools.pairwise(members):
            if chrono_sort_key(current)[0] - chrono_sort_key(previous)[0] > timedelta(days=season_gap_days):
                seasons.append([])
            seasons[-1].append(current)
        for number, season in enumerate(seasons, start=1):
            days: list[dict[str, Any]] = []
            by_start = itertools.groupby(season, key=lambda r: chrono_sort_key(r)[0])
            for day, (_, group) in enumerate(by_start, start=1):
                same = sorted(group, key=lambda r: r.id)
                for r in same:
                    division = (
                        r.name.split(LEAGUE_NAME_SEPARATOR, 1)[1]
                        if len(same) > 1 and LEAGUE_NAME_SEPARATOR in r.name
                        else None
                    )
                    days.append({"tournament_id": r.id, "day": day, "division": division})
            planned.append(
                {
                    "league": league,
                    "season": number,
                    "name": league,
                    "target_tournament_id": days[0]["tournament_id"],
                    "aggregate": None,
                    "days": days,
                }
            )
    return sorted(planned, key=lambda p: p["target_tournament_id"])


async def fetch_league_rows(session: AsyncSession) -> list[LeagueSourceRow]:
    # Raw SQL: the ORM model drops `is_league`; this runs only against a database still at `flowP6_01`.
    result = await session.execute(
        sa.text(
            "SELECT id, workspace_id, discipline, name, start_date, end_date, created_at "
            "FROM tournament.tournament WHERE is_league"
        )
    )
    return [LeagueSourceRow(*r) for r in result.all()]


Rule = tuple[Literal["move", "keep_latest", "dedupe", "drop", "leave", "special"], tuple[str, ...]]


def _rule(kind: Literal["move", "keep_latest", "dedupe", "drop", "leave", "special"], *keys: str) -> Rule:
    return (kind, keys)


#: Every column carrying a tournament id, classified by the nearest rule of spec §15.3 step 4 (the guard test fails on an
#: unclassified one). Keys are ``schema.table.column``; the second item of a rule is the ``dedupe`` key.
#: ``leave`` = cascades with the emptied day; ``special`` = collapsed by a dedicated step first, then moved.
#: Flow nodes, edges, schedules and results move with their node; registration entries follow their node.
TOURNAMENT_FKS: dict[str, Rule] = {
    "achievements.evaluation_result.tournament_id": _rule("leave"),  # Spec issue 10: collides, re-evaluated
    "achievements.evaluation_run.tournament_id": _rule("leave"),  # audit, SET NULL on delete
    "achievements.override.tournament_id": _rule("move"),
    "analytics.anomaly_feedback.tournament_id": _rule("move"),
    "analytics.job.tournament_id": _rule("move"),
    "analytics.ml_model_artifact.training_cutoff_tournament_id": _rule("move"),
    "analytics.performance.tournament_id": _rule("move"),
    "analytics.player_anomaly.tournament_id": _rule("move"),
    "analytics.player_shift.tournament_id": _rule("move"),
    "analytics.shifts.tournament_id": _rule("move"),
    "analytics.standings_distribution.tournament_id": _rule("move"),
    "balancer.balance.tournament_id": _rule("move"),
    "balancer.tournament_config.tournament_id": _rule("move"),
    "draft.session.tournament_id": _rule("move"),
    "encounter.encounter.tournament_id": _rule("move"),
    "encounter.team.tournament_id": _rule("move"),
    "registration.form.tournament_id": _rule("special"),
    "registration.google_sheet_feed.tournament_id": _rule("keep_latest"),
    "registration.registration.tournament_id": _rule("special"),
    "registration.team.tournament_id": _rule("special"),
    "roster.team_format.tournament_id": _rule("keep_latest"),
    "stats.discord_channel.tournament_id": _rule("keep_latest"),
    "stats.ingest_job.hint_tournament_id": _rule("move"),
    "stats.match_fetch.hint_tournament_id": _rule("move"),
    "stream.session.tournament_id": _rule("dedupe", "stream_id"),
    "tournament.bracket_encounter.tournament_id": _rule("move"),
    "tournament.challonge_source.tournament_id": _rule("dedupe", "challonge_tournament_id"),
    "tournament.challonge_sync_log.tournament_id": _rule("move"),
    "tournament.computation_job.tournament_id": _rule("drop"),
    "tournament.encounter_link.tournament_id": _rule("move"),
    "tournament.encounter_report_form.tournament_id": _rule("keep_latest"),
    "tournament.flow_edge.tournament_id": _rule("move"),
    "tournament.flow_node.tournament_id": _rule("move"),
    "tournament.participant_result.tournament_id": _rule("drop"),
    "tournament.pick_ban_config.tournament_id": _rule("dedupe", "kind", "stage_id", "round"),
    "tournament.player.tournament_id": _rule("move"),
    "tournament.player_standing.tournament_id": _rule("move"),
    "tournament.recalculation_state.tournament_id": _rule("drop"),
    "tournament.scrim_room.tournament_id": _rule("move"),
    "tournament.slug_redirect.tournament_id": _rule("move"),
    "tournament.stage.tournament_id": _rule("move"),
    "tournament.standing.tournament_id": _rule("move"),
    "tournament.standing_pin.tournament_id": _rule("move"),
    "tournament.team.tournament_id": _rule("move"),
    "tournament.tournament_link.tournament_id": _rule("dedupe", "kind", "url"),
    "tournament.tournament_preview_access.tournament_id": _rule("dedupe", "auth_user_id"),
    "tournament.voice_channel.tournament_id": _rule("dedupe", "slot_key"),
    "tournament.voice_settings.tournament_id": _rule("keep_latest"),
}

#: Every FK into ``registration.registration``: ``repoint`` moves a dropped profile's rows to the kept profile,
#: ``owned`` rows go with the dropped profile (CASCADE).
REGISTRATION_FKS: dict[str, Literal["repoint", "owned"]] = {
    "draft.player.registration_id": "repoint",
    "registration.google_sheet_binding.registration_id": "owned",
    "registration.identity.registration_id": "owned",
    "registration.registration_entry.registration_id": "repoint",
    "registration.role.registration_id": "owned",
    "registration.team.captain_registration_id": "repoint",
    "registration.team_invite.accepted_registration_id": "repoint",
    "tournament.player_standing.registration_id": "repoint",
}


@dataclass(frozen=True)
class Dropped:
    table: str
    row_id: int
    tournament_id: int
    key: dict[str, Any]


@dataclass
class MergeLog:
    target_tournament_id: int
    deleted_tournament_ids: list[int]
    dropped: list[Dropped] = field(default_factory=list)
    moved: dict[str, int] = field(default_factory=dict)


def _ids(values: Sequence[int]) -> dict[str, list[int]]:
    return {"ids": list(values)}


async def _check_days(session: AsyncSession, entry: LeagueEntry) -> None:
    rows = (
        await session.execute(
            sa.text(
                "SELECT id, workspace_id, discipline FROM tournament.tournament "
                "WHERE id = ANY(CAST(:ids AS bigint[])) FOR UPDATE"
            ),
            _ids([d.tournament_id for d in entry.days]),
        )
    ).all()
    found = {r.id: r for r in rows}
    for day in entry.days:
        if day.tournament_id not in found:
            raise MergeError(f"tournament {day.tournament_id} does not exist")
    target = found[entry.target_tournament_id]
    for day in entry.days:
        row = found[day.tournament_id]
        if (row.workspace_id, row.discipline) != (target.workspace_id, target.discipline):
            raise MergeError(f"tournament {row.id} is not in workspace {target.workspace_id} / {target.discipline}")


async def _assign_formations(session: AsyncSession, entry: LeagueEntry) -> None:
    """Teams and players still owned by the whole tournament belong to their day's one formation node."""
    for day in entry.days:
        params = {"day": day.tournament_id}
        nodes = list(
            await session.scalars(
                sa.text(
                    "SELECT id FROM tournament.flow_node WHERE tournament_id = :day AND kind = 'formation' ORDER BY id"
                ),
                params,
            )
        )
        unowned = (
            await session.execute(
                sa.text(
                    "SELECT (SELECT count(*) FROM tournament.team WHERE tournament_id = :day AND formation_node_id IS NULL)"
                    " + (SELECT count(*) FROM tournament.player WHERE tournament_id = :day AND formation_node_id IS NULL)"
                ),
                params,
            )
        ).scalar_one()
        if not unowned:
            continue
        if len(nodes) != 1:
            raise MergeError(f"day {day.day}: expected one formation node, found {len(nodes)}")
        for table in ("tournament.team", "tournament.player"):
            await session.execute(
                sa.text(
                    f"UPDATE {table} SET formation_node_id = :node WHERE tournament_id = :day AND formation_node_id IS NULL"
                ),
                {**params, "node": nodes[0]},
            )


def _losers(rows: Sequence[Any], days_latest_first: Sequence[int], key: Callable[[Any], Any]) -> list[tuple[int, int]]:
    """``(dropped id, kept id)`` for every row whose ``key`` repeats; the latest day's row is the one kept."""
    rank = {day: i for i, day in enumerate(days_latest_first)}
    kept: dict[Any, int] = {}
    losers: list[tuple[int, int]] = []
    for row in sorted(rows, key=lambda r: (rank[r.tournament_id], -r.id)):
        if (k := key(row)) in kept:
            losers.append((row.id, kept[k]))
        else:
            kept[k] = row.id
    return losers


async def _repoint(session: AsyncSession, table: str, column: str, losers: Sequence[tuple[int, int]]) -> None:
    if losers:
        await session.execute(
            sa.text(
                f"UPDATE {table} AS t SET {column} = m.kept FROM unnest(CAST(:dropped AS bigint[]), "
                f"CAST(:kept AS bigint[])) AS m(dropped, kept) WHERE t.{column} = m.dropped"
            ),
            {"dropped": [d for d, _ in losers], "kept": [k for _, k in losers]},
        )


async def _delete_rows(
    session: AsyncSession, table: str, ids: Sequence[int], log: MergeLog, key: Sequence[str] = ()
) -> None:
    if not ids:
        return
    columns = ", ".join(("id", "tournament_id", *key))
    rows = await session.execute(
        sa.text(f"DELETE FROM {table} WHERE id = ANY(CAST(:ids AS bigint[])) RETURNING {columns}"), _ids(ids)
    )
    log.dropped.extend(
        Dropped(table, r["id"], r["tournament_id"], {c: r[c] for c in key})
        for r in sorted(rows.mappings(), key=lambda r: r["id"])
    )


async def _active_rows(session: AsyncSession, table: str, days: Sequence[int], *columns: str) -> list[Any]:
    result = await session.execute(
        sa.text(
            f"SELECT id, tournament_id, {', '.join(columns)} FROM {table} "
            "WHERE tournament_id = ANY(CAST(:ids AS bigint[])) AND deleted_at IS NULL"
        ),
        _ids(days),
    )
    return list(result.all())


async def _collapse_registered_teams(session: AsyncSession, days: Sequence[int], log: MergeLog) -> None:
    """A same-name registered team of several days is one team: the latest day's (Decision 12)."""
    rows = await _active_rows(session, "registration.team", days, "name_normalized")
    losers = _losers(rows, days, lambda r: r.name_normalized)
    await _repoint(session, "registration.registration", "registration_team_id", losers)
    await _delete_rows(session, "registration.team", [d for d, _ in losers], log, ("name_normalized",))


async def _collapse_profiles(session: AsyncSession, days: Sequence[int], log: MergeLog) -> None:
    """A member keeps the latest day's profile; the other days' participation and links move onto it (Decision 13)."""
    rows = [
        r
        for r in await _active_rows(session, "registration.registration", days, "workspace_member_id")
        if r.workspace_member_id is not None
    ]
    losers = _losers(rows, days, lambda r: r.workspace_member_id)
    for key, role in REGISTRATION_FKS.items():
        if role == "repoint":
            table, column = key.rsplit(".", 1)
            await _repoint(session, table, column, losers)
    await _delete_rows(session, "registration.registration", [d for d, _ in losers], log, ("workspace_member_id",))


async def _collapse_forms(session: AsyncSession, days: Sequence[int], log: MergeLog) -> None:
    """One form per tournament: the latest day's keeps every other form's versions, renumbered after its own."""
    rows = (
        await session.execute(
            sa.text(
                "SELECT id, tournament_id FROM registration.form WHERE tournament_id = ANY(CAST(:ids AS bigint[]))"
            ),
            _ids(days),
        )
    ).all()
    for old, kept in _losers(rows, days, lambda _: None):
        await session.execute(
            sa.text(
                "UPDATE registration.form_version SET form_id = :kept, number = number + "
                "(SELECT coalesce(max(number), 0) FROM registration.form_version WHERE form_id = :kept) "
                "WHERE form_id = :old"
            ),
            {"kept": kept, "old": old},
        )
        await _delete_rows(session, "registration.form", [old], log)


async def _drop_collisions(
    session: AsyncSession, table: str, column: str, days: Sequence[int], key: Sequence[str], log: MergeLog
) -> None:
    """Delete every row but the latest day's of each ``key`` (one partition when ``key`` is empty)."""
    partition = ", ".join(key) or "1"
    returning = ", ".join(("t.id", f"t.{column}", *(f"t.{c}" for c in key)))
    rows = await session.execute(
        sa.text(
            f"""
        DELETE FROM {table} AS t USING (
          SELECT id, row_number() OVER (
            PARTITION BY {partition} ORDER BY array_position(CAST(:days AS bigint[]), {column})) AS rn
          FROM {table} WHERE {column} = ANY(CAST(:days AS bigint[]))
        ) AS ranked
        WHERE t.id = ranked.id AND ranked.rn > 1
        RETURNING {returning}"""
        ),
        {"days": list(days)},
    )
    log.dropped.extend(
        Dropped(table, r["id"], r[column], {c: r[c] for c in key})
        for r in sorted(rows.mappings(), key=lambda r: r["id"])
    )


async def _apply_rules(session: AsyncSession, entry: LeagueEntry, log: MergeLog) -> None:
    others = entry.others
    for qualified, (kind, key) in TOURNAMENT_FKS.items():
        table, column = qualified.rsplit(".", 1)
        if kind == "leave":
            continue
        if kind == "drop":
            await session.execute(
                sa.text(f"DELETE FROM {table} WHERE {column} = ANY(CAST(:ids AS bigint[]))"), _ids(others)
            )
            continue
        if kind in ("keep_latest", "dedupe"):
            await _drop_collisions(session, table, column, entry.days_latest_first, key, log)
        moved = await session.execute(
            sa.text(f"UPDATE {table} SET {column} = :target WHERE {column} = ANY(CAST(:ids AS bigint[]))"),
            {"target": entry.target_tournament_id, **_ids(others)},
        )
        log.moved[qualified] = moved.rowcount


async def _relabel_days(session: AsyncSession, entry: LeagueEntry) -> list[int]:
    """Name each day's branch, stack the branches on y and offset ``Stage.order`` so days display in order.

    Returns the day sinks (stage nodes with no outgoing edge) in day order: the aggregate's inputs (Decision 9).
    """
    sinks: list[int] = []
    offset = 0
    for index, day in enumerate(entry.days_in_order):
        label = f"Day {day.day}" if day.division is None else f"Day {day.day} · {day.division}"
        params = {"day": day.tournament_id}
        await session.execute(
            sa.text(
                "UPDATE tournament.flow_node SET position_y = position_y + :dy, name = CASE kind "
                "WHEN 'registration' THEN :label WHEN 'formation' THEN :label || ' · Teams' "
                "ELSE :label || ' · ' || name END WHERE tournament_id = :day"
            ),
            {**params, "dy": index * 400, "label": label},
        )
        top = await session.scalar(
            sa.text('SELECT max("order") FROM tournament.stage WHERE tournament_id = :day'), params
        )
        if top is not None:
            await session.execute(
                sa.text('UPDATE tournament.stage SET "order" = "order" + :offset WHERE tournament_id = :day'),
                {**params, "offset": offset},
            )
            offset += top + 1
        sinks += await session.scalars(
            sa.text(
                "SELECT n.id FROM tournament.flow_node n WHERE n.tournament_id = :day AND n.kind = 'stage' "
                "AND NOT EXISTS (SELECT 1 FROM tournament.flow_edge e WHERE e.source_node_id = n.id) ORDER BY n.id"
            ),
            params,
        )
    return sinks


async def _add_season_table(session: AsyncSession, entry: LeagueEntry, sinks: Sequence[int]) -> None:
    """``sinks → aggregate → leaderboard`` right of the rightmost node; invalid graphs abort the league (Decision 9)."""
    target = entry.target_tournament_id
    max_x = await session.scalar(
        sa.text("SELECT coalesce(max(position_x), 0) FROM tournament.flow_node WHERE tournament_id = :t"),
        {"t": target},
    )
    aggregate = FlowNode(
        tournament_id=target,
        kind=FlowNodeKind.AGGREGATE,
        name=f"{entry.name} · Season",
        status=FlowNodeStatus.PENDING,
        config=entry.aggregate.model_dump(mode="json"),
        position_x=max_x + 300,
        position_y=0,
    )
    leaderboard = FlowNode(
        tournament_id=target,
        kind=FlowNodeKind.LEADERBOARD,
        name="Table",
        status=FlowNodeStatus.PENDING,
        config=LeaderboardNodeConfig().model_dump(mode="json"),
        position_x=max_x + 600,
        position_y=0,
    )
    session.add_all([aggregate, leaderboard])
    await session.flush()
    session.add_all(
        [
            *(
                FlowEdge(
                    tournament_id=target,
                    source_node_id=sink,
                    source_port="ranking",
                    target_node_id=aggregate.id,
                    target_port="inputs",
                )
                for sink in sinks
            ),
            FlowEdge(
                tournament_id=target,
                source_node_id=aggregate.id,
                source_port="ranking",
                target_node_id=leaderboard.id,
                target_port="ranking",
            ),
        ]
    )
    await session.flush()
    issues = [i for i in validate_flow(*await load_flow_specs(session, target)) if i.severity == "error"]
    if issues:
        raise MergeError("; ".join(f"{i.code}: {i.message}" for i in issues))


async def merge_league(session: AsyncSession, entry: LeagueEntry) -> MergeLog:
    """Re-point every day of ``entry`` to its target tournament and delete the emptied days (spec §15.3).

    Flushes, never commits. The composite FKs are deferred while rows move and checked at the end of the merge.
    """
    await _check_days(session, entry)
    await session.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    log = MergeLog(entry.target_tournament_id, [])
    days = entry.days_latest_first
    await _assign_formations(session, entry)
    sinks = await _relabel_days(session, entry)
    await _collapse_registered_teams(session, days, log)
    await _collapse_profiles(session, days, log)
    await _collapse_forms(session, days, log)
    await _apply_rules(session, entry, log)
    await _add_season_table(session, entry, sinks)
    await session.execute(
        sa.text(
            "UPDATE tournament.tournament SET name = :name, end_date = ("
            "SELECT max(coalesce(end_date, start_date)) FROM tournament.tournament WHERE id = ANY(CAST(:ids AS bigint[])))"
            " WHERE id = :target"
        ),
        {"name": entry.name, "target": entry.target_tournament_id, **_ids(days)},
    )
    has_league_flag = await session.scalar(
        sa.text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'tournament' "
            "AND table_name = 'tournament' AND column_name = 'is_league'"
        )
    )
    if has_league_flag:
        # shortcut: the column exists only before flowP6_02; the production merge runs at flowP6_01
        await session.execute(
            sa.text("UPDATE tournament.tournament SET is_league = false WHERE id = :target"),
            {"target": entry.target_tournament_id},
        )
    await session.execute(
        sa.text("DELETE FROM tournament.tournament WHERE id = ANY(CAST(:ids AS bigint[]))"), _ids(entry.others)
    )
    log.deleted_tournament_ids = list(entry.others)
    await flow_engine.recompute(session, entry.target_tournament_id)
    # The target's status and ``is_finished`` follow the merged flow (a finished league becomes ``completed``).
    await flow_node_service.sync_tournament_status(session, entry.target_tournament_id)
    await write_participant_results(session, entry.target_tournament_id)
    await session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))  # surface a violation here, not at commit
    return log


async def apply_mapping(
    session_maker: async_sessionmaker[AsyncSession], entries: Sequence[LeagueEntry], *, dry_run: bool
) -> list[MergeLog]:
    """Merge each league in its own transaction (rolled back on ``dry_run``); the first failure is re-raised."""
    logs: list[MergeLog] = []
    for entry in entries:
        async with session_maker() as session:
            logs.append(await merge_league(session, entry))
            await (session.rollback() if dry_run else session.commit())
    return logs
