"""Flow recompute (spec §5.4, §8.1): derives every node's output rows from the tournament's current state.

Lifecycle nodes read their rows from the registration, team and standings tables; the pure nodes compute them from
their inputs. Rows are updated in place so ids stay stable (plan Decision 5). Lifecycle statuses are never written here.
A moved leaderboard sink of a finished tournament rewrites ``participant_result`` (spec §4.7 rule 1).
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.core.enums import FlowNodeKind, FlowNodeStatus, FlowResultState, FlowUnit, StageType
from shared.domain.flow.config import (
    AggregateNodeConfig,
    FilterNodeConfig,
    LeaderboardNodeConfig,
    RegistrationNodeConfig,
    SplitNodeConfig,
    parse_node_config,
)
from shared.domain.flow.ports import concrete_outputs
from shared.domain.flow.validate import topological_order
from shared.models.balancer.balance import BalancerBalance, BalancerTeam
from shared.models.draft.draft import DraftSession, DraftTeam
from shared.models.encounter.encounter import Encounter
from shared.models.registration.registration import Registration, RegistrationEntry, RegistrationTeam
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.player_standing import PlayerStanding
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Player, Team
from shared.models.tournament.tournament import Tournament
from shared.services.participant_result import write_participant_results
from src.domain.flow.aggregate import AggregateInput, Seat, compute_aggregate
from src.domain.flow.compute import (
    PureOutput,
    ResultRow,
    compute_filter,
    compute_leaderboard,
    compute_merge,
    compute_split,
)
from src.services.standings.service import FFA_STAGE_TYPES

__all__ = ("FlowEngine", "FlowRecomputeReport", "flow_engine")

_LIFECYCLE_PORT = {
    FlowNodeKind.REGISTRATION: "participants",
    FlowNodeKind.FORMATION: "teams",
    FlowNodeKind.STAGE: "ranking",
}
#: The status at which a lifecycle node's rows stop moving.
_FINAL_STATUS = {
    FlowNodeKind.REGISTRATION: FlowNodeStatus.CLOSED,
    FlowNodeKind.FORMATION: FlowNodeStatus.COMPLETED,
    FlowNodeKind.STAGE: FlowNodeStatus.COMPLETED,
}


@dataclass(frozen=True, slots=True)
class FlowRecomputeReport:
    changed_node_ids: tuple[int, ...]

    @property
    def changed(self) -> bool:
        return bool(self.changed_node_ids)


def _dedup(rows: Sequence[ResultRow]) -> list[ResultRow]:
    return compute_merge([rows])


class FlowEngine:
    async def recompute(self, session: AsyncSession, tournament_id: int) -> FlowRecomputeReport:
        """Rewrite every node's results and pure-node statuses; flushes, never commits."""
        nodes = (
            await session.scalars(
                sa.select(FlowNode).where(FlowNode.tournament_id == tournament_id).order_by(FlowNode.id)
            )
        ).all()
        edges = (
            await session.scalars(
                sa.select(FlowEdge).where(FlowEdge.tournament_id == tournament_id).order_by(FlowEdge.id)
            )
        ).all()
        by_id = {n.id: n for n in nodes}
        order = topological_order(by_id, ((e.source_node_id, e.target_node_id) for e in edges))
        if order is None:
            raise ValueError(f"flow of tournament {tournament_id} contains a cycle")
        incoming: defaultdict[int, list[FlowEdge]] = defaultdict(list)
        for e in edges:
            incoming[e.target_node_id].append(e)
        item_order = await self._item_order(session, tournament_id) if any(n.kind == "filter" for n in nodes) else {}
        has_successor = {e.source_node_id for e in edges}
        # The same sink ``write_participant_results`` reads: a leaderboard with no outgoing edge, the highest id.
        sink_id = max(
            (n.id for n in nodes if n.kind == FlowNodeKind.LEADERBOARD and n.id not in has_successor), default=None
        )

        stage_ended = (
            await self._stage_ended(session, tournament_id) if any(n.kind == "aggregate" for n in nodes) else {}
        )
        recency: dict[int, datetime | None] = {}
        outputs: dict[tuple[int, str], tuple[list[ResultRow], FlowResultState]] = {}
        board_moved = False
        changed: list[int] = []
        for node_id in order:
            node = by_id[node_id]
            kind = FlowNodeKind(node.kind)
            status = None
            if kind in _LIFECYCLE_PORT:
                loader = {
                    FlowNodeKind.REGISTRATION: self._registration_rows,
                    FlowNodeKind.FORMATION: self.formation_rows,
                    FlowNodeKind.STAGE: self._stage_rows,
                }[kind]
                ports, state = {_LIFECYCLE_PORT[kind]: await loader(session, node)}, self._lifecycle_state(node)
            else:
                sources = [outputs.get((e.source_node_id, e.source_port)) for e in incoming[node_id]]
                # An aggregate scores a missing input as 0, so it waits only while no input has rows.
                has_rows = [bool(s and s[0]) for s in sources]
                if not (any(has_rows) if kind == FlowNodeKind.AGGREGATE else sources and all(has_rows)):
                    ports = {p.name: [] for p in concrete_outputs(kind, node.config)}
                    state, status = FlowResultState.TENTATIVE, FlowNodeStatus.PENDING
                else:
                    if kind == FlowNodeKind.AGGREGATE:
                        computed = await self._compute_aggregate(session, node, incoming[node_id], sources, recency)
                    else:
                        computed = self._compute_pure(kind, node, [s[0] for s in sources if s], item_order)
                    final = not computed.boundary_tie and all(s and s[1] == FlowResultState.FINAL for s in sources)
                    ports, state = computed.ports, FlowResultState.FINAL if final else FlowResultState.TENTATIVE
                    status = FlowNodeStatus(state.value)
            # When the node finished: what an aggregate orders its inputs by. A node without a stamp (legacy and merged
            # stages) falls back to its stage's latest encounter; a pure node to its most recent input.
            recency[node_id] = (
                node.completed_at or (stage_ended.get(node.stage_id) if state == FlowResultState.FINAL else None)
                if kind in _LIFECYCLE_PORT
                else max((r for e in incoming[node_id] if (r := recency[e.source_node_id])), default=None)
            )
            moved = False
            for port, rows in ports.items():
                outputs[(node_id, port)] = (rows, state)
                written = await self._write_results(session, node_id, port, rows, state)
                moved |= written
                board_moved |= written and node_id == sink_id
            if status is not None and status != node.status:
                await session.execute(sa.update(FlowNode).where(FlowNode.id == node_id).values(status=status.value))
                moved = True
            if moved:
                changed.append(node_id)
        await session.flush()
        if board_moved and await session.scalar(
            sa.select(Tournament.is_finished).where(Tournament.id == tournament_id)
        ):
            await write_participant_results(session, tournament_id)
        return FlowRecomputeReport(tuple(changed))

    def _compute_pure(
        self, kind: FlowNodeKind, node: FlowNode, inputs: Sequence[list[ResultRow]], item_order: Mapping[int, int]
    ) -> PureOutput:
        if kind == FlowNodeKind.FILTER:
            config = parse_node_config(kind, node.config)
            assert isinstance(config, FilterNodeConfig)
            return compute_filter(config, inputs[0], item_order=item_order)
        if kind == FlowNodeKind.SPLIT:
            split = parse_node_config(kind, node.config)
            assert isinstance(split, SplitNodeConfig)
            return compute_split(split, inputs[0])
        if kind == FlowNodeKind.LEADERBOARD:
            board = parse_node_config(kind, node.config)
            assert isinstance(board, LeaderboardNodeConfig)
            return compute_leaderboard(board, inputs[0])
        return PureOutput({"merged": compute_merge(inputs)})

    async def _stage_ended(self, session: AsyncSession, tournament_id: int) -> dict[int, datetime]:
        """Stage id -> the time of its latest encounter, for a completed stage node that carries no ``completed_at``."""
        when = sa.func.coalesce(
            Encounter.ended_at, Encounter.confirmed_at, Encounter.started_at, Encounter.scheduled_at
        )
        rows = await session.execute(
            sa.select(BracketEncounter.stage_id, sa.func.max(when))
            .join(Encounter, Encounter.id == BracketEncounter.encounter_id)
            .join(Stage, Stage.id == BracketEncounter.stage_id)
            .where(Stage.tournament_id == tournament_id)
            .group_by(BracketEncounter.stage_id)
        )
        return {stage_id: ended for stage_id, ended in rows if ended is not None}

    async def _compute_aggregate(
        self,
        session: AsyncSession,
        node: FlowNode,
        edges: Sequence[FlowEdge],
        sources: Sequence[tuple[list[ResultRow], FlowResultState] | None],
        recency: Mapping[int, datetime | None],
    ) -> PureOutput:
        config = parse_node_config(FlowNodeKind.AGGREGATE, node.config)
        assert isinstance(config, AggregateNodeConfig)
        inputs = [
            AggregateInput(
                e.source_node_id,
                s[0] if s else [],
                bool(s and s[1] == FlowResultState.FINAL),
                recency[e.source_node_id],
            )
            for e, s in zip(edges, sources, strict=True)
        ]
        members: defaultdict[int, list[Seat]] = defaultdict(list)
        team_ids = {r.team_id for i in inputs for r in i.rows if r.team_id is not None}
        if config.unit == FlowUnit.PLAYERS and team_ids:
            rows = await session.execute(
                sa.select(Player.team_id, Player.workspace_member_id, Player.role)
                .where(
                    Player.team_id.in_(team_ids),
                    Player.is_substitution.is_(False),
                    Player.workspace_member_id.is_not(None),
                )
                .order_by(Player.id)
            )
            for team_id, member_id, role in rows:
                members[team_id].append(Seat(member_id, role))
        player_inputs = {i.node_id for i in inputs if any(r.workspace_member_id is not None for r in i.rows)}
        if config.unit == FlowUnit.PLAYERS and player_inputs:
            # A player row (an individual Swiss table) plays the role its stage's standing froze.
            roles: defaultdict[int, dict[int, str]] = defaultdict(dict)
            for node_id, member_id, role in await session.execute(
                sa.select(FlowNode.id, PlayerStanding.workspace_member_id, PlayerStanding.role)
                .join(PlayerStanding, PlayerStanding.stage_id == FlowNode.stage_id)
                .where(FlowNode.id.in_(player_inputs))
            ):
                roles[node_id][member_id] = role
            inputs = [
                replace(i, rows=[replace(r, role=roles[i.node_id].get(r.workspace_member_id or 0)) for r in i.rows])
                if i.node_id in roles
                else i
                for i in inputs
            ]
        return compute_aggregate(config, inputs, members_by_team=members)

    def _lifecycle_state(self, node: FlowNode) -> FlowResultState:
        final = node.status == _FINAL_STATUS[FlowNodeKind(node.kind)]
        return FlowResultState.FINAL if final else FlowResultState.TENTATIVE

    async def _item_order(self, session: AsyncSession, tournament_id: int) -> dict[int, int]:
        rows = await session.execute(
            sa.select(StageItem.id, StageItem.order)
            .join(Stage, Stage.id == StageItem.stage_id)
            .where(Stage.tournament_id == tournament_id)
        )
        return dict(rows.tuples().all())

    async def _registration_rows(self, session: AsyncSession, node: FlowNode) -> list[ResultRow]:
        config = parse_node_config(FlowNodeKind.REGISTRATION, node.config)
        assert isinstance(config, RegistrationNodeConfig)

        def qualifies(entry: Any) -> sa.ColumnElement[bool]:
            """The entry is approved (and checked in when the node asks for check-in): it is on the node's output."""
            clause = sa.and_(entry.status == "approved", entry.deleted_at.is_(None))
            return sa.and_(clause, entry.checked_in.is_(True)) if config.check_in else clause

        query = (
            sa.select(Registration.workspace_member_id, Registration.registration_team_id)
            .join(RegistrationEntry, RegistrationEntry.registration_id == Registration.id)
            .where(
                RegistrationEntry.registration_node_id == node.id,
                qualifies(RegistrationEntry),
                Registration.deleted_at.is_(None),
                Registration.workspace_member_id.is_not(None),
            )
            .order_by(RegistrationEntry.reviewed_at.asc().nulls_last(), Registration.id)
        )
        if config.intake == "team":
            # Whole teams only: a complete team none of whose live members is left out (a pending or unchecked member
            # holds the whole team back), emitted with the team id so a registered formation can rebuild it.
            member = aliased(Registration)
            other = aliased(RegistrationEntry)
            held_back = (
                sa.select(sa.literal(1))
                .select_from(member)
                .join(other, other.registration_id == member.id)
                .where(
                    member.registration_team_id == RegistrationTeam.id,
                    member.deleted_at.is_(None),
                    other.registration_node_id == node.id,
                    other.deleted_at.is_(None),
                    other.status.notin_(("withdrawn", "rejected")),
                    ~qualifies(other),
                )
                .exists()
            )
            query = query.join(RegistrationTeam, RegistrationTeam.id == Registration.registration_team_id).where(
                RegistrationTeam.registration_node_id == node.id,
                RegistrationTeam.status == "complete",
                RegistrationTeam.deleted_at.is_(None),
                ~held_back,
            )
        rows = await session.execute(query)
        return _dedup(
            [
                ResultRow(
                    member_id,
                    None,
                    breakdown={"registration_team_id": team_id} if config.intake == "team" else None,
                )
                for member_id, team_id in rows
            ]
        )

    async def formation_rows(self, session: AsyncSession, node: FlowNode) -> list[ResultRow]:
        """The node's teams plus the tournament-wide ones (plan Decision 8), balancer / draft order first, then ``Team.id``."""
        mode = node.config.get("mode")
        if mode == "balancer":
            place = (
                sa.select(sa.func.min(BalancerTeam.sort_order))
                .join(BalancerBalance, BalancerBalance.id == BalancerTeam.balance_id)
                .where(BalancerBalance.formation_node_id == node.id, BalancerTeam.exported_team_id == Team.id)
                .scalar_subquery()
            )
        elif mode == "draft":
            place = (
                sa.select(sa.func.min(DraftTeam.draft_position))
                .join(DraftSession, DraftSession.id == DraftTeam.session_id)
                .where(DraftSession.formation_node_id == node.id, DraftTeam.exported_team_id == Team.id)
                .scalar_subquery()
            )
        else:
            place = None
        team_ids = await session.scalars(
            sa.select(Team.id)
            .where(
                Team.tournament_id == node.tournament_id,
                sa.or_(Team.formation_node_id == node.id, Team.formation_node_id.is_(None)),
            )
            .order_by(*([] if place is None else [place.asc().nulls_last()]), Team.id)
        )
        return [ResultRow(None, team_id) for team_id in team_ids]

    async def _stage_rows(self, session: AsyncSession, node: FlowNode) -> list[ResultRow]:
        """The stage table; ``breakdown`` carries the stage metrics an aggregate formula reads (plan Decision 8)."""
        stage_type = await session.scalar(sa.select(Stage.stage_type).where(Stage.id == node.stage_id))
        if stage_type == StageType.INDIVIDUAL_SWISS:
            players = await session.execute(
                sa.select(
                    PlayerStanding.workspace_member_id,
                    PlayerStanding.points,
                    PlayerStanding.wins,
                    PlayerStanding.draws,
                    PlayerStanding.losses,
                    PlayerStanding.maps_won - PlayerStanding.maps_lost,
                    PlayerStanding.buchholz,
                )
                .where(PlayerStanding.stage_id == node.stage_id)
                .order_by(
                    PlayerStanding.is_qualified.desc(),
                    PlayerStanding.position.asc().nulls_last(),
                    PlayerStanding.points.desc(),
                    PlayerStanding.workspace_member_id,
                )
            )
            return [
                ResultRow(
                    member_id,
                    None,
                    score=points,
                    breakdown={
                        "wins": wins,
                        "draws": draws,
                        "losses": losses,
                        "map_diff": map_diff,
                        "buchholz": buchholz,
                    },
                )
                for member_id, points, wins, draws, losses, map_diff, buchholz in players
            ]
        standings = await session.execute(
            sa.select(
                Standing.team_id,
                Standing.stage_item_id,
                Standing.position,
                Standing.points,
                Standing.tie_group,
                Standing.win,
                Standing.draw,
                Standing.lose,
                Standing.score_differential,
                Standing.buchholz,
                Standing.swiss_status,
            )
            .outerjoin(StageItem, StageItem.id == Standing.stage_item_id)
            .where(Standing.stage_id == node.stage_id)
            .order_by(
                # A seeded team that never played (position 0) ranks last.
                sa.func.coalesce(Standing.position, 0) <= 0,
                Standing.position,
                StageItem.order.asc().nulls_first(),
                Standing.points.desc(),
                Standing.team_id,
            )
        )
        return _share_places(
            _dedup(
                [
                    ResultRow(
                        None,
                        team_id,
                        item_id,
                        position,
                        points,
                        tie_group,
                        {
                            "wins": win,
                            "draws": draw,
                            "losses": lose,
                            "map_diff": score_differential or 0,
                            "buchholz": buchholz or 0,
                            "ffa_score": points if stage_type in FFA_STAGE_TYPES else 0,
                            **({} if swiss_status is None else {"swiss_status": swiss_status}),
                        },
                    )
                    for (
                        team_id,
                        item_id,
                        position,
                        points,
                        tie_group,
                        win,
                        draw,
                        lose,
                        score_differential,
                        buchholz,
                        swiss_status,
                    ) in standings
                ]
            )
        )

    async def _write_results(
        self, session: AsyncSession, node_id: int, port: str, rows: Sequence[ResultRow], state: FlowResultState
    ) -> bool:
        """UPDATE changed, INSERT new and DELETE gone rows of one port, keyed by participant and role; True when any
        was touched. The rank counts inside the row's role (one sequence for a port without roles)."""
        columns = ("rank", "stage_item_id", "item_rank", "score", "tie_group", "breakdown", "state")
        existing = {
            (r.workspace_member_id, r.team_id, r.role): r
            for r in await session.execute(
                sa.select(
                    FlowNodeResult.id,
                    FlowNodeResult.workspace_member_id,
                    FlowNodeResult.team_id,
                    FlowNodeResult.role,
                    *(getattr(FlowNodeResult, c) for c in columns),
                ).where(FlowNodeResult.node_id == node_id, FlowNodeResult.port == port)
            )
        }
        ranks: Counter[str | None] = Counter()
        wanted: dict[tuple[int | None, int | None, str | None], dict[str, Any]] = {}
        for r in rows:
            ranks[r.role] += 1
            wanted[(r.workspace_member_id, r.team_id, r.role)] = {
                "rank": ranks[r.role],
                "stage_item_id": r.stage_item_id,
                "item_rank": r.item_rank,
                "score": r.score,
                "tie_group": r.tie_group,
                "breakdown": r.breakdown,
                "state": state.value,
            }
        gone = [row.id for key, row in existing.items() if key not in wanted]
        updates = [
            {"id": existing[key].id, **values}
            for key, values in wanted.items()
            if key in existing and any(getattr(existing[key], c) != values[c] for c in columns)
        ]
        inserts = [
            {
                "node_id": node_id,
                "port": port,
                "workspace_member_id": key[0],
                "team_id": key[1],
                "role": key[2],
                **values,
            }
            for key, values in wanted.items()
            if key not in existing
        ]
        if gone:
            await session.execute(sa.delete(FlowNodeResult).where(FlowNodeResult.id.in_(gone)))
        if updates:
            await session.execute(sa.update(FlowNodeResult), [_decimal_score(u) for u in updates])
        if inserts:
            await session.execute(sa.insert(FlowNodeResult), [_decimal_score(i) for i in inserts])
        return bool(gone or updates or inserts)


def _tie_key(row: ResultRow) -> tuple[int | None, int] | None:
    """What makes two rows of a stage table tie: one group's tie group, or equal positions of an elimination table."""
    if row.stage_item_id is not None:
        return (row.stage_item_id, row.tie_group) if row.tie_group else None
    return (None, row.item_rank) if row.item_rank is not None else None


def _share_places(rows: list[ResultRow]) -> list[ResultRow]:
    """Stage-wide tie groups: every tied row carries the rank of its run's first row (the head place).

    A group stage stores ties per group (the group's own place); an elimination table has no tie group, only equal
    positions (two semi-final losers are both 3rd). Neither numbering is a stage rank, and two groups reuse numbers.
    """
    keys = [_tie_key(r) for r in rows]
    sizes = Counter(keys)
    heads: dict[tuple[int | None, int], int] = {}
    return [
        replace(r, tie_group=None if key is None or sizes[key] < 2 else heads.setdefault(key, rank))
        for rank, (r, key) in enumerate(zip(rows, keys, strict=True), 1)
    ]


def _decimal_score(values: Mapping[str, object]) -> dict[str, object]:
    return {**values, "score": None if values["score"] is None else Decimal(str(values["score"]))}


flow_engine = FlowEngine()
