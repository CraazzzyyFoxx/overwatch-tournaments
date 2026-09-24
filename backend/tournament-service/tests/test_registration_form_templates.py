"""Workspace registration-form templates: the library, and the two bridges.

The interesting claims are all about what a template does NOT do. Applying one
is a plain schema save on the tournament -- a version bump by the common rule --
and leaves nothing behind that points at the template, so a later template edit
cannot rewrite a live form. Saving one is a snapshot of the form's questions AT
THAT MOMENT, so a later form edit cannot rewrite the template. Both directions
are asserted here because "copy-on-apply" is a decision that only exists in
these two tests.

The name uniqueness check is the other half: the unique index is over
``(workspace_id, lower(name))``, and the service must answer that collision as a
structured 409 rather than letting an IntegrityError surface as a 500.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ["DEBUG"] = "true"

import pytest  # noqa: E402

from shared.core import enums  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.forms import FormField, FormSchema, default_schema  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    BalancerRegistrationForm,
    BalancerRegistrationFormTemplate,
)
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from src.rpc import _helpers as helpers  # noqa: E402
from src.rpc import registration_admin  # noqa: E402
from src.schemas.registration_form import (  # noqa: E402
    RegistrationFormTemplateUpsert,
    RegistrationFormUpsert,
)
from src.services.registration.form_service import form_service  # noqa: E402
from src.services.registration.templates import template_service  # noqa: E402


def _schema_with(key: str) -> FormSchema:
    """``default_schema()`` plus one custom question in the ``details`` section."""
    changed = default_schema()
    changed.sections[2].fields.append(FormField(key=key, kind="text", label=key.upper()))
    return changed


def _keys(schema_json: Any) -> set[str]:
    return {field["key"] for section in schema_json["sections"] for field in section["fields"]}


#: Identity/bookkeeping columns, excluded when two forms are compared for "same
#: settings". Everything else on the mapper is a toggle and is compared, so a
#: newly added setting is covered without editing this test.
_FORM_IDENTITY_COLUMNS = frozenset(
    {"id", "tournament_id", "workspace_id", "current_version_id", "created_at", "updated_at"}
)


def _toggles(form: Any) -> dict[str, Any]:
    return {
        attr.key: getattr(form, attr.key)
        for attr in sa.inspect(BalancerRegistrationForm).mapper.column_attrs
        if attr.key not in _FORM_IDENTITY_COLUMNS
    }


async def _seed(session: Any) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"formtpl-{suffix}", name=f"Form templates {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Form templates {suffix}",
        slug=f"formtpl-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    await session.commit()
    return workspace.id, tournament.id


async def _drop(session: Any, workspace_id: int) -> None:
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_create_list_update_delete_round_trip(db_session) -> None:
    async def _run() -> tuple[list[str], set[str], str, set[str], int]:
        workspace_id, _ = await _seed(db_session)
        try:
            created = await template_service.create(
                db_session,
                workspace_id=workspace_id,
                body=RegistrationFormTemplateUpsert(name="Open Cup", form_schema=default_schema()),
                actor_user_id=None,
            )
            listed = await template_service.list(db_session, workspace_id=workspace_id)
            listed_names = [row.name for row in listed]
            listed_keys = _keys(listed[0].schema_json)

            updated = await template_service.update(
                db_session,
                workspace_id=workspace_id,
                template_id=created.id,
                body=RegistrationFormTemplateUpsert(name="Open Cup 2026", form_schema=_schema_with("vk")),
                actor_user_id=None,
            )
            updated_name = updated.name
            updated_keys = _keys(updated.schema_json)

            await template_service.delete(db_session, workspace_id=workspace_id, template_id=created.id)
            remaining = len(await template_service.list(db_session, workspace_id=workspace_id))
            return listed_names, listed_keys, updated_name, updated_keys, remaining
        finally:
            await _drop(db_session, workspace_id)

    listed_names, listed_keys, updated_name, updated_keys, remaining = asyncio.run(_run())

    assert listed_names == ["Open Cup"]
    assert "vk" not in listed_keys
    assert updated_name == "Open Cup 2026"
    # The update replaces the question set wholesale, name and schema together.
    assert "vk" in updated_keys
    assert remaining == 0


def test_a_name_differing_only_in_case_is_refused(db_session) -> None:
    """The unique index is over ``lower(name)``, so "open cup" and "Open Cup" are
    the same template. The refusal must be the structured 409 the frontend maps,
    not the 500 an escaping IntegrityError would produce."""

    async def _run() -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
        workspace_id, _ = await _seed(db_session)
        try:
            first = await template_service.create(
                db_session,
                workspace_id=workspace_id,
                body=RegistrationFormTemplateUpsert(name="Open Cup", form_schema=default_schema()),
                actor_user_id=None,
            )
            with pytest.raises(ApiHTTPException) as caught:
                await template_service.create(
                    db_session,
                    workspace_id=workspace_id,
                    body=RegistrationFormTemplateUpsert(name="open CUP", form_schema=default_schema()),
                    actor_user_id=None,
                )
            create_detail = list(caught.value.detail)
            create_status = caught.value.status_code

            # Renaming a second template onto the first's name collides the same way.
            second = await template_service.create(
                db_session,
                workspace_id=workspace_id,
                body=RegistrationFormTemplateUpsert(name="Closed Cup", form_schema=default_schema()),
                actor_user_id=None,
            )
            with pytest.raises(ApiHTTPException) as renamed:
                await template_service.update(
                    db_session,
                    workspace_id=workspace_id,
                    template_id=second.id,
                    body=RegistrationFormTemplateUpsert(name="OPEN cup", form_schema=default_schema()),
                    actor_user_id=None,
                )
            assert first.id != second.id
            return create_detail, create_status, list(renamed.value.detail)
        finally:
            await _drop(db_session, workspace_id)

    create_detail, create_status, update_detail = asyncio.run(_run())

    assert create_status == 409
    assert create_detail[0]["code"] == "template_name_taken"
    assert create_detail[0]["field"] == "name"
    assert update_detail[0]["code"] == "template_name_taken"


def test_apply_bumps_the_form_version_and_leaves_the_template_untouched(db_session) -> None:
    """Copy-on-apply: the form gets a new version, the template row is not
    rewritten, and nothing on the form points back at it."""

    async def _run() -> tuple[int, int, set[str], dict[str, Any], int]:
        workspace_id, tournament_id = await _seed(db_session)
        try:
            form = await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=default_schema()),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            before_number = form.current_version.number

            template = await template_service.create(
                db_session,
                workspace_id=workspace_id,
                body=RegistrationFormTemplateUpsert(name="With VK", form_schema=_schema_with("vk")),
                actor_user_id=None,
            )
            template_before = dict(template.schema_json)

            applied = await template_service.apply(
                db_session,
                workspace_id=workspace_id,
                tournament_id=tournament_id,
                template_id=template.id,
                actor_user_id=None,
            )
            after_number = applied.current_version.number
            after_keys = _keys(applied.current_version.schema_json)

            # Re-read the template from the database rather than trusting the
            # identity-mapped instance: the assertion is that the row did not move.
            template_after = await db_session.scalar(
                sa.select(BalancerRegistrationFormTemplate.schema_json).where(
                    BalancerRegistrationFormTemplate.id == template.id
                )
            )
            assert template_after == template_before

            # Re-applying the same template is a no-op save: identical canonical
            # JSON appends no version.
            again = await template_service.apply(
                db_session,
                workspace_id=workspace_id,
                tournament_id=tournament_id,
                template_id=template.id,
                actor_user_id=None,
            )
            return before_number, after_number, after_keys, template_after, again.current_version.number
        finally:
            await _drop(db_session, workspace_id)

    before_number, after_number, after_keys, template_after, again_number = asyncio.run(_run())

    assert before_number == 1
    assert after_number == 2
    assert "vk" in after_keys
    assert "vk" in _keys(template_after)
    assert again_number == 2


def test_save_from_form_snapshots_the_current_schema(db_session) -> None:
    """A snapshot, not a link: the template holds what the form asked when it was
    saved, and a later form edit leaves it exactly where it was."""

    async def _run() -> tuple[set[str], set[str], int]:
        workspace_id, tournament_id = await _seed(db_session)
        try:
            await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=_schema_with("vk")),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            template = await template_service.save_from_form(
                db_session,
                workspace_id=workspace_id,
                tournament_id=tournament_id,
                name="Snapshot",
                actor_user_id=None,
            )
            snapshot_keys = _keys(template.schema_json)

            edited = await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=_schema_with("telegram")),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            assert "telegram" in _keys(edited.current_version.schema_json)

            after_edit = await db_session.scalar(
                sa.select(BalancerRegistrationFormTemplate.schema_json).where(
                    BalancerRegistrationFormTemplate.id == template.id
                )
            )
            return snapshot_keys, _keys(after_edit), edited.current_version.number
        finally:
            await _drop(db_session, workspace_id)

    snapshot_keys, after_edit_keys, form_version = asyncio.run(_run())

    assert "vk" in snapshot_keys
    # The form moved on; the template did not.
    assert after_edit_keys == snapshot_keys
    assert "telegram" not in after_edit_keys
    assert form_version == 2


def test_apply_to_a_tournament_with_no_form_creates_one(db_session) -> None:
    """Form rows are created lazily on the first save, so applying a template to
    a tournament nobody has configured yet IS that first save -- not a 404. The
    toggles must come out exactly as a plain first upsert leaves them, which is
    asserted against a real one rather than against copied literals."""

    async def _run() -> tuple[set[str], int, dict[str, Any], dict[str, Any]]:
        workspace_id, tournament_id = await _seed(db_session)
        try:
            template = await template_service.create(
                db_session,
                workspace_id=workspace_id,
                body=RegistrationFormTemplateUpsert(name="Fresh", form_schema=_schema_with("vk")),
                actor_user_id=None,
            )
            created = await template_service.apply(
                db_session,
                workspace_id=workspace_id,
                tournament_id=tournament_id,
                template_id=template.id,
                actor_user_id=None,
            )

            # The yardstick: a second tournament in the same workspace, given a
            # form the ordinary way. Whatever defaults that produces is what the
            # lazily created one must carry.
            baseline_tournament = Tournament(
                workspace_id=workspace_id,
                name=f"Baseline {uuid.uuid4().hex[:8]}",
                slug=f"baseline-{uuid.uuid4().hex[:8]}",
                status=enums.TournamentStatus.REGISTRATION,
            )
            db_session.add(baseline_tournament)
            await db_session.flush()
            baseline = await form_service.upsert(
                db_session,
                baseline_tournament.id,
                RegistrationFormUpsert(form_schema=default_schema()),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            return (
                _keys(created.current_version.schema_json),
                created.current_version.number,
                _toggles(created),
                _toggles(baseline),
            )
        finally:
            await _drop(db_session, workspace_id)

    keys, number, created_toggles, baseline_toggles = asyncio.run(_run())

    assert "vk" in keys
    assert number == 1
    assert created_toggles == baseline_toggles


def test_save_from_form_without_a_form_is_a_structured_404(db_session) -> None:
    """There is nothing to snapshot, and the refusal must carry a code the
    frontend can branch on rather than a bare sentence."""

    async def _run() -> tuple[int, list[dict[str, Any]]]:
        workspace_id, tournament_id = await _seed(db_session)
        try:
            with pytest.raises(ApiHTTPException) as caught:
                await template_service.save_from_form(
                    db_session,
                    workspace_id=workspace_id,
                    tournament_id=tournament_id,
                    name="Nothing to save",
                    actor_user_id=None,
                )
            return caught.value.status_code, list(caught.value.detail)
        finally:
            await _drop(db_session, workspace_id)

    status_code, detail = asyncio.run(_run())

    assert status_code == 404
    assert detail[0]["code"] == "form_not_configured"


def test_another_workspaces_template_is_invisible(db_session) -> None:
    """The tenancy boundary. Every lookup is scoped by the workspace the caller
    was authorized against, so a template id from a neighbouring workspace must
    read as "not found" -- never as a row to rename, delete or apply. The
    neighbour's row is re-read afterwards to prove nothing leaked through."""

    async def _run() -> tuple[list[tuple[int, str]], str, set[str], dict[str, Any] | None]:
        owner_ws, _ = await _seed(db_session)
        other_ws, other_tournament = await _seed(db_session)
        try:
            template = await template_service.create(
                db_session,
                workspace_id=owner_ws,
                body=RegistrationFormTemplateUpsert(name="Owned", form_schema=_schema_with("vk")),
                actor_user_id=None,
            )
            refusals: list[tuple[int, str]] = []

            async def _refused(coro) -> None:
                with pytest.raises(ApiHTTPException) as caught:
                    await coro
                refusals.append((caught.value.status_code, caught.value.detail[0]["code"]))

            await _refused(
                template_service.update(
                    db_session,
                    workspace_id=other_ws,
                    template_id=template.id,
                    body=RegistrationFormTemplateUpsert(name="Stolen", form_schema=default_schema()),
                    actor_user_id=None,
                )
            )
            await _refused(template_service.delete(db_session, workspace_id=other_ws, template_id=template.id))
            await _refused(
                template_service.apply(
                    db_session,
                    workspace_id=other_ws,
                    tournament_id=other_tournament,
                    template_id=template.id,
                    actor_user_id=None,
                )
            )

            # The neighbour is also not listed for the wrong workspace.
            assert [row.id for row in await template_service.list(db_session, workspace_id=other_ws)] == []

            survivor = await db_session.execute(
                sa.select(BalancerRegistrationFormTemplate.name, BalancerRegistrationFormTemplate.schema_json).where(
                    BalancerRegistrationFormTemplate.id == template.id
                )
            )
            name, schema_json = survivor.one()
            # The refused apply must also have left the other workspace's
            # tournament without a form: a 404 that still wrote is not a 404.
            leaked = await form_service.get_form(db_session, other_tournament)
            return refusals, name, _keys(schema_json), None if leaked is None else {"id": leaked.id}
        finally:
            await _drop(db_session, owner_ws)
            await _drop(db_session, other_ws)

    refusals, name, keys, leaked = asyncio.run(_run())

    assert refusals == [(404, "template_not_found")] * 3
    # The owner's row survived all three refusals untouched, name and questions.
    assert name == "Owned"
    assert "vk" in keys
    assert leaked is None


# ── RPC wiring: the path params and body keys the handlers read ─────────────
#
# Nothing else in the suite calls these six handlers, so a mistyped path param
# or body key would ship silently -- route parity only proves the subject
# exists, and the service tests above never see a request. Same shape as
# ``test_regstatus_rpc_wiring.py``, and written for the same gap.


_IDENTITY = make_identity(
    workspaces=[
        {
            "workspace_id": 1,
            "rbac_roles": [],
            "rbac_permissions": [
                {"resource": "registration_form", "action": "read"},
                {"resource": "registration_form", "action": "update"},
            ],
        }
    ],
)


def _template_row(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": 42,
        "workspace_id": 1,
        "name": "Open Cup",
        "schema_json": default_schema().model_dump(mode="json"),
        # A fresh row: ``updated_at`` stays NULL until the first edit (``onupdate``).
        "created_at": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
        "updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TemplateHandlersReadTheRequest(IsolatedAsyncioTestCase):
    async def _invoke(
        self,
        subject: str,
        data: dict[str, Any],
        *,
        service_fn: str,
        service_result: Any,
        extra_patches: tuple[Any, ...] = (),
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        broker = CapturingBroker()
        registration_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        calls: list[dict[str, Any]] = []

        async def stub(session, **kwargs):
            calls.append(kwargs)
            return service_result

        with ExitStack() as stack:
            stack.enter_context(patch.object(helpers.db, "async_session_maker", FakeSessionMaker()))
            stack.enter_context(patch.object(registration_admin.template_service, service_fn, stub))
            for extra in extra_patches:
                stack.enter_context(extra)
            envelope = await broker.handlers[subject](data, None)
        return envelope, calls

    async def test_list_serializes_every_template_for_the_path_workspace(self):
        envelope, calls = await self._invoke(
            "rpc.tournament.regform_template_list",
            {"identity": _IDENTITY, "workspace_id": 1},
            service_fn="list",
            service_result=[_template_row()],
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual([{"workspace_id": 1}], calls)
        self.assertEqual("Open Cup", envelope["data"][0]["name"])
        self.assertIn("sections", envelope["data"][0]["form_schema"])

    async def test_update_reads_the_template_id_from_the_path(self):
        envelope, calls = await self._invoke(
            "rpc.tournament.regform_template_update",
            {
                "identity": _IDENTITY,
                "workspace_id": 1,
                "template_id": 42,
                "payload": {"name": "Renamed", "form_schema": _schema_with("vk").model_dump(mode="json")},
            },
            service_fn="update",
            service_result=_template_row(name="Renamed"),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(42, calls[0]["template_id"])
        self.assertEqual(1, calls[0]["workspace_id"])
        self.assertEqual("Renamed", calls[0]["body"].name)
        # The schema arrives parsed, so a malformed question set is refused with
        # per-path `schema_invalid` errors before the service ever sees it.
        self.assertIn(
            "vk", {field.key for section in calls[0]["body"].form_schema.sections for field in section.fields}
        )

    async def test_delete_reads_the_template_id_from_the_path(self):
        envelope, calls = await self._invoke(
            "rpc.tournament.regform_template_delete",
            {"identity": _IDENTITY, "workspace_id": 1, "template_id": 42},
            service_fn="delete",
            service_result=None,
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual([{"workspace_id": 1, "template_id": 42}], calls)
        self.assertIsNone(envelope["data"])

    async def test_apply_reads_the_template_id_from_the_body_and_the_tournament_from_the_id(self):
        form = SimpleNamespace(
            id=5,
            tournament_id=9,
            workspace_id=1,
            auto_approve=False,
            require_open_profile=False,
            open_profile_scope="main",
            show_ranks=False,
            hide_registrations=False,
            max_participants=None,
            max_substitutes=0,
            require_subscription=False,
            subscription_stage="check_in",
            subscription_scope="player",
            team_rank_min=None,
            team_rank_max=None,
            team_max_rank_spread=None,
            team_unique_identity=False,
            team_require_discord_guild=False,
            current_version=SimpleNamespace(id=3, number=2, schema_json=_schema_with("vk").model_dump(mode="json")),
        )

        async def _workspace_of(_session, _tournament_id):
            return 1

        async def _blob(_session, _workspace_id):
            return {}

        async def _open(_session, _tournament_id):
            return True

        async def _stale(_session, _form):
            return 0

        envelope, calls = await self._invoke(
            "rpc.tournament.regform_template_apply",
            {"identity": _IDENTITY, "id": 9, "payload": {"template_id": 42}},
            service_fn="apply",
            service_result=form,
            extra_patches=(
                patch.object(registration_admin.auth, "get_tournament_workspace_id", _workspace_of),
                patch.object(
                    registration_admin.subscription_config.subscription_config_service,
                    "load_workspace_requirement_blob",
                    _blob,
                ),
                patch.object(registration_admin.windows_service, "load_registration_open", _open),
                patch.object(registration_admin.form_service, "stale_count", _stale),
            ),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(
            {"workspace_id": 1, "tournament_id": 9, "template_id": 42, "actor_user_id": 7},
            calls[0],
        )
        self.assertEqual(2, envelope["data"]["version_number"])

    async def test_save_from_form_reads_the_name_from_the_body(self):
        async def _workspace_of(_session, _tournament_id):
            return 1

        envelope, calls = await self._invoke(
            "rpc.tournament.regform_template_save_from_form",
            {"identity": _IDENTITY, "id": 9, "payload": {"name": "Snapshot"}},
            service_fn="save_from_form",
            service_result=_template_row(name="Snapshot"),
            extra_patches=(patch.object(registration_admin.auth, "get_tournament_workspace_id", _workspace_of),),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(
            {"workspace_id": 1, "tournament_id": 9, "name": "Snapshot", "actor_user_id": 7},
            calls[0],
        )
        self.assertEqual("Snapshot", envelope["data"]["name"])
