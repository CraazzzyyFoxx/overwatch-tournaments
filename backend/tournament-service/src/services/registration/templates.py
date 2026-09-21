"""Workspace-level registration form templates: named schemas, copied on apply.

A template is a question set with a name and nothing else -- no toggles, no
tournament. Applying one is an ordinary schema save on the target tournament's
form (``form_service.apply_schema``), so it appends a version by exactly the
rule a hand edit follows, and NOTHING links the form back to the template
afterwards: editing a template later never rewrites a live form (copy-on-apply).

Names are unique per workspace, case-insensitively. The database says so --
``uq_balancer_registration_form_template_name`` over ``(workspace_id,
lower(name))`` -- but this module checks first anyway, so the ordinary collision
answers a structured 409 instead of letting an ``IntegrityError`` escape as a
500. The ``IntegrityError`` is caught too, for the race the read cannot close.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.domain.forms import FormSchema
from shared.repository import RegistrationFormTemplateRepository
from shared.services.realtime import Resource, Scope, emit
from src import models
from src.schemas.registration_form import (
    RegistrationFormTemplateUpsert,
    RegistrationFormUpsert,
)
from src.services.registration.form_service import form_service

__all__ = ("RegistrationFormTemplateService", "template_service")


def _fail(status_code: int, code: str, msg: str, *, field: str | None = None) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(msg=msg, code=code, field=field)])


def _name_taken(name: str) -> ApiHTTPException:
    return _fail(
        status.HTTP_409_CONFLICT,
        "template_name_taken",
        f"A template named '{name}' already exists in this workspace",
        field="name",
    )


def _clean_name(raw: str) -> str:
    """The stored form of a name. Stripped, because the unique index is over the
    stored value: leaving the whitespace in would let ``"Cup "`` and ``"Cup"``
    coexist and read as duplicates to everyone but Postgres."""
    name = raw.strip()
    if not name:
        raise _fail(status.HTTP_422_UNPROCESSABLE_ENTITY, "required", "Template name must not be blank", field="name")
    return name


class RegistrationFormTemplateService:
    """Reads and writes of ``registration_form_template``, plus the two bridges
    between a template and a tournament's form (apply / snapshot)."""

    def __init__(self) -> None:
        self.template_repo = RegistrationFormTemplateRepository()

    async def list(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
    ) -> Sequence[models.BalancerRegistrationFormTemplate]:
        return await self.template_repo.list_for_workspace(session, workspace_id)

    async def create(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        body: RegistrationFormTemplateUpsert,
        actor_user_id: int | None,
    ) -> models.BalancerRegistrationFormTemplate:
        """Store a new named schema. Commits internally."""
        name = _clean_name(body.name)
        await self._ensure_name_free(session, workspace_id=workspace_id, name=name)
        template = models.BalancerRegistrationFormTemplate(
            workspace_id=workspace_id,
            name=name,
            schema_json=body.form_schema.model_dump(mode="json"),
            created_by=actor_user_id,
        )
        try:
            await self.template_repo.create(session, template)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise _name_taken(name)
        await session.refresh(template)
        return template

    async def update(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        template_id: int,
        body: RegistrationFormTemplateUpsert,
        actor_user_id: int | None,
    ) -> models.BalancerRegistrationFormTemplate:
        """Rename and/or replace a template's questions. Commits internally.

        ``actor_user_id`` is taken for symmetry with :meth:`create`; the row
        records only its author (``created_by``), and an edit does not change who
        that was.
        """
        template = await self._require(session, workspace_id, template_id)
        name = _clean_name(body.name)
        await self._ensure_name_free(session, workspace_id=workspace_id, name=name, excluding=template.id)
        template.name = name
        template.schema_json = body.form_schema.model_dump(mode="json")
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise _name_taken(name)
        await session.refresh(template)
        return template

    async def delete(self, session: AsyncSession, *, workspace_id: int, template_id: int) -> None:
        """Drop a template. Nothing references it -- apply copies -- so no form
        anywhere changes."""
        template = await self._require(session, workspace_id, template_id)
        await self.template_repo.delete(session, template)
        await session.commit()

    async def apply(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        tournament_id: int,
        template_id: int,
        actor_user_id: int | None,
    ) -> models.BalancerRegistrationForm:
        """Copy a template's questions onto a tournament's form. Commits internally.

        A plain schema save: ``apply_schema`` dedupes on canonical JSON, so
        re-applying the template a form already carries appends nothing. The
        template is not recorded on the form -- a later edit of either side is
        invisible to the other.
        """
        template = await self._require(session, workspace_id, template_id)
        schema = FormSchema.model_validate(template.schema_json)

        form = await form_service.get_form(session, tournament_id)
        if form is None:
            # No form row yet: rows are created lazily on the first save, and this
            # IS a first save -- default toggles carrying the template's questions.
            return await form_service.upsert(
                session,
                tournament_id,
                RegistrationFormUpsert(form_schema=schema),
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )

        await form_service.apply_schema(session, form, schema, actor_user_id=actor_user_id)
        # Same signal a hand edit stages, for the same reason: open organizer tabs
        # are rendering the question set that just moved.
        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATION_FORM],
        )
        await session.commit()
        # Re-read, never ``refresh``: the commit expires the instance and a refresh
        # brings back the columns only, leaving ``current_version`` to lazy-load --
        # a ``MissingGreenlet`` for the caller that serializes the schema next.
        reloaded = await form_service.get_form(session, tournament_id)
        if reloaded is None:  # pragma: no cover -- committed one statement ago
            raise RuntimeError(f"registration form for tournament {tournament_id} vanished after commit")
        return reloaded

    async def save_from_form(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        tournament_id: int,
        name: str,
        actor_user_id: int | None,
    ) -> models.BalancerRegistrationFormTemplate:
        """Snapshot a tournament form's CURRENT questions under a new name.

        A snapshot, not a link: the template keeps what the form asked at this
        moment, and the form moving on afterwards leaves it alone.
        """
        form = await form_service.get_form(session, tournament_id)
        if form is None:
            raise _fail(
                status.HTTP_404_NOT_FOUND,
                "form_not_configured",
                "This tournament has no registration form to save as a template",
            )
        return await self.create(
            session,
            workspace_id=workspace_id,
            body=RegistrationFormTemplateUpsert(name=name, form_schema=form_service.schema_of(form)),
            actor_user_id=actor_user_id,
        )

    async def _require(
        self,
        session: AsyncSession,
        workspace_id: int,
        template_id: int,
    ) -> models.BalancerRegistrationFormTemplate:
        """The template, scoped to the workspace the caller was authorized against
        -- a bare id lookup would let one workspace edit another's."""
        template = await self.template_repo.get_for_workspace(session, workspace_id, template_id)
        if template is None:
            raise _fail(status.HTTP_404_NOT_FOUND, "template_not_found", "Registration form template not found")
        return template

    async def _ensure_name_free(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        name: str,
        excluding: int | None = None,
    ) -> None:
        clashing = await session.scalar(
            sa.select(models.BalancerRegistrationFormTemplate.id).where(
                models.BalancerRegistrationFormTemplate.workspace_id == workspace_id,
                sa.func.lower(models.BalancerRegistrationFormTemplate.name) == name.lower(),
            )
        )
        if clashing is not None and clashing != excluding:
            raise _name_taken(name)


template_service = RegistrationFormTemplateService()
