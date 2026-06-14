"""tournament_phase_a_backfill_stage_refs

Phase A: завершает миграцию groups → stages.

1. Создаёт Stage + StageItem для любой TournamentGroup, у которой stage_id IS NULL
   (группы, созданные уже после t0o4p8q9r0s1 через Challonge sync / create_groups).
2. Backfill Encounter.stage_id / stage_item_id из TournamentGroup для записей
   с stage_id IS NULL.
3. Backfill Standing.stage_id / stage_item_id из TournamentGroup.
4. Делает Standing.group_id nullable.
5. Ослабляет UNIQUE(tournament_id, group_id, team_id) → COALESCE-aware unique index
   по (tournament_id, stage_id, stage_item_id, team_id).

Revision ID: phasea0001
Revises: merge0003
Create Date: 2026-04-18 04:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "phasea0001"
down_revision: Union[str, Sequence[str], None] = "merge0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create Stage + StageItem for each "orphan" TournamentGroup (stage_id IS NULL).
    #    Идентично t0o4p8q9r0s1 но для групп, добавленных позже (Challonge sync
    #    после первичной миграции создавал TournamentGroup без linked Stage).
    orphan_groups = conn.execute(
        sa.text(
            """
            SELECT g.id, g.tournament_id, g.name, g.description,
                   g.is_groups, g.challonge_id, g.challonge_slug
            FROM tournament."group" g
            WHERE g.stage_id IS NULL
            ORDER BY g.tournament_id, g.id
            """
        )
    ).fetchall()

    # Для правильного order: считаем существующий max(order) per tournament
    per_tournament_order: dict[int, int] = {}
    for group in orphan_groups:
        group_id = group[0]
        tournament_id = group[1]
        name = group[2]
        description = group[3]
        is_groups = group[4]
        challonge_id = group[5]
        challonge_slug = group[6]

        if tournament_id not in per_tournament_order:
            max_order_row = conn.execute(
                sa.text(
                    'SELECT COALESCE(MAX("order"), -1) FROM tournament.stage WHERE tournament_id = :tid'
                ),
                {"tid": tournament_id},
            ).scalar()
            per_tournament_order[tournament_id] = int(max_order_row or -1)

        per_tournament_order[tournament_id] += 1
        order = per_tournament_order[tournament_id]

        if is_groups:
            stage_type = "round_robin"
            item_type = "group"
        else:
            has_negative = conn.execute(
                sa.text(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM tournament.encounter
                        WHERE tournament_group_id = :gid AND round < 0
                    )
                    """
                ),
                {"gid": group_id},
            ).scalar()
            stage_type = "double_elimination" if has_negative else "single_elimination"
            item_type = "single_bracket"

        stage_row = conn.execute(
            sa.text(
                """
                INSERT INTO tournament.stage
                    (tournament_id, name, description, stage_type, "order",
                     is_active, is_completed, challonge_id, challonge_slug, created_at)
                VALUES
                    (:tid, :name, :desc, CAST(:stype AS tournament.stagetype), :ord,
                     false, false, :cid, :cslug, now())
                RETURNING id
                """
            ),
            {
                "tid": tournament_id,
                "name": name,
                "desc": description,
                "stype": stage_type,
                "ord": order,
                "cid": challonge_id,
                "cslug": challonge_slug,
            },
        )
        stage_id = stage_row.scalar_one()

        item_row = conn.execute(
            sa.text(
                """
                INSERT INTO tournament.stage_item
                    (stage_id, name, type, "order", created_at)
                VALUES
                    (:sid, :name, CAST(:itype AS tournament.stageitemtype), 0, now())
                RETURNING id
                """
            ),
            {"sid": stage_id, "name": name, "itype": item_type},
        )
        stage_item_id = item_row.scalar_one()

        conn.execute(
            sa.text(
                'UPDATE tournament."group" SET stage_id = :sid WHERE id = :gid'
            ),
            {"sid": stage_id, "gid": group_id},
        )

        conn.execute(
            sa.text(
                """
                UPDATE tournament.encounter
                SET stage_id = :sid,
                    stage_item_id = :siid
                WHERE tournament_group_id = :gid
                  AND stage_id IS NULL
                """
            ),
            {"sid": stage_id, "siid": stage_item_id, "gid": group_id},
        )

        conn.execute(
            sa.text(
                """
                UPDATE tournament.standing
                SET stage_id = :sid,
                    stage_item_id = :siid
                WHERE group_id = :gid
                  AND stage_id IS NULL
                """
            ),
            {"sid": stage_id, "siid": stage_item_id, "gid": group_id},
        )

    # 2. Для encounter, у которых есть stage_id но нет stage_item_id —
    #    подтянем stage_item через tournament_group_id → TournamentGroup.stage_id.
    conn.execute(
        sa.text(
            """
            UPDATE tournament.encounter e
            SET stage_item_id = si.id
            FROM tournament.stage_item si
            WHERE e.stage_id IS NOT NULL
              AND e.stage_item_id IS NULL
              AND si.stage_id = e.stage_id
              AND si.id = (
                  SELECT s.id FROM tournament.stage_item s
                  WHERE s.stage_id = e.stage_id
                  ORDER BY s."order" ASC, s.id ASC
                  LIMIT 1
              )
            """
        )
    )

    # 3. Та же эвристика для standings.
    conn.execute(
        sa.text(
            """
            UPDATE tournament.standing st
            SET stage_item_id = si.id
            FROM tournament.stage_item si
            WHERE st.stage_id IS NOT NULL
              AND st.stage_item_id IS NULL
              AND si.stage_id = st.stage_id
              AND si.id = (
                  SELECT s.id FROM tournament.stage_item s
                  WHERE s.stage_id = st.stage_id
                  ORDER BY s."order" ASC, s.id ASC
                  LIMIT 1
              )
            """
        )
    )

    # 4. Standing.group_id → nullable. Старые записи оставляем, новые могут
    #    жить без compat-группы.
    op.alter_column(
        "standing",
        "group_id",
        existing_type=sa.BigInteger(),
        nullable=True,
        schema="tournament",
    )

    # 5. Меняем UNIQUE constraint: (tournament_id, group_id, team_id) →
    #    stage-aware unique.
    op.execute(
        'ALTER TABLE tournament.standing '
        'DROP CONSTRAINT IF EXISTS standing_tournament_id_group_id_team_id_key'
    )
    op.execute(
        'ALTER TABLE tournament.standing '
        'DROP CONSTRAINT IF EXISTS uq_standing_tournament_group_team'
    )
    # COALESCE чтобы NULL stage_item_id не давал дубликаты среди разных групп
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_tournament_stage_item_team
        ON tournament.standing (
            tournament_id,
            stage_id,
            COALESCE(stage_item_id, 0),
            team_id
        )
        """
    )

    # 6. Дополнительный sanity index для публичной сетки (stage_item -> encounters)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_encounter_stage_item_round
        ON tournament.encounter (stage_item_id, round)
        """
    )


def downgrade() -> None:
    op.execute(
        'DROP INDEX IF EXISTS tournament.ix_encounter_stage_item_round'
    )
    op.execute(
        'DROP INDEX IF EXISTS tournament.uq_standing_tournament_stage_item_team'
    )

    # Восстанавливаем старый UNIQUE. Если в данных есть конфликты с nullable
    # group_id, миграция вниз упадёт — это ожидаемо.
    op.execute(
        """
        ALTER TABLE tournament.standing
        ADD CONSTRAINT standing_tournament_id_group_id_team_id_key
        UNIQUE (tournament_id, group_id, team_id)
        """
    )

    op.alter_column(
        "standing",
        "group_id",
        existing_type=sa.BigInteger(),
        nullable=False,
        schema="tournament",
    )
