"""The tournament-composite foreign keys become ``DEFERRABLE INITIALLY IMMEDIATE`` for the league merge.

Revision ID: flowP6_01_deferrable_fks
Revises: flowP4_01_source_result
Create Date: 2026-11-06 12:00:00.000000

The league merge (spec 15.3 step 3) re-points a day's encounters, ``encounter.team`` seats, teams, stages and bracket
rows to the target tournament in one transaction. ``encounter.team`` references both ``encounter.encounter (id,
tournament_id)`` and ``tournament.team (id, tournament_id)``, so no statement order satisfies immediate checks; the six
composite FKs that copy ``tournament_id`` must be deferrable for ``SET CONSTRAINTS ALL DEFERRED`` to matter.

Initially immediate: every other writer keeps today's behaviour. Re-adding validates; every row was validated by
``enclayer01``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "flowP6_01_deferrable_fks"
down_revision: str | Sequence[str] | None = "flowP4_01_source_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace(deferral: str) -> str:
    return f"""
    ALTER TABLE encounter.team
      DROP CONSTRAINT fk_team_encounter_tournament,
      DROP CONSTRAINT fk_team_source,
      ADD CONSTRAINT fk_team_encounter_tournament FOREIGN KEY (encounter_id, tournament_id)
        REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE {deferral},
      ADD CONSTRAINT fk_team_source FOREIGN KEY (team_id, tournament_id)
        REFERENCES tournament.team (id, tournament_id) ON DELETE SET NULL (team_id) {deferral};
    ALTER TABLE tournament.bracket_encounter
      DROP CONSTRAINT fk_bracket_encounter,
      DROP CONSTRAINT fk_bracket_stage,
      ADD CONSTRAINT fk_bracket_encounter FOREIGN KEY (encounter_id, tournament_id)
        REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE {deferral},
      ADD CONSTRAINT fk_bracket_stage FOREIGN KEY (stage_id, tournament_id)
        REFERENCES tournament.stage (id, tournament_id) ON DELETE SET NULL (stage_id) {deferral};
    ALTER TABLE tournament.encounter_link
      DROP CONSTRAINT fk_link_source,
      DROP CONSTRAINT fk_link_target,
      ADD CONSTRAINT fk_link_source FOREIGN KEY (source_encounter_id, tournament_id)
        REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE {deferral},
      ADD CONSTRAINT fk_link_target FOREIGN KEY (target_encounter_id, tournament_id)
        REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE {deferral};
    """


def upgrade() -> None:
    op.execute(_replace("DEFERRABLE INITIALLY IMMEDIATE"))


def downgrade() -> None:
    op.execute(_replace(""))
