"""Export a completed draft to tournament teams/players.

Reuses the proven ``team_flows.bulk_create_from_balancer`` path by synthesizing
a ``BalancerTeam`` payload from the final rosters, and mirrors
``export_balance``'s idempotent cleanup (delete prior ``exported_team_id`` rows
before re-import, then backfill the links by ``balancer_name``).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPlayerStatus, DraftStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.models.draft import DraftPlayer, DraftSession, DraftTeam

from src import models
from src.schemas.team import BalancerTeam, BalancerTeamMember
from src.services import team as team_flows


def _err(code: str, msg: str, status_code: int = 409) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(code=code, msg=msg)])


def _draft_to_balancer_payload(
    teams: list[DraftTeam],
    roster_by_team: dict[int, list[DraftPlayer]],
) -> list[BalancerTeam]:
    """Pure mapping: draft rosters -> balancer export payload.

    The team name is the captain's battle_tag/name so the export's
    ``find_by_battle_tag`` resolves the captain; members carry their
    battle_tag, role (tank/dps/support), and rank.
    """
    payload: list[BalancerTeam] = []
    for team in sorted(teams, key=lambda t: t.draft_position):
        roster = roster_by_team.get(team.id, [])
        captain = next((p for p in roster if p.is_captain), None)
        team_name = (captain.battle_tag if captain and captain.battle_tag else None) or team.name

        members: list[BalancerTeamMember] = []
        total_sr = 0
        for p in roster:
            rank = p.rank_value or 0
            total_sr += rank
            members.append(
                BalancerTeamMember(
                    uuid=str(p.user_id) if p.user_id is not None else str(uuid4()),
                    name=p.battle_tag or "",
                    sub_role=p.sub_role,
                    role=p.primary_role,  # already tank/dps/support
                    rank=rank,
                )
            )
        avg_sr = (total_sr / len(members)) if members else 0.0
        payload.append(BalancerTeam(uuid=uuid4(), name=team_name, avgSr=avg_sr, totalSr=total_sr, members=members))
    return payload


async def export(session: AsyncSession, draft_session: DraftSession) -> tuple[DraftSession, int, int]:
    """Export a COMPLETED draft. Returns (session, removed_teams, imported_teams)."""
    if draft_session.status != DraftStatus.COMPLETED.value:
        raise _err("draft_not_completed", "Only a completed draft can be exported")

    teams = (await session.scalars(sa.select(DraftTeam).where(DraftTeam.session_id == draft_session.id))).all()
    roster_rows = (
        await session.scalars(
            sa.select(DraftPlayer).where(
                DraftPlayer.session_id == draft_session.id,
                DraftPlayer.status == DraftPlayerStatus.PICKED.value,
            )
        )
    ).all()
    roster_by_team: dict[int, list[DraftPlayer]] = defaultdict(list)
    for p in roster_rows:
        if p.drafted_by_team_id is not None:
            roster_by_team[p.drafted_by_team_id].append(p)

    payload = _draft_to_balancer_payload(list(teams), roster_by_team)

    # Idempotent cleanup of any prior export (mirror export_balance).
    linked_ids = [t.exported_team_id for t in teams if t.exported_team_id is not None]
    removed = len(linked_ids)
    if linked_ids:
        await session.execute(sa.delete(models.Standing).where(models.Standing.team_id.in_(linked_ids)))
        await session.execute(sa.delete(models.Player).where(models.Player.team_id.in_(linked_ids)))
        await session.execute(sa.delete(models.Team).where(models.Team.id.in_(linked_ids)))
        for t in teams:
            t.exported_team_id = None
        await session.flush()

    # bulk_create_from_balancer commits internally.
    await team_flows.bulk_create_from_balancer(session, draft_session.tournament_id, payload)

    # Backfill exported_team_id by balancer_name.
    imported_names = [p.name for p in payload]
    created = (
        await session.scalars(
            sa.select(models.Team).where(
                models.Team.tournament_id == draft_session.tournament_id,
                models.Team.balancer_name.in_(imported_names),
            )
        )
    ).all()
    by_name = {t.balancer_name: t for t in created}
    for team, p in zip(teams, payload, strict=False):
        public_team = by_name.get(p.name)
        if public_team is not None:
            team.exported_team_id = public_team.id

    draft_session.exported_at = datetime.now(UTC)
    draft_session.export_status = "success"
    await session.flush()
    await session.refresh(draft_session)
    return draft_session, removed, len(payload)
