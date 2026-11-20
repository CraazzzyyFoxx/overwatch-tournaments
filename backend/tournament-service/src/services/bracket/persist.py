"""Write a ``BracketSkeleton`` as encounters, seats, positions and links.

Four tables, one pass: ``encounter.encounter`` (the card), ``encounter.team``
(the seats, through the participation writer), ``tournament.bracket_encounter``
(where it sits in the bracket) and ``tournament.encounter_link`` (how a place
moves into a seat).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.domain.encounter_naming import build_encounter_name_from_ids
from shared.models.encounter.encounter import Encounter
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.stage import Stage
from shared.models.tournament.tournament import Tournament
from shared.repository import BracketEncounterRepository, EncounterRepository
from shared.services.encounter.participants import MemberSnapshot, place_team
from src.domain.bracket import BracketSkeleton
from src.services.bracket.advancement import persist_advancement_edges

__all__ = ("SeatTeam", "persist_skeleton")

_encounters = EncounterRepository()
_positions = BracketEncounterRepository()


@dataclass(frozen=True, slots=True)
class SeatTeam:
    """One tournament team as the bracket seats it.

    ``members`` is the roster snapshot the participation keeps; advancement
    carries it into the next round, so a team seeded without one plays the
    whole bracket without a line-up on record.
    """

    name: str
    seed: int | None = None
    members: Sequence[MemberSnapshot] = field(default_factory=tuple)


async def persist_skeleton(
    session: AsyncSession,
    *,
    stage: Stage,
    skeleton: BracketSkeleton,
    stage_item_id: int | None,
    teams_by_id: Mapping[int, SeatTeam],
    best_of_for_round,
    is_elimination: bool,
    lb_stage_item_id: int | None = None,
) -> list[Encounter]:
    """Insert pairings in skeleton order, seat them, and wire the links.

    ``best_of_for_round(round_number, *, is_final)`` resolves BoN for a pairing
    without its own ``best_of``. Negative
    rounds go to ``lb_stage_item_id`` when that item exists. A team id the
    skeleton seeds but ``teams_by_id`` does not name is seated anyway, under
    the name "TBD", as the display name shows it.
    """
    tournament = await session.get_one(Tournament, stage.tournament_id)
    names_by_id = {team_id: seat.name for team_id, seat in teams_by_id.items()}
    encounters: list[Encounter] = []
    by_local_id: dict[int, Encounter] = {}
    third_place_ids = skeleton.third_place_ids if is_elimination else set()
    max_round = max(
        (pairing.round_number for pairing in skeleton.pairings if pairing.local_id not in third_place_ids), default=0
    )
    for pairing in skeleton.pairings:
        encounter = Encounter(
            workspace_id=tournament.workspace_id,
            discipline=tournament.discipline,
            tournament_id=tournament.id,
            scoring_rule_id=stage.scoring_rule_id,
            name=build_encounter_name_from_ids(pairing.team_ids, names_by_id),
            slot_count=pairing.slot_count,
            best_of=pairing.best_of
            if pairing.best_of is not None
            else best_of_for_round(
                pairing.round_number,
                is_final=is_elimination
                and pairing.round_number == max_round
                and pairing.local_id not in third_place_ids,
            ),
            status=enums.EncounterStatus.OPEN,
        )
        encounters.append(encounter)
        by_local_id[pairing.local_id] = encounter

    # One ``add_all`` + one flush for the whole skeleton: a per-pairing create
    # would cost a round trip per encounter, and the bracket rows and links
    # below need every id at once anyway.
    await _encounters.create_many(session, encounters)
    await _positions.create_many(
        session,
        [
            BracketEncounter(
                encounter_id=by_local_id[pairing.local_id].id,
                tournament_id=tournament.id,
                stage_id=stage.id,
                stage_item_id=(
                    lb_stage_item_id if lb_stage_item_id is not None and pairing.round_number < 0 else stage_item_id
                ),
                round=pairing.round_number,
            )
            for pairing in skeleton.pairings
        ],
    )

    for pairing in skeleton.pairings:
        encounter = by_local_id[pairing.local_id]
        for index, team_id in enumerate(pairing.team_ids):
            if team_id is None:
                continue
            seat = teams_by_id.get(team_id)
            await place_team(
                session,
                encounter,
                slot=index + 1,
                team_id=team_id,
                name=seat.name if seat is not None else "TBD",
                seed=seat.seed if seat is not None else None,
                members=seat.members if seat is not None else (),
            )

    await persist_advancement_edges(
        session,
        edges=skeleton.advancement_edges,
        encounters_by_local_id=by_local_id,
    )
    return encounters
