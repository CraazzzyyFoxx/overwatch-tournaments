"""Tournament cover/logo upload/delete: the S3 <-> DB contract, no DB and no S3.

The team pair's three seam risks (see ``test_team_image_rpc.py``) all apply here
unchanged, plus two that exist only because a tournament carries *two* images:

4. the ``slot`` segment reaches ``upload_avatar`` as ``variant`` and lands in the
   S3 key, so a slot the handler failed to validate would be a caller-chosen
   prefix — and, on delete, a caller-chosen ``delete_prefix`` target;
5. the slot must select the right *column*: writing the banner into ``logo_url``
   is a bug no type checker sees, since both are ``str | None``.

``set_tournament_image`` is exercised directly (it must arm the realtime/cache
listener and commit), then both subscribers run end to end through their real
``_run`` envelope with S3 stubbed out.
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

tournament_binary = importlib.import_module("src.rpc.tournament_binary")
helpers = importlib.import_module("src.rpc._helpers")
admin_tournament = importlib.import_module("src.services.admin.tournament")
schemas = importlib.import_module("src.schemas")
s3_types = importlib.import_module("shared.clients.s3.types")

UploadResult = s3_types.UploadResult

TOURNAMENT_ID = 72
WORKSPACE_ID = 1
COVER_URL = "https://cdn.example.test/avatars/tournaments/72/cover/abc123def456.webp"
LOGO_URL = "https://cdn.example.test/avatars/tournaments/72/logo/abc123def456.webp"

#: ``upload_avatar`` is stubbed, but the handler really base64-decodes this.
CONTENT_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()

#: Gateway-shaped identity granting exactly the gate both subjects check.
#: Deliberately not a superuser, so the real permission path runs.
IDENTITY = make_identity(
    workspaces=[
        {
            "workspace_id": WORKSPACE_ID,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "tournament", "action": "update"}],
        }
    ]
)

#: Same identity without tournament.update — proves the gate is load-bearing.
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


def _tournament_read(*, cover_image_url: str | None, logo_url: str | None) -> object:
    """The serialized shape ``flows.tournament_read`` returns."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return schemas.TournamentRead(
        id=TOURNAMENT_ID,
        workspace_id=WORKSPACE_ID,
        name="Anak Cup",
        slug="anak-cup",
        description=None,
        challonge_id=None,
        challonge_slug=None,
        is_league=False,
        is_finished=False,
        status="registration",
        start_date=now,
        end_date=now,
        cover_image_url=cover_image_url,
        logo_url=logo_url,
        participants_count=None,
        division_grid_version_id=None,
    )


class SetTournamentImage(IsolatedAsyncioTestCase):
    """``set_tournament_image`` must write the slot's column, arm the
    realtime/cache listener, commit, then re-read."""

    class _Session:
        def __init__(self, tournament) -> None:
            self._tournament = tournament
            self.commits = 0

        async def execute(self, _query):
            scalars = SimpleNamespace(
                first=lambda: self._tournament,
                all=lambda: [self._tournament] if self._tournament else [],
            )
            return SimpleNamespace(
                scalar_one_or_none=lambda: self._tournament,
                unique=lambda: SimpleNamespace(scalars=lambda: scalars),
            )

        async def commit(self) -> None:
            self.commits += 1

    async def _call(self, tournament, *, slot, url):
        session = self._Session(tournament)
        registered: list[tuple[int, tuple]] = []

        async def fake_emit(_session, *, scope, invalidates):
            registered.append((scope.id, tuple(invalidates)))

        async def fake_get_tournament(_session, tournament_id):
            return SimpleNamespace(id=tournament_id, reloaded=True)

        with (
            patch.object(admin_tournament, "emit", fake_emit),
            patch.object(admin_tournament.tournament_service, "get_tournament", fake_get_tournament),
        ):
            result = await admin_tournament.tournament_service.set_tournament_image(
                session, TOURNAMENT_ID, slot=slot, url=url
            )
        return result, session, registered

    def _row(self, **overrides):
        row = SimpleNamespace(id=TOURNAMENT_ID, cover_image_url=None, logo_url=None)
        for key, value in overrides.items():
            setattr(row, key, value)
        return row

    async def test_cover_slot_writes_cover_column_only(self):
        row = self._row()

        result, session, registered = await self._call(row, slot="cover", url=COVER_URL)

        self.assertEqual(COVER_URL, row.cover_image_url)
        self.assertIsNone(row.logo_url, "the cover slot must not touch the logo")
        # The listener this arms is what purges the cached public read; without it
        # the page serves the old banner for the whole TTL.
        self.assertEqual([(TOURNAMENT_ID, (admin_tournament.Resource.TOURNAMENT_DETAIL,))], registered)
        self.assertEqual(1, session.commits)
        self.assertTrue(result.reloaded)

    async def test_logo_slot_writes_logo_column_only(self):
        row = self._row()

        await self._call(row, slot="logo", url=LOGO_URL)

        self.assertEqual(LOGO_URL, row.logo_url)
        self.assertIsNone(row.cover_image_url, "the logo slot must not touch the cover")

    async def test_clears_only_the_named_slot(self):
        row = self._row(cover_image_url=COVER_URL, logo_url=LOGO_URL)

        await self._call(row, slot="cover", url=None)

        self.assertIsNone(row.cover_image_url)
        self.assertEqual(LOGO_URL, row.logo_url)

    async def test_missing_tournament_404s(self):
        with self.assertRaises(Exception) as ctx:
            await self._call(None, slot="cover", url=COVER_URL)

        self.assertEqual(404, ctx.exception.status_code)
        self.assertEqual("Tournament not found", ctx.exception.detail)


class TournamentImageSubjects(IsolatedAsyncioTestCase):
    """Both subscribers, driven through their real ``_run`` envelope."""

    UPLOAD = "rpc.tournament.tournaments.image_upload"
    DELETE = "rpc.tournament.tournaments.image_delete"

    def setUp(self) -> None:
        self.trace: list[str] = []
        self.s3 = _FakeS3(self.trace)
        self.set_image_calls: list[tuple[int, str, str | None]] = []
        self.upload_kwargs: dict = {}
        #: Whatever the handler staged on the session -- the audit row.
        self.staged: list = []

    async def _invoke(self, subject: str, data: dict, *, upload_result: object | None = None) -> dict:
        broker = CapturingBroker()
        tournament_binary.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        upload_kwargs: dict = {}
        stored: dict[str, str | None] = {"cover_image_url": None, "logo_url": None}

        async def fake_get_s3():
            return self.s3

        async def fake_upload_avatar(_s3, **kwargs):
            upload_kwargs.update(kwargs)
            self.trace.append("upload_avatar")
            return upload_result

        async def fake_workspace_id(_session, _tournament_id):
            return WORKSPACE_ID

        async def fake_set_tournament_image(_session, tournament_id, *, slot, url):
            self.set_image_calls.append((tournament_id, slot, url))
            self.trace.append(f"set_tournament_image:{slot}:{url}")
            stored["cover_image_url" if slot == "cover" else "logo_url"] = url
            return SimpleNamespace(id=tournament_id, **stored)

        async def fake_tournament_read(_session, tournament, entities):
            # Same entity set registry._ser_tournament hydrates, so the admin form
            # reads this reply exactly as it reads a PATCH reply.
            self.assertEqual(["stages", "roster_shape", "division_grid_version"], entities)
            return _tournament_read(cover_image_url=tournament.cover_image_url, logo_url=tournament.logo_url)

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(SimpleNamespace(add=self.staged.append))),
            patch.object(tournament_binary, "get_s3", fake_get_s3),
            patch.object(tournament_binary, "upload_avatar", fake_upload_avatar),
            patch.object(tournament_binary.auth, "get_tournament_workspace_id", fake_workspace_id),
            patch.object(tournament_binary.tournament_service, "set_tournament_image", fake_set_tournament_image),
            patch.object(tournament_binary.tournament_flows.flows_service, "tournament_read", fake_tournament_read),
        ):
            envelope = await broker.handlers[subject](data, None)
        self.upload_kwargs = upload_kwargs
        return envelope

    def _upload_payload(self, slot: str, identity: dict | None = None) -> dict:
        return {
            "id": TOURNAMENT_ID,
            "slot": slot,
            "identity": identity or IDENTITY,
            "content_b64": CONTENT_B64,
            "content_type": "image/png",
        }

    async def test_cover_upload_stores_public_url_under_the_cover_variant(self):
        envelope = await self._invoke(
            self.UPLOAD,
            self._upload_payload("cover"),
            upload_result=UploadResult(success=True, key="k", public_url=COVER_URL),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        # What the broker does to the reply: it must already be plain JSON.
        json.dumps(envelope)
        self.assertEqual(COVER_URL, envelope["data"]["cover_image_url"])
        self.assertIsNone(envelope["data"]["logo_url"])
        self.assertEqual([(TOURNAMENT_ID, "cover", COVER_URL)], self.set_image_calls)
        # Keys must land under avatars/tournaments/{id}/cover/ with the decoded bytes.
        self.assertEqual("tournaments", self.upload_kwargs["entity_type"])
        self.assertEqual(TOURNAMENT_ID, self.upload_kwargs["entity_id"])
        self.assertEqual("cover", self.upload_kwargs["variant"])
        self.assertEqual("image/png", self.upload_kwargs["content_type"])
        self.assertEqual(b"\x89PNG\r\n\x1a\nfake", self.upload_kwargs["file_data"])

    async def test_logo_upload_stores_public_url_under_the_logo_variant(self):
        envelope = await self._invoke(
            self.UPLOAD,
            self._upload_payload("logo"),
            upload_result=UploadResult(success=True, key="k", public_url=LOGO_URL),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(LOGO_URL, envelope["data"]["logo_url"])
        self.assertIsNone(envelope["data"]["cover_image_url"])
        self.assertEqual("logo", self.upload_kwargs["variant"])

    async def test_each_slot_write_journals_its_own_action_without_the_bytes(self):
        """The action name is built from the slot, so cover and logo are separable
        in the journal -- and the row carries the URL and content type, never the
        decoded file.
        """
        await self._invoke(
            self.UPLOAD,
            self._upload_payload("logo"),
            upload_result=UploadResult(success=True, key="k", public_url=LOGO_URL),
        )

        (row,) = self.staged
        self.assertEqual("tournament.logo_set", row.action)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)
        self.assertEqual("tournament", row.entity_type)
        self.assertEqual(TOURNAMENT_ID, row.entity_id)
        self.assertEqual({"slot": "logo", "image_url": LOGO_URL, "content_type": "image/png"}, row.after_json)

        self.staged.clear()
        await self._invoke(self.DELETE, {"id": TOURNAMENT_ID, "slot": "cover", "identity": IDENTITY})

        (row,) = self.staged
        self.assertEqual("tournament.cover_clear", row.action)
        self.assertEqual({"slot": "cover", "image_url": None}, row.after_json)

    async def test_string_id_from_the_gateway_is_accepted(self):
        # Both gateway handlers forward path params as strings (r.PathValue /
        # edge.Dispatcher), so `id` arrives as "72", not 72.
        envelope = await self._invoke(
            self.UPLOAD,
            {**self._upload_payload("cover"), "id": str(TOURNAMENT_ID)},
            upload_result=UploadResult(success=True, key="k", public_url=COVER_URL),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual([(TOURNAMENT_ID, "cover", COVER_URL)], self.set_image_calls)

    async def test_rejected_upload_400s_and_writes_nothing(self):
        envelope = await self._invoke(
            self.UPLOAD,
            self._upload_payload("cover"),
            upload_result=UploadResult(success=False, key="", error="File type not allowed"),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("bad_request", envelope["error"]["code"])
        self.assertEqual("File type not allowed", envelope["error"]["message"])
        self.assertEqual([], self.set_image_calls, "a failed upload must not touch the tournament")

    async def test_unknown_slot_400s_before_any_s3_call(self):
        envelope = await self._invoke(
            self.UPLOAD,
            self._upload_payload("../../users"),
            upload_result=UploadResult(success=True, key="k", public_url=COVER_URL),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("bad_request", envelope["error"]["code"])
        # The slot ends up inside the S3 key, so validation has to precede the
        # upload, not merely accompany it.
        self.assertEqual([], self.trace)
        self.assertEqual([], self.set_image_calls)

    async def test_missing_slot_400s(self):
        payload = self._upload_payload("cover")
        del payload["slot"]

        envelope = await self._invoke(
            self.UPLOAD, payload, upload_result=UploadResult(success=True, key="k", public_url=COVER_URL)
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("bad_request", envelope["error"]["code"])
        self.assertEqual([], self.trace)

    async def test_delete_removes_objects_before_clearing_the_column(self):
        envelope = await self._invoke(self.DELETE, {"id": TOURNAMENT_ID, "slot": "logo", "identity": IDENTITY})

        self.assertTrue(envelope.get("ok"), envelope)
        json.dumps(envelope)
        self.assertIsNone(envelope["data"]["logo_url"])
        # Only the slot's own prefix — deleting `avatars/tournaments/72/` would
        # take the cover down with the logo.
        self.assertEqual([f"avatars/tournaments/{TOURNAMENT_ID}/logo/"], self.s3.deleted_prefixes)
        self.assertEqual([(TOURNAMENT_ID, "logo", None)], self.set_image_calls)
        # Order is the whole point: bytes go first, so a failed DB write cannot
        # leave a URL pointing at objects that no longer exist.
        self.assertEqual(
            [f"s3.delete_prefix:avatars/tournaments/{TOURNAMENT_ID}/logo/", "set_tournament_image:logo:None"],
            self.trace,
        )

    async def test_delete_with_unknown_slot_400s_before_any_s3_call(self):
        envelope = await self._invoke(self.DELETE, {"id": TOURNAMENT_ID, "slot": "banner", "identity": IDENTITY})

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("bad_request", envelope["error"]["code"])
        self.assertEqual([], self.s3.deleted_prefixes)

    async def test_upload_without_tournament_update_is_forbidden(self):
        envelope = await self._invoke(
            self.UPLOAD,
            self._upload_payload("cover", IDENTITY_NO_PERMISSION),
            upload_result=UploadResult(success=True, key="k", public_url=COVER_URL),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], self.trace, "the gate must run before any S3 call")

    async def test_delete_without_tournament_update_is_forbidden(self):
        envelope = await self._invoke(
            self.DELETE, {"id": TOURNAMENT_ID, "slot": "cover", "identity": IDENTITY_NO_PERMISSION}
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], self.s3.deleted_prefixes)


class RegisteredSubjects(TestCase):
    """Both subjects must be documented and typed for the gateway's OpenAPI."""

    def test_openapi_docs_and_schemas_cover_both_subjects(self):
        docs = importlib.import_module("src.openapi_docs").DOCS
        operations = importlib.import_module("src.openapi_schemas").OPERATIONS

        for subject in (
            "rpc.tournament.tournaments.image_upload",
            "rpc.tournament.tournaments.image_delete",
        ):
            self.assertIn(subject, docs)
            self.assertIn(subject, operations)
            self.assertIs(schemas.TournamentRead, operations[subject].response)

    def test_facets_subject_is_documented_and_typed(self):
        docs = importlib.import_module("src.openapi_docs").DOCS
        operations = importlib.import_module("src.openapi_schemas").OPERATIONS

        self.assertIn("rpc.tournament.tournaments_facets", docs)
        op = operations["rpc.tournament.tournaments_facets"]
        self.assertIs(schemas.TournamentFacets, op.response)
        self.assertIs(schemas.TournamentFacetsQueryParams, op.query)
