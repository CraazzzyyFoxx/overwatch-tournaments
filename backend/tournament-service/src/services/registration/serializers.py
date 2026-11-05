from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm.attributes import NO_VALUE

from shared import models
from shared.domain.forms import FormSchema, schema_from_form
from shared.domain.roster import PlayerRoster, RosterRole
from shared.registration_statuses import (
    StatusMeta,
    build_status_meta_from_model,
    build_unknown_status_meta,
)
from src import schemas
from src.schemas.admission import AdmissionRead
from src.schemas.registration_form import RegistrationFormRead, RegistrationFormTemplateRead
from src.services.registration.answers import answer_service
from src.services.registration.roles_rules import is_flex_submission
from src.services.registration.self_edit import submitted_late


def loaded_relationship_or_none(instance: object, attribute: str):
    loaded_value = sa.inspect(instance).attrs[attribute].loaded_value
    if loaded_value is NO_VALUE:
        return None
    return loaded_value


def _role_top_characters(role: models.RegistrationRole) -> list[str]:
    """Ordered character slugs for a role, without triggering a lazy load.

    Returns ``[]`` when ``hero_entries`` was not eagerly loaded, so callers that
    don't need characters need not eager-load them.
    """
    hero_entries = loaded_relationship_or_none(role, "hero_entries")
    if not hero_entries:
        return []
    return [entry.entity.slug for entry in sorted(hero_entries, key=lambda entry: entry.priority)]


def serialize_registration_role(
    role: models.RegistrationRole,
    ow_rank_value: int | None = None,
    entry: RosterRole | None = None,
) -> schemas.BalancerRegistrationRoleRead:
    """One role row, rated by the engine.

    ``entry`` is this role's resolved :class:`RosterRole`; ``None`` means the
    engine did not put the role in the roster at all, which is the honest
    "unplayable, no number" answer. The declared flag is reported separately from
    playability on purpose: ``is_active`` is what the balancer and the draft act
    on (active AND ranked), ``is_declared_active`` is the checkbox the editor
    toggles.
    """
    return schemas.BalancerRegistrationRoleRead(
        role=role.role_ref,
        priority=role.priority,
        is_primary=role.is_primary,
        rank_value=entry.rank if entry is not None else None,
        rank_source=entry.source if entry is not None else "none",
        is_active=entry is not None and entry.is_playable,
        is_declared_active=bool(role.is_active),
        top_characters=_role_top_characters(role),
        ow_rank_value=ow_rank_value,
    )


def serialize_registration(
    registration: models.Registration,
    entry: models.RegistrationEntry,
    *,
    workspace_id: int,
    provider: str,
    status_meta_map: dict[str, dict[str, StatusMeta]] | None = None,
    ow_ranks_for_user: dict[str, int] | None = None,
    admission: AdmissionRead | None = None,
    profiles_open: bool | None = None,
    subscription_outcome: str | None = None,
    roster: PlayerRoster | None = None,
) -> schemas.BalancerRegistrationRead:
    binding = loaded_relationship_or_none(registration, "google_sheet_binding")
    roles = loaded_relationship_or_none(registration, "roles") or []
    reviewer = loaded_relationship_or_none(entry, "reviewer")
    checked_in_by_user = loaded_relationship_or_none(entry, "checked_in_by_user")
    # API shape: ``user_id`` (the frontend depends on it) is derived from the
    # member anchor — callers must eager-load workspace_member
    # (loaded_relationship_or_none never lazy-loads).
    workspace_member = loaded_relationship_or_none(registration, "workspace_member")
    tournament = loaded_relationship_or_none(registration, "tournament")
    sorted_roles = sorted(roles, key=lambda item: (item.priority, item.role))
    # Every role row is reported (the editor toggles the ones the engine left
    # out of the roster); the roster is what rates them.
    roster_role_by_code = {role.role: role for role in roster.roles} if roster is not None else {}
    resolved_status_meta = (
        status_meta_map["registration"].get(entry.status) if status_meta_map is not None else None
    ) or build_unknown_status_meta("registration", entry.status)
    resolved_balancer_status_meta = (
        status_meta_map["balancer"].get(entry.balancer_status) if status_meta_map is not None else None
    ) or build_unknown_status_meta("balancer", entry.balancer_status)
    return schemas.BalancerRegistrationRead(
        id=registration.id,
        entry_id=entry.id,
        registration_node_id=entry.registration_node_id,
        tournament_id=registration.tournament_id,
        workspace_id=workspace_id,
        user_id=workspace_member.player_id if workspace_member is not None else None,
        workspace_member_id=registration.workspace_member_id,
        display_name=registration.display_name,
        primary_handle=(
            identity.handle if (identity := registration.primary_game_identity(provider=provider)) else None
        ),
        source="google_sheets" if binding is not None else "manual",
        source_record_key=binding.source_record_key if binding is not None else None,
        answers=answer_service.answers_of(registration, entry),
        admin_notes=registration.admin_notes,
        # The roster is the one flex predicate (``PlayerRoster.is_full_flex``,
        # computed over playable declared roles). Without a roster there is no
        # rank information here, so fall back to the write-path predicate over
        # the declared-active rows.
        is_flex=(
            roster.is_full_flex
            if roster is not None
            else is_flex_submission([role for role in sorted_roles if role.is_active])
        ),
        status=entry.status,
        balancer_status=entry.balancer_status,
        status_meta=schemas.StatusMetaRead(**resolved_status_meta),
        balancer_status_meta=schemas.StatusMetaRead(**resolved_balancer_status_meta),
        exclude_reason=entry.exclude_reason,
        checked_in=entry.checked_in,
        checked_in_at=entry.checked_in_at,
        checked_in_by_username=checked_in_by_user.username if checked_in_by_user is not None else None,
        deleted_at=entry.deleted_at,
        submitted_at=registration.submitted_at,
        submitted_late=tournament is not None and submitted_late(registration, tournament),
        reviewed_at=entry.reviewed_at,
        reviewed_by_username=reviewer.username if reviewer is not None else None,
        balancer_profile_overridden_at=registration.balancer_profile_overridden_at,
        admission=admission if admission is not None else AdmissionRead.unknown(),
        profiles_open=profiles_open,
        subscription_outcome=subscription_outcome,
        best_rank=roster.best_rank if roster is not None else None,
        roles=[
            serialize_registration_role(
                role,
                (ow_ranks_for_user or {}).get(role.role),
                roster_role_by_code.get(role.role),
            )
            for role in sorted_roles
        ],
    )


def serialize_registration_form(
    form: models.RegistrationForm,
    *,
    discipline: str,
    is_open: bool,
    registration_late: bool = False,
    subscription_requirement: dict[str, Any] | None = None,
    subrole_catalog: dict[str, list[dict[str, str]]] | None = None,
    stale_registrations: int | None = None,
) -> RegistrationFormRead:
    """Project a registration form for the client.

    ``subscription_requirement`` is the WORKSPACE's rule, passed in rather than
    looked up because this stays sync and must not issue a second round trip per
    call; the async RPC handler fetches it once via
    ``subscription_config.load_workspace_requirement_blob``.

    ``is_open`` is passed in for the same reason; it is derived from the
    tournament's REGISTRATION schedule window, not from the form.

    ``registration_late`` says the window's ``ends_at`` has passed and only
    ``allow_late_registration`` keeps the form open: everyone signing up now is
    written as a reserve, and the form has to say so before they submit.

    ``stale_registrations`` is the organizer-only count of registrations still on
    an older version; the public read leaves it ``None`` rather than paying for it.
    """
    version = form.current_version
    schema = schema_from_form(form)
    if version is None or schema is None:
        raise RuntimeError(f"registration form {form.id} has no current version")
    return RegistrationFormRead(
        id=form.id,
        tournament_id=form.tournament_id,
        workspace_id=form.workspace_id,
        discipline=discipline,
        is_open=is_open,
        registration_late=registration_late,
        auto_approve=form.auto_approve,
        require_open_profile=form.require_open_profile,
        open_profile_scope=form.open_profile_scope,
        show_ranks=form.show_ranks,
        hide_registrations=form.hide_registrations,
        max_participants=form.max_participants,
        max_substitutes=form.max_substitutes,
        require_subscription=form.require_subscription,
        subscription_stage=form.subscription_stage,
        subscription_scope=getattr(form, "subscription_scope", None) or "player",
        team_rank_min=getattr(form, "team_rank_min", None),
        team_rank_max=getattr(form, "team_rank_max", None),
        team_max_rank_spread=getattr(form, "team_max_rank_spread", None),
        team_unique_identity=bool(getattr(form, "team_unique_identity", False)),
        team_require_discord_guild=bool(getattr(form, "team_require_discord_guild", False)),
        subscription_requirement_json=subscription_requirement or {},
        form_schema=schema,
        version_id=version.id,
        version_number=version.number,
        stale_registrations=stale_registrations,
        subrole_catalog=subrole_catalog or {},
    )


def serialize_registration_form_template(
    template: models.RegistrationFormTemplate,
) -> RegistrationFormTemplateRead:
    """A template is its questions and its name -- no toggles, no tournament.

    ``schema_json`` is re-validated rather than passed through: a document
    written by an older schema version must reach the client in today's shape,
    the same normalization ``apply`` relies on before comparing canonical JSON.
    """
    return RegistrationFormTemplateRead(
        id=template.id,
        workspace_id=template.workspace_id,
        discipline=template.discipline,
        name=template.name,
        form_schema=FormSchema.model_validate(template.schema_json),
        # ``updated_at`` is only set by ``onupdate`` -- NULL until the first edit.
        updated_at=template.updated_at or template.created_at,
    )


def serialize_status(
    status_row: models.RegistrationStatus,
) -> schemas.BalancerRegistrationStatusRead:
    is_override = status_row.kind == "builtin" and status_row.workspace_id is not None
    return schemas.BalancerRegistrationStatusRead(
        id=status_row.id,
        workspace_id=status_row.workspace_id,
        scope=status_row.scope,
        slug=status_row.slug,
        kind=status_row.kind,
        is_override=is_override,
        can_delete=status_row.kind == "custom",
        can_reset=is_override,
        icon_slug=status_row.icon_slug,
        icon_color=status_row.icon_color,
        name=status_row.name,
        description=status_row.description,
        # Builtin rows never carry their own inclusion semantics on the raw
        # column -- read it through the same builtin-aware helper the
        # resolved StatusMeta uses, so a builtin-override row (e.g. a
        # workspace's re-skinned "excluded") still reports the true fixed value.
        excludes_from_balancer=build_status_meta_from_model(status_row)["excludes_from_balancer"],
        excludes_from_ready=build_status_meta_from_model(status_row)["excludes_from_ready"],
        created_at=status_row.created_at,
        updated_at=status_row.updated_at,
    )


def serialize_feed(
    feed: models.RegistrationGoogleSheetFeed,
) -> schemas.BalancerGoogleSheetFeedRead:
    return schemas.BalancerGoogleSheetFeedRead(
        id=feed.id,
        tournament_id=feed.tournament_id,
        registration_node_id=feed.registration_node_id,
        source_url=feed.source_url,
        sheet_id=feed.sheet_id,
        gid=feed.gid,
        title=feed.title,
        header_row_json=feed.header_row_json,
        mapping_config_json=feed.mapping_config_json,
        value_mapping_json=feed.value_mapping_json,
        auto_sync_enabled=feed.auto_sync_enabled,
        auto_sync_interval_seconds=feed.auto_sync_interval_seconds,
        last_synced_at=feed.last_synced_at,
        last_sync_status=feed.last_sync_status,
        last_error=feed.last_error,
    )
