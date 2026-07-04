"""Balance-export event emission for analytics snapshots.

When a balance is exported to a tournament, balancer-service emits a
``balance_exported`` domain event (via the transactional outbox, atomic with the
balance mutation). analytics-service consumes it and owns the writes to
``analytics.balance_snapshot`` + ``analytics.balance_player_snapshot`` — balancer
no longer writes into the analytics schema.

All the per-player derivation (identity resolution, division lookup, off-role
flagging) stays here because it needs balancer's registrations + division grid;
the fully denormalized result rides in the event payload so the consumer never
reaches back into balancer's schema.
"""

from __future__ import annotations

import math

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.messaging.config import BALANCER_EVENTS_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.platform.outbox import EventOutbox
from shared.schemas.events import BalanceExportedEvent, BalancePlayerSnapshotData
from src import models
from src.schemas.team import InternalBalancerTeamsPayload
from src.services.balancer.algorithm.role_entries import resolve_division_from_rank

BALANCE_EXPORTED_ROUTING_KEY = "balancer.balance.exported"

ROLE_NAME_TO_CODE: dict[str, str] = {
    "Tank": "tank",
    "tank": "tank",
    "Damage": "dps",
    "dps": "dps",
    "DPS": "dps",
    "Support": "support",
    "support": "support",
}


async def enqueue_balance_exported_event(
    session: AsyncSession,
    balance: models.BalancerBalance,
    payload: InternalBalancerTeamsPayload,
    exported_teams: dict[str, models.Team],
) -> EventOutbox | None:
    """Enqueue a ``balance_exported`` outbox event at balance export time.

    Runs inside the same transaction as the balance export, so the event is
    persisted atomically with the mutation and later relayed by the outbox
    dispatcher. analytics-service consumes it and writes the snapshot tables.

    Args:
        balance: The BalancerBalance being exported.
        payload: Parsed balance result payload.
        exported_teams: Map of balancer_name -> tournament.Team (just created).

    Returns:
        The enqueued EventOutbox row, or ``None`` when there is nothing to export.
    """
    if not payload.teams:
        return None

    # Collect all individual player ratings for aggregate metrics
    all_ratings: list[int] = []
    for team in payload.teams:
        for players in team.roster.values():
            for player in players:
                all_ratings.append(player.rating)

    avg_sr_overall = sum(all_ratings) / len(all_ratings) if all_ratings else 0.0
    sr_range = max(all_ratings) - min(all_ratings) if len(all_ratings) > 1 else 0.0
    sr_std_dev = (
        math.sqrt(sum((r - avg_sr_overall) ** 2 for r in all_ratings) / len(all_ratings))
        if all_ratings
        else 0.0
    )

    # Resolve variant if exists
    variant_id = None
    if balance.variants:
        selected = next((v for v in balance.variants if v.is_selected), None)
        if selected:
            variant_id = selected.id

    # Build registration lookup (battle_tag_normalized -> registration, roles eagerly
    # loaded). Registrations are the source of truth for player identity (via the
    # workspace_member anchor) and per-role rank.
    reg_result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == balance.tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
        )
        .options(
            selectinload(models.BalancerRegistration.roles),
            # The member anchor is the only path to the player id (user_id below).
            selectinload(models.BalancerRegistration.workspace_member),
        )
    )
    reg_lookup: dict[str, models.BalancerRegistration] = {}
    for reg in reg_result.scalars().all():
        if reg.battle_tag_normalized:
            reg_lookup[reg.battle_tag_normalized] = reg

    player_rows: list[BalancePlayerSnapshotData] = []
    total_discomfort = 0
    off_role_count = 0

    for team_data in payload.teams:
        tournament_team = exported_teams.get(team_data.name)
        tournament_team_id = tournament_team.id if tournament_team else None

        for role_name, players in team_data.roster.items():
            role_code = ROLE_NAME_TO_CODE.get(role_name, role_name.lower())

            for player in players:
                discomfort = player.discomfort or 0
                total_discomfort += discomfort

                name_normalized = player.name.replace(" ", "").strip().lower()
                registration = reg_lookup.get(name_normalized)
                user_id = (
                    registration.workspace_member.player_id
                    if registration is not None and registration.workspace_member is not None
                    else None
                )

                preferred_role: str | None = None
                was_off_role = False
                if player.preferences:
                    pref_display = player.preferences[0]
                    preferred_role = ROLE_NAME_TO_CODE.get(pref_display, pref_display.lower())
                    was_off_role = preferred_role != role_code
                if was_off_role:
                    off_role_count += 1

                # Derive division_number from the registration role matching the assigned
                # role (registrations store rank, not division). Uses the canonical
                # in-code DEFAULT_GRID: the per-tournament grid loader was moved out of
                # balancer-service (commit bdd942ff, service-boundary cleanup), and
                # DEFAULT_GRID is the scale analytics normalizes divisions against.
                division_number: int | None = None
                if registration is not None:
                    matching_role = next(
                        (r for r in registration.roles if r.role == role_code),
                        None,
                    )
                    if matching_role is not None:
                        division_number = resolve_division_from_rank(matching_role.rank_value)

                player_rows.append(
                    BalancePlayerSnapshotData(
                        user_id=user_id,
                        team_id=tournament_team_id,
                        assigned_role=role_code,
                        preferred_role=preferred_role,
                        assigned_rank=player.rating,
                        discomfort=discomfort,
                        division_number=division_number,
                        is_captain=player.is_captain,
                        was_off_role=was_off_role,
                    )
                )

    event = BalanceExportedEvent(
        tournament_id=balance.tournament_id,
        balance_id=balance.id,
        variant_id=variant_id,
        workspace_id=balance.workspace_id,
        algorithm=balance.algorithm or "unknown",
        division_scope=balance.division_scope,
        division_grid_json=balance.division_grid_json,
        team_count=len(payload.teams),
        player_count=len(player_rows),
        avg_sr_overall=round(avg_sr_overall, 2),
        sr_std_dev=round(sr_std_dev, 2),
        sr_range=round(sr_range, 2),
        total_discomfort=total_discomfort,
        off_role_count=off_role_count,
        objective_score=None,
        players=player_rows,
        source_service="balancer-service",
    )

    return await enqueue_outbox_event(
        session,
        event,
        exchange=BALANCER_EVENTS_EXCHANGE,
        routing_key=BALANCE_EXPORTED_ROUTING_KEY,
    )
