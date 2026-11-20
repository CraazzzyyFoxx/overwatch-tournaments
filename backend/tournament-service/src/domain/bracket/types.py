"""The format-neutral shape of a bracket: seats and places, not sides.

An encounter seats ``slot_count`` participations, so a pairing is a sequence
of team ids -- index ``i`` is slot ``i + 1`` -- and an edge between two of them
names the PLACE it moves (``source_position``: 1 is the winner, 2 the loser)
and the SEAT it fills (``target_slot``). Nothing here knows about home and away.
"""

from dataclasses import dataclass, field

__all__ = (
    "Pairing",
    "AdvancementEdge",
    "BracketSkeleton",
)


@dataclass(frozen=True)
class AdvancementEdge:
    """``source_position`` of ``source_local_id`` fills ``target_slot`` of
    ``target_local_id``, within one skeleton.

    ``local_id`` values are skeleton-local (0-based); the consumer translates
    them to real DB encounter ids when persisting the ``EncounterLink`` rows.
    """

    source_local_id: int
    #: Place in the source encounter's final standing; 1 is first.
    source_position: int
    target_local_id: int
    #: Seat of the target encounter, ``1..slot_count``.
    target_slot: int


@dataclass(frozen=True)
class Pairing:
    """One encounter: ``team_ids[i]`` is seeded into slot ``i + 1``, ``None``
    when the seat waits for an advancement edge."""

    team_ids: tuple[int | None, ...]
    round_number: int
    name: str = ""
    local_id: int = 0  # Position in the pairings list (bracket-local identity)
    #: The encounter's own series length; ``None`` = the stage's per-round rule.
    best_of: int | None = None

    @property
    def slot_count(self) -> int:
        return len(self.team_ids)


@dataclass(frozen=True)
class BracketSkeleton:
    """Complete bracket structure with all pairings and advancement edges."""

    pairings: list[Pairing]
    total_rounds: int
    advancement_edges: list[AdvancementEdge] = field(default_factory=list)
    bye_team_id: int | None = None

    @property
    def third_place_ids(self) -> set[int]:
        """Positive-round matches whose incoming edges all carry a losing position."""
        losing, other = set(), set()
        for edge in self.advancement_edges:
            if edge.source_position > 1:
                losing.add(edge.target_local_id)
            else:
                other.add(edge.target_local_id)
        losing.difference_update(other)
        return {p.local_id for p in self.pairings if p.round_number > 0 and p.local_id in losing}


def third_place_sources(final_id: int, winner_targets: dict[int, int], *, double_elimination: bool) -> list[int]:
    """Trace winners from the relevant bracket (upper for SE, lower for DE) back from the title."""
    sources = [source for source, target in winner_targets.items() if target == final_id]
    if double_elimination:
        if len(sources) != 1:
            return []
        lower_final = sources[0]
        sources.extend(source for source, target in winner_targets.items() if target == lower_final)
    return sources if len(sources) == 2 else []


def append_third_place(pairings: list[Pairing], edges: list[AdvancementEdge], *, double_elimination: bool) -> None:
    """Append bronze to a generated bracket, whose last pairing is still the title."""
    final = pairings[-1]
    winner_targets = {
        edge.source_local_id: edge.target_local_id
        for edge in edges
        if edge.source_position == 1 and (pairings[edge.source_local_id].round_number < 0) == double_elimination
    }
    sources = third_place_sources(final.local_id, winner_targets, double_elimination=double_elimination)
    if sources:
        bronze_id = len(pairings)
        pairings.append(
            Pairing(team_ids=(None, None), round_number=final.round_number, name="Third Place", local_id=bronze_id)
        )
        edges.extend(AdvancementEdge(source, 2, bronze_id, slot) for slot, source in enumerate(sources, start=1))
