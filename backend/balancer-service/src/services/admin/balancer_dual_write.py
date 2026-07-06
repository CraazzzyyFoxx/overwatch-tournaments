"""Write helpers for the balancer subsystem.

These functions synchronize data to the normalized relational tables
(team_slot, balance_variant).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.schemas.team import InternalBalancerTeamsPayload

# ---------------------------------------------------------------------------
# Balance variants + team slots  (replaces roster_json)
# ---------------------------------------------------------------------------


ROLE_NAME_TO_CODE: dict[str, str] = {
    "Tank": "tank",
    "tank": "tank",
    "Damage": "dps",
    "dps": "dps",
    "DPS": "dps",
    "Support": "support",
    "support": "support",
}


async def sync_balance_variants_and_slots(
    session: AsyncSession,
    balance: models.BalancerBalance,
    payload: InternalBalancerTeamsPayload,
    *,
    algorithm: str = "unknown",
) -> None:
    """Create balance_variant and team_slot rows from the saved balance result.

    Called after the BalancerTeam rows for the balance have been persisted.
    """
    # Delete old variants (cascades to team_slots through variant→team FK)
    await session.execute(
        sa.delete(models.BalancerBalanceVariant).where(models.BalancerBalanceVariant.balance_id == balance.id)
    )
    await session.flush()

    # Create single variant (the saved/selected one)
    variant = models.BalancerBalanceVariant(
        balance_id=balance.id,
        variant_number=1,
        algorithm=algorithm,
        objective_score=None,
        statistics_json=None,
        is_selected=True,
    )
    session.add(variant)
    await session.flush()

    # Update balance metadata
    balance.algorithm = algorithm

    # Link teams to variant and create team_slots
    teams_result = await session.execute(
        sa.select(models.BalancerTeam).where(models.BalancerTeam.balance_id == balance.id)
    )
    balancer_teams = {t.balancer_name: t for t in teams_result.scalars().all()}

    for team_data in payload.teams:
        balancer_team = balancer_teams.get(team_data.name)
        if balancer_team is None:
            continue

        balancer_team.variant_id = variant.id

        sort_order = 0
        for role_name, players in team_data.roster.items():
            role_code = ROLE_NAME_TO_CODE.get(role_name, role_name.lower())
            for player_data in players:
                name_normalized = player_data.name.replace(" ", "").strip().lower()

                session.add(
                    models.BalancerTeamSlot(
                        team_id=balancer_team.id,
                        battle_tag_normalized=name_normalized,
                        role=role_code,
                        assigned_rank=player_data.rating,
                        discomfort=player_data.discomfort or 0,
                        is_captain=player_data.is_captain,
                        sort_order=sort_order,
                    )
                )
                sort_order += 1
