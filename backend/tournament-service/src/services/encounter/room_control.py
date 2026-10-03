"""The organizer's control over a room that is NOT going the way the rules
assumed: freeze its clock, hand a side more time, drop a session the series can
no longer play out, and end a match nobody is going to play at all.

Every command here is staff-only (`match.result`) and every one of them is a
decision that has to survive being questioned later, so each writes a room
journal entry with the reason the organizer gave. They live together rather than
on ``PickBanSessionService`` because three of them are not pick-ban operations at
all: the pause belongs to the ROOM, and a technical loss ends the encounter.

Pause is one nullable column (``PickBanSession.paused_at``) that the engine reads
in three places -- ``step_deadline`` (so no clock runs and nothing expires),
``step_clock`` (a step that opens while frozen starts at ``paused_at``) and
``assert_not_paused`` (so no captain writes). The board itself keeps settling, so
an organizer acting during the pause sees it move. Resume shifts the step's start
by the whole pause: the step keeps the time it had left, a step that opened
during the pause gets its full timer, and an extension granted while frozen
survives -- all three from one subtraction, because the clock was never read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import EncounterGameState, MapVetoSessionStatus, PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_rules as pbr
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.pick_ban import PickBanSession
from src.services.encounter.captain import captain_service
from src.services.encounter.games import encounter_game_service
from src.services.encounter.pick_ban_action import pick_ban_action_service
from src.services.encounter.pick_ban_session import pick_ban_session_service, resolved_steps
from src.services.encounter.realtime_commit import emit_pick_ban_update
from src.services.encounter.room_journal import record_room_event

__all__ = (
    "cancel_session",
    "default_technical_score",
    "extend_step_timer",
    "set_paused",
    "technical_loss",
)


def _aware(moment: datetime) -> datetime:
    """Stored timestamps come back naive on some drivers; they are UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


async def _load_active(
    session: AsyncSession, encounter_id: int, kind: PickBanKind, *, require_active: bool = True
) -> PickBanSession:
    """The session row under its write lock, or the 409 that says why not.

    Same lock every step-moving path takes (``get_pick_ban_session(for_update)``):
    the resume arithmetic reads ``current_step_started_at`` and writes it back, so
    a settling reader must not be sitting between the two.
    """
    # Idempotent controls can read state before releasing their session lock.
    # Match the settling reader's encounter -> session order.
    await captain_service.encounter_repo.get_for_update(session, encounter_id)
    pick_ban = await pick_ban_session_service.get_pick_ban_session(session, encounter_id, kind, for_update=True)
    if pick_ban is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pick-ban session is not initialized")
    if require_active and str(pick_ban.status) != MapVetoSessionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Pick-ban session is {pick_ban.status}")
    return pick_ban


async def _settled_state(session: AsyncSession, encounter_id: int, kind: PickBanKind) -> dict[str, Any]:
    """Publish, commit, and answer the room state the panel re-renders from."""
    await emit_pick_ban_update(session, encounter_id, kind=kind.value)
    await session.commit()
    return await pick_ban_action_service.get_pick_ban_state(session, encounter_id, kind, viewer_side=None)


async def set_paused(
    session: AsyncSession,
    encounter_id: int,
    kind: PickBanKind,
    *,
    paused: bool,
    actor_auth_user_id: int | None,
) -> dict[str, Any]:
    """Freeze or unfreeze the room's clock. Idempotent: pausing a paused session
    changes nothing and journals nothing."""
    pick_ban = await _load_active(session, encounter_id, kind)
    now = datetime.now(UTC)
    if paused:
        if pick_ban.paused_at is not None:
            return await pick_ban_action_service.get_pick_ban_state(session, encounter_id, kind, viewer_side=None)
        pick_ban.paused_at = now
        await record_room_event(
            session,
            encounter_id,
            action="paused",
            source="admin",
            kind=kind.value,
            actor_auth_user_id=actor_auth_user_id,
        )
    else:
        if pick_ban.paused_at is None:
            return await pick_ban_action_service.get_pick_ban_state(session, encounter_id, kind, viewer_side=None)
        paused_at = _aware(pick_ban.paused_at)
        if pick_ban.current_step_started_at is not None:
            # The whole freeze, unconditionally: a step that opened during it
            # already starts at `paused_at` (`step_clock`), and an extension moved
            # this column on purpose -- comparing the two would undo it.
            pick_ban.current_step_started_at = _aware(pick_ban.current_step_started_at) + (now - paused_at)
        pick_ban.paused_at = None
        await record_room_event(
            session,
            encounter_id,
            action="resumed",
            source="admin",
            kind=kind.value,
            actor_auth_user_id=actor_auth_user_id,
            data={"paused_seconds": int((now - paused_at).total_seconds())},
        )
    return await _settled_state(session, encounter_id, kind)


async def extend_step_timer(
    session: AsyncSession,
    encounter_id: int,
    kind: PickBanKind,
    *,
    seconds: int,
    actor_auth_user_id: int | None,
) -> dict[str, Any]:
    """Give the open step ``seconds`` more, by moving its start forward. Allowed
    while paused -- an organizer usually decides both at once."""
    pick_ban = await _load_active(session, encounter_id, kind)
    steps = resolved_steps(pick_ban)
    submissions = list(
        await pick_ban_action_service.submission_repo.list_by_session(session, pick_ban.id, populate_existing=True)
    )
    step = pbr.current_step(steps, submissions)
    if step is None or step.timer_seconds is None or pick_ban.current_step_started_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No timed step is open")
    pick_ban.current_step_started_at = _aware(pick_ban.current_step_started_at) + timedelta(seconds=seconds)
    await record_room_event(
        session,
        encounter_id,
        action="timer_extended",
        source="admin",
        kind=kind.value,
        actor_auth_user_id=actor_auth_user_id,
        data={"seconds": seconds, "step_index": step.index},
    )
    return await _settled_state(session, encounter_id, kind)


async def cancel_session(
    session: AsyncSession,
    encounter_id: int,
    kind: PickBanKind,
    *,
    reason: str,
    actor_auth_user_id: int | None,
) -> dict[str, Any]:
    """Retire a session the room cannot finish.

    A cancelled HERO session simply stops opening rounds. A cancelled MAP session
    hands the series back to freeplay: the maps it already settled keep their
    positions, every later one is named by the captains (``_series_state``). The
    way back from either is the existing session reset.
    """
    pick_ban = await _load_active(session, encounter_id, kind, require_active=False)
    if str(pick_ban.status) == MapVetoSessionStatus.CANCELLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pick-ban session is already cancelled")
    pick_ban.status = MapVetoSessionStatus.CANCELLED
    # A cancelled session has no clock to freeze, and leaving the flag set would
    # make a later reset inherit a pause nobody asked for.
    pick_ban.paused_at = None
    await record_room_event(
        session,
        encounter_id,
        action="session_cancelled",
        source="admin",
        kind=kind.value,
        actor_auth_user_id=actor_auth_user_id,
        reason=reason,
    )
    return await _settled_state(session, encounter_id, kind)


def default_technical_score(*, best_of: int, loser_side: str, home_wins: int, away_wins: int) -> tuple[int, int]:
    """The score a forfeit is recorded as when the organizer names no explicit one.

    The winner is given a winning series (``best_of // 2 + 1``) or whatever more
    they had already won; the forfeiting side keeps the maps it really won, capped
    one short of winning. A Bo5 that stood 2:0 for the side that then forfeits is
    recorded 2:3 -- the two maps they won are history, the series is not theirs.
    """
    need = max(int(best_of), 1) // 2 + 1
    loser_wins, winner_wins = (home_wins, away_wins) if loser_side == "home" else (away_wins, home_wins)
    winner, loser = max(winner_wins, need), min(loser_wins, need - 1)
    return (loser, winner) if loser_side == "home" else (winner, loser)


async def technical_loss(
    session: AsyncSession,
    encounter: Encounter,
    *,
    loser_side: Literal["home", "away"],
    home_score: int | None,
    away_score: int | None,
    reason: str,
    actor_auth_user_id: int | None,
    actor_player_id: int | None,
) -> Encounter:
    """End the encounter against ``loser_side`` without playing it out.

    One transaction: every live session is cancelled, every position that was not
    already confirmed is cancelled with it, and the result is confirmed last --
    ``set_encounter_result`` is what commits, so everything above it is staged
    against the same unit of work and a refused result (409 on a confirmed
    encounter) leaves the room exactly as it was. The maps that WERE played keep
    their results: a forfeit ends a series, it does not erase it.
    """
    games = await encounter_game_service.list_games(session, encounter.id)
    score = encounter_game_service.live_score(games)
    if (home_score is None) != (away_score is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="home_score and away_score must be provided together",
        )
    if home_score is None or away_score is None:
        home_score, away_score = default_technical_score(
            best_of=encounter.best_of,
            loser_side=loser_side,
            home_wins=score.home_wins,
            away_wins=score.away_wins,
        )
    elif (home_score > away_score) != (loser_side == "away"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A technical loss must score the forfeiting side below its opponent",
        )

    for kind in (PickBanKind.MAP, PickBanKind.HERO):
        pick_ban = await pick_ban_session_service.get_pick_ban_session(session, encounter.id, kind, for_update=True)
        if pick_ban is None or str(pick_ban.status) == MapVetoSessionStatus.CANCELLED:
            continue
        pick_ban.status = MapVetoSessionStatus.CANCELLED
        pick_ban.paused_at = None
        await emit_pick_ban_update(session, encounter.id, kind=kind.value)
    unplayed = [game for game in games if game.state != EncounterGameState.CONFIRMED]
    if unplayed:
        await encounter_game_service.cancel_games(
            session, encounter, unplayed, actor_user_id=actor_player_id, reason="technical_loss"
        )
    await record_room_event(
        session,
        encounter.id,
        action="technical_loss",
        source="admin",
        side=loser_side,
        actor_auth_user_id=actor_auth_user_id,
        reason=reason,
        data={"loser_side": loser_side, "home_score": home_score, "away_score": away_score},
    )
    # Commits (and confirms the result, and advances the bracket) -- the last
    # thing this transaction does.
    return await captain_service.set_encounter_result(
        session,
        encounter.id,
        actor_user_id=actor_player_id,
        home_score=home_score,
        away_score=away_score,
    )
