"""Shared pick-ban helpers: round-1 seeding and the room's side-pick gates.

The seed vocabulary ``pick_ban_session`` calls -- which PARTICIPATION opens
round 1, and where that answer came from -- plus the two gates the RESULT paths
have to ask of the room: :func:`side_pick_pending` and
:func:`side_pick_required`.

Seeding reads the bracket, never the card's order: a seat's slot says where a
team sits, not how it was ranked. The bracket slot it was fed into comes first,
the previous stage's standing second, and with neither the first seat opens --
``VetoSeedSource.FALLBACK_FIRST_SLOT``.

This module imports no service, which is what lets ``games``, ``map_report``
and ``pick_ban_session`` all read it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import MapVetoMode, MapVetoSessionStatus, PickBanKind, VetoSeedSource
from shared.disciplines import discipline as discipline_spec
from shared.domain import pick_ban_rules as pbr
from shared.domain.pick_ban_config import pick_config
from shared.models.encounter.team import EncounterTeam
from shared.models.tournament.pick_ban import PickBanConfig
from shared.repository import BracketEncounterRepository, PickBanConfigRepository, PickBanSessionRepository
from shared.repository.pick_ban import CONFIG_ROOM_LOAD

_positions = BracketEncounterRepository()
_configs = PickBanConfigRepository()
_sessions = PickBanSessionRepository()

REASON_TEAMS_UNKNOWN = "teams_unknown"
REASON_NOT_CONFIGURED = "not_configured"
REASON_SLOT_COUNT_MISMATCH = "slot_count_mismatch"
REASON_SLOT_UNDERFILLED = "slot_underfilled"
REASON_BRACKET_PREVIEW = "bracket_preview"

SLOT_CANDIDATE_FLOOR = 2

#: A pick-ban room is a contest between two seats; a lobby has nobody to veto
#: against. Lives here rather than on ``pick_ban_session`` so ``room_reconcile``
#: -- which that module imports -- can read it without a cycle.
ROOM_SLOT_COUNT = 2


def side_codes(encounter: models.Encounter) -> tuple[str, ...]:
    """The sides a ``side_pick`` step hands out for this encounter.

    Empty for a discipline with no sides, and for one whose side count does
    not match the card -- the same gate the ruleset validator applies, so a
    session that somehow holds a ``side_pick`` it may not play refuses it
    here too rather than writing half a game row.
    """
    sides = discipline_spec(encounter.discipline).sides
    return sides if len(sides) == encounter.slot_count else ()


def rounds_are_progressive(config: PickBanConfig, kind: PickBanKind) -> bool:
    """Whether this config's rounds are created one map at a time.

    Slot mode says so structurally -- one slot IS one map of the series --,
    progressive mode says so by name, and every hero config says so by domain:
    heroes are banned per map, never once per series. A flat ``kind=map`` pool
    config is the classic veto, one sequence that settles the whole series' map
    order up front, and stays single-round (``PickBanEntry.round IS NULL``).
    """
    return config.mode in (MapVetoMode.SLOTS, MapVetoMode.PROGRESSIVE) or kind == PickBanKind.HERO


async def side_pick_pending(session: AsyncSession, encounter_id: int, position: int) -> bool:
    """Whether series position ``position`` still owes a ``side_pick`` an answer.

    A game cannot START while the side it is played on is undecided: the
    position may be named, but no claim and no accepted result may
    land on it until the pick resolves -- or the clock flips a coin for it.

    Read straight off ``resolved_sequence_json`` and the submission log rather
    than through the step objects: the result paths must not have to load a
    room's whole runtime to ask one question, and an UNBOUND step (``actors:
    []``, waiting on this very pick) counts as pending by the same rule.
    """
    rows = (
        await session.execute(
            select(models.PickBanSession.id, models.PickBanSession.resolved_sequence_json).where(
                models.PickBanSession.encounter_id == encounter_id,
                # A cancelled room is the organizer's opt-out: its unanswered
                # step must not refuse every claim of the series forever.
                models.PickBanSession.status != MapVetoSessionStatus.CANCELLED,
            )
        )
    ).all()
    owed: dict[int, set[int | None]] = {}
    for session_id, sequence in rows:
        for step in sequence or []:
            if step.get("action") != "side_pick" or (step.get("round") or 1) != position:
                continue
            actors = step.get("actors") or []
            if not actors:
                return True  # unbound: the pick itself has not been resolved
            owed.setdefault(session_id, set())
            for actor in actors:
                owed[session_id].add((step["index"], actor))
    if not owed:
        return False
    for session_id, keys in owed.items():
        answered = {
            (row.step_index, row.encounter_team_id)
            for row in (
                await session.execute(
                    select(models.PickBanSubmission).where(
                        models.PickBanSubmission.session_id == session_id,
                        models.PickBanSubmission.state == "revealed",
                    )
                )
            ).scalars()
        }
        if keys - answered:
            return True
    return False


async def side_pick_required(session: AsyncSession, encounter: models.Encounter, position: int) -> bool:
    """Whether the room picks position ``position``'s sides -- so its game may
    not start, nor take a result, without both of them.

    Per kind, the room's ruleset is the live session's snapshot, or -- before
    the room opens -- the config the cascade resolves for this encounter, so a
    room the captains have not readied yet cannot be played around. A CANCELLED
    session ends that kind's answer: the organizer opted the room out. Only the
    phase the engine would select for that game counts (the same ``RoundCtx``
    session creation and the round append select with); a flat ruleset describes
    position 1 alone.
    """
    for kind in (PickBanKind.MAP, PickBanKind.HERO):
        pick_ban = await _sessions.get_for_encounter(session, encounter_id=encounter.id, kind=kind)
        if pick_ban is not None:
            if pick_ban.status == MapVetoSessionStatus.CANCELLED:
                continue
            ruleset_json, progressive = pick_ban.ruleset_json, bool((pick_ban.pool_json or {}).get("progressive"))
        else:
            bracket = await _positions.get_position(session, encounter.id)
            config = pick_config(
                await _configs.list_by_tournament(
                    session, encounter.tournament_id, kind=kind, options=CONFIG_ROOM_LOAD
                ),
                stage_id=bracket.stage_id if bracket is not None else None,
                round=bracket.round if bracket is not None else None,
            )
            if config is None:
                continue
            ruleset_json, progressive = config.ruleset_json, rounds_are_progressive(config, kind)
        if position > 1 and not progressive:
            continue
        try:
            ruleset = pbr.parse_ruleset(ruleset_json)
        except pbr.RulesetError:
            continue  # a room that cannot be played cannot open either
        phase = pbr.select_phase(
            ruleset,
            pbr.RoundCtx(round=position if progressive else 1, best_of=max(encounter.best_of, 1), kind=kind.value),
        )
        if phase is not None and any(step.action == "side_pick" for step in phase.steps):
            return True
    return False


@dataclass(frozen=True)
class SeedResolution:
    """Who opens round 1, and on what evidence.

    ``opener`` is a participation id; ``seeds`` is ``{participation: seed}`` for
    every seat the source could rank, kept so the journal records what the
    decision was made on (the session row stores only the two).
    """

    opener: int
    seed_source: VetoSeedSource
    seeds: dict[int, int]


def decide_seeds(ordered: list[EncounterTeam], seeds: dict[int, int], source: VetoSeedSource) -> SeedResolution:
    """Pure seed decision: the lowest seed opens, ties fall back to the first slot.

    ``ordered`` is the encounter's live seats in slot order, so "the first
    slot" is simply the first of them.
    """
    ranked = [(seeds[team.id], team.slot, team.id) for team in ordered if team.id in seeds]
    if len(ranked) == len(ordered) and len({seed for seed, _slot, _id in ranked}) == len(ranked):
        return SeedResolution(opener=min(ranked)[2], seed_source=source, seeds=seeds)
    return SeedResolution(opener=ordered[0].id, seed_source=VetoSeedSource.FALLBACK_FIRST_SLOT, seeds=seeds)


async def resolve_seeds(
    session: AsyncSession, encounter: models.Encounter, teams: list[EncounterTeam]
) -> SeedResolution:
    """Resolve every seat's seed for the encounter (snapshot at session init).

    ``teams`` are the live participations in slot order; the caller has them
    already, and loading them twice would let the two reads disagree.
    """
    if not teams:
        raise ValueError("an encounter with no participations has no pick-ban opener")
    position = await _positions.get_position(session, encounter.id)
    source_team_ids = {team.team_id: team.id for team in teams if team.team_id is not None}
    if not source_team_ids or position is None:
        return SeedResolution(teams[0].id, VetoSeedSource.FALLBACK_FIRST_SLOT, {})

    if position.stage_item_id is not None:
        rows = await session.execute(
            select(models.StageItemInput.team_id, models.StageItemInput.slot).where(
                models.StageItemInput.stage_item_id == position.stage_item_id,
                models.StageItemInput.team_id.in_(tuple(source_team_ids)),
            )
        )
        slots = {source_team_ids[team_id]: slot for team_id, slot in rows.all() if team_id in source_team_ids}
        if len(slots) == len(teams):
            return decide_seeds(teams, slots, VetoSeedSource.BRACKET_SLOT)

    previous_stage_id = await _previous_stage_id(session, encounter, position)
    if previous_stage_id is not None:
        rows = await session.execute(
            select(models.Standing.team_id, sa.func.min(models.Standing.position))
            .where(
                models.Standing.stage_id == previous_stage_id,
                models.Standing.team_id.in_(tuple(source_team_ids)),
            )
            .group_by(models.Standing.team_id)
        )
        positions = {source_team_ids[team_id]: place for team_id, place in rows.all() if team_id in source_team_ids}
        if len(positions) == len(teams):
            return decide_seeds(teams, positions, VetoSeedSource.STANDINGS)

    return SeedResolution(teams[0].id, VetoSeedSource.FALLBACK_FIRST_SLOT, {})


async def _previous_stage_id(
    session: AsyncSession, encounter: models.Encounter, position: models.BracketEncounter
) -> int | None:
    """The stage that actually feeds this bracket.

    Follow the seats' ``source_result_id`` back to the stage item of the result row they came from.
    Plain stage order cannot answer it once a phase runs parallel divisions —
    "the earlier stage" is then two stages, only one of which holds these teams.
    """
    if position.stage_id is None:
        return None
    if position.stage_item_id is not None:
        source = await session.scalar(
            select(models.StageItem.stage_id)
            .join(models.FlowNodeResult, models.FlowNodeResult.stage_item_id == models.StageItem.id)
            .join(models.StageItemInput, models.StageItemInput.source_result_id == models.FlowNodeResult.id)
            .where(models.StageItemInput.stage_item_id == position.stage_item_id)
            .limit(1)
        )
        if source is not None:
            return source
    current_order = await session.scalar(select(models.Stage.order).where(models.Stage.id == position.stage_id))
    if current_order is None:
        return None
    return await session.scalar(
        select(models.Stage.id)
        .where(
            models.Stage.tournament_id == encounter.tournament_id,
            models.Stage.order < current_order,
        )
        .order_by(models.Stage.order.desc(), models.Stage.id.desc())
        .limit(1)
    )
