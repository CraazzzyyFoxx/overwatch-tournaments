"""The single writer of an encounter's result.

Every path that moves a result — the confirmed games adding up, a captain's
series claim, an admin decision, a Challonge import, a bracket reset — ends in
:func:`apply_result`; reports that are incomplete or contradict each other move
only the status, through :func:`hold_result`. One write is one transaction
holding the encounter row's own lock (:func:`lock_encounter`), one
``result_version`` step, and exactly one ``encounter.result_audit`` row, which
is what makes the journal a readable version sequence instead of a pile of
entries nobody can order.

``result_source`` records WHOSE result is standing. ``games`` is the aggregate
of the confirmed games and the only source a recalculation may overwrite;
``series_claim``, ``admin`` and ``import`` are decisions, and only a reopen
takes them off the row. :func:`refresh_from_games` therefore keeps its hands
off an encounter whose result somebody decided.

Transaction-agnostic on purpose: nothing here commits, so the result, the
events it raises and whatever the caller does around it land together or not
at all.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status
from shared.core.enums import (
    AuditSnapshotScope,
    EncounterResultAuditAction,
    EncounterResultSource,
    EncounterResultStatus,
    EncounterStatus,
)
from shared.core.errors import ApiExc, BaseAPIException
from shared.domain.encounter_scoring import EncounterOutcome, GameLine, compile_rules, evaluate_encounter
from shared.models.encounter.audit import EncounterResultAudit
from shared.models.encounter.encounter import Encounter
from shared.models.encounter.game import EncounterGame
from shared.repository import (
    EncounterGameTeamRepository,
    EncounterRepository,
    ScoringRuleRepository,
)
from shared.services.encounter.participants import active_teams
from shared.services.encounter.result_audit import record_result_transition, snapshot

__all__ = ("apply_result", "hold_result", "lock_encounter", "refresh_from_games", "reopen")

_encounters = EncounterRepository()
_game_teams = EncounterGameTeamRepository()
_rules = ScoringRuleRepository()


async def lock_encounter(session: AsyncSession, encounter_id: int) -> Encounter:
    """``SELECT … FOR UPDATE`` the encounter every result write starts from."""
    encounter = await _encounters.get_for_update(session, encounter_id)
    if encounter is None:
        raise BaseAPIException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Encounter {encounter_id} not found",
        )
    return encounter


async def apply_result(
    session: AsyncSession,
    encounter: Encounter,
    *,
    source: EncounterResultSource,
    totals: Mapping[int, float],
    placements: Mapping[int, int],
    action: EncounterResultAuditAction,
    audit_source: str,
    actor_user_id: int | None,
    reason: str | None,
    game: EncounterGame | None = None,
    scope: AuditSnapshotScope = AuditSnapshotScope.ENCOUNTER,
) -> EncounterResultAudit:
    """Write one standing onto the participations and journal the transition.

    ``source`` is the result that stands after this write, and there is no way
    to spell "none" here: an encounter loses its official result through
    :func:`reopen`, or through :func:`refresh_from_games` finding the series
    unfinished — never through a caller that left a keyword out.

    ``totals``/``placements`` state the WHOLE standing, keyed by
    ``encounter_team_id``: a live seat the caller left out scored nothing and
    holds no place, and an id that is not a live seat is refused (a 422) rather
    than ignored. Passing a ``tournament.team`` id here -- two ints, both called
    "team" -- would otherwise zero every seat and confirm that.

    The caller must hold the row's lock (:func:`lock_encounter`):
    ``result_version`` is read, bumped and journalled here, and the journal's
    one-row-per-version constraint is what catches a caller who did not.
    """
    if source is None:
        raise ValueError("apply_result writes a standing result; use reopen() to take one off")
    return await _write(
        session,
        encounter,
        source=source,
        totals=totals,
        placements=placements,
        action=action,
        audit_source=audit_source,
        actor_user_id=actor_user_id,
        reason=reason,
        game=game,
        scope=scope,
    )


async def _write(
    session: AsyncSession,
    encounter: Encounter,
    *,
    source: EncounterResultSource | None,
    totals: Mapping[int, float],
    placements: Mapping[int, int],
    action: EncounterResultAuditAction,
    audit_source: str,
    actor_user_id: int | None,
    reason: str | None,
    game: EncounterGame | None = None,
    scope: AuditSnapshotScope = AuditSnapshotScope.ENCOUNTER,
    hold: EncounterResultStatus | None = None,
) -> EncounterResultAudit:
    """The one writer. ``source=None`` leaves no official result standing, and
    only :func:`reopen` and the unfinished branch of :func:`refresh_from_games`
    may say that -- which is why this half is private. ``hold`` is the
    ``pending_confirmation``/``disputed`` status such a write keeps (the
    unfinished branch must not erase a hold somebody earned)."""
    seats = await active_teams(session, encounter.id)
    live = {seat.id for seat in seats}
    unknown = sorted((set(totals) | set(placements)) - live)
    if unknown:
        # 422, not ValueError: the ids arrive in an admin's request body (``encounter_set_result``),
        # so naming a participation of another encounter is a client error, never a 500.
        raise BaseAPIException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                ApiExc(
                    code="not_a_participation",
                    msg=(
                        f"Encounter {encounter.id}: {unknown} are not live participations of it "
                        f"(its seats are {sorted(live)}); a standing is keyed by encounter_team_id"
                    ),
                )
            ],
        )
    before = snapshot(seats)
    from_result_status = encounter.result_status

    for seat in seats:
        seat.score = _finite(totals.get(seat.id, 0.0), seat.id)
        seat.placement = placements.get(seat.id)

    confirmed = source is not None
    encounter.result_source = source.value if source is not None else None
    encounter.result_status = EncounterResultStatus.CONFIRMED if confirmed else (hold or EncounterResultStatus.NONE)
    if confirmed:
        encounter.status = EncounterStatus.COMPLETED
        encounter.confirmed_at = datetime.now(UTC)
    else:
        # PENDING is a schedule, not a result: only an encounter that WAS
        # complete is re-opened by losing its result.
        if encounter.status == EncounterStatus.COMPLETED:
            encounter.status = EncounterStatus.OPEN
        encounter.confirmed_at = None
    encounter.result_version += 1

    audit = record_result_transition(
        session,
        encounter,
        action=action,
        source=audit_source,
        actor_user_id=actor_user_id,
        from_result_status=from_result_status,
        before=before,
        after=snapshot(seats),
        scope=scope,
        game=game,
        reason=reason,
    )
    await session.flush()
    return audit


async def hold_result(
    session: AsyncSession,
    encounter: Encounter,
    *,
    status: EncounterResultStatus,
    action: EncounterResultAuditAction,
    audit_source: str,
    actor_user_id: int | None,
) -> EncounterResultAudit:
    """Move the result to ``pending_confirmation`` or ``disputed``, adopting nothing.

    Reports that are still incomplete or contradict each other do not decide a
    standing: the seats' numbers and ``result_source`` are left exactly as they
    were, only the status moves and ``confirmed_at`` and ``closeness`` (the
    reports' average, meaningless without an agreed result) are cleared. It is still a
    change of the result, so it takes the same version step and writes the same
    one journal row as :func:`apply_result` does -- the journal stays the
    complete, ordered version sequence.

    Refuses ``confirmed`` (that is :func:`apply_result`, and it needs a source)
    and refuses an encounter that already stands confirmed: a decided result
    leaves through :func:`reopen`. The caller holds the row's lock.
    """
    if status not in (EncounterResultStatus.PENDING_CONFIRMATION, EncounterResultStatus.DISPUTED):
        raise ValueError(f"hold_result moves a result to pending_confirmation or disputed, not {status.value}")
    if encounter.result_status == EncounterResultStatus.CONFIRMED:
        raise ValueError(f"Encounter {encounter.id} stands confirmed; reopen() it before holding its result")
    seats = await active_teams(session, encounter.id)
    from_result_status = encounter.result_status
    standing = snapshot(seats)

    encounter.result_status = status
    encounter.confirmed_at = None
    encounter.closeness = None
    encounter.result_version += 1

    audit = record_result_transition(
        session,
        encounter,
        action=action,
        source=audit_source,
        actor_user_id=actor_user_id,
        from_result_status=from_result_status,
        before=standing,
        after=standing,
    )
    await session.flush()
    return audit


async def refresh_from_games(
    session: AsyncSession,
    encounter: Encounter,
    *,
    action: EncounterResultAuditAction,
    audit_source: str,
    actor_user_id: int | None,
    game: EncounterGame | None = None,
    reason: str | None = None,
) -> EncounterOutcome:
    """Re-score the encounter from its confirmed games and write the outcome.

    Does nothing to an encounter whose result somebody decided — a series
    claim, an admin, an import — and returns what the games say anyway, so a
    caller can show the two side by side. Confirms with source ``games`` once
    the rule's end condition holds; until then the standing is materialized
    but no official result exists.

    A game whose line-up includes a seat that has since been taken over counts
    for nobody. ``vacate_slot`` deliberately leaves a CONFIRMED game with the
    participation that played it, so after a mid-series correction those rows
    are still on record -- and they are the OLD line-up's result, not the live
    one's. Dropping only the retired LINE would be worse than keeping it: a
    two-seat game left with one line ranks the survivor first and pays it a
    win it never earned, so the whole game goes.

    ``reason`` is the stated cause of a correction. The journal has exactly one
    row per ``result_version``, so an admin's words have to travel with the
    write that moved the standing rather than in a second row beside it.
    """
    seats = await active_teams(session, encounter.id)
    live = {seat.id for seat in seats}
    rule = await _rules.get(session, encounter.scoring_rule_id)
    if rule is None:
        raise BaseAPIException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Encounter {encounter.id} points at scoring rule {encounter.scoring_rule_id}, which is gone",
        )
    rules = compile_rules(rule)
    outcome = evaluate_encounter(
        rules,
        best_of=encounter.best_of,
        team_ids=[seat.id for seat in seats],
        games=[
            [
                GameLine(
                    encounter_team_id=line.encounter_team_id,
                    score=line.score,
                    placement=line.placement,
                    values=line.column_values or {},
                )
                for line in lines
            ]
            for lines in await _game_teams.confirmed_lines(session, encounter.id)
            if live.issuperset(row.encounter_team_id for row in lines)
        ],
    )

    if encounter.result_source not in (None, EncounterResultSource.GAMES.value):
        return outcome

    # Games that say "not finished" say nothing about a pending report or a
    # dispute: those are about the captains' series claim, so they stay.
    hold = (
        encounter.result_status
        if not outcome.ended
        and encounter.result_status in (EncounterResultStatus.PENDING_CONFIRMATION, EncounterResultStatus.DISPUTED)
        else None
    )
    await _write(
        session,
        encounter,
        source=EncounterResultSource.GAMES if outcome.ended else None,
        totals=outcome.totals,
        placements=outcome.placements,
        action=action,
        audit_source=audit_source,
        actor_user_id=actor_user_id,
        reason=reason,
        game=game,
        scope=AuditSnapshotScope.GAME if game is not None else AuditSnapshotScope.ENCOUNTER,
        hold=hold,
    )
    return outcome


async def reopen(
    session: AsyncSession,
    encounter: Encounter,
    *,
    actor_user_id: int | None,
    reason: str,
) -> EncounterResultAudit:
    """Take the standing result off the encounter, keeping the numbers.

    The only way an ``admin``/``series_claim``/``import`` result stops
    standing, and the one action that unmakes a human decision -- so a human
    signs it. The materialized scores are left alone: with no source they read
    as the running tally again, and the next :func:`refresh_from_games`
    replaces them with what the games actually say.
    """
    seats = await active_teams(session, encounter.id)
    return await _write(
        session,
        encounter,
        source=None,
        totals={seat.id: seat.score for seat in seats},
        placements={seat.id: seat.placement for seat in seats if seat.placement is not None},
        action=EncounterResultAuditAction.REOPEN,
        audit_source="admin",
        actor_user_id=actor_user_id,
        reason=reason,
    )


def _finite(value: float, encounter_team_id: int) -> float:
    """A standing is a number a tiebreak can compare; NaN and ±Inf are not."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Participation {encounter_team_id}: {value!r} is not a finite score")
    return number
