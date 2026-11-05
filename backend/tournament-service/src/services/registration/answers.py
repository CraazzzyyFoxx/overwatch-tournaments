"""The one answer pipeline: validate a submission, write it, project it back.

A registration answer has exactly three jobs, and here they are three methods
over one flat ``{field key -> value}`` document, so adding a question to the
form costs an organizer a schema edit and nothing else.

``validate`` runs the three stages -- normalisation, role composition, verified
identity -- and collects errors from ALL of them before raising, so a registrant
fixes their form once rather than once per rule.

``apply`` is the only writer of a registration's answers. It merges rather than
replaces wherever merging is what the caller meant: role rows keep the
``rank_value``/``is_active`` an organizer set (a player editing their roles must
not silently erase a rank they never saw), and custom answers merge over the
stored dict so a partial PATCH is not a wipe.

PRESENT-AND-EMPTY clears its target; ABSENT leaves it alone. That distinction is
why :func:`_explicit_clears` puts an explicit ``None`` back for a visible field
answered blank: ``normalize_answers`` drops it, and the writer must be able to
tell "the registrant emptied this" from "this PATCH did not mention it".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.core.social import VERIFIABLE_PROVIDERS, normalize_social_handle
from shared.disciplines import DISCIPLINES
from shared.domain.forms import (
    IDENTITY_PROVIDERS,
    ErrorCode,
    FieldError,
    FormField,
    FormSchema,
    IdentityParams,
    RolesParams,
    identity_key,
    identity_provider,
    is_builtin_key,
    normalize_answers,
    raise_field_errors,
    visible_fields,
)
from shared.domain.roster import flex_role_mode_from_schema
from shared.hero_catalog import HeroCatalog
from src.services.registration._common import build_registration_roles, only_role_answer, root_role_codes
from src.services.registration.roles_rules import validate_roles

__all__ = (
    "RegistrationAnswerService",
    "answer_service",
    "custom_answers",
    "merge_custom_answers",
)

#: Builtin answer key -> the profile column it lands in. ``identity_*`` (rows) and
#: ``roles`` (rows) are handled on their own, and so is ``reserve``: it lands on the registration ENTRY (a
#: registrant's availability is per intake).
_ANSWER_COLUMNS: dict[str, str] = {
    "stream_pov": "stream_pov",
    "public_notes": "public_notes",
    "organizer_notes": "organizer_notes",
}

#: The builtin answer an entry carries: key -> ``RegistrationEntry`` column.
ENTRY_ANSWER_COLUMNS: dict[str, str] = {"reserve": "is_reserve"}

#: Of those, the ones whose column is NOT NULL boolean: a blank answer is
#: ``False``, never ``NULL``.
_BOOL_COLUMNS = frozenset({"stream_pov"})

_NOT_VERIFIED_MSG = "This must match an OAuth-verified account linked to your profile."


def _is_blank(value: Any) -> bool:
    """An answer that says "nothing", as opposed to one that was never given."""
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == "" or value == []


def _explicit_clears(schema: FormSchema, answers: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, None]:
    """Visible fields this submission answered BLANK, as explicit ``None``.

    ``normalize_answers`` drops a blank optional answer, which is right for a
    document that never mentioned the question and wrong for one that emptied
    it. Restricted to VISIBLE fields so a question hidden by ``visible_when``
    stays dropped rather than clearing what it does not ask.
    """
    return {
        field.key: None
        for field in visible_fields(schema, answers)
        if field.key in answers and field.key not in values and _is_blank(answers[field.key])
    }


def _verified_provider(field: FormField) -> str | None:
    """The provider whose OAuth proof gates this field, or ``None`` when ungated.

    Derived from the field's own params rather than a hand-kept field->provider
    table: a question is verifiable exactly when the catalog says its provider
    can prove ownership. ``require_verified`` on a provider that cannot be
    verified (boosty, vk, ...) is meaningless and ignored.
    """
    provider = identity_provider(field.key)
    if provider is None or provider not in VERIFIABLE_PROVIDERS:
        return None
    return provider if IdentityParams.model_validate(field.params).require_verified else None


def custom_answers(values: Mapping[str, Any]) -> dict[str, Any]:
    """The organizer-defined answers of a validated document: everything that is
    not one of the builtin keys."""
    return {key: value for key, value in values.items() if not is_builtin_key(key)}


def merge_custom_answers(stored: Mapping[str, Any] | None, custom: Mapping[str, Any]) -> dict[str, Any]:
    """The stored custom answers with ``custom`` written over them.

    Merged, not replaced: a partial PATCH names only the questions it changes,
    and replacing wholesale would wipe the rest. A key answered BLANK is removed
    -- that is how the admin editor, which round-trips every definition, clears
    one.
    """
    merged = dict(stored or {})
    for key, value in custom.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


class RegistrationAnswerService:
    """Validate, write and project a registration's answers."""

    async def validate(
        self,
        session: AsyncSession,
        *,
        schema: FormSchema,
        answers: Mapping[str, Any],
        partial: bool,
        enforce_required: bool,
        player_id: int | None,
        workspace_id: int,
        discipline: str,
        hero_catalog: HeroCatalog | None,
        registration: models.Registration | None = None,
        entry: models.RegistrationEntry | None = None,
    ) -> dict[str, Any]:
        """The typed values ``answers`` reduces to, or ``422`` with every error.

        Three stages, all collected before anything is raised: per-field
        normalisation (pure, in ``shared.domain.forms``), the ``roles``
        composition rules, and the ``require_verified`` OAuth gate. Raising after
        stage one would make a registrant resubmit to discover the role error
        waiting behind it.

        ``enforce_required=False`` is the organizer path: blanks are allowed and
        the OAuth gate does not run, because the organizer authoring the row IS
        the authority the gate exists to substitute for.

        ``registration`` (with its ``entry`` in the node being written, if any) is the row an EDIT rewrites. A key the form does not ask
        that only repeats what ``answers_of`` reads back for it is dropped, not
        refused: the read reports every answer column (``reserve``/``stream_pov``
        are NOT NULL) and answers to questions a later version removed, so a
        client sending back the document it just read must not get
        ``unknown_field``. A CHANGED undeclared key still does.
        """
        if registration is not None:
            stored = self.answers_of(registration, entry)
            answers = {
                key: value
                for key, value in answers.items()
                if schema.field(key) is not None or key not in stored or stored[key] != value
            }
        role_codes = tuple(role.code for role in DISCIPLINES[discipline].rated_dimension.roles)
        implied = only_role_answer(role_codes)
        if implied is not None and not partial and schema.builtin("roles") is not None and not answers.get("roles"):
            # A one-role game asks no role question: the sign-up still plays that role, required question or not.
            answers = {**answers, "roles": implied}
        normalized = normalize_answers(schema, answers, partial=partial, enforce_required=enforce_required)
        values = normalized.values
        errors: list[FieldError] = list(normalized.errors)
        for field in schema.fields():
            if field.kind == "role_ranks" and isinstance(values.get(field.key), dict):
                unknown = tuple(sorted(set(values[field.key]) - set(role_codes)))
                if unknown:
                    errors.append(
                        FieldError(field.key, ErrorCode.INVALID_OPTION.value, "Not a known role.", {"values": unknown})
                    )

        roles_field = schema.builtin("roles")
        if roles_field is not None and "roles" in values:
            errors.extend(
                validate_roles(
                    roles_field,
                    values["roles"],
                    role_codes=role_codes,
                    subrole_catalog=await resolve_subrole_catalog(session, workspace_id, discipline=discipline),
                    hero_catalog=hero_catalog,
                )
            )

        if enforce_required:
            errors.extend(
                await self._verified_errors(
                    session,
                    schema=schema,
                    answers=answers,
                    values=values,
                    partial=partial,
                    player_id=player_id,
                    # A key that failed stage one is absent from ``values`` for a
                    # reason that is already reported. Without this the gate reads
                    # that absence as "answered blank" and adds a second, wrong
                    # verdict on the same field: ``invalid_format`` AND
                    # ``not_verified`` for one malformed handle.
                    errored_keys={error.field for error in normalized.errors},
                )
            )

        if errors:
            raise_field_errors(errors)

        values.update(_explicit_clears(schema, answers, values))
        return values

    async def _verified_errors(
        self,
        session: AsyncSession,
        *,
        schema: FormSchema,
        answers: Mapping[str, Any],
        values: Mapping[str, Any],
        partial: bool,
        player_id: int | None,
        errored_keys: frozenset[str] | set[str] = frozenset(),
    ) -> list[FieldError]:
        """``require_verified`` fields checked against the registrant's OAuth rows.

        Ownership of a handle is provable only through OAuth (see
        identity-service), so a submission with no linked player cannot satisfy a
        gated field at all. ``require_verified`` implies the field is required:
        gated-and-blank is ``not_verified``, not a silent pass.

        ``errored_keys`` are the fields normalisation already refused. They are
        skipped, not re-judged: an unreadable answer is not evidence about who
        owns it, and the registrant gets one verdict per field.

        An identity answer carries several handles: EVERY one of them must be
        verified. A smurf nobody proved ownership of is exactly what the gate
        exists to keep out, and "primary only" would let it in beside a verified
        main.
        """
        gated: list[tuple[str, str, list[str]]] = []
        errors: list[FieldError] = []
        for field in visible_fields(schema, answers):
            provider = _verified_provider(field)
            if provider is None or field.key in errored_keys or (partial and field.key not in answers):
                continue
            handles = values.get(field.key) or []
            if not handles:
                errors.append(_not_verified(field.key))
                continue
            gated.append((field.key, provider, [normalize_social_handle(provider, handle) for handle in handles]))

        if not gated:
            return errors
        if player_id is None:
            errors.extend(_not_verified(key) for key, _, _ in gated)
            return errors

        verified = await self._verified_handles(
            session, player_id=player_id, providers={provider for _, provider, _ in gated}
        )
        errors.extend(
            _not_verified(key)
            for key, provider, handles in gated
            if not set(handles) <= verified.get(provider, frozenset())
        )
        return errors

    async def _verified_handles(
        self,
        session: AsyncSession,
        *,
        player_id: int,
        providers: set[str],
    ) -> dict[str, set[str]]:
        # Analytical: a two-column projection over one player's verified handles.
        rows = (
            await session.execute(
                sa.select(models.SocialAccount.provider, models.SocialAccount.username_normalized).where(
                    models.SocialAccount.user_id == player_id,
                    models.SocialAccount.provider.in_(providers),
                    models.SocialAccount.is_verified.is_(True),
                )
            )
        ).all()
        by_provider: dict[str, set[str]] = {provider: set() for provider in providers}
        for provider, normalized in rows:
            if normalized:
                by_provider.setdefault(provider, set()).add(normalized)
        return by_provider

    def apply(
        self,
        registration: models.Registration,
        values: Mapping[str, Any],
        *,
        schema: FormSchema,
        hero_catalog: HeroCatalog | None,
        catalog_roles: Mapping[str, models.CatalogRole],
        entry: models.RegistrationEntry | None = None,
    ) -> None:
        """Write validated answers onto a registration (and its child rows).

        ``entry`` is the registration's participation in the node being written: the ``reserve`` answer lands there,
        so a write with no entry (a profile edit outside any node) leaves it alone.

        Nothing is flushed or committed: the caller owns the transaction, which
        is what lets the team flows land a registration and its team slot
        together.
        """
        for key, column in _ANSWER_COLUMNS.items():
            if key not in values:
                continue
            value = values[key]
            setattr(registration, column, bool(value) if column in _BOOL_COLUMNS else (value or None))
        if entry is not None:
            for key, column in ENTRY_ANSWER_COLUMNS.items():
                if key in values:
                    setattr(entry, column, bool(values[key]))
        self._apply_identities(registration, values, schema=schema)
        roots = root_role_codes(catalog_roles)
        # A NEW registration of a one-role game gets that role even when nothing asked (organizer and sheet rows
        # validate partially, so ``validate`` implied nothing). A stored row is edited, never re-seeded: its roles may
        # not even be loaded.
        if "roles" in values or (registration.id is None and len(roots) == 1):
            self._apply_roles(
                registration,
                values.get("roles") or [],
                schema=schema,
                hero_catalog=hero_catalog,
                catalog_roles=catalog_roles,
            )
        custom = custom_answers(values)
        if custom:
            registration.custom_fields_json = merge_custom_answers(registration.custom_fields_json, custom) or None

    def _apply_identities(
        self,
        registration: models.Registration,
        values: Mapping[str, Any],
        *,
        schema: FormSchema,
    ) -> None:
        """The ``registration_identity`` rows of every provider the form asks about.

        An answer is a LIST of handles, primary first: the rows are rewritten in
        place by position (so a promoted smurf is an UPDATE, not a
        delete-insert), surplus rows are dropped, and a present-and-blank answer
        removes the provider entirely -- an identity the registrant removed must
        leave the table, not linger where ``team_eligibility`` and the stream
        targets still read it. The positional/handle uniques are DEFERRED, so a
        swap mid-rewrite is fine.
        """
        rows_by_provider: dict[str, list[models.RegistrationIdentity]] = {}
        for row in registration.identities:
            rows_by_provider.setdefault(row.provider, []).append(row)
        for provider in IDENTITY_PROVIDERS:
            key = identity_key(provider)
            if key not in values or schema.field(key) is None:
                continue
            handles = values[key] or []
            rows = sorted(rows_by_provider.get(provider, ()), key=lambda row: row.position)
            for position, handle in enumerate(handles):
                normalized = normalize_social_handle(provider, handle)
                if position < len(rows):
                    rows[position].handle = handle
                    rows[position].handle_normalized = normalized
                else:
                    registration.identities.append(
                        models.RegistrationIdentity(
                            provider=provider,
                            position=position,
                            handle=handle,
                            handle_normalized=normalized,
                        )
                    )
            for surplus in rows[len(handles) :]:
                registration.identities.remove(surplus)

    def _apply_roles(
        self,
        registration: models.Registration,
        roles: list[Any],
        *,
        schema: FormSchema,
        hero_catalog: HeroCatalog | None,
        catalog_roles: Mapping[str, models.CatalogRole],
    ) -> None:
        """Replace the role set, KEEPING the rank of every role that survives.

        ``rank_value`` and ``is_active`` are organizer state (rank autofill, the
        admin editor, the sheet sync); the public form submits neither. Building
        fresh rows and assigning them would therefore blank every rank the moment
        a player reordered their roles — which is why the surviving rows are
        mutated in place instead.
        """
        roles_field = schema.builtin("roles")
        params = RolesParams.model_validate(roles_field.params) if roles_field is not None else RolesParams()
        entries = build_registration_roles(
            roles,
            catalog_roles=catalog_roles,
            role_codes=root_role_codes(catalog_roles),
            hero_catalog=hero_catalog,
            max_heroes=params.top_heroes.max,
            mode=flex_role_mode_from_schema(schema),
        )
        existing = {row.role: row for row in registration.roles}
        merged: list[models.RegistrationRole] = []
        for entry in entries:
            row = existing.get(entry.role)
            if row is None:
                merged.append(entry)
                continue
            row.catalog_role = entry.catalog_role
            row.dimension_id = entry.dimension_id
            row.is_primary = entry.is_primary
            row.priority = entry.priority
            if hero_catalog is not None:
                # Emptied off ``entry`` FIRST. Handing its live collection over
                # instead makes the backref cascade ``entry`` itself into the
                # session -- a second role row nothing owns, whose INSERT then
                # fails on ``registration_id`` NOT NULL and 500s the whole edit.
                heroes = list(entry.hero_entries)
                entry.hero_entries = []
                row.hero_entries = heroes
            merged.append(row)
        # Slice assignment, not rebinding: the rows this drops must go through
        # the delete-orphan cascade rather than being detached from the list.
        registration.roles[:] = merged

    def answers_of(
        self, registration: models.Registration, entry: models.RegistrationEntry | None = None
    ) -> dict[str, Any]:
        """The flat answer document a registration reads back as.

        ``entry`` adds the answers an entry carries (``reserve``); without one they are not part of the document.

        Every ``identity_<provider>`` answer is a list of handles, primary first
        (sorted by ``position`` rather than trusting the in-session order of a
        collection the writer just appended to).

        ``__dict__`` for ``identities`` for the same reason ``_reg_to_read`` uses
        it for the team: the relationship is documented as never lazy-loadable in
        async code, and a row that did not eager-load it has no identities to
        report rather than a ``MissingGreenlet``.
        """
        out: dict[str, Any] = {}
        for key, column in _ANSWER_COLUMNS.items():
            value = getattr(registration, column, None)
            if value is not None:
                out[key] = value
        if entry is not None:
            for key, column in ENTRY_ANSWER_COLUMNS.items():
                out[key] = getattr(entry, column)
        identities = sorted(registration.__dict__.get("identities") or (), key=lambda row: row.position)
        for identity in identities:
            out.setdefault(identity_key(identity.provider), []).append(identity.handle)
        for key, value in (getattr(registration, "custom_fields_json", None) or {}).items():
            if value is not None:
                out[key] = value
        return out


def _not_verified(field: str) -> FieldError:
    return FieldError(field=field, code=ErrorCode.NOT_VERIFIED.value, msg=_NOT_VERIFIED_MSG)


answer_service = RegistrationAnswerService()
