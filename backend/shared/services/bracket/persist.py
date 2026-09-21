"""Write a BracketSkeleton as Encounter + EncounterLink rows."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.stage import Stage
from shared.repository import EncounterRepository
from shared.services.bracket.advancement import persist_advancement_edges
from shared.services.bracket.types import BracketSkeleton
from shared.domain.encounter_naming import build_encounter_name_from_ids

__all__ = ("persist_skeleton",)

_encounters = EncounterRepository()


async def persist_skeleton(
    session: AsyncSession,
    *,
    stage: Stage,
    skeleton: BracketSkeleton,
    stage_item_id: int | None,
    team_names_by_id: dict[int, str],
    best_of_for_round,
    is_elimination: bool,
    lb_stage_item_id: int | None = None,
) -> list[Encounter]:
    """Insert pairings in skeleton order and persist advancement edges.

    ``best_of_for_round(round_number, *, is_final)`` resolves BoN. Negative
    rounds go to ``lb_stage_item_id`` when that item exists.
    """
    encounters: list[Encounter] = []
    local_to_encounter: dict[int, Encounter] = {}
    max_round = max((pairing.round_number for pairing in skeleton.pairings), default=0)
    for pairing in skeleton.pairings:
        item_id = lb_stage_item_id if lb_stage_item_id is not None and pairing.round_number < 0 else stage_item_id
        encounter = Encounter(
            name=build_encounter_name_from_ids(
                pairing.home_team_id,
                pairing.away_team_id,
                team_names_by_id,
            ),
            home_team_id=pairing.home_team_id,
            away_team_id=pairing.away_team_id,
            home_score=0,
            away_score=0,
            round=pairing.round_number,
            best_of=best_of_for_round(
                pairing.round_number,
                is_final=is_elimination and pairing.round_number == max_round,
            ),
            tournament_id=stage.tournament_id,
            stage_id=stage.id,
            stage_item_id=item_id,
            status=enums.EncounterStatus.OPEN,
        )
        encounters.append(encounter)
        local_to_encounter[pairing.local_id] = encounter

    # One ``add_all`` + one flush for the whole skeleton: a per-pairing create
    # would cost a round trip per encounter, and the advancement edges below
    # need every id at once anyway.
    await _encounters.create_many(session, encounters)
    await persist_advancement_edges(
        session,
        edges=skeleton.advancement_edges,
        local_to_encounter_id={local_id: encounter.id for local_id, encounter in local_to_encounter.items()},
    )
    return encounters
