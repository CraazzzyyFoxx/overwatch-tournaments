from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import sqlalchemy as sa
from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from shared.balancer_registration_statuses import get_builtin_status_values
from shared.core import enums
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.core.social import SocialProvider
from shared.domain.player_sub_roles import REGISTRATION_TO_CANONICAL, normalize_sub_role
from shared.hero_catalog import HeroCatalog
from shared.services import social_identity
from shared.services.division_grid_normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
    build_division_grid_normalizer,
)
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
from src.services.registration.service import ensure_player_identity
from src.services.registration.utils import (
    DEFAULT_BOOLEAN_TRUE_VALUES,
    DEFAULT_SORT_PRIORITY_SENTINEL,
    DEFAULT_SYNC_INTERVAL_SECONDS,
    GOOGLE_SHEET_FETCH_TIMEOUT,
    MIN_SYNC_INTERVAL_SECONDS,
    ROLE_ORDER,
    UNKNOWN_PRIORITY_SENTINEL,
    VALID_ROLES,
    RoleSubroleEntry,
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
    """Resolved rank value for autofill, abstracting over snapshot and balancer history.

    ``rank_value`` is the *chosen* (suggested) value. The ``*_rank_value`` breakdown fields
    carry every candidate signal that was considered so the UI can surface why a value was
    picked, and ``used_source`` names the candidate that won.
    """

    rank_value: int | None
    platform: str | None = None
    division: str | None = None
    tier: int | None = None
    season: int | None = None
    captured_at: datetime | None = None
    source: str = "analytics"
    division_history_rank_value: int | None = None
    ow_rank_value: int | None = None
    ow_current_rank_value: int | None = None
    analytics_rank_value: int | None = None
    used_source: str | None = None


@dataclass
class _OwRankSignals:
    """Weekly OW rank signal for a single (battle_tag, role).

    ``composite_rank_value`` is ``round((max + mean) / 2)`` over the chosen weekly window of
    mapped OW ``rank_value`` snapshots (see ``_compute_ow_week_rank_value``). ``latest_snapshot``
    is the most recent snapshot, kept for display metadata (platform/division/season/captured_at)
    and for the contextual "OW current" value.
    """

    composite_rank_value: int | None = None
    latest_snapshot: models.UserRankSnapshot | Any | None = None


@dataclass(frozen=True)
class _ResolvedAutofillStage:
    """One enabled source in the resolved autofill chain, with its lookback window.

    ``lookback_tournaments`` applies to the tournament-based sources (``division_history``,
    ``analytics``); ``lookback_days`` overrides the OW weekly window. The irrelevant field for a
    given ``source`` is simply ignored by the orchestrator.
    """

    source: str
    lookback_tournaments: int | None = None
    lookback_days: int | None = None


# Registration role code -> canonical RankRole value (e.g. dps -> damage). Single source of
# truth is shared.domain.player_sub_roles; aliased here for the autofill snapshot lookups.
RANK_ROLE_BY_REGISTRATION_ROLE = dict(REGISTRATION_TO_CANONICAL)
REGISTRATION_ROLE_LABELS = {
    "tank": "Tank",
    "dps": "Damage",
    "support": "Support",
}
# tournament.player.role is a HeroClass (Tank/Damage/Support); bridge it to the registration
# role codes (tank/dps/support) used to key balancer history and the per-role rank data.
HERO_CLASS_TO_REGISTRATION_ROLE = {
    enums.HeroClass.tank: "tank",
    enums.HeroClass.damage: "dps",
    enums.HeroClass.support: "support",
}
# Window for the OW rank source: aggregate snapshots captured within one week.
OW_RANK_WEEK_WINDOW = timedelta(days=7)


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
            "division_history_rank_value": None,
            "ow_rank_value": None,
            "ow_current_rank_value": None,
            "analytics_rank_value": None,
            "used_source": None,
        }
    return {
        "parsed_rank_value": getattr(snapshot, "rank_value", None),
        "platform": getattr(snapshot, "platform", None),
        "division": getattr(snapshot, "division", None),
        "tier": getattr(snapshot, "tier", None),
        "season": getattr(snapshot, "season", None),
        "captured_at": getattr(snapshot, "captured_at", None),
        "source": getattr(snapshot, "source", "analytics"),
        "division_history_rank_value": getattr(snapshot, "division_history_rank_value", None),
        "ow_rank_value": getattr(snapshot, "ow_rank_value", None),
        "ow_current_rank_value": getattr(snapshot, "ow_current_rank_value", None),
        "analytics_rank_value": getattr(snapshot, "analytics_rank_value", None),
        "used_source": getattr(snapshot, "used_source", None),
    }


def build_registration_rank_autofill_plan(
    registration: models.BalancerRegistration | Any,
    rank_snapshots_by_role: dict[str, models.UserRankSnapshot | Any],
    *,
    battle_tag_linked: bool,
    overwrite_existing: bool,
    allow_partial: bool = False,
    applied: bool = False,
) -> tuple[dict[str, Any], list[tuple[Any, Any]]]:
    """Build the rank autofill preview row and pending role updates.

    Only active registration roles are considered, and parsed ranks are expected to come from the
    registration's main battle tag only. With ``allow_partial`` the found role ranks are still
    applied when other active roles have no parsed rank (instead of skipping the whole registration);
    unfilled roles are left untouched — an existing rank is never cleared. A role that has a current
    rank no enabled source could corroborate is reported as ``unverified`` (informational only).
    """

    display_name = getattr(registration, "display_name", None)
    battle_tag = getattr(registration, "battle_tag", None)
    row = {
        "registration_id": registration.id,
        "display_name": display_name,
        "battle_tag": battle_tag,
        "status": "skipped",
        "reason": None,
        "partial": False,
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
            if parsed_rank is None:
                role_row["action"] = "unverified"
                role_row["reason"] = "Current rank kept; no enabled source found a value to verify it."
            else:
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

    if missing_roles and not allow_partial:
        # All-or-nothing: one unparsed role skips the whole registration and blocks its updates.
        row["reason"] = f"No parsed rank for registered role(s): {', '.join(missing_roles)}."
        for role_row in row["roles"]:
            if role_row["action"] in {"set", "overwrite"}:
                role_row["action"] = "blocked"
                role_row["reason"] = "Player skipped because another registered role has no parsed rank."
        return row, []

    if updates:
        row["status"] = "applied" if applied else "will_update"
        if missing_roles:
            # allow_partial: apply what was found, leave the unparsed roles untouched.
            row["partial"] = True
            row["reason"] = f"Partial: applied found ranks; no parsed rank for {', '.join(missing_roles)}."
        return row, updates

    if missing_roles:
        # allow_partial but nothing to apply (the parsed roles already matched / were kept).
        row["reason"] = f"No parsed rank for registered role(s): {', '.join(missing_roles)}."
        return row, []

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
        sa.select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.division_grid_version).selectinload(
                models.DivisionGridVersion.tiers
            )
        )
    )
    return result.scalar_one_or_none()


def _normalize_history_rank(
    normalizer: DivisionGridNormalizer | None,
    source_version_id: int | None,
    rank: int | None,
    target_grid: DivisionGrid,
) -> int | None:
    """Map a historical rank from its source tournament's grid version into the target grid.

    Returns the target tier's ``rank_min``. When no normalizer/source version is available the
    rank is returned unchanged; when a primary mapping is missing it falls back to matching the
    division *number* (stable across grids), mirroring the frontend ``safeNormalize``.
    """
    if rank is None:
        return None
    if normalizer is None or source_version_id is None:
        return rank
    try:
        return normalizer.normalize_division(source_version_id, rank).rank_min
    except DivisionGridNormalizationError:
        source_grid = normalizer.source_grids_by_version_id.get(source_version_id, target_grid)
        number = source_grid.resolve_division_number(rank)
        mapped = target_grid.resolve_rank_from_division(number)
        return mapped if mapped is not None else rank


async def _build_autofill_rank_normalizer(
    session: AsyncSession,
    tournament: models.Tournament | Any,
) -> DivisionGridNormalizer | None:
    """Build a normalizer targeting the tournament's grid version, or None if unavailable.

    ``require_complete=False`` so a workspace with partially-mapped grids still builds; per-rank
    misses are handled by ``_normalize_history_rank``'s division-number fallback.
    """
    target_version_id = getattr(tournament, "division_grid_version_id", None)
    if target_version_id is None:
        return None
    try:
        return await build_division_grid_normalizer(
            session,
            tournament.workspace_id,
            target_version_id=target_version_id,
            require_complete=False,
        )
    except DivisionGridNormalizationError:
        return None


async def _load_latest_ranks_from_balancer_history(
    session: AsyncSession,
    user_ids: list[int],
    current_tournament_id: int,
    workspace_id: int,
    normalizer: DivisionGridNormalizer | None,
    target_grid: DivisionGrid,
    min_tournament_number: int | None = None,
) -> dict[int, dict[str, int]]:
    """Return dict[user_id][role_code] → rank_value from past registration records.

    Searches the workspace's previous tournaments (excluding the current one), ordered
    by tournament number descending so the most recent entry wins. Ranks are normalized from
    each source tournament's grid version into the target grid. When ``min_tournament_number`` is
    set, only tournaments whose ``number`` is at least that cutoff are considered (recency window;
    rows with a ``NULL`` number naturally fall outside the window).
    """
    if not user_ids:
        return {}

    stmt = (
        sa.select(
            models.BalancerRegistration.user_id,
            models.BalancerRegistrationRole.role,
            models.BalancerRegistrationRole.rank_value,
            models.Tournament.division_grid_version_id,
        )
        .join(
            models.BalancerRegistrationRole,
            models.BalancerRegistrationRole.registration_id == models.BalancerRegistration.id,
        )
        .join(
            models.Tournament,
            models.Tournament.id == models.BalancerRegistration.tournament_id,
        )
        .where(
            models.BalancerRegistration.user_id.in_(user_ids),
            models.Tournament.workspace_id == workspace_id,
            models.BalancerRegistration.tournament_id != current_tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistrationRole.is_active.is_(True),
            models.BalancerRegistrationRole.rank_value.is_not(None),
        )
        .order_by(
            models.BalancerRegistration.user_id,
            models.BalancerRegistrationRole.role,
            models.Tournament.number.desc().nullslast(),
            models.BalancerRegistration.tournament_id.desc(),
        )
    )
    if min_tournament_number is not None:
        stmt = stmt.where(models.Tournament.number >= min_tournament_number)

    rows = (await session.execute(stmt)).all()

    latest: dict[int, dict[str, int]] = {}
    for row in rows:
        user_map = latest.setdefault(row.user_id, {})
        if row.role not in user_map:
            normalized = _normalize_history_rank(
                normalizer, row.division_grid_version_id, row.rank_value, target_grid
            )
            if normalized is not None:
                user_map[row.role] = normalized
    return latest


async def _load_latest_ranks_from_tournament_history(
    session: AsyncSession,
    user_ids: list[int],
    current_tournament_id: int,
    workspace_id: int,
    normalizer: DivisionGridNormalizer | None,
    target_grid: DivisionGrid,
    min_tournament_number: int | None = None,
) -> dict[int, dict[str, int]]:
    """Return dict[user_id][registration_role_code] → rank from past tournament participation.

    This is the "analytics" source: actual ranks played in the workspace's previous tournaments
    (``tournament.player``), distinct from the balancer-registration history. Excludes the current
    tournament and substitution rows; the most recent tournament wins per role. ``Player.role`` is
    a HeroClass and is bridged to the registration role code (Damage → dps) to match keying. Ranks
    are normalized from each source tournament's grid version into the target grid. When
    ``min_tournament_number`` is set, only tournaments whose ``number`` is at least that cutoff are
    considered (recency window; rows with a ``NULL`` number naturally fall outside the window).
    """
    if not user_ids:
        return {}

    stmt = (
        sa.select(
            models.Player.user_id,
            models.Player.role,
            models.Player.rank,
            models.Tournament.division_grid_version_id,
        )
        .join(
            models.Tournament,
            models.Tournament.id == models.Player.tournament_id,
        )
        .where(
            models.Player.user_id.in_(user_ids),
            models.Tournament.workspace_id == workspace_id,
            models.Player.tournament_id != current_tournament_id,
            models.Player.role.is_not(None),
            models.Player.is_substitution.is_(False),
            models.Player.rank > 0,
        )
        .order_by(
            models.Player.user_id,
            models.Player.role,
            models.Tournament.number.desc().nullslast(),
            models.Player.tournament_id.desc(),
        )
    )
    if min_tournament_number is not None:
        stmt = stmt.where(models.Tournament.number >= min_tournament_number)

    rows = (await session.execute(stmt)).all()

    latest: dict[int, dict[str, int]] = {}
    for row in rows:
        role_code = HERO_CLASS_TO_REGISTRATION_ROLE.get(row.role)
        if role_code is None:
            continue
        user_map = latest.setdefault(row.user_id, {})
        if role_code not in user_map:
            normalized = _normalize_history_rank(
                normalizer, row.division_grid_version_id, row.rank, target_grid
            )
            if normalized is not None:
                user_map[role_code] = normalized
    return latest


async def load_user_balancer_rank_history(
    session: AsyncSession,
    *,
    user_id: int,
    workspace_id: int,
) -> list[dict[str, Any]]:
    """Per (tournament, role) ranks from a user's past balancer registrations in a workspace.

    Newest tournament first; only active, ranked roles. Powers the balancer step of the
    PlayerEditSheet "Load from history" preview (source = "balancer").
    """
    rows = (
        await session.execute(
            sa.select(
                models.Tournament.id.label("tournament_id"),
                models.Tournament.number.label("tournament_number"),
                models.Tournament.name.label("tournament_name"),
                models.BalancerRegistrationRole.role,
                models.BalancerRegistrationRole.rank_value,
            )
            .join(
                models.BalancerRegistration,
                models.BalancerRegistration.id == models.BalancerRegistrationRole.registration_id,
            )
            .join(
                models.Tournament,
                models.Tournament.id == models.BalancerRegistration.tournament_id,
            )
            .where(
                models.BalancerRegistration.user_id == user_id,
                models.Tournament.workspace_id == workspace_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistrationRole.is_active.is_(True),
                models.BalancerRegistrationRole.rank_value.is_not(None),
            )
            .order_by(
                models.Tournament.number.desc().nullslast(),
                models.BalancerRegistration.tournament_id.desc(),
            )
        )
    ).all()

    return [
        {
            "tournament_id": row.tournament_id,
            "tournament_number": row.tournament_number,
            "tournament_name": row.tournament_name,
            "role": row.role,
            "rank_value": row.rank_value,
        }
        for row in rows
    ]


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
) -> dict[str, models.SocialAccount]:
    """Map normalized battletag key → the battlenet ``social_account`` it belongs to.

    ``social_account.username_normalized`` (battlenet) is exactly
    ``normalize_battle_tag_key`` of the handle, so registration keys match directly.
    """
    tag_keys = {
        key
        for registration in registrations
        if (key := (registration.battle_tag_normalized or normalize_battle_tag_key(registration.battle_tag)))
    }
    if not tag_keys:
        return {}

    acc = models.SocialAccount
    result = await session.execute(
        sa.select(acc).where(
            acc.provider == SocialProvider.BATTLENET,
            acc.username_normalized.in_(tag_keys),
        )
    )
    return {
        account.username_normalized: account
        for account in result.scalars().all()
        if account.username_normalized
    }


async def _load_ow_rank_signals_by_social_account_id(
    session: AsyncSession,
    social_account_ids: list[int],
    now: datetime,
    week_window: timedelta = OW_RANK_WEEK_WINDOW,
) -> dict[int, dict[str, _OwRankSignals]]:
    """Return per (social_account_id, rank_role) the weekly OW rank composite + latest snapshot."""
    if not social_account_ids:
        return {}
    result = await session.execute(
        sa.select(models.UserRankSnapshot)
        .where(
            models.UserRankSnapshot.social_account_id.in_(social_account_ids),
            models.UserRankSnapshot.role.in_(set(RANK_ROLE_BY_REGISTRATION_ROLE.values())),
            models.UserRankSnapshot.rank_value.is_not(None),
            models.UserRankSnapshot.is_ranked.is_(True),
        )
        .order_by(models.UserRankSnapshot.captured_at.desc(), models.UserRankSnapshot.id.desc())
    )
    return _group_ow_rank_signals(result.scalars().all(), now, week_window)


def _group_ow_rank_signals(
    snapshots_newest_first: Iterable[models.UserRankSnapshot | Any],
    now: datetime,
    week_window: timedelta = OW_RANK_WEEK_WINDOW,
) -> dict[int, dict[str, _OwRankSignals]]:
    """Group newest-first snapshots into per (social_account_id, role) weekly OW signals.

    Pure (no DB) so the windowing logic can be unit-tested. For each (tag, role) the composite
    rank is ``round((max + mean) / 2)`` over the ``week_window`` (see ``_compute_ow_week_rank_value``);
    the first snapshot seen (newest) is kept as the latest for display metadata.
    """
    grouped: dict[int, dict[str, list[Any]]] = {}
    for snapshot in snapshots_newest_first:
        grouped.setdefault(snapshot.social_account_id, {}).setdefault(snapshot.role, []).append(snapshot)

    signals_by_tag_id: dict[int, dict[str, _OwRankSignals]] = {}
    for tag_id, role_map in grouped.items():
        out = signals_by_tag_id.setdefault(tag_id, {})
        for role, snaps in role_map.items():
            out[role] = _OwRankSignals(
                composite_rank_value=_compute_ow_week_rank_value(snaps, now, week_window),
                latest_snapshot=snaps[0] if snaps else None,
            )
    return signals_by_tag_id


def _compute_ow_week_rank_value(
    snapshots: Iterable[models.UserRankSnapshot | Any],
    now: datetime,
    week_window: timedelta = OW_RANK_WEEK_WINDOW,
) -> int | None:
    """Composite OW rank over a weekly window: ``round((max + mean) / 2)`` of mapped rank_value.

    Window selection (per role), using ``week_window`` (default 7 days):
      1. snapshots captured within the last ``week_window`` from ``now``;
      2. if none, snapshots within ``week_window`` of the player's most recent snapshot;
      3. if still none (no usable timestamps), the single most-recent snapshot.
    Returns ``None`` only when there are no snapshots carrying a ``rank_value``.
    """
    snaps = [s for s in snapshots if getattr(s, "rank_value", None) is not None]
    if not snaps:
        return None

    dated = [s for s in snaps if getattr(s, "captured_at", None) is not None]
    window = [s for s in dated if s.captured_at >= now - week_window]
    if not window and dated:
        latest_at = max(s.captured_at for s in dated)
        window = [s for s in dated if s.captured_at >= latest_at - week_window]
    if not window:
        window = [snaps[0]]

    values = [s.rank_value for s in window]
    return round((max(values) + sum(values) / len(values)) / 2)


# Legacy ``mode`` presets, expressed as a default stage order. Used only when no explicit stage
# chain is supplied on the request.
_DEFAULT_STAGE_ORDER_BY_MODE: dict[str, tuple[str, ...]] = {
    "ow_first": ("ow", "division_history", "analytics"),
    "balancer_first": ("division_history", "analytics", "ow"),
}


def resolve_autofill_stages(
    mode: str | None,
    stages: Sequence[Any] | None,
) -> list[_ResolvedAutofillStage]:
    """Resolve the effective, ordered list of enabled autofill stages.

    When ``stages`` is non-empty it wins: disabled entries are dropped and duplicate sources are
    de-duplicated (first occurrence kept), preserving order. Otherwise the legacy ``mode`` preset
    order is used, with no lookback windows. ``stages`` items are duck-typed (``source``,
    ``enabled``, ``lookback_tournaments``, ``lookback_days``) so unit tests can pass simple objects.
    """
    if stages:
        resolved: list[_ResolvedAutofillStage] = []
        seen: set[str] = set()
        for stage in stages:
            if not getattr(stage, "enabled", True):
                continue
            source = getattr(stage, "source", None)
            if source is None or source in seen:
                continue
            seen.add(source)
            resolved.append(
                _ResolvedAutofillStage(
                    source=source,
                    lookback_tournaments=getattr(stage, "lookback_tournaments", None),
                    lookback_days=getattr(stage, "lookback_days", None),
                )
            )
        return resolved

    order = _DEFAULT_STAGE_ORDER_BY_MODE.get(mode or "ow_first", _DEFAULT_STAGE_ORDER_BY_MODE["ow_first"])
    return [_ResolvedAutofillStage(source=source) for source in order]


def _build_priority_rank_data(
    order: Sequence[str],
    signals: _OwRankSignals | None,
    division_history_rank: int | None,
    analytics_rank: int | None,
    grid: DivisionGrid,
) -> _RankData | None:
    """Pick a rank by strict priority fallback over the given (enabled, ordered) source chain.

    ``order`` lists the enabled sources in priority order (subset of ``ow`` / ``division_history`` /
    ``analytics``). The first source carrying a value wins (no max blending). Returns ``None`` when
    no source in ``order`` carries a value (the role is then treated as missing).
    """
    latest_snapshot = signals.latest_snapshot if signals else None
    ow_rank = _map_ow_rank_value(signals.composite_rank_value, grid) if signals else None
    ow_current_rank = _map_ow_snapshot_rank(latest_snapshot, grid)

    candidates: dict[str, int | None] = {
        "ow": ow_rank,
        "division_history": division_history_rank,
        "analytics": analytics_rank,
    }

    used_source = next((source for source in order if candidates.get(source) is not None), None)
    if used_source is None:
        return None
    chosen = candidates[used_source]

    source = "balancer" if used_source == "division_history" else "analytics"
    return _RankData(
        rank_value=chosen,
        platform=getattr(latest_snapshot, "platform", None),
        division=getattr(latest_snapshot, "division", None),
        tier=getattr(latest_snapshot, "tier", None),
        season=getattr(latest_snapshot, "season", None),
        captured_at=getattr(latest_snapshot, "captured_at", None),
        source=source,
        division_history_rank_value=division_history_rank,
        ow_rank_value=ow_rank,
        ow_current_rank_value=ow_current_rank,
        analytics_rank_value=analytics_rank,
        used_source=used_source,
    )


def _map_ow_rank_value(ow_rank_value: int | None, grid: DivisionGrid) -> int | None:
    """Map an OW ``rank_value`` to a tournament division rank via the grid, or None if unmapped."""
    if ow_rank_value is None:
        return None
    tier = grid.resolve_division_from_ow_rank(ow_rank_value)
    return tier.rank_min if tier is not None else None


def _map_ow_snapshot_rank(snapshot: models.UserRankSnapshot | Any | None, grid: DivisionGrid) -> int | None:
    """Map a single OW snapshot to a tournament division rank via the grid, or None if unmapped."""
    if snapshot is None:
        return None
    return _map_ow_rank_value(getattr(snapshot, "rank_value", None), grid)


def _autofill_lookback_cutoff(target_number: int | None, lookback_tournaments: int | None) -> int | None:
    """Min ``Tournament.number`` for a "last N tournaments" window, or None when not applicable.

    Returns ``target_number - lookback_tournaments`` so that tournaments numbered
    ``[target - N, target)`` (the N immediately preceding the current one, which is excluded
    elsewhere) qualify. ``None`` when no window is requested or the current tournament has no number.
    """
    if lookback_tournaments is None or target_number is None:
        return None
    return target_number - lookback_tournaments


async def autofill_registration_ranks_from_parsed(
    session: AsyncSession,
    tournament_id: int,
    *,
    registration_ids: list[int] | None = None,
    overwrite_existing: bool = False,
    add_to_balancer: bool = False,
    allow_partial: bool = False,
    mode: str = "ow_first",
    stages: Sequence[Any] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    if registration_ids is not None:
        registration_ids = list(dict.fromkeys(int(registration_id) for registration_id in registration_ids))

    # Resolve the effective, ordered chain of enabled sources (explicit ``stages`` win over ``mode``).
    resolved_stages = resolve_autofill_stages(mode, stages)
    order = tuple(stage.source for stage in resolved_stages)
    enabled_sources = set(order)
    ow_lookback_days = next((s.lookback_days for s in resolved_stages if s.source == "ow"), None)
    division_lookback = next(
        (s.lookback_tournaments for s in resolved_stages if s.source == "division_history"), None
    )
    analytics_lookback = next(
        (s.lookback_tournaments for s in resolved_stages if s.source == "analytics"), None
    )

    now = datetime.now(UTC)
    tournament = await _load_tournament_for_autofill(session, tournament_id)
    grid = DivisionGrid.from_version(tournament.division_grid_version if tournament else None)
    target_number = getattr(tournament, "number", None) if tournament is not None else None

    registrations = await _load_rank_autofill_registrations(session, tournament_id, registration_ids)
    battle_tags_by_key = await _load_main_battle_tags_by_key(session, registrations)

    # Only load a source when its stage is enabled (skips its DB query otherwise). A disabled
    # source contributes no candidate, so it can never win the priority chain.
    ow_signals_by_tag_id: dict[int, dict[str, _OwRankSignals]] = {}
    if "ow" in enabled_sources:
        ow_week_window = timedelta(days=ow_lookback_days) if ow_lookback_days else OW_RANK_WEEK_WINDOW
        ow_signals_by_tag_id = await _load_ow_rank_signals_by_social_account_id(
            session,
            [account.id for account in battle_tags_by_key.values()],
            now,
            ow_week_window,
        )

    # Balancer history (division_history) and tournament-participation history (analytics) are
    # both candidates in the priority chain, keyed by user_id then registration role code.
    balancer_history_by_user_id: dict[int, dict[str, int]] = {}
    analytics_history_by_user_id: dict[int, dict[str, int]] = {}
    if tournament is not None and ({"division_history", "analytics"} & enabled_sources):
        user_ids = [
            battle_tag.user_id
            for battle_tag in battle_tags_by_key.values()
            if battle_tag.user_id is not None
        ]
        # Normalize historical ranks from each source tournament's grid version into this
        # tournament's grid. Best-effort: skip when the target version is unknown or the
        # normalizer cannot be built (loaders then fall back to raw ranks).
        normalizer = await _build_autofill_rank_normalizer(session, tournament)
        if "division_history" in enabled_sources:
            balancer_history_by_user_id = await _load_latest_ranks_from_balancer_history(
                session,
                user_ids,
                tournament_id,
                tournament.workspace_id,
                normalizer,
                grid,
                _autofill_lookback_cutoff(target_number, division_lookback),
            )
        if "analytics" in enabled_sources:
            analytics_history_by_user_id = await _load_latest_ranks_from_tournament_history(
                session,
                user_ids,
                tournament_id,
                tournament.workspace_id,
                normalizer,
                grid,
                _autofill_lookback_cutoff(target_number, analytics_lookback),
            )

    players: list[dict[str, Any]] = []
    applied_registrations = 0
    role_updates = 0
    balancer_additions = 0

    for registration in registrations:
        tag_key = registration.battle_tag_normalized or normalize_battle_tag_key(registration.battle_tag)
        main_battle_tag = battle_tags_by_key.get(tag_key or "")
        ow_signals_by_role = ow_signals_by_tag_id.get(main_battle_tag.id, {}) if main_battle_tag else {}
        user_id = getattr(main_battle_tag, "user_id", None) if main_battle_tag else None
        balancer_by_role = balancer_history_by_user_id.get(user_id or -1, {})
        analytics_by_role = analytics_history_by_user_id.get(user_id or -1, {})

        # Build one suggestion per rank-role via the selected priority chain, keyed the way the
        # plan builder expects. Balancer/analytics history are stored under registration-role codes
        # (tank/dps/support); OW snapshots use rank-role codes (tank/damage/support) — bridge via
        # the mapping.
        rank_data_by_role: dict[str, _RankData | Any] = {}
        for registration_role, rank_role in RANK_ROLE_BY_REGISTRATION_ROLE.items():
            resolved = _build_priority_rank_data(
                order,
                ow_signals_by_role.get(rank_role),
                balancer_by_role.get(registration_role),
                analytics_by_role.get(registration_role),
                grid,
            )
            if resolved is not None:
                rank_data_by_role[rank_role] = resolved

        row, updates = build_registration_rank_autofill_plan(
            registration,
            rank_data_by_role,
            battle_tag_linked=main_battle_tag is not None,
            overwrite_existing=overwrite_existing,
            allow_partial=allow_partial,
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
    unverified_registrations = sum(
        1 for row in players if any(role.get("action") == "unverified" for role in row["roles"])
    )

    return {
        "total_registrations": len(players),
        "updatable_registrations": updatable_registrations,
        "applied_registrations": applied_registrations,
        "skipped_registrations": skipped_registrations,
        "unchanged_registrations": unchanged_registrations,
        "unverified_registrations": unverified_registrations,
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

    # Manual (admin-created) registrations have no registering auth account, so
    # they are intentionally left with workspace_member_id=None — mirrors the
    # sheet-sync creation path below. Workspace is derived from
    # tournament_id -> Tournament.workspace_id when needed, not stored here.
    registration = models.BalancerRegistration(
        tournament_id=tournament_id,
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
            workspace_id=registration.tournament.workspace_id,
            scope="registration",
            value=status_value,
        )
        registration.status = status_value
    if balancer_status_value is not None:
        await validate_registration_status_value(
            session,
            workspace_id=registration.tournament.workspace_id,
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
        workspace_id=registration.tournament.workspace_id,
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
                # Sheet-sync-created registrations have no registering auth account,
                # so workspace_member_id is left None (mirrors create_manual_registration).
                registration = models.BalancerRegistration(
                    tournament_id=tournament_id,
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

            # Resolve/provision the domain player so sheet-imported registrations
            # carry user_id (mirrors create_registration). Without this, OW-rank
            # lookup — which joins by user_id — finds nothing and the balancer
            # rank-delta UI stays empty. Idempotent: respects an already-linked
            # user_id, so re-syncs and already-linked rows are untouched.
            await ensure_player_identity(session, registration)

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
    user_id = await social_identity.find_player_id_by_handle(
        session, provider=SocialProvider.BATTLENET, username=battle_tag
    )
    if user_id is None:
        return None
    return await session.get(models.User, user_id)


async def _ensure_user_battle_tag(session: AsyncSession, user: models.User, battle_tag: str) -> None:
    if "#" not in battle_tag:
        return
    await social_identity.upsert_social_account(
        session, user_id=user.id, provider=SocialProvider.BATTLENET, username=battle_tag
    )


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
    if registration.discord_nick:
        await social_identity.upsert_social_account(
            session, user_id=user.id, provider=SocialProvider.DISCORD, username=registration.discord_nick
        )
    if registration.twitch_nick:
        await social_identity.upsert_social_account(
            session, user_id=user.id, provider=SocialProvider.TWITCH, username=registration.twitch_nick
        )


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
