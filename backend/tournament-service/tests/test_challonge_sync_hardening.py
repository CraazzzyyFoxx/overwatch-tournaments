"""The Challonge sync under load and failure.

Against the real Postgres: a tick Challonge changed nothing for writes nothing (no row lock, no log row, no
recompute, no invalidation); one bad match takes back only its own writes and the rest of the import lands; the
sync-log purge takes only rows past the retention; a result push holds no transaction while Challonge answers.
Over the RPC envelope: an import already running is a 409, an unreachable Challonge a 503, an unknown bracket a 404.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx
import sqlalchemy as sa

from shared.core import enums
from shared.models.encounter import Encounter
from shared.models.tournament.challonge import (
    ChallongeMatchMapping,
    ChallongeParticipantMapping,
    ChallongeSource,
    ChallongeSyncLog,
)
from shared.models.tournament.stage import Stage, StageItem
from shared.schemas.challonge import ChallongeMatch
from shared.schemas.events import ChallongePushRequestedEvent
from shared.services.encounter.participants import active_teams, place_team
from shared.services.encounter.result import apply_result, lock_encounter
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.rpc import _helpers as rpc_helpers
from src.rpc import integrations
from src.services.challonge import sync as challonge_sync
from src.services.encounter import challonge_push_events
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity


class _Redis:
    """``SET NX`` plus the lock's release and renew scripts: all ``distributed_lock`` asks of Redis."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script: str, _numkeys: int, key: str, token: str, *renew_ms: str) -> int:
        if self.values.get(key) != token:
            return 0
        if not renew_ms:
            del self.values[key]
        return 1


def _match(match_id: int, player1: int | None, player2: int | None, *, state: str = "complete", scores: str = "2-1"):
    return ChallongeMatch(
        id=match_id,
        started_at=None,
        created_at=datetime.now(UTC),
        updated_at=None,
        player1_id=player1,
        player2_id=player2,
        round=1,
        identifier="A",
        state=state,
        scores_csv=scores,
        tournament_id=5,
        group_id=None,
    )


class ChallongeImportTests(EncounterWriterCase):
    """A playoff stage linked to Challonge tournament 5, participants 1..4 mapped to the four teams."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="Playoffs",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=0,
            )
            s.add(stage)
            await s.flush()
            s.add(StageItem(stage_id=stage.id, name="Playoffs", type=enums.StageItemType.SINGLE_BRACKET, order=0))
            source = ChallongeSource(
                tournament_id=self.ids["t"], stage_id=stage.id, challonge_tournament_id=5, source_type="stage"
            )
            s.add(source)
            await s.flush()
            s.add_all(
                ChallongeParticipantMapping(
                    source_id=source.id, challonge_participant_id=participant, team_id=self.ids[f"team{index}"]
                )
                for index, participant in enumerate((1, 2, 3, 4))
            )
            await s.commit()
            self.source_id = source.id
        self.redis = _Redis()

    async def tick(self, *matches: ChallongeMatch, before_lock=None) -> tuple[dict, AsyncMock, AsyncMock, AsyncMock]:  # noqa: ANN001
        """One auto-sync import of ``matches``: its stats, the recompute and invalidation requests and the row locks.

        ``before_lock(encounter_id)`` runs just before the sync takes an encounter's row lock -- after its unlocked
        reads -- to commit a competing write in that gap."""

        async def lock(session, encounter_id):  # noqa: ANN001, ANN202
            await before_lock(encounter_id)
            return await lock_encounter(session, encounter_id)

        with (
            patch.object(challonge_sync, "_get_redis", AsyncMock(return_value=self.redis)),
            patch.object(challonge_sync.challonge_client, "fetch_matches", AsyncMock(return_value=list(matches))),
            patch.object(challonge_sync.challonge_client, "fetch_participants", AsyncMock(return_value=[])),
            patch.object(challonge_sync, "enqueue_tournament_recalculation", AsyncMock()) as recompute,
            patch.object(challonge_sync, "publish_tournament_invalidation", AsyncMock()) as invalidate,
            patch.object(
                challonge_sync,
                "lock_encounter",
                AsyncMock(side_effect=lock) if before_lock is not None else AsyncMock(wraps=lock_encounter),
            ) as lock_mock,
        ):
            async with self.Session() as s:
                stats = await challonge_sync.sync_service.import_tournament(s, self.ids["t"])
        return stats, recompute, invalidate, lock_mock

    async def log_rows(self) -> int:
        async with self.Session() as s:
            return await s.scalar(
                sa.select(sa.func.count())
                .select_from(ChallongeSyncLog)
                .where(ChallongeSyncLog.tournament_id == self.ids["t"])
            )

    async def test_a_tick_challonge_changed_nothing_for_writes_nothing(self) -> None:
        decided = _match(9001, 1, 2)
        # Player 2 still TBD: one seat, no running score.
        waiting = _match(9002, 3, None, state="pending", scores="")
        stats, recompute, _invalidate, _lock = await self.tick(decided, waiting)
        self.assertEqual((2, 2), (stats["created"], stats["matches_synced"]))
        recompute.assert_awaited_once()
        logged = await self.log_rows()

        savepoints: list[str] = []

        def count_savepoints(conn, cursor, statement, *args) -> None:  # noqa: ANN001, ANN002
            if statement.lstrip().upper().startswith("SAVEPOINT"):
                savepoints.append(statement)

        sa.event.listen(self.engine.sync_engine, "before_cursor_execute", count_savepoints)
        try:
            stats, recompute, invalidate, lock = await self.tick(decided, waiting)
        finally:
            sa.event.remove(self.engine.sync_engine, "before_cursor_execute", count_savepoints)

        self.assertEqual((2, 0, 0, 0), (stats["skipped"], stats["updated"], stats["matches_synced"], stats["errors"]))
        lock.assert_not_awaited()
        recompute.assert_not_awaited()
        invalidate.assert_not_awaited()
        self.assertEqual([], savepoints, "an unchanged match opens no savepoint")
        self.assertEqual(logged, await self.log_rows(), "a no-op tick writes no sync-log row")

        # A real change still syncs: the second match opened.
        stats, recompute, invalidate, lock = await self.tick(decided, _match(9002, 3, None, state="open", scores=""))

        self.assertEqual((1, 1, 1), (stats["skipped"], stats["updated"], stats["matches_synced"]))
        lock.assert_awaited_once()
        recompute.assert_awaited_once()
        invalidate.assert_awaited_once()
        self.assertEqual(logged + 1, await self.log_rows())

    async def test_a_captain_result_committed_after_the_unlocked_read_is_judged_not_overwritten(self) -> None:
        """The sync decides "something changed" without a lock, then locks the encounter to write. A captain's result
        committed in between must be judged on what stands after the lock: here the stale seats (2-0) equal
        Challonge's 2-0, the captains' fresh 2-1 does not -- a conflict, never the remote score over theirs."""
        await self.tick(_match(9201, 1, 2, state="open", scores="2-0"))  # creates the encounter
        await self.tick(_match(9201, 1, 2, state="open", scores="2-0"))  # writes the running 2-0 onto the seats
        async with self.Session() as s:
            encounter_id = await s.scalar(
                sa.select(ChallongeMatchMapping.encounter_id).where(ChallongeMatchMapping.challonge_match_id == 9201)
            )
            encounter = await s.get_one(Encounter, encounter_id)
            self.assertEqual(
                ([2.0, 0.0], enums.EncounterResultStatus.NONE),
                ([seat.score for seat in await active_teams(s, encounter_id)], encounter.result_status),
            )

        async def captains_confirm_2_1(locking_id: int) -> None:
            async with self.Session() as other:
                encounter = await lock_encounter(other, locking_id)
                seats = await active_teams(other, locking_id)
                await apply_result(
                    other,
                    encounter,
                    source=enums.EncounterResultSource.SERIES_CLAIM,
                    totals={seats[0].id: 2.0, seats[1].id: 1.0},
                    placements={seats[0].id: 1, seats[1].id: 2},
                    action=enums.EncounterResultAuditAction.AUTO_CONFIRM,
                    audit_source="series_claim",
                    actor_user_id=None,
                    reason=None,
                )
                await other.commit()

        stats, _recompute, _invalidate, lock = await self.tick(
            _match(9201, 1, 2, state="complete", scores="2-0"), before_lock=captains_confirm_2_1
        )

        lock.assert_awaited_once()
        self.assertEqual((1, 0, 0), (stats["conflicts"], stats["updated"], stats["matches_synced"]))
        async with self.Session() as s:
            seats = await active_teams(s, encounter_id)
            source = await s.scalar(sa.select(Encounter.result_source).where(Encounter.id == encounter_id))
        self.assertEqual([2.0, 1.0], [seat.score for seat in seats])
        self.assertEqual("series_claim", source)

    async def test_one_bad_match_takes_back_only_its_own_writes(self) -> None:
        # Participant 5 is a second Challonge id for team 0: a match of 1 against 5 seats one team twice.
        async with self.Session() as s:
            s.add(
                ChallongeParticipantMapping(
                    source_id=self.source_id, challonge_participant_id=5, team_id=self.ids["team0"]
                )
            )
            await s.commit()

        stats, recompute, _invalidate, _lock = await self.tick(_match(9101, 1, 5), _match(9102, 3, 4))

        self.assertEqual((1, 1, 1), (stats["errors"], stats["created"], stats["matches_synced"]))
        recompute.assert_awaited_once()
        async with self.Session() as s:
            mapped = set(
                await s.scalars(
                    sa.select(ChallongeMatchMapping.challonge_match_id).where(
                        ChallongeMatchMapping.source_id == self.source_id
                    )
                )
            )
            failure = (
                await s.scalars(
                    sa.select(ChallongeSyncLog).where(
                        ChallongeSyncLog.tournament_id == self.ids["t"], ChallongeSyncLog.challonge_id == 9101
                    )
                )
            ).one()
        self.assertEqual({9102}, mapped, "the good match landed, the bad one left nothing behind")
        self.assertEqual("failed", failure.status)
        self.assertTrue(failure.error_message.startswith("IntegrityError: "), failure.error_message)
        self.assertNotIn("Traceback", failure.error_message)


class SyncLogPurgeTests(EncounterWriterCase):
    async def test_only_rows_past_thirty_days_go_in_batches(self) -> None:
        now = datetime.now(UTC)
        async with self.Session() as s:
            rows = [
                ChallongeSyncLog(
                    tournament_id=self.ids["t"],
                    direction="import",
                    entity_type="match",
                    status="success",
                    created_at=now - timedelta(days=age),
                )
                for age in (40, 31, 29)
            ]
            s.add_all(rows)
            await s.commit()
            ids = [row.id for row in rows]
            expired = await s.scalar(
                sa.select(sa.func.count())
                .select_from(ChallongeSyncLog)
                .where(ChallongeSyncLog.created_at < now - timedelta(days=30))
            )

        with patch.object(challonge_sync, "SYNC_LOG_PURGE_BATCH", 1):
            deleted = await challonge_sync.purge_sync_log(self.Session)

        async with self.Session() as s:
            kept = set(await s.scalars(sa.select(ChallongeSyncLog.id).where(ChallongeSyncLog.id.in_(ids))))
        self.assertEqual({ids[2]}, kept)
        self.assertEqual(expired, deleted)


class ChallongePushTransactionTests(EncounterWriterCase):
    async def test_no_transaction_is_open_while_challonge_answers(self) -> None:
        async with self.Session() as s:
            source = ChallongeSource(tournament_id=self.ids["t"], challonge_tournament_id=5)
            s.add(source)
            await s.flush()
            s.add_all(
                [
                    ChallongeMatchMapping(source_id=source.id, challonge_match_id=9001, encounter_id=self.ids["e"]),
                    ChallongeParticipantMapping(
                        source_id=source.id, challonge_participant_id=11, team_id=self.ids["team0"]
                    ),
                ]
            )
            encounter = await self.encounter(s)
            for slot, score in ((1, 2.0), (2, 1.0)):
                seat = await place_team(
                    s, encounter, slot=slot, team_id=self.ids[f"team{slot - 1}"], name=f"T{slot}", seed=None, members=()
                )
                seat.score = score
            await s.commit()
            version = encounter.result_version

        sessions = []

        def session_maker():
            sessions.append(self.Session())
            return sessions[-1]

        in_transaction: list[bool] = []

        async def update_match(*_args, **_kwargs) -> dict:
            in_transaction.append(sessions[0].in_transaction())
            return {}

        request = ChallongePushRequestedEvent(
            tournament_id=self.ids["t"], encounter_id=self.ids["e"], result_version=version, source_service="test"
        )
        with (
            patch.object(challonge_push_events.db, "async_session_maker", session_maker),
            patch.object(challonge_sync.challonge_client, "update_match", update_match),
        ):
            outcome = await challonge_push_events.process_challonge_push(request.model_dump(mode="json"))

        self.assertEqual((challonge_push_events.PUSHED, [False]), (outcome, in_transaction))
        async with self.Session() as s:
            journaled = await s.scalar(
                sa.select(ChallongeSyncLog.status).where(
                    ChallongeSyncLog.entity_id == self.ids["e"], ChallongeSyncLog.direction == "export"
                )
            )
        self.assertEqual("success", journaled, "the outcome is written after the call, in a transaction of its own")


class ChallongeRpcErrorTests(IsolatedAsyncioTestCase):
    def handler(self, subject: str):
        broker = CapturingBroker()
        integrations.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        return broker.handlers[subject]

    async def test_an_import_already_running_is_a_409(self) -> None:
        redis = _Redis()
        redis.values["challonge:sync:12:import"] = "the-auto-sync"
        with (
            patch.object(rpc_helpers.db, "async_session_maker", FakeSessionMaker()),
            patch.object(integrations.auth, "require_tournament_id_permission", AsyncMock()),
            patch.object(integrations.auth, "get_tournament_workspace_id", AsyncMock(return_value=4)),
            patch.object(integrations, "quota", SimpleNamespace(charge=AsyncMock())),
            patch.object(challonge_sync, "_get_redis", AsyncMock(return_value=redis)),
            patch.object(challonge_sync, "ADMIN_LOCK_WAIT_SECONDS", 0.05),
        ):
            envelope = await self.handler("rpc.tournament.challonge_import")(
                {"identity": make_identity(), "id": 12}, None
            )

        self.assertEqual("conflict", envelope["error"]["code"], envelope)
        self.assertEqual("the-auto-sync", redis.values["challonge:sync:12:import"], "the running import keeps its lock")

    async def test_an_unreachable_challonge_is_a_503_and_an_unknown_bracket_a_404(self) -> None:
        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable", request=request)

        def unknown(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        identity = make_identity(permissions=[{"resource": "challonge", "action": "read"}])
        for answer, code in ((unreachable, "unavailable"), (unknown, "not_found")):
            with self.subTest(code=code):
                async with httpx.AsyncClient(
                    base_url="https://api.challonge.com/v1/", transport=httpx.MockTransport(answer)
                ) as http:
                    with (
                        patch.object(rpc_helpers.db, "async_session_maker", FakeSessionMaker()),
                        patch.object(integrations.challonge_client, "_http", http),
                    ):
                        envelope = await self.handler("rpc.tournament.challonge_fetch_tournament")(
                            {"identity": identity, "query": {"tournament_slug": ["spring-cup"]}}, None
                        )
                self.assertEqual(code, envelope["error"]["code"], envelope)
