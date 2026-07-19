"""Small deterministic bipartite matcher shared by balancer and live draft.

The matcher intentionally knows nothing about players or roles.  Callers map
their domain objects to unique candidate/slot identifiers and provide the
eligible edges.  An augmenting-path pass then finds a maximum matching.
"""

from __future__ import annotations

from collections.abc import Collection, Hashable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

CandidateT = TypeVar("CandidateT", bound=Hashable)
SlotT = TypeVar("SlotT", bound=Hashable)


@dataclass(frozen=True)
class BipartiteMatching(Generic[CandidateT, SlotT]):
    slot_to_candidate: dict[SlotT, CandidateT]
    candidate_to_slot: dict[CandidateT, SlotT]
    unmatched_slots: tuple[SlotT, ...]
    unmatched_candidates: tuple[CandidateT, ...]

    @property
    def matched_count(self) -> int:
        return len(self.slot_to_candidate)


def maximum_bipartite_matching(
    *,
    candidates: Collection[CandidateT],
    slots: Collection[SlotT],
    eligible_slots: Mapping[CandidateT, Collection[SlotT]],
) -> BipartiteMatching[CandidateT, SlotT]:
    """Return a maximum candidate-to-slot matching.

    Input order is retained for deterministic reports. Duplicate candidate or
    slot identifiers are collapsed because identifiers represent graph nodes.
    Edges to unknown slots are ignored.
    """

    candidate_order = tuple(dict.fromkeys(candidates))
    slot_order = tuple(dict.fromkeys(slots))
    known_slots = set(slot_order)
    edges = {
        candidate: tuple(dict.fromkeys(slot for slot in eligible_slots.get(candidate, ()) if slot in known_slots))
        for candidate in candidate_order
    }
    slot_to_candidate: dict[SlotT, CandidateT] = {}

    def try_match(candidate: CandidateT, visited_slots: set[SlotT]) -> bool:
        for slot in edges[candidate]:
            if slot in visited_slots:
                continue
            visited_slots.add(slot)
            owner = slot_to_candidate.get(slot)
            if owner is None or try_match(owner, visited_slots):
                slot_to_candidate[slot] = candidate
                return True
        return False

    for candidate in candidate_order:
        if len(slot_to_candidate) == len(slot_order):
            break
        try_match(candidate, set())

    candidate_to_slot = {candidate: slot for slot, candidate in slot_to_candidate.items()}
    return BipartiteMatching(
        slot_to_candidate={slot: slot_to_candidate[slot] for slot in slot_order if slot in slot_to_candidate},
        candidate_to_slot={
            candidate: candidate_to_slot[candidate]
            for candidate in candidate_order
            if candidate in candidate_to_slot
        },
        unmatched_slots=tuple(slot for slot in slot_order if slot not in slot_to_candidate),
        unmatched_candidates=tuple(candidate for candidate in candidate_order if candidate not in candidate_to_slot),
    )


__all__ = ("BipartiteMatching", "maximum_bipartite_matching")
