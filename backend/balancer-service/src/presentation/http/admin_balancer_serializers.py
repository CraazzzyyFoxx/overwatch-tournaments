from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm.attributes import NO_VALUE

from src import models
from src.domain.balancer.config_provider import serialize_saved_config_payload
from src.domain.balancer.public_contract import normalize_balance_response_payload
from src.domain.balancer.role_entries import normalize_role_entries
from src.schemas.admin import balancer as admin_schemas


def loaded_relationship_or_none(instance: object, attribute: str):
    loaded_value = sa.inspect(instance).attrs[attribute].loaded_value
    if loaded_value is NO_VALUE:
        return None
    return loaded_value


def serialize_role_entries(
    player: models.BalancerPlayer,
    ow_ranks_for_player: dict[str, int] | None = None,
) -> list[admin_schemas.BalancerPlayerRoleEntry]:
    loaded_role_entries = loaded_relationship_or_none(player, "role_entries")
    if loaded_role_entries is not None:
        normalized_entries = [
            {
                "role": entry.role,
                "subtype": entry.subtype,
                "priority": entry.priority,
                "division_number": entry.division_number,
                "rank_value": entry.rank_value,
                "is_active": entry.is_active,
            }
            for entry in sorted(loaded_role_entries, key=lambda entry: entry.priority)
        ]
    else:
        normalized_entries = normalize_role_entries(player.role_entries_json)

    result = []
    ow_ranks = ow_ranks_for_player or {}
    for entry in normalized_entries:
        role_key = entry["role"] if isinstance(entry, dict) else entry.role
        validated = admin_schemas.BalancerPlayerRoleEntry.model_validate(entry)
        result.append(validated.model_copy(update={"ow_rank_value": ow_ranks.get(role_key)}))
    return result


def serialize_player(
    player: models.BalancerPlayer,
    ow_ranks_for_player: dict[str, int] | None = None,
) -> admin_schemas.BalancerPlayerRead:
    return admin_schemas.BalancerPlayerRead(
        id=player.id,
        tournament_id=player.tournament_id,
        application_id=player.application_id,
        battle_tag=player.battle_tag,
        battle_tag_normalized=player.battle_tag_normalized,
        user_id=player.user_id,
        role_entries_json=serialize_role_entries(player, ow_ranks_for_player),
        is_flex=player.is_flex,
        is_in_pool=player.is_in_pool,
        admin_notes=player.admin_notes,
    )


def serialize_application(
    application: models.BalancerApplication,
) -> admin_schemas.BalancerApplicationRead:
    player = loaded_relationship_or_none(application, "player")
    return admin_schemas.BalancerApplicationRead(
        id=application.id,
        tournament_id=application.tournament_id,
        tournament_sheet_id=application.tournament_sheet_id,
        battle_tag=application.battle_tag,
        battle_tag_normalized=application.battle_tag_normalized,
        smurf_tags_json=application.smurf_tags_json or [],
        twitch_nick=application.twitch_nick,
        discord_nick=application.discord_nick,
        stream_pov=application.stream_pov,
        last_tournament_text=application.last_tournament_text,
        primary_role=application.primary_role,
        additional_roles_json=application.additional_roles_json or [],
        notes=application.notes,
        submitted_at=application.submitted_at,
        synced_at=application.synced_at,
        is_active=application.is_active,
        player=serialize_player(player) if player is not None else None,
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


def serialize_balance(
    balance: models.BalancerBalance,
) -> admin_schemas.BalanceRead:
    return admin_schemas.BalanceRead(
        id=balance.id,
        tournament_id=balance.tournament_id,
        config_json=serialize_saved_config_payload(balance.config_json),
        result_json=normalize_balance_response_payload(balance.result_json),
        saved_by=balance.saved_by,
        saved_at=balance.saved_at,
        exported_at=balance.exported_at,
        export_status=balance.export_status,
    )


def serialize_tournament_config(
    tournament_config: models.BalancerTournamentConfig,
) -> admin_schemas.BalancerTournamentConfigRead:
    return admin_schemas.BalancerTournamentConfigRead(
        id=tournament_config.id,
        tournament_id=tournament_config.tournament_id,
        workspace_id=tournament_config.workspace_id,
        config_json=serialize_saved_config_payload(tournament_config.config_json),
        updated_by=tournament_config.updated_by,
        updated_at=tournament_config.updated_at,
    )
