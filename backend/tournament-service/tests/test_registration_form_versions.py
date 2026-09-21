"""Registration form versions: when a save appends one, and who is left behind.

Two layers, because the interesting rules split cleanly:

* the append-or-not decision and the stale-count predicate are pure, so they run
  against fake sessions and always execute;
* the one-flush insert of a form together with its version #1 -- the reason
  ``current_version_id`` is nullable and the relationship carries
  ``post_update=True`` -- can only be proven against a real database, so those
  tests take ``db_session`` and SKIP when Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from shared.core import enums  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.forms import (  # noqa: E402
    Condition,
    FormField,
    FormSchema,
    FormSection,
    default_schema,
)
from shared.models.registration.registration import BalancerRegistration  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from src.schemas.registration_form import RegistrationFormUpsert  # noqa: E402
from src.services.registration.form_service import (  # noqa: E402
    _schema_field_error,
    form_service,
    parse_form_schema,
)


def _schema_with_vk() -> FormSchema:
    """``default_schema()`` plus one custom question in the ``details`` section."""
    changed = default_schema()
    changed.sections[2].fields.append(FormField(key="vk", kind="url", label="VK"))
    return changed


# ── the schema an organizer POSTs: refusals name the offending path ──────────


def _errors_of(raw: object) -> list[dict[str, Any]]:
    """``ApiHTTPException`` serializes its ``ApiExc`` list on construction, so the
    wire shape is what a caller actually sees."""
    with pytest.raises(ApiHTTPException) as caught:
        parse_form_schema(raw)
    return list(caught.value.detail)


def test_a_cross_field_invariant_names_the_field_it_is_about() -> None:
    """``visible_when`` pointing forward is raised by ``FormSchema``'s model
    validator, so pydantic reports it at the model ROOT with an empty ``loc`` and
    the path folded into the message. The builder highlights a field from
    ``ApiExc.field``, so the path has to be lifted back out -- otherwise every
    multi-field rule (duplicate keys, builtin params, fixed visibility) answers
    with a blank field and an English sentence."""
    forward = FormSchema.model_construct(
        schema_version=1,
        sections=[
            FormSection(
                key="details",
                fields=[
                    FormField(key="why", kind="text", label="Why", visible_when=Condition(field="later", op="truthy")),
                    FormField(key="later", kind="checkbox", label="Later"),
                ],
            )
        ],
    ).model_dump(mode="json")

    errors = _errors_of(forward)

    assert len(errors) == 1
    assert errors[0]["code"] == "schema_invalid"
    assert errors[0]["field"] == "sections[0].fields[0].visible_when"
    assert errors[0]["msg"] == "must reference an earlier field"


def test_a_per_field_type_error_keeps_its_own_location() -> None:
    """The ``loc`` path is authoritative when pydantic supplies one."""
    errors = _errors_of({"sections": [{"key": "details", "fields": [{"key": "why", "kind": "telepathy"}]}]})

    assert [e["field"] for e in errors] == ["sections.0.fields.0.kind"]
    assert errors[0]["code"] == "schema_invalid"


def test_an_invariant_without_a_path_keeps_its_whole_message() -> None:
    """Guard for a future invariant that names no path: the message must survive
    whole rather than lose its first clause to a field it never identified."""
    error = _schema_field_error({"loc": (), "msg": "Value error, the form is haunted"})

    assert error.field == ""
    assert error.msg == "the form is haunted"


# ── pure: dedupe and the stale predicate ────────────────────────────────────


class _Scalar:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """Only what ``apply_schema`` touches: the max-number read, and the flush."""

    def __init__(self, latest_number: int | None) -> None:
        self._latest_number = latest_number
        self.flushes = 0

    async def execute(self, _statement: Any) -> _Scalar:
        return _Scalar(self._latest_number)

    async def flush(self) -> None:
        self.flushes += 1


class _CapturingSession:
    """Records the statement ``stale_count`` builds instead of running it."""

    def __init__(self) -> None:
        self.statement: Any = None

    async def scalar(self, statement: Any) -> int:
        self.statement = statement
        return 3


def _form_stub(schema: FormSchema | None, *, form_id: int = 1) -> SimpleNamespace:
    version = None if schema is None else SimpleNamespace(schema_json=schema.model_dump(mode="json"))
    return SimpleNamespace(id=form_id, current_version=version, current_version_id=None, tournament_id=7)


def test_an_identical_schema_appends_no_version() -> None:
    """Dedupe is on canonical JSON, and the STORED document is re-validated first:
    a version written by the migration's own converter must compare equal to the
    same form round-tripped through today's model, or every toggle-only save
    would orphan every existing answer behind a cosmetic new version."""
    form = _form_stub(default_schema())
    session = _FakeSession(latest_number=1)

    version = asyncio.run(form_service.apply_schema(session, form, default_schema(), actor_user_id=None))

    assert version is form.current_version
    assert session.flushes == 0


def test_a_changed_schema_appends_the_next_number() -> None:
    form = _form_stub(default_schema())
    session = _FakeSession(latest_number=4)

    version = asyncio.run(form_service.apply_schema(session, form, _schema_with_vk(), actor_user_id=99))

    assert version.number == 5
    assert version.form_id == form.id
    assert version.created_by == 99
    assert form.current_version is version
    # One flush, because the version INSERT and the form's pointer UPDATE are the
    # same flush -- ``post_update`` is what resolves the FK cycle inside it.
    assert session.flushes == 1


def test_the_first_version_of_a_brand_new_form_is_number_one() -> None:
    """``latest_number`` answers 0 for a form with no versions, so the caller
    needs no branch -- and a brand-new form must not start at 0."""
    form = _form_stub(None)
    session = _FakeSession(latest_number=None)

    version = asyncio.run(form_service.apply_schema(session, form, default_schema(), actor_user_id=None))

    assert version.number == 1


def test_stale_count_asks_for_live_rows_on_a_different_version() -> None:
    """``IS DISTINCT FROM``, not ``!=``: a legacy row whose ``form_version_id`` is
    NULL is exactly the kind nobody can render, so it must count as stale. A plain
    inequality would evaluate to NULL and silently drop it from the badge."""
    form = _form_stub(default_schema())
    form.current_version_id = 12
    session = _CapturingSession()

    assert asyncio.run(form_service.stale_count(session, form)) == 3

    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "count(" in sql
    assert "tournament_id = " in sql
    assert "deleted_at IS NULL" in sql
    assert "form_version_id IS DISTINCT FROM" in sql


# ── integration: the form/version pair, written for real ────────────────────


async def _seed(session: Any) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"formver-{suffix}", name=f"Form versions {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Form versions {suffix}",
        slug=f"formver-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    await session.commit()
    return workspace.id, tournament.id


async def _drop(session: Any, workspace_id: int) -> None:
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_upsert_creates_a_version_only_when_the_schema_changes(db_session) -> None:
    async def _run() -> tuple[int, int, int, bool, int]:
        workspace_id, tournament_id = await _seed(db_session)
        try:
            form = await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=default_schema()),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            first_version_id = form.current_version_id
            first_number = form.current_version.number

            again = await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=default_schema(), show_ranks=True),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            toggled_version_id = again.current_version_id
            show_ranks = again.show_ranks

            changed = await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=_schema_with_vk()),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            return first_version_id, first_number, toggled_version_id, show_ranks, changed.current_version.number
        finally:
            await _drop(db_session, workspace_id)

    first_version_id, first_number, toggled_version_id, show_ranks, changed_number = asyncio.run(_run())

    assert first_number == 1
    # A toggle-only save keeps the version: otherwise every unrelated setting
    # change would mark every existing registration stale.
    assert toggled_version_id == first_version_id
    assert show_ranks is True
    assert changed_number == 2


def test_stale_count_counts_live_registrations_on_older_versions(db_session) -> None:
    async def _run() -> int:
        workspace_id, tournament_id = await _seed(db_session)
        try:
            form = await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=default_schema()),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            version_one = form.current_version_id
            db_session.add_all(
                [
                    BalancerRegistration(
                        tournament_id=tournament_id,
                        display_name="live-a",
                        status="approved",
                        form_version_id=version_one,
                    ),
                    BalancerRegistration(
                        tournament_id=tournament_id,
                        display_name="live-b",
                        status="approved",
                        form_version_id=version_one,
                    ),
                    BalancerRegistration(
                        tournament_id=tournament_id,
                        display_name="withdrawn",
                        status="approved",
                        form_version_id=version_one,
                        deleted_at=datetime.now(UTC),
                    ),
                ]
            )
            await db_session.commit()

            bumped = await form_service.upsert(
                db_session,
                tournament_id,
                RegistrationFormUpsert(form_schema=_schema_with_vk()),
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            assert bumped.current_version_id != version_one
            return await form_service.stale_count(db_session, bumped)
        finally:
            await _drop(db_session, workspace_id)

    # The soft-deleted row is NOT counted: the badge is about registrations an
    # organizer can still act on.
    assert asyncio.run(_run()) == 2
