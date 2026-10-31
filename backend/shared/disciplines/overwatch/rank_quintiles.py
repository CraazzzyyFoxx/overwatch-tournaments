"""Rank quintiles of the expectation axis (``impact_v2`` design §5).

A player's quintile is the mid-rank percentile of their rank for the role they played, among the players of that role
in the same owner (a tournament, or a pickup mix). ``quintile_of`` is the pure rule; ``match_quintiles`` reads the
ranks of every owner a batch of encounters belongs to.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core.impact import IMPACT_ROLES, MIN_RANK_POPULATION, RANK_QUINTILES

__all__ = ("match_quintiles", "quintile_of")

#: ``("tournament" | "mix", owner id)``
_Owner = tuple[str, int]


def quintile_of(value: float | None, population: Sequence[float]) -> int | None:
    """``min(4, floor(5p))`` of the mid-rank percentile ``p`` of ``value`` in ``population``; ``None`` when the
    population is smaller than ``MIN_RANK_POPULATION`` or there is no value."""
    if value is None or len(population) < MIN_RANK_POPULATION:
        return None
    ordered = sorted(population)
    below, upto = bisect_left(ordered, value), bisect_right(ordered, value)
    percentile = (below + 0.5 * (upto - below)) / len(ordered)
    return min(RANK_QUINTILES - 1, int(RANK_QUINTILES * percentile))


async def match_quintiles(session: AsyncSession, wanted: Iterable[tuple[int, int, str]]) -> dict[tuple[int, int], int]:
    """``(encounter_id, member_id, role) -> quintile`` of the rank for that role in the encounter's owner.

    ``role`` is a top-level role code (``tank``/``damage``/``support``). Members without a quintile (no rank, or fewer
    than ``MIN_RANK_POPULATION`` ranked players of the role in the owner) are absent from the result.
    """
    wanted = list(wanted)
    if not wanted:
        return {}
    encounter = models.Encounter
    owners: dict[int, _Owner] = {}
    for encounter_id, tournament_id, mix_id in await session.execute(
        sa.select(encounter.id, encounter.tournament_id, encounter.custom_game_id).where(
            encounter.id.in_({encounter_id for encounter_id, _, _ in wanted})
        )
    ):
        owners[encounter_id] = ("tournament", tournament_id) if tournament_id is not None else ("mix", mix_id)

    values: dict[tuple[_Owner, int, str], float] = {}
    population: dict[tuple[_Owner, str], list[float]] = defaultdict(list)
    await _tournament_values(session, {o[1] for o in owners.values() if o[0] == "tournament"}, values, population)
    await _mix_values(session, {o[1] for o in owners.values() if o[0] == "mix"}, values, population)
    for ranks in population.values():
        ranks.sort()  # quintile_of re-sorts per call; sorting an ordered list is linear

    out: dict[tuple[int, int], int] = {}
    for encounter_id, member_id, role in wanted:
        owner = owners.get(encounter_id)
        if owner is None:
            continue
        quintile = quintile_of(values.get((owner, member_id, role)), population[(owner, role)])
        if quintile is not None:
            out[(encounter_id, member_id)] = quintile
    return out


async def _tournament_values(
    session: AsyncSession,
    tournament_ids: set[int],
    values: dict[tuple[_Owner, int, str], float],
    population: dict[tuple[_Owner, str], list[float]],
) -> None:
    """A rostered member's value for each role: their registration rank for it, else their roster rank. The role's
    population is the members rostered in that role, at their value for it."""
    if not tournament_ids:
        return
    player = models.Player
    roster = (
        await session.execute(
            sa.select(player.tournament_id, player.workspace_member_id, player.role, player.rank)
            .where(player.tournament_id.in_(tournament_ids))
            .distinct(player.tournament_id, player.workspace_member_id)
            .order_by(player.tournament_id, player.workspace_member_id, player.is_substitution.asc(), player.id.desc())
        )
    ).all()
    registered: dict[tuple[int, int, str], int] = {}
    reg, role = models.Registration, models.RegistrationRole
    for tournament_id, member_id, code, rank in await session.execute(
        sa.select(reg.tournament_id, reg.workspace_member_id, role.role, role.rank_value)
        .join(role, role.registration_id == reg.id)
        .where(
            reg.tournament_id.in_(tournament_ids),
            reg.deleted_at.is_(None),
            reg.workspace_member_id.is_not(None),
            role.rank_value.is_not(None),
            role.role.in_(IMPACT_ROLES),
        )
        .order_by(role.priority, role.id)
    ):
        registered.setdefault((tournament_id, member_id, code), rank)
    for tournament_id, member_id, rostered_role, rank in roster:
        owner = ("tournament", tournament_id)
        for code in IMPACT_ROLES:
            value = registered.get((tournament_id, member_id, code), rank)
            if value is None:
                continue
            values[(owner, member_id, code)] = float(value)
            if code == rostered_role:
                population[(owner, code)].append(float(value))


async def _mix_values(
    session: AsyncSession,
    mix_ids: set[int],
    values: dict[tuple[_Owner, int, str], float],
    population: dict[tuple[_Owner, str], list[float]],
) -> None:
    """The member's latest seat rank (> 0) per rated role over the mix's encounters; a role's population is the
    members seated in it."""
    if not mix_ids:
        return
    seat, seat_role, leaf, parent = (
        models.EncounterTeamMember,
        models.EncounterTeamMemberRole,
        models.CatalogRole,
        aliased(models.CatalogRole),
    )
    code = sa.func.coalesce(parent.code, leaf.code)
    rows = await session.execute(
        sa.select(models.Encounter.custom_game_id, seat.workspace_member_id, code, seat.rank)
        .select_from(seat)
        .join(models.Encounter, models.Encounter.id == seat.encounter_id)
        .join(seat_role, seat_role.team_member_id == seat.id)
        .join(leaf, leaf.id == seat_role.role_id)
        .join(models.RoleDimension, sa.and_(models.RoleDimension.id == leaf.dimension_id, models.RoleDimension.rated))
        .outerjoin(parent, parent.id == leaf.parent_role_id)
        .where(models.Encounter.custom_game_id.in_(mix_ids), seat.rank > 0, code.in_(IMPACT_ROLES))
        .order_by(models.Encounter.id.desc(), seat.id.desc())
    )
    for mix_id, member_id, role, rank in rows:
        key = (("mix", mix_id), member_id, role)
        if key not in values:
            values[key] = float(rank)
            population[(("mix", mix_id), role)].append(float(rank))
