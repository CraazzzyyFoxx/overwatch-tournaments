"""Lifecycle facts a competitor is waiting to hear: registration opened, the
check-in started, their next match is ready to play.

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
every site that can fill a team slot. The key says "this event", so a repeat
writes nothing; a *new* opponent or a *new* match time is a new key, hence a
fresh notification.

``ponytail:`` a window that opens *lazily* -- a manual transition made before
``starts_at``, a ``set_schedule`` landing a start time already in the past, or
``allow_late_registration`` flipped on later -- notifies nobody, because only a
status write reaches this module. The upgrade path is the reminders tick,
which detects the window crossing itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, tournament_state
from shared.domain.pick_ban_config import has_pool
from shared.repository.notification_recipients import NotificationRecipientRepository
from shared.repository.tournament import TournamentPhaseScheduleRepository
from shared.services.notifications import PersonalNotification, broadcast, notify, notify_users
from shared.services.registration_window import is_registration_window_open
from src.services.bracket.advancement import AdvanceOutcome, advance_after_result


def _pick_ban_sessions():
    """The pick-ban service, loaded on first use.

    Module scope would make every admin encounter write depend on the whole
    pick-ban stack loading, and the notifier only reaches it on the two paths
    below. Resolved through the singleton on each call, so a test patching
    ``pick_ban_session_service`` still intercepts both.
    """
    from src.services.encounter.pick_ban_session import pick_ban_session_service  # noqa: PLC0415

    return pick_ban_session_service


__all__ = ("LifecycleNotifier", "advance_and_announce", "after_encounter_teams_changed", "lifecycle_notifier")


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
    ) -> None:
        self.schedule_repo = schedule_repo
        self.recipient_repo = recipient_repo

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
        if tournament.discord_broadcasts_enabled:
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
        recipients = await self.recipient_repo.check_in_pending_auth_user_ids(session, tournament.id)
        await notify_users(
            session,
            kind="check_in.opened",
            notifications=[
                PersonalNotification(auth_user_id, payload, dedupe_key, tournament.workspace_id)
                for auth_user_id in recipients
            ],
        )
        if not tournament.is_hidden and tournament.discord_broadcasts_enabled:
            await broadcast(
                session,
                kind="check_in.opened",
                payload=payload,
                workspace_id=tournament.workspace_id,
                dedupe_key=dedupe_key,
            )

    async def on_encounter_changed(
        self,
        session: AsyncSession,
        encounter: models.Encounter,
        *,
        channel: bool = True,
    ) -> None:
        """Tell every seated roster they have a match ready to play, and against whom.

        A time is not what makes it news -- knowing the opponent is -- so a fully
        seated encounter notifies whether or not it is scheduled. What silences
        it is the match being unplayable or already under way: an empty seat, a
        preview bracket nobody can enter, a started or completed encounter
        (backfilled results, Challonge imports), a finished tournament.

        "Fully seated" is as many live participations as the card has slots,
        which is the same question for a duel and for a lobby.

        ``channel=False`` keeps the event personal. Bulk producers (stage
        activation, Swiss rounds, requalification, Challonge sync) fill a
        dozen encounters in one go, and a dozen channel posts is spam.
        """
        await self.on_encounters_changed(session, [encounter], channel=channel)

    async def on_encounters_changed(
        self,
        session: AsyncSession,
        encounters: Sequence[models.Encounter],
        *,
        channel: bool = False,
    ) -> None:
        """:meth:`on_encounter_changed` for every encounter of a bulk producer at once.

        Same rules per encounter, in a constant number of statements: seats,
        bracket positions, stages, tournaments, team names and rosters are read
        once for the batch, the pick-ban flag once per (stage, round), and every
        row goes through one ``notify_users`` (one dedupe lookup, one flush).
        Column reads, not entity loads: a tournament row drags its grid and
        schedule along, and this only needs six of its columns. ``channel``
        defaults to False because the batch callers are the bulk producers.
        """
        if any(encounter.id is None for encounter in encounters):
            # ``create_encounter`` calls this before its own flush when the
            # recalculation enqueue was skipped (scrim containers); the id is
            # part of the dedupe key, and the seats are read by it.
            await session.flush()
        pending = [
            encounter
            for encounter in encounters
            if encounter.started_at is None and encounter.status != enums.EncounterStatus.COMPLETED
        ]
        if not pending:
            return

        seats: dict[int, list[tuple[int | None, str]]] = {}
        seat_rows = await session.execute(
            sa.select(models.EncounterTeam.encounter_id, models.EncounterTeam.team_id, models.EncounterTeam.name)
            .where(
                models.EncounterTeam.encounter_id.in_([encounter.id for encounter in pending]),
                models.EncounterTeam.active.is_(True),
            )
            .order_by(models.EncounterTeam.encounter_id, models.EncounterTeam.slot, models.EncounterTeam.id)
        )
        for encounter_id, team_id, name in seat_rows.all():
            seats.setdefault(encounter_id, []).append((team_id, name))
        seated = [
            encounter
            for encounter in pending
            if len(seats.get(encounter.id, ())) >= encounter.slot_count
            and all(team_id is not None for team_id, _name in seats.get(encounter.id, ()))
        ]
        if not seated:
            return

        # Liveness as ``is_encounter_live`` decides it: no position (a scrim, a
        # mix) or no stage is live; otherwise the stage must be published.
        position_rows = await session.execute(
            sa.select(
                models.BracketEncounter.encounter_id,
                models.BracketEncounter.stage_id,
                models.BracketEncounter.round,
            ).where(models.BracketEncounter.encounter_id.in_([encounter.id for encounter in seated]))
        )
        positions = {encounter_id: (stage_id, round_) for encounter_id, stage_id, round_ in position_rows.all()}
        stage_ids = sorted({stage_id for stage_id, _round in positions.values() if stage_id is not None})
        unpublished: set[int] = set()
        if stage_ids:
            stage_rows = await session.execute(
                sa.select(models.Stage.id, models.Stage.is_published).where(models.Stage.id.in_(stage_ids))
            )
            unpublished = {stage_id for stage_id, is_published in stage_rows.all() if not is_published}
        live = [encounter for encounter in seated if positions.get(encounter.id, (None, 0))[0] not in unpublished]
        if not live:
            return

        tournament_rows = await session.execute(
            sa.select(
                models.Tournament.id,
                models.Tournament.name,
                models.Tournament.status,
                models.Tournament.workspace_id,
                models.Tournament.is_hidden,
                models.Tournament.discord_broadcasts_enabled,
            ).where(models.Tournament.id.in_(sorted({encounter.tournament_id for encounter in live})))
        )
        tournaments = {row.id: row for row in tournament_rows.all()}
        live = [
            encounter
            for encounter in live
            if encounter.tournament_id in tournaments
            and not tournament_state.is_finished_for_status(tournaments[encounter.tournament_id].status)
        ]
        if not live:
            return

        team_ids = sorted({team_id for encounter in live for team_id, _name in seats[encounter.id]})
        name_rows = await session.execute(
            sa.select(models.Team.id, models.Team.name).where(models.Team.id.in_(team_ids))
        )
        names = dict(name_rows.tuples().all())
        rosters = await self.recipient_repo.team_roster_auth_user_ids(session, team_ids)

        pick_ban: dict[tuple[int, int | None, int], bool] = {}
        rows: list[PersonalNotification] = []
        posts: list[tuple[dict, int, str]] = []
        for encounter in live:
            tournament = tournaments[encounter.tournament_id]
            stage_id, round_ = positions.get(encounter.id, (None, 0))
            coordinate = (encounter.tournament_id, stage_id, round_)
            if coordinate not in pick_ban:
                pick_ban[coordinate] = await self._has_pick_ban(session, *coordinate)
            # Normalized to UTC first: the same instant arriving as a naive column
            # value and as an offset-aware payload must produce the same key, or a
            # re-save of an unchanged time would read as a reschedule.
            scheduled_at = _as_utc(encounter.scheduled_at) if encounter.scheduled_at is not None else None
            encounter_team_ids = [team_id for team_id, _name in seats[encounter.id]]
            payload = {
                "encounter_id": encounter.id,
                "tournament_id": tournament.id,
                "tournament_name": tournament.name,
                "team_names": [names.get(team_id) or name for team_id, name in seats[encounter.id]],
                "scheduled_at": scheduled_at,
                "pick_ban": pick_ban[coordinate],
            }
            # The opponent is half the event: a slot refilled with another team is
            # a new match to prepare for, not a repeat of the old one.
            dedupe_key = (
                f"encounter:{encounter.id}:{':'.join(str(team_id) for team_id in encounter_team_ids)}:"
                f"{scheduled_at.isoformat() if scheduled_at is not None else 'tbd'}"
            )
            recipients = dict.fromkeys(
                auth_user_id for team_id in encounter_team_ids for auth_user_id in rosters.get(team_id, ())
            )
            rows.extend(
                PersonalNotification(auth_user_id, payload, dedupe_key, tournament.workspace_id)
                for auth_user_id in recipients
            )
            if channel and not tournament.is_hidden and tournament.discord_broadcasts_enabled:
                posts.append((payload, tournament.workspace_id, dedupe_key))

        await notify_users(session, kind="encounter.scheduled", notifications=rows)
        for payload, workspace_id, dedupe_key in posts:
            await broadcast(
                session,
                kind="encounter.scheduled",
                payload=payload,
                workspace_id=workspace_id,
                dedupe_key=dedupe_key,
            )

    async def _has_pick_ban(self, session: AsyncSession, tournament_id: int, stage_id: int | None, round_: int) -> bool:
        """Whether this bracket coordinate resolves to a pick-ban with a pool --
        the same question ``PregameRoomLink`` asks on the frontend.

        An encounter with no bracket position -- a scrim, a mix -- resolves at
        the tournament level only (``stage_id=None, round_=0``).

        Sessions are not consulted: they only exist once both captains are
        ready, which is after the message this flag is for.
        """
        for kind in (enums.PickBanKind.MAP, enums.PickBanKind.HERO):
            config = await _pick_ban_sessions().resolve_config_at_level(
                session,
                tournament_id=tournament_id,
                kind=kind,
                stage_id=stage_id,
                round=round_,
            )
            if config is not None and has_pool(config):
                return True
        return False


lifecycle_notifier = LifecycleNotifier()


async def after_encounter_teams_changed(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    channel: bool,
) -> None:
    """Everything a filled-in (or re-assigned) team slot owes, in one call.

    The pick-ban rooms follow the new pairing, then both rosters hear who they
    play. Lives here rather than beside the pick-ban service because the
    notifier already resolves pick-ban configs; the service is reached through
    its singleton, so a test patching ``pick_ban_session_service`` at any call
    site still intercepts the sync.
    """
    await _pick_ban_sessions().sync_all_pick_ban_sessions_after_team_change(session, encounter)
    await lifecycle_notifier.on_encounter_changed(session, encounter, channel=channel)


async def advance_and_announce(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    channel: bool = True,
) -> AdvanceOutcome:
    """Advance ``encounter``'s standing, then settle what each filled seat owes.

    Advancement is the path where an already-scheduled slot finally learns who
    plays in it, so every encounter the bracket just put a team into gets the
    same upkeep as any other seat change: its pick-ban rooms follow the new
    pairing and both rosters hear who they play. The shared primitive cannot do
    this itself -- the notifier and the pick-ban service are this service's.
    """
    outcome = await advance_after_result(session, encounter)
    for target_id in dict.fromkeys(target for target, _slot in outcome.placed):
        await after_encounter_teams_changed(
            session, await session.get_one(models.Encounter, target_id), channel=channel
        )
    return outcome
