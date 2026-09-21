"""The tournament's registration form: its toggles, and its versioned schema.

One service owns both halves of a form save because they land in one
transaction: the flat toggles are overwritten in place, while the question set
is append-only. A save whose :meth:`FormSchema.canonical_json` matches the
current version writes NO version -- otherwise every unrelated toggle flip would
orphan the answers of every existing registration behind a new version number.

The ``registration_form`` <-> ``registration_form_version`` foreign keys form a
cycle, which is why ``current_version_id`` is nullable and the relationship
carries ``post_update=True``: a brand-new form and its version #1 are inserted
in ONE flush, then the pointer is UPDATEd in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.domain.forms import FieldError, FormSchema, raise_field_errors, schema_from_form
from shared.repository import RegistrationFormRepository, RegistrationFormVersionRepository
from shared.services.realtime import Resource, Scope, emit
from src import models
from src.schemas.registration_form import RegistrationFormUpsert

__all__ = ("RegistrationFormService", "form_service", "parse_form_schema")


#: What pydantic prepends to a ``ValueError`` raised inside a validator.
_VALUE_ERROR_PREFIX = "Value error, "


def _schema_field_error(error: Mapping[str, Any]) -> FieldError:
    """One pydantic error, keyed by the schema path it is about.

    A per-field error (a bad ``kind``, a bad ``max``) carries its path in ``loc``.
    A CROSS-field invariant does not: ``FormSchema``'s ``model_validator`` raises a
    plain ``ValueError``, which pydantic reports at the model root with an empty
    ``loc`` and the path folded into the message as ``"<path>: <detail>"``. Those
    are precisely the rules the builder most needs to point at -- duplicate keys,
    ``visible_when`` ordering, builtin params and fixed visibility -- so the path is
    lifted back out here rather than left for the client to parse out of English.
    """
    loc = error["loc"]
    msg = str(error["msg"])
    if loc:
        return FieldError(field=".".join(str(part) for part in loc), code="schema_invalid", msg=msg)
    detail = msg.removeprefix(_VALUE_ERROR_PREFIX)
    path, separator, remainder = detail.partition(": ")
    # No separator means an invariant that does not name a path; keep the whole
    # message rather than inventing one out of its first clause.
    return FieldError(field=path if separator else "", code="schema_invalid", msg=remainder if separator else detail)


def parse_form_schema(raw: object) -> FormSchema:
    """Validate a schema document, turning pydantic's errors into field errors.

    One ``schema_invalid`` ``FieldError`` per pydantic error, keyed by the offending
    schema path, so the builder can highlight what is wrong instead of showing one
    English sentence.
    """
    try:
        return FormSchema.model_validate(raw)
    except ValidationError as exc:
        raise_field_errors([_schema_field_error(error) for error in exc.errors()])


class RegistrationFormService:
    """Reads and writes of ``registration_form`` and its schema versions."""

    def __init__(self) -> None:
        self.form_repo = RegistrationFormRepository()
        self.version_repo = RegistrationFormVersionRepository()

    async def get_form(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerRegistrationForm | None:
        """The tournament's form with ``current_version`` eager-loaded.

        Eager on purpose: ``current_version`` is never lazy-loadable in async
        code, and every caller of this service reads the schema off it.
        """
        return await self.form_repo.get_by(
            session,
            options=[selectinload(models.BalancerRegistrationForm.current_version)],
            tournament_id=tournament_id,
        )

    def schema_of(self, form: models.BalancerRegistrationForm) -> FormSchema:
        """The form's current schema.

        A form with no version is a bug rather than a state to render around:
        every write path through this service creates version #1 with the form,
        and the migration backfilled one for every pre-existing row.
        """
        schema = schema_from_form(form)
        if schema is None:
            raise RuntimeError(f"registration form {form.id} has no current version")
        return schema

    async def apply_schema(
        self,
        session: AsyncSession,
        form: models.BalancerRegistrationForm,
        schema: FormSchema,
        *,
        actor_user_id: int | None,
    ) -> models.BalancerRegistrationFormVersion:
        """Point ``form`` at a version holding ``schema``, appending one if needed.

        Dedupe is on canonical JSON, and the STORED side is re-validated through
        ``FormSchema`` before comparing: a document written by an older schema
        version -- or by the migration's hand-rolled converter -- must compare
        equal to the same document round-tripped through today's model, or every
        save would append a cosmetic version.
        """
        current = form.current_version
        if current is not None and FormSchema.model_validate(current.schema_json).canonical_json() == (
            schema.canonical_json()
        ):
            return current

        version = models.BalancerRegistrationFormVersion(
            form_id=form.id,
            number=await self.version_repo.latest_number(session, form.id) + 1,
            schema_json=schema.model_dump(mode="json"),
            created_by=actor_user_id,
        )
        # Assigning THROUGH the relationship, not ``session.add``: the save-update
        # cascade enrols the version, and ``post_update`` then resolves the FK
        # cycle inside a single flush -- INSERT the version, UPDATE the form's
        # pointer. Two statements, one flush, no nullable window to observe.
        form.current_version = version
        await session.flush()
        return version

    async def save_schema(
        self,
        session: AsyncSession,
        form: models.BalancerRegistrationForm,
        schema: FormSchema,
        *,
        actor_user_id: int | None,
    ) -> models.BalancerRegistrationForm:
        """Persist ``schema`` on ``form`` and hand back the reloaded row. Commits.

        The whole tail of a schema save, shared by the form upsert and by
        applying a template: version the schema, tell open tabs, commit, re-read.
        Two call sites, one place to change the invalidation resource or the
        reload reasoning.
        """
        await self.apply_schema(session, form, schema, actor_user_id=actor_user_id)
        # Staged before the commit that owns the write: the rail persists the
        # row in this transaction and publishes it from after_commit. Until this
        # existed a form edit emitted nothing at all, so open tabs only learned
        # about it by accident, riding along with the next unrelated
        # registration event.
        await emit(
            session,
            scope=Scope.tournament(form.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATION_FORM],
        )
        tournament_id = form.tournament_id
        await session.commit()
        # Re-read rather than ``refresh``: the commit expires the instance, and a
        # refresh brings back the COLUMNS only -- leaving ``current_version`` to
        # lazy-load on the caller's first read, which in async code is a
        # ``MissingGreenlet``. Every caller serializes the schema straight after.
        reloaded = await self.get_form(session, tournament_id)
        if reloaded is None:  # pragma: no cover -- committed one statement ago
            raise RuntimeError(f"registration form for tournament {tournament_id} vanished after commit")
        return reloaded

    async def upsert(
        self,
        session: AsyncSession,
        tournament_id: int,
        body: RegistrationFormUpsert,
        *,
        workspace_id: int,
        actor_user_id: int | None,
    ) -> models.BalancerRegistrationForm:
        """Create-or-update the tournament's form. Commits internally.

        ``workspace_id`` is the tournament's already-resolved workspace (the RPC
        handler resolves it for the permission check anyway).

        ``require_subscription`` is written here because the toggle is the
        tournament's decision; the rule itself belongs to the workspace and is
        written through ``subscription_config.upsert_workspace_requirement``.
        """
        form = await self.get_form(session, tournament_id)

        if form is None:
            form = models.BalancerRegistrationForm(
                tournament_id=tournament_id,
                workspace_id=workspace_id,
                auto_approve=body.auto_approve,
                require_open_profile=body.require_open_profile,
                open_profile_scope=body.open_profile_scope,
                show_ranks=body.show_ranks,
                hide_registrations=body.hide_registrations,
                max_participants=body.max_participants,
                require_subscription=body.require_subscription,
                subscription_stage=body.subscription_stage.value,
                subscription_scope=body.subscription_scope,
                team_rank_min=body.team_rank_min,
                team_rank_max=body.team_rank_max,
                team_max_rank_spread=body.team_max_rank_spread,
                team_unique_identity=body.team_unique_identity,
                team_require_discord_guild=body.team_require_discord_guild,
                max_substitutes=body.max_substitutes,
            )
            await self.form_repo.create(session, form)
        else:
            form.auto_approve = body.auto_approve
            form.require_open_profile = body.require_open_profile
            form.open_profile_scope = body.open_profile_scope
            form.show_ranks = body.show_ranks
            form.hide_registrations = body.hide_registrations
            form.max_participants = body.max_participants
            form.require_subscription = body.require_subscription
            form.subscription_stage = body.subscription_stage.value
            form.subscription_scope = body.subscription_scope
            form.team_rank_min = body.team_rank_min
            form.team_rank_max = body.team_rank_max
            form.team_max_rank_spread = body.team_max_rank_spread
            form.team_unique_identity = body.team_unique_identity
            form.team_require_discord_guild = body.team_require_discord_guild
            form.max_substitutes = body.max_substitutes

        return await self.save_schema(session, form, body.form_schema, actor_user_id=actor_user_id)

    async def stale_count(
        self,
        session: AsyncSession,
        form: models.BalancerRegistrationForm,
    ) -> int:
        """Live registrations answering something other than the current version.

        ``IS DISTINCT FROM`` rather than ``!=`` so the legacy/manual rows whose
        ``form_version_id`` is NULL are counted as stale -- they are exactly the
        ones whose answers nobody can render against a known question set.
        """
        return (
            await session.scalar(
                sa.select(sa.func.count(models.BalancerRegistration.id)).where(
                    models.BalancerRegistration.tournament_id == form.tournament_id,
                    models.BalancerRegistration.deleted_at.is_(None),
                    models.BalancerRegistration.form_version_id.is_distinct_from(form.current_version_id),
                )
            )
            or 0
        )


form_service = RegistrationFormService()
