"""migrate_achievement_data

Revision ID: k1f3g5h9i0j1
Revises: j0e2f4g8h9i0
Create Date: 2026-04-09 23:00:00.000000

Migrates existing Achievement + AchievementUser data into
AchievementRule + AchievementEvaluationResult.

Strategy:
- Seed each workspace with default rules via the seeder
- Map old achievement.slug → new rule.slug (per workspace)
- Copy AchievementUser rows → AchievementEvaluationResult
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "k1f3g5h9i0j1"
down_revision: Union[str, None] = "j0e2f4g8h9i0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Find all workspace IDs that have tournaments with achievements
    workspace_ids = conn.execute(
        sa.text("""
            SELECT DISTINCT t.workspace_id
            FROM achievements."user" au
            JOIN tournament.tournament t ON t.id = au.tournament_id
            WHERE au.tournament_id IS NOT NULL

            UNION

            SELECT DISTINCT w.id
            FROM workspace w
        """)
    ).scalars().all()

    if not workspace_ids:
        return

    # Step 2: Seed rules from existing achievements via SQL.
    # For each workspace, create a rule per old achievement, with a placeholder condition_tree.
    # The admin can later update condition trees via the UI.
    conn.execute(
        sa.text("""
            INSERT INTO achievements.rule (
                workspace_id, slug, name, description_ru, description_en,
                image_url, hero_id, category, scope, grain,
                condition_tree, depends_on, enabled, rule_version,
                created_at
            )
            SELECT
                w.id as workspace_id,
                a.slug,
                a.name,
                a.description_ru,
                a.description_en,
                a.image_url,
                a.hero_id,
                'overall' as category,
                'global' as scope,
                'user' as grain,
                '{"type": "tournament_count", "params": {"op": ">=", "value": 1}}'::jsonb as condition_tree,
                '[]'::jsonb as depends_on,
                true as enabled,
                1 as rule_version,
                NOW() as created_at
            FROM achievements.achievement a
            CROSS JOIN workspace w
            WHERE NOT EXISTS (
                SELECT 1 FROM achievements.rule r
                WHERE r.workspace_id = w.id AND r.slug = a.slug
            )
        """)
    )

    # Step 3: Migrate AchievementUser → AchievementEvaluationResult.
    # Map old achievement_id → new rule.id via slug matching + workspace from tournament.
    conn.execute(
        sa.text("""
            INSERT INTO achievements.evaluation_result (
                achievement_rule_id, user_id, tournament_id, match_id,
                qualified_at, evidence_json, rule_version, run_id,
                created_at
            )
            SELECT
                r.id as achievement_rule_id,
                au.user_id,
                au.tournament_id,
                au.match_id,
                au.created_at as qualified_at,
                jsonb_build_object('migrated_from', 'achievement_user', 'old_id', au.id) as evidence_json,
                1 as rule_version,
                NULL as run_id,
                au.created_at
            FROM achievements."user" au
            JOIN achievements.achievement a ON a.id = au.achievement_id
            JOIN achievements.rule r ON r.slug = a.slug
            LEFT JOIN tournament.tournament t ON t.id = au.tournament_id
            WHERE r.workspace_id = COALESCE(t.workspace_id, (SELECT MIN(id) FROM workspace))
            AND NOT EXISTS (
                SELECT 1 FROM achievements.evaluation_result er
                WHERE er.achievement_rule_id = r.id
                  AND er.user_id = au.user_id
                  AND COALESCE(er.tournament_id, 0) = COALESCE(au.tournament_id, 0)
                  AND COALESCE(er.match_id, 0) = COALESCE(au.match_id, 0)
            )
        """)
    )


def downgrade() -> None:
    # Remove migrated data (evaluation_results with migration evidence)
    op.execute(
        sa.text("""
            DELETE FROM achievements.evaluation_result
            WHERE evidence_json->>'migrated_from' = 'achievement_user'
        """)
    )
    # Remove seeded rules (those created during migration)
    op.execute(
        sa.text("""
            DELETE FROM achievements.rule
            WHERE rule_version = 1
        """)
    )
