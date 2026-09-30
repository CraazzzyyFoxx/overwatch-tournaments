"""Drop the v1 table the rank-mapping editor froze into ``parser.rank_mapping``.

Revision ID: owmapfix01
Revises: draftfmt01
Create Date: 2026-09-30 00:00:00.000000

The admin rank-mapping editor saved every one of its cells, edited or not,
stamped ``ow2-default-v1``. One save and the "override" was a full copy of the
v1 table, which ``get_rank_mapping`` overlays cell by cell -- so it outlived
``owemerald01``: the collector kept writing v1 values (platinum 3 = 2700) that
every reader resolves on the v2 ladder (2700 = Emerald 3). Every Bronze..Platinum
player has read one division too high since: Platinum in game, Emerald on the
site. ``owemerald01`` rebased the rows that existed then; the setting that kept
producing new ones was out of its scope.

1. The setting: an entry equal to its v1 or v2 default cell is the frozen copy,
   not an override, and goes. An entry that differs from both was set by hand
   and stays.
2. The snapshots: every row stamped with the setting's old version is recomputed
   from its native ``division``/``tier`` through the effective table -- v2 plus
   the surviving overrides -- and restamped v2. Lossless, as in ``owemerald01``.

``balancer.registration_role.rank_value`` is left alone for the reason
``owemerald01`` gives: those are recorded registrations, not a cache.

Downgrade is a no-op: the removed entries were the bug, and v2 rows are what
``owemerald01`` -- still applied below this revision -- expects.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "owmapfix01"
down_revision: str | Sequence[str] | None = "draftfmt01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTING_KEY = "parser.rank_mapping"
V1_VERSION = "ow2-default-v1"
V2_VERSION = "ow2-default-v2"

#: Tier-5 rank_value per native division, as in ``owemerald01``.
V1_BASES: dict[str, int] = {
    "bronze": 1000,
    "silver": 1500,
    "gold": 2000,
    "platinum": 2500,
    "diamond": 3000,
    "master": 3500,
    "grandmaster": 4000,
    "ultimate": 4500,
}
V2_BASES: dict[str, int] = {
    "bronze": 500,
    "silver": 1000,
    "gold": 1500,
    "platinum": 2000,
    "emerald": 2500,
    "diamond": 3000,
    "master": 3500,
    "grandmaster": 4000,
    "ultimate": 4500,
}


def _cell(bases: dict[str, int], division: str, tier: int) -> int | None:
    base = bases.get(division)
    return None if base is None else base + (5 - tier) * 100


def upgrade() -> None:
    bind = op.get_bind()
    value = bind.execute(sa.text("SELECT value FROM settings WHERE key = :key"), {"key": SETTING_KEY}).scalar()
    if not value:
        return

    stale_version = value.get("version") or V1_VERSION
    kept = [
        entry
        for entry in value.get("entries") or []
        if entry["rank_value"]
        not in (
            _cell(V1_BASES, entry["division"].lower(), entry["tier"]),
            _cell(V2_BASES, entry["division"].lower(), entry["tier"]),
        )
    ]
    bind.execute(
        sa.text("UPDATE settings SET value = :value, updated_at = now() WHERE key = :key").bindparams(
            sa.bindparam("value", type_=sa.JSON())
        ),
        {"key": SETTING_KEY, "value": {**value, "version": V2_VERSION, "entries": kept}},
    )

    effective = {(division, tier): _cell(V2_BASES, division, tier) for division in V2_BASES for tier in range(1, 6)}
    effective.update({(entry["division"].lower(), entry["tier"]): entry["rank_value"] for entry in kept})
    bind.execute(
        sa.text(
            """
            UPDATE overwatch_rank.rank_snapshot AS s
            SET rank_value = e.rank_value,
                mapping_version = :to_version
            FROM unnest(CAST(:divisions AS text[]), CAST(:tiers AS int[]), CAST(:values AS int[]))
                AS e(division, tier, rank_value)
            WHERE s.mapping_version IN (:v1, :stale)
              AND lower(s.division) = e.division
              AND s.tier = e.tier
            """
        ),
        {
            "to_version": V2_VERSION,
            "v1": V1_VERSION,
            "stale": stale_version,
            "divisions": [division for division, _ in effective],
            "tiers": [tier for _, tier in effective],
            "values": list(effective.values()),
        },
    )


def downgrade() -> None:
    pass
