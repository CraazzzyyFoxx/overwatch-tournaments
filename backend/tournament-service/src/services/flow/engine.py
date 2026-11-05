"""Flow recompute (spec §5.4, §8.1): derives every node's output rows from the tournament's current state.

Lifecycle nodes read their rows from the registration, team and standings tables; filter and merge compute them from
their inputs. Rows are updated in place so ids stay stable (plan Decision 5). Lifecycle statuses are never written here.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.core.enums import FlowNodeKind, FlowNodeStatus, FlowResultState, StageType
from shared.domain.flow.config import FilterNodeConfig, RegistrationNodeConfig, parse_node_config
from shared.domain.flow.validate import topological_order
from shared.models.balancer.balance import BalancerBalance, BalancerTeam
from shared.models.draft.draft import DraftSession, DraftTeam
from shared.models.registration.registration import Registration, RegistrationEntry, RegistrationTeam
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.player_standing import PlayerStanding
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Team
from src.domain.flow.compute import ResultRow, compute_filter, compute_merge

__all__ = ("FlowEngine", "FlowRecomputeReport", "flow_engine")

_LIFECYCLE_PORT = {
    FlowNodeKind.REGISTRATION: "participants",
    FlowNodeKind.FORMATION: "teams",
    FlowNodeKind.STAGE: "ranking",
}
_PURE_PORT = {FlowNodeKind.FILTER: "passed", FlowNodeKind.MERGE: "merged"}
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
        for n in nodes:
            if n.kind not in _LIFECYCLE_PORT and n.kind not in _PURE_PORT:
                raise ValueError(f"flow node {n.id} of kind {n.kind} is not computed in phase 2")
        order = topological_order(by_id, ((e.source_node_id, e.target_node_id) for e in edges))
        if order is None:
            raise ValueError(f"flow of tournament {tournament_id} contains a cycle")
        incoming: defaultdict[int, list[FlowEdge]] = defaultdict(list)
        for e in edges:
            incoming[e.target_node_id].append(e)
        item_order = await self._item_order(session, tournament_id) if any(n.kind == "filter" for n in nodes) else {}

        outputs: dict[tuple[int, str], tuple[list[ResultRow], FlowResultState]] = {}
        changed: list[int] = []
        for node_id in order:
            node = by_id[node_id]
            kind = FlowNodeKind(node.kind)
            port = _LIFECYCLE_PORT.get(kind) or _PURE_PORT[kind]
            status = None
            if kind in _LIFECYCLE_PORT:
                loader = {
                    FlowNodeKind.REGISTRATION: self._registration_rows,
                    FlowNodeKind.FORMATION: self.formation_rows,
                    FlowNodeKind.STAGE: self._stage_rows,
                }[kind]
                rows, state = await loader(session, node), self._lifecycle_state(node)
            else:
                sources = [outputs.get((e.source_node_id, e.source_port)) for e in incoming[node_id]]
                if not sources or not all(s and s[0] for s in sources):
                    rows, state, status = [], FlowResultState.TENTATIVE, FlowNodeStatus.PENDING
                else:
                    ready = [s for s in sources if s]
                    if kind == FlowNodeKind.FILTER:
                        config = parse_node_config(kind, node.config)
                        assert isinstance(config, FilterNodeConfig)
                        rows = compute_filter(config, ready[0][0], item_order=item_order)
                    else:
                        rows = compute_merge([s[0] for s in ready])
                    final = all(s[1] == FlowResultState.FINAL for s in ready)
                    state = FlowResultState.FINAL if final else FlowResultState.TENTATIVE
                    status = FlowNodeStatus(state.value)
            outputs[(node_id, port)] = (rows, state)
            moved = await self._write_results(session, node_id, port, rows, state)
            if status is not None and status != node.status:
                await session.execute(sa.update(FlowNode).where(FlowNode.id == node_id).values(status=status.value))
                moved = True
            if moved:
                changed.append(node_id)
        await session.flush()
        return FlowRecomputeReport(tuple(changed))

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
        if (
            await session.scalar(sa.select(Stage.stage_type).where(Stage.id == node.stage_id))
            == StageType.INDIVIDUAL_SWISS
        ):
            players = await session.execute(
                sa.select(PlayerStanding.workspace_member_id, PlayerStanding.points)
                .where(PlayerStanding.stage_id == node.stage_id)
                .order_by(
                    PlayerStanding.is_qualified.desc(),
                    PlayerStanding.position.asc().nulls_last(),
                    PlayerStanding.points.desc(),
                    PlayerStanding.workspace_member_id,
                )
            )
            return [ResultRow(member_id, None, score=points) for member_id, points in players]
        standings = await session.execute(
            sa.select(Standing.team_id, Standing.stage_item_id, Standing.position, Standing.points, Standing.tie_group)
            .outerjoin(StageItem, StageItem.id == Standing.stage_item_id)
            .where(Standing.stage_id == node.stage_id)
            .order_by(Standing.position, StageItem.order.asc().nulls_first(), Standing.points.desc(), Standing.team_id)
        )
        return _dedup(
            [
                ResultRow(None, team_id, item_id, position, points, tie_group)
                for team_id, item_id, position, points, tie_group in standings
            ]
        )

    async def _write_results(
        self, session: AsyncSession, node_id: int, port: str, rows: Sequence[ResultRow], state: FlowResultState
    ) -> bool:
        """UPDATE changed, INSERT new and DELETE gone rows of one port, keyed by participant; True when any was touched."""
        columns = ("rank", "stage_item_id", "item_rank", "score", "tie_group", "breakdown", "state")
        existing = {
            (r.workspace_member_id, r.team_id): r
            for r in await session.execute(
                sa.select(
                    FlowNodeResult.id,
                    FlowNodeResult.workspace_member_id,
                    FlowNodeResult.team_id,
                    *(getattr(FlowNodeResult, c) for c in columns),
                ).where(FlowNodeResult.node_id == node_id, FlowNodeResult.port == port)
            )
        }
        wanted = {
            (r.workspace_member_id, r.team_id): {
                "rank": rank,
                "stage_item_id": r.stage_item_id,
                "item_rank": r.item_rank,
                "score": r.score,
                "tie_group": r.tie_group,
                "breakdown": r.breakdown,
                "state": state.value,
            }
            for rank, r in enumerate(rows, 1)
        }
        gone = [row.id for key, row in existing.items() if key not in wanted]
        updates = [
            {"id": existing[key].id, **values}
            for key, values in wanted.items()
            if key in existing and any(getattr(existing[key], c) != values[c] for c in columns)
        ]
        inserts = [
            {"node_id": node_id, "port": port, "workspace_member_id": key[0], "team_id": key[1], **values}
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


def _decimal_score(values: Mapping[str, object]) -> dict[str, object]:
    return {**values, "score": None if values["score"] is None else Decimal(str(values["score"]))}


flow_engine = FlowEngine()
