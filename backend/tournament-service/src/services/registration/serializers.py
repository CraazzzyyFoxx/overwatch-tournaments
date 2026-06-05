from __future__ import annotations

import sqlalchemy as sa
from shared.balancer_registration_statuses import StatusMeta, build_unknown_status_meta
from sqlalchemy.orm.attributes import NO_VALUE

from src import models
from src.schemas.admin import balancer as admin_schemas
from src.schemas.registration import RegistrationFormRead


def loaded_relationship_or_none(instance: object, attribute: str):
    loaded_value = sa.inspect(instance).attrs[attribute].loaded_value
    if loaded_value is NO_VALUE:
        return None
    return loaded_value


def _role_top_heroes(role: models.BalancerRegistrationRole) -> list[str]:
    """Ordered hero slugs for a role, without triggering a lazy load.

    Returns ``[]`` when ``hero_entries`` was not eagerly loaded, so callers that
    don't need heroes need not eager-load them.
    """
    hero_entries = loaded_relationship_or_none(role, "hero_entries")
    if not hero_entries:
        return []
    return [entry.hero.slug for entry in sorted(hero_entries, key=lambda entry: entry.priority)]


def serialize_registration_role(
    role: models.BalancerRegistrationRole,
) -> admin_schemas.BalancerRegistrationRoleRead:
    return admin_schemas.BalancerRegistrationRoleRead(
        role=role.role,
        subrole=role.subrole,
        priority=role.priority,
        is_primary=role.is_primary,
        rank_value=role.rank_value,
        is_active=role.is_active,
        top_heroes=_role_top_heroes(role),
    )


def serialize_registration(
    registration: models.BalancerRegistration,
    *,
    status_meta_map: dict[str, dict[str, StatusMeta]] | None = None,
) -> admin_schemas.BalancerRegistrationRead:
    binding = loaded_relationship_or_none(registration, "google_sheet_binding")
    roles = loaded_relationship_or_none(registration, "roles") or []
    reviewer = loaded_relationship_or_none(registration, "reviewer")
    checked_in_by_user = loaded_relationship_or_none(registration, "checked_in_by_user")
    sorted_roles = sorted(roles, key=lambda item: (item.priority, item.role))
    resolved_status_meta = (
        status_meta_map["registration"].get(registration.status) if status_meta_map is not None else None
    ) or build_unknown_status_meta("registration", registration.status)
    resolved_balancer_status_meta = (
        status_meta_map["balancer"].get(registration.balancer_status) if status_meta_map is not None else None
    ) or build_unknown_status_meta("balancer", registration.balancer_status)
    return admin_schemas.BalancerRegistrationRead(
        id=registration.id,
        tournament_id=registration.tournament_id,
        workspace_id=registration.workspace_id,
        auth_user_id=registration.auth_user_id,
        user_id=registration.user_id,
        display_name=registration.display_name,
        battle_tag=registration.battle_tag,
        battle_tag_normalized=registration.battle_tag_normalized,
        source="google_sheets" if binding is not None else "manual",
        source_record_key=binding.source_record_key if binding is not None else None,
        smurf_tags_json=registration.smurf_tags_json or [],
        discord_nick=registration.discord_nick,
        twitch_nick=registration.twitch_nick,
        stream_pov=registration.stream_pov,
        notes=registration.notes,
        admin_notes=registration.admin_notes,
        custom_fields_json=registration.custom_fields_json,
        is_flex=bool(sorted_roles) and all(role.is_primary for role in sorted_roles),
        status=registration.status,
        balancer_status=registration.balancer_status,
        status_meta=admin_schemas.StatusMetaRead(**resolved_status_meta),
        balancer_status_meta=admin_schemas.StatusMetaRead(**resolved_balancer_status_meta),
        exclude_from_balancer=registration.exclude_from_balancer,
        exclude_reason=registration.exclude_reason,
        checked_in=registration.checked_in,
        checked_in_at=registration.checked_in_at,
        checked_in_by_username=checked_in_by_user.username if checked_in_by_user is not None else None,
        deleted_at=registration.deleted_at,
        submitted_at=registration.submitted_at,
        reviewed_at=registration.reviewed_at,
        reviewed_by_username=reviewer.username if reviewer is not None else None,
        balancer_profile_overridden_at=registration.balancer_profile_overridden_at,
        roles=[serialize_registration_role(role) for role in sorted_roles],
    )


def serialize_registration_form(
    form: models.BalancerRegistrationForm,
) -> RegistrationFormRead:
    return RegistrationFormRead(
        id=form.id,
        tournament_id=form.tournament_id,
        workspace_id=form.workspace_id,
        is_open=form.is_open,
        auto_approve=form.auto_approve,
        opens_at=form.opens_at,
        closes_at=form.closes_at,
        require_open_profile=form.require_open_profile,
        open_profile_scope=form.open_profile_scope,
        show_ranks=form.show_ranks,
        built_in_fields=form.built_in_fields_json or {},
        custom_fields=form.custom_fields_json or [],
    )


def serialize_status(
    status_row: models.BalancerRegistrationStatus,
) -> admin_schemas.BalancerRegistrationStatusRead:
    is_override = status_row.kind == "builtin" and status_row.workspace_id is not None
    return admin_schemas.BalancerRegistrationStatusRead(
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
        created_at=status_row.created_at,
        updated_at=status_row.updated_at,
    )


def serialize_feed(
    feed: models.BalancerRegistrationGoogleSheetFeed,
) -> admin_schemas.BalancerGoogleSheetFeedRead:
    return admin_schemas.BalancerGoogleSheetFeedRead(
        id=feed.id,
        tournament_id=feed.tournament_id,
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
