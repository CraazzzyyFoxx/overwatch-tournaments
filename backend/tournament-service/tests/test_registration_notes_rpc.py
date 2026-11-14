"""Organizer notes on registrations and teams, through the real handlers on the test Postgres.

What can go wrong without a type checker noticing:

1. the permission resource must follow the note's TARGET (``registration`` vs
   ``team``) -- a registration grant must not open a team's notes;
2. only the author edits; a colleague deletes only with the ``delete`` grant;
3. an attachment is stored PRIVATE, typed by its extension (never the client's
   content type), refused for a disallowed type or past the per-note cap before
   anything reaches S3, and its objects go only after the row is gone;
4. a target from another tournament is a 404, not a cross-event write.

S3 is the only stub.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from shared.testing.db import ensure_test_postgres  # noqa: E402
from src.rpc import _helpers as helpers  # noqa: E402
from src.rpc import registration_notes  # noqa: E402
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity  # noqa: E402

_TAG = itertools.count()
_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


class _FakeS3:
    def __init__(self) -> None:
        self.puts: list[tuple[str, str, bool]] = []
        self.deleted_keys: list[str] = []
        self.deleted_prefixes: list[str] = []
        self.presigned: list[tuple[str, str | None]] = []

    async def put_object(self, key, data, content_type="application/octet-stream", *, public=False):
        self.puts.append((key, content_type, public))
        return True

    async def delete_object(self, key):
        self.deleted_keys.append(key)
        return True

    async def delete_prefix(self, prefix, *, keep=None):
        self.deleted_prefixes.append(prefix)
        return 1

    async def generate_presigned_url(self, key, expires_in=3600, *, content_disposition=None):
        self.presigned.append((key, content_disposition))
        return f"https://s3.test/{key}?sig"


def _grant(workspace_id: int, *perms: str) -> list[dict]:
    return [
        {
            "workspace_id": workspace_id,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": p.split(".")[0], "action": p.split(".")[1]} for p in perms],
        }
    ]


class RegistrationNotesRpc(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"regnote-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            workspace = models.Workspace(slug=tag, name=tag)
            s.add(workspace)
            await s.flush()
            tournaments = [
                models.Tournament(
                    workspace_id=workspace.id, name=f"{tag}-{i}", slug=f"{tag}-{i}", status=enums.TournamentStatus.LIVE
                )
                for i in range(2)
            ]
            s.add_all(tournaments)
            users = [models.AuthUser(email=f"{tag}-{i}@t.test", username=f"{tag}-{i}") for i in range(2)]
            s.add_all(users)
            await s.flush()
            node = models.FlowNode(tournament_id=tournaments[0].id, kind="registration", name="R", status="live")
            s.add(node)
            registration = models.Registration(tournament_id=tournaments[0].id, display_name="p1")
            foreign = models.Registration(tournament_id=tournaments[1].id, display_name="p2")
            s.add_all([registration, foreign])
            await s.flush()
            team = models.RegistrationTeam(
                tournament_id=tournaments[0].id,
                registration_node_id=node.id,
                workspace_id=workspace.id,
                name="Alpha",
                name_normalized="alpha",
            )
            s.add(team)
            await s.commit()
            self.ws, self.tid = workspace.id, tournaments[0].id
            self.author, self.colleague = users[0].id, users[1].id
            self.user_ids = [u.id for u in users]
            self.reg, self.foreign_reg, self.team = registration.id, foreign.id, team.id
        self.s3 = _FakeS3()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.ws))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id.in_(self.user_ids)))
            await s.commit()
        await self.engine.dispose()

    async def call(self, subject: str, user_id: int, perms: tuple[str, ...], **data) -> dict:
        broker = CapturingBroker()
        registration_notes.register(broker, SimpleNamespace(exception=lambda *a, **k: None))

        async def fake_get_s3():
            return self.s3

        identity = make_identity(user_id=user_id, workspaces=_grant(self.ws, *perms))
        async with self.Session() as session:
            with (
                patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
                patch.object(registration_notes, "get_s3", fake_get_s3),
            ):
                return await broker.handlers[subject]({"identity": identity, "id": self.tid, **data}, None)

    async def create(self, user_id: int, perms: tuple[str, ...], **target) -> dict:
        return await self.call(
            "rpc.tournament.regnote_create", user_id, perms, payload={"body": "Checked **discord**", **target}
        )

    async def upload(self, note_id: int, filename: str, user_id: int | None = None) -> dict:
        return await self.call(
            "rpc.tournament.regnote_attachment_upload",
            user_id or self.author,
            ("registration.update",),
            note_id=note_id,
            filename=filename,
            content_type="application/octet-stream",
            content_b64=_PNG,
        )

    async def test_author_writes_attaches_and_reads_back(self) -> None:
        created = await self.create(self.author, ("registration.update",), registration_id=self.reg)
        self.assertTrue(created["ok"], created)
        note_id = created["data"]["id"]

        uploaded = await self.upload(note_id, "C:\\shots\\Proof.PNG")
        self.assertTrue(uploaded["ok"], uploaded)
        [attachment] = uploaded["data"]["attachments"]
        self.assertEqual(("Proof.PNG", "image/png"), (attachment["filename"], attachment["content_type"]))
        [(key, content_type, public)] = self.s3.puts
        self.assertTrue(key.startswith(f"registration-notes/{self.tid}/{note_id}/"))
        self.assertEqual(("image/png", False), (content_type, public))

        listed = await self.call(
            "rpc.tournament.regnote_list",
            self.colleague,
            ("registration.read",),
            query={"registration_id": [str(self.reg)]},
        )
        self.assertTrue(listed["ok"], listed)
        [note] = listed["data"]
        self.assertEqual(("Checked **discord**", 1), (note["body"], len(note["attachments"])))
        self.assertIsNotNone(note["author_username"])

        url = await self.call(
            "rpc.tournament.regnote_attachment_url",
            self.colleague,
            ("registration.read",),
            note_id=note_id,
            attachment_id=attachment["id"],
        )
        self.assertTrue(url["ok"], url)
        self.assertEqual([(key, "inline; filename*=UTF-8''Proof.PNG")], self.s3.presigned)

        counts = await self.call("rpc.tournament.regnote_counts", self.colleague, ("team.read",))
        self.assertEqual({str(self.reg): 1}, counts["data"]["registrations"])

    async def test_only_the_author_edits_and_a_colleague_deletes_only_with_the_delete_grant(self) -> None:
        note_id = (await self.create(self.author, ("registration.update",), registration_id=self.reg))["data"]["id"]
        await self.upload(note_id, "proof.pdf")

        edit = await self.call(
            "rpc.tournament.regnote_update",
            self.colleague,
            ("registration.update",),
            note_id=note_id,
            payload={"body": "rewritten"},
        )
        self.assertEqual("forbidden", edit["error"]["code"])
        delete = await self.call(
            "rpc.tournament.regnote_delete", self.colleague, ("registration.update",), note_id=note_id
        )
        self.assertEqual("forbidden", delete["error"]["code"])
        self.assertEqual([], self.s3.deleted_prefixes)

        edited = await self.call(
            "rpc.tournament.regnote_update",
            self.author,
            ("registration.update",),
            note_id=note_id,
            payload={"body": "rewritten"},
        )
        self.assertEqual("rewritten", edited["data"]["body"])
        self.assertIsNotNone(edited["data"]["edited_at"])

        deleted = await self.call(
            "rpc.tournament.regnote_delete",
            self.colleague,
            ("registration.read", "registration.delete"),
            note_id=note_id,
        )
        self.assertTrue(deleted["ok"], deleted)
        self.assertEqual([f"registration-notes/{self.tid}/{note_id}/"], self.s3.deleted_prefixes)
        async with self.Session() as s:
            self.assertEqual(
                0,
                await s.scalar(
                    sa.select(sa.func.count())
                    .select_from(models.RegistrationNoteAttachment)
                    .where(models.RegistrationNoteAttachment.note_id == note_id)
                ),
            )

    async def test_disallowed_type_and_the_sixth_file_never_reach_s3(self) -> None:
        note_id = (await self.create(self.author, ("registration.update",), registration_id=self.reg))["data"]["id"]
        refused = await self.upload(note_id, "page.html")
        self.assertEqual("unprocessable", refused["error"]["code"])
        self.assertEqual([], self.s3.puts)

        for i in range(5):
            self.assertTrue((await self.upload(note_id, f"{i}.png"))["ok"])
        sixth = await self.upload(note_id, "6.png")
        self.assertEqual("unprocessable", sixth["error"]["code"])
        self.assertEqual(5, len(self.s3.puts))

        listed = await self.call(
            "rpc.tournament.regnote_list",
            self.author,
            ("registration.read",),
            query={"registration_id": [str(self.reg)]},
        )
        first_id = listed["data"][0]["attachments"][0]["id"]
        removed = await self.call(
            "rpc.tournament.regnote_attachment_delete",
            self.author,
            ("registration.update",),
            note_id=note_id,
            attachment_id=first_id,
        )
        self.assertTrue(removed["ok"], removed)
        self.assertEqual(4, len(removed["data"]["attachments"]))
        self.assertEqual([self.s3.puts[0][0]], self.s3.deleted_keys)

    async def test_team_notes_need_the_team_grant(self) -> None:
        refused = await self.create(self.author, ("registration.update",), registration_team_id=self.team)
        self.assertEqual("forbidden", refused["error"]["code"])
        created = await self.create(self.author, ("team.update",), registration_team_id=self.team)
        self.assertTrue(created["ok"], created)
        listed = await self.call(
            "rpc.tournament.regnote_list",
            self.colleague,
            ("registration.read",),
            query={"registration_team_id": [str(self.team)]},
        )
        self.assertEqual("forbidden", listed["error"]["code"])

    async def test_a_target_in_another_tournament_is_not_found(self) -> None:
        created = await self.create(self.author, ("registration.update",), registration_id=self.foreign_reg)
        self.assertEqual("not_found", created["error"]["code"])
