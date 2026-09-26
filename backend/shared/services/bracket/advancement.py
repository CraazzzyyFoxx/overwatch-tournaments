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
from dataclasses import dataclass

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.domain import pick_ban_engine as engine
from shared.domain.encounter_naming import build_encounter_name_from_ids
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.encounter_link import EncounterLink
from shared.models.tournament.encounter_report import EncounterCaptainReport
from shared.models.tournament.stage import Stage
from shared.models.tournament.team import Team
from shared.services.bracket.types import AdvancementEdge
from shared.services.encounter.game_audit import cancel_games
from shared.services.encounter.result_audit import record_result_transition

__all__ = (
    "persist_advancement_edges",
    "advance_winner",
    "reset_encounter_result",
    "SlotSource",
    "resolve_slot_sources",
)


@dataclass(frozen=True)
class SlotSource:
    """One incoming advancement edge, from the target's point of view: ``slot``
    is filled by the ``role`` ("winner"/"loser") of ``encounter_id``."""

    encounter_id: int
    role: str
    slot: str


async def resolve_slot_sources(session: AsyncSession, encounter_ids: Iterable[int]) -> dict[int, list[SlotSource]]:
    """Incoming advancement edges, keyed by TARGET encounter id.

    ``EncounterLink`` is the bracket's real topology, but until now only the
    engine read it: a reader had to infer where an empty slot's team would come
    from out of round numbers and match counts. That inference cannot tell a
    lower bracket seeded straight from the group stage — whose round 1 holds
    seeds, so its slots really are TBD — from a standard one whose round 1 holds
    the upper bracket's first losers. Handing the edges out removes the guess.
    """
    targets = {encounter_id for encounter_id in encounter_ids if encounter_id is not None}
    if not targets:
        return {}

    rows = await session.execute(
        sa.select(
            EncounterLink.target_encounter_id,
            EncounterLink.source_encounter_id,
            EncounterLink.role,
            EncounterLink.target_slot,
        )
        .where(EncounterLink.target_encounter_id.in_(targets))
        .order_by(EncounterLink.target_encounter_id, EncounterLink.id)
    )

    sources: dict[int, list[SlotSource]] = {}
    for target_id, source_id, role, slot in rows.all():
        sources.setdefault(target_id, []).append(SlotSource(encounter_id=source_id, role=role.value, slot=slot.value))
    return sources


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

        role = enums.EncounterLinkRole.WINNER if edge.role == "winner" else enums.EncounterLinkRole.LOSER
        slot = enums.EncounterLinkSlot.HOME if edge.target_slot == "home" else enums.EncounterLinkSlot.AWAY
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

    winner_id = encounter.home_team_id if encounter.home_score > encounter.away_score else encounter.away_team_id
    loser_id = encounter.away_team_id if encounter.home_score > encounter.away_score else encounter.home_team_id

    links = (
        (await session.execute(sa.select(EncounterLink).where(EncounterLink.source_encounter_id == encounter.id)))
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
        current_team_id = (
            target.home_team_id if link.target_slot == enums.EncounterLinkSlot.HOME else target.away_team_id
        )
        if current_team_id == team_id:
            # Idempotent re-finalisation (e.g. admin corrected the score but
            # the winner did not change) — nothing to propagate.
            continue

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

        # The slot previously held a DIFFERENT team (an upstream result was
        # corrected): any result already recorded on the target — and anything
        # that result had advanced further down the bracket — is stale now.
        updated.extend(await reset_encounter_result(session, target))

    reset_match, dropped = await _maybe_create_grand_final_reset(session, encounter, winner_id)
    if dropped:
        # The link loop above filled the leftover Reset's slots before it was
        # dropped; a deleted row must not reach the caller's post-advance hooks.
        dropped_ids = {id(encounter) for encounter in dropped}
        updated = [target for target in updated if id(target) not in dropped_ids]
    if reset_match is not None:
        updated.append(reset_match)

    if updated:
        await session.flush()
    return updated


async def reset_encounter_result(
    session: AsyncSession,
    encounter: Encounter,
    *,
    action: enums.EncounterResultAuditAction = enums.EncounterResultAuditAction.CASCADE_RESET,
    actor_user_id: int | None = None,
    source: str = "admin",
) -> list[Encounter]:
    """Un-play an encounter and clear whatever its old result advanced.

    Two callers, one behaviour. The bracket calls it with the defaults when a
    corrected upstream result rewired this encounter's team slots: any score
    recorded for the OLD matchup is void. An admin reopening a result calls it
    with ``action=REOPEN`` and their own id, so the initiating transition is
    attributed while the downstream fan-out stays ``cascade_reset``.

    Returns every *additional* encounter that was modified. Only flushes are
    left to the caller (``advance_winner``).
    """
    had_advanced = encounter.status == enums.EncounterStatus.COMPLETED
    has_recorded_result = (
        had_advanced
        or encounter.result_status != enums.EncounterResultStatus.NONE
        or encounter.home_score != 0
        or encounter.away_score != 0
    )
    if not has_recorded_result:
        return []

    from_result_status = encounter.result_status
    home_score_before = encounter.home_score
    away_score_before = encounter.away_score

    encounter.home_score = 0
    encounter.away_score = 0
    encounter.status = enums.EncounterStatus.OPEN
    encounter.result_status = enums.EncounterResultStatus.NONE
    encounter.confirmed_at = None
    # The old matchup's intensity rating is void with the rest of the result;
    # tournament closeness averages this column, so a stale value would leak
    # the previous pairing into the tournament's numbers.
    encounter.closeness = None
    if action == enums.EncounterResultAuditAction.CASCADE_RESET:
        # A cascade means the MATCHUP changed, not just the score: every artefact
        # of the old pairing is void. Captain reports above all — a surviving
        # report from the replaced opponent would pair with the new team's report
        # and auto-confirm a series that was never played (review item 7). The
        # series' games go the same way: a position played by the REPLACED team
        # is not a position of this encounter any more, and leaving one confirmed
        # would re-materialise its win onto the new pairing.
        await session.execute(
            sa.delete(EncounterCaptainReport).where(EncounterCaptainReport.encounter_id == encounter.id)
        )
        live_games = (
            (
                await session.execute(
                    sa.select(EncounterGame).where(
                        EncounterGame.encounter_id == encounter.id,
                        EncounterGame.state != enums.EncounterGameState.CANCELLED,
                    )
                )
            )
            .scalars()
            .all()
        )
        cancel_games(session, encounter, live_games, actor_user_id=actor_user_id, reason="cascade_reset")
        encounter.ended_at = None
        encounter.current_map_index = None
    else:
        # A REOPEN keeps the same two teams and their games: the encounter drops
        # back to the LIVE score its confirmed positions still add up to, not to
        # 0:0. Zeroing it would make the room disagree with every game row it
        # renders, and the next captain claim would count from the wrong base.
        rows = (
            await session.execute(
                sa.select(EncounterGame.accepted_home_score, EncounterGame.accepted_away_score).where(
                    EncounterGame.encounter_id == encounter.id,
                    EncounterGame.state == enums.EncounterGameState.CONFIRMED,
                )
            )
        ).all()
        score = engine.series_score(rows)
        encounter.home_score, encounter.away_score = score.home_wins, score.away_wins
    record_result_transition(
        session,
        encounter,
        action=action,
        source=source,
        actor_user_id=actor_user_id,
        from_result_status=from_result_status,
        home_score_before=home_score_before,
        away_score_before=away_score_before,
    )
    logger.info(
        "Reset result on encounter %s (%s)",
        encounter.id,
        action.value,
    )

    if not had_advanced:
        # A pending/disputed submission never advanced anyone — no fan-out.
        return []

    links = (
        (await session.execute(sa.select(EncounterLink).where(EncounterLink.source_encounter_id == encounter.id)))
        .scalars()
        .all()
    )
    cleared: list[Encounter] = []
    for link in links:
        target = await session.get(
            Encounter,
            link.target_encounter_id,
            with_for_update=True,
        )
        if target is None:
            continue

        if link.target_slot == enums.EncounterLinkSlot.HOME:
            if target.home_team_id is None:
                continue
            target.home_team_id = None
        else:
            if target.away_team_id is None:
                continue
            target.away_team_id = None
        target.name = await _build_encounter_name_for_ids(
            session,
            home_team_id=target.home_team_id,
            away_team_id=target.away_team_id,
        )
        cleared.append(target)
        cleared.extend(await reset_encounter_result(session, target))
    return cleared


async def _maybe_create_grand_final_reset(
    session: AsyncSession,
    gf_encounter: Encounter,
    gf_winner_id: int,
) -> tuple[Encounter | None, list[Encounter]]:
    """Lazily create a Grand Final Reset match when the LB champion wins GF.

    Rules:
    - Stage is double-elimination AND configured ``de_grand_final_type ==
      "with_reset"``; a ``no_reset`` stage ends at the Grand Final.
    - The encounter is a Grand Final iff it has an incoming WINNER
      ``EncounterLink`` whose SOURCE sits in a negative (lower-bracket) round.
      That link's ``target_slot`` is where the LB champion plays. Round numbers
      cannot say this: the Reset itself and the UB Final are positive rounds too,
      and a materialised Reset is the highest of them (review items 2, 3).
    - The Reset is fed by two links from the GF (WINNER -> the LB champion's
      slot, LOSER -> the other), so it is a normal advancement target: it fills
      itself and ``reset_encounter_result(GF)`` un-plays it again. Its own
      incoming links all come from a positive round, so completing it never
      spawns a second Reset.
    - The GF winner must be the team in the LB champion's slot; a home/away swap
      moves the link with the team, so the answer survives it (review item 4).

    Returns ``(created_reset, dropped_leftovers)``.
    """
    if gf_encounter.stage_id is None or gf_encounter.round <= 0:
        return None, []

    stage = await session.get(Stage, gf_encounter.stage_id)
    if stage is None or stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
        return None, []
    if stage.de_grand_final_type != "with_reset":
        return None, []

    lb_slot = await session.scalar(
        sa.select(EncounterLink.target_slot)
        .join(Encounter, Encounter.id == EncounterLink.source_encounter_id)
        .where(
            EncounterLink.target_encounter_id == gf_encounter.id,
            EncounterLink.role == enums.EncounterLinkRole.WINNER,
            Encounter.round < 0,
        )
    )
    if lb_slot is None:
        return None, []

    outgoing = (
        (await session.execute(sa.select(EncounterLink).where(EncounterLink.source_encounter_id == gf_encounter.id)))
        .scalars()
        .all()
    )

    lb_champion_id = gf_encounter.home_team_id if lb_slot == enums.EncounterLinkSlot.HOME else gf_encounter.away_team_id
    if lb_champion_id != gf_winner_id:
        # UB champion won — the tournament ends at the Grand Final. Drop an
        # untouched Reset left over from an earlier LB-champion result (or from a
        # generator that pre-created one); a played one is an admin's problem.
        dropped: list[Encounter] = []
        for reset_id in {link.target_encounter_id for link in outgoing}:
            leftover = await session.get(Encounter, reset_id, with_for_update=True)
            if (
                leftover is not None
                and leftover.status == enums.EncounterStatus.OPEN
                and leftover.home_score == 0
                and leftover.away_score == 0
                and leftover.result_status == enums.EncounterResultStatus.NONE
            ):
                await session.delete(leftover)
                dropped.append(leftover)
        return None, dropped

    if outgoing:
        # The Reset already exists and ``advance_winner``'s link loop just filled
        # its slots from these very links.
        return None, []

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
        # The reset is the same series as the Grand Final it continues; without
        # this it took the column default (Bo3) no matter what the stage's
        # best-of config said, because it is materialised here rather than by
        # the generator that resolves best-of.
        best_of=gf_encounter.best_of,
        round=gf_encounter.round + 1,
        tournament_id=gf_encounter.tournament_id,
        stage_id=gf_encounter.stage_id,
        stage_item_id=gf_encounter.stage_item_id,
        status=enums.EncounterStatus.OPEN,
    )
    session.add(reset)
    await session.flush()
    other_slot = (
        enums.EncounterLinkSlot.AWAY if lb_slot == enums.EncounterLinkSlot.HOME else enums.EncounterLinkSlot.HOME
    )
    for role, slot in (
        (enums.EncounterLinkRole.WINNER, lb_slot),
        (enums.EncounterLinkRole.LOSER, other_slot),
    ):
        session.add(
            EncounterLink(
                source_encounter_id=gf_encounter.id,
                target_encounter_id=reset.id,
                role=role,
                target_slot=slot,
            )
        )
    await session.flush()
    logger.info(
        "Created Grand Final Reset for tournament=%s stage=%s (LB champion won GF)",
        gf_encounter.tournament_id,
        gf_encounter.stage_id,
    )
    return reset, []


async def _build_encounter_name_for_ids(
    session: AsyncSession,
    *,
    home_team_id: int | None,
    away_team_id: int | None,
) -> str:
    team_ids = {team_id for team_id in (home_team_id, away_team_id) if team_id is not None}
    if not team_ids:
        return build_encounter_name_from_ids(home_team_id, away_team_id, {})

    result = await session.execute(sa.select(Team.id, Team.name).where(Team.id.in_(team_ids)))
    team_names_by_id = dict(result.all())
    return build_encounter_name_from_ids(
        home_team_id,
        away_team_id,
        team_names_by_id,
    )
