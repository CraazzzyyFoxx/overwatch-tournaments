"""The six mutations in tournament-service that append to somebody's inbox.

What is asserted throughout is the *observable* outcome: after the flow ran, a
``notification`` row exists (or does not), addressed to the right account, with
the snapshot the frontend renders. Never "the helper was called" -- a mock echo
would pass just as happily against a `notify()` that writes nothing.

The engine is in-memory SQLite behind a synchronous ``Session`` (no async SQLite
driver is installed), the shape ``test_scrim_recalculation_exclusion.py`` and
``test_notification_repository.py`` already use. Three things are patched, none
of them the behaviour under test:

* the two Redis-backed invite rate limiters (`assert_invite_attempt_allowed`,
  `assert_accept_attempt_allowed`) -- they meter, they do not decide anything a
  notification depends on;
* ``_assert_registration_open`` and ``_resolve_shape``, whose real
  implementations need the phase-schedule and roster-slot fixture graphs; the
  first is replaced by the *real* Tournament row the flow then snapshots, so the
  `tournament_name` in the payload still comes from the database;
* ``is_encounter_live`` / ``get_pick_ban_session`` for the map report, for the
  same reason.

The shim deliberately hides ``info``/``sync_session``: that is the handle the
realtime-staging factories look for, and without it they no-op, so these tests
exercise the notification write without dragging a ``workspace_event`` row and a
Redis publish into every assertion. The one exception is
``NotificationSignalListenerTests`` at the bottom, whose subject *is* the pair of
global ``Session`` listeners that drain ``Session.info`` after a commit or a
rollback -- it hands the real dict over and commits a real ``Session``.
"""

from __future__ import annotations

import sys
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core.enums import TournamentStatus  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.models.platform.notification import Notification  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from src import models  # noqa: E402
from src.schemas.registration import RegistrationCreate  # noqa: E402
from src.services.encounter import map_report as map_report_module  # noqa: E402
from src.services.registration import lifecycle as lifecycle_module  # noqa: E402
from src.services.registration import teams as teams_module  # noqa: E402
from src.services.tournament import events as events_module  # noqa: E402

install_postgres_type_shims()

TABLE_NAMES = (
    "notification",
    "event_outbox",
    "tournament.tournament",
    "tournament.tournament_phase_schedule",
    "tournament.team",
    "tournament.encounter",
    "tournament.encounter_map_report",
    "matches.match",
    "workspace",
    "players.user",
    "workspace_member",
    "balancer.registration",
    "balancer.registration_role",
    "balancer.registration_form",
    "balancer.registration_team",
    "balancer.registration_team_invite",
)

WORKSPACE_ID = 1
TOURNAMENT_ID = 10
TOURNAMENT_NAME = "Autumn Cup"

CAPTAIN_AUTH = 501
INVITEE_AUTH = 502
OPPONENT_AUTH = 503

FIVE_STACK = parse_roster_slots({"tank": 1, "dps": 2, "support": 2})


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session`` -- see the module docstring."""

    def __init__(self, session: Session) -> None:
        self._session = session
        # The shim's OWN scratch space, deliberately not the ``Session.info`` the
        # global ``before_flush``/``after_commit`` listeners drain. Producer code
        # that stages per-transaction state (the notification-signal recipients,
        # the tournament-name memo) works normally against it, while the
        # realtime-staging factories write their builders into a dict nothing
        # reads -- so no ``workspace_event`` row and no Redis publish is dragged
        # into these tests.
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

    async def get(self, entity, primary_key):  # noqa: ANN001, ANN202
        return self._session.get(entity, primary_key)

    def add(self, obj) -> None:  # noqa: ANN001
        self._session.add(obj)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        if name == "sync_session":
            # Hidden so ``info`` above is the one every producer reaches.
            raise AttributeError(name)
        return getattr(self._session, name)


class _Fixture:
    """A throwaway in-memory database plus the row builders these flows need."""

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
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.session.add(self.tournament)
        self.session.flush()

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    # -- builders ---------------------------------------------------------

    def player(self, name: str, *, auth_user_id: int | None) -> models.WorkspaceMember:
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
        team_id: int | None = None,
        slot_code: str | None = None,
    ) -> models.BalancerRegistration:
        registration = models.BalancerRegistration(
            tournament_id=TOURNAMENT_ID,
            workspace_member_id=member.id,
            battle_tag=battle_tag,
            status=status,
            registration_team_id=team_id,
            team_slot_code=slot_code,
            is_substitute=False,
        )
        self.session.add(registration)
        self.session.flush()
        return registration

    def team(self, name: str) -> models.BalancerRegistrationTeam:
        team = models.BalancerRegistrationTeam(
            workspace_id=WORKSPACE_ID,
            tournament_id=TOURNAMENT_ID,
            name=name,
            name_normalized=name.lower(),
            status=teams_module.TEAM_FORMING,
        )
        self.session.add(team)
        self.session.flush()
        return team

    def invite(
        self,
        team: models.BalancerRegistrationTeam,
        *,
        slot_code: str,
        target_auth_user_id: int | None,
    ) -> models.BalancerRegistrationTeamInvite:
        invite = models.BalancerRegistrationTeamInvite(
            team_id=team.id,
            slot_code=slot_code,
            is_substitute=False,
            target_auth_user_id=target_auth_user_id,
            state=teams_module.INVITE_PENDING,
            invited_by=CAPTAIN_AUTH,
        )
        self.session.add(invite)
        self.session.flush()
        return invite

    # -- assertions -------------------------------------------------------

    def notifications(self, kind: str | None = None) -> list[Notification]:
        statement = sa.select(Notification).order_by(Notification.id)
        if kind is not None:
            statement = statement.where(Notification.kind == kind)
        return list(self.session.scalars(statement))


def _auth_user(auth_user_id: int, username: str) -> SimpleNamespace:
    """What the flows read off the identity: an id and a display handle."""
    return SimpleNamespace(id=auth_user_id, username=username)


class _ProducerTestCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.close)


class TeamInviteReceivedTests(_ProducerTestCase):
    """``teams.py:invite_member`` -- only a targeted invite has an addressee."""

    def setUp(self) -> None:
        super().setUp()
        self.team = self.fx.team("Vanguard")
        captain_member = self.fx.player("Cap", auth_user_id=CAPTAIN_AUTH)
        captain_registration = self.fx.registration(
            captain_member, battle_tag="Cap#1111", team_id=self.team.id, slot_code="tank"
        )
        self.team.captain_registration_id = captain_registration.id
        invitee_member = self.fx.player("Rook", auth_user_id=INVITEE_AUTH)
        self.invitee_registration = self.fx.registration(invitee_member, battle_tag="Rook#2222")
        self.fx.session.flush()

        limiter = patch.object(teams_module, "assert_invite_attempt_allowed", AsyncMock())
        limiter.start()
        self.addCleanup(limiter.stop)
        window = patch.object(
            teams_module.RegistrationTeamService,
            "_assert_registration_open",
            AsyncMock(return_value=self.fx.tournament),
        )
        window.start()
        self.addCleanup(window.stop)
        shape = patch.object(teams_module.RegistrationTeamService, "_resolve_shape", AsyncMock(return_value=FIVE_STACK))
        shape.start()
        self.addCleanup(shape.stop)

    async def test_targeted_invite_notifies_the_invitee(self) -> None:
        invite, raw_token = await teams_module.teams_service.invite_member(
            self.fx.shim,
            team_id=self.team.id,
            auth_user=_auth_user(CAPTAIN_AUTH, "cap"),
            slot_code="dps",
            target_registration_id=self.invitee_registration.id,
        )

        self.assertIsNone(raw_token)
        rows = self.fx.notifications()
        self.assertEqual(1, len(rows))
        self.assertEqual("team_invite.received", rows[0].kind)
        self.assertEqual(INVITEE_AUTH, rows[0].recipient_auth_user_id)
        self.assertEqual(CAPTAIN_AUTH, rows[0].actor_auth_user_id)
        self.assertEqual(
            {
                "team_id": self.team.id,
                "team_name": "Vanguard",
                "tournament_id": TOURNAMENT_ID,
                "tournament_name": TOURNAMENT_NAME,
                "slot_code": "dps",
                "is_substitute": False,
                "invite_id": invite.id,
            },
            rows[0].payload_json,
        )

    async def test_link_invite_notifies_nobody(self) -> None:
        """A shareable token has no addressee -- there is nobody's inbox to write to."""
        _invite, raw_token = await teams_module.teams_service.invite_member(
            self.fx.shim,
            team_id=self.team.id,
            auth_user=_auth_user(CAPTAIN_AUTH, "cap"),
            slot_code="dps",
        )

        self.assertIsNotNone(raw_token)
        self.assertEqual([], self.fx.notifications())


class TeamInviteAnsweredTests(_ProducerTestCase):
    """``accept_invite`` / ``decline_invite`` -- the captain is the one waiting."""

    def setUp(self) -> None:
        super().setUp()
        self.team = self.fx.team("Vanguard")
        captain_member = self.fx.player("Cap", auth_user_id=CAPTAIN_AUTH)
        captain_registration = self.fx.registration(
            captain_member, battle_tag="Cap#1111", team_id=self.team.id, slot_code="tank"
        )
        self.team.captain_registration_id = captain_registration.id
        invitee_member = self.fx.player("Rook", auth_user_id=INVITEE_AUTH)
        # An existing free-agent registration: accepting attaches it to the team
        # rather than running the whole public-registration write path.
        self.invitee_registration = self.fx.registration(invitee_member, battle_tag="Rook#2222")
        self.invite = self.fx.invite(self.team, slot_code="dps", target_auth_user_id=INVITEE_AUTH)
        self.fx.session.flush()

        limiter = patch.object(teams_module, "assert_accept_attempt_allowed", AsyncMock())
        limiter.start()
        self.addCleanup(limiter.stop)
        window = patch.object(
            teams_module.RegistrationTeamService,
            "_assert_registration_open",
            AsyncMock(return_value=self.fx.tournament),
        )
        window.start()
        self.addCleanup(window.stop)
        shape = patch.object(teams_module.RegistrationTeamService, "_resolve_shape", AsyncMock(return_value=FIVE_STACK))
        shape.start()
        self.addCleanup(shape.stop)

    async def test_accept_notifies_the_captain(self) -> None:
        await teams_module.teams_service.accept_invite(
            self.fx.shim,
            auth_user=_auth_user(INVITEE_AUTH, "rook"),
            body=RegistrationCreate(),
            invite_id=self.invite.id,
        )

        rows = self.fx.notifications()
        self.assertEqual(1, len(rows))
        self.assertEqual("team_invite.answered", rows[0].kind)
        self.assertEqual(CAPTAIN_AUTH, rows[0].recipient_auth_user_id)
        self.assertEqual(
            {
                "team_id": self.team.id,
                "team_name": "Vanguard",
                "invite_id": self.invite.id,
                "answer": "accepted",
                "responder_name": "Rook#2222",
            },
            rows[0].payload_json,
        )

    async def test_decline_notifies_the_captain(self) -> None:
        await teams_module.teams_service.decline_invite(
            self.fx.shim,
            auth_user=_auth_user(INVITEE_AUTH, "rook"),
            invite_id=self.invite.id,
        )

        rows = self.fx.notifications()
        self.assertEqual(1, len(rows))
        self.assertEqual("team_invite.answered", rows[0].kind)
        self.assertEqual(CAPTAIN_AUTH, rows[0].recipient_auth_user_id)
        self.assertEqual("declined", rows[0].payload_json["answer"])
        self.assertEqual("Rook#2222", rows[0].payload_json["responder_name"])


class RegistrationDecisionTests(_ProducerTestCase):
    """``events.py`` -- the registrant learns their entry was decided."""

    def setUp(self) -> None:
        super().setUp()
        member = self.fx.player("Rook", auth_user_id=INVITEE_AUTH)
        self.registration = self.fx.registration(member, battle_tag="Rook#2222", status="pending")
        self.fx.session.flush()

    async def test_approve_notifies_the_player(self) -> None:
        self.registration.status = "approved"
        await events_module.enqueue_registration_approved(self.fx.shim, self.registration)
        await self.fx.shim.commit()

        rows = self.fx.notifications()
        self.assertEqual(1, len(rows))
        self.assertEqual("registration.approved", rows[0].kind)
        self.assertEqual(INVITEE_AUTH, rows[0].recipient_auth_user_id)
        self.assertEqual(
            {
                "tournament_id": TOURNAMENT_ID,
                "tournament_name": TOURNAMENT_NAME,
                "registration_id": self.registration.id,
            },
            rows[0].payload_json,
        )

    async def test_reject_notifies_the_player(self) -> None:
        self.registration.status = "rejected"
        await events_module.enqueue_registration_rejected(self.fx.shim, self.registration)
        await self.fx.shim.commit()

        rows = self.fx.notifications()
        self.assertEqual(1, len(rows))
        self.assertEqual("registration.rejected", rows[0].kind)
        self.assertEqual(INVITEE_AUTH, rows[0].recipient_auth_user_id)

    async def test_shadow_player_without_auth_user_is_skipped(self) -> None:
        """No account behind the player: no inbox, no exception, and the decision
        itself still goes through."""
        shadow_member = self.fx.player("Ghost", auth_user_id=None)
        shadow_registration = self.fx.registration(shadow_member, battle_tag="Ghost#3333", status="pending")
        shadow_registration.status = "approved"

        await events_module.enqueue_registration_approved(self.fx.shim, shadow_registration)
        await self.fx.shim.commit()

        self.assertEqual([], self.fx.notifications())
        self.assertEqual(
            "approved",
            self.fx.session.scalar(
                sa.select(models.BalancerRegistration.status).where(
                    models.BalancerRegistration.id == shadow_registration.id
                )
            ),
        )


class DisputedMapReportTests(_ProducerTestCase):
    """``map_report.py`` -- a contradiction needs an answer from BOTH captains."""

    def setUp(self) -> None:
        super().setUp()
        home_captain = self.fx.player("Cap", auth_user_id=CAPTAIN_AUTH)
        away_captain = self.fx.player("Rival", auth_user_id=OPPONENT_AUTH)
        home = models.Team(
            name="Vanguard",
            balancer_name="Vanguard",
            tournament_id=TOURNAMENT_ID,
            captain_id=home_captain.player_id,
        )
        away = models.Team(
            name="Rearguard",
            balancer_name="Rearguard",
            tournament_id=TOURNAMENT_ID,
            captain_id=away_captain.player_id,
        )
        self.fx.session.add_all([home, away])
        self.fx.session.flush()
        self.encounter = models.Encounter(
            tournament_id=TOURNAMENT_ID,
            name="Vanguard vs Rearguard",
            home_team_id=home.id,
            away_team_id=away.id,
            home_score=0,
            away_score=0,
            round=1,
            closeness=0.0,
            best_of=3,
        )
        self.fx.session.add(self.encounter)
        self.fx.session.flush()
        self.home_team_id = home.id
        self.away_team_id = away.id
        # The opponent already reported a contradicting score for this map.
        self.fx.session.add(
            models.EncounterMapReport(
                encounter_id=self.encounter.id,
                map_id=77,
                map_index=0,
                team_id=away.id,
                home_score=1,
                away_score=3,
            )
        )
        self.fx.session.flush()

        live = patch.object(map_report_module, "is_encounter_live", AsyncMock(return_value=True))
        live.start()
        self.addCleanup(live.stop)
        session_lookup = patch.object(
            map_report_module.pick_ban_session_service, "get_pick_ban_session", AsyncMock(return_value=None)
        )
        session_lookup.start()
        self.addCleanup(session_lookup.stop)

    async def test_disputed_map_report_notifies_both_captains(self) -> None:
        result = await map_report_module.map_report_service.submit_map_report(
            self.fx.shim,
            self.encounter,
            map_id=77,
            team_id=self.home_team_id,
            reporter_user_id=CAPTAIN_AUTH,
            home_score=3,
            away_score=1,
        )

        self.assertTrue(result["disputed"])
        rows = self.fx.notifications()
        self.assertEqual({CAPTAIN_AUTH, OPPONENT_AUTH}, {row.recipient_auth_user_id for row in rows})
        self.assertEqual({"encounter.report_disputed"}, {row.kind for row in rows})
        self.assertEqual(
            {
                "encounter_id": self.encounter.id,
                "tournament_id": TOURNAMENT_ID,
                "map_id": 77,
                "map_index": 0,
            },
            rows[0].payload_json,
        )


class RegistrationDecisionQueryBudgetTests(_ProducerTestCase):
    """The two snapshot reads must not be re-issued when the flow already holds
    the rows, and must not scale with the size of a batch.

    Both claims are invisible to a "the notification was created" assertion --
    the rows come out identical either way -- so this counts the statements the
    engine actually sees, matching selected columns by lineage rather than by SQL
    text.

    The admin review paths reach the producer with a registration loaded by
    ``get_registration_by_id``, whose options already eager-load ``tournament``
    and ``workspace_member.player``: re-reading either is pure waste.
    ``bulk_approve_registrations`` reaches it with a bare registration, N times
    for ONE tournament: re-reading the name there is an N+1 that grows with the
    batch. Five registrations rather than two, so a per-row read is unmistakable
    -- this reads 1 where the N+1 reads 5.

    The fixture's own tournament is expunged first; production callers of the
    bulk path do not hold it, and leaving it in the identity map would make the
    count zero for reasons the code under test does not own.
    """

    def setUp(self) -> None:
        super().setUp()
        self.fx.session.expunge(self.fx.tournament)
        self.statements: list[object] = []
        event.listen(self.fx.engine, "before_execute", self._record)
        self.addCleanup(event.remove, self.fx.engine, "before_execute", self._record)

    def _record(self, _conn, clauseelement, _multiparams, _params, _execution_options) -> None:  # noqa: ANN001
        self.statements.append(clauseelement)

    def _reads_of(self, column) -> int:  # noqa: ANN001
        """Statements projecting ``column``, matched on the column object's
        lineage rather than on SQL text (an ORM-annotated column is not the same
        object as the table's)."""
        return sum(
            1
            for statement in self.statements
            if isinstance(statement, sa.Select)
            and any(selected.shares_lineage(column) for selected in statement.selected_columns)
        )

    def _tournament_name_reads(self) -> int:
        return self._reads_of(models.Tournament.__table__.c.name)

    async def _approve_batch(self, size: int) -> int:
        registration_ids = []
        for index in range(size):
            member = self.fx.player(f"Player{index}", auth_user_id=700 + index)
            registration_ids.append(self.fx.registration(member, battle_tag=f"Player{index}#1000", status="pending").id)
        self.fx.session.flush()
        self.statements.clear()
        approved, _skipped = await lifecycle_module.lifecycle_service.bulk_approve_registrations(
            self.fx.shim, TOURNAMENT_ID, registration_ids, reviewed_by=None
        )
        self.assertEqual(size, approved)
        return self._tournament_name_reads()

    async def test_bulk_approval_reads_the_tournament_name_once_per_batch(self) -> None:
        self.assertEqual(1, await self._approve_batch(5))

    async def test_every_registration_in_the_batch_is_still_notified(self) -> None:
        """The budget above must not be bought by dropping notifications."""
        await self._approve_batch(5)
        self.assertEqual(5, len(self.fx.notifications("registration.approved")))

    async def test_an_eager_loaded_registration_re_reads_neither_snapshot(self) -> None:
        member = self.fx.player("Loaded", auth_user_id=800)
        registration_id = self.fx.registration(member, battle_tag="Loaded#4000", status="pending").id
        self.fx.session.flush()
        self.fx.session.expire_all()
        registration = self.fx.session.scalar(
            sa.select(models.BalancerRegistration)
            .where(models.BalancerRegistration.id == registration_id)
            .options(
                selectinload(models.BalancerRegistration.tournament),
                selectinload(models.BalancerRegistration.workspace_member).selectinload(models.WorkspaceMember.player),
            )
        )
        registration.status = "approved"
        self.statements.clear()

        await events_module.enqueue_registration_approved(self.fx.shim, registration)
        await self.fx.shim.commit()

        self.assertEqual(0, self._tournament_name_reads())
        self.assertEqual(0, self._reads_of(models.User.__table__.c.auth_user_id))
        row = self.fx.notifications("registration.approved")[0]
        self.assertEqual(800, row.recipient_auth_user_id)
        self.assertEqual(TOURNAMENT_NAME, row.payload_json["tournament_name"])


class _RecordingRedis:
    """The realtime Redis, minus the socket: records what was published."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))


class _CommittingSessionShim(_AsyncSessionShim):
    """The same async facade, sharing the real ``Session.info``.

    The base shim hides ``info`` on purpose (see the module docstring). The two
    listeners under test below are registered on ``Session`` and drain exactly
    that dict, so this is the one place that has to hand it over.
    """

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.info = session.info


MATE_AUTH = 504


class TeamRosterOutcomeTests(_ProducerTestCase):
    """Kick, reject and disband must write inbox rows *before* the roster is
    withdrawn — `_roster_members` hides withdrawn players, so notifying
    afterwards is a silent no-op.
    """

    def setUp(self) -> None:
        super().setUp()
        self.team = self.fx.team("Vanguard")
        captain_member = self.fx.player("Cap", auth_user_id=CAPTAIN_AUTH)
        captain_registration = self.fx.registration(
            captain_member, battle_tag="Cap#1111", team_id=self.team.id, slot_code="tank"
        )
        self.team.captain_registration_id = captain_registration.id
        mate_member = self.fx.player("Mate", auth_user_id=MATE_AUTH)
        self.mate_registration = self.fx.registration(
            mate_member, battle_tag="Mate#2222", team_id=self.team.id, slot_code="dps"
        )
        self.fx.session.flush()

        window = patch.object(
            teams_module.RegistrationTeamService,
            "_assert_registration_open",
            AsyncMock(return_value=self.fx.tournament),
        )
        window.start()
        self.addCleanup(window.stop)
        shape = patch.object(teams_module.RegistrationTeamService, "_resolve_shape", AsyncMock(return_value=FIVE_STACK))
        shape.start()
        self.addCleanup(shape.stop)

    async def test_kick_notifies_the_removed_player(self) -> None:
        await teams_module.teams_service.kick_member(
            self.fx.shim,
            team_id=self.team.id,
            registration_id=self.mate_registration.id,
            auth_user=_auth_user(CAPTAIN_AUTH, "cap"),
        )
        rows = self.fx.notifications("team.kicked")
        self.assertEqual(1, len(rows))
        self.assertEqual(MATE_AUTH, rows[0].recipient_auth_user_id)
        self.assertEqual("Vanguard", rows[0].payload_json["team_name"])

    async def test_disband_notifies_every_member(self) -> None:
        await teams_module.teams_service.disband_team(
            self.fx.shim,
            team_id=self.team.id,
            auth_user=_auth_user(CAPTAIN_AUTH, "cap"),
        )
        rows = self.fx.notifications("team.disbanded")
        self.assertEqual({CAPTAIN_AUTH, MATE_AUTH}, {row.recipient_auth_user_id for row in rows})

    async def test_reject_notifies_every_member_with_the_reason(self) -> None:
        await teams_module.teams_service.reject_team(
            self.fx.shim,
            tournament_id=TOURNAMENT_ID,
            team_id=self.team.id,
            auth_user=_auth_user(CAPTAIN_AUTH, "cap"),
            reason="  Duplicate roster \n",
        )
        rows = self.fx.notifications("team.rejected")
        self.assertEqual({CAPTAIN_AUTH, MATE_AUTH}, {row.recipient_auth_user_id for row in rows})
        self.assertEqual("Duplicate roster", rows[0].payload_json["reason"])
        self.fx.session.expire_all()
        rejected = self.fx.session.get(models.BalancerRegistrationTeam, self.team.id)
        self.assertEqual("Duplicate roster", rejected.rejection_reason)
        members = list(self.fx.session.scalars(sa.select(models.BalancerRegistration)))
        self.assertEqual({"approved"}, {member.status for member in members})
        self.assertTrue(all(member.registration_team_id is None for member in members))
        self.assertTrue(all(member.team_slot_code is None and not member.is_substitute for member in members))
        for account, expected in ((None, []), (MATE_AUTH, []), (CAPTAIN_AUTH, [self.team.id])):
            visible = await teams_module.teams_service.list_teams(
                self.fx.shim,
                tournament_id=TOURNAMENT_ID,
                include_terminal_for_auth_user_id=account,
            )
            self.assertEqual(expected, [team.id for team, _occupancy in visible])
        self.assertTrue(await teams_module.teams_service.is_team_staff(self.fx.shim, rejected, CAPTAIN_AUTH))

    async def test_explicit_withdrawal_retains_the_rejected_team_link_and_revokes_offers(self) -> None:
        invite = self.fx.invite(self.team, slot_code="support", target_auth_user_id=INVITEE_AUTH)
        await teams_module.teams_service.reject_team(
            self.fx.shim,
            tournament_id=TOURNAMENT_ID,
            team_id=self.team.id,
            auth_user=_auth_user(CAPTAIN_AUTH, "cap"),
            reason="Ineligible roster",
            withdraw_members=True,
        )
        self.fx.session.expire_all()
        members = list(self.fx.session.scalars(sa.select(models.BalancerRegistration)))
        self.assertEqual({"withdrawn"}, {member.status for member in members})
        self.assertEqual({self.team.id}, {member.registration_team_id for member in members})
        self.assertEqual(teams_module.INVITE_REVOKED, invite.state)


class TargetedInviteAvailabilityTests(_ProducerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.window = models.TournamentPhaseSchedule(
            tournament_id=TOURNAMENT_ID,
            status=TournamentStatus.REGISTRATION,
            starts_at=datetime.now(UTC) - timedelta(days=1),
        )
        self.fx.session.add(self.window)
        self.fx.session.add(
            models.BalancerRegistrationForm(tournament_id=TOURNAMENT_ID, workspace_id=WORKSPACE_ID, max_substitutes=1)
        )
        shape = patch.object(
            teams_module.RegistrationTeamService,
            "_resolve_shape",
            AsyncMock(return_value=parse_roster_slots({"tank": 1, "dps": 1})),
        )
        shape.start()
        self.addCleanup(shape.stop)
        self.team = self.fx.team("Complete")
        self.team.status = teams_module.TEAM_COMPLETE
        captain = self.fx.player("Cap", auth_user_id=CAPTAIN_AUTH)
        self.fx.registration(captain, battle_tag="Cap#1111", team_id=self.team.id, slot_code="tank")
        self.offer = self.fx.invite(self.team, slot_code="tank", target_auth_user_id=INVITEE_AUTH)
        self.offer.is_substitute = True
        self.fx.session.flush()

    async def _offers(self) -> list[int]:
        self.fx.session.flush()
        offers = await teams_module.teams_service.list_my_invites(
            self.fx.shim,
            tournament_id=TOURNAMENT_ID,
            auth_user=_auth_user(INVITEE_AUTH, "invitee"),
        )
        return [offer.invite_id for offer in offers]

    async def test_complete_team_bench_offer_is_visible_until_unavailable(self) -> None:
        self.assertEqual([self.offer.id], await self._offers())
        unavailable = (
            (self.team, "roster_locked_at", datetime.now(UTC)),
            (self.team, "exported_team_id", 999),
            (self.team, "status", teams_module.TEAM_REJECTED),
            (self.team, "status", teams_module.TEAM_DISBANDED),
            (self.team, "deleted_at", datetime.now(UTC)),
            (self.offer, "state", teams_module.INVITE_REVOKED),
            (self.offer, "expires_at", datetime.now(UTC) - timedelta(days=1)),
            (self.offer, "target_auth_user_id", OPPONENT_AUTH),
            (self.offer, "target_auth_user_id", None),
            (self.offer, "is_substitute", False),
            (self.window, "ends_at", datetime.now(UTC) - timedelta(hours=1)),
        )
        for row, attribute, value in unavailable:
            original = getattr(row, attribute)
            with self.subTest(attribute=attribute, value=value):
                setattr(row, attribute, value)
                self.assertEqual([], await self._offers())
            setattr(row, attribute, original)
        substitute = self.fx.player("Bench", auth_user_id=OPPONENT_AUTH)
        registration = self.fx.registration(substitute, battle_tag="Bench#3333", team_id=self.team.id, slot_code="tank")
        registration.is_substitute = True
        self.assertEqual([], await self._offers())

    async def test_terminal_recipient_registration_hides_the_offer(self) -> None:
        invitee = self.fx.player("Invitee", auth_user_id=INVITEE_AUTH)
        self.fx.registration(invitee, battle_tag="Invitee#2222", status="withdrawn")
        self.assertEqual([], await self._offers())
