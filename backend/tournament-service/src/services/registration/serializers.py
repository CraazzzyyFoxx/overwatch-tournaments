from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm.attributes import NO_VALUE

from shared.balancer_registration_statuses import (
    StatusMeta,
    build_status_meta_from_model,
    build_unknown_status_meta,
)
from shared.domain.roster import PlayerRoster, RosterRole
from src import models, schemas
from src.schemas.admission import AdmissionRead
from src.schemas.registration import RegistrationFormRead
from src.services.registration.validation import is_flex_submission


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
        role=role.role,
        subrole=role.subrole,
        priority=role.priority,
        is_primary=role.is_primary,
        rank_value=entry.rank if entry is not None else None,
        rank_source=entry.source if entry is not None else "none",
        is_active=entry is not None and entry.is_playable,
        is_declared_active=bool(role.is_active),
        top_heroes=_role_top_heroes(role),
        ow_rank_value=ow_rank_value,
    )


def serialize_registration(
    registration: models.BalancerRegistration,
    *,
    workspace_id: int,
    status_meta_map: dict[str, dict[str, StatusMeta]] | None = None,
    ow_ranks_for_user: dict[str, int] | None = None,
    admission: AdmissionRead | None = None,
    profiles_open: bool | None = None,
    subscription_outcome: str | None = None,
    roster: PlayerRoster | None = None,
) -> schemas.BalancerRegistrationRead:
    binding = loaded_relationship_or_none(registration, "google_sheet_binding")
    roles = loaded_relationship_or_none(registration, "roles") or []
    reviewer = loaded_relationship_or_none(registration, "reviewer")
    checked_in_by_user = loaded_relationship_or_none(registration, "checked_in_by_user")
    # API shape: user_id stays in the payload (frontend depends on it) but is
    # now derived from the member anchor — callers must eager-load
    # workspace_member (loaded_relationship_or_none never lazy-loads).
    workspace_member = loaded_relationship_or_none(registration, "workspace_member")
    sorted_roles = sorted(roles, key=lambda item: (item.priority, item.role))
    # Every role row is still reported (the editor toggles the ones the engine
    # left out of the roster); the roster is what rates them.
    entry_by_role = {entry.role.slot_code: entry for entry in roster.roles} if roster is not None else {}
    resolved_status_meta = (
        status_meta_map["registration"].get(registration.status) if status_meta_map is not None else None
    ) or build_unknown_status_meta("registration", registration.status)
    resolved_balancer_status_meta = (
        status_meta_map["balancer"].get(registration.balancer_status) if status_meta_map is not None else None
    ) or build_unknown_status_meta("balancer", registration.balancer_status)
    return schemas.BalancerRegistrationRead(
        id=registration.id,
        tournament_id=registration.tournament_id,
        workspace_id=workspace_id,
        user_id=workspace_member.player_id if workspace_member is not None else None,
        display_name=registration.display_name,
        battle_tag=registration.battle_tag,
        battle_tag_normalized=registration.battle_tag_normalized,
        source="google_sheets" if binding is not None else "manual",
        source_record_key=binding.source_record_key if binding is not None else None,
        smurf_tags_json=registration.smurf_tags_json or [],
        discord_nick=registration.discord_nick,
        twitch_nick=registration.twitch_nick,
        boosty_nick=registration.boosty_nick,
        stream_pov=registration.stream_pov,
        notes=registration.notes,
        admin_notes=registration.admin_notes,
        custom_fields_json=registration.custom_fields_json,
        # The roster is the one flex predicate (``PlayerRoster.is_full_flex``,
        # computed over playable declared roles). Without a roster there is no
        # rank information here, so fall back to the write-path predicate over
        # the declared-active rows -- never a third inline copy.
        is_flex=(
            roster.is_full_flex
            if roster is not None
            else is_flex_submission([role for role in sorted_roles if role.is_active])
        ),
        status=registration.status,
        balancer_status=registration.balancer_status,
        status_meta=schemas.StatusMetaRead(**resolved_status_meta),
        balancer_status_meta=schemas.StatusMetaRead(**resolved_balancer_status_meta),
        exclude_reason=registration.exclude_reason,
        checked_in=registration.checked_in,
        checked_in_at=registration.checked_in_at,
        checked_in_by_username=checked_in_by_user.username if checked_in_by_user is not None else None,
        deleted_at=registration.deleted_at,
        submitted_at=registration.submitted_at,
        reviewed_at=registration.reviewed_at,
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
                entry_by_role.get(role.role),
            )
            for role in sorted_roles
        ],
    )


def serialize_registration_form(
    form: models.BalancerRegistrationForm,
    *,
    is_open: bool,
    subscription_requirement: dict[str, Any] | None = None,
) -> RegistrationFormRead:
    """``subscription_requirement`` is the WORKSPACE's rule, passed in by the caller.

    An argument rather than a lookup because this stays sync and must not issue a
    second round trip per call; the async RPC handler already has the session and
    fetches it once via ``subscription_config.load_workspace_requirement_blob``.

    ``is_open`` is passed in for the same reason, and is now DERIVED from the
    tournament's REGISTRATION schedule window rather than read off the form — the
    form no longer has a say in whether registration is open.
    """
    return RegistrationFormRead(
        id=form.id,
        tournament_id=form.tournament_id,
        workspace_id=form.workspace_id,
        is_open=is_open,
        auto_approve=form.auto_approve,
        require_open_profile=form.require_open_profile,
        open_profile_scope=form.open_profile_scope,
        show_ranks=form.show_ranks,
        max_substitutes=form.max_substitutes,
        require_subscription=form.require_subscription,
        subscription_stage=form.subscription_stage,
        subscription_requirement_json=subscription_requirement or {},
        built_in_fields=form.built_in_fields_json or {},
        custom_fields=form.custom_fields_json or [],
    )


def serialize_status(
    status_row: models.BalancerRegistrationStatus,
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
    feed: models.BalancerRegistrationGoogleSheetFeed,
) -> schemas.BalancerGoogleSheetFeedRead:
    return schemas.BalancerGoogleSheetFeedRead(
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
