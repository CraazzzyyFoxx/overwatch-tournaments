from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from shared.balancer_registration_statuses import get_builtin_status_values
from shared.hero_catalog import HeroCatalog, resolve_hero_catalog
from shared.core import enums
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.domain.player_sub_roles import normalize_sub_role
from src import models
from src.schemas.user import UserCSV
from src.services import user as user_flows
from src.services.admin.balancer_utils import (
    DEFAULT_BOOLEAN_TRUE_VALUES,
    DEFAULT_ROLE_VALUE_MAP,
    DEFAULT_SORT_PRIORITY_SENTINEL,
    DEFAULT_SUBROLE_VALUE_MAP,
    DEFAULT_SYNC_INTERVAL_SECONDS,
    GOOGLE_SHEET_FETCH_TIMEOUT,
    MIN_SYNC_INTERVAL_SECONDS,
    ROLE_ORDER,
    UNKNOWN_PRIORITY_SENTINEL,
    build_csv_export_url,
    build_header_keys,
    extract_sheet_source,
    fetch_csv_rows,
    normalize_battle_tag,
    normalize_battle_tag_key,
    normalize_header,
    parse_boolean_value,
    parse_datetime,
    parse_integer,
    row_to_json,
    unique_strings,
)
from src.services.admin.balancer_utils import (
    extract_battle_tags as _extract_battle_tags,
)

logger = logging.getLogger(__name__)

VALID_REGISTRATION_STATUSES = get_builtin_status_values("registration")
VALID_BALANCER_STATUSES = get_builtin_status_values("balancer")

BATTLE_TAG_RE = re.compile(r"[\w][\w ]{0,30}#[0-9]{3,}", re.UNICODE)
DEFAULT_MAPPING_TARGETS = (
    "source_record_key",
    "display_name",
    "battle_tag",
    "submitted_at",
    "smurf_tags",
    "discord_nick",
    "twitch_nick",
    "stream_pov",
    "notes",
    "source_roles.primary",
    "source_roles.additional",
    "is_flex",
    "admin_notes",
    "roles.tank.rank_value",
    "roles.tank.division_input",
    "roles.tank.is_active",
    "roles.tank.priority",
    "roles.dps.rank_value",
    "roles.dps.division_input",
    "roles.dps.subrole",
    "roles.dps.is_active",
    "roles.dps.priority",
    "roles.support.rank_value",
    "roles.support.division_input",
    "roles.support.subrole",
    "roles.support.is_active",
    "roles.support.priority",
)


async def fetch_google_sheet_rows(
    source_url: str,
    *,
    sheet_id: str | None = None,
    gid: str | None = None,
) -> list[list[str]]:
    actual_sheet_id, actual_gid = (sheet_id, gid) if sheet_id else extract_sheet_source(source_url)
    url = build_csv_export_url(actual_sheet_id, actual_gid)
    async with httpx.AsyncClient(timeout=GOOGLE_SHEET_FETCH_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    return fetch_csv_rows(response.text)


def parse_boolean(value: str | None, value_mapping: dict[str, Any]) -> bool:
    if value is None:
        return False
    normalized = normalize_header(value)
    custom_booleans = {
        normalize_header(key): bool(mapped_value)
        for key, mapped_value in (value_mapping.get("booleans") or {}).items()
    }
    if normalized in custom_booleans:
        return custom_booleans[normalized]
    return parse_boolean_value(value)


def extract_battle_tags(value: str | None) -> list[str]:
    return _extract_battle_tags(value, BATTLE_TAG_RE)


def map_role_token(value: str | None, value_mapping: dict[str, Any]) -> str | None:
    if value is None:
        return None
    normalized = normalize_header(value)
    custom_map = {
        normalize_header(key): mapped_value
        for key, mapped_value in (value_mapping.get("roles") or {}).items()
    }
    if normalized in custom_map:
        mapped = custom_map[normalized]
        return mapped if mapped in {"tank", "dps", "support"} else None
    if normalized in {"tank", "Ñ‚Ð°Ð½Ðº"} or "Ñ‚Ð°Ð½Ðº" in normalized:
        return "tank"
    if normalized in {"dps", "damage"} or "Ð´Ð´" in normalized or "damage" in normalized:
        return "dps"
    if normalized in {"support", "ÑÐ°Ð¿", "Ð¿Ð¾Ð´Ð´ÐµÑ€Ð¶ÐºÐ°"} or "Ñ…Ð¸Ð»" in normalized or "support" in normalized:
        return "support"
    return None


def map_subrole_token(value: str | None, value_mapping: dict[str, Any]) -> str | None:
    if value is None:
        return None
    normalized = normalize_header(value)
    custom_map = {
        normalize_header(key): mapped_value
        for key, mapped_value in (value_mapping.get("subroles") or {}).items()
    }
    mapped = custom_map.get(normalized)
    if mapped:
        return normalize_sub_role(mapped)
    return DEFAULT_SUBROLE_VALUE_MAP.get(normalized)


def parse_role_token_list(values: list[str], value_mapping: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    for value in values:
        for token in re.split(r"[,/\n]+", value):
            role_code = map_role_token(token, value_mapping)
            if role_code:
                roles.append(role_code)
    return unique_strings(roles)


def build_default_value_mapping() -> dict[str, Any]:
    return {
        "booleans": dict.fromkeys(sorted(DEFAULT_BOOLEAN_TRUE_VALUES), True),
        "roles": DEFAULT_ROLE_VALUE_MAP,
        "subroles": DEFAULT_SUBROLE_VALUE_MAP,
    }


def default_mapping_target(parser: str) -> dict[str, Any]:
    return {"mode": "disabled", "parser": parser}


def _set_target(mapping: dict[str, Any], target_key: str, *, parser: str, columns: list[str] | None = None) -> None:
    if columns:
        mapping["targets"][target_key] = {"mode": "columns", "columns": columns, "parser": parser}


def suggest_mapping_from_headers(headers: list[str]) -> dict[str, Any]:
    header_keys = build_header_keys(headers)
    mapping = {
        "targets": {
            "source_record_key": default_mapping_target("battle_tag"),
            "display_name": default_mapping_target("string"),
            "battle_tag": default_mapping_target("battle_tag"),
            "submitted_at": default_mapping_target("datetime"),
            "smurf_tags": default_mapping_target("battle_tag_list"),
            "discord_nick": default_mapping_target("string"),
            "twitch_nick": default_mapping_target("string"),
            "stream_pov": default_mapping_target("boolean"),
            "notes": default_mapping_target("join_lines"),
            "source_roles.primary": default_mapping_target("role_token"),
            "source_roles.additional": default_mapping_target("role_token_list"),
            "is_flex": default_mapping_target("boolean"),
            "admin_notes": default_mapping_target("join_lines"),
        }
    }
    for role in ("tank", "dps", "support"):
        mapping["targets"][f"roles.{role}.rank_value"] = default_mapping_target("integer")
        mapping["targets"][f"roles.{role}.division_input"] = default_mapping_target("division_to_rank")
        mapping["targets"][f"roles.{role}.is_active"] = default_mapping_target("boolean")
        mapping["targets"][f"roles.{role}.priority"] = default_mapping_target("integer")
        if role != "tank":
            mapping["targets"][f"roles.{role}.subrole"] = default_mapping_target("subrole_token")

    def find_first(predicate: Any) -> str | None:
        for index, header in enumerate(headers):
            if predicate(normalize_header(header)):
                return header_keys[index]
        return None

    def find_all(predicate: Any) -> list[str]:
        return [header_keys[index] for index, header in enumerate(headers) if predicate(normalize_header(header))]

    battle_tag_column = find_first(lambda header: header.startswith("Ð²Ð°Ñˆ battle tag") or "battle tag" in header)
    if battle_tag_column:
        _set_target(mapping, "source_record_key", parser="battle_tag", columns=[battle_tag_column])
        _set_target(mapping, "display_name", parser="string", columns=[battle_tag_column])
        _set_target(mapping, "battle_tag", parser="battle_tag", columns=[battle_tag_column])

    _set_target(mapping, "submitted_at", parser="datetime", columns=[find_first(lambda header: "Ð¾Ñ‚Ð¼ÐµÑ‚ÐºÐ° Ð²Ñ€ÐµÐ¼ÐµÐ½Ð¸" in header)])
    _set_target(mapping, "smurf_tags", parser="battle_tag_list", columns=[find_first(lambda header: "ÑÐ¼ÑƒÑ€Ñ„" in header)])
    _set_target(mapping, "discord_nick", parser="string", columns=[find_first(lambda header: "Ð´Ð¸ÑÐºÐ¾Ñ€" in header)])
    _set_target(mapping, "twitch_nick", parser="string", columns=[find_first(lambda header: "Ñ‚Ð²Ð¸Ñ‡" in header)])
    _set_target(mapping, "stream_pov", parser="boolean", columns=[find_first(lambda header: "ÑÑ‚Ñ€Ð¸Ð¼" in header)])
    _set_target(mapping, "notes", parser="join_lines", columns=[find_first(lambda header: "Ð»ÑŽÐ±Ð°Ñ Ð´Ð¾Ð¿." in header or "Ð¿Ñ€Ð¸Ð¼ÐµÑ‡" in header)])
    _set_target(mapping, "source_roles.primary", parser="role_token", columns=[find_first(lambda header: header.startswith("ÑƒÐºÐ°Ð¶Ð¸Ñ‚Ðµ Ð²Ð°ÑˆÑƒ Ñ€Ð¾Ð»ÑŒ"))])

    additional_role_columns = find_all(lambda header: header.startswith("Ð´Ð¾Ð¿Ð¾Ð»Ð½Ð¸Ñ‚ÐµÐ»ÑŒÐ½Ð°Ñ Ð¸Ð³Ñ€Ð¾Ð²Ð°Ñ Ñ€Ð¾Ð»ÑŒ"))
    if additional_role_columns:
        _set_target(mapping, "source_roles.additional", parser="role_token_list", columns=additional_role_columns)

    return mapping


def serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_check_in_window_active(
    tournament: models.Tournament,
    *,
    now: datetime | None = None,
) -> bool:
    if tournament.status != enums.TournamentStatus.CHECK_IN:
        return False

    current_time = _as_utc(now or datetime.now(UTC))
    opens_at = (
        _as_utc(tournament.check_in_opens_at)
        if tournament.check_in_opens_at is not None
        else None
    )
    closes_at = (
        _as_utc(tournament.check_in_closes_at)
        if tournament.check_in_closes_at is not None
        else None
    )
    return (opens_at is None or opens_at <= current_time) and (
        closes_at is None or current_time <= closes_at
    )


def serialize_parsed_fields(parsed_fields: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(parsed_fields)
    serialized["submitted_at"] = serialize_datetime(parsed_fields.get("submitted_at"))
    return serialized


def get_selector_values(target_config: dict[str, Any] | None, row_json: dict[str, str]) -> list[str]:
    if not target_config:
        return []
    mode = target_config.get("mode")
    if mode == "disabled":
        return []
    if mode == "constant":
        value = target_config.get("value")
        return [] if value is None else [str(value)]
    return [
        row_json[column_name]
        for column_name in target_config.get("columns") or []
        if column_name in row_json and row_json[column_name].strip()
    ]


def parse_target_value(*, parser: str, values: list[str], value_mapping: dict[str, Any], grid: DivisionGrid) -> Any:
    if parser == "string":
        return values[0].strip() if values else None
    if parser == "battle_tag":
        return normalize_battle_tag(values[0]) if values else None
    if parser == "battle_tag_list":
        return extract_battle_tags("\n".join(values))
    if parser == "boolean":
        return parse_boolean(values[0] if values else None, value_mapping)
    if parser == "integer":
        return parse_integer(values[0]) if values else None
    if parser == "datetime":
        return parse_datetime(values[0] if values else None)
    if parser == "role_token":
        return map_role_token(values[0] if values else None, value_mapping)
    if parser == "role_token_list":
        return parse_role_token_list(values, value_mapping)
    if parser == "subrole_token":
        return map_subrole_token(values[0] if values else None, value_mapping)
    if parser == "division_to_rank":
        division_number = parse_integer(values[0] if values else None)
        return grid.resolve_rank_from_division(division_number) if division_number is not None else None
    if parser == "join_lines":
        return "\n".join(value.strip() for value in values if value.strip()) or None
    return values[0] if values else None


def get_tournament_grid_from_rows(
    tournament_row: models.Tournament | None,
    workspace_row: models.Workspace | None,
    fallback_version: models.DivisionGridVersion | None = None,
) -> DivisionGrid:
    if tournament_row and tournament_row.division_grid_version is not None:
        return load_runtime_grid(tournament_row.division_grid_version)
    if workspace_row and workspace_row.default_division_grid_version is not None:
        return load_runtime_grid(workspace_row.default_division_grid_version)
    return load_runtime_grid(fallback_version)


async def get_tournament_grid(session: AsyncSession, tournament_id: int) -> DivisionGrid:
    fallback_version = await session.scalar(
        sa.select(models.DivisionGridVersion)
        .join(models.DivisionGrid, models.DivisionGrid.id == models.DivisionGridVersion.grid_id)
        .options(selectinload(models.DivisionGridVersion.tiers))
        .where(models.DivisionGrid.workspace_id.is_(None))
        .order_by(models.DivisionGridVersion.id.asc())
        .limit(1)
    )
    result = await session.execute(
        sa.select(models.Tournament, models.Workspace)
        .join(models.Workspace, models.Workspace.id == models.Tournament.workspace_id)
        .options(
            selectinload(models.Tournament.division_grid_version).selectinload(models.DivisionGridVersion.tiers),
            selectinload(models.Workspace.default_division_grid_version).selectinload(models.DivisionGridVersion.tiers),
        )
        .where(models.Tournament.id == tournament_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    tournament_row, workspace_row = row
    return get_tournament_grid_from_rows(tournament_row, workspace_row, fallback_version)


def parse_sheet_row(
    *,
    headers: list[str],
    row: list[str],
    mapping_config: dict[str, Any] | None,
    value_mapping: dict[str, Any] | None,
    grid: DivisionGrid,
) -> dict[str, Any] | None:
    effective_mapping = mapping_config or suggest_mapping_from_headers(headers)
    targets = effective_mapping.get("targets") or {}
    row_json = row_to_json(headers, row)
    effective_value_mapping = {**build_default_value_mapping(), **(value_mapping or {})}

    flat_values: dict[str, Any] = {}
    for target_key in DEFAULT_MAPPING_TARGETS:
        target_config = targets.get(target_key)
        values = get_selector_values(target_config, row_json)
        parser = (target_config or {}).get("parser", "string")
        flat_values[target_key] = parse_target_value(
            parser=parser,
            values=values,
            value_mapping=effective_value_mapping,
            grid=grid,
        )

    source_record_key = flat_values.get("source_record_key") or flat_values.get("battle_tag")
    if isinstance(source_record_key, str):
        source_record_key = normalize_battle_tag_key(source_record_key) or source_record_key.strip()
    if not source_record_key:
        return None

    return {
        "source_record_key": str(source_record_key),
        "display_name": flat_values.get("display_name") or flat_values.get("battle_tag"),
        "battle_tag": normalize_battle_tag(flat_values.get("battle_tag")),
        "submitted_at": flat_values.get("submitted_at"),
        "smurf_tags": flat_values.get("smurf_tags") or [],
        "discord_nick": flat_values.get("discord_nick"),
        "twitch_nick": flat_values.get("twitch_nick"),
        "stream_pov": bool(flat_values.get("stream_pov", False)),
        "notes": flat_values.get("notes"),
        "source_roles": {
            "primary": flat_values.get("source_roles.primary"),
            "additional": flat_values.get("source_roles.additional") or [],
        },
        "is_flex": bool(flat_values.get("is_flex", False)),
        "admin_notes": flat_values.get("admin_notes"),
        "roles": {
            "tank": {
                "rank_value": flat_values.get("roles.tank.rank_value") or flat_values.get("roles.tank.division_input"),
                "subrole": None,
                "is_active": bool(flat_values.get("roles.tank.is_active", False)),
                "priority": flat_values.get("roles.tank.priority"),
            },
            "dps": {
                "rank_value": flat_values.get("roles.dps.rank_value") or flat_values.get("roles.dps.division_input"),
                "subrole": flat_values.get("roles.dps.subrole"),
                "is_active": bool(flat_values.get("roles.dps.is_active", False)),
                "priority": flat_values.get("roles.dps.priority"),
            },
            "support": {
                "rank_value": flat_values.get("roles.support.rank_value") or flat_values.get("roles.support.division_input"),
                "subrole": flat_values.get("roles.support.subrole"),
                "is_active": bool(flat_values.get("roles.support.is_active", False)),
                "priority": flat_values.get("roles.support.priority"),
            },
        },
    }


def build_registration_role_payloads(parsed_fields: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    source_primary = parsed_fields.get("source_roles", {}).get("primary")
    source_additional = parsed_fields.get("source_roles", {}).get("additional") or []
    is_full_flex = bool(parsed_fields.get("is_flex", False))
    for fallback_priority, role_code in enumerate(ROLE_ORDER):
        role_data = parsed_fields.get("roles", {}).get(role_code) or {}
        rank_value = role_data.get("rank_value")
        subrole = role_data.get("subrole")
        is_active = role_data.get("is_active")
        priority = role_data.get("priority")
        declared_in_source = source_primary == role_code or role_code in source_additional
        if rank_value is None and not is_active and not subrole and priority is None and not declared_in_source:
            continue
        payloads.append(
            {
                "role": role_code,
                "subrole": subrole,
                "is_primary": is_full_flex or source_primary == role_code or (source_primary is None and fallback_priority == 0),
                "priority": int(priority) if isinstance(priority, int) else fallback_priority,
                "rank_value": rank_value,
                "is_active": bool(is_active) if is_active is not None else rank_value is not None,
            }
        )
    return payloads


def registration_source(registration: models.BalancerRegistration) -> str:
    return "google_sheets" if registration.google_sheet_binding is not None else "manual"


def serialize_registration_for_export(registration: models.BalancerRegistration, export_uuid: str) -> dict[str, Any]:
    role_entries = sorted(registration.roles, key=lambda role: role.priority)
    role_map = {role.role: role for role in role_entries}
    is_full_flex = registration.is_flex_computed

    def build_class(role_code: str) -> dict[str, Any]:
        role = role_map.get(role_code)
        return {
            "isActive": bool(role and role.is_active and role.rank_value is not None),
            "rank": int(role.rank_value) if role and role.rank_value is not None else 0,
            "priority": 0 if is_full_flex else int(role.priority) if role else UNKNOWN_PRIORITY_SENTINEL,
            "subtype": role.subrole if role else None,
        }

    return {
        "uuid": export_uuid,
        "identity": {
            "name": registration.battle_tag or registration.display_name or f"registration-{registration.id}",
            "isFullFlex": is_full_flex,
        },
        "stats": {
            "classes": {
                "tank": build_class("tank"),
                "dps": build_class("dps"),
                "support": build_class("support"),
            }
        },
    }


async def ensure_tournament_exists(session: AsyncSession, tournament_id: int) -> models.Tournament:
    result = await session.execute(sa.select(models.Tournament).where(models.Tournament.id == tournament_id))
    tournament = result.scalar_one_or_none()
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


async def get_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerRegistrationGoogleSheetFeed | None:
    result = await session.execute(
        sa.select(models.BalancerRegistrationGoogleSheetFeed).where(
            models.BalancerRegistrationGoogleSheetFeed.tournament_id == tournament_id
        )
    )
    return result.scalar_one_or_none()


async def require_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerRegistrationGoogleSheetFeed:
    feed = await get_google_sheet_feed(session, tournament_id)
    if feed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Google Sheets feed not configured")
    return feed


async def upsert_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str,
    title: str | None,
    auto_sync_enabled: bool,
    auto_sync_interval_seconds: int,
    mapping_config_json: dict[str, Any] | None,
    value_mapping_json: dict[str, Any] | None,
) -> models.BalancerRegistrationGoogleSheetFeed:
    tournament = await ensure_tournament_exists(session, tournament_id)
    sheet_id, gid = extract_sheet_source(source_url)
    feed = await get_google_sheet_feed(session, tournament_id)
    if feed is None:
        feed = models.BalancerRegistrationGoogleSheetFeed(
            tournament_id=tournament.id,
            source_url=source_url,
            sheet_id=sheet_id,
            gid=gid,
            title=title,
            auto_sync_enabled=auto_sync_enabled,
            auto_sync_interval_seconds=auto_sync_interval_seconds,
            mapping_config_json=mapping_config_json,
            value_mapping_json=value_mapping_json,
            last_sync_status="pending",
        )
        session.add(feed)
    else:
        feed.source_url = source_url
        feed.sheet_id = sheet_id
        feed.gid = gid
        feed.title = title
        feed.auto_sync_enabled = auto_sync_enabled
        feed.auto_sync_interval_seconds = auto_sync_interval_seconds
        if mapping_config_json is not None:
            feed.mapping_config_json = mapping_config_json
        if value_mapping_json is not None:
            feed.value_mapping_json = value_mapping_json

    await session.commit()
    await session.refresh(feed)
    return feed


async def suggest_google_sheet_mapping(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str | None = None,
) -> tuple[models.BalancerRegistrationGoogleSheetFeed | None, list[str], dict[str, Any]]:
    feed = await get_google_sheet_feed(session, tournament_id)
    url = source_url or (feed.source_url if feed else None)
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets URL is required")
    rows = await fetch_google_sheet_rows(url)
    headers = rows[0]
    return feed, headers, suggest_mapping_from_headers(headers)


async def preview_google_sheet_mapping(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str | None = None,
    mapping_config_json: dict[str, Any] | None = None,
    value_mapping_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    feed = await get_google_sheet_feed(session, tournament_id)
    url = source_url or (feed.source_url if feed else None)
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets URL is required")

    rows = await fetch_google_sheet_rows(url)
    headers = rows[0]
    sample_row = rows[1] if len(rows) > 1 else []
    grid = await get_tournament_grid(session, tournament_id)
    parsed = parse_sheet_row(
        headers=headers,
        row=sample_row,
        mapping_config=mapping_config_json or (feed.mapping_config_json if feed else None),
        value_mapping=value_mapping_json or (feed.value_mapping_json if feed else None),
        grid=grid,
    )
    return {
        "headers": headers,
        "sample_raw_row": row_to_json(headers, sample_row),
        "parsed_fields": serialize_parsed_fields(parsed or {}),
    }


async def list_registrations(
    session: AsyncSession,
    tournament_id: int,
    *,
    status_filter: str | None = None,
    inclusion_filter: str | None = None,
    source_filter: str | None = None,
    include_deleted: bool = False,
) -> list[models.BalancerRegistration]:
    query = (
        sa.select(models.BalancerRegistration)
        .where(models.BalancerRegistration.tournament_id == tournament_id)
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero),
            selectinload(models.BalancerRegistration.auth_user),
            selectinload(models.BalancerRegistration.reviewer),
            selectinload(models.BalancerRegistration.deleted_by_user),
            selectinload(models.BalancerRegistration.checked_in_by_user),
            selectinload(models.BalancerRegistration.google_sheet_binding).selectinload(
                models.BalancerRegistrationGoogleSheetBinding.feed
            ),
        )
        .order_by(models.BalancerRegistration.submitted_at.desc(), models.BalancerRegistration.id.desc())
    )
    if not include_deleted:
        query = query.where(models.BalancerRegistration.deleted_at.is_(None))
    if status_filter and status_filter != "all":
        query = query.where(models.BalancerRegistration.status == status_filter)
    if inclusion_filter == "included":
        query = query.where(models.BalancerRegistration.exclude_from_balancer.is_(False))
    elif inclusion_filter == "excluded":
        query = query.where(models.BalancerRegistration.exclude_from_balancer.is_(True))
    if source_filter == "google_sheets":
        query = query.where(models.BalancerRegistration.google_sheet_binding.has())
    elif source_filter == "manual":
        query = query.where(~models.BalancerRegistration.google_sheet_binding.has())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_registration_by_id(session: AsyncSession, registration_id: int) -> models.BalancerRegistration:
    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(models.BalancerRegistration.id == registration_id)
        .options(
            selectinload(models.BalancerRegistration.roles)
            .selectinload(models.BalancerRegistrationRole.hero_entries)
            .selectinload(models.BalancerRegistrationRoleHero.hero),
            selectinload(models.BalancerRegistration.reviewer),
            selectinload(models.BalancerRegistration.checked_in_by_user),
            selectinload(models.BalancerRegistration.google_sheet_binding),
            selectinload(models.BalancerRegistration.tournament),
        )
    )
    registration = result.scalar_one_or_none()
    if registration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    return registration


async def ensure_unique_battle_tag(
    session: AsyncSession,
    *,
    tournament_id: int,
    battle_tag: str | None,
    exclude_registration_id: int | None = None,
) -> None:
    normalized = normalize_battle_tag_key(battle_tag)
    if not normalized:
        return
    query = sa.select(models.BalancerRegistration.id).where(
        models.BalancerRegistration.tournament_id == tournament_id,
        models.BalancerRegistration.deleted_at.is_(None),
        models.BalancerRegistration.battle_tag_normalized == normalized,
    )
    if exclude_registration_id is not None:
        query = query.where(models.BalancerRegistration.id != exclude_registration_id)
    existing_id = (await session.execute(query)).scalar_one_or_none()
    if existing_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registration with this BattleTag already exists")


def replace_registration_roles(
    registration: models.BalancerRegistration,
    roles: list[dict[str, Any]],
    *,
    hero_catalog: HeroCatalog | None = None,
    max_heroes: int | None = None,
) -> None:
    existing_by_role = {existing.role: existing for existing in registration.roles}
    next_roles: list[models.BalancerRegistrationRole] = []
    seen_roles: set[str] = set()

    for index, role in enumerate(sorted(roles, key=lambda item: item.get("priority", DEFAULT_SORT_PRIORITY_SENTINEL))):
        role_code = role.get("role")
        if role_code not in {"tank", "dps", "support"} or role_code in seen_roles:
            continue
        seen_roles.add(role_code)

        registration_role = existing_by_role.pop(role_code, None)
        if registration_role is None:
            registration_role = models.BalancerRegistrationRole(role=role_code)

        registration_role.role = role_code
        registration_role.subrole = normalize_sub_role(role.get("subrole"))
        registration_role.is_primary = bool(role.get("is_primary", index == 0))
        registration_role.priority = index
        registration_role.rank_value = role.get("rank_value")
        registration_role.is_active = bool(role.get("is_active", role.get("rank_value") is not None))

        if hero_catalog is not None:
            top_heroes = role.get("top_heroes")
            if top_heroes is not None:
                from shared.hero_catalog import build_hero_entries, DEFAULT_MAX_TOP_HEROES
                registration_role.hero_entries = build_hero_entries(
                    top_heroes,
                    hero_catalog=hero_catalog,
                    max_heroes=max_heroes or DEFAULT_MAX_TOP_HEROES,
                )

        next_roles.append(registration_role)

    registration.roles[:] = next_roles



def _active_roles(registration: models.BalancerRegistration | Any) -> list[Any]:
    return [r for r in getattr(registration, "roles", []) if getattr(r, "is_active", False)]


def registration_has_active_roles(registration: models.BalancerRegistration | Any) -> bool:
    return len(_active_roles(registration)) > 0


def active_roles_all_ranked(registration: models.BalancerRegistration | Any) -> bool:
    roles = _active_roles(registration)
    return len(roles) > 0 and all(getattr(r, "rank_value", None) is not None for r in roles)


def included_balancer_status(registration: models.BalancerRegistration | Any) -> str:
    return "ready" if active_roles_all_ranked(registration) else "incomplete"


def sync_included_balancer_status(registration: models.BalancerRegistration | Any) -> None:
    current_balancer_status = getattr(registration, "balancer_status", None)
    if (
        getattr(registration, "status", None) == "approved"
        and current_balancer_status in VALID_BALANCER_STATUSES
        and current_balancer_status != "not_in_balancer"
    ):
        registration.balancer_status = included_balancer_status(registration)


async def validate_registration_status_value(
    session: AsyncSession,
    *,
    workspace_id: int,
    scope: str,
    value: str,
) -> None:
    builtin_values = VALID_REGISTRATION_STATUSES if scope == "registration" else VALID_BALANCER_STATUSES
    if value in builtin_values:
        return

    result = await session.execute(
        sa.select(models.BalancerRegistrationStatus.id).where(
            models.BalancerRegistrationStatus.workspace_id == workspace_id,
            models.BalancerRegistrationStatus.scope == scope,
            models.BalancerRegistrationStatus.slug == value,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {scope} status: {value}",
        )


async def create_manual_registration(
    session: AsyncSession,
    *,
    tournament_id: int,
    workspace_id: int,
    display_name: str | None,
    battle_tag: str | None,
    smurf_tags_json: list[str] | None,
    discord_nick: str | None,
    twitch_nick: str | None,
    stream_pov: bool,
    notes: str | None,
    admin_notes: str | None,
    roles: list[dict[str, Any]],
) -> models.BalancerRegistration:
    battle_tag = normalize_battle_tag(battle_tag)
    await ensure_unique_battle_tag(session, tournament_id=tournament_id, battle_tag=battle_tag)

    form = (
        await session.execute(
            sa.select(models.BalancerRegistrationForm).where(
                models.BalancerRegistrationForm.tournament_id == tournament_id
            )
        )
    ).scalar_one_or_none()
    config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
    hero_catalog = None
    max_heroes = None
    if config and config.get("enabled", True) is not False:
        from shared.hero_catalog import resolve_hero_catalog, DEFAULT_MAX_TOP_HEROES
        hero_catalog = await resolve_hero_catalog(session)
        raw_max = config.get("max_heroes")
        max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else DEFAULT_MAX_TOP_HEROES

    registration = models.BalancerRegistration(
        tournament_id=tournament_id,
        workspace_id=workspace_id,
        display_name=display_name or battle_tag,
        battle_tag=battle_tag,
        battle_tag_normalized=normalize_battle_tag_key(battle_tag),
        smurf_tags_json=smurf_tags_json or None,
        discord_nick=discord_nick,
        twitch_nick=twitch_nick,
        stream_pov=stream_pov,
        notes=notes,
        admin_notes=admin_notes,
        status="approved",
        exclude_from_balancer=False,
        submitted_at=datetime.now(UTC),
        balancer_profile_overridden_at=datetime.now(UTC),
    )
    replace_registration_roles(registration, roles, hero_catalog=hero_catalog, max_heroes=max_heroes)
    session.add(registration)
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def update_registration_profile(
    session: AsyncSession,
    registration_id: int,
    *,
    display_name: str | None,
    battle_tag: str | None,
    smurf_tags_json: list[str] | None,
    discord_nick: str | None,
    twitch_nick: str | None,
    stream_pov: bool | None,
    notes: str | None,
    admin_notes: str | None,
    status_value: str | None,
    balancer_status_value: str | None,
    roles: list[dict[str, Any]] | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    if battle_tag is not None:
        normalized_battle_tag = normalize_battle_tag(battle_tag)
        await ensure_unique_battle_tag(
            session,
            tournament_id=registration.tournament_id,
            battle_tag=normalized_battle_tag,
            exclude_registration_id=registration.id,
        )
        registration.battle_tag = normalized_battle_tag
        registration.battle_tag_normalized = normalize_battle_tag_key(normalized_battle_tag)
    if display_name is not None:
        registration.display_name = display_name or registration.battle_tag
    if smurf_tags_json is not None:
        registration.smurf_tags_json = smurf_tags_json or None
    if discord_nick is not None:
        registration.discord_nick = discord_nick
    if twitch_nick is not None:
        registration.twitch_nick = twitch_nick
    if stream_pov is not None:
        registration.stream_pov = stream_pov
    if notes is not None:
        registration.notes = notes
    if status_value is not None:
        await validate_registration_status_value(
            session,
            workspace_id=registration.workspace_id,
            scope="registration",
            value=status_value,
        )
        registration.status = status_value
    if balancer_status_value is not None:
        await validate_registration_status_value(
            session,
            workspace_id=registration.workspace_id,
            scope="balancer",
            value=balancer_status_value,
        )
        registration.balancer_status = balancer_status_value
        if balancer_status_value == "not_in_balancer":
            registration.exclude_from_balancer = True

    override_changed = False
    if status_value is not None or balancer_status_value is not None:
        override_changed = True
    if admin_notes is not None:
        registration.admin_notes = admin_notes
        override_changed = True
    if roles is not None:
        for r_obj in registration.roles:
            if hasattr(r_obj, "hero_entries") and hasattr(r_obj.hero_entries, "clear"):
                r_obj.hero_entries.clear()
        await session.flush()

        form = (
            await session.execute(
                sa.select(models.BalancerRegistrationForm).where(
                    models.BalancerRegistrationForm.tournament_id == registration.tournament_id
                )
            )
        ).scalar_one_or_none()
        config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
        hero_catalog = None
        max_heroes = None
        if config and config.get("enabled", True) is not False:
            from shared.hero_catalog import resolve_hero_catalog, DEFAULT_MAX_TOP_HEROES
            hero_catalog = await resolve_hero_catalog(session)
            raw_max = config.get("max_heroes")
            max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else DEFAULT_MAX_TOP_HEROES

        replace_registration_roles(registration, roles, hero_catalog=hero_catalog, max_heroes=max_heroes)
        sync_included_balancer_status(registration)
        override_changed = True
    if override_changed:
        registration.balancer_profile_overridden_at = datetime.now(UTC)

    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def approve_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    reviewed_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "approved"
    registration.reviewed_at = datetime.now(UTC)
    registration.reviewed_by = reviewed_by
    # Keep exclude_from_balancer for backward compat but do NOT
    # auto-add to balancer.  Admin must explicitly set balancer_status.
    registration.exclude_from_balancer = False
    registration.exclude_reason = None
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def reject_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    reviewed_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "rejected"
    registration.reviewed_at = datetime.now(UTC)
    registration.reviewed_by = reviewed_by
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def bulk_approve_registrations(
    session: AsyncSession,
    tournament_id: int,
    registration_ids: list[int],
    *,
    reviewed_by: int | None,
) -> tuple[int, int]:
    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.id.in_(registration_ids),
            models.BalancerRegistration.status == "pending",
        )
    )
    registrations = list(result.scalars().all())
    now = datetime.now(UTC)
    for registration in registrations:
        registration.status = "approved"
        registration.reviewed_at = now
        registration.reviewed_by = reviewed_by
        registration.exclude_from_balancer = False
        registration.exclude_reason = None
    await session.commit()
    return len(registrations), len(registration_ids) - len(registrations)


async def set_registration_exclusion(
    session: AsyncSession,
    registration_id: int,
    *,
    exclude_from_balancer: bool,
    exclude_reason: str | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.exclude_from_balancer = exclude_from_balancer
    if exclude_from_balancer:
        registration.balancer_status = "not_in_balancer"
        registration.exclude_reason = exclude_reason
    else:
        registration.exclude_reason = None
        registration.balancer_status = (
            included_balancer_status(registration) if registration.status == "approved" else "not_in_balancer"
        )
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def withdraw_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "withdrawn"
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def restore_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "approved"
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def soft_delete_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    deleted_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.deleted_at = datetime.now(UTC)
    registration.deleted_by = deleted_by
    await session.commit()
    return registration

async def set_balancer_status(
    session: AsyncSession,
    registration_id: int,
    *,
    balancer_status: str,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    await validate_registration_status_value(
        session,
        workspace_id=registration.workspace_id,
        scope="balancer",
        value=balancer_status,
    )
    if balancer_status != "not_in_balancer" and registration.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration must be approved before adding to balancer",
        )
    if balancer_status == "ready" and not active_roles_all_ranked(registration):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration must have at least one active role with rank before it can be ready",
        )
    registration.balancer_status = balancer_status
    if balancer_status == "not_in_balancer":
        registration.exclude_from_balancer = True
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def check_in_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    checked_in_by: int | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    if not is_check_in_window_active(registration.tournament):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Check-in is not active for this tournament",
        )
    registration.checked_in = True
    registration.checked_in_at = datetime.now(UTC)
    registration.checked_in_by = checked_in_by
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def uncheck_in_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.checked_in = False
    registration.checked_in_at = None
    registration.checked_in_by = None
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def bulk_add_to_balancer(
    session: AsyncSession,
    tournament_id: int,
    registration_ids: list[int],
    *,
    balancer_status: str = "ready",
) -> tuple[int, int]:
    if balancer_status not in VALID_BALANCER_STATUSES:
        tournament = await ensure_tournament_exists(session, tournament_id)
        await validate_registration_status_value(
            session,
            workspace_id=tournament.workspace_id,
            scope="balancer",
            value=balancer_status,
        )
    result = await session.execute(
        sa.select(models.BalancerRegistration).where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.id.in_(registration_ids),
            models.BalancerRegistration.status == "approved",
        )
    )
    registrations = list(result.scalars().all())
    for registration in registrations:
        registration.balancer_status = included_balancer_status(registration) if balancer_status == "ready" else balancer_status
        registration.exclude_from_balancer = balancer_status == "not_in_balancer"
        registration.exclude_reason = None
    await session.commit()
    return len(registrations), len(registration_ids) - len(registrations)


def apply_sheet_fields_to_registration(
    registration: models.BalancerRegistration,
    parsed_fields: dict[str, Any],
    *,
    allow_balancer_overwrite: bool,
) -> None:
    registration.display_name = parsed_fields.get("display_name") or parsed_fields.get("battle_tag") or registration.display_name
    if parsed_fields.get("battle_tag") is not None:
        registration.battle_tag = parsed_fields["battle_tag"]
        registration.battle_tag_normalized = normalize_battle_tag_key(parsed_fields["battle_tag"])
    registration.smurf_tags_json = parsed_fields.get("smurf_tags") or None
    registration.discord_nick = parsed_fields.get("discord_nick")
    registration.twitch_nick = parsed_fields.get("twitch_nick")
    registration.stream_pov = bool(parsed_fields.get("stream_pov", False))
    registration.notes = parsed_fields.get("notes")

    if allow_balancer_overwrite:
        registration.admin_notes = parsed_fields.get("admin_notes")
        replace_registration_roles(registration, build_registration_role_payloads(parsed_fields))
        sync_included_balancer_status(registration)


async def sync_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
) -> tuple[models.BalancerRegistrationGoogleSheetFeed, int, int, int, int]:
    feed = await require_google_sheet_feed(session, tournament_id)
    grid = await get_tournament_grid(session, tournament_id)
    tournament = await ensure_tournament_exists(session, tournament_id)
    now = datetime.now(UTC)

    try:
        rows = await fetch_google_sheet_rows(feed.source_url, sheet_id=feed.sheet_id, gid=feed.gid)
        headers = rows[0]
        mapping_config = feed.mapping_config_json or suggest_mapping_from_headers(headers)
        value_mapping = feed.value_mapping_json or build_default_value_mapping()

        parsed_rows: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
        for row in rows[1:]:
            parsed_fields = parse_sheet_row(
                headers=headers,
                row=row,
                mapping_config=mapping_config,
                value_mapping=value_mapping,
                grid=grid,
            )
            if not parsed_fields:
                continue
            parsed_rows[parsed_fields["source_record_key"]] = (row_to_json(headers, row), parsed_fields)

        existing_bindings_result = await session.execute(
            sa.select(models.BalancerRegistrationGoogleSheetBinding)
            .where(models.BalancerRegistrationGoogleSheetBinding.feed_id == feed.id)
            .options(
                selectinload(models.BalancerRegistrationGoogleSheetBinding.registration).selectinload(
                    models.BalancerRegistration.roles
                )
            )
        )
        existing_bindings = list(existing_bindings_result.scalars().all())
        bindings_by_key = {binding.source_record_key: binding for binding in existing_bindings}

        created = 0
        updated = 0
        withdrawn = 0
        seen_keys: set[str] = set()

        for source_record_key, (raw_row_json, parsed_fields) in parsed_rows.items():
            seen_keys.add(source_record_key)
            binding = bindings_by_key.get(source_record_key)
            registration = binding.registration if binding else None

            if registration is None:
                battle_tag_key = normalize_battle_tag_key(parsed_fields.get("battle_tag"))
                if battle_tag_key:
                    reuse_result = await session.execute(
                        sa.select(models.BalancerRegistration)
                        .where(
                            models.BalancerRegistration.tournament_id == tournament_id,
                            models.BalancerRegistration.deleted_at.is_(None),
                            models.BalancerRegistration.battle_tag_normalized == battle_tag_key,
                        )
                        .options(selectinload(models.BalancerRegistration.roles))
                        .limit(1)
                    )
                    registration = reuse_result.scalar_one_or_none()

            if registration is None:
                registration = models.BalancerRegistration(
                    tournament_id=tournament_id,
                    workspace_id=tournament.workspace_id,
                    display_name=parsed_fields.get("display_name") or parsed_fields.get("battle_tag"),
                    battle_tag=parsed_fields.get("battle_tag"),
                    battle_tag_normalized=normalize_battle_tag_key(parsed_fields.get("battle_tag")),
                    smurf_tags_json=parsed_fields.get("smurf_tags") or None,
                    discord_nick=parsed_fields.get("discord_nick"),
                    twitch_nick=parsed_fields.get("twitch_nick"),
                    stream_pov=bool(parsed_fields.get("stream_pov", False)),
                    notes=parsed_fields.get("notes"),
                    admin_notes=parsed_fields.get("admin_notes"),
                    status="approved",
                    exclude_from_balancer=False,
                    submitted_at=parsed_fields.get("submitted_at") or now,
                )
                replace_registration_roles(registration, build_registration_role_payloads(parsed_fields))
                session.add(registration)
                await session.flush()
                created += 1
            else:
                allow_balancer_overwrite = registration.balancer_profile_overridden_at is None
                apply_sheet_fields_to_registration(
                    registration,
                    parsed_fields,
                    allow_balancer_overwrite=allow_balancer_overwrite,
                )
                if registration.status == "withdrawn":
                    registration.status = "approved"
                updated += 1

            if binding is None:
                binding = models.BalancerRegistrationGoogleSheetBinding(
                    feed_id=feed.id,
                    registration_id=registration.id,
                    source_record_key=source_record_key,
                )
                session.add(binding)
                bindings_by_key[source_record_key] = binding

            binding.raw_row_json = raw_row_json
            binding.parsed_fields_json = serialize_parsed_fields(parsed_fields)
            binding.row_hash = hashlib.sha1(repr(raw_row_json).encode("utf-8")).hexdigest()
            binding.last_seen_at = now

        for binding in existing_bindings:
            if binding.source_record_key in seen_keys:
                continue
            if binding.registration.status != "withdrawn":
                binding.registration.status = "withdrawn"
                withdrawn += 1

        feed.header_row_json = headers
        if feed.mapping_config_json is None:
            feed.mapping_config_json = mapping_config
        if feed.value_mapping_json is None:
            feed.value_mapping_json = value_mapping
        feed.last_synced_at = now
        feed.last_sync_status = "success"
        feed.last_error = None
        await session.commit()
        await session.refresh(feed)
        return feed, created, updated, withdrawn, len(parsed_rows)
    except HTTPException as exc:
        feed.last_synced_at = now
        feed.last_sync_status = "failed"
        feed.last_error = str(exc.detail)
        await session.commit()
        raise
    except httpx.HTTPError as exc:
        feed.last_synced_at = now
        feed.last_sync_status = "failed"
        feed.last_error = str(exc)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to fetch Google Sheet") from exc


async def sync_due_google_sheet_feeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        result = await session.execute(
            sa.select(models.BalancerRegistrationGoogleSheetFeed)
            .where(models.BalancerRegistrationGoogleSheetFeed.auto_sync_enabled.is_(True))
            .order_by(models.BalancerRegistrationGoogleSheetFeed.id.asc())
        )
        feeds = list(result.scalars().all())

    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    for feed in feeds:
        interval = timedelta(seconds=max(int(feed.auto_sync_interval_seconds or DEFAULT_SYNC_INTERVAL_SECONDS), MIN_SYNC_INTERVAL_SECONDS))
        if feed.last_synced_at is not None and feed.last_synced_at > now - interval:
            continue
        async with session_factory() as session:
            try:
                _, created, updated, withdrawn, total = await sync_google_sheet_feed(session, feed.tournament_id)
                results.append(
                    {
                        "tournament_id": feed.tournament_id,
                        "status": "success",
                        "created": created,
                        "updated": updated,
                        "withdrawn": withdrawn,
                        "total": total,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to sync feed for tournament %s", feed.tournament_id)
                results.append(
                    {
                        "tournament_id": feed.tournament_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
    return results


async def list_active_registrations_for_balancer(
    session: AsyncSession,
    tournament_id: int,
) -> list[models.BalancerRegistration]:
    result = await session.execute(
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.status == "approved",
            models.BalancerRegistration.exclude_from_balancer.is_(False),
            # Mirror the panel's "in balancer" rule (draft load_pool): a registration
            # is part of the pool only once it has been added (balancer_status set).
            models.BalancerRegistration.balancer_status != "not_in_balancer",
        )
        .options(selectinload(models.BalancerRegistration.roles))
        .order_by(models.BalancerRegistration.battle_tag_normalized.asc().nullslast())
    )
    return list(result.scalars().all())


async def export_active_registrations(
    session: AsyncSession,
    tournament_id: int,
) -> dict[str, Any]:
    registrations = await list_active_registrations_for_balancer(session, tournament_id)
    payload_players: dict[str, Any] = {}
    for registration in registrations:
        export_uuid = str(uuid4())
        payload_players[export_uuid] = serialize_registration_for_export(registration, export_uuid)
    return {"format": "xv-1", "players": payload_players}


async def export_registrations_to_users(
    session: AsyncSession,
    tournament_id: int,
) -> dict[str, int]:
    registrations = await list_registrations(
        session, tournament_id, include_deleted=False, status_filter="approved"
    )

    processed = 0
    skipped = 0
    for registration in registrations:
        battle_tag = registration.battle_tag
        if not battle_tag:
            skipped += 1
            continue
        smurfs = [tag for tag in (registration.smurf_tags_json or []) if BATTLE_TAG_RE.match(tag)]
        try:
            payload = UserCSV(
                battle_tag=battle_tag,
                discord=registration.discord_nick,
                twitch=registration.twitch_nick,
                smurfs=smurfs,
            )
        except Exception:
            logger.exception("Failed to build user payload for registration %s", battle_tag)
            skipped += 1
            continue

        await user_flows.create(session, payload)
        processed += 1

    return {"processed": processed, "skipped": skipped, "total": len(registrations)}
