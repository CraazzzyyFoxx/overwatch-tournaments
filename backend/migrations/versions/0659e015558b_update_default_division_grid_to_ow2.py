"""update_default_division_grid_to_ow2

Revision ID: 0659e015558b
Revises: settings0001
Create Date: 2026-06-02 03:34:52.946294

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0659e015558b"
down_revision: str | None = "settings0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Find the system-default grid ID
    grid_id = bind.execute(
        sa.text("SELECT id FROM division_grid WHERE workspace_id IS NULL AND slug = 'system-default'")
    ).scalar()

    if grid_id is None:
        grid_id = bind.execute(
            sa.text(
                "INSERT INTO division_grid (slug, name, description) "
                "VALUES ('system-default', 'System Default', 'System default division grid') RETURNING id"
            )
        ).scalar()

    # 2. Get the new version number
    max_ver = bind.execute(
        sa.text("SELECT COALESCE(MAX(version), 0) FROM division_grid_version WHERE grid_id = :grid_id"),
        {"grid_id": grid_id},
    ).scalar()
    new_version = int(max_ver or 0) + 1

    # 3. Create a new published version
    new_version_id = bind.execute(
        sa.text(
            "INSERT INTO division_grid_version (grid_id, version, label, status, published_at) "
            "VALUES (:grid_id, :version, 'Overwatch 2 Default Grid', 'published', NOW()) RETURNING id"
        ),
        {"grid_id": grid_id, "version": new_version},
    ).scalar()

    # 4. Generate the 40 standard tiers
    divisions = ["champion", "grandmaster", "master", "diamond", "platinum", "gold", "silver", "bronze"]
    bases = {
        "bronze": 1000,
        "silver": 1500,
        "gold": 2000,
        "platinum": 2500,
        "diamond": 3000,
        "master": 3500,
        "grandmaster": 4000,
        "champion": 4500,
    }

    tiers = []
    sort_order = 0
    number = 1

    for div in divisions:
        base = bases[div]
        for tier_num in range(1, 6):
            slug = f"{div}-{tier_num}"
            name = f"{div.capitalize()} {tier_num}"
            offset = (5 - tier_num) * 100
            rank_min = base + offset

            if div == "champion" and tier_num == 1:
                rank_max = None
            else:
                rank_max = rank_min + 99

            icon_url = f"https://minio.craazzzyyfoxx.me/aqt/assets/divisions/{slug}.png"

            tiers.append(
                {
                    "version_id": new_version_id,
                    "slug": slug,
                    "number": number,
                    "name": name,
                    "sort_order": sort_order,
                    "rank_min": rank_min,
                    "rank_max": rank_max,
                    "icon_url": icon_url,
                }
            )
            sort_order += 1
            number += 1

    # 5. Insert the tiers
    for tier in tiers:
        bind.execute(
            sa.text(
                "INSERT INTO division_grid_tier (version_id, slug, number, name, sort_order, rank_min, rank_max, icon_url) "
                "VALUES (:version_id, :slug, :number, :name, :sort_order, :rank_min, :rank_max, :icon_url)"
            ),
            tier,
        )

    # 6. Update workspaces to point to the new version
    bind.execute(
        sa.text(
            "UPDATE workspace SET default_division_grid_version_id = :new_version_id "
            "WHERE default_division_grid_version_id IN ("
            "    SELECT id FROM division_grid_version WHERE grid_id = :grid_id"
            ")"
        ),
        {"new_version_id": new_version_id, "grid_id": grid_id},
    )

    # 7. Update tournaments to point to the new version
    bind.execute(
        sa.text(
            "UPDATE tournament.tournament SET division_grid_version_id = :new_version_id "
            "WHERE division_grid_version_id IN ("
            "    SELECT id FROM division_grid_version WHERE grid_id = :grid_id"
            ")"
        ),
        {"new_version_id": new_version_id, "grid_id": grid_id},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Find system default grid ID
    grid_id = bind.execute(
        sa.text("SELECT id FROM division_grid WHERE workspace_id IS NULL AND slug = 'system-default'")
    ).scalar()

    if grid_id is None:
        return

    # 2. Find version 1 (old default) and version 2 (new default)
    v1_id = bind.execute(
        sa.text("SELECT id FROM division_grid_version WHERE grid_id = :grid_id AND version = 1"), {"grid_id": grid_id}
    ).scalar()

    v2_id = bind.execute(
        sa.text("SELECT id FROM division_grid_version WHERE grid_id = :grid_id AND version = 2"), {"grid_id": grid_id}
    ).scalar()

    if v1_id is not None and v2_id is not None:
        # Revert workspaces pointing to v2 back to v1
        bind.execute(
            sa.text(
                "UPDATE workspace SET default_division_grid_version_id = :v1_id WHERE default_division_grid_version_id = :v2_id"
            ),
            {"v1_id": v1_id, "v2_id": v2_id},
        )

        # Revert tournaments pointing to v2 back to v1
        bind.execute(
            sa.text(
                "UPDATE tournament.tournament SET division_grid_version_id = :v1_id WHERE division_grid_version_id = :v2_id"
            ),
            {"v1_id": v1_id, "v2_id": v2_id},
        )

        # Delete version 2 (this cascades to division_grid_tier)
        bind.execute(sa.text("DELETE FROM division_grid_version WHERE id = :v2_id"), {"v2_id": v2_id})
