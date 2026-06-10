from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.division_grid import DEFAULT_GRID, DivisionGrid
from shared.domain.player_sub_roles import normalize_sub_role
from shared.models.balancer import WorkspaceBalancerConfig
from shared.models.overwatch_rank import UserRankSnapshot
from shared.services.division_grid_resolution import resolve_tournament_division
from src import models
from src.domain.balancer.config_provider import normalize_tournament_config_payload, serialize_saved_config_payload
from src.domain.balancer.public_contract import normalize_balance_response_payload
from src.schemas.admin import balancer as admin_schemas
from src.schemas.team import InternalBalancerTeamsPayload
from src.schemas.user import UserCSV
from src.services import team as team_flows
from src.services import user as user_flows
from src.services import user as user_service
from src.services.admin.balance_analytics import create_balance_snapshot
from src.services.admin.balancer_dual_write import sync_balance_variants_and_slots
from src.services.admin.balancer_utils import (
    DEFAULT_ROLE_MAPPING,
    DEFAULT_SORT_PRIORITY_SENTINEL,
    GOOGLE_SHEET_FETCH_TIMEOUT,
    UNKNOWN_PRIORITY_SENTINEL,
    VALID_ROLES,
    build_csv_export_url,
    extract_sheet_source,
    fetch_csv_rows,
    normalize_battle_tag,
    normalize_battle_tag_key,
    normalize_header,
    parse_boolean_value,
    parse_submitted_at,
    row_to_json,
    unique_strings,
)
from src.services.admin.balancer_utils import (
    extract_battle_tags as _extract_battle_tags,
)

logger = logging.getLogger(__name__)

BATTLE_TAG_RE = re.compile(r"([\w0-9]{2,12}#[0-9]{4,})", re.UNICODE)

EXPORT_ROLE_ORDER = ["dps", "tank", "support"]
EXPORT_ROLE_PRIORITY = {role: index for index, role in enumerate(EXPORT_ROLE_ORDER)}


def parse_bool(value: str | None) -> bool:
    return parse_boolean_value(value)


def extract_battle_tags(value: str | None) -> list[str]:
    return _extract_battle_tags(value, BATTLE_TAG_RE)


def map_role(raw_role: str | None, role_mapping: dict[str, str | None]) -> str | None:
    if raw_role is None:
        return None

    normalized_value = raw_role.strip()
    if not normalized_value:
        return None

    if normalized_value in role_mapping:
        return role_mapping[normalized_value]

    lowered = normalize_header(normalized_value)
    if "танк" in lowered or lowered == "tank":
        return "tank"
    if "дд" in lowered or "dps" in lowered or "damage" in lowered:
        return "dps"
    if "хил" in lowered or "support" in lowered:
        return "support"
    return None


def is_flex_role_selection(raw_role: str | None, role_mapping: dict[str, str | None]) -> bool:
    if raw_role is None:
        return False

    normalized_value = raw_role.strip()
    if not normalized_value:
        return False

    if normalized_value in role_mapping and role_mapping[normalized_value] is None:
        return True

    lowered = normalize_header(normalized_value)
    return "флекс" in lowered or "flex" in lowered


def extract_roles_from_flex_selection(raw_role: str | None, role_mapping: dict[str, str | None]) -> list[str]:
    if not is_flex_role_selection(raw_role, role_mapping):
        return []

    normalized_value = (raw_role or "").strip()
    lowered = normalize_header(normalized_value)

    if normalized_value in role_mapping and role_mapping[normalized_value] is None:
        return ["tank", "dps", "support"]

    if "абсолютно на всем" in lowered or "на всем" in lowered or "all roles" in lowered or "everything" in lowered:
        return ["tank", "dps", "support"]

    roles: list[str] = []
    if "танк" in lowered or "tank" in lowered:
        roles.append("tank")
    if "дд" in lowered or "dps" in lowered or "damage" in lowered:
        roles.append("dps")
    if "хил" in lowered or "support" in lowered or "сап" in lowered:
        roles.append("support")

    return unique_strings(roles) or ["tank", "dps", "support"]


def parse_application_roles(
    primary_role_raw: str | None,
    additional_roles_raw: list[str],
    role_mapping: dict[str, str | None],
    flex_hint_values: list[str] | None = None,
) -> tuple[str | None, list[str], bool]:
    explicit_primary_role = (
        None if is_flex_role_selection(primary_role_raw, role_mapping) else map_role(primary_role_raw, role_mapping)
    )
    ordered_roles: list[str] = []
    if explicit_primary_role in VALID_ROLES:
        ordered_roles.append(explicit_primary_role)

    has_flex = False

    for value in [primary_role_raw, *additional_roles_raw, *(flex_hint_values or [])]:
        if not value:
            continue

        flex_roles = extract_roles_from_flex_selection(value, role_mapping)
        if flex_roles:
            has_flex = True
            ordered_roles.extend(flex_roles)
            continue

        mapped_role = map_role(value, role_mapping)
        if mapped_role in VALID_ROLES:
            ordered_roles.append(mapped_role)

    unique_roles = unique_strings([role for role in ordered_roles if role in VALID_ROLES])

    if explicit_primary_role in unique_roles:
        additional_roles = [role for role in unique_roles if role != explicit_primary_role]
        return explicit_primary_role, additional_roles, has_flex

    return None, unique_roles, has_flex


def sanitize_secondary_roles(primary_role: str | None, roles: list[str] | None) -> list[str]:
    valid_roles = [role for role in roles or [] if role in VALID_ROLES]
    unique_roles = unique_strings(valid_roles)
    if primary_role is None:
        return unique_roles
    return [role for role in unique_roles if role != primary_role]


def infer_role_subtype(raw_role: str | None, mapped_role: str | None) -> str | None:
    if raw_role is None or mapped_role not in VALID_ROLES:
        return None

    lowered = normalize_header(raw_role)
    if mapped_role == "dps":
        if "хитскан" in lowered or "hitscan" in lowered:
            return "hitscan"
        if "проджект" in lowered or "projectile" in lowered:
            return "projectile"
    if mapped_role == "support":
        if "мейн хил" in lowered or "main heal" in lowered:
            return "main_heal"
        if "лайт хил" in lowered or "light heal" in lowered:
            return "light_heal"
    return None


def infer_role_subtype_from_class_flags(role: str, stats: dict[str, Any]) -> str | None:
    primary = bool(stats.get("primary", False))
    secondary = bool(stats.get("secondary", False))

    if primary and secondary:
        return None

    if role == "dps":
        if primary:
            return "hitscan"
        if secondary:
            return "projectile"

    if role == "support":
        if primary:
            return "main_heal"
        if secondary:
            return "light_heal"

    return None


def build_class_subtype_flags(role: str, subtype: str | None) -> tuple[bool, bool]:
    if role == "dps":
        return subtype == "hitscan", subtype == "projectile"

    if role == "support":
        return subtype == "main_heal", subtype == "light_heal"

    return False, False


def filter_ranked_role_entries(
    role_entries: list[dict[str, Any]] | list[admin_schemas.BalancerPlayerRoleEntry] | None,
) -> list[dict[str, Any]]:
    normalized_entries = normalize_role_entries(role_entries)
    ranked_entries = [
        entry for entry in normalized_entries if entry.get("is_active", True) and entry.get("rank_value") is not None
    ]
    return normalize_role_entries(ranked_entries)


def merge_role_candidates_with_subtypes(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_by_role: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for candidate in candidates:
        role = candidate["role"]
        if role not in merged_by_role:
            merged_by_role[role] = {**candidate}
            order.append(role)
            continue

        existing = merged_by_role[role]
        if existing.get("subtype") != candidate.get("subtype"):
            existing["subtype"] = None

    return [merged_by_role[role] for role in order]


def extract_application_raw_role_values(application: models.BalancerApplication) -> tuple[str | None, list[str]]:
    raw_row = application.raw_row_json or {}
    primary_role_raw: str | None = None
    additional_roles_raw: list[str] = []

    for key, value in raw_row.items():
        if not isinstance(value, str) or not value.strip():
            continue

        normalized_key = normalize_header(key)
        if normalized_key.startswith("укажите вашу роль") and primary_role_raw is None:
            primary_role_raw = value.strip()
            continue
        if normalized_key.startswith("дополнительная игровая роль"):
            additional_roles_raw.append(value.strip())

    return primary_role_raw, additional_roles_raw


def normalize_role_entries(
    role_entries: list[dict[str, Any]] | list[admin_schemas.BalancerPlayerRoleEntry] | None,
) -> list[dict[str, Any]]:
    normalized_entries: list[dict[str, Any]] = []
    seen_roles: set[str] = set()

    prepared_entries: list[dict[str, Any]] = []
    for entry in role_entries or []:
        if isinstance(entry, dict):
            prepared_entries.append(entry)
        else:
            prepared_entries.append(entry.model_dump())

    prepared_entries.sort(key=lambda item: item.get("priority") if item.get("priority") is not None else DEFAULT_SORT_PRIORITY_SENTINEL)

    for entry in prepared_entries:
        role = entry.get("role")
        if role not in VALID_ROLES or role in seen_roles:
            continue

        is_active_raw = entry.get("is_active")
        if is_active_raw is None:
            is_active_raw = entry.get("isActive")
        is_active = bool(True if is_active_raw is None else is_active_raw)

        subtype = normalize_sub_role(entry.get("subtype"))

        division_number = entry.get("division_number")
        rank_value = entry.get("rank_value")

        if division_number is not None and rank_value is None:
            rank_value = resolve_rank_from_division(int(division_number))
        elif rank_value is not None and division_number is None:
            division_number = resolve_division_from_rank(int(rank_value))

        normalized_entries.append(
            {
                "role": role,
                "subtype": subtype,
                "priority": len(normalized_entries) + 1,
                "division_number": int(division_number) if division_number is not None else None,
                "rank_value": int(rank_value) if rank_value is not None else None,
                "is_active": is_active,
            }
        )
        seen_roles.add(role)

    return normalized_entries


def build_role_entries_from_application(application: models.BalancerApplication) -> list[dict[str, Any]]:
    primary_role_raw, additional_roles_raw = extract_application_raw_role_values(application)
    primary_role, additional_roles, _ = parse_application_roles(
        primary_role_raw,
        additional_roles_raw,
        DEFAULT_ROLE_MAPPING,
        [application.notes] if application.notes else None,
    )

    candidates: list[dict[str, Any]] = []
    if primary_role in VALID_ROLES:
        candidates.append(
            {
                "role": primary_role,
                "subtype": infer_role_subtype(primary_role_raw, primary_role),
                "priority": 0,
                "division_number": None,
                "rank_value": None,
                "is_active": True,
            }
        )

    additional_index = 1
    for raw_role in additional_roles_raw:
        mapped_role = map_role(raw_role, DEFAULT_ROLE_MAPPING)
        if mapped_role not in additional_roles:
            continue
        candidates.append(
            {
                "role": mapped_role,
                "subtype": infer_role_subtype(raw_role, mapped_role),
                "priority": additional_index,
                "division_number": None,
                "rank_value": None,
                "is_active": True,
            }
        )
        additional_index += 1

    merged_candidates = merge_role_candidates_with_subtypes(candidates)
    if merged_candidates:
        return normalize_role_entries(merged_candidates)

    ordered_roles: list[str] = []
    if application.primary_role in VALID_ROLES:
        ordered_roles.append(application.primary_role)

    ordered_roles.extend(
        role
        for role in sanitize_secondary_roles(application.primary_role, application.additional_roles_json or [])
        if role not in ordered_roles
    )

    return normalize_role_entries(
        [
            {
                "role": role,
                "subtype": None,
                "priority": index + 1,
                "division_number": None,
                "rank_value": None,
                "is_active": True,
            }
            for index, role in enumerate(ordered_roles)
        ]
    )


def map_imported_role_entries_to_application(
    application: models.BalancerApplication,
    imported_role_entries: list[dict[str, Any]] | list[admin_schemas.BalancerPlayerRoleEntry] | None,
) -> list[dict[str, Any]]:
    normalized_imported = normalize_role_entries(imported_role_entries)
    allowed_role_entries = build_role_entries_from_application(application)
    allowed_by_role = {entry["role"]: entry for entry in allowed_role_entries}

    merged_entries = [
        {
            "role": imported_entry["role"],
            "subtype": imported_entry.get("subtype") or allowed_by_role[imported_entry["role"]].get("subtype"),
            "priority": imported_entry["priority"],
            "division_number": imported_entry.get("division_number"),
            "rank_value": imported_entry.get("rank_value"),
            "is_active": imported_entry.get("is_active", True),
        }
        for imported_entry in normalized_imported
        if imported_entry["role"] in allowed_by_role
    ]
    return normalize_role_entries(merged_entries)


def map_existing_role_entries_to_application(
    application: models.BalancerApplication,
    existing_role_entries: list[dict[str, Any]] | list[admin_schemas.BalancerPlayerRoleEntry] | None,
) -> list[dict[str, Any]]:
    normalized_existing = normalize_role_entries(existing_role_entries)
    allowed_role_entries = build_role_entries_from_application(application)
    existing_by_role = {entry["role"]: entry for entry in normalized_existing}

    mapped_entries = [
        {
            "role": allowed_entry["role"],
            "subtype": allowed_entry.get("subtype"),
            "priority": allowed_entry["priority"],
            "division_number": existing_by_role.get(allowed_entry["role"], {}).get("division_number"),
            "rank_value": existing_by_role.get(allowed_entry["role"], {}).get("rank_value"),
            "is_active": existing_by_role.get(allowed_entry["role"], {}).get("is_active", True),
        }
        for allowed_entry in allowed_role_entries
    ]
    return normalize_role_entries(mapped_entries)


async def _write_player_role_entries(
    session: AsyncSession,
    player: models.BalancerPlayer,
    role_entries: list[dict[str, Any]],
) -> None:
    """Write normalized role entries directly to BalancerPlayerRoleEntry table.

    Deletes existing entries for the player and re-inserts from the provided list.
    This is the sole write path — no JSON column intermediate.
    """
    await session.execute(
        sa.delete(models.BalancerPlayerRoleEntry).where(
            models.BalancerPlayerRoleEntry.player_id == player.id
        )
    )
    for entry in normalize_role_entries(role_entries):
        session.add(
            models.BalancerPlayerRoleEntry(
                player_id=player.id,
                role=entry["role"],
                subtype=entry.get("subtype"),
                priority=entry["priority"],
                rank_value=entry.get("rank_value"),
                division_number=entry.get("division_number"),
                is_active=entry.get("is_active", True),
            )
        )


def extract_players_dict(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if payload.get("format") == "xv-1" and isinstance(payload.get("players"), dict):
        return payload["players"]

    data_root = payload.get("data")
    if isinstance(data_root, dict):
        if isinstance(data_root.get("players"), dict):
            return data_root["players"]

        nested_root = data_root.get("data")
        if isinstance(nested_root, dict) and isinstance(nested_root.get("players"), dict):
            return nested_root["players"]

    if isinstance(payload.get("players"), dict):
        return payload["players"]

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid atravkovs payload")


def build_role_entries_from_classes(classes: dict[str, Any]) -> list[dict[str, Any]]:
    raw_entries: list[dict[str, Any]] = []
    for role, stats in classes.items():
        if role not in VALID_ROLES or not isinstance(stats, dict):
            continue

        rank_raw = stats.get("rank")
        rank_value = int(rank_raw) if isinstance(rank_raw, int | float) and int(rank_raw) > 0 else None
        priority_raw = stats.get("priority")
        priority = int(priority_raw) if isinstance(priority_raw, int | float) else UNKNOWN_PRIORITY_SENTINEL
        is_active = bool(stats.get("isActive", False))

        if not is_active and rank_value is None and "priority" not in stats:
            continue

        raw_entries.append(
            {
                "role": role,
                "subtype": stats.get("subtype") or infer_role_subtype_from_class_flags(role, stats),
                "priority": priority,
                "division_number": resolve_division_from_rank(rank_value),
                "rank_value": rank_value,
                "is_active": is_active,
            }
        )

    return normalize_role_entries(raw_entries)


def parse_imported_player_nodes(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    players_dict = extract_players_dict(payload)
    parsed_players: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_tags: set[str] = set()

    for _, player_node in players_dict.items():
        if not isinstance(player_node, dict):
            continue

        battle_tag = normalize_battle_tag(player_node.get("identity", {}).get("name"))
        normalized_tag = normalize_battle_tag_key(battle_tag)
        if not normalized_tag:
            continue

        if normalized_tag in seen_tags:
            skipped.append(
                {
                    "battle_tag": battle_tag,
                    "battle_tag_normalized": normalized_tag,
                    "reason": "duplicate_in_file",
                }
            )
            continue

        seen_tags.add(normalized_tag)
        meta = player_node.get("meta") if isinstance(player_node.get("meta"), dict) else {}
        role_entries = meta.get("roleEntries") if isinstance(meta.get("roleEntries"), list) else None
        normalized_role_entries = normalize_role_entries(role_entries) if role_entries is not None else None

        if not normalized_role_entries:
            classes = player_node.get("stats", {}).get("classes", {})
            normalized_role_entries = build_role_entries_from_classes(classes if isinstance(classes, dict) else {})

        if not filter_ranked_role_entries(normalized_role_entries):
            skipped.append(
                {
                    "battle_tag": battle_tag,
                    "battle_tag_normalized": normalized_tag,
                    "reason": "no_ranked_roles",
                }
            )
            continue

        admin_notes = meta.get("adminNotes") if isinstance(meta.get("adminNotes"), str) else None
        is_in_pool = bool(meta.get("isInPool", True))
        is_flex = meta.get("isFlex") if isinstance(meta.get("isFlex"), bool) else None

        parsed_players.append(
            {
                "battle_tag": battle_tag,
                "battle_tag_normalized": normalized_tag,
                "role_entries_json": normalized_role_entries,
                "admin_notes": admin_notes,
                "is_in_pool": is_in_pool,
                "is_flex": is_flex,
            }
        )

    return parsed_players, skipped


async def resolve_import_context(
    session: AsyncSession,
    tournament_id: int,
    imported_players: list[dict[str, Any]],
) -> tuple[dict[str, models.BalancerApplication], dict[int, models.BalancerPlayer]]:
    if not imported_players:
        return {}, {}

    result = await session.execute(
        sa.select(models.BalancerApplication)
        .where(models.BalancerApplication.tournament_id == tournament_id)
        .where(models.BalancerApplication.is_active.is_(True))
        .options(
            selectinload(models.BalancerApplication.player).selectinload(models.BalancerPlayer.role_entries)
        )
        .order_by(models.BalancerApplication.battle_tag_normalized.asc())
    )
    active_applications = list(result.scalars().all())
    applications_by_tag = {application.battle_tag_normalized: application for application in active_applications}
    applications_by_user_id: dict[int, models.BalancerApplication] = {}

    for application in active_applications:
        user_id = application.player.user_id if application.player is not None else None
        if user_id is None:
            user_id = await resolve_public_user_id_for_application(session, application)
        if user_id is None or user_id in applications_by_user_id:
            continue
        applications_by_user_id[user_id] = application

    applications: dict[str, models.BalancerApplication] = {}
    for imported_player in imported_players:
        normalized_tag = imported_player["battle_tag_normalized"]
        direct_application = applications_by_tag.get(normalized_tag)
        if direct_application is not None:
            applications[normalized_tag] = direct_application
            continue

        user = await user_service.find_by_battle_tag(session, imported_player["battle_tag"], ["battle_tag"])
        if user is None:
            continue

        alias_application = applications_by_user_id.get(user.id)
        if alias_application is not None:
            applications[normalized_tag] = alias_application

    existing_players = {
        application.id: application.player for application in applications.values() if application.player is not None
    }
    return applications, existing_players


def serialize_player_for_export(player: models.BalancerPlayer, export_uuid: str) -> dict[str, Any]:
    loaded_role_entries = getattr(player, "role_entries", None)
    if loaded_role_entries is not None:
        role_entries = [
            {
                "role": e.role,
                "subtype": e.subtype,
                "priority": e.priority,
                "rank_value": e.rank_value,
                "division_number": e.division_number,
                "is_active": e.is_active,
            }
            for e in sorted(loaded_role_entries, key=lambda e: e.priority)
        ]
    else:
        role_entries = normalize_role_entries(getattr(player, "role_entries_json", []))

    if player.is_flex:
        export_priorities = dict.fromkeys(EXPORT_ROLE_ORDER, 0)
    else:
        ordered_active_roles = [entry["role"] for entry in role_entries if entry.get("is_active", True)]
        ordered_roles = ordered_active_roles + [role for role in EXPORT_ROLE_ORDER if role not in ordered_active_roles]
        export_priorities = {role: index for index, role in enumerate(ordered_roles)}
    classes: dict[str, dict[str, Any]] = {}
    for role in EXPORT_ROLE_ORDER:
        entry = next((candidate for candidate in role_entries if candidate["role"] == role), None)
        is_active = bool(entry and entry.get("is_active", True) and entry.get("rank_value") is not None)
        priority = export_priorities[role]
        primary_flag, secondary_flag = build_class_subtype_flags(
            role, entry.get("subtype") if is_active and entry else None
        )
        subtype = entry.get("subtype") if is_active and entry else None
        classes[role] = {
            "rank": entry.get("rank_value") if is_active and entry is not None else 0,
            "playHours": 0,
            "priority": priority,
            "primary": primary_flag,
            "isActive": is_active,
            "secondary": secondary_flag,
            "subtype": subtype,
        }

    return {
        "identity": {
            "name": player.battle_tag,
            "uuid": export_uuid,
            "isLocked": False,
            "isCaptain": False,
            "isSquire": False,
            "isFullFlex": bool(player.is_flex),
        },
        "stats": {"classes": classes},
        "createdAt": player.created_at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def detect_column_mapping(headers: list[str]) -> dict[str, Any]:
    mapping: dict[str, Any] = {"additional_roles": []}

    for index, header in enumerate(headers):
        normalized = normalize_header(header)
        if normalized == "отметка времени":
            mapping["timestamp"] = index
        elif normalized.startswith("ваш battle tag"):
            mapping["battle_tag"] = index
        elif normalized.startswith("ваши battle tag смурфов"):
            mapping["smurf_tags"] = index
        elif normalized.startswith("ваш ник на твиче"):
            mapping["twitch_nick"] = index
        elif normalized.startswith("ваш ник в дискорде"):
            mapping["discord_nick"] = index
        elif normalized.startswith("планируете ли стримить"):
            mapping["stream_pov"] = index
        elif normalized.startswith("в каком последнем турнире"):
            mapping["last_tournament_text"] = index
        elif normalized.startswith("укажите вашу роль"):
            mapping["primary_role"] = index
        elif normalized.startswith("дополнительная игровая роль"):
            mapping["additional_roles"].append(index)
        elif normalized.startswith("любая доп. информация"):
            mapping["notes"] = index

    if not mapping["additional_roles"]:
        mapping.pop("additional_roles")

    return mapping


def get_row_value(row: list[str], index: int | None) -> str | None:
    if index is None or index < 0 or index >= len(row):
        return None
    value = row[index].strip()
    return value or None


def get_row_values(row: list[str], indexes: list[int] | None) -> list[str]:
    if not indexes:
        return []
    values = [get_row_value(row, index) for index in indexes]
    return [value for value in values if value]


def resolve_rank_from_division(division_number: int | None, grid: DivisionGrid = DEFAULT_GRID) -> int | None:
    if division_number is None:
        return None
    return grid.resolve_rank_from_division(division_number)


def resolve_division_from_rank(rank_value: int | None, grid: DivisionGrid = DEFAULT_GRID) -> int | None:
    if rank_value is None:
        return None
    return resolve_tournament_division(
        rank_value,
        tournament_grid=grid,
    )


async def get_tournament_sheet(session: AsyncSession, tournament_id: int) -> models.BalancerTournamentSheet | None:
    result = await session.execute(
        sa.select(models.BalancerTournamentSheet).where(models.BalancerTournamentSheet.tournament_id == tournament_id)
    )
    return result.scalar_one_or_none()


async def require_tournament_sheet(session: AsyncSession, tournament_id: int) -> models.BalancerTournamentSheet:
    sheet = await get_tournament_sheet(session, tournament_id)
    if sheet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament sheet not found")
    return sheet


async def ensure_tournament_exists(session: AsyncSession, tournament_id: int) -> None:
    result = await session.execute(sa.select(models.Tournament.id).where(models.Tournament.id == tournament_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")


async def get_tournament_workspace_id(session: AsyncSession, tournament_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return int(workspace_id)


async def get_tournament_config(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerTournamentConfig | None:
    result = await session.execute(
        sa.select(models.BalancerTournamentConfig).where(
            models.BalancerTournamentConfig.tournament_id == tournament_id
        )
    )
    return result.scalar_one_or_none()


async def upsert_tournament_config(
    session: AsyncSession,
    tournament_id: int,
    config_json: dict[str, Any] | None,
    auth_user: models.AuthUser,
) -> models.BalancerTournamentConfig:
    workspace_id = await get_tournament_workspace_id(session, tournament_id)
    normalized_config = normalize_tournament_config_payload(config_json)
    tournament_config = await get_tournament_config(session, tournament_id)

    if tournament_config is None:
        tournament_config = models.BalancerTournamentConfig(
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            config_json=normalized_config,
            updated_by=auth_user.id,
            updated_at=datetime.now(UTC),
        )
        session.add(tournament_config)
    else:
        tournament_config.workspace_id = workspace_id
        tournament_config.config_json = normalized_config
        tournament_config.updated_by = auth_user.id
        tournament_config.updated_at = datetime.now(UTC)

    await session.commit()
    return tournament_config


async def upsert_tournament_sheet(
    session: AsyncSession,
    tournament_id: int,
    data: admin_schemas.BalancerTournamentSheetUpsert,
) -> models.BalancerTournamentSheet:
    await ensure_tournament_exists(session, tournament_id)

    sheet_id, gid = extract_sheet_source(data.source_url)
    sheet = await get_tournament_sheet(session, tournament_id)
    role_mapping = data.role_mapping_json or DEFAULT_ROLE_MAPPING

    if sheet is None:
        sheet = models.BalancerTournamentSheet(
            tournament_id=tournament_id,
            source_url=data.source_url,
            sheet_id=sheet_id,
            gid=gid,
            title=data.title,
            column_mapping_json=data.column_mapping_json,
            role_mapping_json=role_mapping,
            last_sync_status="pending",
        )
        session.add(sheet)
    else:
        sheet.source_url = data.source_url
        sheet.sheet_id = sheet_id
        sheet.gid = gid
        sheet.title = data.title
        if data.column_mapping_json is not None:
            sheet.column_mapping_json = data.column_mapping_json
        if data.role_mapping_json is not None:
            sheet.role_mapping_json = data.role_mapping_json

    await session.commit()
    await session.refresh(sheet)
    return sheet


async def fetch_google_sheet_rows(sheet: models.BalancerTournamentSheet) -> list[list[str]]:
    url = build_csv_export_url(sheet.sheet_id, sheet.gid)
    async with httpx.AsyncClient(timeout=GOOGLE_SHEET_FETCH_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    return fetch_csv_rows(response.text)


def build_application_payload(
    row: list[str],
    headers: list[str],
    column_mapping: dict[str, Any],
    role_mapping: dict[str, str | None],
) -> dict[str, Any] | None:
    battle_tag = normalize_battle_tag(get_row_value(row, column_mapping.get("battle_tag")))
    battle_tag_normalized = normalize_battle_tag_key(battle_tag)
    if not battle_tag_normalized:
        return None

    primary_role_raw = get_row_value(row, column_mapping.get("primary_role"))
    additional_roles_raw = get_row_values(row, column_mapping.get("additional_roles"))
    notes = get_row_value(row, column_mapping.get("notes"))
    primary_role, additional_roles, _ = parse_application_roles(
        primary_role_raw,
        additional_roles_raw,
        role_mapping,
        [notes] if notes else None,
    )

    submitted_at = parse_submitted_at(get_row_value(row, column_mapping.get("timestamp")))
    return {
        "battle_tag": battle_tag,
        "battle_tag_normalized": battle_tag_normalized,
        "smurf_tags_json": extract_battle_tags(get_row_value(row, column_mapping.get("smurf_tags"))),
        "twitch_nick": get_row_value(row, column_mapping.get("twitch_nick")),
        "discord_nick": get_row_value(row, column_mapping.get("discord_nick")),
        "stream_pov": parse_bool(get_row_value(row, column_mapping.get("stream_pov"))),
        "last_tournament_text": get_row_value(row, column_mapping.get("last_tournament_text")),
        "primary_role": primary_role,
        "additional_roles_json": additional_roles,
        "notes": notes,
        "raw_row_json": row_to_json(headers, row),
        "submitted_at": submitted_at,
    }


async def sync_tournament_sheet(
    session: AsyncSession,
    tournament_id: int,
) -> tuple[models.BalancerTournamentSheet, int, int, int, int]:
    sheet = await require_tournament_sheet(session, tournament_id)

    try:
        rows = await fetch_google_sheet_rows(sheet)
        headers = rows[0]
        detected_mapping = detect_column_mapping(headers)
        column_mapping = sheet.column_mapping_json or detected_mapping
        role_mapping = {**DEFAULT_ROLE_MAPPING, **(sheet.role_mapping_json or {})}

        if column_mapping.get("battle_tag") is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Battle tag column not detected")

        latest_payloads: dict[str, tuple[int, dict[str, Any]]] = {}
        for row_index, row in enumerate(rows[1:], start=1):
            payload = build_application_payload(row, headers, column_mapping, role_mapping)
            if payload is None:
                continue

            ordering_key = payload["submitted_at"].timestamp() if payload["submitted_at"] else row_index
            existing = latest_payloads.get(payload["battle_tag_normalized"])
            if existing is None or ordering_key >= existing[0]:
                latest_payloads[payload["battle_tag_normalized"]] = (int(ordering_key), payload)

        result = await session.execute(
            sa.select(models.BalancerApplication)
            .where(models.BalancerApplication.tournament_id == tournament_id)
            .options(selectinload(models.BalancerApplication.player))
        )
        existing_applications = {
            application.battle_tag_normalized: application for application in result.scalars().all()
        }

        created = 0
        updated = 0
        seen_keys: set[str] = set()
        sync_time = datetime.now(UTC)

        for normalized_tag, (_, payload) in latest_payloads.items():
            seen_keys.add(normalized_tag)
            application = existing_applications.get(normalized_tag)
            if application is None:
                application = models.BalancerApplication(
                    tournament_id=tournament_id,
                    tournament_sheet_id=sheet.id,
                    synced_at=sync_time,
                    is_active=True,
                    **payload,
                )
                session.add(application)
                created += 1
                continue

            application.tournament_sheet_id = sheet.id
            application.battle_tag = payload["battle_tag"]
            application.smurf_tags_json = payload["smurf_tags_json"]
            application.twitch_nick = payload["twitch_nick"]
            application.discord_nick = payload["discord_nick"]
            application.stream_pov = payload["stream_pov"]
            application.last_tournament_text = payload["last_tournament_text"]
            application.primary_role = payload["primary_role"]
            application.additional_roles_json = payload["additional_roles_json"]
            application.notes = payload["notes"]
            application.raw_row_json = payload["raw_row_json"]
            application.submitted_at = payload["submitted_at"]
            application.synced_at = sync_time
            application.is_active = True
            updated += 1

        deactivated = 0
        for normalized_tag, application in existing_applications.items():
            if normalized_tag in seen_keys or not application.is_active:
                continue
            application.is_active = False
            application.synced_at = sync_time
            deactivated += 1

        sheet.header_row_json = headers
        sheet.column_mapping_json = column_mapping
        sheet.role_mapping_json = role_mapping
        sheet.last_synced_at = sync_time
        sheet.last_sync_status = "success"
        sheet.last_error = None

        await session.commit()
        await session.refresh(sheet)
        return sheet, created, updated, deactivated, len(latest_payloads)
    except HTTPException as exc:
        sheet.last_sync_status = "failed"
        sheet.last_error = str(exc.detail)
        sheet.last_synced_at = datetime.now(UTC)
        await session.commit()
        raise
    except httpx.HTTPError as exc:
        sheet.last_sync_status = "failed"
        sheet.last_error = str(exc)
        sheet.last_synced_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to fetch Google Sheet") from exc


async def list_applications(
    session: AsyncSession,
    tournament_id: int,
    *,
    include_inactive: bool = False,
) -> list[models.BalancerApplication]:
    query = (
        sa.select(models.BalancerApplication)
        .where(models.BalancerApplication.tournament_id == tournament_id)
        .options(
            selectinload(models.BalancerApplication.player).selectinload(
                models.BalancerPlayer.role_entries
            )
        )
        .order_by(models.BalancerApplication.battle_tag_normalized.asc())
    )
    if not include_inactive:
        query = query.where(models.BalancerApplication.is_active.is_(True))

    result = await session.execute(query)
    return list(result.scalars().all())


async def resolve_public_user_id_for_application(
    session: AsyncSession,
    application: models.BalancerApplication,
) -> int | None:
    user_payload = UserCSV(
        battle_tag=application.battle_tag,
        discord=application.discord_nick,
        twitch=application.twitch_nick,
        smurfs=application.smurf_tags_json or [],
    )
    user = await user_service.find_by_csv(session, user_payload)
    return user.id if user else None


async def create_players_from_applications(
    session: AsyncSession,
    tournament_id: int,
    data: admin_schemas.BalancerPlayerCreateRequest,
) -> list[models.BalancerPlayer]:
    if not data.application_ids:
        return []

    result = await session.execute(
        sa.select(models.BalancerApplication)
        .where(
            models.BalancerApplication.tournament_id == tournament_id,
            models.BalancerApplication.id.in_(data.application_ids),
        )
        .options(
            selectinload(models.BalancerApplication.player).selectinload(
                models.BalancerPlayer.role_entries
            )
        )
    )
    applications = list(result.scalars().all())
    if not applications:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Applications not found")

    created_players: list[tuple[models.BalancerPlayer, list[dict[str, Any]]]] = []
    for application in applications:
        if application.player is not None:
            continue

        role_entries = build_role_entries_from_application(application)
        user_id = await resolve_public_user_id_for_application(session, application)

        player = models.BalancerPlayer(
            tournament_id=tournament_id,
            application_id=application.id,
            battle_tag=application.battle_tag,
            battle_tag_normalized=application.battle_tag_normalized,
            user_id=user_id,
            is_flex=False,
            is_in_pool=True,
        )
        session.add(player)
        created_players.append((player, role_entries))

    await session.flush()

    for player, role_entries in created_players:
        await _write_player_role_entries(session, player, role_entries)

    await session.commit()

    result = await session.execute(
        sa.select(models.BalancerPlayer)
        .where(models.BalancerPlayer.tournament_id == tournament_id)
        .where(models.BalancerPlayer.application_id.in_(data.application_ids))
        .options(selectinload(models.BalancerPlayer.role_entries))
        .order_by(models.BalancerPlayer.battle_tag_normalized.asc())
    )
    return list(result.scalars().all())


async def fetch_latest_ow_ranks_by_user_ids(
    session: AsyncSession,
    user_ids: list[int],
) -> dict[int, dict[str, int]]:
    """Return the latest mapped rank_value per (user_id, role).

    Result shape: {user_id: {role_code: rank_value}}.
    Only entries where rank_value IS NOT NULL are included.
    """
    if not user_ids:
        return {}

    subq = (
        sa.select(
            UserRankSnapshot.user_id,
            UserRankSnapshot.role,
            UserRankSnapshot.rank_value,
            sa.func.row_number()
            .over(
                partition_by=[UserRankSnapshot.user_id, UserRankSnapshot.role],
                order_by=UserRankSnapshot.captured_at.desc(),
            )
            .label("rn"),
        )
        .where(
            UserRankSnapshot.user_id.in_(user_ids),
            UserRankSnapshot.rank_value.is_not(None),
        )
        .subquery()
    )
    query = sa.select(subq.c.user_id, subq.c.role, subq.c.rank_value).where(subq.c.rn == 1)
    result = await session.execute(query)

    out: dict[int, dict[str, int]] = {}
    for uid, role, rank_value in result:
        out.setdefault(uid, {})[role] = rank_value
    return out


def normalize_ow_ranks_to_grid(
    raw_by_user: dict[int, dict[str, int]],
    grid: DivisionGrid,
) -> dict[int, dict[str, int]]:
    """Map raw OW2 SR values to workspace-grid rank points (tier.rank_min).

    Mirrors the registration autofill mapping (``_map_ow_snapshot_rank``): a raw OW2 SR is
    resolved to a tier via ``ow_rank_min``/``ow_rank_max`` and replaced with that tier's
    ``rank_min`` so it lives on the same scale as the balancer ``rank_value``. Entries whose
    SR does not fall into any configured tier are dropped (so ``ow_rank_value`` stays ``None``
    and no spurious delta is computed).
    """
    out: dict[int, dict[str, int]] = {}
    for user_id, by_role in raw_by_user.items():
        for role, ow_rank in by_role.items():
            tier = grid.resolve_division_from_ow_rank(ow_rank)
            if tier is not None:
                out.setdefault(user_id, {})[role] = tier.rank_min
    return out


async def get_workspace_balancer_config(
    session: AsyncSession,
    workspace_id: int,
) -> WorkspaceBalancerConfig | None:
    result = await session.execute(
        sa.select(WorkspaceBalancerConfig).where(
            WorkspaceBalancerConfig.workspace_id == workspace_id
        )
    )
    return result.scalar_one_or_none()


async def upsert_workspace_balancer_config(
    session: AsyncSession,
    workspace_id: int,
    rank_delta_threshold: int | None,
    rank_delta_hide_from_pool: bool,
    updated_by: int | None,
) -> WorkspaceBalancerConfig:
    config = await get_workspace_balancer_config(session, workspace_id)
    payload: dict[str, Any] = {
        "rank_delta_threshold": rank_delta_threshold,
        "rank_delta_hide_from_pool": rank_delta_hide_from_pool,
    }
    if config is None:
        config = WorkspaceBalancerConfig(
            workspace_id=workspace_id,
            config_json=payload,
            updated_by=updated_by,
        )
        session.add(config)
    else:
        config.config_json = payload
        config.updated_by = updated_by
    await session.commit()
    await session.refresh(config)
    return config


async def list_players(
    session: AsyncSession,
    tournament_id: int,
    *,
    in_pool_only: bool = False,
) -> list[models.BalancerPlayer]:
    query = (
        sa.select(models.BalancerPlayer)
        .where(models.BalancerPlayer.tournament_id == tournament_id)
        .options(selectinload(models.BalancerPlayer.role_entries))
        .order_by(models.BalancerPlayer.battle_tag_normalized.asc())
    )
    if in_pool_only:
        query = query.where(models.BalancerPlayer.is_in_pool.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_player(session: AsyncSession, player_id: int) -> models.BalancerPlayer:
    result = await session.execute(
        sa.select(models.BalancerPlayer)
        .where(models.BalancerPlayer.id == player_id)
        .options(selectinload(models.BalancerPlayer.role_entries))
    )
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balancer player not found")
    return player


async def update_player(
    session: AsyncSession,
    player_id: int,
    data: admin_schemas.BalancerPlayerUpdate,
) -> models.BalancerPlayer:
    player = await get_player(session, player_id)
    update_data = data.model_dump(exclude_unset=True)

    role_entries: list[dict[str, Any]] | None = None
    if "role_entries_json" in update_data:
        role_entries = update_data.pop("role_entries_json")

    if "is_flex" in update_data:
        player.is_flex = bool(update_data["is_flex"])

    for field, value in update_data.items():
        if field == "is_flex":
            continue
        setattr(player, field, value)

    await session.flush()
    if role_entries is not None:
        await _write_player_role_entries(session, player, role_entries)

    await session.commit()
    await session.refresh(player)
    return player


async def delete_player(session: AsyncSession, player_id: int) -> None:
    player = await get_player(session, player_id)
    await session.delete(player)
    await session.commit()


async def preview_player_import(
    session: AsyncSession,
    tournament_id: int,
    payload: dict[str, Any],
    *,
    match_application_roles: bool = False,
) -> admin_schemas.BalancerPlayerImportPreviewResponse:
    await ensure_tournament_exists(session, tournament_id)
    imported_players, skipped_entries = parse_imported_player_nodes(payload)
    applications, existing_players = await resolve_import_context(session, tournament_id, imported_players)

    duplicates: list[admin_schemas.BalancerPlayerImportDuplicate] = []
    skipped = [admin_schemas.BalancerPlayerImportSkipped.model_validate(entry) for entry in skipped_entries]
    creatable_players = 0

    for imported_player in imported_players:
        application = applications.get(imported_player["battle_tag_normalized"])
        if application is None:
            skipped.append(
                admin_schemas.BalancerPlayerImportSkipped(
                    battle_tag=imported_player["battle_tag"],
                    battle_tag_normalized=imported_player["battle_tag_normalized"],
                    reason="missing_active_application",
                )
            )
            continue

        imported_role_entries = (
            map_imported_role_entries_to_application(application, imported_player["role_entries_json"])
            if match_application_roles
            else imported_player["role_entries_json"]
        )
        existing_player = existing_players.get(application.id)
        if existing_player is None:
            creatable_players += 1
            continue

        duplicates.append(
            admin_schemas.BalancerPlayerImportDuplicate(
                battle_tag=imported_player["battle_tag"],
                battle_tag_normalized=imported_player["battle_tag_normalized"],
                application_id=application.id,
                existing_player_id=existing_player.id,
                imported_role_entries_json=imported_role_entries,
                existing_role_entries_json=[
                    {
                        "role": e.role,
                        "subtype": e.subtype,
                        "priority": e.priority,
                        "rank_value": e.rank_value,
                        "division_number": e.division_number,
                        "is_active": e.is_active,
                    }
                    for e in sorted(existing_player.role_entries, key=lambda e: e.priority)
                ],
                imported_is_in_pool=imported_player["is_in_pool"],
                existing_is_in_pool=existing_player.is_in_pool,
                imported_admin_notes=imported_player["admin_notes"],
                existing_admin_notes=existing_player.admin_notes,
            )
        )

    return admin_schemas.BalancerPlayerImportPreviewResponse(
        total_players=len(imported_players) + len(skipped_entries),
        creatable_players=creatable_players,
        duplicate_players=len(duplicates),
        skipped_players=len(skipped),
        duplicates=duplicates,
        skipped=skipped,
    )


async def import_players(
    session: AsyncSession,
    tournament_id: int,
    payload: dict[str, Any],
    *,
    duplicate_strategy: admin_schemas.DuplicateStrategy,
    resolutions: dict[str, admin_schemas.DuplicateResolution] | None = None,
    match_application_roles: bool = False,
) -> admin_schemas.BalancerPlayerImportResult:
    await ensure_tournament_exists(session, tournament_id)
    imported_players, skipped_entries = parse_imported_player_nodes(payload)
    applications, existing_players = await resolve_import_context(session, tournament_id, imported_players)

    created = 0
    replaced = 0
    skipped_duplicates = 0
    skipped_missing_application = 0
    skipped_duplicate_in_file = sum(1 for entry in skipped_entries if entry["reason"] == "duplicate_in_file")
    skipped_no_ranked_roles = sum(1 for entry in skipped_entries if entry["reason"] == "no_ranked_roles")
    unresolved_duplicates: list[str] = []
    resolutions = resolutions or {}
    pending_role_writes: list[tuple[models.BalancerPlayer, list[dict[str, Any]]]] = []

    for imported_player in imported_players:
        application = applications.get(imported_player["battle_tag_normalized"])
        if application is None:
            skipped_missing_application += 1
            continue

        imported_role_entries = (
            map_imported_role_entries_to_application(application, imported_player["role_entries_json"])
            if match_application_roles
            else imported_player["role_entries_json"]
        )

        existing_player = existing_players.get(application.id)
        if existing_player is None:
            user_id = await resolve_public_user_id_for_application(session, application)
            player = models.BalancerPlayer(
                tournament_id=tournament_id,
                application_id=application.id,
                battle_tag=application.battle_tag,
                battle_tag_normalized=application.battle_tag_normalized,
                user_id=user_id,
                is_flex=bool(imported_player["is_flex"]) if imported_player["is_flex"] is not None else False,
                is_in_pool=imported_player["is_in_pool"],
                admin_notes=imported_player["admin_notes"],
            )
            session.add(player)
            pending_role_writes.append((player, imported_role_entries))
            created += 1
            continue

        if duplicate_strategy == "replace_all":
            resolution = "replace"
        elif duplicate_strategy == "skip_all":
            resolution = "skip"
        else:
            resolution = resolutions.get(imported_player["battle_tag_normalized"])
            if resolution not in {"replace", "skip"}:
                unresolved_duplicates.append(imported_player["battle_tag"])
                continue

        if resolution == "skip":
            skipped_duplicates += 1
            continue

        user_id = await resolve_public_user_id_for_application(session, application)
        existing_player.battle_tag = application.battle_tag
        existing_player.battle_tag_normalized = application.battle_tag_normalized
        existing_player.user_id = user_id
        if imported_player["is_flex"] is not None:
            existing_player.is_flex = imported_player["is_flex"]
        existing_player.is_in_pool = imported_player["is_in_pool"]
        if imported_player["admin_notes"] is not None:
            existing_player.admin_notes = imported_player["admin_notes"]
        pending_role_writes.append((existing_player, imported_role_entries))
        replaced += 1

    if unresolved_duplicates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unresolved duplicate players: {', '.join(unresolved_duplicates)}",
        )

    await session.flush()
    for player, role_entries in pending_role_writes:
        await _write_player_role_entries(session, player, role_entries)

    await session.commit()
    return admin_schemas.BalancerPlayerImportResult(
        success=True,
        created=created,
        replaced=replaced,
        skipped_duplicates=skipped_duplicates,
        skipped_missing_application=skipped_missing_application,
        skipped_duplicate_in_file=skipped_duplicate_in_file,
        skipped_no_ranked_roles=skipped_no_ranked_roles,
        total_players=len(imported_players) + len(skipped_entries),
    )


async def export_players(
    session: AsyncSession,
    tournament_id: int,
) -> admin_schemas.BalancerPlayerExportResponse:
    await ensure_tournament_exists(session, tournament_id)
    players = await list_players(session, tournament_id)
    serialized_players: dict[str, Any] = {}
    for player in players:
        export_uuid = str(uuid4())
        serialized_players[export_uuid] = serialize_player_for_export(player, export_uuid)
    return admin_schemas.BalancerPlayerExportResponse(format="xv-1", players=serialized_players)


async def sync_player_roles_from_applications(
    session: AsyncSession,
    tournament_id: int,
) -> admin_schemas.BalancerPlayerRoleSyncResponse:
    await ensure_tournament_exists(session, tournament_id)

    result = await session.execute(
        sa.select(models.BalancerPlayer)
        .where(models.BalancerPlayer.tournament_id == tournament_id)
        .options(
            selectinload(models.BalancerPlayer.application),
            selectinload(models.BalancerPlayer.role_entries),
        )
        .order_by(models.BalancerPlayer.battle_tag_normalized.asc())
    )
    players = list(result.scalars().all())

    updated = 0
    skipped = 0
    pending_role_writes: list[tuple[models.BalancerPlayer, list[dict[str, Any]]]] = []
    for player in players:
        application = player.application
        if application is None or not application.is_active:
            skipped += 1
            continue

        existing_entries = [
            {
                "role": e.role,
                "subtype": e.subtype,
                "priority": e.priority,
                "rank_value": e.rank_value,
                "division_number": e.division_number,
                "is_active": e.is_active,
            }
            for e in player.role_entries
        ]
        role_entries = map_existing_role_entries_to_application(application, existing_entries)
        pending_role_writes.append((player, role_entries))
        updated += 1

    await session.flush()
    for player, role_entries in pending_role_writes:
        await _write_player_role_entries(session, player, role_entries)

    await session.commit()
    return admin_schemas.BalancerPlayerRoleSyncResponse(updated=updated, skipped=skipped)


async def export_applications_to_users(
    session: AsyncSession,
    tournament_id: int,
) -> admin_schemas.ApplicationUserExportResponse:
    await ensure_tournament_exists(session, tournament_id)
    applications = await list_applications(session, tournament_id, include_inactive=False)

    processed = 0
    skipped = 0
    for application in applications:
        smurfs = [tag for tag in (application.smurf_tags_json or []) if BATTLE_TAG_RE.match(tag)]
        try:
            payload = UserCSV(
                battle_tag=application.battle_tag,
                discord=application.discord_nick,
                twitch=application.twitch_nick,
                smurfs=smurfs,
            )
        except Exception:
            logger.exception("Failed to build user payload for application %s", application.battle_tag)
            skipped += 1
            continue

        await user_flows.create(session, payload)
        processed += 1

    return admin_schemas.ApplicationUserExportResponse(
        processed=processed,
        skipped=skipped,
        total=len(applications),
    )


async def get_balance(session: AsyncSession, tournament_id: int) -> models.BalancerBalance | None:
    result = await session.execute(
        sa.select(models.BalancerBalance)
        .where(models.BalancerBalance.tournament_id == tournament_id)
        .options(selectinload(models.BalancerBalance.teams))
    )
    return result.scalar_one_or_none()


def materialize_balance_teams(
    balance_id: int,
    payload: InternalBalancerTeamsPayload,
) -> list[models.BalancerTeam]:
    teams: list[models.BalancerTeam] = []
    for sort_order, team in enumerate(payload.teams):
        total_sr = sum(player.assigned_rating for players in team.roster.values() for player in players)
        teams.append(
            models.BalancerTeam(
                balance_id=balance_id,
                exported_team_id=None,
                name=team.name.split("#")[0],
                balancer_name=team.name,
                captain_battle_tag=team.name,
                avg_sr=team.average_mmr,
                total_sr=total_sr,
                roster_json=team.model_dump(mode="python", by_alias=True)["roster"],
                sort_order=sort_order,
            )
        )
    return teams


async def save_balance(
    session: AsyncSession,
    tournament_id: int,
    data: admin_schemas.BalanceSaveRequest,
    auth_user: models.AuthUser,
) -> models.BalancerBalance:
    await ensure_tournament_exists(session, tournament_id)
    normalized_config_json = serialize_saved_config_payload(data.config_json)
    normalized_result_json = normalize_balance_response_payload(data.result_json)
    payload = InternalBalancerTeamsPayload.model_validate(normalized_result_json)
    if not payload.teams:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Balance result does not contain teams")

    balance = await get_balance(session, tournament_id)
    if balance is None:
        balance = models.BalancerBalance(
            tournament_id=tournament_id,
            config_json=normalized_config_json,
            result_json=normalized_result_json,
            saved_by=auth_user.id,
            saved_at=datetime.now(UTC),
            export_status=None,
            export_error=None,
            exported_at=None,
        )
        session.add(balance)
        await session.flush()
    else:
        balance.config_json = normalized_config_json
        balance.result_json = normalized_result_json
        balance.saved_by = auth_user.id
        balance.saved_at = datetime.now(UTC)
        balance.export_status = None
        balance.export_error = None
        balance.exported_at = None
        await session.execute(sa.delete(models.BalancerTeam).where(models.BalancerTeam.balance_id == balance.id))

    session.add_all(materialize_balance_teams(balance.id, payload))
    await session.flush()

    algorithm = normalized_config_json.get("algorithm", "unknown") if normalized_config_json else "unknown"
    await sync_balance_variants_and_slots(session, balance, payload, algorithm=algorithm)

    await session.commit()

    saved_balance = await get_balance(session, tournament_id)
    if saved_balance is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save balance")
    return saved_balance


async def ensure_public_user_for_application(
    session: AsyncSession,
    application: models.BalancerApplication,
) -> models.User:
    payload = UserCSV(
        battle_tag=application.battle_tag,
        discord=application.discord_nick,
        twitch=application.twitch_nick,
        smurfs=application.smurf_tags_json or [],
    )
    user = await user_service.find_by_csv(session, payload)
    if user is None:
        user = await user_flows.create(session, payload)
    return user


async def ensure_public_users_for_balance(
    session: AsyncSession,
    tournament_id: int,
    payload: InternalBalancerTeamsPayload,
) -> None:
    normalized_tags = unique_strings(
        [
            normalize_battle_tag_key(player.name)
            for team in payload.teams
            for players in team.roster.values()
            for player in players
        ]
    )
    if not normalized_tags:
        return

    result = await session.execute(
        sa.select(models.BalancerApplication)
        .where(models.BalancerApplication.tournament_id == tournament_id)
        .where(models.BalancerApplication.battle_tag_normalized.in_(normalized_tags))
        .options(selectinload(models.BalancerApplication.player))
    )
    applications = {application.battle_tag_normalized: application for application in result.scalars().all()}

    for normalized_tag in normalized_tags:
        application = applications.get(normalized_tag)
        if application is None:
            continue
        user = await ensure_public_user_for_application(session, application)
        if application.player is not None and application.player.user_id != user.id:
            application.player.user_id = user.id

    await session.commit()


async def export_balance(session: AsyncSession, balance_id: int) -> tuple[models.BalancerBalance, int, int]:
    result = await session.execute(
        sa.select(models.BalancerBalance)
        .where(models.BalancerBalance.id == balance_id)
        .options(selectinload(models.BalancerBalance.teams))
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance not found")

    payload = InternalBalancerTeamsPayload.model_validate(normalize_balance_response_payload(balance.result_json))

    linked_team_ids = [team.exported_team_id for team in balance.teams if team.exported_team_id is not None]
    removed_teams = len(linked_team_ids)

    if linked_team_ids:
        await session.execute(sa.delete(models.Standing).where(models.Standing.team_id.in_(linked_team_ids)))
        await session.execute(sa.delete(models.Player).where(models.Player.team_id.in_(linked_team_ids)))
        await session.execute(sa.delete(models.Team).where(models.Team.id.in_(linked_team_ids)))
        for team in balance.teams:
            team.exported_team_id = None
        await session.commit()

    try:
        await ensure_public_users_for_balance(session, balance.tournament_id, payload)
        balancer_teams = [team.to_balancer_team() for team in payload.teams]
        await team_flows.bulk_create_from_balancer(session, balance.tournament_id, balancer_teams)

        imported_names = [team.name for team in payload.teams]
        result = await session.execute(
            sa.select(models.Team).where(
                models.Team.tournament_id == balance.tournament_id,
                models.Team.balancer_name.in_(imported_names),
            )
        )
        public_teams = {team.balancer_name: team for team in result.scalars().all()}
        for materialized_team in balance.teams:
            public_team = public_teams.get(materialized_team.balancer_name)
            if public_team is not None:
                materialized_team.exported_team_id = public_team.id

        balance.exported_at = datetime.now(UTC)
        balance.export_status = "success"
        balance.export_error = None

        await create_balance_snapshot(session, balance, payload, public_teams)

        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to export balance %s", balance.id)
        balance.export_status = "failed"
        balance.export_error = str(exc)
        await session.commit()
        raise

    refreshed = await get_balance(session, balance.tournament_id)
    if refreshed is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to refresh exported balance"
        )
    return refreshed, removed_teams, len(payload.teams)
