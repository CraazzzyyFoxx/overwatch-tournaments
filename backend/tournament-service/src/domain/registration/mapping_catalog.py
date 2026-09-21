"""Catalog and validation for the Google Sheets → registration mapping engine.

This module is the single source of truth for:

* the set of mappable **targets** (internal registration fields), including the
  tournament's dynamic custom fields, exposed to the frontend mapper;
* the catalog of available **parsers**;
* **validation** of a saved ``mapping_config_json`` against the live sheet headers;
* row **disposition** classification (create / update / skip) used by the preview;
* type-aware coercion of sheet values into **custom fields**.

It is intentionally pure: no FastAPI, no SQLAlchemy, no network. Everything here
is unit-testable without a database, mirroring the existing registration tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from shared.core.social import SocialProvider
from shared.domain.forms import IDENTITY_PROVIDERS, FormField, FormSchema, identity_key
from shared.domain.player_sub_roles import catalog_slugs, normalize_sub_role
from src.domain.registration.utils import (
    normalize_header,
    parse_boolean_value,
    parse_integer,
)

ROLE_CODES = ("tank", "damage", "support")

#: Targets that are FORM ANSWERS: they reach the registration through the
#: answer pipeline instead of straight onto a column. Everything else a sheet
#: can map -- ``display_name``, ``admin_notes``, ``submitted_at`` and the
#: role/rank targets -- is organizer state the form never asks a player about.
ANSWER_TARGET_KEYS: tuple[str, ...] = (
    "battle_tag",
    "smurf_tags",
    *(identity_key(provider) for provider in IDENTITY_PROVIDERS),
    "stream_pov",
    "public_notes",
    "organizer_notes",
)

#: Label and header aliases for each identity provider the form can ask about.
#: Data, not branches: a new provider in ``IDENTITY_PROVIDERS`` only needs a row
#: here to become mappable (and is mappable without one, minus the suggester).
_IDENTITY_HEADERS: dict[str, tuple[str, tuple[str, ...]]] = {
    SocialProvider.DISCORD: ("Discord", ("discord", "дискорд", "дискор")),
    SocialProvider.TWITCH: ("Twitch", ("twitch", "твич")),
    SocialProvider.BOOSTY: ("Boosty", ("boosty", "бусти")),
    SocialProvider.VK: ("VK", ("vk", "вконтакте")),
    SocialProvider.YOUTUBE: ("YouTube", ("youtube", "ютуб")),
}

# Parser identifiers understood by ``parse_target_value`` in admin.py.
PARSER_STRING = "string"
PARSER_BATTLE_TAG = "battle_tag"
PARSER_BATTLE_TAG_LIST = "battle_tag_list"
PARSER_BOOLEAN = "boolean"
PARSER_INTEGER = "integer"
PARSER_DATETIME = "datetime"
PARSER_ROLE_TOKEN = "role_token"
PARSER_ROLE_TOKEN_LIST = "role_token_list"
PARSER_SUBROLE_TOKEN = "subrole_token"
PARSER_DIVISION_TO_RANK = "division_to_rank"
PARSER_JOIN_LINES = "join_lines"
PARSER_ROLE_SUBROLE_TOKEN = "role_subrole_token"
PARSER_SR_VALUE = "sr_value"

VALID_MODES = ("columns", "disabled", "constant", "auto")


@dataclass(frozen=True)
class ParserSpec:
    """Describes one value parser for the frontend catalog."""

    parser: str
    label: str
    cardinality: str  # "single" | "multi"
    produces: str  # "string" | "int" | "bool" | "datetime" | "list" | "role" | "subrole"


PARSER_CATALOG: tuple[ParserSpec, ...] = (
    ParserSpec(PARSER_STRING, "Text", "single", "string"),
    ParserSpec(PARSER_BATTLE_TAG, "Battle tag", "single", "string"),
    ParserSpec(PARSER_BATTLE_TAG_LIST, "Battle tag list", "multi", "list"),
    ParserSpec(PARSER_BOOLEAN, "Yes / No", "single", "bool"),
    ParserSpec(PARSER_INTEGER, "Number", "single", "int"),
    ParserSpec(PARSER_DATETIME, "Date / time", "single", "datetime"),
    ParserSpec(PARSER_ROLE_TOKEN, "Role", "single", "role"),
    ParserSpec(PARSER_SUBROLE_TOKEN, "Sub-role", "single", "subrole"),
    ParserSpec(PARSER_DIVISION_TO_RANK, "Division → rank", "single", "int"),
    ParserSpec(PARSER_JOIN_LINES, "Joined text", "multi", "string"),
    ParserSpec(PARSER_ROLE_SUBROLE_TOKEN, "Role + sub-role token", "single", "role_subrole"),
    ParserSpec(PARSER_SR_VALUE, "SR / rank text", "single", "int"),
)

VALID_PARSERS = frozenset(spec.parser for spec in PARSER_CATALOG) | {PARSER_ROLE_TOKEN_LIST}


@dataclass(frozen=True)
class MappingTargetSpec:
    """One mappable internal field.

    ``key`` is the dotted target key used in ``mapping_config_json["targets"]``.
    ``aliases`` are language-agnostic, lowercased header substrings used by the
    auto-suggester — they are *data*, not hardcoded branches, so new languages
    are added by extending this list.
    """

    key: str
    label: str
    group: str  # "identity" | "profile" | "roles" | "custom_fields"
    accepted_parsers: tuple[str, ...]
    default_parser: str
    default_mode: str = "disabled"
    default_is_list: bool = False
    multi_column: bool = False
    required: bool = False
    aliases: tuple[str, ...] = ()


def _role_label(role_code: str) -> str:
    return {"tank": "Tank", "damage": "Damage", "support": "Support"}[role_code]


def _identity_specs() -> list[MappingTargetSpec]:
    """One mappable target per identity provider the form can ask about."""
    specs: list[MappingTargetSpec] = []
    for provider in IDENTITY_PROVIDERS:
        label, aliases = _IDENTITY_HEADERS.get(provider, (provider.title(), ()))
        specs.append(
            MappingTargetSpec(
                key=identity_key(provider),
                label=label,
                group="profile",
                accepted_parsers=(PARSER_STRING,),
                default_parser=PARSER_STRING,
                aliases=aliases,
            )
        )
    return specs


def _build_builtin_specs() -> tuple[MappingTargetSpec, ...]:
    specs: list[MappingTargetSpec] = [
        MappingTargetSpec(
            key="source_record_key",
            label="Record key (dedup)",
            group="identity",
            accepted_parsers=(PARSER_BATTLE_TAG, PARSER_STRING),
            default_parser=PARSER_BATTLE_TAG,
            aliases=("battle tag", "battletag", "ваш battle tag"),
        ),
        MappingTargetSpec(
            key="battle_tag",
            label="Battle tag",
            group="identity",
            accepted_parsers=(PARSER_BATTLE_TAG, PARSER_STRING),
            default_parser=PARSER_BATTLE_TAG,
            required=True,
            aliases=("battle tag", "battletag", "ваш battle tag"),
        ),
        MappingTargetSpec(
            key="display_name",
            label="Display name",
            group="profile",
            accepted_parsers=(PARSER_STRING, PARSER_BATTLE_TAG),
            default_parser=PARSER_STRING,
            aliases=("display name", "nickname", "имя", "ник"),
        ),
        MappingTargetSpec(
            key="submitted_at",
            label="Submitted at",
            group="profile",
            accepted_parsers=(PARSER_DATETIME,),
            default_parser=PARSER_DATETIME,
            aliases=("timestamp", "submitted", "отметка времени"),
        ),
        MappingTargetSpec(
            key="smurf_tags",
            label="Smurf accounts",
            group="profile",
            accepted_parsers=(PARSER_BATTLE_TAG_LIST,),
            default_parser=PARSER_BATTLE_TAG_LIST,
            multi_column=True,
            aliases=("smurf", "alt", "смурф"),
        ),
        *_identity_specs(),
        MappingTargetSpec(
            key="stream_pov",
            label="Stream POV",
            group="profile",
            accepted_parsers=(PARSER_BOOLEAN,),
            default_parser=PARSER_BOOLEAN,
            aliases=("stream", "pov", "стрим"),
        ),
        MappingTargetSpec(
            key="public_notes",
            label="Notes",
            group="profile",
            accepted_parsers=(PARSER_JOIN_LINES, PARSER_STRING),
            default_parser=PARSER_JOIN_LINES,
            multi_column=True,
            aliases=("note", "comment", "примеч", "любая доп."),
        ),
        MappingTargetSpec(
            # Deliberately alias-free: an organizers-only answer must be mapped
            # on purpose, never guessed off a header a player filled in.
            key="organizer_notes",
            label="Organizer notes",
            group="profile",
            accepted_parsers=(PARSER_JOIN_LINES, PARSER_STRING),
            default_parser=PARSER_JOIN_LINES,
            multi_column=True,
        ),
        MappingTargetSpec(
            key="is_flex",
            label="Full flex",
            group="roles",
            accepted_parsers=(PARSER_BOOLEAN,),
            default_parser=PARSER_BOOLEAN,
            aliases=("flex", "флекс"),
        ),
        MappingTargetSpec(
            key="admin_notes",
            label="Admin notes",
            group="profile",
            accepted_parsers=(PARSER_JOIN_LINES, PARSER_STRING),
            default_parser=PARSER_JOIN_LINES,
            multi_column=True,
            aliases=("admin note", "админ"),
        ),
        MappingTargetSpec(
            key="source_roles.primary",
            label="Primary role",
            group="roles",
            accepted_parsers=(PARSER_ROLE_TOKEN, PARSER_ROLE_SUBROLE_TOKEN),
            default_parser=PARSER_ROLE_TOKEN,
            aliases=("your role", "primary role", "main role", "укажите вашу роль"),
        ),
        MappingTargetSpec(
            key="source_roles.additional",
            label="Additional roles",
            group="roles",
            accepted_parsers=(PARSER_ROLE_TOKEN, PARSER_ROLE_SUBROLE_TOKEN, PARSER_ROLE_TOKEN_LIST),
            default_parser=PARSER_ROLE_TOKEN,
            default_is_list=True,
            multi_column=True,
            aliases=("additional role", "secondary role", "дополнительная игровая роль"),
        ),
    ]

    for role_code in ROLE_CODES:
        label = _role_label(role_code)
        specs.append(
            MappingTargetSpec(
                key=f"roles.{role_code}.rank_value",
                label=f"{label} rank (SR)",
                group="roles",
                accepted_parsers=(PARSER_INTEGER, PARSER_DIVISION_TO_RANK, PARSER_SR_VALUE),
                default_parser=PARSER_INTEGER,
            )
        )
        specs.append(
            MappingTargetSpec(
                key=f"roles.{role_code}.division_input",
                label=f"{label} division",
                group="roles",
                accepted_parsers=(PARSER_DIVISION_TO_RANK, PARSER_INTEGER),
                default_parser=PARSER_DIVISION_TO_RANK,
            )
        )
        specs.append(
            MappingTargetSpec(
                key=f"roles.{role_code}.is_active",
                label=f"{label} active",
                group="roles",
                accepted_parsers=(PARSER_BOOLEAN,),
                default_parser=PARSER_BOOLEAN,
                default_mode="auto",
            )
        )
        specs.append(
            MappingTargetSpec(
                key=f"roles.{role_code}.priority",
                label=f"{label} priority",
                group="roles",
                accepted_parsers=(PARSER_INTEGER,),
                default_parser=PARSER_INTEGER,
            )
        )
        if role_code != "tank":
            specs.append(
                MappingTargetSpec(
                    key=f"roles.{role_code}.subrole",
                    label=f"{label} sub-role",
                    group="roles",
                    accepted_parsers=(PARSER_SUBROLE_TOKEN,),
                    default_parser=PARSER_SUBROLE_TOKEN,
                )
            )

    return tuple(specs)


#: Every builtin target the engine knows HOW to parse. Not what a given
#: tournament may bind: see :func:`builtin_target_specs`.
_ALL_BUILTIN_SPECS: tuple[MappingTargetSpec, ...] = _build_builtin_specs()

_CUSTOM_FIELD_PARSER_BY_TYPE: dict[str, str] = {
    "text": PARSER_STRING,
    "url": PARSER_STRING,
    "number": PARSER_INTEGER,
    "checkbox": PARSER_BOOLEAN,
    "select": PARSER_STRING,
}


def custom_field_target_key(field_key: str) -> str:
    return f"custom_fields.{field_key}"


def custom_field_target_specs(
    custom_fields: list[FormField] | None,
) -> tuple[MappingTargetSpec, ...]:
    """Build a mapping target spec for each dynamic custom field on the form.

    ``role_ranks`` is skipped: its answer is one number per role, and a sheet
    column is one cell -- there is no shape to map onto it, so offering the
    target would only let an organizer store a string where a dict belongs.
    """
    specs: list[MappingTargetSpec] = []
    for definition in custom_fields or []:
        if definition.kind == "role_ranks":
            continue
        parser = _CUSTOM_FIELD_PARSER_BY_TYPE.get(definition.kind, PARSER_STRING)
        specs.append(
            MappingTargetSpec(
                key=custom_field_target_key(definition.key),
                label=definition.label or definition.key,
                group="custom_fields",
                accepted_parsers=(parser,),
                default_parser=parser,
                required=definition.required,
                aliases=tuple(a for a in (definition.label, definition.key) if a),
            )
        )
    return tuple(specs)


def schema_custom_fields(schema: FormSchema | None) -> list[FormField]:
    """The organizer-defined (non-builtin) questions of a schema."""
    return [field_def for field_def in schema.fields() if not field_def.is_builtin] if schema is not None else []


def builtin_target_specs(schema: FormSchema | None) -> tuple[MappingTargetSpec, ...]:
    """The builtin targets THIS form can receive, in catalog order.

    An answer target (:data:`ANSWER_TARGET_KEYS`) is offered only when the
    schema declares that question, exactly as a custom-field target exists only
    while its question does. Otherwise binding a column to, say,
    ``identity_boosty`` on a form that never asks for Boosty would pass
    :func:`validate_mapping_config` -- the key is a permanent member of the
    catalog -- and then be dropped by every sync with nothing said anywhere.

    Everything else stays unconditional: ``source_record_key``,
    ``display_name``, ``submitted_at``, ``admin_notes`` and the role/rank
    targets are organizer state, which no form asks about and the answer
    pipeline never touches.
    """
    declared = {field_def.key for field_def in schema.fields()} if schema is not None else set()
    return tuple(spec for spec in _ALL_BUILTIN_SPECS if spec.key not in ANSWER_TARGET_KEYS or spec.key in declared)


def build_target_specs(schema: FormSchema | None = None) -> tuple[MappingTargetSpec, ...]:
    """Every target this form can bind: its builtins plus its custom questions."""
    return builtin_target_specs(schema) + custom_field_target_specs(schema_custom_fields(schema))


def target_spec_map(schema: FormSchema | None = None) -> dict[str, MappingTargetSpec]:
    return {spec.key: spec for spec in build_target_specs(schema)}


# ---------------------------------------------------------------------------
# Custom-field value coercion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoercionResult:
    """Outcome of coercing a single sheet cell into a custom-field value.

    ``error`` blocks nothing on its own — callers decide. ``warning`` is for
    soft mismatches (e.g. a value outside a select's options) that should not
    block a sync.
    """

    value: Any
    error: str | None = None
    warning: str | None = None


def _compile_regex(pattern: str | None) -> re.Pattern[str] | None:
    if not pattern:
        return None
    normalized = pattern.strip()
    if not normalized:
        return None
    try:
        return re.compile(normalized)
    except re.error:
        return None


def coerce_custom_field_value(
    field_def: FormField,
    raw: str | None,
    *,
    value_mapping: dict[str, Any] | None = None,
) -> CoercionResult:
    """Coerce a raw sheet value into the typed value a custom field expects."""
    text = (raw or "").strip()
    if not text:
        return CoercionResult(value=None)

    if field_def.kind == "number":
        parsed = parse_integer(text)
        if parsed is None:
            return CoercionResult(value=None, error=f"'{text}' is not a valid number")
        return CoercionResult(value=parsed)

    if field_def.kind == "checkbox":
        custom_booleans = {
            normalize_header(key): bool(mapped) for key, mapped in ((value_mapping or {}).get("booleans") or {}).items()
        }
        normalized = normalize_header(text)
        value = custom_booleans.get(normalized, parse_boolean_value(text))
        return CoercionResult(value=value)

    if field_def.kind == "select":
        if field_def.options and text not in field_def.options:
            return CoercionResult(value=text, warning=f"'{text}' is not one of the configured options")
        return CoercionResult(value=text)

    # text / url
    pattern = _compile_regex(field_def.validation.regex if field_def.validation else None)
    if pattern is not None and pattern.fullmatch(text) is None:
        message = (
            field_def.validation.error_message
            if field_def.validation and field_def.validation.error_message
            else f"'{text}' does not match the expected format"
        )
        return CoercionResult(value=text, warning=message)
    return CoercionResult(value=text)


# ---------------------------------------------------------------------------
# Mapping validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingValidationIssue:
    code: str
    message: str
    target: str | None = None
    column: str | None = None


IDENTITY_TARGETS = ("source_record_key", "battle_tag")


def _target_is_mapped(target_config: dict[str, Any] | None) -> bool:
    if not target_config:
        return False
    mode = target_config.get("mode")
    if mode == "columns":
        return bool(target_config.get("columns"))
    if mode == "constant":
        return target_config.get("value") not in (None, "")
    return False


def validate_mapping_config(
    mapping_config: dict[str, Any] | None,
    *,
    target_specs: dict[str, MappingTargetSpec],
    header_keys: list[str] | None,
    valid_parsers: frozenset[str] = VALID_PARSERS,
    subrole_catalog: dict[str, list[dict[str, str]]] | None = None,
) -> list[MappingValidationIssue]:
    """Validate a ``mapping_config_json`` payload.

    ``header_keys=None`` means the live headers are unknown (feed never synced
    and no URL supplied): column-existence checks are skipped, but mode/parser/
    constant/identity rules are still enforced.
    """
    issues: list[MappingValidationIssue] = []
    targets = (mapping_config or {}).get("targets")
    if not isinstance(targets, dict):
        return [
            MappingValidationIssue(
                code="missing_targets",
                message="Mapping must contain a 'targets' object.",
            )
        ]

    header_set = set(header_keys) if header_keys is not None else None

    for target_key, raw_config in targets.items():
        spec = target_specs.get(target_key)
        if spec is None:
            issues.append(
                MappingValidationIssue(
                    code="unknown_target",
                    message=f"Unknown target '{target_key}'.",
                    target=target_key,
                )
            )
            continue
        if not isinstance(raw_config, dict):
            issues.append(
                MappingValidationIssue(
                    code="invalid_target",
                    message=f"Target '{target_key}' must be an object.",
                    target=target_key,
                )
            )
            continue

        mode = raw_config.get("mode")
        if mode is not None and mode not in VALID_MODES:
            issues.append(
                MappingValidationIssue(
                    code="invalid_mode",
                    message=f"Invalid mode '{mode}' for '{target_key}'.",
                    target=target_key,
                )
            )

        parser = raw_config.get("parser")
        if parser is not None:
            if parser not in valid_parsers:
                issues.append(
                    MappingValidationIssue(
                        code="unknown_parser",
                        message=f"Unknown parser '{parser}'.",
                        target=target_key,
                    )
                )
            elif parser not in spec.accepted_parsers:
                issues.append(
                    MappingValidationIssue(
                        code="invalid_parser_for_target",
                        message=f"Parser '{parser}' is not allowed for '{spec.label}'.",
                        target=target_key,
                    )
                )

        if mode == "columns":
            columns = raw_config.get("columns") or []
            if not columns:
                issues.append(
                    MappingValidationIssue(
                        code="missing_columns",
                        message=f"'{spec.label}' is set to map columns but none are selected.",
                        target=target_key,
                    )
                )
            if not spec.multi_column and len(columns) > 1:
                issues.append(
                    MappingValidationIssue(
                        code="too_many_columns",
                        message=f"'{spec.label}' accepts a single column.",
                        target=target_key,
                    )
                )
            if header_set is not None:
                for column in columns:
                    if column not in header_set:
                        issues.append(
                            MappingValidationIssue(
                                code="unknown_column",
                                message=f"Column '{column}' is not present in the sheet.",
                                target=target_key,
                                column=column,
                            )
                        )
        elif mode == "constant":
            if raw_config.get("value") in (None, ""):
                issues.append(
                    MappingValidationIssue(
                        code="missing_constant_value",
                        message=f"'{spec.label}' is set to a constant but no value was provided.",
                        target=target_key,
                    )
                )
            elif spec.default_parser == PARSER_SUBROLE_TOKEN and subrole_catalog is not None:
                parts = spec.key.split(".")
                role = parts[1] if len(parts) >= 3 and parts[0] == "roles" else None
                slug = normalize_sub_role(str(raw_config.get("value")))
                allowed = catalog_slugs(subrole_catalog, role)
                if slug and allowed is not None and slug not in allowed:
                    issues.append(
                        MappingValidationIssue(
                            code="unknown_subrole",
                            message=f"'{slug}' is not a workspace sub-role" + (f" for {role}" if role else "") + ".",
                            target=target_key,
                        )
                    )

    if not any(_target_is_mapped(targets.get(key)) for key in IDENTITY_TARGETS):
        issues.append(
            MappingValidationIssue(
                code="missing_identity_target",
                message="Map either 'Battle tag' or 'Record key' so rows can be matched.",
            )
        )

    return issues


def validate_value_mapping_subroles(
    value_mapping: dict[str, Any] | None,
    subrole_catalog: dict[str, list[dict[str, str]]] | None,
) -> list[MappingValidationIssue]:
    """Reject value-map entries whose mapped slug is not in the workspace catalog."""
    if subrole_catalog is None or not value_mapping:
        return []
    issues: list[MappingValidationIssue] = []
    all_slugs = catalog_slugs(subrole_catalog)
    for sheet_key, raw in (value_mapping.get("subroles") or {}).items():
        slug = normalize_sub_role(str(raw) if raw is not None else None)
        if slug and all_slugs is not None and slug not in all_slugs:
            issues.append(
                MappingValidationIssue(
                    code="unknown_subrole",
                    message=f"Mapped sub-role '{slug}' is not in the workspace catalog.",
                    column=str(sheet_key),
                )
            )
    for sheet_key, raw in (value_mapping.get("role_subroles") or {}).items():
        entries = raw if isinstance(raw, list) else [raw]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            slug = normalize_sub_role(entry.get("subrole") if isinstance(entry.get("subrole"), str) else None)
            if not slug:
                continue
            if role == "flex":
                issues.append(
                    MappingValidationIssue(
                        code="unknown_subrole",
                        message="Flex cannot carry a sub-role.",
                        column=str(sheet_key),
                    )
                )
                continue
            allowed = catalog_slugs(subrole_catalog, role if isinstance(role, str) else None)
            if allowed is not None and slug not in allowed:
                issues.append(
                    MappingValidationIssue(
                        code="unknown_subrole",
                        message=f"Mapped sub-role '{slug}' is not in the workspace catalog"
                        + (f" for {role}" if role else "")
                        + ".",
                        column=str(sheet_key),
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# Row disposition (used by the preview)
# ---------------------------------------------------------------------------


def classify_row_disposition(
    source_record_key: str | None,
    battle_tag_key: str | None,
    *,
    known_source_keys: set[str],
    known_battle_tag_keys: set[str],
) -> str:
    """Return 'create' | 'update' | 'skip' for a parsed row.

    Mirrors the reuse logic in ``sync_google_sheet_feed``: a row updates an
    existing registration when its source key has a binding, or its battle tag
    matches an existing registration; otherwise it creates a new one. Rows that
    produced no identity are skipped.
    """
    if not source_record_key:
        return "skip"
    if source_record_key in known_source_keys:
        return "update"
    if battle_tag_key and battle_tag_key in known_battle_tag_keys:
        return "update"
    return "create"


@dataclass
class ParsedRowResult:
    """Detailed result of parsing one sheet row (used by preview & sync)."""

    fields: dict[str, Any] | None
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
