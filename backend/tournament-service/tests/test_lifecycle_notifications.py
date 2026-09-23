"""The three tournament lifecycle events that reach an inbox or a channel.

Same shape (and same reasoning) as ``test_notification_producers.py``: an
in-memory SQLite database behind a synchronous ``Session``, and what is
asserted is the *observable* outcome -- which ``notification`` rows exist,
addressed to whom, and which ``event_outbox`` rows carry the broadcast. Never
"the notifier was called".

``broadcast()`` enqueues on every call by design (the once-only guarantee for a
channel post is the delivery ledger in app-service, not the producer), so a
repeated transition is asserted on the notification rows: those must not
double.

The pick-ban team-change sync is patched in the advancement test alone. It is
not the subject there, and its real implementation would need the map pool,
settings and readiness fixtures of a whole veto engine to say "no session to
sync".
"""

from __future__ import annotations

import sys
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.core.enums import TournamentStatus  # noqa: E402
from shared.models.platform.notification import Notification  # noqa: E402
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from src import models  # noqa: E402
from src.services.encounter import finalize as finalize_module  # noqa: E402
from src.services.notifications.lifecycle import lifecycle_notifier  # noqa: E402

install_postgres_type_shims()

TABLE_NAMES = (
    "notification",
    "event_outbox",
    "workspace",
    "players.user",
    "workspace_member",
    "balancer.registration",
    "matches.match",
    "tournament.tournament",
    "tournament.tournament_phase_schedule",
    "tournament.team",
    "tournament.player",
    "tournament.encounter",
    "tournament.encounter_link",
)

WORKSPACE_ID = 1
TOURNAMENT_ID = 10
TOURNAMENT_NAME = "Autumn Cup"

BROADCAST_ROUTING_KEY = "notification.broadcast"


def _instant(stored: str) -> datetime:
    """A payload timestamp as an instant.

    SQLite has no timezone-aware column type, so a value that made a round trip
    through it comes back naive (in UTC). What the payload has to carry is the
    moment, not the offset spelling.
    """
    value = datetime.fromisoformat(stored)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session``.

    ``info`` is the shim's own dict and ``sync_session`` is hidden, so the
    realtime-staging factories inside ``notify()`` no-op -- see the
    ``test_notification_producers`` docstring for why.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self.info: dict[Any, Any] = {}

    async def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self._session.execute(statement, *args, **kwargs)

    async def scalar(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self._session.scalar(statement, *args, **kwargs)

    async def scalars(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self._session.scalars(statement, *args, **kwargs)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, obj) -> None:  # noqa: ANN001
        self._session.refresh(obj)

    async def get(self, entity, primary_key, **kwargs):  # noqa: ANN001, ANN003, ANN202
        # ``**kwargs`` for ``with_for_update``: bracket advancement locks the
        # target encounter it is about to fill in.
        return self._session.get(entity, primary_key, **kwargs)

    def add(self, obj) -> None:  # noqa: ANN001
        self._session.add(obj)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        if name == "sync_session":
            raise AttributeError(name)
        return getattr(self._session, name)


class _Fixture:
    """A throwaway in-memory database plus the rows these hooks read."""

    def __init__(self) -> None:
        metadata = models.Tournament.__table__.metadata
        tables = [metadata.tables[name] for name in TABLE_NAMES]
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)
        self.session = Session(self.engine, expire_on_commit=False)
        self.shim = _AsyncSessionShim(self.session)
        self.tournament = models.Tournament(
            id=TOURNAMENT_ID,
            workspace_id=WORKSPACE_ID,
            name=TOURNAMENT_NAME,
            slug="autumn-cup",
            is_hidden=False,
            is_league=False,
            status=TournamentStatus.ANNOUNCEMENT,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.session.add(self.tournament)
        self.session.flush()

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    # -- builders ---------------------------------------------------------

    def schedule(self, status: TournamentStatus, *, starts_at: datetime, ends_at: datetime | None = None) -> None:
        self.session.add(
            models.TournamentPhaseSchedule(
                tournament_id=TOURNAMENT_ID,
                status=status,
                starts_at=starts_at,
                ends_at=ends_at,
            )
        )
        self.session.flush()

    def member(self, name: str, *, auth_user_id: int | None) -> models.WorkspaceMember:
        """A domain player plus their workspace membership.

        ``auth_user_id=None`` is a shadow player: a real competitor with no site
        account behind them, which every recipient resolution has to survive.
        """
        user = models.User(name=name, auth_user_id=auth_user_id)
        self.session.add(user)
        self.session.flush()
        member = models.WorkspaceMember(workspace_id=WORKSPACE_ID, player_id=user.id)
        self.session.add(member)
        self.session.flush()
        return member

    def registration(
        self,
        member: models.WorkspaceMember,
        *,
        battle_tag: str,
        status: str = "approved",
        checked_in: bool = False,
        deleted_at: datetime | None = None,
    ) -> models.BalancerRegistration:
        registration = models.BalancerRegistration(
            tournament_id=TOURNAMENT_ID,
            workspace_member_id=member.id,
            battle_tag=battle_tag,
            status=status,
            checked_in=checked_in,
            deleted_at=deleted_at,
            is_substitute=False,
        )
        self.session.add(registration)
        self.session.flush()
        return registration

    def team(self, name: str, *members: models.WorkspaceMember) -> models.Team:
        team = models.Team(tournament_id=TOURNAMENT_ID, name=name, balancer_name=name)
        self.session.add(team)
        self.session.flush()
        for index, member in enumerate(members):
            self.session.add(
                models.Player(
                    name=f"{name}-{index}",
                    rank=3000,
                    tournament_id=TOURNAMENT_ID,
                    workspace_member_id=member.id,
                    team_id=team.id,
                )
            )
        self.session.flush()
        return team

    def encounter(
        self,
        *,
        home_team_id: int | None,
        away_team_id: int | None,
        scheduled_at: datetime | None,
        round_number: int = 1,
    ) -> models.Encounter:
        encounter = models.Encounter(
            name="match",
            tournament_id=TOURNAMENT_ID,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=0,
            away_score=0,
            round=round_number,
            scheduled_at=scheduled_at,
            status=enums.EncounterStatus.OPEN,
            result_status=enums.EncounterResultStatus.NONE,
        )
        self.session.add(encounter)
        self.session.flush()
        return encounter

    # -- assertions -------------------------------------------------------

    def notifications(self, kind: str | None = None) -> list[Notification]:
        statement = sa.select(Notification).order_by(Notification.id)
        if kind is not None:
            statement = statement.where(Notification.kind == kind)
        return list(self.session.scalars(statement))

    def recipients(self, kind: str) -> list[int]:
        return sorted(row.recipient_auth_user_id for row in self.notifications(kind))

    def broadcasts(self) -> list[EventOutbox]:
        return list(
            self.session.scalars(
                sa.select(EventOutbox)
                .where(EventOutbox.routing_key == BROADCAST_ROUTING_KEY)
                .order_by(EventOutbox.id)
            )
        )


class _LifecycleTestCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.close)

    async def _enter(self, status: TournamentStatus) -> None:
        self.fx.tournament.status = status
        await lifecycle_notifier.on_status_entered(self.fx.shim, self.fx.tournament)


class RegistrationOpenedTests(_LifecycleTestCase):
    """Entering REGISTRATION announces a sign-up that actually works."""

    async def test_an_open_window_announces_to_the_workspace_and_the_channel(self) -> None:
        closes_at = datetime.now(UTC) + timedelta(days=2)
        self.fx.schedule(
            TournamentStatus.REGISTRATION,
            starts_at=datetime.now(UTC) - timedelta(hours=1),
            ends_at=closes_at,
        )

        await self._enter(TournamentStatus.REGISTRATION)

        rows = self.fx.notifications("registration.opened")
        self.assertEqual(1, len(rows))
        self.assertEqual("workspace", rows[0].audience)
        self.assertEqual(WORKSPACE_ID, rows[0].workspace_id)
        self.assertEqual(TOURNAMENT_NAME, rows[0].payload_json["tournament_name"])
        self.assertEqual(closes_at, _instant(rows[0].payload_json["closes_at"]))
        self.assertEqual(f"tournament:{TOURNAMENT_ID}", rows[0].dedupe_key)
        self.assertEqual(1, len(self.fx.broadcasts()))

    async def test_a_window_that_has_not_started_announces_nothing(self) -> None:
        """A manual transition ahead of the schedule leaves the register button
        refusing; inviting people to it is worse than silence."""
        self.fx.schedule(
            TournamentStatus.REGISTRATION,
            starts_at=datetime.now(UTC) + timedelta(days=1),
            ends_at=datetime.now(UTC) + timedelta(days=3),
        )

        await self._enter(TournamentStatus.REGISTRATION)

        self.assertEqual([], self.fx.notifications())
        self.assertEqual([], self.fx.broadcasts())

    async def test_late_registration_promises_no_closing_time(self) -> None:
        self.fx.tournament.allow_late_registration = True
        self.fx.schedule(
            TournamentStatus.REGISTRATION,
            starts_at=datetime.now(UTC) - timedelta(days=3),
            ends_at=datetime.now(UTC) - timedelta(days=1),
        )

        await self._enter(TournamentStatus.REGISTRATION)

        rows = self.fx.notifications("registration.opened")
        self.assertEqual(1, len(rows))
        self.assertNotIn("closes_at", rows[0].payload_json)

    async def test_a_hidden_tournament_is_not_announced_at_all(self) -> None:
        self.fx.tournament.is_hidden = True
        self.fx.schedule(TournamentStatus.REGISTRATION, starts_at=datetime.now(UTC) - timedelta(hours=1))

        await self._enter(TournamentStatus.REGISTRATION)

        self.assertEqual([], self.fx.notifications())
        self.assertEqual([], self.fx.broadcasts())

    async def test_muted_discord_keeps_the_workspace_row_but_posts_nothing(self) -> None:
        self.fx.tournament.discord_broadcasts_enabled = False
        self.fx.schedule(TournamentStatus.REGISTRATION, starts_at=datetime.now(UTC) - timedelta(hours=1))

        await self._enter(TournamentStatus.REGISTRATION)

        self.assertEqual(1, len(self.fx.notifications("registration.opened")))
        self.assertEqual([], self.fx.broadcasts())

    async def test_re_entering_the_phase_does_not_write_a_second_row(self) -> None:
        """Status flap (REGISTRATION -> ANNOUNCEMENT -> REGISTRATION)."""
        self.fx.schedule(TournamentStatus.REGISTRATION, starts_at=datetime.now(UTC) - timedelta(hours=1))

        await self._enter(TournamentStatus.REGISTRATION)
        await self._enter(TournamentStatus.ANNOUNCEMENT)
        await self._enter(TournamentStatus.REGISTRATION)

        self.assertEqual(1, len(self.fx.notifications("registration.opened")))


class CheckInOpenedTests(_LifecycleTestCase):
    """Entering CHECK_IN tells the people who still owe a check-in."""

    def setUp(self) -> None:
        super().setUp()
        self.expected = self.fx.member("Approved", auth_user_id=601)
        self.fx.registration(self.expected, battle_tag="Approved#1")
        self.fx.registration(
            self.fx.member("Pending", auth_user_id=602),
            battle_tag="Pending#1",
            status="pending",
        )
        self.fx.registration(
            self.fx.member("Checked", auth_user_id=603),
            battle_tag="Checked#1",
            checked_in=True,
        )
        self.fx.registration(
            self.fx.member("Withdrawn", auth_user_id=604),
            battle_tag="Withdrawn#1",
            deleted_at=datetime.now(UTC),
        )
        self.fx.registration(self.fx.member("Shadow", auth_user_id=None), battle_tag="Shadow#1")

    async def test_only_approved_unchecked_registrations_with_an_account_are_told(self) -> None:
        self.fx.schedule(TournamentStatus.CHECK_IN, starts_at=datetime.now(UTC) - timedelta(minutes=5))

        await self._enter(TournamentStatus.CHECK_IN)

        self.assertEqual([601], self.fx.recipients("check_in.opened"))
        self.assertEqual("user", self.fx.notifications("check_in.opened")[0].audience)
        self.assertEqual(WORKSPACE_ID, self.fx.notifications("check_in.opened")[0].source_workspace_id)
        self.assertEqual(1, len(self.fx.broadcasts()))

    async def test_a_missing_schedule_row_spans_the_whole_phase(self) -> None:
        """Unlike registration, check-in without a row is open for the phase --
        ``is_within_phase_window``'s documented contract."""
        await self._enter(TournamentStatus.CHECK_IN)

        self.assertEqual([601], self.fx.recipients("check_in.opened"))

    async def test_a_window_that_has_not_started_tells_nobody(self) -> None:
        self.fx.schedule(TournamentStatus.CHECK_IN, starts_at=datetime.now(UTC) + timedelta(hours=2))

        await self._enter(TournamentStatus.CHECK_IN)

        self.assertEqual([], self.fx.notifications())
        self.assertEqual([], self.fx.broadcasts())

    async def test_a_hidden_tournament_still_tells_its_own_registrants(self) -> None:
        """They are registered already -- what must not happen is the channel
        post and the workspace-wide row."""
        self.fx.tournament.is_hidden = True
        self.fx.schedule(TournamentStatus.CHECK_IN, starts_at=datetime.now(UTC) - timedelta(minutes=5))

        await self._enter(TournamentStatus.CHECK_IN)

        self.assertEqual([601], self.fx.recipients("check_in.opened"))
        self.assertEqual([], self.fx.broadcasts())

    async def test_muted_discord_still_tells_registrants_but_posts_nothing(self) -> None:
        self.fx.tournament.discord_broadcasts_enabled = False
        self.fx.schedule(TournamentStatus.CHECK_IN, starts_at=datetime.now(UTC) - timedelta(minutes=5))

        await self._enter(TournamentStatus.CHECK_IN)

        self.assertEqual([601], self.fx.recipients("check_in.opened"))
        self.assertEqual([], self.fx.broadcasts())

    async def test_re_entering_the_phase_does_not_write_a_second_row(self) -> None:
        self.fx.schedule(TournamentStatus.CHECK_IN, starts_at=datetime.now(UTC) - timedelta(minutes=5))

        await self._enter(TournamentStatus.CHECK_IN)
        await self._enter(TournamentStatus.CHECK_IN)

        self.assertEqual(1, len(self.fx.notifications("check_in.opened")))

    async def test_another_phase_notifies_nobody(self) -> None:
        await self._enter(TournamentStatus.LIVE)

        self.assertEqual([], self.fx.notifications())


class EncounterScheduledTests(_LifecycleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.fx.team("Home", self.fx.member("HomePlayer", auth_user_id=701))
        self.away = self.fx.team("Away", self.fx.member("AwayPlayer", auth_user_id=702))
        self.later = datetime.now(UTC) + timedelta(days=1)

    async def _changed(self, encounter: models.Encounter) -> None:
        await lifecycle_notifier.on_encounter_changed(self.fx.shim, encounter)

    async def test_a_future_time_tells_both_rosters_and_the_channel(self) -> None:
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=self.later,
        )

        await self._changed(encounter)

        self.assertEqual([701, 702], self.fx.recipients("encounter.scheduled"))
        payload = self.fx.notifications("encounter.scheduled")[0].payload_json
        self.assertEqual(encounter.id, payload["encounter_id"])
        self.assertEqual("Home", payload["home_team_name"])
        self.assertEqual("Away", payload["away_team_name"])
        self.assertEqual(self.later, _instant(payload["scheduled_at"]))
        self.assertEqual(1, len(self.fx.broadcasts()))

    async def test_muted_discord_still_tells_both_rosters_but_posts_nothing(self) -> None:
        self.fx.tournament.discord_broadcasts_enabled = False
        self.fx.session.flush()
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=self.later,
        )

        await self._changed(encounter)

        self.assertEqual([701, 702], self.fx.recipients("encounter.scheduled"))
        self.assertEqual([], self.fx.broadcasts())

    async def test_the_same_time_saved_again_writes_nothing(self) -> None:
        """The round scheduler sends one PATCH per encounter, carrying the time
        it already has."""
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=self.later,
        )

        await self._changed(encounter)
        after_first = len(self.fx.notifications("encounter.scheduled"))
        await self._changed(encounter)

        self.assertEqual(2, after_first)
        self.assertEqual(after_first, len(self.fx.notifications("encounter.scheduled")))

    async def test_a_new_time_is_a_new_notification(self) -> None:
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=self.later,
        )
        await self._changed(encounter)

        encounter.scheduled_at = self.later + timedelta(hours=3)
        await self._changed(encounter)

        self.assertEqual(4, len(self.fx.notifications("encounter.scheduled")))
        self.assertEqual(2, len(self.fx.broadcasts()))

    async def test_a_time_in_the_past_is_silent(self) -> None:
        """Backfilled brackets and Challonge imports carry played-match times."""
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=datetime.now(UTC) - timedelta(hours=1),
        )

        await self._changed(encounter)

        self.assertEqual([], self.fx.notifications())

    async def test_an_empty_slot_is_silent(self) -> None:
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=None,
            scheduled_at=self.later,
        )

        await self._changed(encounter)

        self.assertEqual([], self.fx.notifications())

    async def test_an_unscheduled_encounter_is_silent(self) -> None:
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=None,
        )

        await self._changed(encounter)

        self.assertEqual([], self.fx.notifications())

    async def test_a_finished_tournament_is_silent(self) -> None:
        self.fx.tournament.status = TournamentStatus.COMPLETED
        self.fx.session.flush()
        encounter = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=self.later,
        )

        await self._changed(encounter)

        self.assertEqual([], self.fx.notifications())

    async def test_bracket_advancement_tells_the_team_that_just_arrived(self) -> None:
        """The scheduled slot whose opponent was still TBD: the time was set
        long before the semi-final was played."""
        source = self.fx.encounter(
            home_team_id=self.home.id,
            away_team_id=self.away.id,
            scheduled_at=None,
        )
        target = self.fx.encounter(
            home_team_id=self.fx.team("Final", self.fx.member("FinalPlayer", auth_user_id=703)).id,
            away_team_id=None,
            scheduled_at=self.later,
            round_number=2,
        )
        self.fx.session.add(
            models.EncounterLink(
                source_encounter_id=source.id,
                target_encounter_id=target.id,
                role=enums.EncounterLinkRole.WINNER,
                target_slot=enums.EncounterLinkSlot.AWAY,
            )
        )
        self.fx.session.flush()

        with patch.object(
            finalize_module.pick_ban_session_service,
            "sync_all_pick_ban_sessions_after_team_change",
            AsyncMock(),
        ):
            await finalize_module.finalize_service.finalize_encounter_score(
                self.fx.shim,
                source.id,
                home_score=2,
                away_score=0,
                source="admin",
            )

        self.assertEqual(self.home.id, target.away_team_id)
        self.assertEqual([701, 703], self.fx.recipients("encounter.scheduled"))
