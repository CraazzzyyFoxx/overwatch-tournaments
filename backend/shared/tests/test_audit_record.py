from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from shared.observability.correlation import reset_correlation_id, set_correlation_id  # noqa: E402
from shared.services.audit import record_audit  # noqa: E402


class _Session:
    """Fakes the only three session methods the primitive could reach for.

    ``commit`` and ``flush`` are counters rather than no-ops because the tests
    below assert what ``record_audit`` does *not* do: owning the transaction is
    the caller's job, and a commit here would detach the audit row from the
    mutation it describes.
    """

    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = 0
        self.flushed = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1


class RecordAuditTests(IsolatedAsyncioTestCase):
    async def test_adds_row_to_callers_session_and_never_commits(self) -> None:
        session = _Session()

        row = await record_audit(
            session,
            action="role.assign",
            source="admin",
            actor=SimpleNamespace(id=7),
            workspace_id=42,
            entity_type="role",
            entity_id=3,
        )

        self.assertIs(row, session.added[0])
        self.assertEqual(1, len(session.added))
        self.assertEqual("role.assign", row.action)
        self.assertEqual("admin", row.source)
        self.assertEqual(42, row.workspace_id)
        self.assertEqual("role", row.entity_type)
        self.assertEqual(3, row.entity_id)
        # The whole atomicity guarantee: the caller's transaction stays open, so
        # a later rollback takes the audit row with it.
        self.assertEqual(0, session.committed)
        self.assertEqual(0, session.flushed)

    async def test_source_is_required_and_rejected_at_the_call(self) -> None:
        session = _Session()

        # Not a row with an empty column and not a runtime surprise inside the
        # transaction: the call itself is invalid, so no coroutine is created.
        with self.assertRaises(TypeError):
            record_audit(session, action="role.assign")  # type: ignore[call-arg]

        self.assertEqual([], session.added)

    async def test_machine_actor_is_distinguishable_from_a_human_one(self) -> None:
        session = _Session()

        machine = await record_audit(session, action="tournament.sync", source="scheduler")
        human = await record_audit(
            session,
            action="tournament.delete",
            source="admin",
            actor=SimpleNamespace(id=7),
        )

        self.assertIsNone(machine.actor_auth_user_id)
        self.assertEqual(7, human.actor_auth_user_id)

    async def test_api_key_actor_rewrites_admin_source(self) -> None:
        session = _Session()
        actor = SimpleNamespace(id=7, _credential_type="api_key", _api_key_public_id="pub")

        row = await record_audit(session, action="team.create", source="admin", actor=actor)

        self.assertEqual("api_key", row.source)
        self.assertEqual(7, row.actor_auth_user_id)

    async def test_a_discord_button_action_is_told_apart_from_a_session(self) -> None:
        """The bot acts as the linked account; the journal must still say it came from Discord."""
        session = _Session()
        actor = SimpleNamespace(id=7, _credential_type="discord")

        row = await record_audit(
            session, action="registration.check_in", source="player", actor=actor, actor_label="kira"
        )

        self.assertEqual(("discord", "kira (via Discord)", 7), (row.source, row.actor_label, row.actor_auth_user_id))

    async def test_session_actor_keeps_admin_source(self) -> None:
        session = _Session()
        actor = SimpleNamespace(id=7, _credential_type="access_token")

        row = await record_audit(session, action="team.create", source="admin", actor=actor)

        self.assertEqual("admin", row.source)

    async def test_client_supplied_strings_are_clipped_to_their_columns(self) -> None:
        session = _Session()

        row = await record_audit(
            session,
            action="session.revoke",
            source="admin",
            actor=SimpleNamespace(id=7),
            actor_label="a" * 400,
            entity_label="e" * 400,
            user_agent="Mozilla/5.0 " + "x" * 400,
            ip_address="f" * 80,
        )

        # Overlong values would raise DataError inside the mutation's own
        # transaction and fail the audited action itself.
        self.assertEqual(255, len(row.user_agent))
        self.assertEqual(255, len(row.actor_label))
        self.assertEqual(255, len(row.entity_label))
        self.assertEqual(45, len(row.ip_address))
        self.assertTrue(row.user_agent.startswith("Mozilla/5.0 "))

    async def test_omitted_optional_fields_stay_null(self) -> None:
        session = _Session()

        row = await record_audit(session, action="workspace.settings.update", source="admin")

        # NULL means "not recorded"; an empty dict would claim the caller
        # captured a before/after state and found it empty.
        self.assertIsNone(row.before_json)
        self.assertIsNone(row.after_json)
        self.assertIsNone(row.reason)
        self.assertIsNone(row.workspace_id)
        self.assertIsNone(row.entity_type)
        self.assertIsNone(row.entity_id)
        self.assertIsNone(row.entity_label)
        self.assertIsNone(row.actor_label)
        self.assertIsNone(row.ip_address)
        self.assertIsNone(row.user_agent)

    async def test_correlation_id_is_captured_when_the_context_has_one(self) -> None:
        session = _Session()
        token = set_correlation_id("corr-1")
        try:
            traced = await record_audit(session, action="role.create", source="admin")
        finally:
            reset_correlation_id(token)

        untraced = await record_audit(session, action="role.create", source="admin")

        self.assertEqual("corr-1", traced.correlation_id)
        # Outside a traced flow the column is simply NULL — never a crash.
        self.assertIsNone(untraced.correlation_id)
