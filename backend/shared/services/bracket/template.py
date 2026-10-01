"""Custom bracket templates: an organizer-drawn bracket with seed placeholders.

A template is a ``BracketSkeleton`` written slot-first so an editor can store it.
``U3`` is the third upper-bracket seed and ``L1`` the first lower one, in engine
seed order (``placeholder_seeds``: ``Uk`` -> ``-k``, ``Lk`` -> ``-(upper_seeds + k)``).
Generation, preview and seed fill consume ``template_to_skeleton`` like any
generated skeleton; ``validate_template`` keeps a template to the conventions
they rely on (spec 2026-10-01 §5.2).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from shared.core.enums import StageType

from .types import AdvancementEdge, BracketSkeleton, Pairing

__all__ = (
    "BracketTemplate",
    "TemplateMatch",
    "TemplateProblem",
    "TemplateSlot",
    "skeleton_to_template",
    "template_to_skeleton",
    "validate_template",
)

SeedRef = Annotated[str, StringConstraints(pattern=r"^[UL][1-9][0-9]*$")]
Side = Literal["home", "away"]
_SIDES: tuple[Side, Side] = ("home", "away")


class TemplateSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: SeedRef | None = None
    winner_of: int | None = None
    loser_of: int | None = None

    @model_validator(mode="after")
    def _exactly_one_origin(self) -> TemplateSlot:
        if sum(value is not None for value in (self.seed, self.winner_of, self.loser_of)) != 1:
            raise ValueError("a slot takes exactly one of seed, winner_of, loser_of")
        return self


class TemplateMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=0)
    round: int
    home: TemplateSlot
    away: TemplateSlot


class BracketTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    upper_seeds: int = Field(ge=2)
    lower_seeds: int = Field(ge=0)
    matches: list[TemplateMatch] = Field(min_length=1, max_length=256)


@dataclass(frozen=True)
class TemplateProblem:
    match_id: int | None
    slot: Side | None
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
        teams: dict[str, int | None] = {}
        for side in _SIDES:
            slot: TemplateSlot = getattr(match, side)
            teams[side] = _seed_id(slot.seed, template.upper_seeds) if slot.seed is not None else None
            source = slot.winner_of if slot.winner_of is not None else slot.loser_of
            if source is not None:
                edges.append(
                    AdvancementEdge(
                        source_local_id=position_of[source],
                        target_local_id=position,
                        role="winner" if slot.winner_of is not None else "loser",
                        target_slot=side,
                    )
                )
        pairings.append(
            Pairing(
                home_team_id=teams["home"],
                away_team_id=teams["away"],
                round_number=match.round,
                local_id=position,
            )
        )
    total_rounds = max((match.round for match in template.matches if match.round > 0), default=0)
    return BracketSkeleton(pairings=pairings, total_rounds=total_rounds, advancement_edges=edges)


def skeleton_to_template(skeleton: BracketSkeleton, *, upper_seeds: int, lower_seeds: int) -> BracketTemplate:
    """A generated placeholder skeleton as an editable template (``id`` = ``local_id``)."""
    incoming = {(edge.target_local_id, edge.target_slot): edge for edge in skeleton.advancement_edges}

    def slot(pairing: Pairing, side: Side) -> TemplateSlot:
        team = pairing.home_team_id if side == "home" else pairing.away_team_id
        if team is not None:
            number = -team
            return TemplateSlot(seed=f"U{number}" if number <= upper_seeds else f"L{number - upper_seeds}")
        edge = incoming[(pairing.local_id, side)]
        if edge.role == "winner":
            return TemplateSlot(winner_of=edge.source_local_id)
        return TemplateSlot(loser_of=edge.source_local_id)

    return BracketTemplate(
        upper_seeds=upper_seeds,
        lower_seeds=lower_seeds,
        matches=[
            TemplateMatch(
                id=pairing.local_id,
                round=pairing.round_number,
                home=slot(pairing, "home"),
                away=slot(pairing, "away"),
            )
            for pairing in skeleton.pairings
        ],
    )


def validate_template(template: BracketTemplate, stage_type: StageType) -> list[TemplateProblem]:
    """Every way ``template`` breaks spec §5.2, in match order; ``[]`` when it is sound."""
    problems: list[TemplateProblem] = []

    def add(code: str, message: str, match_id: int | None = None, slot: Side | None = None) -> None:
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

    seeded = Counter(
        slot.seed for match in template.matches for slot in (match.home, match.away) if slot.seed is not None
    )
    feeds: dict[tuple[int, str], tuple[int, Side]] = {}  # (source, role) -> (target, slot)
    lower_to_upper: list[tuple[int, Side]] = []
    for match in template.matches:
        for side in _SIDES:
            slot: TemplateSlot = getattr(match, side)
            if slot.seed is not None:
                pool, number = slot.seed[0], int(slot.seed[1:])
                limit = template.upper_seeds if pool == "U" else template.lower_seeds
                if number > limit:
                    bracket = "upper" if pool == "U" else "lower"
                    add("seed_out_of_range", f"{slot.seed} is past the {limit} {bracket} seeds", match.id, side)
                elif seeded[slot.seed] > 1:
                    # Both slots are flagged: an editor highlights the conflict, not one side of it.
                    add("seed_duplicate", f"{slot.seed} is seeded twice", match.id, side)
                continue
            role = "winner" if slot.winner_of is not None else "loser"
            source_id = slot.winner_of if slot.winner_of is not None else slot.loser_of
            source = by_id.get(source_id)
            if source is None or source_id == match.id:
                add("unknown_match", f"Match {source_id} does not exist", match.id, side)
                continue
            if (source_id, role) in feeds:
                target_id = feeds[(source_id, role)][0]
                add(
                    "result_reused",
                    f"The {role} of match {source_id} already goes to match {target_id}",
                    match.id,
                    side,
                )
                continue
            feeds[(source_id, role)] = (match.id, side)
            source_upper, target_upper = source.round > 0, match.round > 0
            if source_upper and target_upper and match.round <= source.round:
                add("edge_direction", f"Round {source.round} cannot feed round {match.round}", match.id, side)
            elif not source_upper and not target_upper and -match.round <= -source.round:
                add("edge_direction", f"Round {source.round} cannot feed round {match.round}", match.id, side)
            elif source_upper and not target_upper and role != "loser":
                add("edge_direction", "Only a loser drops from the upper bracket to the lower one", match.id, side)
            elif not source_upper and target_upper:
                if role != "winner":
                    add("edge_direction", "Only a winner leaves the lower bracket", match.id, side)
                else:
                    lower_to_upper.append((match.id, side))

    for pool, count in (("U", template.upper_seeds), ("L", template.lower_seeds)):
        for number in range(1, count + 1):
            if f"{pool}{number}" not in seeded:
                add("seed_unused", f"{pool}{number} is not seeded into any match")

    upper_rounds = sorted({match.round for match in template.matches if match.round > 0})
    lower_rounds = sorted({-match.round for match in template.matches if match.round < 0})
    if upper_rounds != list(range(1, len(upper_rounds) + 1)):
        add("round_gap", "Upper rounds must run 1, 2, 3… without a gap")
    # Lower rounds carry no contiguity rule: the generator numbers an LB round after
    # the upper round whose losers drop into it and skips the ones that are all byes,
    # so a valid bracket's lower rounds may start below -1 and have holes.
    # ``edge_direction`` and ``final`` still keep them forward-only and connected.

    terminals = [match for match in template.matches if (match.id, "winner") not in feeds]
    final: TemplateMatch | None = None
    if not terminals:
        add("final", "Every match feeds another one, so the bracket has no final")
    elif len(terminals) > 1:
        for match in terminals:
            add("final", f"The winner of match {match.id} goes nowhere: only the final may end the bracket", match.id)
    else:
        final = terminals[0]
        top_round = upper_rounds[-1] if upper_rounds else None
        if final.round != top_round or sum(1 for match in template.matches if match.round == top_round) != 1:
            add("final", "The final must be the only match of the last upper round", final.id)

    for target_id, side in lower_to_upper:
        if final is None or target_id != final.id:
            add("edge_direction", "A lower-bracket winner can only go to the final", target_id, side)

    loser_target = {source: by_id[target] for (source, role), (target, _) in feeds.items() if role == "loser"}
    if stage_type == StageType.DOUBLE_ELIMINATION and final is not None:
        if not any(
            slot.winner_of is not None and slot.winner_of in by_id and by_id[slot.winner_of].round < 0
            for slot in (final.home, final.away)
        ):
            add("de_final_needs_lower", "The final needs the lower bracket's winner in one of its slots", final.id)
        for match in template.matches:
            is_final = match.id == final.id
            drop = loser_target.get(match.id)
            if match.round > 0 and not is_final and (drop is None or drop.round > 0):
                add("de_upper_loser", f"The loser of match {match.id} must drop to the lower bracket", match.id)
            if (match.round < 0 or is_final) and drop is not None:
                add("de_lower_loser", f"The loser of match {match.id} is out; it cannot go to another match", drop.id)
    if stage_type == StageType.SINGLE_ELIMINATION and (template.lower_seeds or lower_rounds or loser_target):
        add("se_shape", "Single elimination has no lower bracket and no loser drops")
    return problems
