from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import sqlalchemy as sa
from fastapi import HTTPException, status
from shared.balancer_registration_statuses import get_builtin_status_values
from shared.core import enums
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.domain.player_sub_roles import normalize_sub_role
from shared.hero_catalog import HeroCatalog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from src import models
from src.schemas.registration import CustomFieldDefinition
from src.services.registration.mapping_catalog import (
    DEFAULT_MAPPING_TARGETS,  # noqa: F401 - compatibility re-export
    PARSER_CATALOG,
    ParsedRowResult,
    build_target_specs,
    classify_row_disposition,
    coerce_custom_field_value,
    custom_field_target_key,
    target_spec_map,
    validate_mapping_config,
)
from src.services.registration.utils import (
    DEFAULT_BOOLEAN_TRUE_VALUES,
    RoleSubroleEntry,
    DEFAULT_SORT_PRIORITY_SENTINEL,
    DEFAULT_SYNC_INTERVAL_SECONDS,
    GOOGLE_SHEET_FETCH_TIMEOUT,
    MIN_SYNC_INTERVAL_SECONDS,
    ROLE_ORDER,
    UNKNOWN_PRIORITY_SENTINEL,
    VALID_ROLES,
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
from src.services.registration.utils import (
    extract_battle_tags as _extract_battle_tags,
)
from src.services.tournament.events import (
    enqueue_registration_approved,
    enqueue_registration_rejected,
)
from src.services.tournament.realtime_commit import register_tournament_realtime_update

logger = logging.getLogger(__name__)

VALID_REGISTRATION_STATUSES = get_builtin_status_values("registration")
VALID_BALANCER_STATUSES = get_builtin_status_values("balancer")


@dataclass
class _RankData:
    """Resolved rank value for autofill, abstracting over snapshot and balancer history."""

    rank_value: int | None
    platform: str | None = None
    division: str | None = None
    tier: int | None = None
    season: int | None = None
    captured_at: datetime | None = None
    source: str = "analytics"


RANK_ROLE_BY_REGISTRATION_ROLE = {
    "tank": enums.RankRole.tank.value,
    "dps": enums.RankRole.damage.value,
    "support": enums.RankRole.support.value,
}
REGISTRATION_ROLE_LABELS = {
    "tank": "Tank",
    "dps": "Damage",
    "support": "Support",
}


def _register_registration_changed(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> None:
    register_tournament_realtime_update(session, registration.tournament_id, "structure_changed")

BATTLE_TAG_RE = re.compile(r"[\w][\w ]{0,30}#[0-9]{3,}", re.UNICODE)


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
        normalize_header(key): bool(mapped_value) for key, mapped_value in (value_mapping.get("booleans") or {}).items()
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
        normalize_header(key): mapped_value for key, mapped_value in (value_mapping.get("roles") or {}).items()
    }
    if normalized in custom_map:
        mapped = custom_map[normalized]
        return mapped if mapped in {"tank", "dps", "support"} else None
    return None


def map_subrole_token(value: str | None, value_mapping: dict[str, Any]) -> str | None:
    if value is None:
        return None
    normalized = normalize_header(value)
    custom_map = {
        normalize_header(key): mapped_value for key, mapped_value in (value_mapping.get("subroles") or {}).items()
    }
    mapped = custom_map.get(normalized)
    if mapped:
        return normalize_sub_role(mapped)
    return None


def _valid_role_subrole_entry(entry: Any) -> RoleSubroleEntry | None:
    if not isinstance(entry, dict):
        return None
    role = entry.get("role")
    if role == "flex" or role in VALID_ROLES:
        return {"role": role, "subrole": entry.get("subrole")}
    return None


def map_role_subrole_tokens(value: str | None, value_mapping: dict[str, Any]) -> list[RoleSubroleEntry]:
    """Return all role+subrole entries for a single cell value.

    A value_mapping entry may be a single dict or a list of dicts (multi-role
    mapping), allowing one cell option like "Флекс, Танк или Сап" to expand
    into multiple role entries.
    """
    if value is None:
        return []
    normalized = normalize_header(value)
    custom_map = {
        normalize_header(k): v
        for k, v in (value_mapping.get("role_subroles") or {}).items()
    }
    raw = custom_map.get(normalized)
    if isinstance(raw, list):
        return [e for e in (_valid_role_subrole_entry(item) for item in raw) if e is not None]
    entry = _valid_role_subrole_entry(raw)
    return [entry] if entry else []


def map_role_subrole_token(value: str | None, value_mapping: dict[str, Any]) -> RoleSubroleEntry | None:
    entries = map_role_subrole_tokens(value, value_mapping)
    return entries[0] if entries else None


def _parse_sr_value(raw: str | None, value_mapping: dict[str, Any]) -> int | None:
    if not raw:
        return None
    normalized = normalize_header(raw)
    division_map = {
        normalize_header(k): int(v)
        for k, v in (value_mapping.get("divisions") or {}).items()
        if str(v).lstrip("-").isdigit()
    }
    if normalized in division_map:
        return division_map[normalized]
    return parse_integer(raw)


def parse_role_token_list(values: list[str], value_mapping: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        # Try the whole cell value first — handles custom mappings that include commas.
        role_code = map_role_token(stripped, value_mapping)
        if role_code:
            roles.append(role_code)
            continue
        for token in re.split(r"[,/\n]+", value):
            role_code = map_role_token(token, value_mapping)
            if role_code:
                roles.append(role_code)
    return unique_strings(roles)


def parse_role_subrole_token_list(values: list[str], value_mapping: dict[str, Any]) -> list[RoleSubroleEntry]:
    """Parse a list of role+subrole tokens, one per value (column).

    Each value is treated as a single complete token — no splitting by separators.
    This matches the column-mapping model where every cell holds exactly one role
    option (e.g. a Google Forms checkbox selection).
    """
    entries: list[RoleSubroleEntry] = []
    seen_roles: set[str] = set()
    for value in values:
        for entry in map_role_subrole_tokens(value.strip() or None, value_mapping):
            role = entry.get("role") or ""
            if role and role not in seen_roles:
                seen_roles.add(role)
                entries.append(entry)
    return entries


def build_default_value_mapping() -> dict[str, Any]:
    return {
        "booleans": dict.fromkeys(sorted(DEFAULT_BOOLEAN_TRUE_VALUES), True),
        "roles": {},
        "subroles": {},
        "role_subroles": {},
        "divisions": {},
    }


def default_mapping_target(parser: str, mode: str = "disabled") -> dict[str, Any]:
    return {"mode": mode, "parser": parser}


def suggest_mapping_from_headers(
    headers: list[str],
    *,
    custom_fields: list[CustomFieldDefinition] | None = None,
) -> dict[str, Any]:
    """Suggest a starting mapping by matching headers against target aliases.

    Language-agnostic: each target carries lowercased alias substrings (English
    and Russian alike) in the catalog, so no header strings are hardcoded here.
    Unmatched targets are returned as disabled hints. Suggestions are only a
    starting point - the saved mapping is authoritative.
    """
    header_keys = build_header_keys(headers)
    normalized_headers = [normalize_header(header) for header in headers]
    specs = build_target_specs(custom_fields)
    targets: dict[str, Any] = {spec.key: default_mapping_target(spec.default_parser, spec.default_mode) for spec in specs}

    def matching_columns(spec: Any) -> list[str]:
        return [
            header_keys[index]
            for index, normalized in enumerate(normalized_headers)
            if any(normalize_header(alias) in normalized for alias in spec.aliases)
        ]

    for spec in specs:
        if not spec.aliases:
            continue
        found = matching_columns(spec)
        if not found:
            continue
        columns = found if spec.multi_column else [found[0]]
        targets[spec.key] = {"mode": "columns", "columns": columns, "parser": spec.default_parser}

    # The battle-tag column also seeds the dedup key and the display name, matching
    # the legacy behavior where a single column drives all three identity fields.
    battle_tag_config = targets.get("battle_tag")
    if battle_tag_config and battle_tag_config.get("mode") == "columns":
        column = battle_tag_config["columns"][0]
        targets["source_record_key"] = {"mode": "columns", "columns": [column], "parser": "battle_tag"}
        if targets.get("display_name", {}).get("mode") != "columns":
            targets["display_name"] = {"mode": "columns", "columns": [column], "parser": "string"}

    return {"targets": targets}


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
    opens_at = _as_utc(tournament.check_in_opens_at) if tournament.check_in_opens_at is not None else None
    closes_at = _as_utc(tournament.check_in_closes_at) if tournament.check_in_closes_at is not None else None
    return (opens_at is None or opens_at <= current_time) and (closes_at is None or current_time <= closes_at)


def serialize_parsed_fields(parsed_fields: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(parsed_fields)
    serialized["submitted_at"] = serialize_datetime(parsed_fields.get("submitted_at"))
    return serialized


def get_selector_values(target_config: dict[str, Any] | None, row_json: dict[str, str]) -> list[str]:
    if not target_config:
        return []
    mode = target_config.get("mode")
    if mode in ("disabled", "auto"):
        return []
    if mode == "constant":
        value = target_config.get("value")
        return [] if value is None else [str(value)]
    return [
        row_json[column_name]
        for column_name in target_config.get("columns") or []
        if column_name in row_json and row_json[column_name].strip()
    ]


def parse_target_value(
    *,
    parser: str,
    values: list[str],
    value_mapping: dict[str, Any],
    grid: DivisionGrid,
    is_list: bool = False,
) -> Any:
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
        if is_list:
            return parse_role_token_list(values, value_mapping)
        return map_role_token(values[0] if values else None, value_mapping)
    if parser == "role_token_list":  # backward compat — treated as role_token + is_list=True
        return parse_role_token_list(values, value_mapping)
    if parser == "subrole_token":
        return map_subrole_token(values[0] if values else None, value_mapping)
    if parser == "division_to_rank":
        raw_value = values[0] if values else None
        normalized = normalize_header(raw_value)
        division_map = {
            normalize_header(key): str(mapped_value)
            for key, mapped_value in (value_mapping.get("divisions") or {}).items()
        }
        mapped_rank = parse_integer(division_map.get(normalized))
        if mapped_rank is not None:
            return mapped_rank
        division_number = parse_integer(raw_value)
        return grid.resolve_rank_from_division(division_number) if division_number is not None else None
    if parser == "join_lines":
        return "\n".join(value.strip() for value in values if value.strip()) or None
    if parser == "role_subrole_token":
        if is_list:
            return parse_role_subrole_token_list(values, value_mapping)
        return map_role_subrole_token(values[0] if values else None, value_mapping)
    if parser == "sr_value":
        return _parse_sr_value(values[0] if values else None, value_mapping)
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


def parse_sheet_row_detailed(
    *,
    headers: list[str],
    row: list[str],
    mapping_config: dict[str, Any] | None,
    value_mapping: dict[str, Any] | None,
    grid: DivisionGrid,
    custom_fields: list[CustomFieldDefinition] | None = None,
) -> ParsedRowResult:
    """Parse one sheet row into the structured registration payload.

    Collects per-target ``errors`` and ``warnings`` (chiefly from custom-field
    coercion) so a single bad cell never aborts the whole row. Returns
    ``fields=None`` when the row produces no identity key (caller skips it).
    """
    effective_mapping = mapping_config or suggest_mapping_from_headers(headers, custom_fields=custom_fields)
    targets = effective_mapping.get("targets") or {}
    row_json = row_to_json(headers, row)
    effective_value_mapping = {**build_default_value_mapping(), **(value_mapping or {})}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    flat_values: dict[str, Any] = {}
    for target_key, spec in target_spec_map(custom_fields).items():
        if spec.group == "custom_fields":
            continue
        target_config = targets.get(target_key)
        raw_mode = (target_config or {}).get("mode") or spec.default_mode
        effective_mode = "auto" if raw_mode in ("auto", "disabled") and spec.default_mode == "auto" else raw_mode
        if effective_mode == "auto":
            continue
        values = get_selector_values(target_config, row_json)
        parser = (target_config or {}).get("parser", spec.default_parser)
        is_list = bool((target_config or {}).get("is_list", spec.default_is_list))
        try:
            flat_values[target_key] = parse_target_value(
                parser=parser,
                values=values,
                value_mapping=effective_value_mapping,
                grid=grid,
                is_list=is_list,
            )
        except Exception as exc:  # noqa: BLE001 - surface per-field instead of failing the row
            flat_values[target_key] = None
            errors.append({"target": target_key, "column": None, "message": str(exc)})

    source_record_key = flat_values.get("source_record_key") or flat_values.get("battle_tag")
    if isinstance(source_record_key, str):
        source_record_key = normalize_battle_tag_key(source_record_key) or source_record_key.strip()
    if not source_record_key:
        return ParsedRowResult(fields=None, errors=errors, warnings=warnings)

    parsed: dict[str, Any] = {
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
                "is_active": flat_values.get("roles.tank.is_active"),
                "priority": flat_values.get("roles.tank.priority"),
            },
            "dps": {
                "rank_value": flat_values.get("roles.dps.rank_value") or flat_values.get("roles.dps.division_input"),
                "subrole": flat_values.get("roles.dps.subrole"),
                "is_active": flat_values.get("roles.dps.is_active"),
                "priority": flat_values.get("roles.dps.priority"),
            },
            "support": {
                "rank_value": flat_values.get("roles.support.rank_value")
                or flat_values.get("roles.support.division_input"),
                "subrole": flat_values.get("roles.support.subrole"),
                "is_active": flat_values.get("roles.support.is_active"),
                "priority": flat_values.get("roles.support.priority"),
            },
        },
    }

    custom_values: dict[str, Any] = {}
    for field_def in custom_fields or []:
        target_config = targets.get(custom_field_target_key(field_def.key))
        values = get_selector_values(target_config, row_json)
        if not values:
            continue
        result = coerce_custom_field_value(field_def, values[0], value_mapping=effective_value_mapping)
        target_key = custom_field_target_key(field_def.key)
        if result.error:
            errors.append({"target": target_key, "column": None, "message": result.error})
            continue
        if result.warning:
            warnings.append({"target": target_key, "column": None, "message": result.warning})
        if result.value is not None:
            custom_values[field_def.key] = result.value
    if custom_values:
        parsed["custom_fields"] = custom_values

    return ParsedRowResult(fields=parsed, errors=errors, warnings=warnings)


def parse_sheet_row(
    *,
    headers: list[str],
    row: list[str],
    mapping_config: dict[str, Any] | None,
    value_mapping: dict[str, Any] | None,
    grid: DivisionGrid,
    custom_fields: list[CustomFieldDefinition] | None = None,
) -> dict[str, Any] | None:
    return parse_sheet_row_detailed(
        headers=headers,
        row=row,
        mapping_config=mapping_config,
        value_mapping=value_mapping,
        grid=grid,
        custom_fields=custom_fields,
    ).fields


def build_registration_role_payloads(parsed_fields: dict[str, Any]) -> list[dict[str, Any]]:
    source_primary = parsed_fields.get("source_roles", {}).get("primary")
    source_additional = parsed_fields.get("source_roles", {}).get("additional") or []

    def _role_code(v: Any) -> str | None:
        if isinstance(v, dict):
            code = v.get("role")
            return code if code in VALID_ROLES else None
        return v if v in VALID_ROLES else None

    def _subrole(v: Any) -> str | None:
        return v.get("subrole") if isinstance(v, dict) else None

    # Full flex only when primary is the "flex" token AND no additional roles are listed.
    # Having additional roles means the player has explicit preferences — not a true full flex.
    is_full_flex = (
        isinstance(source_primary, dict)
        and source_primary.get("role") == "flex"
        and not source_additional
    )

    primary_code = _role_code(source_primary)
    declared_order: list[str] = []
    if primary_code:
        declared_order.append(primary_code)
    for item in source_additional:
        code = _role_code(item)
        if code and code not in declared_order:
            declared_order.append(code)
    source_priority = {code: i for i, code in enumerate(declared_order)}

    # Map role codes to their source entries so subroles can be looked up for
    # both the primary role and additional roles.
    source_entry_by_role: dict[str, Any] = {}
    if primary_code:
        source_entry_by_role[primary_code] = source_primary
    for item in source_additional:
        code = _role_code(item)
        if code and code not in source_entry_by_role:
            source_entry_by_role[code] = item

    payloads: list[dict[str, Any]] = []
    additional_role_codes = {_role_code(r) for r in source_additional} - {None}
    for fallback_priority, role_code in enumerate(ROLE_ORDER):
        role_data = parsed_fields.get("roles", {}).get(role_code) or {}
        rank_value = role_data.get("rank_value")
        explicit_subrole = role_data.get("subrole")
        is_active = role_data.get("is_active")
        priority = role_data.get("priority")

        token_subrole = _subrole(source_entry_by_role.get(role_code))
        effective_subrole = explicit_subrole or token_subrole

        declared_in_source = primary_code == role_code or role_code in additional_role_codes
        if rank_value is None and not is_active and not effective_subrole and priority is None and not declared_in_source and not is_full_flex:
            continue

        payloads.append(
            {
                "role": role_code,
                "subrole": effective_subrole,
                "is_primary": is_full_flex or primary_code == role_code or (primary_code is None and fallback_priority == 0),
                "priority": int(priority) if isinstance(priority, int) else source_priority.get(role_code, fallback_priority),
                "rank_value": rank_value,
                "is_active": bool(is_active) if is_active is not None else (rank_value is not None or declared_in_source or is_full_flex),
            }
        )

    if payloads and not is_full_flex and not any(p["is_primary"] for p in payloads):
        payloads[0]["is_primary"] = True

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


async def get_registration_form(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerRegistrationForm | None:
    result = await session.execute(
        sa.select(models.BalancerRegistrationForm).where(models.BalancerRegistrationForm.tournament_id == tournament_id)
    )
    return result.scalar_one_or_none()


def form_custom_field_defs(
    form: models.BalancerRegistrationForm | None,
) -> list[CustomFieldDefinition]:
    """Coerce a form's stored custom-field JSON into typed definitions."""
    raw = getattr(form, "custom_fields_json", None) or []
    defs: list[CustomFieldDefinition] = []
    for value in raw:
        if isinstance(value, CustomFieldDefinition):
            defs.append(value)
        else:
            defs.append(CustomFieldDefinition.model_validate(value or {}))
    return defs


async def get_form_custom_field_defs(
    session: AsyncSession,
    tournament_id: int,
) -> list[CustomFieldDefinition]:
    form = await get_registration_form(session, tournament_id)
    return form_custom_field_defs(form)


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


async def _resolve_header_keys(
    source_url: str,
    feed: models.BalancerRegistrationGoogleSheetFeed | None,
) -> list[str] | None:
    """Header keys from a cached header row, else a best-effort live fetch.

    Returns ``None`` when headers can't be determined (so validation falls back
    to mode/parser/identity checks without column-existence).
    """
    if feed is not None and feed.source_url == source_url and feed.header_row_json:
        return build_header_keys(feed.header_row_json)
    try:
        rows = await fetch_google_sheet_rows(source_url)
    except (HTTPException, httpx.HTTPError):
        return None
    return build_header_keys(rows[0]) if rows else None


async def _validate_feed_mapping(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str,
    existing_feed: models.BalancerRegistrationGoogleSheetFeed | None,
    mapping_config_json: dict[str, Any],
) -> None:
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    target_specs = target_spec_map(custom_fields)
    header_keys = await _resolve_header_keys(source_url, existing_feed)
    issues = validate_mapping_config(
        mapping_config_json,
        target_specs=target_specs,
        header_keys=header_keys,
    )
    if issues:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Invalid mapping configuration",
                "errors": [
                    {"code": issue.code, "target": issue.target, "column": issue.column, "message": issue.message}
                    for issue in issues
                ],
            },
        )


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
    if mapping_config_json is not None:
        await _validate_feed_mapping(
            session,
            tournament_id,
            source_url=source_url,
            existing_feed=feed,
            mapping_config_json=mapping_config_json,
        )
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
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    return feed, headers, suggest_mapping_from_headers(headers, custom_fields=custom_fields)


def build_mapping_catalog(
    custom_fields: list[CustomFieldDefinition],
    *,
    value_mapping: dict[str, Any] | None = None,
    header_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the frontend mapping catalog (targets, parsers, value maps)."""
    specs = build_target_specs(custom_fields)
    default_value_mapping = build_default_value_mapping()
    saved_value_mapping = value_mapping or {}
    effective_value_mapping = {
        category: {
            **(default_value_mapping.get(category) or {}),
            **(saved_value_mapping.get(category) or {}),
        }
        for category in ("booleans", "roles", "subroles", "role_subroles", "divisions")
    }
    return {
        "targets": [
            {
                "key": spec.key,
                "label": spec.label,
                "group": spec.group,
                "accepted_parsers": list(spec.accepted_parsers),
                "default_parser": spec.default_parser,
                "default_mode": spec.default_mode,
                "default_is_list": spec.default_is_list,
                "multi_column": spec.multi_column,
                "required": spec.required,
            }
            for spec in specs
        ],
        "parsers": [
            {
                "parser": parser.parser,
                "label": parser.label,
                "cardinality": parser.cardinality,
                "produces": parser.produces,
            }
            for parser in PARSER_CATALOG
        ],
        "value_categories": [
            {"category": category, "entries": effective_value_mapping.get(category) or {}}
            for category in ("booleans", "roles", "subroles", "role_subroles", "divisions")
        ],
        "custom_fields": [field_def.model_dump() for field_def in custom_fields],
        "header_keys": header_keys or [],
    }


async def get_mapping_catalog(
    session: AsyncSession,
    tournament_id: int,
    *,
    include_headers: bool = False,
) -> dict[str, Any]:
    await ensure_tournament_exists(session, tournament_id)
    feed = await get_google_sheet_feed(session, tournament_id)
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    header_keys: list[str] | None = None
    if include_headers and feed is not None:
        if feed.header_row_json:
            header_keys = build_header_keys(feed.header_row_json)
        elif feed.source_url:
            header_keys = await _resolve_header_keys(feed.source_url, feed)
    return build_mapping_catalog(
        custom_fields,
        value_mapping=feed.value_mapping_json if feed else None,
        header_keys=header_keys,
    )


async def preview_google_sheet_mapping(
    session: AsyncSession,
    tournament_id: int,
    *,
    source_url: str | None = None,
    mapping_config_json: dict[str, Any] | None = None,
    value_mapping_json: dict[str, Any] | None = None,
    sample_rows: int = 5,
) -> dict[str, Any]:
    feed = await get_google_sheet_feed(session, tournament_id)
    url = source_url or (feed.source_url if feed else None)
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets URL is required")

    limit = max(1, min(int(sample_rows or 1), 50))
    rows = await fetch_google_sheet_rows(url)
    headers = rows[0]
    header_keys = build_header_keys(headers)
    data_rows = rows[1 : 1 + limit]
    grid = await get_tournament_grid(session, tournament_id)
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    effective_mapping = mapping_config_json or (feed.mapping_config_json if feed else None)
    effective_value_mapping = value_mapping_json or (feed.value_mapping_json if feed else None)

    known_source_keys, known_battle_tag_keys = await _existing_match_keys(session, tournament_id, feed)

    preview_rows: list[dict[str, Any]] = []
    create_count = 0
    update_count = 0
    skip_count = 0
    for index, data_row in enumerate(data_rows):
        result = parse_sheet_row_detailed(
            headers=headers,
            row=data_row,
            mapping_config=effective_mapping,
            value_mapping=effective_value_mapping,
            grid=grid,
            custom_fields=custom_fields,
        )
        fields = result.fields
        source_record_key = fields.get("source_record_key") if fields else None
        battle_tag_key = normalize_battle_tag_key(fields.get("battle_tag")) if fields else None
        disposition = classify_row_disposition(
            source_record_key,
            battle_tag_key,
            known_source_keys=known_source_keys,
            known_battle_tag_keys=known_battle_tag_keys,
        )
        if disposition == "create":
            create_count += 1
        elif disposition == "update":
            update_count += 1
        else:
            skip_count += 1
        preview_rows.append(
            {
                "row_index": index,
                "sample_raw_row": row_to_json(headers, data_row),
                "parsed_fields": serialize_parsed_fields(fields or {}),
                "errors": result.errors,
                "warnings": result.warnings,
                "disposition": disposition,
            }
        )

    first = preview_rows[0] if preview_rows else {}
    return {
        "headers": headers,
        "header_keys": header_keys,
        "rows": preview_rows,
        "create_count": create_count,
        "update_count": update_count,
        "skip_count": skip_count,
        # Back-compat single-row fields (populated from the first row).
        "sample_raw_row": first.get("sample_raw_row", {}),
        "parsed_fields": first.get("parsed_fields", {}),
    }


async def _existing_match_keys(
    session: AsyncSession,
    tournament_id: int,
    feed: models.BalancerRegistrationGoogleSheetFeed | None,
) -> tuple[set[str], set[str]]:
    """Existing source-record keys (bound rows) and battle-tag keys for disposition."""
    battle_tag_result = await session.execute(
        sa.select(models.BalancerRegistration.battle_tag_normalized).where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.battle_tag_normalized.is_not(None),
        )
    )
    battle_tag_keys = set(battle_tag_result.scalars().all())
    source_keys: set[str] = set()
    if feed is not None:
        source_result = await session.execute(
            sa.select(models.BalancerRegistrationGoogleSheetBinding.source_record_key).where(
                models.BalancerRegistrationGoogleSheetBinding.feed_id == feed.id
            )
        )
        source_keys = set(source_result.scalars().all())
    return source_keys, battle_tag_keys


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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Registration with this BattleTag already exists"
        )


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
                from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, build_hero_entries
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


def _rank_snapshot_payload(snapshot: models.UserRankSnapshot | _RankData | Any | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "parsed_rank_value": None,
            "platform": None,
            "division": None,
            "tier": None,
            "season": None,
            "captured_at": None,
            "source": "analytics",
        }
    return {
        "parsed_rank_value": getattr(snapshot, "rank_value", None),
        "platform": getattr(snapshot, "platform", None),
        "division": getattr(snapshot, "division", None),
        "tier": getattr(snapshot, "tier", None),
        "season": getattr(snapshot, "season", None),
        "captured_at": getattr(snapshot, "captured_at", None),
        "source": getattr(snapshot, "source", "analytics"),
    }


def build_registration_rank_autofill_plan(
    registration: models.BalancerRegistration | Any,
    rank_snapshots_by_role: dict[str, models.UserRankSnapshot | Any],
    *,
    battle_tag_linked: bool,
    overwrite_existing: bool,
    applied: bool = False,
) -> tuple[dict[str, Any], list[tuple[Any, Any]]]:
    """Build the rank autofill preview row and pending role updates.

    Only active registration roles are considered, and parsed ranks are expected
    to come from the registration's main battle tag only.
    """

    display_name = getattr(registration, "display_name", None)
    battle_tag = getattr(registration, "battle_tag", None)
    row = {
        "registration_id": registration.id,
        "display_name": display_name,
        "battle_tag": battle_tag,
        "status": "skipped",
        "reason": None,
        "roles": [],
    }

    if not battle_tag:
        row["reason"] = "Registration has no main BattleTag."
        return row, []

    active_roles = sorted(
        _active_roles(registration),
        key=lambda role: (getattr(role, "priority", DEFAULT_SORT_PRIORITY_SENTINEL), getattr(role, "role", "")),
    )
    if not active_roles:
        row["reason"] = "Registration has no active roles."
        return row, []

    if not battle_tag_linked:
        row["reason"] = "Main BattleTag is not linked to an analytics player account."
        return row, []

    updates: list[tuple[Any, Any]] = []
    missing_roles: list[str] = []
    kept_existing = False

    for role_entry in active_roles:
        role_code = getattr(role_entry, "role", None)
        rank_role = RANK_ROLE_BY_REGISTRATION_ROLE.get(role_code)
        snapshot = rank_snapshots_by_role.get(rank_role or "")
        current_rank = getattr(role_entry, "rank_value", None)
        snapshot_payload = _rank_snapshot_payload(snapshot)
        parsed_rank = snapshot_payload["parsed_rank_value"]
        role_row = {
            "role": role_code,
            "current_rank_value": current_rank,
            **snapshot_payload,
            "action": "missing_rank",
            "reason": "No parsed rank for this registered role on the main account.",
        }

        if current_rank is not None and not overwrite_existing:
            kept_existing = True
            role_row["action"] = "keep_existing"
            role_row["reason"] = "Existing registration rank is kept. Enable overwrite to replace it."
        elif parsed_rank is None:
            missing_roles.append(REGISTRATION_ROLE_LABELS.get(role_code, str(role_code)))
        elif current_rank == parsed_rank:
            kept_existing = True
            role_row["action"] = "keep_existing"
            role_row["reason"] = "Parsed rank already matches the registration rank."
        else:
            role_row["action"] = "overwrite" if current_rank is not None else "set"
            role_row["reason"] = None
            updates.append((role_entry, snapshot))

        row["roles"].append(role_row)

    if missing_roles:
        row["reason"] = f"No parsed rank for registered role(s): {', '.join(missing_roles)}."
        for role_row in row["roles"]:
            if role_row["action"] in {"set", "overwrite"}:
                role_row["action"] = "blocked"
                role_row["reason"] = "Player skipped because another registered role has no parsed rank."
        return row, []

    if updates:
        row["status"] = "applied" if applied else "will_update"
        return row, updates

    row["status"] = "unchanged"
    row["reason"] = (
        "All active registration ranks are already set."
        if kept_existing and not overwrite_existing
        else "No rank changes needed."
    )
    return row, []


def _active_roles_ranked_after_updates(registration: models.BalancerRegistration | Any, updates: list[tuple[Any, Any]]) -> bool:
    roles = _active_roles(registration)
    if not roles:
        return False
    updated_role_ids = {id(role_entry) for role_entry, _snapshot in updates}
    return all(getattr(role, "rank_value", None) is not None or id(role) in updated_role_ids for role in roles)


def _rank_autofill_balancer_addition(
    registration: models.BalancerRegistration | Any,
    updates: list[tuple[Any, Any]],
    *,
    add_to_balancer: bool,
) -> tuple[bool, str | None]:
    if not add_to_balancer:
        return False, None
    if getattr(registration, "status", None) != "approved":
        return False, "Registration must be approved before it can be added to balancer."
    if not (
        getattr(registration, "exclude_from_balancer", False)
        or getattr(registration, "balancer_status", None) == "not_in_balancer"
    ):
        return False, "Registration is already in balancer."
    if not _active_roles_ranked_after_updates(registration, updates):
        return False, "Registration will still be missing active role ranks."
    return True, None


async def _load_tournament_for_autofill(
    session: AsyncSession,
    tournament_id: int,
) -> models.Tournament | None:
    result = await session.execute(
        sa.select(models.Tournament).where(models.Tournament.id == tournament_id)
    )
    return result.scalar_one_or_none()


def _build_ow2_rank_data(snapshot: models.UserRankSnapshot, grid: DivisionGrid) -> _RankData:
    """Map a raw OW2 rank snapshot to a tournament division rank via ow_rank_min/ow_rank_max."""
    ow_rank = getattr(snapshot, "rank_value", None)
    if ow_rank is not None:
        tier = grid.resolve_division_from_ow_rank(ow_rank)
        rank_value = tier.rank_min if tier is not None else ow_rank
    else:
        rank_value = None
    return _RankData(
        rank_value=rank_value,
        platform=getattr(snapshot, "platform", None),
        division=getattr(snapshot, "division", None),
        tier=getattr(snapshot, "tier", None),
        season=getattr(snapshot, "season", None),
        captured_at=getattr(snapshot, "captured_at", None),
        source="analytics",
    )


async def _load_latest_ranks_from_balancer_history(
    session: AsyncSession,
    user_ids: list[int],
    current_tournament_id: int,
    workspace_id: int,
) -> dict[int, dict[str, int]]:
    """Return dict[user_id][role_code] → rank_value from past BalancerPlayerRoleEntry records.

    Searches the workspace's previous tournaments (excluding the current one), ordered
    by tournament number descending so the most recent entry wins.
    """
    if not user_ids:
        return {}

    rows = (
        await session.execute(
            sa.select(
                models.BalancerPlayer.user_id,
                models.BalancerPlayerRoleEntry.role,
                models.BalancerPlayerRoleEntry.rank_value,
            )
            .join(
                models.BalancerPlayerRoleEntry,
                models.BalancerPlayerRoleEntry.player_id == models.BalancerPlayer.id,
            )
            .join(
                models.Tournament,
                models.Tournament.id == models.BalancerPlayer.tournament_id,
            )
            .where(
                models.BalancerPlayer.user_id.in_(user_ids),
                models.Tournament.workspace_id == workspace_id,
                models.BalancerPlayer.tournament_id != current_tournament_id,
                models.BalancerPlayerRoleEntry.is_active.is_(True),
                models.BalancerPlayerRoleEntry.rank_value.is_not(None),
            )
            .order_by(
                models.BalancerPlayer.user_id,
                models.BalancerPlayerRoleEntry.role,
                models.Tournament.number.desc().nullslast(),
                models.BalancerPlayer.tournament_id.desc(),
            )
        )
    ).all()

    latest: dict[int, dict[str, int]] = {}
    for row in rows:
        user_map = latest.setdefault(row.user_id, {})
        if row.role not in user_map:
            user_map[row.role] = row.rank_value
    return latest


async def _load_rank_autofill_registrations(
    session: AsyncSession,
    tournament_id: int,
    registration_ids: list[int] | None,
) -> list[models.BalancerRegistration]:
    query = (
        sa.select(models.BalancerRegistration)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
        )
        .options(selectinload(models.BalancerRegistration.roles))
        .order_by(models.BalancerRegistration.battle_tag_normalized.asc().nullslast(), models.BalancerRegistration.id.asc())
    )
    if registration_ids is not None:
        if not registration_ids:
            return []
        query = query.where(models.BalancerRegistration.id.in_(registration_ids))
    result = await session.execute(query)
    return list(result.scalars().all())


async def _load_main_battle_tags_by_key(
    session: AsyncSession,
    registrations: list[models.BalancerRegistration],
) -> dict[str, models.UserBattleTag]:
    tag_keys = {
        key
        for registration in registrations
        if (key := (registration.battle_tag_normalized or normalize_battle_tag_key(registration.battle_tag)))
    }
    if not tag_keys:
        return {}

    tag_key_expr = sa.func.replace(sa.func.lower(models.UserBattleTag.battle_tag), " ", "")
    result = await session.execute(sa.select(models.UserBattleTag).where(tag_key_expr.in_(tag_keys)))
    return {
        key: battle_tag
        for battle_tag in result.scalars().all()
        if (key := normalize_battle_tag_key(battle_tag.battle_tag))
    }


async def _load_latest_rank_snapshots_by_battle_tag_id(
    session: AsyncSession,
    battle_tag_ids: list[int],
) -> dict[int, dict[str, models.UserRankSnapshot]]:
    if not battle_tag_ids:
        return {}
    result = await session.execute(
        sa.select(models.UserRankSnapshot)
        .where(
            models.UserRankSnapshot.battle_tag_id.in_(battle_tag_ids),
            models.UserRankSnapshot.role.in_(set(RANK_ROLE_BY_REGISTRATION_ROLE.values())),
            models.UserRankSnapshot.rank_value.is_not(None),
            models.UserRankSnapshot.is_ranked.is_(True),
        )
        .order_by(models.UserRankSnapshot.captured_at.desc(), models.UserRankSnapshot.id.desc())
    )
    snapshots_by_tag_id: dict[int, dict[str, models.UserRankSnapshot]] = {}
    for snapshot in result.scalars().all():
        role_map = snapshots_by_tag_id.setdefault(snapshot.battle_tag_id, {})
        role_map.setdefault(snapshot.role, snapshot)
    return snapshots_by_tag_id


async def autofill_registration_ranks_from_parsed(
    session: AsyncSession,
    tournament_id: int,
    *,
    registration_ids: list[int] | None = None,
    overwrite_existing: bool = False,
    add_to_balancer: bool = False,
    mode: str = "ow2_ranks",
    apply: bool = False,
) -> dict[str, Any]:
    if registration_ids is not None:
        registration_ids = list(dict.fromkeys(int(registration_id) for registration_id in registration_ids))

    tournament = await _load_tournament_for_autofill(session, tournament_id)
    grid = DivisionGrid.from_version(tournament.division_grid_version if tournament else None)

    registrations = await _load_rank_autofill_registrations(session, tournament_id, registration_ids)
    battle_tags_by_key = await _load_main_battle_tags_by_key(session, registrations)
    snapshots_by_tag_id = await _load_latest_rank_snapshots_by_battle_tag_id(
        session,
        [battle_tag.id for battle_tag in battle_tags_by_key.values()],
    )

    # For division_history mode: load balancer history keyed by user_id
    balancer_history_by_user_id: dict[int, dict[str, int]] = {}
    if mode == "division_history" and tournament is not None:
        user_ids = [
            battle_tag.user_id
            for battle_tag in battle_tags_by_key.values()
            if battle_tag.user_id is not None
        ]
        balancer_history_by_user_id = await _load_latest_ranks_from_balancer_history(
            session,
            user_ids,
            tournament_id,
            tournament.workspace_id,
        )

    players: list[dict[str, Any]] = []
    applied_registrations = 0
    role_updates = 0
    balancer_additions = 0
    now = datetime.now(UTC)

    for registration in registrations:
        tag_key = registration.battle_tag_normalized or normalize_battle_tag_key(registration.battle_tag)
        main_battle_tag = battle_tags_by_key.get(tag_key or "")
        raw_snapshots = snapshots_by_tag_id.get(main_battle_tag.id, {}) if main_battle_tag else {}

        rank_data_by_role: dict[str, _RankData | Any] = {}
        if mode == "ow2_ranks":
            for role, snapshot in raw_snapshots.items():
                rank_data_by_role[role] = _build_ow2_rank_data(snapshot, grid)
        elif mode == "division_history":
            user_id = getattr(main_battle_tag, "user_id", None) if main_battle_tag else None
            balancer_by_role = balancer_history_by_user_id.get(user_id or -1, {})
            for role, snapshot in raw_snapshots.items():
                if role in balancer_by_role:
                    rank_data_by_role[role] = _RankData(
                        rank_value=balancer_by_role[role],
                        source="balancer",
                    )
                else:
                    rank_data_by_role[role] = _RankData(
                        rank_value=getattr(snapshot, "rank_value", None),
                        platform=getattr(snapshot, "platform", None),
                        division=getattr(snapshot, "division", None),
                        tier=getattr(snapshot, "tier", None),
                        season=getattr(snapshot, "season", None),
                        captured_at=getattr(snapshot, "captured_at", None),
                        source="analytics",
                    )
        else:
            rank_data_by_role = dict(raw_snapshots)

        row, updates = build_registration_rank_autofill_plan(
            registration,
            rank_data_by_role,
            battle_tag_linked=main_battle_tag is not None,
            overwrite_existing=overwrite_existing,
            applied=apply,
        )
        will_add_to_balancer, balancer_reason = _rank_autofill_balancer_addition(
            registration,
            updates,
            add_to_balancer=add_to_balancer,
        )
        row["will_add_to_balancer"] = will_add_to_balancer
        row["balancer_reason"] = balancer_reason

        changed = False
        if apply and updates:
            for role_entry, rank_data in updates:
                role_entry.rank_value = getattr(rank_data, "rank_value", None)
                role_updates += 1
            registration.balancer_profile_overridden_at = now
            applied_registrations += 1
            changed = True
        elif not apply:
            role_updates += len(updates)

        if apply and will_add_to_balancer:
            registration.exclude_from_balancer = False
            registration.exclude_reason = None
            registration.balancer_status = included_balancer_status(registration)
            balancer_additions += 1
            changed = True
        elif not apply and will_add_to_balancer:
            balancer_additions += 1

        if apply and changed:
            if not will_add_to_balancer:
                sync_included_balancer_status(registration)
            _register_registration_changed(session, registration)

        players.append(row)

    if apply and (applied_registrations > 0 or balancer_additions > 0):
        await session.commit()

    updatable_registrations = sum(1 for row in players if row["status"] in {"will_update", "applied"})
    skipped_registrations = sum(1 for row in players if row["status"] == "skipped")
    unchanged_registrations = sum(1 for row in players if row["status"] == "unchanged")

    return {
        "total_registrations": len(players),
        "updatable_registrations": updatable_registrations,
        "applied_registrations": applied_registrations,
        "skipped_registrations": skipped_registrations,
        "unchanged_registrations": unchanged_registrations,
        "role_updates": role_updates,
        "overwrite_existing": overwrite_existing,
        "add_to_balancer": add_to_balancer,
        "balancer_additions": balancer_additions,
        "players": players,
    }


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
    is_flex: bool,
    roles: list[dict[str, Any]],
) -> models.BalancerRegistration:
    battle_tag = normalize_battle_tag(battle_tag)
    await ensure_unique_battle_tag(session, tournament_id=tournament_id, battle_tag=battle_tag)

    form = await get_registration_form(session, tournament_id)
    config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
    hero_catalog = None
    max_heroes = None
    if config and config.get("enabled", True) is not False:
        from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, resolve_hero_catalog
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
        is_flex=is_flex,
        status="approved",
        exclude_from_balancer=False,
        submitted_at=datetime.now(UTC),
        balancer_profile_overridden_at=datetime.now(UTC),
    )
    replace_registration_roles(registration, roles, hero_catalog=hero_catalog, max_heroes=max_heroes)
    registration.is_flex = registration.is_flex_computed
    session.add(registration)
    await session.flush()
    await enqueue_registration_approved(session, registration)
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
    is_flex: bool | None,
    status_value: str | None,
    balancer_status_value: str | None,
    roles: list[dict[str, Any]] | None,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    previous_status = registration.status
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
    if is_flex is not None:
        registration.is_flex = is_flex
        override_changed = True
    if roles is not None:
        for r_obj in registration.roles:
            r_obj.hero_entries.clear()
        await session.flush()

        form = await get_registration_form(session, registration.tournament_id)
        config = (form.built_in_fields_json or {}).get("top_heroes") if form else None
        hero_catalog = None
        max_heroes = None
        if config and config.get("enabled", True) is not False:
            from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, resolve_hero_catalog
            hero_catalog = await resolve_hero_catalog(session)
            raw_max = config.get("max_heroes")
            max_heroes = raw_max if isinstance(raw_max, int) and raw_max > 0 else DEFAULT_MAX_TOP_HEROES

        replace_registration_roles(registration, roles, hero_catalog=hero_catalog, max_heroes=max_heroes)
        registration.is_flex = registration.is_flex_computed
        sync_included_balancer_status(registration)
        override_changed = True
    if override_changed:
        registration.balancer_profile_overridden_at = datetime.now(UTC)

    if status_value == "approved" and previous_status != "approved":
        await enqueue_registration_approved(session, registration)
    elif status_value == "rejected" and previous_status != "rejected":
        await enqueue_registration_rejected(session, registration)
    else:
        _register_registration_changed(session, registration)

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
    await enqueue_registration_approved(session, registration)
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
    await enqueue_registration_rejected(session, registration)
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
        sa.select(models.BalancerRegistration).where(
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
        await enqueue_registration_approved(session, registration)
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
    _register_registration_changed(session, registration)
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def withdraw_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "withdrawn"
    _register_registration_changed(session, registration)
    await session.commit()
    return await get_registration_by_id(session, registration.id)


async def restore_registration(
    session: AsyncSession,
    registration_id: int,
) -> models.BalancerRegistration:
    registration = await get_registration_by_id(session, registration_id)
    registration.status = "approved"
    _register_registration_changed(session, registration)
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
    _register_registration_changed(session, registration)
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
    _register_registration_changed(session, registration)
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
    _register_registration_changed(session, registration)
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
    _register_registration_changed(session, registration)
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
        registration.balancer_status = (
            included_balancer_status(registration) if balancer_status == "ready" else balancer_status
        )
        registration.exclude_from_balancer = balancer_status == "not_in_balancer"
        registration.exclude_reason = None
        _register_registration_changed(session, registration)
    await session.commit()
    return len(registrations), len(registration_ids) - len(registrations)


def apply_sheet_fields_to_registration(
    registration: models.BalancerRegistration,
    parsed_fields: dict[str, Any],
    *,
    allow_balancer_overwrite: bool,
) -> None:
    registration.display_name = (
        parsed_fields.get("display_name") or parsed_fields.get("battle_tag") or registration.display_name
    )
    if parsed_fields.get("battle_tag") is not None:
        registration.battle_tag = parsed_fields["battle_tag"]
        registration.battle_tag_normalized = normalize_battle_tag_key(parsed_fields["battle_tag"])
    registration.smurf_tags_json = parsed_fields.get("smurf_tags") or None
    registration.discord_nick = parsed_fields.get("discord_nick")
    registration.twitch_nick = parsed_fields.get("twitch_nick")
    registration.stream_pov = bool(parsed_fields.get("stream_pov", False))
    registration.notes = parsed_fields.get("notes")

    parsed_custom = parsed_fields.get("custom_fields")
    if parsed_custom:
        merged = dict(registration.custom_fields_json or {})
        merged.update(parsed_custom)
        registration.custom_fields_json = merged or None

    if allow_balancer_overwrite:
        registration.admin_notes = parsed_fields.get("admin_notes")
        replace_registration_roles(registration, build_registration_role_payloads(parsed_fields))
        registration.is_flex = registration.is_flex_computed
        sync_included_balancer_status(registration)


SYNC_ERROR_SAMPLE_LIMIT = 20


@dataclass
class SheetSyncResult:
    feed: models.BalancerRegistrationGoogleSheetFeed
    created: int
    updated: int
    withdrawn: int
    total: int
    skipped: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


async def sync_google_sheet_feed(
    session: AsyncSession,
    tournament_id: int,
) -> SheetSyncResult:
    feed = await require_google_sheet_feed(session, tournament_id)
    grid = await get_tournament_grid(session, tournament_id)
    tournament = await ensure_tournament_exists(session, tournament_id)
    custom_fields = await get_form_custom_field_defs(session, tournament_id)
    now = datetime.now(UTC)

    try:
        rows = await fetch_google_sheet_rows(feed.source_url, sheet_id=feed.sheet_id, gid=feed.gid)
        headers = rows[0]
        mapping_config = feed.mapping_config_json or suggest_mapping_from_headers(headers, custom_fields=custom_fields)
        value_mapping = feed.value_mapping_json or build_default_value_mapping()

        parsed_rows: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
        skipped = 0
        row_errors: list[dict[str, Any]] = []
        for row_index, row in enumerate(rows[1:]):
            result = parse_sheet_row_detailed(
                headers=headers,
                row=row,
                mapping_config=mapping_config,
                value_mapping=value_mapping,
                grid=grid,
                custom_fields=custom_fields,
            )
            for entry in result.errors:
                if len(row_errors) < SYNC_ERROR_SAMPLE_LIMIT:
                    row_errors.append({**entry, "row_index": row_index})
            if not result.fields:
                skipped += 1
                continue
            parsed_rows[result.fields["source_record_key"]] = (row_to_json(headers, row), result.fields)

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
                    custom_fields_json=parsed_fields.get("custom_fields") or None,
                    is_flex=bool(parsed_fields.get("is_flex", False)),
                    status="approved",
                    exclude_from_balancer=False,
                    submitted_at=parsed_fields.get("submitted_at") or now,
                )
                replace_registration_roles(registration, build_registration_role_payloads(parsed_fields))
                registration.is_flex = registration.is_flex_computed
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
        if skipped or row_errors:
            summary = f"Synced with {skipped} skipped row(s)"
            if row_errors:
                summary += f" and {len(row_errors)} field error(s)"
            feed.last_error = summary
        else:
            feed.last_error = None
        if created or updated or withdrawn:
            register_tournament_realtime_update(session, tournament_id, "structure_changed")
        await session.commit()
        await session.refresh(feed)
        return SheetSyncResult(
            feed=feed,
            created=created,
            updated=updated,
            withdrawn=withdrawn,
            total=len(parsed_rows),
            skipped=skipped,
            errors=row_errors,
        )
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
        interval = timedelta(
            seconds=max(
                int(feed.auto_sync_interval_seconds or DEFAULT_SYNC_INTERVAL_SECONDS), MIN_SYNC_INTERVAL_SECONDS
            )
        )
        if feed.last_synced_at is not None and feed.last_synced_at > now - interval:
            continue
        async with session_factory() as session:
            try:
                sync_result = await sync_google_sheet_feed(session, feed.tournament_id)
                results.append(
                    {
                        "tournament_id": feed.tournament_id,
                        "status": "success",
                        "created": sync_result.created,
                        "updated": sync_result.updated,
                        "withdrawn": sync_result.withdrawn,
                        "total": sync_result.total,
                        "skipped": sync_result.skipped,
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
            # Mirror the panel's "in balancer" rule (load_pool): a registration is
            # part of the pool only once it has been added (balancer_status set).
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


async def _find_user_by_battle_tag(session: AsyncSession, battle_tag: str) -> models.User | None:
    result = await session.execute(
        sa.select(models.User)
        .join(models.UserBattleTag, models.User.id == models.UserBattleTag.user_id)
        .where(
            sa.or_(
                models.UserBattleTag.battle_tag == battle_tag,
                sa.func.lower(models.UserBattleTag.battle_tag) == battle_tag.lower(),
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_user_battle_tag(session: AsyncSession, user: models.User, battle_tag: str) -> None:
    exists = await session.scalar(
        sa.select(models.UserBattleTag.id).where(
            sa.or_(
                models.UserBattleTag.battle_tag == battle_tag,
                sa.func.lower(models.UserBattleTag.battle_tag) == battle_tag.lower(),
            )
        )
    )
    if exists is not None:
        return
    try:
        name, tag = battle_tag.split("#", 1)
    except ValueError:
        return
    session.add(
        models.UserBattleTag(
            user_id=user.id,
            battle_tag=battle_tag,
            name=name,
            tag=tag,
        )
    )


async def _ensure_user_identity(session: AsyncSession, user: models.User, model: type, value: str | None) -> None:
    if not value:
        return
    exists = await session.scalar(sa.select(model.id).where(model.name == value))
    if exists is None:
        session.add(model(user_id=user.id, name=value))


async def _upsert_user_from_registration(
    session: AsyncSession,
    registration: models.BalancerRegistration,
    *,
    battle_tag: str,
) -> None:
    user = await _find_user_by_battle_tag(session, battle_tag)
    if user is None:
        user = models.User(name=battle_tag)
        session.add(user)
        await session.flush()

    await _ensure_user_battle_tag(session, user, battle_tag)
    for smurf in registration.smurf_tags_json or []:
        if BATTLE_TAG_RE.match(smurf):
            await _ensure_user_battle_tag(session, user, smurf)
    await _ensure_user_identity(session, user, models.UserDiscord, registration.discord_nick)
    await _ensure_user_identity(session, user, models.UserTwitch, registration.twitch_nick)


async def export_registrations_to_users(
    session: AsyncSession,
    tournament_id: int,
) -> dict[str, int]:
    registrations = await list_registrations(session, tournament_id, include_deleted=False, status_filter="approved")

    processed = 0
    skipped = 0
    for registration in registrations:
        battle_tag = registration.battle_tag
        if not battle_tag:
            skipped += 1
            continue
        try:
            await _upsert_user_from_registration(session, registration, battle_tag=battle_tag)
        except Exception:
            logger.exception("Failed to build user payload for registration %s", battle_tag)
            skipped += 1
            continue

        processed += 1

    await session.commit()
    return {"processed": processed, "skipped": skipped, "total": len(registrations)}
