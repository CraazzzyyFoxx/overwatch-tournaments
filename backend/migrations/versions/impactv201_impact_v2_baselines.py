"""impact_v2: per-hero baselines; drop the impact_v1 baselines and the legacy performance facts.

Revision ID: impactv201
Revises: tidx01
Create Date: 2026-10-31 00:00:00.000000

Design: ``docs/superpowers/specs/2026-10-31-mvp-impact-v2-design.md`` (§4 storage, §6 contracts C6).

* ``stats.stat_baseline.entity_id`` (nullable, ``catalog.entity``): a hero's own baseline row. The unique key gains it
  (``NULLS NOT DISTINCT``, so a role row, entity NULL, stays unique).
* Deletes the ``impact_v1`` baselines (v2 reads only its own version; recompute writes them).
* Deletes the Overwatch ``performance`` / ``performance_points`` facts (R2.Q6: the legacy MVP is gone). The ``stat_def``
  rows stay: ``project_disciplines`` deactivates the codes the discipline no longer declares.

Both deletes are out-of-band for ``stats_evidence``: its evidence is captured per operation (before/after inside one
transaction), so no stored baseline of the removed rows exists to contradict. The impact facts of the other codes are
rewritten by ``backfill_impact.py`` after the baselines are recomputed (design §8).

Downgrade restores the schema only: deleted rows do not come back, and hero rows go because the old key cannot hold
them.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "impactv201"
down_revision: str | Sequence[str] | None = "tidx01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DELETE FROM stats.stat_baseline WHERE formula_version = 'impact_v1'")
    op.execute(
        """
        DELETE FROM stats.fact f USING stats.stat_def d
        WHERE d.id = f.stat_id AND d.discipline = 'overwatch' AND d.code IN ('performance', 'performance_points')
        """
    )
    op.execute(
        """
        ALTER TABLE stats.stat_baseline
          ADD COLUMN entity_id BIGINT,
          ADD CONSTRAINT fk_stat_baseline_entity FOREIGN KEY (entity_id)
            REFERENCES catalog.entity (id) DEFERRABLE INITIALLY DEFERRED,
          DROP CONSTRAINT uq_stat_baseline,
          ADD CONSTRAINT uq_stat_baseline UNIQUE NULLS NOT DISTINCT (formula_version, role_id, rank_bucket, stat_id, entity_id)
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM stats.stat_baseline WHERE entity_id IS NOT NULL")
    op.execute(
        """
        ALTER TABLE stats.stat_baseline
          DROP CONSTRAINT uq_stat_baseline,
          ADD CONSTRAINT uq_stat_baseline UNIQUE (formula_version, role_id, rank_bucket, stat_id),
          DROP CONSTRAINT fk_stat_baseline_entity,
          DROP COLUMN entity_id
        """
    )
