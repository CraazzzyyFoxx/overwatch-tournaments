"""Advancement service: materialises winner/loser edges in the DB
(``EncounterLink`` rows) and auto-fills target encounter slots when an
encounter's score is finalised.

Called from:
- Bracket generation (``admin/stage.py::generate_encounters``) — after
  creating encounters, the service wires up links using local_id → encounter.id
  mapping returned from :func:`shared.services.bracket.engine.generate_bracket`.
- Encounter score update hooks (captain submission, admin override, logs
  parser) — when ``status`` transitions to COMPLETED and a winner is
  determinable, propagate to every linked target.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.models.encounter import Encounter
from shared.models.encounter_link import EncounterLink
from shared.models.stage import Stage
from shared.models.team import Team
from shared.services.bracket.types import AdvancementEdge
from shared.services.encounter_naming import build_encounter_name_from_ids

__all__ = (
    "persist_advancement_edges",
    "advance_winner",
)


async def persist_advancement_edges(
    session: AsyncSession,
    *,
    edges: Iterable[AdvancementEdge],
    local_to_encounter_id: dict[int, int],
) -> list[EncounterLink]:
    """Create EncounterLink rows from bracket-engine AdvancementEdges.

    Silently skips edges referencing an unknown local_id (can happen if a
    pairing was not persisted — e.g. bye-induced matches).
    """
    links: list[EncounterLink] = []
    for edge in edges:
        source_id = local_to_encounter_id.get(edge.source_local_id)
        target_id = local_to_encounter_id.get(edge.target_local_id)
        if source_id is None or target_id is None:
            continue

        role = (
            enums.EncounterLinkRole.WINNER
            if edge.role == "winner"
            else enums.EncounterLinkRole.LOSER
        )
        slot = (
            enums.EncounterLinkSlot.HOME
            if edge.target_slot == "home"
            else enums.EncounterLinkSlot.AWAY
        )
        link = EncounterLink(
            source_encounter_id=source_id,
            target_encounter_id=target_id,
            role=role,
            target_slot=slot,
        )
        session.add(link)
        links.append(link)

    if links:
        await session.flush()
    return links


async def advance_winner(
    session: AsyncSession,
    encounter: Encounter,
) -> list[Encounter]:
    """Propagate the winner/loser of an encounter into every linked target.

    Additionally, if this encounter is a Grand Final in a double-elimination
    bracket AND the LB champion (the team that came via the "LB final winner"
    edge) won it, lazily materialise a Grand Final Reset match.

    Returns the list of target encounters that were created or updated.
    Callers should commit the session; this function only flushes.
    """
    if (
        encounter.home_team_id is None
        or encounter.away_team_id is None
        or encounter.status != enums.EncounterStatus.COMPLETED
    ):
        return []
    if encounter.home_score == encounter.away_score:
        return []

    winner_id = (
        encounter.home_team_id
        if encounter.home_score > encounter.away_score
        else encounter.away_team_id
    )
    loser_id = (
        encounter.away_team_id
        if encounter.home_score > encounter.away_score
        else encounter.home_team_id
    )

    links = (
        (
            await session.execute(
                sa.select(EncounterLink).where(
                    EncounterLink.source_encounter_id == encounter.id
                )
            )
        )
        .scalars()
        .all()
    )

    updated: list[Encounter] = []
    for link in links:
        target = await session.get(
            Encounter,
            link.target_encounter_id,
            with_for_update=True,
        )
        if target is None:
            logger.warning(
                "EncounterLink %s points to missing target encounter %s",
                link.id,
                link.target_encounter_id,
            )
            continue

        team_id = winner_id if link.role == enums.EncounterLinkRole.WINNER else loser_id
        if link.target_slot == enums.EncounterLinkSlot.HOME:
            target.home_team_id = team_id
        else:
            target.away_team_id = team_id
        target.name = await _build_encounter_name_for_ids(
            session,
            home_team_id=target.home_team_id,
            away_team_id=target.away_team_id,
        )
        updated.append(target)

    reset_match = await _maybe_create_grand_final_reset(session, encounter, winner_id)
    if reset_match is not None:
        updated.append(reset_match)

    if updated:
        await session.flush()
    return updated


async def _maybe_create_grand_final_reset(
    session: AsyncSession,
    gf_encounter: Encounter,
    gf_winner_id: int,
) -> Encounter | None:
    """Lazily create a Grand Final Reset match when the LB champion wins GF.

    Rules:
    - Encounter belongs to a double-elimination stage.
    - Encounter is the highest currently materialised positive round in its
      bracket item (the original Grand Final, not UB Final / Reset).
    - The GF winner must be the team that reached GF via the
      LB-final → GF winner-edge (target_slot = AWAY in our generator).
    - No Reset match exists yet for this stage_item_id.
    """
    if gf_encounter.stage_id is None or gf_encounter.round <= 0:
        return None

    stage = await session.get(Stage, gf_encounter.stage_id)
    if stage is None or stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
        return None

    max_round_result = await session.execute(
        sa.select(sa.func.max(Encounter.round)).where(
            Encounter.tournament_id == gf_encounter.tournament_id,
            Encounter.stage_id == gf_encounter.stage_id,
            Encounter.stage_item_id == gf_encounter.stage_item_id,
            Encounter.round > 0,
        )
    )
    max_positive_round = max_round_result.scalar_one()
    if max_positive_round != gf_encounter.round:
        return None
    if gf_encounter.away_team_id != gf_winner_id:
        # UB champion won — tournament ends, no reset.
        return None

    existing_reset = await session.execute(
        sa.select(Encounter)
        .where(
            Encounter.tournament_id == gf_encounter.tournament_id,
            Encounter.stage_id == gf_encounter.stage_id,
            Encounter.stage_item_id == gf_encounter.stage_item_id,
            Encounter.round == gf_encounter.round + 1,
        )
        .with_for_update()
    )
    if existing_reset.scalar_one_or_none() is not None:
        return None

    reset = Encounter(
        name=await _build_encounter_name_for_ids(
            session,
            home_team_id=gf_encounter.home_team_id,
            away_team_id=gf_encounter.away_team_id,
        ),
        home_team_id=gf_encounter.home_team_id,
        away_team_id=gf_encounter.away_team_id,
        home_score=0,
        away_score=0,
        round=gf_encounter.round + 1,
        tournament_id=gf_encounter.tournament_id,
        stage_id=gf_encounter.stage_id,
        stage_item_id=gf_encounter.stage_item_id,
        status=enums.EncounterStatus.OPEN,
    )
    session.add(reset)
    await session.flush()
    logger.info(
        "Created Grand Final Reset for tournament=%s stage=%s (LB champion won GF)",
        gf_encounter.tournament_id,
        gf_encounter.stage_id,
    )
    return reset


async def _build_encounter_name_for_ids(
    session: AsyncSession,
    *,
    home_team_id: int | None,
    away_team_id: int | None,
) -> str:
    team_ids = {
        team_id
        for team_id in (home_team_id, away_team_id)
        if team_id is not None
    }
    if not team_ids:
        return build_encounter_name_from_ids(home_team_id, away_team_id, {})

    result = await session.execute(
        sa.select(Team.id, Team.name).where(Team.id.in_(team_ids))
    )
    team_names_by_id = dict(result.all())
    return build_encounter_name_from_ids(
        home_team_id,
        away_team_id,
        team_names_by_id,
    )
