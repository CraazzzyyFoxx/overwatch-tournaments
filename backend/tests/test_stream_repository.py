"""Guards on ``shared.repository.stream`` and ``TournamentLinkRepository`` — the
privacy one above all.

A player's Twitch account is public only when a ``social_account_visibility`` row
with ``workspace_id IS NULL`` exists. That rule is enforced by an INNER JOIN
inside the ``SELECT``, not by a check in a serializer, precisely so a future code
path cannot forget it. These tests assert the JOIN and its predicate are in the
compiled SQL: with the JOIN present a verified account that has no global
visibility row is unreachable by the query and therefore cannot reach a public
response; drop the JOIN, or relax it to a LEFT OUTER, and stream-svc starts
publishing channels players hid from their profile
(``backend/app-service/src/services/user/flows.py`` ``visible_only``).

The second privacy rule is the owner's own veto (``players.user.stream_visible``).
It has to hold in BOTH source queries, which is the interesting part: the verified
path had no off switch at all before it, and a veto honoured by one query and not
the other publishes the channel anyway.

Statements are compiled, not executed: the shape is the contract, and a DB
fixture would test SQLAlchemy rather than this module. The merge/dedup rule that
used to live alongside these queries (verified wins a login collision) is
business logic, not data access — it now lives in, and is tested by,
``stream-service/tests/test_targets_service.py``.
"""

from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase

from sqlalchemy.dialects import postgresql

from shared.core import enums
from shared.repository import StreamTargetRepository, TournamentLinkRepository

_POLLED_STATUSES = (
    enums.TournamentStatus.CHECK_IN,
    enums.TournamentStatus.DRAFT,
    enums.TournamentStatus.LIVE,
    enums.TournamentStatus.PLAYOFFS,
)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _Result:
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)


class _CapturingSession:
    """Fake AsyncSession: records every statement and replays queued row sets."""

    def __init__(self, *row_sets: list[Any]) -> None:
        self.statements: list[Any] = []
        self._row_sets = list(row_sets)

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._row_sets.pop(0) if self._row_sets else [])


def _compiled(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class ActiveTournamentQueryTests(IsolatedAsyncioTestCase):
    async def test_selection_filters_on_status_not_is_finished(self) -> None:
        """``Tournament.is_finished`` is maintained separately and drifts from ``status``."""
        session = _CapturingSession([])
        repo = StreamTargetRepository()

        await repo.list_active_tournaments(session, _POLLED_STATUSES)

        sql = _compiled(session.statements[0])
        self.assertIn("tournament.tournament.status IN", sql)
        self.assertNotIn("is_finished", sql)

    async def test_row_shape_carries_workspace_and_hidden_flag(self) -> None:
        session = _CapturingSession([(7, 3, True)])
        repo = StreamTargetRepository()

        [tournament] = await repo.list_active_tournaments(session, _POLLED_STATUSES)

        self.assertEqual(tournament.tournament_id, 7)
        self.assertEqual(tournament.workspace_id, 3)
        self.assertTrue(tournament.is_hidden)


class OfficialLinkQueryTests(IsolatedAsyncioTestCase):
    async def test_only_active_stream_links_in_organizer_order(self) -> None:
        session = _CapturingSession([])
        repo = TournamentLinkRepository()

        await repo.list_active_by_kind(session, 7, "stream")

        sql = _compiled(session.statements[0])
        self.assertIn("tournament.tournament_link.kind =", sql)
        self.assertIn("tournament.tournament_link.is_active IS true", sql)
        self.assertIn("ORDER BY tournament.tournament_link.sort_order ASC", sql)

    async def test_bulk_variant_filters_on_an_id_set(self) -> None:
        """The poll tick's batching win: one statement covering every active
        tournament instead of one per tournament."""
        session = _CapturingSession([])
        repo = TournamentLinkRepository()

        result = await repo.list_active_by_kind_bulk(session, [7, 8], "stream")

        sql = _compiled(session.statements[0])
        self.assertIn("tournament.tournament_link.tournament_id IN", sql)
        self.assertEqual(len(session.statements), 1)
        # Every requested id gets a (possibly empty) entry, so the caller never
        # has to guard a missing key.
        self.assertEqual(result, {7: [], 8: []})

    async def test_bulk_variant_short_circuits_on_no_ids(self) -> None:
        session = _CapturingSession([])
        repo = TournamentLinkRepository()

        result = await repo.list_active_by_kind_bulk(session, [], "stream")

        self.assertEqual(result, {})
        self.assertEqual(session.statements, [])


class ParticipantVisibilityTests(IsolatedAsyncioTestCase):
    """The privacy control. Do not weaken these without re-reading design §4.5."""

    async def _verified_sql(self) -> str:
        session = _CapturingSession([])
        repo = StreamTargetRepository()
        await repo.list_verified_channels(session, [7])
        return _compiled(session.statements[0])

    async def test_verified_source_joins_global_visibility(self) -> None:
        sql = await self._verified_sql()

        self.assertIn("JOIN players.social_account_visibility", sql)
        self.assertIn("players.social_account_visibility.workspace_id IS NULL", sql)

    async def test_visibility_join_is_inner_so_hidden_accounts_drop_out(self) -> None:
        """A LEFT OUTER JOIN would keep the row and publish the hidden channel."""
        sql = await self._verified_sql()

        self.assertNotIn("LEFT OUTER JOIN players.social_account_visibility", sql)

    async def test_verified_source_requires_a_proven_twitch_account(self) -> None:
        sql = await self._verified_sql()

        self.assertIn("players.social_account.provider =", sql)
        self.assertIn("players.social_account.is_verified IS true", sql)

    async def test_filters_on_a_tournament_id_set(self) -> None:
        """Batched across every active tournament, not one query per tournament."""
        sql = await self._verified_sql()

        self.assertIn("balancer.registration.tournament_id IN", sql)


class ParticipantSelfDeclaredTests(IsolatedAsyncioTestCase):
    async def _self_declared_stmt(self) -> Any:
        session = _CapturingSession([])
        repo = StreamTargetRepository()
        await repo.list_self_declared_channels(session, [7])
        return session.statements[0]

    async def _self_declared_sql(self) -> str:
        return _compiled(await self._self_declared_stmt())

    async def test_requires_the_explicit_stream_pov_opt_in(self) -> None:
        sql = await self._self_declared_sql()

        self.assertIn("balancer.registration.stream_pov IS true", sql)

    async def test_the_channel_comes_from_the_twitch_identity_answer(self) -> None:
        """An inner join on the provider: no identity row, no declared channel."""
        stmt = await self._self_declared_stmt()
        compiled = stmt.compile(dialect=postgresql.dialect())

        self.assertIn("JOIN balancer.registration_identity ON", str(compiled))
        self.assertIn("balancer.registration_identity.provider =", str(compiled))
        self.assertIn("twitch", compiled.params.values())

    async def test_excludes_withdrawn_and_deleted_registrations(self) -> None:
        sql = await self._self_declared_sql()

        self.assertIn("balancer.registration.deleted_at IS NULL", sql)
        self.assertIn("balancer.registration.status =", sql)

    async def test_player_identity_comes_through_workspace_member(self) -> None:
        sql = await self._self_declared_sql()

        self.assertIn("JOIN workspace_member ON", sql)
        self.assertIn("workspace_member.player_id", sql)


class StreamVetoCollectionGateTests(IsolatedAsyncioTestCase):
    """``players.user.stream_visible`` must gate BOTH sources, or it gates neither.

    A veto in only one query is worse than none: the player believes they opted out
    while the other source keeps feeding their channel to the poller.
    ``user`` is a reserved word, so the compiled SQL quotes it: ``players."user"``.
    """

    # The veto predicate as PostgreSQL renders it. One constant, because the point of
    # these tests is that the two statements carry the SAME condition.
    VETO = 'players."user".stream_visible IS true'

    async def test_the_self_declared_source_drops_a_vetoed_player(self) -> None:
        # Even with ``stream_pov`` set and a nick filled in: the veto outranks the
        # per-tournament opt-in, so both predicates have to be in the same WHERE.
        session = _CapturingSession([])
        await StreamTargetRepository().list_self_declared_channels(session, [7])
        self_declared = _compiled(session.statements[0])

        self.assertIn("balancer.registration.stream_pov IS true", self_declared)
        self.assertIn(self.VETO, self_declared)

    async def test_the_self_declared_source_joins_user_to_reach_the_flag(self) -> None:
        """Without the join there is no column to test, and the filter silently
        becomes a cartesian condition on some other ``user`` alias."""
        session = _CapturingSession([])
        await StreamTargetRepository().list_self_declared_channels(session, [7])
        self_declared = _compiled(session.statements[0])

        self.assertIn('JOIN players."user" ON workspace_member.player_id = players."user".id', self_declared)
        self.assertNotIn('LEFT OUTER JOIN players."user"', self_declared)

    async def test_the_verified_source_drops_a_vetoed_player(self) -> None:
        # The gap this closes: a verified + globally visible Twitch account used to be
        # consent enough, with no per-tournament or per-player way to say no.
        session = _CapturingSession([])
        await StreamTargetRepository().list_verified_channels(session, [7])
        verified = _compiled(session.statements[0])

        self.assertIn("players.social_account.is_verified IS true", verified)
        self.assertIn(self.VETO, verified)

    async def test_the_predicate_is_the_same_in_both_sources(self) -> None:
        """The anti-drift guard: one shared helper, not two hand-written copies."""
        self_declared_session = _CapturingSession([])
        await StreamTargetRepository().list_self_declared_channels(self_declared_session, [7])
        verified_session = _CapturingSession([])
        await StreamTargetRepository().list_verified_channels(verified_session, [7])

        self_declared = _compiled(self_declared_session.statements[0])
        verified = _compiled(verified_session.statements[0])
        self.assertEqual(self_declared.count(self.VETO), 1)
        self.assertEqual(verified.count(self.VETO), 1)


class RosterQueryTests(IsolatedAsyncioTestCase):
    async def test_roster_join_walks_through_workspace_member(self) -> None:
        """A caller's user id is a ``players.user.id``; ``tournament.player`` no
        longer carries one, so the only path to a roster row is through
        ``workspace_member``."""
        session = _CapturingSession([])
        repo = StreamTargetRepository()

        await repo.list_roster(session, 7, [11, 12])

        sql = _compiled(session.statements[0])
        self.assertIn("LEFT OUTER JOIN workspace_member", sql)
        self.assertIn("LEFT OUTER JOIN tournament.player", sql)
        self.assertIn("LEFT OUTER JOIN tournament.team", sql)
        self.assertIn("tournament.player.tournament_id", sql)

    async def test_the_roster_existence_flag_is_uncorrelated_and_rides_the_same_select(self) -> None:
        """``rosters_formed`` answers "is this tournament drafted", not "does this
        user have a roster row" — the read gates teamless streamers on it, so a
        correlated form would answer the question the LEFT JOIN already answers
        and gate nobody. One statement either way: a second round-trip on a
        public, cacheable read is what the column exists to avoid."""
        session = _CapturingSession([])

        await StreamTargetRepository().list_roster(session, 7, [11, 12])

        sql = _compiled(session.statements[0])
        self.assertEqual(len(session.statements), 1)
        self.assertIn("rosters_formed", sql)
        self.assertIn("EXISTS", sql)
        # The EXISTS keys on the tournament alone. Naming the user/member inside
        # it would make it per-row.
        exists_clause = sql[sql.index("EXISTS") :]
        exists_clause = exists_clause[: exists_clause.index("AS rosters_formed")]
        self.assertIn("tournament.player.tournament_id", exists_clause)
        self.assertNotIn("workspace_member", exists_clause)

    async def test_short_circuits_on_no_user_ids(self) -> None:
        session = _CapturingSession([])

        result = await StreamTargetRepository().list_roster(session, 7, [])

        self.assertEqual(result, [])
        self.assertEqual(session.statements, [])
