"""Team logo upload/delete: the S3 <-> DB contract, with no DB and no S3.

Three things can only go wrong in the seam between ``upload_avatar`` and
``team_service.team_service.set_team_image``, and none of them is visible to a type checker:

1. the upload's ``public_url`` must be what lands on the team (not the key, not
   ``None``) and must survive serialization out to ``TeamRead.image_url``;
2. a *rejected* upload (bad magic bytes, oversized file) must 400 and write
   nothing — a team whose ``image_url`` was set from a failed ``UploadResult``
   would point at an object that never existed;
3. delete must remove the S3 objects **before** clearing the column, so a failed
   DB write can only ever leave a URL pointing at bytes that still exist.

``set_team_image`` itself is exercised directly (it must enqueue the
tournament-changed event exactly like ``update_team``), then both subscribers are
driven end to end through their real envelope with the S3 client stubbed out.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

team_binary = importlib.import_module("src.rpc.team_binary")
helpers = importlib.import_module("src.rpc._helpers")
team_service = importlib.import_module("src.services.admin.team")
schemas = importlib.import_module("src.schemas")
s3_types = importlib.import_module("shared.clients.s3.types")

UploadResult = s3_types.UploadResult

TEAM_ID = 5
TOURNAMENT_ID = 3
WORKSPACE_ID = 1
PUBLIC_URL = "https://cdn.example.test/avatars/teams/5/abc123def456.webp"

#: A one-pixel PNG's leading bytes are irrelevant here (``upload_avatar`` is
#: stubbed), but the handler really does base64-decode this, so it must be valid.
CONTENT_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()

#: Gateway-shaped identity granting exactly the gate both subjects check.
#: Deliberately not a superuser, so the real permission path runs.
IDENTITY = make_identity(
    workspaces=[
        {
            "workspace_id": WORKSPACE_ID,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "team", "action": "update"}],
        }
    ]
)

#: Same identity without team.update — proves the gate is load-bearing.
IDENTITY_NO_PERMISSION = {
    **IDENTITY,
    "workspaces": [{"workspace_id": WORKSPACE_ID, "rbac_roles": [], "rbac_permissions": []}],
}


class _FakeS3:
    """Records ``delete_prefix`` calls into a shared ordered trace."""

    def __init__(self, trace: list[str]) -> None:
        self._trace = trace
        self.deleted_prefixes: list[str] = []

    async def delete_prefix(self, prefix: str) -> int:
        self.deleted_prefixes.append(prefix)
        self._trace.append(f"s3.delete_prefix:{prefix}")
        return 1


def _team_read(image_url: str | None) -> object:
    """The serialized shape the real ``team_flows.to_pydantic`` returns."""
    return schemas.TeamRead(
        id=TEAM_ID,
        name="Alpha",
        image_url=image_url,
        avg_sr=2500.0,
        total_sr=15000,
        tournament_id=TOURNAMENT_ID,
        captain_id=None,
        tournament=None,
        players=[],
        captain=None,
        placement=None,
        group=None,
    )


class SetTeamImage(IsolatedAsyncioTestCase):
    """``set_team_image`` must mirror ``update_team``: write, enqueue, commit,
    re-read."""

    class _Session:
        def __init__(self, team) -> None:
            self._team = team
            self.commits = 0

        async def execute(self, _query):
            # ``TeamRepository.get`` reads through ``.unique().scalars().first()``.
            scalars = SimpleNamespace(first=lambda: self._team, all=lambda: [self._team] if self._team else [])
            return SimpleNamespace(
                scalar_one_or_none=lambda: self._team,
                unique=lambda: SimpleNamespace(scalars=lambda: scalars),
            )

        async def commit(self) -> None:
            self.commits += 1

    async def _call(self, team, image_url):
        session = self._Session(team)
        enqueued: list[tuple[int, tuple]] = []

        async def fake_publish(_session, tournament_id, resources):
            enqueued.append((tournament_id, resources))

        async def fake_get_team(_session, team_id):
            return SimpleNamespace(id=team_id, reloaded=True)

        with (
            patch.object(team_service, "publish_tournament_invalidation", fake_publish),
            patch.object(team_service.team_service, "get_team", fake_get_team),
        ):
            result = await team_service.team_service.set_team_image(session, TEAM_ID, image_url)
        return result, session, enqueued

    async def test_sets_url_enqueues_and_returns_reloaded_team(self):
        team = SimpleNamespace(id=TEAM_ID, tournament_id=TOURNAMENT_ID, image_url=None)

        result, session, enqueued = await self._call(team, PUBLIC_URL)

        self.assertEqual(PUBLIC_URL, team.image_url)
        # Same invalidation update_team/delete_team publish, so the tournament's
        # cached reads and its cross-service aggregates both drop.
        self.assertEqual([(TOURNAMENT_ID, team_service.STRUCTURE_RESOURCES)], enqueued)
        self.assertEqual(1, session.commits)
        self.assertTrue(result.reloaded)

    async def test_clears_url(self):
        team = SimpleNamespace(id=TEAM_ID, tournament_id=TOURNAMENT_ID, image_url=PUBLIC_URL)

        _, _, enqueued = await self._call(team, None)

        self.assertIsNone(team.image_url)
        self.assertEqual([(TOURNAMENT_ID, team_service.STRUCTURE_RESOURCES)], enqueued)

    async def test_missing_team_404s(self):
        with self.assertRaises(Exception) as ctx:
            await self._call(None, PUBLIC_URL)

        self.assertEqual(404, ctx.exception.status_code)
        self.assertEqual("Team not found", ctx.exception.detail)


class TeamImageSubjects(IsolatedAsyncioTestCase):
    """Both subscribers, driven through their real ``_run`` envelope."""

    def setUp(self) -> None:
        self.trace: list[str] = []
        self.s3 = _FakeS3(self.trace)
        self.set_image_calls: list[tuple[int, str | None]] = []
        #: Whatever the handler staged on the session -- the audit row.
        self.staged: list = []

    async def _invoke(self, subject: str, data: dict, *, upload_result: object | None = None) -> dict:
        broker = CapturingBroker()
        team_binary.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        upload_kwargs: dict = {}

        async def fake_get_s3():
            return self.s3

        async def fake_upload_avatar(_s3, **kwargs):
            upload_kwargs.update(kwargs)
            self.trace.append("upload_avatar")
            return upload_result

        async def fake_workspace_id(_session, _team_id):
            return WORKSPACE_ID

        async def fake_set_team_image(_session, team_id, image_url):
            self.set_image_calls.append((team_id, image_url))
            self.trace.append(f"set_team_image:{image_url}")
            return SimpleNamespace(id=team_id, image_url=image_url)

        async def fake_to_pydantic(_session, team, entities):
            self.assertEqual(["tournament", "players", "players.user", "captain"], entities)
            return _team_read(team.image_url)

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(SimpleNamespace(add=self.staged.append))),
            patch.object(team_binary, "get_s3", fake_get_s3),
            patch.object(team_binary, "upload_avatar", fake_upload_avatar),
            patch.object(team_binary.auth, "get_team_workspace_id", fake_workspace_id),
            patch.object(team_binary.team_service, "set_team_image", fake_set_team_image),
            patch.object(team_binary.team_flows.flows_service, "to_pydantic", fake_to_pydantic),
        ):
            envelope = await broker.handlers[subject](data, None)
        self.upload_kwargs = upload_kwargs
        return envelope

    async def test_upload_stores_public_url_and_returns_it(self):
        envelope = await self._invoke(
            "rpc.tournament.teams.image_upload",
            {"id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(success=True, key="avatars/teams/5/abc123def456.webp", public_url=PUBLIC_URL),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        # What the broker does to the reply: it must already be plain JSON.
        json.dumps(envelope)
        self.assertEqual(PUBLIC_URL, envelope["data"]["image_url"])
        self.assertEqual([(TEAM_ID, PUBLIC_URL)], self.set_image_calls)
        # Keys must land under avatars/teams/{id}/ with the decoded bytes.
        self.assertEqual("teams", self.upload_kwargs["entity_type"])
        self.assertEqual(TEAM_ID, self.upload_kwargs["entity_id"])
        self.assertEqual("image/png", self.upload_kwargs["content_type"])
        self.assertEqual(b"\x89PNG\r\n\x1a\nfake", self.upload_kwargs["file_data"])

    async def test_upload_and_delete_journal_the_url_not_the_bytes(self):
        await self._invoke(
            "rpc.tournament.teams.image_upload",
            {"id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(success=True, key="k", public_url=PUBLIC_URL),
        )

        (row,) = self.staged
        self.assertEqual("team.image_set", row.action)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)
        self.assertEqual("team", row.entity_type)
        self.assertEqual(TEAM_ID, row.entity_id)
        self.assertEqual({"image_url": PUBLIC_URL, "content_type": "image/png"}, row.after_json)

        self.staged.clear()
        await self._invoke("rpc.tournament.teams.image_delete", {"id": TEAM_ID, "identity": IDENTITY})

        (row,) = self.staged
        self.assertEqual("team.image_clear", row.action)
        self.assertEqual({"image_url": None}, row.after_json)

    async def test_rejected_upload_400s_and_writes_nothing(self):
        envelope = await self._invoke(
            "rpc.tournament.teams.image_upload",
            {"id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(success=False, key="", error="File type not allowed"),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("bad_request", envelope["error"]["code"])
        self.assertEqual("File type not allowed", envelope["error"]["message"])
        self.assertEqual([], self.set_image_calls, "a failed upload must not touch the team")

    async def test_delete_removes_objects_before_clearing_the_column(self):
        envelope = await self._invoke(
            "rpc.tournament.teams.image_delete",
            {"id": TEAM_ID, "identity": IDENTITY},
        )

        self.assertTrue(envelope.get("ok"), envelope)
        json.dumps(envelope)
        self.assertIsNone(envelope["data"]["image_url"])
        self.assertEqual([f"avatars/teams/{TEAM_ID}/"], self.s3.deleted_prefixes)
        self.assertEqual([(TEAM_ID, None)], self.set_image_calls)
        # Order is the whole point: bytes go first, so a failed DB write cannot
        # leave image_url pointing at objects that no longer exist.
        self.assertEqual([f"s3.delete_prefix:avatars/teams/{TEAM_ID}/", "set_team_image:None"], self.trace)

    async def test_upload_without_team_update_is_forbidden(self):
        envelope = await self._invoke(
            "rpc.tournament.teams.image_upload",
            {
                "id": TEAM_ID,
                "identity": IDENTITY_NO_PERMISSION,
                "content_b64": CONTENT_B64,
                "content_type": "image/png",
            },
            upload_result=UploadResult(success=True, key="k", public_url=PUBLIC_URL),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], self.trace, "the gate must run before any S3 call")

    async def test_delete_without_team_update_is_forbidden(self):
        envelope = await self._invoke(
            "rpc.tournament.teams.image_delete",
            {"id": TEAM_ID, "identity": IDENTITY_NO_PERMISSION},
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], self.s3.deleted_prefixes)


class RegisteredSubjects(TestCase):
    """Both subjects must be documented and typed for the gateway's OpenAPI."""

    def test_openapi_docs_and_schemas_cover_both_subjects(self):
        docs = importlib.import_module("src.openapi_docs").DOCS
        operations = importlib.import_module("src.openapi_schemas").OPERATIONS

        for subject in ("rpc.tournament.teams.image_upload", "rpc.tournament.teams.image_delete"):
            self.assertIn(subject, docs)
            self.assertIn(subject, operations)
            self.assertIs(schemas.TeamRead, operations[subject].response)
