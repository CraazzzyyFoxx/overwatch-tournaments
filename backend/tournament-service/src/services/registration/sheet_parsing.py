"""Google-Sheets row parsing for the registration mapping engine.

Pure (no DB, no network) transformation of raw sheet rows into structured
registration payloads: token/value parsers, mapping suggestion from headers,
the per-row detailed parser and the role-payload builder. The feed CRUD and
the sync orchestration live in ``sheet_sync``; everything here is re-exported
by the ``admin`` facade.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from shared.division_grid import DivisionGrid
from shared.domain.player_sub_roles import normalize_sub_role

from src.schemas.registration import CustomFieldDefinition
from src.services.registration._common import BATTLE_TAG_RE
from src.services.registration.mapping_catalog import (
    ParsedRowResult,
    build_target_specs,
    coerce_custom_field_value,
    custom_field_target_key,
    target_spec_map,
)
from src.services.registration.utils import (
    DEFAULT_BOOLEAN_TRUE_VALUES,
    ROLE_ORDER,
    VALID_ROLES,
    RoleSubroleEntry,
    build_header_keys,
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
