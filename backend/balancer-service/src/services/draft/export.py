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

from shared.core.enums import DraftPickStatus, DraftPlayerStatus, DraftStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from src import models
from src.schemas.team import BalancerTeam, BalancerTeamMember
from src.services import team as team_flows
from src.services.draft import loaders, ranks


def _err(code: str, msg: str, status_code: int = 409) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(code=code, msg=msg)])


def _draft_to_balancer_payload(
    teams: list[DraftTeam],
    roster_by_team: dict[int, list[DraftPlayer]],
    pick_by_player_id: dict[int, DraftPick] | None = None,
) -> list[BalancerTeam]:
    """Pure mapping: draft rosters -> balancer export payload.

    The team name is the captain's battle_tag/name so the export's
    ``find_by_battle_tag`` resolves the captain; members carry their
    battle_tag, the role they were *drafted on* (tank/dps/support), and the
    rank for that role. Mirrors the balancer's own payload (assigned role +
    assigned rating) so both feed ``bulk_create_from_balancer`` identically.
    """
    pick_by_player_id = pick_by_player_id or {}
    payload: list[BalancerTeam] = []
    for team in sorted(teams, key=lambda t: t.draft_position):
        roster = roster_by_team.get(team.id, [])
        captain = next((p for p in roster if p.is_captain), None)
        team_name = (captain.battle_tag if captain and captain.battle_tag else None) or team.name

        members: list[BalancerTeamMember] = []
        total_sr = 0
        for p in roster:
            pk = pick_by_player_id.get(p.id)
            # Drafted role + its rank. Captains have no pick -> primary role.
            role = (pk.target_role if (pk and pk.target_role) else None) or p.primary_role
            if pk is not None and pk.target_rank_value is not None:
                rank = pk.target_rank_value
            else:
                rank = ranks.role_rank(p, role) or 0
            total_sr += rank
            members.append(
                BalancerTeamMember(
                    uuid=str(p.user_id) if p.user_id is not None else str(uuid4()),
                    name=p.battle_tag or "",
                    sub_role=p.sub_role,
                    role=role,  # tank/dps/support
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
            sa.select(DraftPlayer)
            .where(
                DraftPlayer.session_id == draft_session.id,
                DraftPlayer.status == DraftPlayerStatus.PICKED.value,
            )
            # payload reads p.user_id and ranks.role_rank(p, ...) -> role_ranks.
            .options(*loaders.player_options())
        )
    ).all()
    roster_by_team: dict[int, list[DraftPlayer]] = defaultdict(list)
    for p in roster_rows:
        if p.drafted_by_team_id is not None:
            roster_by_team[p.drafted_by_team_id].append(p)

    # Resolved picks carry the drafted role + its rank (frozen at finalize).
    pick_rows = (
        await session.scalars(
            sa.select(DraftPick).where(
                DraftPick.session_id == draft_session.id,
                DraftPick.status.in_(
                    [DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value]
                ),
            )
        )
    ).all()
    pick_by_player_id = {pk.picked_player_id: pk for pk in pick_rows if pk.picked_player_id is not None}

    payload = _draft_to_balancer_payload(list(teams), roster_by_team, pick_by_player_id)

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
