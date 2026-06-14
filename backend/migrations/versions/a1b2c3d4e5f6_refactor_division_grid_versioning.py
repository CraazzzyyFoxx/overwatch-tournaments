"""refactor_division_grid_versioning

Revision ID: a1b2c3d4e5f6
Revises: z6u0v4w5x6y7
Create Date: 2026-04-14 00:00:00.000000
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "z6u0v4w5x6y7"
branch_labels = None
depends_on = None


DEFAULT_ICON_BASE = "https://minio.craazzzyyfoxx.me/aqt/assets/divisions"


def _make_absolute_icon_url(value: str | None, fallback_number: int) -> str:
    if value and value.startswith(("http://", "https://")):
        return value
    if value:
        match = re.search(r"/divisions/(\d+)\.(png|webp|jpg|jpeg|gif)$", value)
        if match:
            return f"{DEFAULT_ICON_BASE}/default-{match.group(1)}.{match.group(2)}"
    return f"{DEFAULT_ICON_BASE}/default-{fallback_number}.png"


def _tiers_from_raw(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    tiers = (raw or {}).get("tiers") or []
    normalized: list[dict[str, Any]] = []
    for index, tier in enumerate(sorted(tiers, key=lambda item: int(item["number"]))):
        number = int(tier["number"])
        normalized.append(
            {
                "slug": f"division-{number}",
                "number": number,
                "name": str(tier["name"]),
                "sort_order": index,
                "rank_min": int(tier["rank_min"]),
                "rank_max": int(tier["rank_max"]) if tier.get("rank_max") is not None else None,
                "icon_url": _make_absolute_icon_url(tier.get("icon_path"), number),
            }
        )
    return normalized


def upgrade() -> None:
    op.create_table(
        "division_grid",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_division_grid_workspace_slug"),
    )
    op.create_index("ix_division_grid_workspace_id", "division_grid", ["workspace_id"])

    op.create_table(
        "division_grid_version",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grid_id", sa.BigInteger(), sa.ForeignKey("division_grid.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column(
            "created_from_version_id",
            sa.BigInteger(),
            sa.ForeignKey("division_grid_version.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("grid_id", "version", name="uq_division_grid_version_grid_version"),
    )
    op.create_index("ix_division_grid_version_grid_id", "division_grid_version", ["grid_id"])
    op.create_index(
        "ix_division_grid_version_created_from_version_id",
        "division_grid_version",
        ["created_from_version_id"],
    )

    op.create_table(
        "division_grid_tier",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version_id",
            sa.BigInteger(),
            sa.ForeignKey("division_grid_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_order", sa.BigInteger(), nullable=False),
        sa.Column("rank_min", sa.BigInteger(), nullable=False),
        sa.Column("rank_max", sa.BigInteger(), nullable=True),
        sa.Column("icon_url", sa.String(), nullable=False),
        sa.UniqueConstraint("version_id", "slug", name="uq_division_grid_tier_version_slug"),
        sa.UniqueConstraint("version_id", "sort_order", name="uq_division_grid_tier_version_sort_order"),
    )
    op.create_index("ix_division_grid_tier_version_id", "division_grid_tier", ["version_id"])

    op.create_table(
        "division_grid_mapping",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_version_id",
            sa.BigInteger(),
            sa.ForeignKey("division_grid_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_version_id",
            sa.BigInteger(),
            sa.ForeignKey("division_grid_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("source_version_id", "target_version_id", name="uq_division_grid_mapping_pair"),
    )
    op.create_index("ix_division_grid_mapping_source_version_id", "division_grid_mapping", ["source_version_id"])
    op.create_index("ix_division_grid_mapping_target_version_id", "division_grid_mapping", ["target_version_id"])

    op.create_table(
        "division_grid_mapping_rule",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "mapping_id",
            sa.BigInteger(),
            sa.ForeignKey("division_grid_mapping.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_tier_id",
            sa.BigInteger(),
            sa.ForeignKey("division_grid_tier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_tier_id",
            sa.BigInteger(),
            sa.ForeignKey("division_grid_tier.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_division_grid_mapping_rule_mapping_id", "division_grid_mapping_rule", ["mapping_id"])
    op.create_index("ix_division_grid_mapping_rule_source_tier_id", "division_grid_mapping_rule", ["source_tier_id"])
    op.create_index("ix_division_grid_mapping_rule_target_tier_id", "division_grid_mapping_rule", ["target_tier_id"])

    op.add_column("workspace", sa.Column("default_division_grid_version_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "ix_workspace_default_division_grid_version_id",
        "workspace",
        ["default_division_grid_version_id"],
    )
    op.create_foreign_key(
        "fk_workspace_default_division_grid_version_id",
        "workspace",
        "division_grid_version",
        ["default_division_grid_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "tournament",
        sa.Column("division_grid_version_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_division_grid_version_id",
        "tournament",
        ["division_grid_version_id"],
        schema="tournament",
    )
    op.create_foreign_key(
        "fk_tournament_division_grid_version_id",
        "tournament",
        "division_grid_version",
        ["division_grid_version_id"],
        ["id"],
        source_schema="tournament",
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    meta = sa.MetaData()
    workspace = sa.Table("workspace", meta, autoload_with=bind)
    tournament = sa.Table("tournament", meta, schema="tournament", autoload_with=bind)
    division_grid = sa.Table("division_grid", meta, autoload_with=bind)
    division_grid_version = sa.Table("division_grid_version", meta, autoload_with=bind)
    division_grid_tier = sa.Table("division_grid_tier", meta, autoload_with=bind)

    def create_grid_version(
        *,
        workspace_id: int | None,
        slug: str,
        name: str,
        description: str | None,
        label: str,
        raw_grid: dict[str, Any] | None,
    ) -> int:
        grid_id = bind.execute(
            division_grid.insert().values(
                workspace_id=workspace_id,
                slug=slug,
                name=name,
                description=description,
            ).returning(division_grid.c.id)
        ).scalar_one()
        version_id = bind.execute(
            division_grid_version.insert().values(
                grid_id=grid_id,
                version=1,
                label=label,
                status="published",
                published_at=sa.func.now(),
            ).returning(division_grid_version.c.id)
        ).scalar_one()

        tiers = _tiers_from_raw(raw_grid)
        if tiers:
            bind.execute(
                division_grid_tier.insert(),
                [{"version_id": version_id, **tier} for tier in tiers],
            )
        return version_id

    system_grid_raw = {
        "tiers": [
            {
                "number": div_num,
                "name": f"Division {div_num}",
                "rank_min": 2000 if div_num == 1 else (20 - div_num) * 100,
                "rank_max": None if div_num == 1 else ((20 - div_num) * 100) + 99,
                "icon_path": f"/divisions/{div_num}.png",
            }
            for div_num in range(20, 0, -1)
        ]
    }
    system_version_id = create_grid_version(
        workspace_id=None,
        slug="system-default",
        name="System Default",
        description="Migrated system default division grid",
        label="System Default",
        raw_grid=system_grid_raw,
    )

    workspace_rows = bind.execute(
        sa.select(workspace.c.id, workspace.c.name, workspace.c.division_grid_json)
    ).mappings().all()
    workspace_version_map: dict[int, int] = {}
    for row in workspace_rows:
        if row["division_grid_json"]:
            version_id = create_grid_version(
                workspace_id=row["id"],
                slug="default",
                name=f"{row['name']} Default Grid",
                description="Migrated from workspace.division_grid_json",
                label="Migrated Workspace Grid",
                raw_grid=row["division_grid_json"],
            )
        else:
            version_id = system_version_id

        workspace_version_map[row["id"]] = version_id
        bind.execute(
            workspace.update()
            .where(workspace.c.id == row["id"])
            .values(default_division_grid_version_id=version_id)
        )

    tournament_rows = bind.execute(
        sa.select(
            tournament.c.id,
            tournament.c.workspace_id,
            tournament.c.name,
            tournament.c.division_grid_json,
        )
    ).mappings().all()
    for row in tournament_rows:
        version_id = workspace_version_map.get(row["workspace_id"], system_version_id)
        if row["division_grid_json"]:
            version_id = create_grid_version(
                workspace_id=row["workspace_id"],
                slug=f"tournament-{row['id']}-override",
                name=f"{row['name']} Override Grid",
                description="Migrated from tournament.division_grid_json",
                label="Migrated Tournament Override",
                raw_grid=row["division_grid_json"],
            )

        bind.execute(
            tournament.update()
            .where(tournament.c.id == row["id"])
            .values(division_grid_version_id=version_id)
        )

    op.alter_column("workspace", "default_division_grid_version_id", nullable=False)
    op.alter_column("tournament", "division_grid_version_id", nullable=False, schema="tournament")

    op.drop_column("workspace", "division_grid_json")
    op.drop_column("tournament", "division_grid_json", schema="tournament")


def downgrade() -> None:
    op.add_column("workspace", sa.Column("division_grid_json", sa.JSON(), nullable=True))
    op.add_column("tournament", sa.Column("division_grid_json", sa.JSON(), nullable=True), schema="tournament")

    op.drop_constraint("fk_tournament_division_grid_version_id", "tournament", schema="tournament", type_="foreignkey")
    op.drop_index("ix_tournament_division_grid_version_id", table_name="tournament", schema="tournament")
    op.drop_column("tournament", "division_grid_version_id", schema="tournament")

    op.drop_constraint("fk_workspace_default_division_grid_version_id", "workspace", type_="foreignkey")
    op.drop_index("ix_workspace_default_division_grid_version_id", table_name="workspace")
    op.drop_column("workspace", "default_division_grid_version_id")

    op.drop_index("ix_division_grid_mapping_rule_target_tier_id", table_name="division_grid_mapping_rule")
    op.drop_index("ix_division_grid_mapping_rule_source_tier_id", table_name="division_grid_mapping_rule")
    op.drop_index("ix_division_grid_mapping_rule_mapping_id", table_name="division_grid_mapping_rule")
    op.drop_table("division_grid_mapping_rule")

    op.drop_index("ix_division_grid_mapping_target_version_id", table_name="division_grid_mapping")
    op.drop_index("ix_division_grid_mapping_source_version_id", table_name="division_grid_mapping")
    op.drop_table("division_grid_mapping")

    op.drop_index("ix_division_grid_tier_version_id", table_name="division_grid_tier")
    op.drop_table("division_grid_tier")

    op.drop_index("ix_division_grid_version_created_from_version_id", table_name="division_grid_version")
    op.drop_index("ix_division_grid_version_grid_id", table_name="division_grid_version")
    op.drop_table("division_grid_version")

    op.drop_index("ix_division_grid_workspace_id", table_name="division_grid")
    op.drop_table("division_grid")
