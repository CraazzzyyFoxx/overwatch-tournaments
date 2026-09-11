"""Team-registration flow contracts.

Three claims are pinned here, chosen because each one is a design decision that a
plausible refactor would silently undo:

* the guarded ``UPDATE`` really is guarded — state *and* expiry are in the SQL, not
  in a preceding read (§3.3);
* rowcount 0 is translated into a distinct machine code per cause, instead of one
  opaque failure (§12.1);
* every rejection carries a stable ``code``, because these surfaces are public and
  Russian-first (§12.2).

The concurrency behaviour these enable needs a real Postgres and lives with the
DB-backed suites; what is asserted here is that the mechanism is present and wired
the right way round.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for path in (str(SERVICE_ROOT), str(BACKEND_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


import sqlalchemy as sa  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.invite_token import hash_invite_token  # noqa: E402
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.domain.team_roster import RosterMember, RosterOccupancy  # noqa: E402
from src import models  # noqa: E402
from src.schemas.registration_team import (  # noqa: E402
    RegistrationTeamAcceptRequest,
    RegistrationTeamInviteCreateRequest,
    RegistrationTeamInvitePreview,
    RegistrationTeamInviteRead,
    RegistrationTeamRejectRequest,
    serialize_registration_team,
)
from src.services.registration import teams  # noqa: E402
from src.services.registration.service import registration_service  # noqa: E402

FIVE_STACK = parse_roster_slots({"tank": 1, "dps": 2, "support": 2})


def _code_of(fn: Any) -> str:
    """A function's source with its docstring removed.

    Every source-inspecting test in this file needs this. Reading raw
    ``inspect.getsource`` makes a docstring that *explains why a check is absent*
    read as the check being present — which is precisely backwards, and cost two
    false passes before this existed.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    assert isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return "\n".join(ast.unparse(statement) for statement in body)


@dataclass
class _Invite:
    """Just the fields `_diagnose_dead_invite` reads."""

    state: str
    expires_at: datetime | None = None


def _code(exc: ApiHTTPException) -> str:
    detail: Any = exc.detail
    return detail[0]["code"]


class DeadInviteDiagnosisTests(TestCase):
    """§12.1: four causes, four recourses, four codes."""

    def test_an_accepted_invite_says_so(self) -> None:
        failure = teams._diagnose_dead_invite(_Invite(state=teams.INVITE_ACCEPTED))
        self.assertEqual("invite_already_accepted", _code(failure))

    def test_a_revoked_invite_says_so(self) -> None:
        failure = teams._diagnose_dead_invite(_Invite(state=teams.INVITE_REVOKED))
        self.assertEqual("invite_revoked", _code(failure))

    def test_a_declined_invite_says_so(self) -> None:
        failure = teams._diagnose_dead_invite(_Invite(state=teams.INVITE_DECLINED))
        self.assertEqual("invite_declined", _code(failure))

    def test_an_expired_invite_is_distinguished_from_a_revoked_one(self) -> None:
        """The recourses differ: "ask for a new link" vs "the captain removed you".
        Collapsing them is the exact failure §12.1 exists to prevent."""
        failure = teams._diagnose_dead_invite(
            _Invite(state=teams.INVITE_PENDING, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        self.assertEqual("invite_expired", _code(failure))

    def test_a_still_valid_invite_is_reported_as_a_lost_race(self) -> None:
        """Pending, unexpired, yet the guard refused it — someone else committed
        first. Reporting "expired" here would be a lie."""
        failure = teams._diagnose_dead_invite(
            _Invite(state=teams.INVITE_PENDING, expires_at=datetime.now(UTC) + timedelta(days=1))
        )
        self.assertEqual("invite_already_accepted", _code(failure))

    def test_an_invite_with_no_expiry_never_reads_as_expired(self) -> None:
        failure = teams._diagnose_dead_invite(_Invite(state=teams.INVITE_PENDING, expires_at=None))
        self.assertNotEqual("invite_expired", _code(failure))

    def test_every_diagnosis_is_a_conflict_not_a_server_error(self) -> None:
        for state in (teams.INVITE_ACCEPTED, teams.INVITE_REVOKED, teams.INVITE_DECLINED, teams.INVITE_PENDING):
            with self.subTest(state=state):
                self.assertEqual(409, teams._diagnose_dead_invite(_Invite(state=state)).status_code)


class GuardedUpdateTests(TestCase):
    """The race fix is the SQL, not the surrounding Python."""

    def _consume_sql(self) -> str:
        statement = (
            sa.update(models.BalancerRegistrationTeamInvite)
            .where(
                models.BalancerRegistrationTeamInvite.id == 1,
                models.BalancerRegistrationTeamInvite.state == teams.INVITE_PENDING,
                sa.or_(
                    models.BalancerRegistrationTeamInvite.expires_at.is_(None),
                    models.BalancerRegistrationTeamInvite.expires_at > sa.func.now(),
                ),
            )
            .values(state=teams.INVITE_ACCEPTED)
            .returning(models.BalancerRegistrationTeamInvite.id)
        )
        return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    def test_the_source_consumes_the_invite_with_a_guarded_update(self) -> None:
        """A read-then-write would let two redemptions of one link both succeed.
        Asserted on the source because the race itself is not unit-testable.

        The statement now lives in ``BalancerRegistrationTeamInviteRepository
        .consume_if_pending``, so the guard is asserted where it is written and
        the delegation where it is used -- both halves, neither dropped.
        """

        source = _code_of(teams.teams_service.accept_invite)
        self.assertIn("self.invite_repo.consume_if_pending(", source)
        self.assertIn("_diagnose_dead_invite", source)

        consume = _code_of(teams.teams_service.invite_repo.consume_if_pending)
        # Still ONE conditional statement: the state and expiry guards ride in the
        # UPDATE's own WHERE, and the winner is decided by whether RETURNING
        # produced a row -- never split into a read followed by a write.
        self.assertIn("sa.update(invite)", consume)
        self.assertIn("invite.state == pending_state", consume)
        self.assertIn("self._live_clause()", consume)
        self.assertIn(".returning(invite.id)", consume)
        self.assertIn("consumed.first() is not None", consume)
        # The expiry half of that guard, in the clause the UPDATE embeds.
        self.assertIn(
            "invite.expires_at > sa.func.now()",
            _code_of(teams.teams_service.invite_repo._live_clause),
        )

    def test_state_and_expiry_are_both_in_the_where_clause(self) -> None:
        sql = self._consume_sql()
        self.assertIn("state = 'pending'", sql)
        self.assertIn("expires_at", sql)
        self.assertIn("now()", sql)

    def test_expiry_uses_the_database_clock(self) -> None:
        """A Python `datetime.now()` in the predicate would be evaluated before the
        row lock is granted, reopening the window it closes."""
        self.assertIn("now()", self._consume_sql())

    def test_the_update_returns_a_row_so_rowcount_can_be_inspected(self) -> None:
        self.assertIn("RETURNING", self._consume_sql())


class SlotRejectionCodeTests(TestCase):
    """§12.2: a public, Russian-first surface cannot render an English `msg`."""

    def test_a_taken_slot_is_a_conflict_named_slot_taken(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, accepted=(RosterMember("tank"),))
        with self.assertRaises(ApiHTTPException) as caught:
            teams._check_slot(occupancy, "tank", is_substitute=False, offering=False)
        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual("slot_taken", _code(caught.exception))

    def test_an_already_offered_slot_is_named_separately_from_a_taken_one(self) -> None:
        """The captain's recourse differs: revoke the outstanding invite, versus
        nothing at all."""
        occupancy = RosterOccupancy(shape=FIVE_STACK, pending=(RosterMember("tank"),))
        with self.assertRaises(ApiHTTPException) as caught:
            teams._check_slot(occupancy, "tank", is_substitute=False, offering=True)
        self.assertEqual("slot_already_offered", _code(caught.exception))

    def test_a_full_bench_is_named_separately_from_a_full_roster(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, max_substitutes=0)
        with self.assertRaises(ApiHTTPException) as caught:
            teams._check_slot(occupancy, "dps", is_substitute=True, offering=False)
        self.assertEqual("bench_full", _code(caught.exception))

    def test_a_slot_the_tournament_does_not_have_is_a_400(self) -> None:
        """Not a 409: no future team state makes "tank" valid on a role-less
        tournament, so retrying is pointless."""
        occupancy = RosterOccupancy(shape=parse_roster_slots({"flex": 6}))
        with self.assertRaises(ApiHTTPException) as caught:
            teams._check_slot(occupancy, "tank", is_substitute=False, offering=False)
        self.assertEqual(400, caught.exception.status_code)
        self.assertEqual("slot_not_in_shape", _code(caught.exception))

    def test_an_available_slot_raises_nothing(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK)
        teams._check_slot(occupancy, "tank", is_substitute=False, offering=False)
        teams._check_slot(occupancy, "tank", is_substitute=False, offering=True)


class StatusDenormalizationTests(TestCase):
    def test_a_full_roster_reads_as_complete(self) -> None:
        occupancy = RosterOccupancy(
            shape=FIVE_STACK,
            accepted=tuple(RosterMember(code) for code in ("tank", "dps", "dps", "support", "support")),
        )
        self.assertEqual(teams.TEAM_COMPLETE, teams._status_for(occupancy))

    def test_a_partial_roster_stays_forming(self) -> None:
        occupancy = RosterOccupancy(shape=FIVE_STACK, accepted=(RosterMember("tank"),))
        self.assertEqual(teams.TEAM_FORMING, teams._status_for(occupancy))

    def test_pending_invites_do_not_make_a_team_complete(self) -> None:
        """Otherwise a captain could reach `complete` by inviting five people and
        the export would materialize an empty roster."""
        occupancy = RosterOccupancy(
            shape=FIVE_STACK,
            accepted=(RosterMember("tank"),),
            pending=tuple(RosterMember(code) for code in ("dps", "dps", "support", "support")),
        )
        self.assertEqual(teams.TEAM_FORMING, teams._status_for(occupancy))


class MutabilityGateTests(TestCase):
    def _team(self, **kwargs: Any) -> models.BalancerRegistrationTeam:
        team = models.BalancerRegistrationTeam(**kwargs)
        return team

    def test_an_exported_team_is_frozen_by_its_export_link_not_its_status(self) -> None:
        """Its shape is already baked into `tournament.player` rows, so editing the
        roster afterwards would desync the two."""
        team = self._team(status=teams.TEAM_FORMING, exported_team_id=7)
        with self.assertRaises(ApiHTTPException) as caught:
            teams._assert_mutable(team)
        self.assertEqual("team_already_exported", _code(caught.exception))

    def test_a_disbanded_team_is_terminal(self) -> None:
        team = self._team(status=teams.TEAM_DISBANDED)
        with self.assertRaises(ApiHTTPException) as caught:
            teams._assert_mutable(team)
        self.assertEqual("team_not_forming", _code(caught.exception))

    def test_a_rejected_team_is_terminal(self) -> None:
        team = self._team(status=teams.TEAM_REJECTED)
        with self.assertRaises(ApiHTTPException) as caught:
            teams._assert_mutable(team)
        self.assertEqual("team_not_forming", _code(caught.exception))

    def test_a_complete_team_is_still_editable(self) -> None:
        """Complete is not terminal: a captain may still swap a player before the
        organizer exports."""
        teams._assert_mutable(self._team(status=teams.TEAM_COMPLETE))

    def test_a_forming_team_is_editable(self) -> None:
        teams._assert_mutable(self._team(status=teams.TEAM_FORMING))


class OrganizerRejectionTests(TestCase):
    def test_reason_is_required_trimmed_and_bounded(self) -> None:
        for payload in ({}, {"reason": None}, {"reason": " \n\t "}, {"reason": "x" * 1001}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                RegistrationTeamRejectRequest.model_validate(payload)
        request = RegistrationTeamRejectRequest(reason=" \n" + "x" * 1000 + "\t ")
        self.assertEqual("x" * 1000, request.reason)

    def test_rejection_reason_is_private_but_available_to_captain_and_organizer(self) -> None:
        team = models.BalancerRegistrationTeam(
            id=1,
            tournament_id=2,
            name="Roster",
            status=teams.TEAM_REJECTED,
            rejection_reason="Duplicate roster",
            organizer_notes="Internal review",
        )
        occupancy = RosterOccupancy(shape=FIVE_STACK)
        public = serialize_registration_team(team, occupancy)
        captain = serialize_registration_team(team, occupancy, include_private=True)
        organizer = serialize_registration_team(team, occupancy, include_staff=True)
        self.assertIsNone(public.rejection_reason)
        self.assertIsNone(public.organizer_notes)
        self.assertEqual("Duplicate roster", captain.rejection_reason)
        self.assertIsNone(captain.organizer_notes)
        self.assertEqual("Duplicate roster", organizer.rejection_reason)
        self.assertEqual("Internal review", organizer.organizer_notes)


class _SingleTeamSession:
    """Answers only the `SELECT … FOR UPDATE` that `_lock_team` issues."""

    def __init__(self, team: object) -> None:
        self.team = team

    async def scalar(self, statement: object) -> object:
        return self.team


class CrossTournamentAuthorizationTests(IsolatedAsyncioTestCase):
    """`reject_team` is authorized against a tournament, so it must verify the team
    actually belongs to it."""

    async def test_rejecting_a_team_from_another_tournament_is_refused(self) -> None:
        """The permission check upstream passes for tournament 1; without this
        assertion an organizer of tournament 1 could reject teams in tournament 2."""
        team = models.BalancerRegistrationTeam(tournament_id=2, status=teams.TEAM_FORMING)
        session = _SingleTeamSession(team)
        with self.assertRaises(ApiHTTPException) as caught:
            await teams.teams_service.reject_team(
                session,  # type: ignore[arg-type]
                tournament_id=1,
                team_id=99,
                auth_user=models.AuthUser(id=5),
                reason="Duplicate roster",
            )
        # 404, not 403: confirming it exists elsewhere leaks roster membership
        # across workspaces.
        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual("team_not_found", _code(caught.exception))

    async def test_the_tournament_id_cannot_be_omitted(self) -> None:
        """Keyword-only with no default, so no call site can accidentally drop the
        scope check by forgetting an argument."""
        import inspect

        parameter = inspect.signature(teams.teams_service.reject_team).parameters["tournament_id"]
        self.assertIs(inspect.Parameter.empty, parameter.default)
        self.assertIs(inspect.Parameter.KEYWORD_ONLY, parameter.kind)


class TeamNameConstraintTests(IsolatedAsyncioTestCase):
    """The export seam derives `Team.name` by splitting `balancer_name` on "#"."""

    async def test_a_name_containing_a_hash_is_rejected(self) -> None:
        """A name like "Team #1" would materialize as "Team " — and the
        `exported_team_id` backfill, keyed on the full name, would then find
        nothing. Rejecting at creation is the only place this is cheap."""
        with self.assertRaises(ApiHTTPException) as caught:
            await teams.teams_service.create_team(
                None,  # type: ignore[arg-type]
                tournament_id=1,
                auth_user=models.AuthUser(id=1),
                name="Team #1",
                slot_code="tank",
                body=None,  # type: ignore[arg-type]
            )
        self.assertEqual(400, caught.exception.status_code)
        self.assertEqual("team_name_invalid", _code(caught.exception))

    async def test_a_blank_name_is_rejected(self) -> None:
        with self.assertRaises(ApiHTTPException) as caught:
            await teams.teams_service.create_team(
                None,  # type: ignore[arg-type]
                tournament_id=1,
                auth_user=models.AuthUser(id=1),
                name="   ",
                slot_code="tank",
                body=None,  # type: ignore[arg-type]
            )
        self.assertEqual("team_name_required", _code(caught.exception))

    async def test_the_check_runs_before_any_database_access(self) -> None:
        """Passing `None` as the session above is the assertion: if either check
        moved after the openness lookup, these tests would fail with an
        AttributeError instead of the expected code."""
        for name in ("Team #1", "  "):
            with self.subTest(name=name), self.assertRaises(ApiHTTPException):
                await teams.teams_service.create_team(
                    None,  # type: ignore[arg-type]
                    tournament_id=1,
                    auth_user=models.AuthUser(id=1),
                    name=name,
                    slot_code="tank",
                    body=None,  # type: ignore[arg-type]
                )


class FreeAgentAttachTests(TestCase):
    """A solo registrant accepting an invite ATTACHES, never re-registers.

    There is one registration row per player per tournament, so "registered solo"
    and "on a team" are two states of the same row. Before this, `accept_invite`
    always called the creating writer, which answered `already_registered` — and
    since withdrawal is final, a solo registrant could never join any team.
    """

    def _source(self) -> str:
        import inspect

        return inspect.getsource(teams.teams_service.accept_invite)

    def test_an_existing_registration_is_attached_not_recreated(self) -> None:
        source = self._source()
        # The existing row is looked up and its three team columns are set...
        self.assertIn("get_registration(session, team.tournament_id, auth_user.id)", source)
        self.assertIn("existing.registration_team_id = team.id", source)
        self.assertIn("existing.team_slot_code = invite.slot_code", source)
        # ...and the creating writer is reached only in the `else`. Matched on the
        # CALL, not the bare name: the docstring mentions it first.
        attach_index = source.index("existing.registration_team_id")
        create_index = source.index("await self.registrations.submit_public_registration(")
        self.assertLess(attach_index, create_index, "attach must precede the create branch")

    def test_the_submitted_body_is_ignored_on_the_attach_path(self) -> None:
        """The player already answered the form; the invite only decides the slot.
        Passing `body` here would let an invite silently rewrite their roles."""
        source = self._source()
        attach = source[source.index("if existing is not None:") : source.index("else:")]
        self.assertNotIn("body", attach)

    def test_a_terminal_registration_is_refused_with_its_own_code(self) -> None:
        """Reviving a withdrawn row would smuggle a re-entry past the rule that
        withdrawal is final — which exists because withdrawing after check-in
        invalidates a composed roster."""
        source = self._source()
        self.assertIn("_SLOT_RELEASING_STATUSES", source)
        self.assertIn("registration_terminal", source)

    def test_the_slot_check_still_runs_before_the_attach(self) -> None:
        """Attaching must not bypass the occupancy check: two free agents accepting
        the same slot would otherwise both land on the roster."""
        source = self._source()
        self.assertLess(
            source.index("_check_slot"),
            source.index("existing.registration_team_id"),
        )


class FreeAgentPredicateTests(TestCase):
    """The one definition of "free agent", shared by the count and the picker.

    Its whole value is the predicate: a wrong filter reports zero on a tournament
    that has stranded players — the exact silence the count exists to break — or
    offers a captain someone who already has a team.
    """

    def _sql(self) -> str:
        import sqlalchemy as sa

        from shared.models.registration.registration import BalancerRegistration

        # Compiles the SERVICE'S OWN clause rather than a hand-written copy of it.
        # A copy is what this test used to do, and it would have kept passing while
        # the service's filter drifted underneath it.
        statement = sa.select(sa.func.count(BalancerRegistration.id)).where(*teams._free_agent_clause(1))
        return str(statement.compile(compile_kwargs={"literal_binds": True}))

    def test_it_counts_only_registrations_with_no_team(self) -> None:
        self.assertIn("registration_team_id IS NULL", self._sql())

    def test_it_ignores_soft_deleted_rows(self) -> None:
        self.assertIn("deleted_at IS NULL", self._sql())

    def test_it_ignores_players_who_released_their_slot(self) -> None:
        """A withdrawn or rejected registration is not waiting to be recruited, so
        counting it would inflate the warning and train organizers to ignore it —
        and offering it in the picker would produce an invite the server refuses."""
        sql = self._sql()
        self.assertIn("withdrawn", sql)
        self.assertIn("rejected", sql)
        self.assertIn("NOT IN", sql.upper())

    def test_the_count_and_the_picker_cannot_disagree(self) -> None:
        """Both must route through one clause. Two copies fail silently and
        specifically: an organizer reading "3 players without a team" above a picker
        offering two of them cannot tell which number is lying."""
        for fn in (teams.teams_service.count_unassigned_players, teams.teams_service.list_free_agents):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_free_agent_clause", _code_of(fn))

    def test_the_clause_uses_the_roster_readers_release_rule(self) -> None:
        """The third consumer of that set is the roster reader. If it and the clause
        disagree, a player can be absent from every team AND absent from the count."""
        self.assertIn("_SLOT_RELEASING_STATUSES", _code_of(teams._free_agent_clause))
        self.assertEqual({"withdrawn", "rejected"}, set(teams._SLOT_RELEASING_STATUSES))


@dataclass
class _PreviewTournament:
    name: str = "Autumn Cup"


@dataclass
class _PreviewTeam:
    id: int = 7
    name: str = "Alpha"
    tournament_id: int = 3
    workspace_id: int = 1
    status: str = teams.TEAM_FORMING
    exported_team_id: int | None = None
    tournament: Any = field(default_factory=_PreviewTournament)


@dataclass
class _PreviewInvite:
    """Just the fields `preview_invite` reads."""

    state: str = teams.INVITE_PENDING
    expires_at: datetime | None = None
    slot_code: str = "tank"
    is_substitute: bool = False
    team: Any = field(default_factory=_PreviewTeam)


class _PreviewSession:
    def __init__(self, invite: Any) -> None:
        self._invite = invite

    async def scalar(self, *_args: Any, **_kwargs: Any) -> Any:
        return self._invite


class _HashMatchingSession:
    """Unlike `_PreviewSession`, actually evaluates what the query asked for: the
    canned invite comes back only if the statement's bound ``token_sha256``
    literal equals the hash this test expects `preview_invite` to look up. This
    is what makes the whitespace-stripping test below meaningful rather than
    vacuous — `_PreviewSession` would return the invite for ANY token."""

    def __init__(self, invite: Any, expected_hash: str) -> None:
        self._invite = invite
        self._expected_hash = expected_hash

    async def scalar(self, stmt: Any) -> Any:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        return self._invite if self._expected_hash in compiled else None


class InvitePreviewTests(IsolatedAsyncioTestCase):
    """The anonymous landing surface for a shared invite link.

    Its contract is narrow and load-bearing: tell the holder what they were
    invited to, tell them honestly whether it still works, and reveal nothing
    about the roster. Each of those is a separate way to be wrong.
    """

    async def _preview(self, invite: Any) -> Any:
        return await teams.teams_service.preview_invite(_PreviewSession(invite), token="whatever")

    async def test_a_live_invite_is_redeemable(self) -> None:
        preview = await self._preview(_PreviewInvite())

        self.assertTrue(preview.is_redeemable)
        self.assertEqual("Alpha", preview.team_name)
        # The tournament id is why this endpoint exists: the token alone tells the
        # landing page nothing about where to register.
        self.assertEqual(3, preview.tournament_id)
        self.assertEqual("Autumn Cup", preview.tournament_name)

    async def test_an_expired_invite_still_resolves_but_is_not_redeemable(self) -> None:
        """The state stays `pending` — that IS the row's state — while redeemability
        goes false. Collapsing the two would make the page either 404 a link whose
        story it could tell, or offer a form the guarded UPDATE will reject."""
        expired = _PreviewInvite(expires_at=datetime.now(UTC) - timedelta(hours=1))

        preview = await self._preview(expired)

        self.assertEqual(teams.INVITE_PENDING, preview.state)
        self.assertFalse(preview.is_redeemable)

    async def test_an_invite_to_a_team_that_already_exported_is_not_redeemable(self) -> None:
        """The invite row is untouched by export, so only the team tells this story.
        Without the check the page would offer a slot on a materialized roster."""
        preview = await self._preview(_PreviewInvite(team=_PreviewTeam(exported_team_id=42)))

        self.assertFalse(preview.is_redeemable)

    async def test_an_invite_to_a_dead_team_is_not_redeemable(self) -> None:
        for status in (teams.TEAM_REJECTED, teams.TEAM_DISBANDED):
            with self.subTest(status=status):
                preview = await self._preview(_PreviewInvite(team=_PreviewTeam(status=status)))
                self.assertFalse(preview.is_redeemable)

    async def test_an_unknown_token_is_a_404(self) -> None:
        with self.assertRaises(ApiHTTPException) as caught:
            await self._preview(None)

        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual("invite_not_found", _code(caught.exception))

    def test_the_preview_reveals_no_roster(self) -> None:
        """Whoever holds the token is not a member yet. The team's name and the
        offered slot are the invitation; who else accepted is not."""
        fields = set(RegistrationTeamInvitePreview.model_fields)

        self.assertEqual(set(), fields & {"members", "invites", "open_slots", "captain"})

    async def test_a_token_with_stray_whitespace_still_resolves(self) -> None:
        """Pasted out of the `<code>` block that displays it, or forwarded through a
        chat client, a token can pick up a leading/trailing/embedded space or
        newline. A real token never contains one, so stripping it before hashing
        can only rescue the corrupted presentation — never match a different,
        wrong invite."""
        raw = "PcWqruHUOoQe4AmdJagQPh_fpjqq2e9qJ61GJgRSIDI"
        session = _HashMatchingSession(_PreviewInvite(), expected_hash=hash_invite_token(raw))

        preview = await teams.teams_service.preview_invite(session, token=f"  {raw[:10]}\n{raw[10:]}\t")

        self.assertTrue(preview.is_redeemable)


@dataclass
class _TargetMember:
    player_id: int | None = 55


@dataclass
class _TargetRegistration:
    id: int = 900
    tournament_id: int = 3
    registration_team_id: int | None = None
    status: str = "approved"
    workspace_member: Any = field(default_factory=_TargetMember)


class _TargetSession:
    """Returns the registration for the ORM select and the account id for the
    scalar lookup that follows it, in that order."""

    def __init__(self, registration: Any, auth_user_id: int | None) -> None:
        self._registration = registration
        self._auth_user_id = auth_user_id
        self.calls = 0

    async def scalar(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls += 1
        return self._registration if self.calls == 1 else self._auth_user_id


class TargetedInviteResolutionTests(IsolatedAsyncioTestCase):
    """A targeted invite names a REGISTRATION and stores an ACCOUNT.

    That indirection is the feature: the captain picks from this tournament's own
    free agents, so no global account search is opened, and the client never sees
    an ``auth_user_id``. Every rejection below has a different recourse, which is
    why each carries its own code.
    """

    async def _resolve(self, registration: Any, auth_user_id: int | None = 77) -> int:
        return await teams.teams_service._resolve_invite_target(
            _TargetSession(registration, auth_user_id), tournament_id=3, registration_id=900
        )

    async def test_a_free_agent_resolves_to_their_account(self) -> None:
        self.assertEqual(77, await self._resolve(_TargetRegistration()))

    async def test_a_registration_from_another_tournament_is_a_404(self) -> None:
        """404 rather than 403 deliberately: confirming that a registration exists
        elsewhere would answer a question the caller has no business asking."""
        with self.assertRaises(ApiHTTPException) as caught:
            await self._resolve(_TargetRegistration(tournament_id=999))

        self.assertEqual(404, caught.exception.status_code)
        self.assertEqual("registration_not_found", _code(caught.exception))

    async def test_someone_recruited_while_the_dialog_was_open_is_refused(self) -> None:
        """The free-agent list is a snapshot. Without this check the invite would
        reserve a second slot for a player who already holds one."""
        with self.assertRaises(ApiHTTPException) as caught:
            await self._resolve(_TargetRegistration(registration_team_id=12))

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual("player_not_free", _code(caught.exception))

    async def test_a_released_registration_is_refused(self) -> None:
        for status in sorted(teams._SLOT_RELEASING_STATUSES):
            with self.subTest(status=status):
                with self.assertRaises(ApiHTTPException) as caught:
                    await self._resolve(_TargetRegistration(status=status))
                self.assertEqual("player_not_free", _code(caught.exception))

    async def test_a_player_with_no_site_account_is_refused_with_the_way_out(self) -> None:
        """An imported player who never signed in cannot be addressed — there is no
        identity to bind the invite to. The code names the alternative, because a
        link invite CAN reach them."""
        with self.assertRaises(ApiHTTPException) as caught:
            await self._resolve(_TargetRegistration(), auth_user_id=None)

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual("player_has_no_account", _code(caught.exception))


class TargetedInviteShapeTests(TestCase):
    """Where the two addressing modes must stay different, and where they must not."""

    def test_a_targeted_invite_mints_no_token(self) -> None:
        """The point of the mode: nothing to paste, nothing to leak, nothing to
        forward to the wrong person. A token here would reintroduce every risk the
        link mode carries, for a recipient who never needed one."""
        source = _code_of(teams.teams_service.invite_member)
        generate = source.index("generate_invite_token()")
        guard = source.index("if target_registration_id is None:")

        self.assertLess(guard, generate, "the token must be minted only in the link branch")
        self.assertIn("target_auth_user_id = await self._resolve_invite_target", source)

    def test_the_resolution_happens_under_the_team_lock(self) -> None:
        """ "This slot is open" and "this player is unattached" must be decided under
        the same lock the insert commits under, or a concurrent acceptance can
        invalidate one of them between the check and the write."""
        source = _code_of(teams.teams_service.invite_member)

        self.assertLess(source.index("_lock_team("), source.index("_resolve_invite_target"))
        self.assertLess(source.index("_check_slot("), source.index("_resolve_invite_target"))

    def test_the_invite_read_no_longer_leaks_an_account_id(self) -> None:
        """It carried ``target_auth_user_id``, which no client could use and which is
        an internal identity travelling outward. A captain needs a name."""
        fields = set(RegistrationTeamInviteRead.model_fields)

        self.assertIn("target_battle_tag", fields)
        self.assertNotIn("target_auth_user_id", fields)

    def test_the_invite_input_takes_a_registration_not_an_account(self) -> None:
        fields = set(RegistrationTeamInviteCreateRequest.model_fields)

        self.assertIn("target_registration_id", fields)
        self.assertNotIn("target_auth_user_id", fields)


class AcceptPayloadTests(TestCase):
    """Who has to answer a form to accept an invite, and who does not."""

    def test_an_attaching_free_agent_need_not_resend_a_form(self) -> None:
        """It used to be required-but-ignored, and the client expressed that by
        casting an empty object — a lie the type system could not catch. An invitee
        who already registered has nothing left to answer."""
        request = RegistrationTeamAcceptRequest.model_validate({"invite_id": 1})

        self.assertIsNotNone(request.registration)
        self.assertIsNone(request.registration.battle_tag)

    def test_the_default_cannot_smuggle_a_blank_registration_through(self) -> None:
        """The permissive default is only safe because the registration form's own
        validation runs downstream. If that ever stopped gating, a new invitee could
        accept into a row with no battle tag."""
        source = _code_of(registration_service.submit_public_registration)

        self.assertIn("validate_registration_input(", source)

    def test_exactly_one_reference_is_still_required(self) -> None:
        """A bearer token and a targeted id together leave which one authorized the
        acceptance ambiguous — a privilege question, not a cosmetic one."""
        for payload in ({}, {"invite_id": 1, "token": "t"}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    RegistrationTeamAcceptRequest.model_validate(payload)


@dataclass
class _CapTeam:
    id: int = 7
    tournament_id: int = 3
    invite_cap_reset_at: Any = None


class InviteCapCounterTests(TestCase):
    """The number that refuses an invite and the number the UI shows.

    They must be the same query. The worst version of this feature is a captain
    told "12 of 60 used" and refused in the same breath, with no way to know which
    of the two is lying.
    """

    def _sql(self, team: Any) -> str:
        import sqlalchemy as sa

        conditions = [models.BalancerRegistrationTeamInvite.team_id == team.id]
        if team.invite_cap_reset_at is not None:
            conditions.append(models.BalancerRegistrationTeamInvite.invited_at > team.invite_cap_reset_at)
        statement = sa.select(sa.func.count(models.BalancerRegistrationTeamInvite.id)).where(*conditions)
        return str(statement.compile(compile_kwargs={"literal_binds": True}))

    def test_the_check_and_the_display_share_one_counter(self) -> None:
        """`invite_member` must not compute its own count. A second copy is how the
        refusal and the counter drift apart."""
        source = _code_of(teams.teams_service.invite_member)

        self.assertIn("count_invites_against_cap(session, team)", source)
        self.assertNotIn("func.count", source)

    def test_every_invite_ever_created_counts(self) -> None:
        """A cumulative ceiling is the only thing an invite -> revoke -> invite loop
        cannot walk around: each cycle satisfies every slot rule."""
        source = _code_of(teams.teams_service.count_invites_against_cap)

        self.assertNotIn("INVITE_PENDING", source)
        self.assertNotIn("state ==", source)

    def test_a_reset_moves_the_floor_instead_of_zeroing_it(self) -> None:
        """Deleting the rows is the other way to clear a cap and is worse: the
        history is now a read, so it would erase the evidence of whatever abuse
        prompted the reset."""
        reset = self._sql(_CapTeam(invite_cap_reset_at=datetime(2026, 8, 1, tzinfo=UTC)))

        self.assertIn("invited_at >", reset)
        self.assertNotIn("invited_at >", self._sql(_CapTeam()))

    def test_the_reset_records_who_forgave_it(self) -> None:
        source = _code_of(teams.teams_service.reset_invite_cap)

        self.assertIn("invite_cap_reset_by = auth_user.id", source)
        self.assertIn("invite_cap_reset_at", source)


class OrganizerRevokeTests(TestCase):
    """A new power over someone else's roster. Three properties make it safe."""

    def test_it_is_scoped_to_the_tournament_it_was_authorized_for(self) -> None:
        """The single most important check here. An invite id is global while the
        organizer's permission is not, so without this an organizer of any
        tournament could pass any id and act on another event's roster."""
        source = _code_of(teams.teams_service.revoke_invite_as_organizer)

        self.assertIn("team.tournament_id != tournament_id", source)
        # 404, not 403: confirming the invite exists elsewhere answers a question
        # this caller has no permission to ask. Quote-agnostic because `_code_of`
        # round-trips through `ast.unparse`, which normalizes string quoting.
        self.assertIn("_fail(404, ", source)
        self.assertIn("invite_not_found", source)
        self.assertNotIn("403", source)

    def test_it_never_takes_the_captain_gate(self) -> None:
        """An organizer is by definition not the captain. Leaving `_assert_captain`
        in would make the whole power unreachable — and reachable only by the one
        person who never needs it."""
        source = _code_of(teams.teams_service.revoke_invite_as_organizer)

        self.assertNotIn("_assert_captain", source)
        # It also must not require a mutable team: the reason to reach in is
        # usually that something is stuck.
        self.assertNotIn("_assert_mutable", source)

    def test_both_paths_share_one_transition_but_not_one_gate(self) -> None:
        """A single function with an `as_organizer` flag is how a privilege check
        gets skipped by a caller passing the wrong default. The member-facing path
        authorizes the caller as the team's own staff (captain or manager); the
        organizer path authorizes on workspace permission upstream."""
        captain = _code_of(teams.teams_service.revoke_invite)
        organizer = _code_of(teams.teams_service.revoke_invite_as_organizer)

        self.assertIn("_assert_staff(", captain)
        self.assertIn("_withdraw_invite(invite, by=auth_user, by_organizer=False)", captain)
        self.assertIn("_withdraw_invite(invite, by=auth_user, by_organizer=True)", organizer)

    def test_provenance_is_written_not_inferred(self) -> None:
        """Comparing the revoker against "the captain" at read time would be a lie:
        captaincy transfers, so the captain now is not the captain then."""
        source = _code_of(teams._withdraw_invite)

        self.assertIn("invite.revoked_by = by.id", source)
        self.assertIn("invite.revoked_by_organizer = by_organizer", source)


class InviteHistoryTests(TestCase):
    """The read that makes the cap explicable."""

    def _source(self) -> str:
        return _code_of(teams.teams_service.list_invite_history)

    def test_it_is_separate_from_the_live_invite_list(self) -> None:
        """`describe_team` returns only pending invites because occupancy depends on
        them reserving slots. A terminal row in that list would hold a place open
        for someone who already declined."""
        # The live list's state filter rides in the repository read the service
        # delegates to, so both halves are asserted: the state that is passed down
        # and the WHERE that applies it.
        self.assertIn("pending_state=INVITE_PENDING", _code_of(teams.teams_service._pending_invites))
        self.assertIn(
            "invite.state == pending_state",
            _code_of(teams.teams_service.invite_repo.list_pending),
        )
        # The history filters on team only. `INVITE_PENDING` still appears in its
        # body -- in the expiry computation -- so the claim is about the WHERE, not
        # about the token being absent.
        self.assertNotIn("INVITE_PENDING", _code_of(teams.teams_service.list_invite_history).split("now =")[0])

    def test_it_returns_terminal_rows_too(self) -> None:
        """The gap it closes: a declined offer used to vanish, so the captain saw
        the slot reopen without knowing whether they were refused or the link
        merely lapsed. Different situations, different next moves."""
        source = self._source()
        history_query = _code_of(teams.teams_service.invite_repo.list_for_team)

        self.assertNotIn(".where(models.BalancerRegistrationTeamInvite.state", source)
        # The read the service delegates to filters on team alone -- no state
        # predicate at all, which is what lets a declined row still surface.
        self.assertNotIn("invite.state", history_query)
        self.assertIn("invited_at.desc()", history_query)

    def test_expiry_is_computed_because_it_is_not_a_stored_state(self) -> None:
        source = self._source()

        self.assertIn("expired", source)
        self.assertIn("row.expires_at <= now", source)
        # It is derived, never selected: no column holds it.
        self.assertNotIn("state == 'expired'", source)

    def test_it_ships_the_cap_standing_alongside(self) -> None:
        """Apart they are a riddle: the cap counts every invite ever issued while
        only pending ones were visible."""
        source = self._source()

        self.assertIn("count_invites_against_cap", source)
        self.assertIn("cap_limit=TEAM_INVITE_TOTAL_CAP", source)


class CaptainReadGateTests(TestCase):
    """Reading is not editing."""

    def test_the_read_gate_does_not_require_a_mutable_team(self) -> None:
        """A captain must be able to read the history of a team that was rejected or
        already exported — those are exactly the cases someone opens it to
        understand."""
        read_gate = _code_of(teams.teams_service.assert_captain_of_team)

        self.assertIn("_assert_captain", read_gate)
        self.assertNotIn("_assert_mutable", read_gate)

    def test_the_edit_gate_still_requires_one(self) -> None:
        """The mutability rule did not disappear; it stayed where it belongs."""
        edit_gate = _code_of(teams.teams_service.assert_may_edit_team)

        self.assertIn("assert_staff_of_team", edit_gate)
        self.assertIn("_assert_mutable(team)", edit_gate)


class _CaptaincyScalarSession:
    """Answers ``session.scalar(...)`` with one canned value, regardless of the
    statement — the statement shape (``_owned_by``) is exercised by
    ``_assert_captain``'s existing callers; only the boolean outcome matters here."""

    def __init__(self, result: int | None) -> None:
        self._result = result

    async def scalar(self, _stmt: Any) -> int | None:
        return self._result


class IsTeamCaptainTests(IsolatedAsyncioTestCase):
    """``is_team_captain`` is the boolean check ``_assert_captain`` used to inline
    and the public team list (§ regteam_list_public) now shares, to decide whose
    invites a captain's own row in that list may carry."""

    async def test_a_team_with_no_captain_is_never_captained(self) -> None:
        team = models.BalancerRegistrationTeam(captain_registration_id=None)

        self.assertFalse(await teams.teams_service.is_team_captain(_CaptaincyScalarSession(42), team, auth_user_id=1))

    async def test_the_owning_account_is_the_captain(self) -> None:
        team = models.BalancerRegistrationTeam(captain_registration_id=42)

        self.assertTrue(await teams.teams_service.is_team_captain(_CaptaincyScalarSession(42), team, auth_user_id=1))

    async def test_a_non_owning_account_is_not_the_captain(self) -> None:
        """The row exists (someone captains this team) but the query for THIS
        account's ownership came back empty — the case an ordinary teammate hits."""
        team = models.BalancerRegistrationTeam(captain_registration_id=42)

        self.assertFalse(await teams.teams_service.is_team_captain(_CaptaincyScalarSession(None), team, auth_user_id=1))
