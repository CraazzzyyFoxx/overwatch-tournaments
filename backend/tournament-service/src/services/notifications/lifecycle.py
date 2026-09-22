"""Lifecycle facts a competitor is waiting to hear: registration opened, the
check-in started, their match got a time.

Called inline from the three mutations that produce those facts
(``transition_status``, encounter create/update, bracket advancement), inside
the caller's transaction and before its ``commit()`` -- the same shape as every
other ``notify()`` producer in this service. Nothing here commits, and nothing
here raises for a missing recipient: a lifecycle write must not fail because
somebody has no account behind their roster row.

Every call is keyed. ``dedupe_key`` is what makes the hooks re-entrant, and
they need to be: a status can flap (REGISTRATION -> ANNOUNCEMENT ->
REGISTRATION), the round scheduler sends one PATCH per encounter with the time
it already has, and an encounter reaches :meth:`on_encounter_changed` from
three different paths. The key says "this event", so a repeat writes nothing;
a *new* match time is a new key, hence a fresh "rescheduled" notification.

``ponytail:`` a window that opens *lazily* -- a manual transition made before
``starts_at``, a ``set_schedule`` landing a start time already in the past, or
``allow_late_registration`` flipped on later -- notifies nobody, because only a
status write reaches this module. The upgrade path is the reminders tick
(spec §10), which detects the window crossing itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums, tournament_state
from shared.repository.notification_recipients import NotificationRecipientRepository
from shared.repository.tournament import (
    TeamRepository,
    TournamentPhaseScheduleRepository,
    TournamentRepository,
)
from shared.services.notifications import broadcast, notify
from shared.services.registration_window import is_registration_window_open
from src import models

__all__ = ("LifecycleNotifier", "lifecycle_notifier")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _phase_entry(
    schedule: Iterable[models.TournamentPhaseSchedule],
    status: enums.TournamentStatus,
) -> models.TournamentPhaseSchedule | None:
    return next((entry for entry in schedule if entry.status == status), None)


class LifecycleNotifier:
    """The three tournament events that leave the app."""

    def __init__(
        self,
        *,
        schedule_repo: TournamentPhaseScheduleRepository = TournamentPhaseScheduleRepository(),
        recipient_repo: NotificationRecipientRepository = NotificationRecipientRepository(),
        team_repo: TeamRepository = TeamRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
    ) -> None:
        self.schedule_repo = schedule_repo
        self.recipient_repo = recipient_repo
        self.team_repo = team_repo
        self.tournament_repo = tournament_repo

    async def on_status_entered(self, session: AsyncSession, tournament: models.Tournament) -> None:
        """Announce the phase ``tournament`` has just been moved into.

        Called with the new status already assigned. Any phase other than the
        two that open a door for participants is silent.
        """
        if tournament.status == enums.TournamentStatus.REGISTRATION:
            await self._registration_opened(session, tournament)
        elif tournament.status == enums.TournamentStatus.CHECK_IN:
            await self._check_in_opened(session, tournament)

    async def _registration_opened(self, session: AsyncSession, tournament: models.Tournament) -> None:
        # Read rather than ``tournament.phase_schedule``: the instance the
        # transition holds was loaded with its stages, and touching an unloaded
        # relationship on an async session raises instead of lazy-loading.
        schedule = await self.schedule_repo.list_for_tournament(session, tournament.id)
        if not is_registration_window_open(
            tournament.status,
            schedule,
            allow_late=tournament.allow_late_registration,
        ):
            # The status says REGISTRATION but the button does not work yet (no
            # schedule row, or the window has not started). Inviting people to
            # a sign-up that refuses them is worse than saying nothing.
            logger.info(
                "registration.opened skipped for tournament {}: registration window is closed",
                tournament.id,
            )
            return

        if tournament.is_hidden:
            # A hidden tournament is admin-only, and this kind has no personal
            # recipients at all -- a workspace row would announce it to every
            # member's bell, a broadcast to a public channel.
            return

        entry = _phase_entry(schedule, enums.TournamentStatus.REGISTRATION)
        payload = {
            "tournament_id": tournament.id,
            "tournament_name": tournament.name,
            # ``allow_late_registration`` lifts ``ends_at``, so there is no
            # closing time to promise.
            "closes_at": None if tournament.allow_late_registration else (entry.ends_at if entry else None),
        }
        dedupe_key = f"tournament:{tournament.id}"
        await notify(
            session,
            kind="registration.opened",
            audience="workspace",
            workspace_id=tournament.workspace_id,
            payload=payload,
            dedupe_key=dedupe_key,
        )
        await broadcast(
            session,
            kind="registration.opened",
            payload=payload,
            workspace_id=tournament.workspace_id,
            dedupe_key=dedupe_key,
        )

    async def _check_in_opened(self, session: AsyncSession, tournament: models.Tournament) -> None:
        schedule = await self.schedule_repo.list_for_tournament(session, tournament.id)
        if not tournament_state.is_within_phase_window(
            enums.TournamentStatus.CHECK_IN,
            schedule,
            datetime.now(UTC),
        ):
            logger.info(
                "check_in.opened skipped for tournament {}: check-in window is not active",
                tournament.id,
            )
            return

        entry = _phase_entry(schedule, enums.TournamentStatus.CHECK_IN)
        payload = {
            "tournament_id": tournament.id,
            "tournament_name": tournament.name,
            "closes_at": entry.ends_at if entry else None,
        }
        dedupe_key = f"tournament:{tournament.id}"
        for auth_user_id in await self.recipient_repo.check_in_pending_auth_user_ids(session, tournament.id):
            await notify(
                session,
                kind="check_in.opened",
                recipient_auth_user_id=auth_user_id,
                source_workspace_id=tournament.workspace_id,
                payload=payload,
                dedupe_key=dedupe_key,
            )
        if not tournament.is_hidden:
            await broadcast(
                session,
                kind="check_in.opened",
                payload=payload,
                workspace_id=tournament.workspace_id,
                dedupe_key=dedupe_key,
            )

    async def on_encounter_changed(self, session: AsyncSession, encounter: models.Encounter) -> None:
        """Tell both rosters when (and against whom) they play.

        Guards first, and all three off the instance in hand: an encounter with
        no time, an empty slot or a time in the past (backfilled results,
        Challonge imports) is not news, and asking the database about it would
        be a query per bracket row for nothing.
        """
        scheduled_at = encounter.scheduled_at
        if scheduled_at is None or encounter.home_team_id is None or encounter.away_team_id is None:
            return
        scheduled_at = _as_utc(scheduled_at)
        if scheduled_at <= datetime.now(UTC):
            return

        tournament = await self.tournament_repo.get(session, encounter.tournament_id)
        if tournament is None or tournament_state.is_finished_for_status(tournament.status):
            return

        if encounter.id is None:
            # ``create_encounter`` calls this before its own flush when the
            # recalculation enqueue was skipped (scrim containers); the id is
            # half the dedupe key.
            await session.flush()

        team_ids: Sequence[int] = (encounter.home_team_id, encounter.away_team_id)
        names = {team.id: team.name for team in await self.team_repo.bulk_get(session, list(team_ids))}
        payload = {
            "encounter_id": encounter.id,
            "tournament_id": tournament.id,
            "tournament_name": tournament.name,
            "home_team_name": names.get(encounter.home_team_id, ""),
            "away_team_name": names.get(encounter.away_team_id, ""),
            "scheduled_at": scheduled_at,
        }
        # Normalized to UTC first: the same instant arriving as a naive column
        # value and as an offset-aware payload must produce the same key, or a
        # re-save of an unchanged time would read as a reschedule.
        dedupe_key = f"encounter:{encounter.id}:{scheduled_at.isoformat()}"
        for auth_user_id in await self.recipient_repo.team_roster_auth_user_ids(session, team_ids):
            await notify(
                session,
                kind="encounter.scheduled",
                recipient_auth_user_id=auth_user_id,
                source_workspace_id=tournament.workspace_id,
                payload=payload,
                dedupe_key=dedupe_key,
            )
        if not tournament.is_hidden:
            await broadcast(
                session,
                kind="encounter.scheduled",
                payload=payload,
                workspace_id=tournament.workspace_id,
                dedupe_key=dedupe_key,
            )


lifecycle_notifier = LifecycleNotifier()
