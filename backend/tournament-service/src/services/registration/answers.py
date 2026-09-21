"""The one answer pipeline: validate a submission, write it, project it back.

A registration answer has exactly three jobs, and they used to live in five
places: the ten-keyword ``create_registration``, the ``setattr``-per-key
``update_registration``, the per-field branches of ``lifecycle`` and the whole
of the deleted ``validation.py``. Here they are three methods over one flat
``{field key -> value}`` document, so adding a question to the form costs an
organizer a schema edit and nothing else.

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

from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.core.social import SocialProvider, normalize_social_handle
from shared.domain.forms import (
    IDENTITY_PROVIDERS,
    BattleTagParams,
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
from src import models
from src.domain.registration.utils import normalize_battle_tag, normalize_battle_tag_key
from src.services.registration._common import build_registration_roles
from src.services.registration.roles_rules import validate_roles

__all__ = (
    "RegistrationAnswerService",
    "answer_service",
    "custom_answers",
    "merge_custom_answers",
)

#: Builtin answer key -> the column it lands in. ``battle_tag`` (two columns),
#: ``identity_*`` (rows) and ``roles`` (rows) are handled on their own.
_ANSWER_COLUMNS: dict[str, str] = {
    "smurf_tags": "smurf_tags_json",
    "stream_pov": "stream_pov",
    "public_notes": "public_notes",
    "organizer_notes": "organizer_notes",
}

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
    can prove ownership, and ``battle_tag`` is Battle.net's handle under its own
    builtin key.
    """
    if field.key == "battle_tag":
        return SocialProvider.BATTLENET if BattleTagParams.model_validate(field.params).require_verified else None
    provider = identity_provider(field.key)
    if provider is None:
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
        hero_catalog: HeroCatalog | None,
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
        """
        normalized = normalize_answers(schema, answers, partial=partial, enforce_required=enforce_required)
        values = normalized.values
        errors: list[FieldError] = list(normalized.errors)

        roles_field = schema.builtin("roles")
        if roles_field is not None and "roles" in values:
            errors.extend(
                validate_roles(
                    roles_field,
                    values["roles"],
                    subrole_catalog=await resolve_subrole_catalog(session, workspace_id),
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
    ) -> list[FieldError]:
        """``require_verified`` fields checked against the registrant's OAuth rows.

        Ownership of a handle is provable only through OAuth (see
        identity-service), so a submission with no linked player cannot satisfy a
        gated field at all. ``require_verified`` implies the field is required:
        gated-and-blank is ``not_verified``, not a silent pass.
        """
        gated: list[tuple[str, str, str]] = []
        errors: list[FieldError] = []
        for field in visible_fields(schema, answers):
            provider = _verified_provider(field)
            if provider is None or (partial and field.key not in answers):
                continue
            handle = values.get(field.key)
            if not handle:
                errors.append(_not_verified(field.key))
                continue
            gated.append((field.key, provider, normalize_social_handle(provider, str(handle))))

        if not gated:
            return errors
        if player_id is None:
            errors.extend(_not_verified(key) for key, _, _ in gated)
            return errors

        verified = await self._verified_handles(
            session, player_id=player_id, providers={provider for _, provider, _ in gated}
        )
        errors.extend(
            _not_verified(key) for key, provider, handle in gated if handle not in verified.get(provider, frozenset())
        )
        return errors

    async def _verified_handles(
        self,
        session: AsyncSession,
        *,
        player_id: int,
        providers: set[str],
    ) -> dict[str, set[str]]:
        # Multi-column projection over one player's verified handles — a
        # row-tuple read, not a CRUD fetch, so it stays here.
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
        registration: models.BalancerRegistration,
        values: Mapping[str, Any],
        *,
        schema: FormSchema,
        hero_catalog: HeroCatalog | None,
    ) -> None:
        """Write validated answers onto a registration (and its child rows).

        Nothing is flushed or committed: the caller owns the transaction, which
        is what lets the team flows land a registration and its team slot
        together.
        """
        if "battle_tag" in values:
            tag = normalize_battle_tag(values["battle_tag"])
            registration.battle_tag = tag
            registration.battle_tag_normalized = normalize_battle_tag_key(tag)
        for key, column in _ANSWER_COLUMNS.items():
            if key not in values:
                continue
            value = values[key]
            setattr(registration, column, bool(value) if column == "stream_pov" else (value or None))
        self._apply_identities(registration, values, schema=schema)
        if "roles" in values:
            self._apply_roles(registration, values["roles"] or [], schema=schema, hero_catalog=hero_catalog)
        custom = custom_answers(values)
        if custom:
            registration.custom_fields_json = merge_custom_answers(registration.custom_fields_json, custom) or None

    def _apply_identities(
        self,
        registration: models.BalancerRegistration,
        values: Mapping[str, Any],
        *,
        schema: FormSchema,
    ) -> None:
        """One ``registration_identity`` row per provider the form asks about.

        Upserted by provider, and DELETED when the answer is present-and-blank:
        an identity the registrant removed must leave the table, not linger where
        ``team_eligibility`` and the stream targets still read it.
        """
        rows = {row.provider: row for row in registration.identities}
        for provider in IDENTITY_PROVIDERS:
            key = identity_key(provider)
            if key not in values or schema.field(key) is None:
                continue
            handle = values[key]
            row = rows.get(provider)
            if not handle:
                if row is not None:
                    registration.identities.remove(row)
                continue
            if row is None:
                registration.identities.append(
                    models.BalancerRegistrationIdentity(
                        provider=provider,
                        handle=handle,
                        handle_normalized=normalize_social_handle(provider, handle),
                    )
                )
            else:
                row.handle = handle
                row.handle_normalized = normalize_social_handle(provider, handle)

    def _apply_roles(
        self,
        registration: models.BalancerRegistration,
        roles: list[Any],
        *,
        schema: FormSchema,
        hero_catalog: HeroCatalog | None,
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
            hero_catalog=hero_catalog,
            max_heroes=params.top_heroes.max,
            mode=flex_role_mode_from_schema(schema),
        )
        existing = {row.role: row for row in registration.roles}
        merged: list[models.BalancerRegistrationRole] = []
        for entry in entries:
            row = existing.get(entry.role)
            if row is None:
                merged.append(entry)
                continue
            row.subrole = entry.subrole
            row.is_primary = entry.is_primary
            row.priority = entry.priority
            if hero_catalog is not None:
                row.hero_entries = entry.hero_entries
            merged.append(row)
        # Slice assignment, not rebinding: the rows this drops must go through
        # the delete-orphan cascade rather than being detached from the list.
        registration.roles[:] = merged

    def answers_of(self, registration: models.BalancerRegistration) -> dict[str, Any]:
        """The flat answer document a registration reads back as.

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
        for identity in registration.__dict__.get("identities") or ():
            out[identity_key(identity.provider)] = identity.handle
        for key, value in (getattr(registration, "custom_fields_json", None) or {}).items():
            if value is not None:
                out[key] = value
        return out


def _not_verified(field: str) -> FieldError:
    return FieldError(field=field, code=ErrorCode.NOT_VERIFIED.value, msg=_NOT_VERIFIED_MSG)


answer_service = RegistrationAnswerService()
