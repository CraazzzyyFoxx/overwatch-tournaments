from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared import models  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain.roster_shape import RosterShape  # noqa: E402
from shared.domain.team_format import FormatDimension, TeamFormat  # noqa: E402
from shared.quota import QuotaLease  # noqa: E402
from shared.services import team_format as formats  # noqa: E402
from shared.services.ontology import project_disciplines  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from shared.testing.db import ensure_test_postgres  # noqa: E402
from src.schemas.balancer import TeamData  # noqa: E402
from src.services.balancer import jobs  # noqa: E402
from src.services.balancer import solver as solver_module  # noqa: E402

JOBS = "src.services.balancer.jobs"
FLEX_SHAPE = RosterShape(entries=tuple({"tank": 1, "flex": 4}.items()))


def _shape_resolver(shape=FLEX_SHAPE) -> AsyncMock:
    """Stand in for the DB-backed roster-shape lookup ``create_job`` performs."""
    return AsyncMock(return_value={"role_mask": shape.slots})


def _noop_quota(**overrides) -> SimpleNamespace:
    """The quota gate as a pass-through, recording what the handler asked for."""
    fake = SimpleNamespace(
        check_payload=AsyncMock(),
        charge=AsyncMock(),
        lease=AsyncMock(),
        release=AsyncMock(),
        principal_of=lambda user: (
            ("api_key", int(user._api_key_id))
            if getattr(user, "_credential_type", "access_token") == "api_key"
            else ("user", int(user.id))
        ),
    )
    fake.lease.side_effect = lambda user, operation, **kwargs: QuotaLease(
        lease_id=kwargs.get("lease_id") or "lease",
        principal_kind="api_key" if getattr(user, "_credential_type", "") == "api_key" else "user",
        principal_id=42,
        workspace_id=kwargs.get("workspace_id"),
    )
    for name, value in overrides.items():
        setattr(fake, name, value)
    return fake


def _api_key_user(*, scopes: list[str], workspace_id: int = 77) -> SimpleNamespace:
    """An API-key principal shaped the way ``_resolve_user_from_token`` builds one.

    ``has_workspace_permission`` stands in for the scope-intersected
    ``rbac_permissions`` identity-service writes into the key's single workspace.
    """
    return SimpleNamespace(
        id=9,
        _credential_type="api_key",
        _api_key_id=42,
        _api_key_workspace_id=workspace_id,
        _api_key_scopes=scopes,
        has_workspace_permission=lambda ws_id, resource, action: ws_id == workspace_id
        and resource == "team"
        and action == "create",
    )


class CreateJobTests(IsolatedAsyncioTestCase):
    async def test_creates_job_and_publishes_queue_event(self) -> None:
        created: dict = {}

        class FakeStore:
            async def create_job(
                self,
                input_data,
                config_overrides,
                *,
                job_id,
                workspace_id,
                created_by,
                credential_type,
                api_key_id,
                tournament_id=None,
                role_mask=None,
            ):
                created.update(
                    input_data=input_data,
                    config_overrides=config_overrides,
                    job_id=job_id,
                    workspace_id=workspace_id,
                    tournament_id=tournament_id,
                    created_by=created_by,
                    credential_type=credential_type,
                    api_key_id=api_key_id,
                    role_mask=role_mask,
                )
                return "job-123"

            async def mark_failed(self, *a, **k):  # pragma: no cover - not expected here
                raise AssertionError("mark_failed should not be called")

        class FakeParser:
            async def parse_player_data(self, uploaded_file) -> dict:
                return {"players": {"1": {"name": "Player One"}}}

            def parse_config_overrides(self, raw_config):
                return {"algorithm": "moo"}

        class FakePublisher:
            def __init__(self, broker, logger):
                self.broker = broker

            async def publish_job_requested(self, job_id: str) -> None:
                created["published_job_id"] = job_id

        access_policy = SimpleNamespace(ensure_workspace_access=lambda *a, **k: created.update(access=True))

        with (
            patch(f"{JOBS}.get_job_store", return_value=FakeStore()),
            patch(f"{JOBS}.quota", _noop_quota()),
            patch(f"{JOBS}._access_policy", access_policy),
            patch(f"{JOBS}._payload_parser", FakeParser()),
            patch(f"{JOBS}.BalancerJobPublisher", FakePublisher),
            patch(f"{JOBS}._owner_format_context", _shape_resolver()),
        ):
            response = await jobs.create_job(
                session=SimpleNamespace(),
                uploaded_file=SimpleNamespace(filename="players.json"),
                raw_config='{"algorithm": "moo"}',
                workspace_id=77,
                user=SimpleNamespace(id=9),
                broker=SimpleNamespace(),
            )

        self.assertEqual(response.job_id, "job-123")
        self.assertEqual(response.status, "queued")
        # Only routes the gateway serves, under its canonical prefix.
        self.assertEqual(
            response.model_dump(),
            {
                "job_id": "job-123",
                "status": "queued",
                "status_url": "/api/v1/balancer/jobs/job-123",
                "result_url": "/api/v1/balancer/jobs/job-123/result",
            },
        )
        self.assertEqual(created["workspace_id"], 77)
        self.assertEqual(created["created_by"], 9)
        self.assertEqual(created["published_job_id"], "job-123")
        self.assertEqual(created["config_overrides"], {"algorithm": "moo"})
        self.assertEqual(created["credential_type"], "access_token")
        self.assertIsNone(created["api_key_id"])
        # The queued payload records the tournament's roster shape, not a
        # request-supplied mask: that is what the run balances against.
        self.assertEqual(created["role_mask"], {"tank": 1, "flex": 4})

    async def test_publishes_realtime_queued_event_when_tournament_scoped(self) -> None:
        class FakeStore:
            async def create_job(self, *a, **k):
                return "job-xyz"

            async def mark_failed(self, *a, **k):  # pragma: no cover - not expected here
                raise AssertionError("mark_failed should not be called")

        class FakeParser:
            async def parse_player_data(self, uploaded_file) -> dict:
                return {"players": {"1": {"name": "Player One"}}}

            def parse_config_overrides(self, raw_config):
                return {}

        class FakePublisher:
            def __init__(self, broker, logger):
                pass

            async def publish_job_requested(self, job_id: str) -> None:
                pass

        access_policy = SimpleNamespace(ensure_workspace_access=lambda *a, **k: None)
        emit = AsyncMock()

        with (
            patch(f"{JOBS}.get_job_store", return_value=FakeStore()),
            patch(f"{JOBS}.quota", _noop_quota()),
            patch(f"{JOBS}._access_policy", access_policy),
            patch(f"{JOBS}._payload_parser", FakeParser()),
            patch(f"{JOBS}.BalancerJobPublisher", FakePublisher),
            patch(f"{JOBS}._emit_job", emit),
            patch(f"{JOBS}._owner_format_context", _shape_resolver()),
        ):
            await jobs.create_job(
                session=SimpleNamespace(),
                uploaded_file=SimpleNamespace(filename="players.json"),
                raw_config=None,
                workspace_id=77,
                user=SimpleNamespace(id=9),
                broker=SimpleNamespace(),
                tournament_id=42,
                formation_node_id=7,
            )

        emit.assert_awaited_once()
        args, kwargs = emit.await_args
        self.assertEqual(args[0], 42)
        self.assertEqual(args[1], "balancer_job.queued")
        self.assertEqual(kwargs["job_id"], "job-xyz")
        self.assertEqual(kwargs["status"], "queued")
        # The event names the node, so a page on another formation ignores the job's result.
        self.assertEqual(kwargs["formation_node_id"], 7)
        self.assertEqual(kwargs["actor_user_id"], 9)

    async def test_api_key_create_job_reserves_limit_and_stores_metadata(self) -> None:
        created: dict = {}

        class FakeStore:
            async def create_job(
                self,
                input_data,
                config_overrides,
                *,
                job_id,
                workspace_id,
                created_by,
                credential_type,
                api_key_id,
                tournament_id=None,
                role_mask=None,
            ):
                created.update(job_id=job_id, credential_type=credential_type, api_key_id=api_key_id)
                return job_id

        class FakeParser:
            async def parse_player_data(self, uploaded_file) -> dict:
                return {"players": {"1": {"name": "Player One"}}}

            def parse_config_overrides(self, raw_config):
                return {"population_size": 150}

        class FakePublisher:
            def __init__(self, broker, logger):
                pass

            async def publish_job_requested(self, job_id: str) -> None:
                created["published_job_id"] = job_id

        gate = _noop_quota()
        # Deliberately NOT stubbing ``_access_policy``: the real
        # WorkspaceAccessPolicy must admit a correctly scoped key, which is the
        # whole point of dropping the old blanket api-key rejection.
        user = _api_key_user(scopes=["team.create"])

        with (
            patch(f"{JOBS}.get_job_store", return_value=FakeStore()),
            patch(f"{JOBS}.quota", gate),
            patch(f"{JOBS}._payload_parser", FakeParser()),
            patch(f"{JOBS}.BalancerJobPublisher", FakePublisher),
            patch(f"{JOBS}._owner_format_context", _shape_resolver()),
        ):
            response = await jobs.create_job(
                session=SimpleNamespace(),
                uploaded_file=SimpleNamespace(filename="players.json", size=1024),
                raw_config='{"algorithm": "moo", "population_size": 150}',
                workspace_id=77,
                user=user,
                broker=SimpleNamespace(),
            )

        self.assertEqual(response.job_id, created["job_id"])
        self.assertEqual(created["credential_type"], "api_key")
        self.assertEqual(created["api_key_id"], 42)
        # The lease id IS the job id, so the worker that finishes the job can
        # release the slot from its metadata alone.
        self.assertEqual(gate.lease.await_args.kwargs["lease_id"], created["job_id"])
        self.assertEqual(gate.lease.await_args.kwargs["workspace_id"], 77)
        self.assertEqual(gate.lease.await_args.args[1], "balancer.job")
        # The upload cap is settled before the payload is parsed.
        self.assertEqual(gate.check_payload.await_args.kwargs["size_bytes"], 1024)
        gate.release.assert_not_awaited()

    async def test_api_key_create_job_rejected_without_team_create_scope(self) -> None:
        """The real scope gate stops an under-scoped key before any work is done.

        ``ensure_workspace_access`` runs ahead of payload parsing and the quota
        lease, so a rejected request must not consume a job slot -- the payload
        cap is the only gate it is allowed to touch.
        """
        gate = _noop_quota()
        user = _api_key_user(scopes=["registration.approve"])

        with (
            patch(f"{JOBS}.get_job_store", return_value=SimpleNamespace()),
            patch(f"{JOBS}.quota", gate),
            self.assertRaises(HTTPException) as exc_info,
        ):
            await jobs.create_job(
                session=SimpleNamespace(),
                uploaded_file=SimpleNamespace(filename="players.json", size=1024),
                raw_config=None,
                workspace_id=77,
                user=user,
                broker=SimpleNamespace(),
            )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.detail, "API key scope required: team.create")
        gate.lease.assert_not_awaited()

    async def test_upload_rejects_tournament_from_another_workspace(self) -> None:
        gate = _noop_quota()
        store = SimpleNamespace(create_job=AsyncMock())
        with (
            patch(f"{JOBS}.get_job_store", return_value=store),
            patch(f"{JOBS}.quota", gate),
            patch(
                f"{JOBS}._payload_parser",
                SimpleNamespace(
                    parse_player_data=AsyncMock(return_value={"players": {}}),
                    parse_config_overrides=lambda value: None,
                ),
            ),
            patch(
                f"{JOBS}.TournamentRepository",
                return_value=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=10, workspace_id=88))),
            ),
            patch(f"{JOBS}.tournament_format", AsyncMock()) as load_format,
            self.assertRaises(HTTPException) as exc_info,
        ):
            await jobs.create_job(
                session=SimpleNamespace(),
                uploaded_file=SimpleNamespace(filename="players.json", size=10),
                raw_config=None,
                workspace_id=77,
                user=_api_key_user(scopes=["team.create"]),
                broker=SimpleNamespace(),
                tournament_id=10,
            )
        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.detail, "Tournament not found")
        load_format.assert_not_awaited()
        gate.lease.assert_not_awaited()
        store.create_job.assert_not_awaited()


class CreateJobFormatIntegrationTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def test_job_uses_workspace_default_or_preset_without_a_tournament(self) -> None:
        ensure_test_postgres()
        engine = create_test_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await project_disciplines(session)
                workspace = models.Workspace(slug="job-format-test", name="Job format test")
                session.add(workspace)
                await session.flush()
                store = SimpleNamespace(create_job=AsyncMock(return_value="format-job"))
                parser = SimpleNamespace(
                    parse_player_data=AsyncMock(return_value={"players": {}}),
                    parse_config_overrides=lambda value: None,
                )
                with (
                    patch(f"{JOBS}.get_job_store", return_value=store),
                    patch(f"{JOBS}.quota", _noop_quota()),
                    patch(f"{JOBS}._payload_parser", parser),
                    patch(
                        f"{JOBS}.BalancerJobPublisher", return_value=SimpleNamespace(publish_job_requested=AsyncMock())
                    ),
                ):
                    for expected in ({"tank": 1, "damage": 2, "support": 2}, {"flex": 6}):
                        response = await jobs.create_job(
                            session=session,
                            uploaded_file=SimpleNamespace(filename="players.json", size=10),
                            raw_config=None,
                            workspace_id=workspace.id,
                            user=_api_key_user(scopes=["team.create"], workspace_id=workspace.id),
                            broker=SimpleNamespace(),
                            discipline="overwatch",
                        )
                        assert response.job_id == "format-job"
                        assert store.create_job.await_args.kwargs["role_mask"] == expected
                        assert store.create_job.await_args.kwargs["tournament_id"] is None
                        snapshot = store.create_job.await_args.args[0]["format_context"]
                        decoded = solver_module._format_kwargs({"format_context": snapshot})
                        assert decoded["team_format"].discipline == "overwatch"
                        assert decoded["ontology"].rated.code == "player_role"
                        await formats.save_workspace_format(
                            session,
                            workspace_id=workspace.id,
                            discipline="overwatch",
                            team_format=TeamFormat(
                                "overwatch", "Open six", 6, 6, dimensions=(FormatDimension("player_role", "off"),)
                            ),
                        )
                    # An upload names its game: none, or one the workspace has not enabled, is refused before any job.
                    for discipline in (None, "lol"):
                        store.create_job.reset_mock()
                        with self.assertRaises(HTTPException) as refused:
                            await jobs.create_job(
                                session=session,
                                uploaded_file=SimpleNamespace(filename="players.json", size=10),
                                raw_config=None,
                                workspace_id=workspace.id,
                                user=_api_key_user(scopes=["team.create"], workspace_id=workspace.id),
                                broker=SimpleNamespace(),
                                discipline=discipline,
                            )
                        assert refused.exception.status_code == 422
                        store.create_job.assert_not_awaited()
                await session.rollback()
        finally:
            await engine.dispose()


def _make_fake_store(payload: dict, *, fail_marks: bool = False, optimizing_messages: list | None = None):
    class FakeStore:
        def __init__(self) -> None:
            self.meta = {"status": "queued", "created_at": 0.0, "events_count": 0}
            self.succeeded = None
            self.failed = None

        async def get_job_payload(self, job_id: str) -> dict:
            return payload

        async def get_job_meta(self, job_id: str) -> dict:
            return self.meta

        async def mark_running(self, job_id: str, meta=None) -> dict:
            self.meta = dict(meta or self.meta)
            self.meta["status"] = "running"
            return self.meta

        async def append_event(
            self, job_id, *, status, stage, message, level="info", progress=None, update_meta=False, meta=None
        ):
            if optimizing_messages is not None and stage == "optimizing":
                optimizing_messages.append(message)
            if meta is not None:
                meta["events_count"] = int(meta.get("events_count", 0)) + 1
                if update_meta:
                    meta["status"] = status
                    meta["stage"] = stage
                    if progress is not None:
                        meta["progress"] = progress
                self.meta = meta

        async def mark_succeeded(self, job_id, result, meta=None) -> dict:
            self.succeeded = (job_id, result)
            self.meta = dict(meta or self.meta)
            self.meta["status"] = "succeeded"
            return self.meta

        async def mark_failed(self, job_id, error_message, meta=None) -> dict:
            if fail_marks:
                raise AssertionError(error_message)
            self.failed = (job_id, error_message)
            self.meta = dict(meta or self.meta)
            self.meta["status"] = "failed"
            return self.meta

    return FakeStore()


_VARIANT = {
    "teams": [],
    "statistics": {"average_mmr": 0, "mmr_std_dev": 0, "total_teams": 0, "players_per_team": 5},
    "benched_players": [],
}


class ExecuteJobTests(IsolatedAsyncioTestCase):
    async def test_executes_job_and_marks_result(self) -> None:
        store = _make_fake_store(
            {
                "player_data": {"players": {}},
                "config_overrides": {"algorithm": "moo"},
                "role_mask": {"tank": 1, "flex": 4},
            }
        )
        seen: dict = {}

        async def fake_run_balance(input_data, config_overrides, progress_callback, role_mask=None, *, discipline=None):
            seen["role_mask"] = role_mask
            progress_callback({"status": "running", "stage": "optimizing", "message": "Working"})
            return {"variants": [dict(_VARIANT)]}

        with (
            patch(f"{JOBS}.get_job_store", return_value=store),
            patch(f"{JOBS}.run_balance", fake_run_balance),
        ):
            await jobs.execute_balance_job("job-42")

        self.assertEqual(store.succeeded[0], "job-42")
        self.assertEqual(store.succeeded[1]["variants"][0]["teams"], [])
        self.assertIsNone(store.failed)
        # The shape resolved at creation reaches the solver untouched.
        self.assertEqual(seen["role_mask"], {"tank": 1, "flex": 4})

    async def test_flushes_last_throttled_progress_update_before_completion(self) -> None:
        messages: list[str] = []
        store = _make_fake_store(
            {"player_data": {"players": {}}, "config_overrides": {"algorithm": "moo"}},
            fail_marks=True,
            optimizing_messages=messages,
        )

        async def fake_run_balance(input_data, config_overrides, progress_callback, role_mask=None, *, discipline=None):
            progress_callback(
                {"status": "running", "stage": "optimizing", "message": "Phase 1", "progress": {"percent": 0.0}}
            )
            progress_callback(
                {"status": "running", "stage": "optimizing", "message": "Phase 2", "progress": {"percent": 1.0}}
            )
            return {"variants": [dict(_VARIANT)]}

        clock_values = iter([1.0, 1.1, 1.2])
        with (
            patch(f"{JOBS}.get_job_store", return_value=store),
            patch(f"{JOBS}.run_balance", fake_run_balance),
        ):
            await jobs.execute_balance_job("job-throttle", progress_clock=lambda: next(clock_values))

        self.assertEqual(messages, ["Phase 1", "Phase 2"])

    async def test_ignores_legacy_job_payload_config_key(self) -> None:
        store = _make_fake_store(
            {"player_data": {"players": {}}, "config": {"population_size": 50}},
            fail_marks=True,
        )
        seen: dict = {}

        async def fake_run_balance(input_data, config_overrides, progress_callback, role_mask=None, *, discipline=None):
            seen["config_overrides"] = config_overrides
            seen["role_mask"] = role_mask
            return {"variants": [dict(_VARIANT)]}

        with (
            patch(f"{JOBS}.get_job_store", return_value=store),
            patch(f"{JOBS}.run_balance", fake_run_balance),
        ):
            await jobs.execute_balance_job("job-legacy")

        self.assertEqual(seen["config_overrides"], {})
        # A payload queued before roster shapes reached the balancer leaves the
        # mask unset, and the AlgorithmConfig default stands in.
        self.assertIsNone(seen["role_mask"])


class BalanceInlineTests(IsolatedAsyncioTestCase):
    """The synchronous endpoint: job gates, no job store, clamped budget."""

    @staticmethod
    def _call(**overrides):
        kwargs = {
            "player_data": {"players": {"1": {"name": "One"}}},
            "role_mask": {"tank": 1, "flex": 4},
            "config_overrides": None,
            "workspace_id": 77,
            "discipline": "overwatch",
            "user": _api_key_user(scopes=["team.create"]),
        }
        kwargs.update(overrides)
        return jobs.balance_inline(**kwargs)

    @staticmethod
    def _patches(gate, run_balance):
        return (
            patch(f"{JOBS}.quota", gate),
            patch(f"{JOBS}._access_policy", SimpleNamespace(ensure_workspace_access=lambda *a, **k: None)),
            patch(f"{JOBS}.run_balance", run_balance),
        )

    async def test_caller_cannot_exceed_the_synchronous_solver_budget(self) -> None:
        seen: dict = {}

        async def fake_run_balance(input_data, config_overrides, progress_callback, role_mask=None, *, discipline=None):
            seen.update(config=config_overrides, role_mask=role_mask, callback=progress_callback)
            return {"variants": [dict(_VARIANT)]}

        gate = _noop_quota()
        session_user = SimpleNamespace(id=5, _credential_type="access_token")
        patches = self._patches(gate, fake_run_balance)
        with patches[0], patches[1], patches[2]:
            result = await self._call(
                user=session_user,
                config_overrides={"time_limit_ms": 600000, "population_size": 50},
            )

        # The 600s job ceiling would outlive the HTTP request that is waiting on it.
        self.assertEqual(seen["config"]["time_limit_ms"], jobs.SYNC_TIME_LIMIT_MS)
        self.assertEqual(seen["config"]["population_size"], 50)
        self.assertEqual(seen["role_mask"], {"tank": 1, "flex": 4})
        # No progress transport on this path, so nothing to emit into.
        self.assertIsNone(seen["callback"])
        self.assertEqual(result["variants"][0]["statistics"]["players_per_team"], 5)
        gate.lease.assert_awaited_once()
        gate.release.assert_awaited_once()

    async def test_the_synchronous_budget_is_injected_not_taken_from_the_caller(self) -> None:
        """The caller never sent ``time_limit_ms``; the inline path sets its own."""
        seen: dict = {}

        async def fake_run_balance(input_data, config_overrides, progress_callback, role_mask=None, *, discipline=None):
            seen.update(config=config_overrides)
            return {"variants": [dict(_VARIANT)]}

        gate = _noop_quota()
        patches = self._patches(gate, fake_run_balance)
        with patches[0], patches[1], patches[2]:
            await self._call(config_overrides={"population_size": 50})

        self.assertEqual(seen["config"]["time_limit_ms"], jobs.SYNC_TIME_LIMIT_MS)

    async def test_releases_the_concurrency_slot_when_the_solve_fails(self) -> None:
        async def failing_run_balance(*args, **kwargs):
            raise HTTPException(status_code=422, detail="No valid players found")

        gate = _noop_quota()
        patches = self._patches(gate, failing_run_balance)
        with patches[0], patches[1], patches[2], self.assertRaises(HTTPException):
            await self._call()

        # A failed solve must give the slot back, or a client that always times
        # out would exhaust its concurrency for the lease TTL.
        gate.release.assert_awaited_once()
        self.assertEqual(
            gate.release.await_args.args[0].lease_id,
            gate.lease.await_args.kwargs["lease_id"],
        )


class SolverTests(IsolatedAsyncioTestCase):
    async def test_run_balance_preserves_variants_shape(self) -> None:
        variants = [
            {"teams": [{"id": 1}], "statistics": {}, "benched_players": []},
            {"teams": [{"id": 2}], "statistics": {}, "benched_players": []},
        ]
        with patch(
            "src.services.balancer.solver.asyncio.to_thread",
            AsyncMock(return_value=variants),
        ) as to_thread:
            result = await solver_module.run_balance({"players": {}}, {"algorithm": "moo"}, None)

        self.assertEqual(result, {"variants": variants})
        to_thread.assert_awaited_once()


def test_format_findings_survive_result_normalization() -> None:
    team = {
        "id": 1,
        "name": "A",
        "average_mmr": 0.0,
        "rating_variance": 0.0,
        "total_discomfort": 0,
        "max_discomfort": 0,
        "roster": {},
        "format_violations": ["role_below_hard_min"],
        "format_advisories": ["role_below_recommended_min"],
    }
    dumped = TeamData.model_validate(team).model_dump()
    assert (dumped["format_violations"], dumped["format_advisories"]) == (
        ["role_below_hard_min"],
        ["role_below_recommended_min"],
    )
