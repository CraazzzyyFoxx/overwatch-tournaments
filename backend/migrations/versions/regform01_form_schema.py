"""Registration form schema: versions, templates, identities.

Revision ID: regform01
Revises: achenc01
Create Date: 2026-09-21 00:00:00.000000

Replaces the two parallel field systems of the registration form --
``built_in_fields_json`` (a dict of hard-coded keys) and ``custom_fields_json``
(a thin list) -- with one ordered, sectioned ``FormSchema`` stored as an
append-only version snapshot, and moves the per-provider social columns into
``balancer.registration_identity``. See
``docs/registration-form-schema/design.md`` sections 4 and 8.

**Destructive by design.** This revision drops five columns:
``registration_form.built_in_fields_json``, ``registration_form.custom_fields_json``
and ``registration.{discord_nick,twitch_nick,boosty_nick}``. That is safe only
because every reader of those columns is migrated in the tasks that follow this
one (services, schemas, RPC, exports, frontend); the data itself is preserved --
the JSON pair becomes version #1 of each form and the nicks become identity
rows, and ``downgrade()`` reverses both.

**No ``shared`` import.** A revision has to run against a database whose code may
predate or postdate it, so the legacy -> schema converter lives here, inline
(the same rule ``roledps01`` and ``regteam0004`` follow). ``FormSchema`` is the
validator the produced documents must survive, and
``backend/tests/test_regform01_convert.py`` loads THIS module by path and proves
exactly that -- without the migration ever importing the model.

Conversion rules:

* Absent key in ``built_in_fields_json`` -> ``LEGACY_DEFAULT_ENABLED``.
* ``discord_nick/twitch_nick/boosty_nick`` -> ``identity_<provider>``,
  ``notes`` -> ``public_notes``; every field is ``visibility="public"`` (the
  legacy form had no private answers).
* ``primary_role/additional_roles/flex_role/top_heroes`` collapse into the one
  ``roles`` builtin's ``params``.
* A legacy ``validation.regex`` that does not compile, or that is longer than
  ``MAX_HANDLE_PATTERN_LENGTH``, is DROPPED rather than copied: ``FormSchema``
  refuses such a pattern at load time, so carrying it through would make the
  form's own version #1 unreadable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "regform01"
down_revision: str | Sequence[str] | None = "achenc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# Inline catalog (mirrors shared/domain/forms/builtins.py -- deliberately copied)
# ---------------------------------------------------------------------------

#: Whether a legacy builtin counted as present when its key was absent from
#: ``built_in_fields_json``. Matches the shipped form's effective behaviour, which
#: is what the backfill has to reproduce; the builder's ``defaultEnabled``
#: (frontend formConfig.ts) differs for ``smurf_tags``/``additional_roles``.
LEGACY_DEFAULT_ENABLED: dict[str, bool] = {
    "battle_tag": True,
    "smurf_tags": True,
    "discord_nick": True,
    "twitch_nick": True,
    "boosty_nick": False,
    "primary_role": True,
    "additional_roles": True,
    "flex_role": True,
    "top_heroes": False,
    "stream_pov": False,
    "notes": True,
}

#: ``accounts`` section, in today's wizard order: (legacy key, schema key).
ACCOUNT_FIELDS: tuple[tuple[str, str], ...] = (
    ("battle_tag", "battle_tag"),
    ("smurf_tags", "smurf_tags"),
    ("discord_nick", "identity_discord"),
    ("twitch_nick", "identity_twitch"),
    ("boosty_nick", "identity_boosty"),
)

#: ``details`` section, before the custom fields.
DETAIL_FIELDS: tuple[tuple[str, str], ...] = (
    ("stream_pov", "stream_pov"),
    ("notes", "public_notes"),
)

#: Builtins whose params model carries ``require_verified``.
VERIFIABLE_KEYS = frozenset({"battle_tag", "identity_discord", "identity_twitch", "identity_boosty"})

#: Legacy nick column -> ``registration_identity.provider``.
NICK_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("discord_nick", "discord"),
    ("twitch_nick", "twitch"),
    ("boosty_nick", "boosty"),
)

#: Google-sheet mapping target keys that move with the fields they name.
#: ``admin_notes`` is an organizer column, not a form field, and stays.
SHEET_TARGET_RENAMES: dict[str, str] = {
    "discord_nick": "identity_discord",
    "twitch_nick": "identity_twitch",
    "boosty_nick": "identity_boosty",
    "notes": "public_notes",
}
SHEET_TARGET_RESTORES: dict[str, str] = {new: old for old, new in SHEET_TARGET_RENAMES.items()}

#: ``shared.core.social.MAX_HANDLE_PATTERN_LENGTH``, copied (see module docstring).
MAX_HANDLE_PATTERN_LENGTH = 256

#: Custom field kinds the legacy list could express; anything else degrades to
#: ``text`` on downgrade.
LEGACY_CUSTOM_KINDS = frozenset({"text", "number", "select", "checkbox", "url"})

#: Every legacy builtin key, so ``schema_to_legacy`` can write an explicit
#: ``{"enabled": false}`` for the ones the schema no longer carries (absence
#: would otherwise mean "enabled" for most of them).
LEGACY_BUILTIN_KEYS: tuple[str, ...] = tuple(LEGACY_DEFAULT_ENABLED)


# ---------------------------------------------------------------------------
# Pure converters (covered by backend/tests/test_regform01_convert.py)
# ---------------------------------------------------------------------------


def _cell(row: Any, key: str) -> Any:
    """One value out of a mapping or a SQLAlchemy ``Row``."""
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _config(built_in: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = built_in.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _enabled(built_in: Mapping[str, Any], key: str) -> bool:
    value = built_in.get(key)
    if not isinstance(value, Mapping):
        return LEGACY_DEFAULT_ENABLED.get(key, False)
    # A saved config without an explicit flag is enabled (BuiltInFieldConfig default).
    return bool(value.get("enabled", True))


def _usable_regex(pattern: Any) -> bool:
    if not isinstance(pattern, str) or not pattern:
        return False
    if len(pattern) > MAX_HANDLE_PATTERN_LENGTH:
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _validation(raw: Any) -> dict[str, Any] | None:
    """Carry a legacy validation block over, minus a pattern ``FormSchema`` would refuse."""
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, Any] = {}
    if _usable_regex(raw.get("regex")):
        out["regex"] = raw["regex"]
    message = raw.get("error_message")
    if isinstance(message, str) and message:
        out["error_message"] = message
    return out or None


def _builtin_field(key: str, config: Mapping[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    field: dict[str, Any] = {
        "key": key,
        "kind": "builtin",
        "required": bool(config.get("required", False)),
        "visibility": "public",
    }
    validation = _validation(config.get("validation"))
    if validation is not None:
        field["validation"] = validation
    if params:
        field["params"] = params
    return field


def _merge_subroles(*sources: Any) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for role, slugs in source.items():
            if not isinstance(slugs, (list, tuple)):
                continue
            bucket = merged.setdefault(str(role), [])
            for slug in slugs:
                text = str(slug)
                if text and text not in bucket:
                    bucket.append(text)
    return merged


def _roles_params(built_in: Mapping[str, Any]) -> dict[str, Any]:
    primary = _config(built_in, "primary_role")
    additional = _config(built_in, "additional_roles")
    flex = _config(built_in, "flex_role")
    top = _config(built_in, "top_heroes")
    max_heroes = top.get("max_heroes")
    return {
        "primary_required": bool(primary.get("required", False)),
        "additional_required": bool(additional.get("required", False)),
        "flex_allowed": _enabled(built_in, "flex_role"),
        "flex_mode": str(flex.get("mode") or "optional"),
        "subroles": _merge_subroles(primary.get("subroles"), additional.get("subroles")),
        "top_heroes": {
            "enabled": _enabled(built_in, "top_heroes"),
            "required": bool(top.get("required", False)),
            # ``TopHeroesParams.max`` is bounded 1..20; a legacy value outside that
            # would make the version row unloadable, so it is clamped, not copied.
            "max": min(max(int(max_heroes), 1), 20) if isinstance(max_heroes, int) else 5,
        },
    }


def _custom_field(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    key = raw.get("key")
    if not isinstance(key, str) or not key:
        return None
    label = raw.get("label")
    field: dict[str, Any] = {
        "key": key,
        "kind": str(raw.get("type") or "text"),
        "label": label if isinstance(label, str) and label.strip() else key,
        "required": bool(raw.get("required", False)),
        "visibility": "public",
    }
    placeholder = raw.get("placeholder")
    if isinstance(placeholder, str) and placeholder:
        field["placeholder"] = placeholder
    options = raw.get("options")
    if isinstance(options, (list, tuple)) and options:
        field["options"] = [str(option) for option in options]
    validation = _validation(raw.get("validation"))
    if validation is not None:
        field["validation"] = validation
    show_in_draft = raw.get("show_in_draft")
    if show_in_draft is not None:
        field["show_in_draft"] = bool(show_in_draft)
    return field


def legacy_to_schema(built_in: dict, custom: list) -> dict:
    """``built_in_fields_json`` + ``custom_fields_json`` -> a ``FormSchema``-shaped dict."""
    built_in = built_in if isinstance(built_in, Mapping) else {}
    custom = custom if isinstance(custom, (list, tuple)) else []

    accounts: list[dict[str, Any]] = []
    for legacy_key, schema_key in ACCOUNT_FIELDS:
        if not _enabled(built_in, legacy_key):
            continue
        config = _config(built_in, legacy_key)
        params: dict[str, Any] = {}
        if schema_key in VERIFIABLE_KEYS and config.get("require_verified") is not None:
            params["require_verified"] = bool(config["require_verified"])
        accounts.append(_builtin_field(schema_key, config, params))

    roles: list[dict[str, Any]] = []
    if _enabled(built_in, "primary_role") or _enabled(built_in, "additional_roles"):
        roles.append(_builtin_field("roles", {}, _roles_params(built_in)))

    details: list[dict[str, Any]] = []
    for legacy_key, schema_key in DETAIL_FIELDS:
        if _enabled(built_in, legacy_key):
            details.append(_builtin_field(schema_key, _config(built_in, legacy_key)))
    for raw in custom:
        field = _custom_field(raw)
        if field is not None:
            details.append(field)

    sections = [
        {"key": key, "fields": fields}
        for key, fields in (("accounts", accounts), ("roles", roles), ("details", details))
        if fields
    ]
    # ``FormSchema.sections`` is ``min_length=1``: a form with everything switched
    # off still has to produce a document the application can load.
    if not sections:
        sections = [{"key": "accounts", "fields": []}]
    return {"schema_version": 1, "sections": sections}


def legacy_nicks(row) -> list[tuple[str, str, str]]:
    """``(provider, handle, handle_normalized)`` for every non-empty legacy nick."""
    out: list[tuple[str, str, str]] = []
    for column, provider in NICK_PROVIDERS:
        raw = _cell(row, column)
        if not isinstance(raw, str):
            continue
        handle = raw.strip()
        if not handle:
            continue
        out.append((provider, handle, handle.casefold()))
    return out


def _remap_targets(mapping: dict | None, renames: Mapping[str, str]) -> dict | None:
    if not isinstance(mapping, Mapping):
        return mapping
    targets = mapping.get("targets")
    if not isinstance(targets, Mapping):
        return dict(mapping)
    return {**mapping, "targets": {renames.get(key, key): value for key, value in targets.items()}}


def remap_sheet_targets(mapping: dict | None) -> dict | None:
    """Rename the mapping-config target keys that this revision renames."""
    return _remap_targets(mapping, SHEET_TARGET_RENAMES)


def unmap_sheet_targets(mapping: dict | None) -> dict | None:
    """Inverse of :func:`remap_sheet_targets`, for the downgrade."""
    return _remap_targets(mapping, SHEET_TARGET_RESTORES)


def schema_to_legacy(schema: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Best-effort inverse: a schema document -> ``(built_in_fields_json, custom_fields_json)``."""
    built_in: dict[str, Any] = {key: {"enabled": False} for key in LEGACY_BUILTIN_KEYS}
    custom: list[dict[str, Any]] = []
    if not isinstance(schema, Mapping):
        return built_in, custom

    schema_keys = {new: old for old, new in (*ACCOUNT_FIELDS, *DETAIL_FIELDS)}
    for section in schema.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        for field in section.get("fields") or []:
            if not isinstance(field, Mapping):
                continue
            key = field.get("key")
            kind = field.get("kind")
            if kind != "builtin":
                legacy_kind = str(kind or "text")
                entry: dict[str, Any] = {
                    "key": key,
                    "label": field.get("label") or key,
                    "type": legacy_kind if legacy_kind in LEGACY_CUSTOM_KINDS else "text",
                    "required": bool(field.get("required", False)),
                }
                for name in ("placeholder", "options", "validation"):
                    if field.get(name) is not None:
                        entry[name] = field[name]
                if field.get("show_in_draft") is not None:
                    entry["show_in_draft"] = bool(field["show_in_draft"])
                custom.append(entry)
                continue
            params = field.get("params") or {}
            if key == "roles":
                top = params.get("top_heroes") or {}
                built_in["primary_role"] = {
                    "enabled": True,
                    "required": bool(params.get("primary_required", False)),
                    "subroles": params.get("subroles") or {},
                }
                built_in["additional_roles"] = {
                    "enabled": True,
                    "required": bool(params.get("additional_required", False)),
                }
                built_in["flex_role"] = {
                    "enabled": bool(params.get("flex_allowed", True)),
                    "mode": params.get("flex_mode") or "optional",
                }
                built_in["top_heroes"] = {
                    "enabled": bool(top.get("enabled", False)),
                    "required": bool(top.get("required", False)),
                    "max_heroes": top.get("max", 5),
                }
                continue
            legacy_key = schema_keys.get(str(key))
            if legacy_key is None:
                # ``organizer_notes`` and any builtin added after this revision have
                # no legacy home; the schema itself is kept in the version table.
                continue
            entry = {"enabled": True, "required": bool(field.get("required", False))}
            if field.get("validation") is not None:
                entry["validation"] = field["validation"]
            if params.get("require_verified") is not None:
                entry["require_verified"] = bool(params["require_verified"])
            built_in[legacy_key] = entry
    return built_in, custom


# ---------------------------------------------------------------------------
# Schema changes
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "registration_form_version",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("form_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["balancer.registration_form.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("form_id", "number", name="uq_balancer_registration_form_version_number"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_registration_form_version_form_id"),
        "registration_form_version",
        ["form_id"],
        unique=False,
        schema="balancer",
    )

    op.create_table(
        "registration_form_template",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_registration_form_template_workspace_id"),
        "registration_form_template",
        ["workspace_id"],
        unique=False,
        schema="balancer",
    )
    # Case-insensitive name uniqueness per workspace: a functional index, which is
    # why it is an ``Index`` on the mapper rather than a ``UniqueConstraint``.
    op.create_index(
        "uq_balancer_registration_form_template_name",
        "registration_form_template",
        ["workspace_id", sa.text("lower(name)")],
        unique=True,
        schema="balancer",
    )

    op.create_table(
        "registration_identity",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registration_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=False),
        sa.Column("handle_normalized", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["registration_id"], ["balancer.registration.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_id", "provider", name="uq_balancer_registration_identity_provider"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_registration_identity_registration_id"),
        "registration_identity",
        ["registration_id"],
        unique=False,
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_registration_identity_handle",
        "registration_identity",
        ["provider", "handle_normalized"],
        unique=False,
        schema="balancer",
    )

    # Nullable on purpose: form and version point at each other and PostgreSQL
    # never defers a NOT NULL check (design section 4).
    op.add_column(
        "registration_form",
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_registration_form_current_version_id",
        "registration_form",
        "registration_form_version",
        ["current_version_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="balancer",
        ondelete="SET NULL",
    )
    op.add_column("registration", sa.Column("form_version_id", sa.BigInteger(), nullable=True), schema="balancer")
    op.create_foreign_key(
        "fk_registration_form_version_id",
        "registration",
        "registration_form_version",
        ["form_version_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="balancer",
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_balancer_registration_form_version_id"),
        "registration",
        ["form_version_id"],
        unique=False,
        schema="balancer",
    )
    op.add_column("registration", sa.Column("organizer_notes", sa.Text(), nullable=True), schema="balancer")
    op.alter_column("registration", "notes", new_column_name="public_notes", schema="balancer")

    # ── Backfill ─────────────────────────────────────────────────────────────
    bind = op.get_bind()
    forms = bind.execute(
        sa.text(
            "SELECT id, tournament_id, built_in_fields_json, custom_fields_json"
            " FROM balancer.registration_form ORDER BY id"
        )
    ).mappings()
    for form in forms.all():
        schema_json = legacy_to_schema(form["built_in_fields_json"] or {}, form["custom_fields_json"] or [])
        version_id = bind.execute(
            sa.text(
                "INSERT INTO balancer.registration_form_version (form_id, number, schema_json, created_at)"
                " VALUES (:form_id, 1, CAST(:schema_json AS json), now()) RETURNING id"
            ),
            {"form_id": form["id"], "schema_json": json.dumps(schema_json)},
        ).scalar_one()
        bind.execute(
            sa.text("UPDATE balancer.registration_form SET current_version_id = :version WHERE id = :form_id"),
            {"version": version_id, "form_id": form["id"]},
        )
        # Soft-deleted registrations included on purpose: the read path resolves a
        # row's schema through its own version, and a NULL there would send a
        # restored row down the "legacy row" fallback for no reason.
        bind.execute(
            sa.text("UPDATE balancer.registration SET form_version_id = :version WHERE tournament_id = :tournament"),
            {"version": version_id, "tournament": form["tournament_id"]},
        )

    registrations = bind.execute(
        sa.text(
            "SELECT id, discord_nick, twitch_nick, boosty_nick FROM balancer.registration"
            " WHERE discord_nick IS NOT NULL OR twitch_nick IS NOT NULL OR boosty_nick IS NOT NULL ORDER BY id"
        )
    ).mappings()
    insert_identity = sa.text(
        "INSERT INTO balancer.registration_identity"
        " (registration_id, provider, handle, handle_normalized, created_at)"
        " VALUES (:registration_id, :provider, :handle, :handle_normalized, now())"
        " ON CONFLICT (registration_id, provider) DO NOTHING"
    )
    for registration in registrations.all():
        for provider, handle, normalized in legacy_nicks(registration):
            bind.execute(
                insert_identity,
                {
                    "registration_id": registration["id"],
                    "provider": provider,
                    "handle": handle[:255],
                    "handle_normalized": normalized[:255],
                },
            )

    _rewrite_sheet_targets(bind, remap_sheet_targets)

    op.drop_column("registration_form", "built_in_fields_json", schema="balancer")
    op.drop_column("registration_form", "custom_fields_json", schema="balancer")
    op.drop_column("registration", "discord_nick", schema="balancer")
    op.drop_column("registration", "twitch_nick", schema="balancer")
    op.drop_column("registration", "boosty_nick", schema="balancer")


def _rewrite_sheet_targets(bind: Any, convert: Any) -> None:
    feeds = bind.execute(
        sa.text("SELECT id, mapping_config_json FROM balancer.registration_google_sheet_feed ORDER BY id")
    ).mappings()
    update = sa.text(
        "UPDATE balancer.registration_google_sheet_feed SET mapping_config_json = CAST(:mapping AS json)"
        " WHERE id = :feed_id"
    )
    for feed in feeds.all():
        current = feed["mapping_config_json"]
        converted = convert(current)
        if converted != current:
            bind.execute(update, {"mapping": json.dumps(converted), "feed_id": feed["id"]})


def downgrade() -> None:
    op.add_column(
        "registration_form",
        sa.Column("built_in_fields_json", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("custom_fields_json", sa.JSON(), server_default="[]", nullable=False),
        schema="balancer",
    )
    op.add_column("registration", sa.Column("discord_nick", sa.String(length=255), nullable=True), schema="balancer")
    op.add_column("registration", sa.Column("twitch_nick", sa.String(length=255), nullable=True), schema="balancer")
    op.add_column("registration", sa.Column("boosty_nick", sa.String(length=255), nullable=True), schema="balancer")

    bind = op.get_bind()
    for column, provider in NICK_PROVIDERS:
        bind.execute(
            sa.text(
                f"UPDATE balancer.registration AS r SET {column} = i.handle"  # noqa: S608 - column from a literal tuple
                " FROM balancer.registration_identity AS i"
                " WHERE i.registration_id = r.id AND i.provider = :provider"
            ),
            {"provider": provider},
        )

    op.alter_column("registration", "public_notes", new_column_name="notes", schema="balancer")

    forms = bind.execute(
        sa.text(
            "SELECT f.id AS form_id, v.schema_json AS schema_json FROM balancer.registration_form AS f"
            " LEFT JOIN balancer.registration_form_version AS v ON v.id = f.current_version_id ORDER BY f.id"
        )
    ).mappings()
    update_form = sa.text(
        "UPDATE balancer.registration_form SET built_in_fields_json = CAST(:built_in AS json),"
        " custom_fields_json = CAST(:custom AS json) WHERE id = :form_id"
    )
    for form in forms.all():
        built_in, custom = schema_to_legacy(form["schema_json"])
        bind.execute(
            update_form,
            {"built_in": json.dumps(built_in), "custom": json.dumps(custom), "form_id": form["form_id"]},
        )

    _rewrite_sheet_targets(bind, unmap_sheet_targets)

    op.drop_column("registration", "organizer_notes", schema="balancer")
    op.drop_index(op.f("ix_balancer_registration_form_version_id"), "registration", schema="balancer")
    op.drop_constraint("fk_registration_form_version_id", "registration", schema="balancer", type_="foreignkey")
    op.drop_column("registration", "form_version_id", schema="balancer")
    op.drop_constraint(
        "fk_registration_form_current_version_id",
        "registration_form",
        schema="balancer",
        type_="foreignkey",
    )
    op.drop_column("registration_form", "current_version_id", schema="balancer")

    op.drop_table("registration_identity", schema="balancer")
    op.drop_table("registration_form_template", schema="balancer")
    op.drop_table("registration_form_version", schema="balancer")
