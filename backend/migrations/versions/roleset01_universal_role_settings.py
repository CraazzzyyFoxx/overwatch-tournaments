"""Fold the per-role solver knobs into ``role_settings``.

Revision ID: roleset01
Revises: mixrank01
Create Date: 2026-10-07 00:00:00.000000

The balancer used to spell its per-role weights as flat, Overwatch-shaped
knobs -- one key per (role, weight) pair, with the role baked into the key name
(``tank_impact_weight``, ``tank_gap_weight``, ``mix_role_weights``). Only three
of the four roster slots ever got a knob, and adding a role meant adding keys
in Python, in Rust and in the drawer. The weights now live in a single
``role_settings`` map keyed by roster slot code, declared once in
``DEFAULT_ROLE_SETTINGS``, and the old keys are rejected on write (422).

This moves the stored overrides to match:

    tank_impact_weight      -> role_settings.tank.impact
    damage_impact_weight    -> role_settings.damage.impact
    support_impact_weight   -> role_settings.support.impact
    tank_gap_weight         -> role_settings.tank.line_gap_weight
    tank_std_weight         -> role_settings.tank.line_std_weight
    mix_role_weights.<role> -> role_settings.<role>.mix_weight

Three blobs carry them: the operator's tournament overrides, the config
snapshot frozen onto a saved balance, and a mix host's own preferences. All
three are *override* documents -- a knob the user never set is an absent key,
never an explicit null -- so only keys actually present move, and everything
else in the document is left exactly as it was. A ``mix_role_weights`` that is
null or not a mapping carries no weights and is simply dropped.

A document that already has a ``role_settings`` is merged into rather than
replaced, and the new shape wins: a field already written under the new spelling
is what the user last saved, the flat key is the stale one. (This only matters
for a blob written between the API switch and this migration.)

The rewrite runs in Python rather than as a SQL function: unlike ``roledps01``
this is a handful of named keys in three small tables, not a token hunt through
every document in the schema, and the mapping is wanted as plain functions the
downgrade can run backwards.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "roleset01"
down_revision: str | Sequence[str] | None = "mixrank01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``(flat key, roster slot code, ``RoleSettings`` field)``.
FLAT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("tank_impact_weight", "tank", "impact"),
    ("damage_impact_weight", "damage", "impact"),
    ("support_impact_weight", "support", "impact"),
    ("tank_gap_weight", "tank", "line_gap_weight"),
    ("tank_std_weight", "tank", "line_std_weight"),
)

#: Everything the fold consumes, including the one map-shaped key.
OLD_KEYS: frozenset[str] = frozenset({key for key, _, _ in FLAT_FIELDS} | {"mix_role_weights"})

#: ``(table, column, column type)``. The cast matters -- two of these are plain
#: ``json`` and one is ``jsonb``, and the value has to go back as what the
#: column actually is.
JSON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("balancer.tournament_config", "config_json", "json"),
    ("balancer.balance", "config_json", "json"),
    ("balancer.user_config", "config_json", "jsonb"),
)


def fold_role_settings(document: Any) -> Any:
    """Move the flat per-role knobs of one override blob into ``role_settings``."""
    if not isinstance(document, Mapping):
        return document

    moved: dict[str, dict[str, Any]] = {}
    for old_key, role, field in FLAT_FIELDS:
        if old_key in document:
            moved.setdefault(role, {})[field] = document[old_key]
    weights = document.get("mix_role_weights")
    if isinstance(weights, Mapping):
        for role, weight in weights.items():
            moved.setdefault(role, {})["mix_weight"] = weight

    if not OLD_KEYS & set(document):
        return document

    folded = {key: value for key, value in document.items() if key not in OLD_KEYS}
    if moved:
        existing = document.get("role_settings")
        settings = dict(existing) if isinstance(existing, Mapping) else {}
        for role, fields in moved.items():
            entry = settings.get(role)
            entry = dict(entry) if isinstance(entry, Mapping) else {}
            # ``setdefault``: a field already saved in the new shape wins.
            for field, value in fields.items():
                entry.setdefault(field, value)
            settings[role] = entry
        folded["role_settings"] = settings
    return folded


def unfold_role_settings(document: Any) -> Any:
    """Spread ``role_settings`` back out into the flat knobs it replaced."""
    if not isinstance(document, Mapping):
        return document
    settings = document.get("role_settings")
    if not isinstance(settings, Mapping):
        return document

    flat: dict[str, Any] = {}
    weights: dict[str, Any] = {}
    remaining: dict[str, Any] = {}
    for role, fields in settings.items():
        if not isinstance(fields, Mapping):
            remaining[role] = fields
            continue
        leftover = dict(fields)
        for old_key, flat_role, field in FLAT_FIELDS:
            if flat_role == role and field in leftover:
                flat[old_key] = leftover.pop(field)
        if "mix_weight" in leftover:
            weights[role] = leftover.pop("mix_weight")
        # A role or field the old shape had no key for (``flex``, a damage line
        # weight) stays where it is rather than being dropped on the floor.
        if leftover:
            remaining[role] = leftover

    unfolded = {key: value for key, value in document.items() if key != "role_settings"}
    unfolded.update(flat)
    if weights:
        unfolded["mix_role_weights"] = weights
    if remaining:
        unfolded["role_settings"] = remaining
    return unfolded


def _rewrite(convert: Callable[[Any], Any]) -> None:
    bind = op.get_bind()
    for table, column, column_type in JSON_COLUMNS:
        rows = bind.execute(
            sa.text(f'SELECT id, "{column}" FROM {table} WHERE "{column}" IS NOT NULL ORDER BY id')
        ).mappings()
        update = sa.text(f'UPDATE {table} SET "{column}" = CAST(:document AS {column_type}) WHERE id = :id')
        for row in rows.all():
            current = row[column]
            converted = convert(current)
            if converted != current:
                bind.execute(update, {"document": json.dumps(converted, ensure_ascii=False), "id": row["id"]})


def upgrade() -> None:
    _rewrite(fold_role_settings)


def downgrade() -> None:
    _rewrite(unfold_role_settings)
