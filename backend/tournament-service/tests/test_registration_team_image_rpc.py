"""Registered-team crest upload/delete: the S3 <-> DB contract, no DB and no S3.

The twin of ``test_team_image_rpc.py``, aimed at the seam that differs. Four
things can go wrong here and none is visible to a type checker:

1. the upload's ``public_url`` must be what lands on the team (not the key, not
   ``None``) and must survive serialization out to
   ``RegistrationTeamRead.image_url``;
2. a *rejected* upload (bad magic bytes, oversized file) must 400 and write
   nothing — a team whose ``image_url`` came from a failed ``UploadResult``
   would point at an object that never existed;
3. delete must remove the S3 objects **before** clearing the column, so a failed
   DB write can only ever leave a URL pointing at bytes that still exist;
4. a non-captain must be refused. Unlike the admin pair this is *not* a
   workspace permission, and the refusal must land before any S3 call:
   ``upload_avatar`` deletes the previous object before storing the new one, so
   a stranger who reached S3 would destroy the captain's crest whatever the
   database then said.

Both subscribers are driven end to end through their real ``_run`` envelope with
the service layer and the S3 client stubbed out.
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

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

regteam_binary = importlib.import_module("src.rpc.registration_team_binary")
helpers = importlib.import_module("src.rpc._helpers")
team_service = importlib.import_module("src.services.registration.teams")
regteam_schemas = importlib.import_module("src.schemas.registration_team")
s3_types = importlib.import_module("shared.clients.s3.types")

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

UploadResult = s3_types.UploadResult
RegistrationTeamRead = regteam_schemas.RegistrationTeamRead

TEAM_ID = 11
TOURNAMENT_ID = 4
PUBLIC_URL = "https://cdn.example.test/avatars/registration_teams/11/abc123def456.webp"

#: A one-pixel PNG's leading bytes are irrelevant here (``upload_avatar`` is
#: stubbed), but the handler really does base64-decode this, so it must be valid.
CONTENT_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()

#: Gateway-shaped identity. No workspace membership at all — the whole point of
#: the captain gate is that the crest's owner is an ordinary competitor.
IDENTITY = make_identity()


class _FakeS3:
    """Records ``delete_prefix`` calls into a shared ordered trace."""

    def __init__(self, trace: list[str]) -> None:
        self._trace = trace
        self.deleted_prefixes: list[str] = []

    async def delete_prefix(self, prefix: str) -> int:
        self.deleted_prefixes.append(prefix)
        self._trace.append(f"s3.delete_prefix:{prefix}")
        return 1


def _team_read(image_url: str | None) -> RegistrationTeamRead:
    """The serialized shape the real ``describe_team`` returns for a captain."""
    return RegistrationTeamRead(
        id=TEAM_ID,
        tournament_id=TOURNAMENT_ID,
        name="Alpha",
        image_url=image_url,
        status="forming",
        captain_registration_id=42,
        exported_team_id=None,
        members=[],
        invites=[],
        open_slots={"tank": 1},
        shortfall="1x tank",
        is_complete=False,
        substitutes_used=0,
        max_substitutes=2,
    )


class RegistrationTeamImageSubjects(IsolatedAsyncioTestCase):
    """Both subscribers, driven through their real ``_run`` envelope."""

    def setUp(self) -> None:
        self.trace: list[str] = []
        self.s3 = _FakeS3(self.trace)
        self.set_image_calls: list[tuple[int, str | None]] = []
        self.gate_calls: list[tuple[int, int]] = []
        #: Overridable so a test can make the captain gate refuse.
        self.gate_error: Exception | None = None
        #: Overridable so a test can make the authoritative under-lock check refuse.
        self.set_image_error: Exception | None = None
        #: Whatever the handler staged on the session -- the audit row.
        self.staged: list = []

    async def _invoke(self, subject: str, data: dict, *, upload_result: object | None = None) -> dict:
        broker = CapturingBroker()
        regteam_binary.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        upload_kwargs: dict = {}

        async def fake_get_s3():
            return self.s3

        async def fake_upload_avatar(_s3, **kwargs):
            upload_kwargs.update(kwargs)
            self.trace.append("upload_avatar")
            return upload_result

        async def fake_gate(_session, *, team_id, auth_user):
            self.gate_calls.append((team_id, auth_user.id))
            self.trace.append(f"assert_may_edit_team:{team_id}")
            if self.gate_error is not None:
                raise self.gate_error

        async def fake_set_team_image(_session, *, team_id, auth_user, image_url):
            self.set_image_calls.append((team_id, image_url))
            self.trace.append(f"set_team_image:{image_url}")
            if self.set_image_error is not None:
                raise self.set_image_error
            return SimpleNamespace(id=team_id, image_url=image_url)

        async def fake_describe_team(_session, team, *, include_invites=False):
            # The captain's own view: a public roster would leak who declined.
            self.assertTrue(include_invites)
            return _team_read(team.image_url)

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(SimpleNamespace(add=self.staged.append))),
            patch.object(regteam_binary, "get_s3", fake_get_s3),
            patch.object(regteam_binary, "upload_avatar", fake_upload_avatar),
            patch.object(regteam_binary.team_service.teams_service, "assert_may_edit_team", fake_gate),
            patch.object(regteam_binary.team_service.teams_service, "set_team_image", fake_set_team_image),
            patch.object(regteam_binary.team_service.teams_service, "describe_team", fake_describe_team),
        ):
            envelope = await broker.handlers[subject](data, None)
        self.upload_kwargs = upload_kwargs
        return envelope

    async def test_upload_stores_public_url_and_returns_it(self):
        envelope = await self._invoke(
            "rpc.tournament.regteam_image_upload",
            {"team_id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(
                success=True,
                key="avatars/registration_teams/11/abc123def456.webp",
                public_url=PUBLIC_URL,
            ),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        # What the broker does to the reply: it must already be plain JSON.
        json.dumps(envelope)
        self.assertEqual(PUBLIC_URL, envelope["data"]["image_url"])
        self.assertEqual([(TEAM_ID, PUBLIC_URL)], self.set_image_calls)
        # Keys must land under avatars/registration_teams/{id}/ with the decoded
        # bytes — a separate prefix from avatars/teams/, which an exported team
        # of the same id would otherwise collide with.
        self.assertEqual("registration_teams", self.upload_kwargs["entity_type"])
        self.assertEqual(TEAM_ID, self.upload_kwargs["entity_id"])
        self.assertEqual("image/png", self.upload_kwargs["content_type"])
        self.assertEqual(b"\x89PNG\r\n\x1a\nfake", self.upload_kwargs["file_data"])

    async def test_upload_and_delete_journal_the_url_not_the_bytes(self):
        """A captain is not an operator, so the row carries no workspace -- the
        gate here is captaincy, not a workspace permission.
        """
        await self._invoke(
            "rpc.tournament.regteam_image_upload",
            {"team_id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(success=True, key="k", public_url=PUBLIC_URL),
        )

        (row,) = self.staged
        self.assertEqual("registration_team.image_set", row.action)
        self.assertIsNone(row.workspace_id)
        self.assertEqual("registration_team", row.entity_type)
        self.assertEqual(TEAM_ID, row.entity_id)
        self.assertEqual({"image_url": PUBLIC_URL, "content_type": "image/png"}, row.after_json)

        self.staged.clear()
        await self._invoke("rpc.tournament.regteam_image_delete", {"team_id": TEAM_ID, "identity": IDENTITY})

        (row,) = self.staged
        self.assertEqual("registration_team.image_clear", row.action)
        self.assertEqual({"image_url": None}, row.after_json)

    async def test_rejected_upload_400s_and_writes_nothing(self):
        envelope = await self._invoke(
            "rpc.tournament.regteam_image_upload",
            {"team_id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(success=False, key="", error="File type not allowed"),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("bad_request", envelope["error"]["code"])
        self.assertEqual("File type not allowed", envelope["error"]["message"])
        self.assertEqual([], self.set_image_calls, "a failed upload must not touch the team")

    async def test_delete_removes_objects_before_clearing_the_column(self):
        envelope = await self._invoke(
            "rpc.tournament.regteam_image_delete",
            {"team_id": TEAM_ID, "identity": IDENTITY},
        )

        self.assertTrue(envelope.get("ok"), envelope)
        json.dumps(envelope)
        self.assertIsNone(envelope["data"]["image_url"])
        self.assertEqual([f"avatars/registration_teams/{TEAM_ID}/"], self.s3.deleted_prefixes)
        self.assertEqual([(TEAM_ID, None)], self.set_image_calls)
        # Order is the whole point: the gate runs before any S3 call, then bytes
        # go before the column, so a failed DB write cannot leave image_url
        # pointing at objects that no longer exist.
        self.assertEqual(
            [
                f"assert_may_edit_team:{TEAM_ID}",
                f"s3.delete_prefix:avatars/registration_teams/{TEAM_ID}/",
                "set_team_image:None",
            ],
            self.trace,
        )

    async def test_non_captain_upload_is_refused_before_s3(self):
        self.gate_error = team_service._fail(403, "not_captain", "Only the team captain can do this")

        envelope = await self._invoke(
            "rpc.tournament.regteam_image_upload",
            {"team_id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(success=True, key="k", public_url=PUBLIC_URL),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        # ``_run`` maps ApiHTTPException through ``shared.rpc.common.http_error``:
        # the message is the human text and the machine code the frontend
        # translates rides ``details["fields"]``, which the gateway relays.
        self.assertEqual("not_captain", envelope["error"]["details"]["fields"][0]["code"])
        self.assertEqual([], self.set_image_calls)
        # upload_avatar deletes the previous object before writing the new one,
        # so reaching S3 at all would let a stranger destroy the crest.
        self.assertEqual([f"assert_may_edit_team:{TEAM_ID}"], self.trace)

    async def test_non_captain_delete_is_refused_before_s3(self):
        self.gate_error = team_service._fail(403, "not_captain", "Only the team captain can do this")

        envelope = await self._invoke(
            "rpc.tournament.regteam_image_delete",
            {"team_id": TEAM_ID, "identity": IDENTITY},
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual([], self.s3.deleted_prefixes)
        self.assertEqual([], self.set_image_calls)

    async def test_under_lock_refusal_surfaces_in_the_envelope(self):
        """The lock-free pre-gate is advisory; ``set_team_image`` re-checks under
        the row lock and its refusal must reach the caller with its code intact."""
        self.set_image_error = team_service._fail(
            409, "team_already_exported", "This team has already been exported to the tournament"
        )

        envelope = await self._invoke(
            "rpc.tournament.regteam_image_upload",
            {"team_id": TEAM_ID, "identity": IDENTITY, "content_b64": CONTENT_B64, "content_type": "image/png"},
            upload_result=UploadResult(success=True, key="k", public_url=PUBLIC_URL),
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("conflict", envelope["error"]["code"])
        self.assertEqual("team_already_exported", envelope["error"]["details"]["fields"][0]["code"])


class GateSignature(TestCase):
    """The handlers call the service by keyword; a positional drift would pass
    ``auth_user`` as ``image_url`` and silently store a user object."""

    def test_set_team_image_is_keyword_only(self):
        import inspect

        params = inspect.signature(team_service.teams_service.set_team_image).parameters
        self.assertEqual(["session", "team_id", "auth_user", "image_url"], list(params))
        for name in ("team_id", "auth_user", "image_url"):
            self.assertIs(inspect.Parameter.KEYWORD_ONLY, params[name].kind)


class RegisteredSubjects(TestCase):
    """Both subjects must be documented and typed for the gateway's OpenAPI."""

    def test_openapi_docs_and_schemas_cover_both_subjects(self):
        docs = importlib.import_module("src.openapi_docs").DOCS
        operations = importlib.import_module("src.openapi_schemas").OPERATIONS

        for subject in ("rpc.tournament.regteam_image_upload", "rpc.tournament.regteam_image_delete"):
            self.assertIn(subject, docs)
            self.assertIn(subject, operations)
            self.assertIs(RegistrationTeamRead, operations[subject].response)
