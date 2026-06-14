"""migrate_groups_to_stages

Migrates TournamentGroup data into Stage + StageItem tables.
Backfills stage_id/stage_item_id on Encounter and Standing.
Adds stage_id bridge column to TournamentGroup.

For each TournamentGroup:
  - is_groups=True  -> Stage(stage_type=round_robin)  + StageItem(type=group)
  - is_groups=False -> Stage(stage_type=double_elimination) + StageItem(type=single_bracket)
    (DE is the default for playoffs; refined by checking encounter round signs)

Revision ID: t0o4p8q9r0s1
Revises: s9n3o7p8q9r0
Create Date: 2026-04-10 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "t0o4p8q9r0s1"
down_revision: Union[str, None] = "s9n3o7p8q9r0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add stage_id bridge FK to tournament.group
    op.add_column(
        "group",
        sa.Column("stage_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )
    op.create_foreign_key(
        "fk_group_stage_id", "group", "stage",
        ["stage_id"], ["id"],
        source_schema="tournament", referent_schema="tournament",
        ondelete="SET NULL",
    )

    # 2. Migrate data: for each TournamentGroup, create a Stage + StageItem
    #    and backfill the bridge FK.
    #
    # We use raw SQL here because Alembic data migrations with ORM models
    # can break when models change in future. Raw SQL is stable.

    conn = op.get_bind()

    # Fetch all groups ordered by tournament_id and id
    groups = conn.execute(sa.text("""
        SELECT g.id, g.tournament_id, g.name, g.description,
               g.is_groups, g.challonge_id, g.challonge_slug
        FROM tournament."group" g
        ORDER BY g.tournament_id, g.id
    """)).fetchall()

    # Track order per tournament for stage ordering
    tournament_order: dict[int, int] = {}

    for group in groups:
        group_id = group[0]
        tournament_id = group[1]
        name = group[2]
        description = group[3]
        is_groups = group[4]
        challonge_id = group[5]
        challonge_slug = group[6]

        # Determine stage order
        order = tournament_order.get(tournament_id, 0)
        tournament_order[tournament_id] = order + 1

        # Determine stage_type:
        # - is_groups=True -> round_robin
        # - is_groups=False -> check encounters for negative rounds (DE) or positive only (SE)
        if is_groups:
            stage_type = "round_robin"
            item_type = "group"
        else:
            # Check if encounters for this group have negative rounds (lower bracket = DE)
            has_negative = conn.execute(sa.text("""
                SELECT EXISTS(
                    SELECT 1 FROM tournament.encounter
                    WHERE tournament_group_id = :gid AND round < 0
                )
            """), {"gid": group_id}).scalar()

            stage_type = "double_elimination" if has_negative else "single_elimination"
            item_type = "single_bracket"

        # Create Stage
        result = conn.execute(sa.text("""
            INSERT INTO tournament.stage
                (tournament_id, name, description, stage_type, "order",
                 is_active, is_completed, challonge_id, challonge_slug, created_at)
            VALUES
                (:tid, :name, :desc, CAST(:stype AS tournament.stagetype), :ord,
                 false, false, :cid, :cslug, now())
            RETURNING id
        """), {
            "tid": tournament_id,
            "name": name,
            "desc": description,
            "stype": stage_type,
            "ord": order,
            "cid": challonge_id,
            "cslug": challonge_slug,
        })
        stage_id = result.scalar_one()

        # Create StageItem
        result = conn.execute(sa.text("""
            INSERT INTO tournament.stage_item
                (stage_id, name, type, "order", created_at)
            VALUES
                (:sid, :name, CAST(:itype AS tournament.stageitemtype), 0, now())
            RETURNING id
        """), {
            "sid": stage_id,
            "name": name,
            "itype": item_type,
        })
        stage_item_id = result.scalar_one()

        # Link TournamentGroup -> Stage
        conn.execute(sa.text("""
            UPDATE tournament."group"
            SET stage_id = :sid
            WHERE id = :gid
        """), {"sid": stage_id, "gid": group_id})

        # Backfill stage_id, stage_item_id on Encounter
        conn.execute(sa.text("""
            UPDATE tournament.encounter
            SET stage_id = :sid, stage_item_id = :siid
            WHERE tournament_group_id = :gid
        """), {"sid": stage_id, "siid": stage_item_id, "gid": group_id})

        # Backfill stage_id, stage_item_id on Standing
        conn.execute(sa.text("""
            UPDATE tournament.standing
            SET stage_id = :sid, stage_item_id = :siid
            WHERE group_id = :gid
        """), {"sid": stage_id, "siid": stage_item_id, "gid": group_id})

    # 3. Create StageItemInput records for teams that have standings
    #    (teams assigned to each stage item)
    conn.execute(sa.text("""
        INSERT INTO tournament.stage_item_input
            (stage_item_id, slot, input_type, team_id, created_at)
        SELECT DISTINCT
            s.stage_item_id,
            ROW_NUMBER() OVER (PARTITION BY s.stage_item_id ORDER BY s.position),
            'final'::tournament.stageiteminputtype,
            s.team_id,
            now()
        FROM tournament.standing s
        WHERE s.stage_item_id IS NOT NULL
    """))


def downgrade() -> None:
    # Remove StageItemInput records created by migration
    op.execute("""
        DELETE FROM tournament.stage_item_input
        WHERE id IN (
            SELECT sii.id FROM tournament.stage_item_input sii
            JOIN tournament.stage_item si ON sii.stage_item_id = si.id
            JOIN tournament.stage st ON si.stage_id = st.id
            JOIN tournament."group" g ON g.stage_id = st.id
        )
    """)

    # Clear backfilled FKs
    op.execute("UPDATE tournament.encounter SET stage_id = NULL, stage_item_id = NULL")
    op.execute("UPDATE tournament.standing SET stage_id = NULL, stage_item_id = NULL")

    # Remove bridge FK and column
    op.drop_constraint("fk_group_stage_id", "group", schema="tournament", type_="foreignkey")
    op.drop_column("group", "stage_id", schema="tournament")

    # Delete migrated Stage/StageItem records
    op.execute("""
        DELETE FROM tournament.stage_item WHERE stage_id IN (
            SELECT id FROM tournament.stage
        )
    """)
    op.execute("DELETE FROM tournament.stage")
