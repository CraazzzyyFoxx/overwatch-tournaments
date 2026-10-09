"""Battle.net becomes an ordinary multi-handle registration identity.

Revision ID: regident01
Revises: wsprof01
Create Date: 2026-10-09 00:00:00.000000

``balancer.registration.battle_tag`` / ``battle_tag_normalized`` /
``smurf_tags_json`` stop being the one special-cased account of a registration:
every handle a registrant gives now lives in ``balancer.registration_identity``,
Battle.net included, and a provider may hold SEVERAL of them (``position`` 0 is
the primary, smurfs follow in the order they were given). The two builtin form
fields ``battle_tag`` and ``smurf_tags`` collapse into one builtin
``identity_battlenet`` whose answer is a list.

**Not destructive.** The three legacy columns and the
``uq_balancer_registration_tournament_tag_active`` index stay (CONTRIBUTING.md:73
gates destructive migrations); the code stops reading and writing them, and the
ORM keeps them as deferred legacy attributes. This revision only COPIES them
into identity rows. The drop is a later, separately gated release.

**No ``shared`` import.** A revision runs against a database whose code may
predate or postdate it, so the converters live here, inline -- the same rule
``regform01`` (this revision's precedent for rewriting stored form schemas and
sheet mappings) follows. ``backend/tests/test_regident01_convert.py`` loads THIS
module by path and feeds the output through the real ``FormSchema`` validator.

Conversion rules:

* ``battle_tag`` -> ``identity_battlenet`` IN PLACE (same section, same
  position), keeping ``label``, ``required``, ``editable``, ``visible_when`` and
  ``validation``; ``params`` becomes ``{"require_verified": <old>, "max_count":
  5 if the schema also asked ``smurf_tags`` else 1}``. ``visibility`` is forced
  to ``public``: ``identity_battlenet`` is the roster's public face and
  ``FormSchema`` refuses any other value for it.
* ``smurf_tags`` is dropped (it IS the extra handles now). A schema that asked
  for smurfs WITHOUT a ``battle_tag`` field converts the smurf field itself, so
  the question is not silently lost.
* ``visible_when.field`` of ``battle_tag``/``smurf_tags`` -> ``identity_battlenet``.
* ``require_verified`` on an identity field of a provider that cannot be
  verified (anything but battlenet/discord/twitch -- boosty/vk/youtube) is
  dropped: the flag has no meaning there any more and the builder no longer
  offers it. One-way; ``downgrade()`` does not put it back, because it was a
  no-op flag either way.
* Sheet mapping targets ``battle_tag`` + ``smurf_tags`` -> one
  ``identity_battlenet`` target (parser ``battle_tag_list``, main column first,
  then the smurf columns). ``source_record_key`` keeps naming the column it
  already named; when a mapping relied on the implicit "no source_record_key ->
  fall back to the battle_tag value" rule, it is pinned to that same column
  explicitly, because the fallback key disappears with the target.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "regident01"
down_revision: str | Sequence[str] | None = "wsprof01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# Inline catalog (mirrors shared/core/social.py + shared/domain/forms/builtins.py)
# ---------------------------------------------------------------------------

BATTLENET = "battlenet"
IDENTITY_KEY_PREFIX = "identity_"
BATTLE_TAG_KEY = "battle_tag"
SMURF_TAGS_KEY = "smurf_tags"
IDENTITY_BATTLENET_KEY = IDENTITY_KEY_PREFIX + BATTLENET

#: ``shared.core.social.VERIFIABLE_PROVIDERS`` (``ProviderSpec.can_be_verified``).
VERIFIABLE_PROVIDERS = frozenset({BATTLENET, "discord", "twitch"})

#: ``ProviderSpec.default_max_count`` for Battle.net -- what a form that asked
#: for smurfs converts to. Without a smurf question one handle is all it asked.
BATTLENET_MAX_COUNT = 5

#: ``builtins.MAX_IDENTITY_COUNT``: the ceiling on handles per identity field,
#: and therefore on the rows one registration gets per provider.
MAX_IDENTITY_COUNT = 10

#: ``shared.core.social._BATTLE_TAG_HASH``.
_BATTLE_TAG_HASH = re.compile(r"\s*#\s*")

#: Keys whose ``visible_when`` references move to the merged identity field.
CONDITION_RENAMES = {BATTLE_TAG_KEY: IDENTITY_BATTLENET_KEY, SMURF_TAGS_KEY: IDENTITY_BATTLENET_KEY}
CONDITION_RESTORES = {IDENTITY_BATTLENET_KEY: BATTLE_TAG_KEY}

#: Field attributes a builtin may not carry (``FormSchema`` refuses them).
_BUILTIN_FORBIDDEN = ("options",)


# ---------------------------------------------------------------------------
# Pure converters (covered by backend/tests/test_regident01_convert.py)
# ---------------------------------------------------------------------------


def normalize_battle_tag_handle(raw: Any) -> tuple[str, str] | None:
    """``(handle, handle_normalized)`` for one raw BattleTag, or None if blank.

    Mirrors ``display_social_handle``/``normalize_social_handle`` for the
    ``battletag`` normalize rule: the spacing a human types around ``#`` is
    collapsed for display, and the matching key additionally loses every
    remaining space and is casefolded.
    """
    if not isinstance(raw, str):
        return None
    handle = _BATTLE_TAG_HASH.sub("#", raw.strip())
    normalized = handle.replace(" ", "").strip().casefold()
    if not handle or not normalized:
        return None
    return handle[:255], normalized[:255]


def battlenet_handles(battle_tag: Any, smurf_tags: Any) -> list[tuple[str, str]]:
    """Every Battle.net handle of one registration, primary first.

    Blanks and handles repeating an earlier one (by normalized form) are
    dropped, and the list is capped at ``MAX_IDENTITY_COUNT`` -- a form cannot
    ask for more, so neither can the data it produced.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    raw_values: list[Any] = [battle_tag]
    if isinstance(smurf_tags, (list, tuple)):
        raw_values.extend(smurf_tags)
    for raw in raw_values:
        pair = normalize_battle_tag_handle(raw)
        if pair is None or pair[1] in seen:
            continue
        seen.add(pair[1])
        out.append(pair)
        if len(out) == MAX_IDENTITY_COUNT:
            break
    return out


def _fields_of(schema: Any) -> list[Mapping[str, Any]]:
    sections = schema.get("sections") if isinstance(schema, Mapping) else None
    if not isinstance(sections, (list, tuple)):
        return []
    return [
        field
        for section in sections
        if isinstance(section, Mapping) and isinstance(section.get("fields"), (list, tuple))
        for field in section["fields"]
        if isinstance(field, Mapping)
    ]


def _params(field: Mapping[str, Any]) -> dict[str, Any]:
    params = field.get("params")
    return dict(params) if isinstance(params, Mapping) else {}


def _rename_condition(field: dict[str, Any], renames: Mapping[str, str]) -> dict[str, Any]:
    condition = field.get("visible_when")
    if isinstance(condition, Mapping) and condition.get("field") in renames:
        field["visible_when"] = {**condition, "field": renames[condition["field"]]}
    return field


def _identity_field(field: Mapping[str, Any], *, max_count: int) -> dict[str, Any]:
    out = dict(field)
    for key in _BUILTIN_FORBIDDEN:
        out.pop(key, None)
    out["key"] = IDENTITY_BATTLENET_KEY
    out["kind"] = "builtin"
    # ``builtin_spec`` pins this one to public; any other value is refused.
    out["visibility"] = "public"
    out["params"] = {"require_verified": bool(_params(field).get("require_verified")), "max_count": max_count}
    return out


def _strip_dead_require_verified(field: dict[str, Any]) -> dict[str, Any]:
    key = field.get("key")
    if not isinstance(key, str) or not key.startswith(IDENTITY_KEY_PREFIX):
        return field
    provider = key[len(IDENTITY_KEY_PREFIX) :]
    params = field.get("params")
    if provider in VERIFIABLE_PROVIDERS or not isinstance(params, Mapping) or not params.get("require_verified"):
        return field
    field["params"] = {name: value for name, value in params.items() if name != "require_verified"}
    return field


def _map_fields(schema: Any, convert: Any) -> Any:
    """A schema document with every field passed through ``convert``.

    ``convert`` returns a list of replacement fields (empty to drop the field).
    A document without sections is handed back untouched -- nothing to rewrite.
    """
    if not isinstance(schema, Mapping) or not isinstance(schema.get("sections"), (list, tuple)):
        return schema
    sections = []
    for section in schema["sections"]:
        if not isinstance(section, Mapping) or not isinstance(section.get("fields"), (list, tuple)):
            sections.append(section)
            continue
        fields: list[Any] = []
        for field in section["fields"]:
            fields.extend(convert(field) if isinstance(field, Mapping) else [field])
        sections.append({**section, "fields": fields})
    return {**schema, "sections": sections}


def convert_schema(schema: Any) -> Any:
    """A stored form schema with ``battle_tag``/``smurf_tags`` merged into
    ``identity_battlenet``. Idempotent: a schema that never asked for either is
    returned unchanged apart from dead ``require_verified`` flags."""
    keys = {field.get("key") for field in _fields_of(schema)}
    has_smurfs = SMURF_TAGS_KEY in keys
    has_main = BATTLE_TAG_KEY in keys
    max_count = BATTLENET_MAX_COUNT if has_smurfs else 1

    def convert(field: Mapping[str, Any]) -> list[dict[str, Any]]:
        key = field.get("key")
        if key == BATTLE_TAG_KEY:
            return [_rename_condition(_identity_field(field, max_count=max_count), CONDITION_RENAMES)]
        if key == SMURF_TAGS_KEY:
            # Only field asking for Battle.net handles: it becomes the identity.
            if has_main:
                return []
            return [_rename_condition(_identity_field(field, max_count=max_count), CONDITION_RENAMES)]
        return [_strip_dead_require_verified(_rename_condition(dict(field), CONDITION_RENAMES))]

    return _map_fields(schema, convert)


def restore_schema(schema: Any) -> Any:
    """Inverse of :func:`convert_schema`: ``identity_battlenet`` back into
    ``battle_tag`` (+ ``smurf_tags`` when it carried more than one handle)."""

    def restore(field: Mapping[str, Any]) -> list[dict[str, Any]]:
        field = _rename_condition(dict(field), CONDITION_RESTORES)
        if field.get("key") != IDENTITY_BATTLENET_KEY:
            return [field]
        params = _params(field)
        main = {**field, "key": BATTLE_TAG_KEY, "kind": "builtin"}
        main.pop("params", None)
        if params.get("require_verified"):
            main["params"] = {"require_verified": True}
        max_count = params.get("max_count")
        if not isinstance(max_count, int) or max_count <= 1:
            return [main]
        return [main, {"key": SMURF_TAGS_KEY, "kind": "builtin", "required": False, "visibility": "public"}]

    return _map_fields(schema, restore)


def _merged_target(main: Any, smurfs: Any) -> dict[str, Any]:
    columns: list[str] = []
    for config in (main, smurfs):
        if not isinstance(config, Mapping) or config.get("mode") != "columns":
            continue
        for column in config.get("columns") or []:
            if isinstance(column, str) and column and column not in columns:
                columns.append(column)
    base = main if isinstance(main, Mapping) else (smurfs if isinstance(smurfs, Mapping) else {})
    merged = {**base, "parser": "battle_tag_list"}
    if columns:
        merged["mode"] = "columns"
        merged["columns"] = columns
    return merged


def convert_mapping(mapping: Any) -> Any:
    """A sheet feed's ``mapping_config_json`` with the two Battle.net targets
    merged into one ``identity_battlenet`` list target."""
    if not isinstance(mapping, Mapping):
        return mapping
    targets = mapping.get("targets")
    if not isinstance(targets, Mapping) or not ({BATTLE_TAG_KEY, SMURF_TAGS_KEY} & set(targets)):
        return dict(mapping)

    main = targets.get(BATTLE_TAG_KEY)
    smurfs = targets.get(SMURF_TAGS_KEY)
    merged = _merged_target(main, smurfs)
    new_targets: dict[str, Any] = {}
    for key, value in targets.items():
        if key == SMURF_TAGS_KEY:
            continue
        new_targets[IDENTITY_BATTLENET_KEY if key == BATTLE_TAG_KEY else key] = (
            merged if key == BATTLE_TAG_KEY else value
        )
    if IDENTITY_BATTLENET_KEY not in new_targets:
        new_targets[IDENTITY_BATTLENET_KEY] = merged

    # The dedup key used to fall back to the battle_tag VALUE when no column was
    # mapped to it. That fallback dies with the target, so pin the key to the
    # column it already resolved to -- every existing binding stays matched.
    record_key = new_targets.get("source_record_key")
    columns = merged.get("columns") if merged.get("mode") == "columns" else None
    if columns and (not isinstance(record_key, Mapping) or record_key.get("mode") != "columns"):
        new_targets["source_record_key"] = {"mode": "columns", "columns": [columns[0]], "parser": "battle_tag"}
    return {**mapping, "targets": new_targets}


def restore_mapping(mapping: Any) -> Any:
    """Inverse of :func:`convert_mapping`. The ``source_record_key`` target the
    upgrade may have pinned is left in place: it names the same column the
    fallback resolved to, so the dedup keys stay identical either way."""
    if not isinstance(mapping, Mapping):
        return mapping
    targets = mapping.get("targets")
    if not isinstance(targets, Mapping) or IDENTITY_BATTLENET_KEY not in targets:
        return dict(mapping)

    merged = targets[IDENTITY_BATTLENET_KEY]
    columns = list(merged.get("columns") or []) if isinstance(merged, Mapping) else []
    base = dict(merged) if isinstance(merged, Mapping) else {}
    main = {**base, "parser": "battle_tag"}
    if columns:
        main["columns"] = columns[:1]
    new_targets: dict[str, Any] = {}
    for key, value in targets.items():
        if key != IDENTITY_BATTLENET_KEY:
            new_targets[key] = value
            continue
        new_targets[BATTLE_TAG_KEY] = main
        if len(columns) > 1:
            new_targets[SMURF_TAGS_KEY] = {**base, "parser": "battle_tag_list", "columns": columns[1:]}
    return {**mapping, "targets": new_targets}


# ---------------------------------------------------------------------------
# Schema changes
# ---------------------------------------------------------------------------


def _rewrite_json(bind: Any, table: str, column: str, convert: Any) -> None:
    rows = bind.execute(sa.text(f"SELECT id, {column} FROM balancer.{table} ORDER BY id")).mappings()  # noqa: S608
    update = sa.text(f"UPDATE balancer.{table} SET {column} = CAST(:value AS json) WHERE id = :id")  # noqa: S608
    for row in rows.all():
        current = row[column]
        converted = convert(current)
        if converted != current:
            bind.execute(update, {"value": json.dumps(converted), "id": row["id"]})


def _rewrite_documents(bind: Any, *, schemas: Any, mappings: Any) -> None:
    """Every stored document that names the two builtins or their sheet targets.

    The four JSON columns of the ``balancer`` schema that can: both schema
    stores (``registration_form_version.schema_json``, the live one and every
    older snapshot, and ``registration_form_template.schema_json``) and the one
    mapping store (``registration_google_sheet_feed.mapping_config_json``).
    ``registration.custom_fields_json`` holds CUSTOM answers only -- both keys
    are reserved builtins, so no custom question can be filed under them --
    ``registration_google_sheet_binding.parsed_fields_json`` is a write-only
    snapshot of the last sync (nothing reads it back; the next sync overwrites
    it), and ``value_mapping_json`` maps cell VALUES, not target keys.
    """
    _rewrite_json(bind, "registration_form_version", "schema_json", schemas)
    _rewrite_json(bind, "registration_form_template", "schema_json", schemas)
    _rewrite_json(bind, "registration_google_sheet_feed", "mapping_config_json", mappings)


def upgrade() -> None:
    op.add_column(
        "registration_identity",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        schema="balancer",
    )
    op.drop_constraint(
        "uq_balancer_registration_identity_provider", "registration_identity", schema="balancer", type_="unique"
    )
    # Deferred for the same reason ``reghero01`` deferred the top-hero uniques:
    # a provider's handle list is rewritten wholesale, so promoting a smurf to
    # primary swaps two rows' positions and passes through a colliding state
    # that is consistent again at COMMIT.
    for name, columns in (
        ("uq_balancer_registration_identity_position", ("registration_id", "provider", "position")),
        ("uq_balancer_registration_identity_handle", ("registration_id", "provider", "handle_normalized")),
    ):
        op.create_unique_constraint(
            name,
            "registration_identity",
            list(columns),
            schema="balancer",
            deferrable=True,
            initially="DEFERRED",
        )

    bind = op.get_bind()
    # Skipping registrations that already carry a battlenet row keeps this safe
    # to re-run and leaves rows written by the new code alone (a deferrable
    # constraint cannot arbitrate ON CONFLICT, so there is no upsert here).
    registrations = bind.execute(
        sa.text(
            "SELECT r.id, r.battle_tag, r.smurf_tags_json FROM balancer.registration AS r"
            " WHERE r.battle_tag IS NOT NULL AND btrim(r.battle_tag) <> ''"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM balancer.registration_identity AS i"
            "   WHERE i.registration_id = r.id AND i.provider = :provider)"
            " ORDER BY r.id"
        ),
        {"provider": BATTLENET},
    ).mappings()
    insert_identity = sa.text(
        "INSERT INTO balancer.registration_identity"
        " (registration_id, provider, position, handle, handle_normalized, created_at)"
        " VALUES (:registration_id, :provider, :position, :handle, :handle_normalized, now())"
    )
    for registration in registrations.all():
        handles = battlenet_handles(registration["battle_tag"], registration["smurf_tags_json"])
        for position, (handle, normalized) in enumerate(handles):
            bind.execute(
                insert_identity,
                {
                    "registration_id": registration["id"],
                    "provider": BATTLENET,
                    "position": position,
                    "handle": handle,
                    "handle_normalized": normalized,
                },
            )

    _rewrite_documents(bind, schemas=convert_schema, mappings=convert_mapping)


def downgrade() -> None:
    bind = op.get_bind()
    # Registrations created AFTER the upgrade have no legacy value yet; the ones
    # that predate it get the same value back they were copied from.
    bind.execute(
        sa.text(
            "UPDATE balancer.registration AS r"
            " SET battle_tag = i.handle, battle_tag_normalized = i.handle_normalized"
            " FROM balancer.registration_identity AS i"
            " WHERE i.registration_id = r.id AND i.provider = :provider AND i.position = 0"
        ),
        {"provider": BATTLENET},
    )
    bind.execute(
        sa.text(
            "UPDATE balancer.registration AS r SET smurf_tags_json = s.tags FROM ("
            "   SELECT registration_id, json_agg(handle ORDER BY position) AS tags"
            "   FROM balancer.registration_identity"
            "   WHERE provider = :provider AND position > 0 GROUP BY registration_id"
            " ) AS s WHERE s.registration_id = r.id"
        ),
        {"provider": BATTLENET},
    )
    bind.execute(
        sa.text("DELETE FROM balancer.registration_identity WHERE provider = :provider"), {"provider": BATTLENET}
    )
    # Whatever extra handles another provider collected: the restored constraint
    # allows one row per (registration, provider), and the primary is the one
    # the old code would have kept.
    bind.execute(sa.text("DELETE FROM balancer.registration_identity WHERE position > 0"))

    _rewrite_documents(bind, schemas=restore_schema, mappings=restore_mapping)

    for name in (
        "uq_balancer_registration_identity_position",
        "uq_balancer_registration_identity_handle",
    ):
        op.drop_constraint(name, "registration_identity", schema="balancer", type_="unique")
    op.create_unique_constraint(
        "uq_balancer_registration_identity_provider",
        "registration_identity",
        ["registration_id", "provider"],
        schema="balancer",
    )
    op.drop_column("registration_identity", "position", schema="balancer")
