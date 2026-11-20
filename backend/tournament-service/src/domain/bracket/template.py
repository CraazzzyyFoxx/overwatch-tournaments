"""Custom bracket templates: an organizer-drawn bracket with seed placeholders.

A template is a ``BracketSkeleton`` written slot-first so an editor can store it.
``U3`` is the third upper-bracket seed and ``L1`` the first lower one, in engine
seed order (``placeholder_seeds``: ``Uk`` -> ``-k``, ``Lk`` -> ``-(upper_seeds + k)``).

A match lists its ``slots``, numbered ``1..n`` the way the encounter seats them,
and a slot that waits for a result names the match it waits on plus the
``source_position`` it takes -- 1 being the winner and 2 the loser.
Generation, preview and seed fill consume ``template_to_skeleton`` like any
generated skeleton; ``validate_template`` keeps a template to the conventions
they rely on.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from shared.core.enums import StageType

from .types import AdvancementEdge, BracketSkeleton, Pairing, third_place_sources

__all__ = (
    "BracketTemplate",
    "TemplateMatch",
    "TemplateProblem",
    "TemplateSlot",
    "skeleton_to_template",
    "template_to_skeleton",
    "validate_template",
)

SeedRef = Annotated[str, StringConstraints(pattern=r"^[UL][1-9][0-9]*$", max_length=5)]
#: The biggest card a drawn match may have, matching the FFA lobby ceiling.
MAX_SLOTS = 100


class TemplateSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Seat of the match, ``1..len(match.slots)``.
    slot: int = Field(ge=1, le=MAX_SLOTS)
    seed: SeedRef | None = None
    source_match: int | None = None
    #: Place in ``source_match``'s standing; 1 is first.
    source_position: int | None = Field(default=None, ge=1, le=MAX_SLOTS)

    @model_validator(mode="after")
    def _exactly_one_origin(self) -> TemplateSlot:
        if (self.seed is None) == (self.source_match is None):
            raise ValueError("a slot takes either a seed or a source match, not both and not neither")
        if (self.source_match is None) != (self.source_position is None):
            raise ValueError("a slot fed by a match names the position it takes, and only such a slot does")
        return self


class TemplateMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=0, le=10_000)
    round: int = Field(ge=-256, le=256)
    slots: list[TemplateSlot] = Field(min_length=2, max_length=MAX_SLOTS)

    @model_validator(mode="after")
    def _slots_are_the_whole_card(self) -> TemplateMatch:
        if [slot.slot for slot in self.slots] != list(range(1, len(self.slots) + 1)):
            raise ValueError("slots must be numbered 1..n in order, with no gap and no repeat")
        return self


class BracketTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    upper_seeds: int = Field(ge=2, le=512)
    lower_seeds: int = Field(ge=0, le=512)
    # One extra card for a validated third-place match; ``validate_template`` enforces the old cap otherwise.
    matches: list[TemplateMatch] = Field(min_length=1, max_length=257)


@dataclass(frozen=True)
class TemplateProblem:
    match_id: int | None
    slot: int | None
    code: str
    message: str


def _seed_id(seed: str, upper_seeds: int) -> int:
    number = int(seed[1:])
    return -number if seed[0] == "U" else -(upper_seeds + number)


def template_to_skeleton(template: BracketTemplate) -> BracketSkeleton:
    """The placeholder skeleton a VALIDATED template draws (``local_id`` = list index)."""
    position_of = {match.id: position for position, match in enumerate(template.matches)}
    pairings: list[Pairing] = []
    edges: list[AdvancementEdge] = []
    for position, match in enumerate(template.matches):
        team_ids: list[int | None] = []
        for slot in match.slots:
            team_ids.append(_seed_id(slot.seed, template.upper_seeds) if slot.seed is not None else None)
            if slot.source_match is not None:
                edges.append(
                    AdvancementEdge(
                        source_local_id=position_of[slot.source_match],
                        source_position=slot.source_position,
                        target_local_id=position,
                        target_slot=slot.slot,
                    )
                )
        pairings.append(
            Pairing(
                team_ids=tuple(team_ids),
                round_number=match.round,
                local_id=position,
            )
        )
    total_rounds = max((match.round for match in template.matches if match.round > 0), default=0)
    return BracketSkeleton(pairings=pairings, total_rounds=total_rounds, advancement_edges=edges)


def skeleton_to_template(skeleton: BracketSkeleton, *, upper_seeds: int, lower_seeds: int) -> BracketTemplate:
    """A generated placeholder skeleton as an editable template (``id`` = ``local_id``)."""
    incoming = {(edge.target_local_id, edge.target_slot): edge for edge in skeleton.advancement_edges}

    def slot(pairing: Pairing, index: int) -> TemplateSlot:
        team = pairing.team_ids[index]
        if team is not None:
            number = -team
            return TemplateSlot(
                slot=index + 1,
                seed=f"U{number}" if number <= upper_seeds else f"L{number - upper_seeds}",
            )
        edge = incoming[(pairing.local_id, index + 1)]
        return TemplateSlot(slot=index + 1, source_match=edge.source_local_id, source_position=edge.source_position)

    return BracketTemplate(
        upper_seeds=upper_seeds,
        lower_seeds=lower_seeds,
        matches=[
            TemplateMatch(
                id=pairing.local_id,
                round=pairing.round_number,
                slots=[slot(pairing, index) for index in range(pairing.slot_count)],
            )
            for pairing in skeleton.pairings
        ],
    )


def _terminal_third_place(
    terminals: list[TemplateMatch],
    by_id: dict[int, TemplateMatch],
    feeds: dict[tuple[int, int], tuple[int, int]],
    stage_type: StageType,
) -> TemplateMatch | None:
    if len(terminals) != 2 or stage_type not in (StageType.SINGLE_ELIMINATION, StageType.DOUBLE_ELIMINATION):
        return None
    a, b = terminals
    if a.round != b.round or a.round <= 0:
        return None
    for bronze, title in ((a, b), (b, a)):
        if len(bronze.slots) != 2 or not all(slot.source_position == 2 for slot in bronze.slots):
            continue
        if (bronze.id, 2) in feeds:  # Its winner is already terminal; its loser must be out too.
            continue
        double_elimination = stage_type == StageType.DOUBLE_ELIMINATION
        winner_targets = {
            source: target
            for (source, position), (target, _) in feeds.items()
            if position == 1 and (by_id[source].round < 0) == double_elimination
        }
        expected = third_place_sources(title.id, winner_targets, double_elimination=double_elimination)
        # A wider feeder would leave more than one team on the provisional place bronze replaces.
        if all(len(by_id[source].slots) == 2 for source in expected) and {
            slot.source_match for slot in bronze.slots
        } == set(expected):
            return bronze
    return None


def validate_template(template: BracketTemplate, stage_type: StageType) -> list[TemplateProblem]:
    """Every convention ``template`` breaks, in match order; ``[]`` when it is sound."""
    problems: list[TemplateProblem] = []

    def add(code: str, message: str, match_id: int | None = None, slot: int | None = None) -> None:
        problems.append(TemplateProblem(match_id=match_id, slot=slot, code=code, message=message))

    by_id: dict[int, TemplateMatch] = {}
    for match in template.matches:
        if match.id in by_id:
            add("duplicate_id", f"Match id {match.id} is used twice", match.id)
        by_id[match.id] = match
        if match.round == 0:
            add("zero_round", "Round 0 does not exist: upper rounds are positive, lower rounds negative", match.id)
    if problems:
        # References cannot be judged until ids and rounds are sound.
        return problems

    seeded = Counter(slot.seed for match in template.matches for slot in match.slots if slot.seed is not None)
    feeds: dict[tuple[int, int], tuple[int, int]] = {}  # (source, position) -> (target, slot)
    lower_to_upper: list[tuple[int, int, int]] = []
    for match in template.matches:
        for slot in match.slots:
            if slot.seed is not None:
                pool, number = slot.seed[0], int(slot.seed[1:])
                limit = template.upper_seeds if pool == "U" else template.lower_seeds
                bracket = "upper" if pool == "U" else "lower"
                if number > limit:
                    add("seed_out_of_range", f"{slot.seed} is past the {limit} {bracket} seeds", match.id, slot.slot)
                elif seeded[slot.seed] > 1:
                    # Both slots are flagged: an editor highlights the conflict, not one side of it.
                    add("seed_duplicate", f"{slot.seed} is seeded twice", match.id, slot.slot)
                if (pool == "U") != (match.round > 0):
                    # Round 0 is already out (``zero_round`` returns early).
                    add(
                        "seed_bracket",
                        f"{slot.seed} is {'an upper' if bracket == 'upper' else 'a lower'} seed; "
                        f"it starts in the {bracket} bracket",
                        match.id,
                        slot.slot,
                    )
                continue
            source = by_id.get(slot.source_match)
            if source is None or slot.source_match == match.id:
                add("unknown_match", f"Match {slot.source_match} does not exist", match.id, slot.slot)
                continue
            if slot.source_position > len(source.slots):
                add(
                    "position_out_of_range",
                    f"Match {source.id} seats {len(source.slots)}; it has no position {slot.source_position}",
                    match.id,
                    slot.slot,
                )
                continue
            key = (slot.source_match, slot.source_position)
            if key in feeds:
                add(
                    "result_reused",
                    f"Position {slot.source_position} of match {slot.source_match} "
                    f"already goes to match {feeds[key][0]}",
                    match.id,
                    slot.slot,
                )
                continue
            feeds[key] = (match.id, slot.slot)
            source_upper, target_upper = source.round > 0, match.round > 0
            if source_upper and target_upper and match.round <= source.round:
                add("edge_direction", f"Round {source.round} cannot feed round {match.round}", match.id, slot.slot)
            elif not source_upper and not target_upper and -match.round <= -source.round:
                add("edge_direction", f"Round {source.round} cannot feed round {match.round}", match.id, slot.slot)
            elif source_upper and not target_upper and slot.source_position == 1:
                add(
                    "edge_direction",
                    "Only a losing position drops from the upper bracket to the lower one",
                    match.id,
                    slot.slot,
                )
            elif not source_upper and target_upper:
                lower_to_upper.append((match.id, slot.slot, slot.source_position))

    for pool, count in (("U", template.upper_seeds), ("L", template.lower_seeds)):
        for number in range(1, count + 1):
            if f"{pool}{number}" not in seeded:
                add("seed_unused", f"{pool}{number} is not seeded into any match")

    upper_rounds = sorted({match.round for match in template.matches if match.round > 0})
    if upper_rounds != list(range(1, len(upper_rounds) + 1)):
        add("round_gap", "Upper rounds must run 1, 2, 3… without a gap")
    # Lower rounds carry no contiguity rule: the generator numbers an LB round after
    # the upper round whose losers drop into it and skips the ones that are all byes,
    # so a valid bracket's lower rounds may start below -1 and have holes.
    # ``edge_direction`` and ``final`` still keep them forward-only and connected.

    terminals = [match for match in template.matches if (match.id, 1) not in feeds]
    bronze = _terminal_third_place(terminals, by_id, feeds, stage_type)
    if bronze is not None:
        terminals.remove(bronze)
    if bronze is None and len(template.matches) > 256:
        add("too_many_matches", "A bracket has at most 256 matches, plus its third-place match")
    final: TemplateMatch | None = None
    if not terminals:
        add("final", "Every match feeds another one, so the bracket has no final")
    elif len(terminals) > 1:
        for match in terminals:
            add(
                "final",
                f"The first place of match {match.id} goes nowhere: only the final may end the bracket",
                match.id,
            )
    else:
        final = terminals[0]
        top_round = upper_rounds[-1] if upper_rounds else None
        if final.round != top_round or any(
            match is not final and match is not bronze and match.round == top_round for match in template.matches
        ):
            add("final", "Only the championship and its third-place match may share the last upper round", final.id)

    bronze_id = bronze.id if bronze is not None else None
    for target_id, slot_number, position in lower_to_upper:
        if target_id == bronze_id:
            continue
        if position != 1:
            add("edge_direction", "Only the first place leaves the lower bracket", target_id, slot_number)
        elif final is None or target_id != final.id:
            add("edge_direction", "A lower-bracket winner can only go to the final", target_id, slot_number)

    # Where every losing position of a match ends up, if anywhere.
    losing_edges = [
        (source, by_id[target], slot)
        for (source, position), (target, slot) in feeds.items()
        if position > 1 and target != bronze_id
    ]
    drops = {source: target for source, target, _ in losing_edges}
    if stage_type == StageType.DOUBLE_ELIMINATION and final is not None:
        if not any(
            slot.source_match is not None and by_id.get(slot.source_match, final).round < 0 for slot in final.slots
        ):
            add("de_final_needs_lower", "The final needs the lower bracket's winner in one of its slots", final.id)
        for match in template.matches:
            if match is bronze:
                continue
            is_final = match.id == final.id
            drop = drops.get(match.id)
            if match.round > 0 and not is_final and drop is None:
                add("de_upper_loser", f"The loser of match {match.id} must drop to the lower bracket", match.id)
        for source_id, target, slot_number in losing_edges:
            source = by_id[source_id]
            if source.round > 0 and source.id != final.id and target.round > 0:
                add("de_upper_loser", f"Every losing place of match {source.id} must drop", target.id, slot_number)
            if source.round < 0 or source.id == final.id:
                add(
                    "de_lower_loser", f"The loser of match {source.id} is out; it cannot go to another match", target.id
                )
    if stage_type == StageType.SINGLE_ELIMINATION:
        has_lower = any(match.round < 0 for match in template.matches)
        if template.lower_seeds or drops or has_lower:
            add("se_shape", "Single elimination has no lower bracket and no loser drops")
    return problems
