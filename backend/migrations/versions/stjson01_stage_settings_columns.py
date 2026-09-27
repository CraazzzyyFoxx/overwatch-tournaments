"""Stage regulation in typed columns; ``tournament.stage.settings_json`` dropped.

Revision ID: stjson01
Revises: stpin01

``settings_json`` mixed three things in one free-form blob: the organizer's
regulation, the Swiss generator's own bookkeeping, and the Challonge group link.
A form round-tripping the blob could roll back what the engine wrote there,
nothing constrained a value until the engine choked on it mid-tournament, and a
bye pointing at a deleted team stayed forever. Each key now has a home:

- regulation -> ``stage`` columns: ``ranking_preset``, ``tiebreak_order``
  (text[]), ``win_points``/``draw_points``/``loss_points`` (NULL = the
  tournament's), ``swiss_bye_points``, ``de_grand_final_type``, ``seed_ranking``,
  ``best_of_default``/``best_of_final`` plus ``stage_round_best_of`` rows, and
  ``ffa_placement_points`` (float8[]) / ``ffa_score_points`` / ``ffa_score_label``;
- Swiss bookkeeping -> ``swiss_bye`` and ``swiss_stopped_scope`` rows, with
  foreign keys to the stage, the stage item and the team;
- ``challonge_group_id`` -> a ``stage`` column;
- the legacy advance-count keys (``advance_count``/``advanceCount``/``top``)
  fill ``stage.advance_count`` where that column is still NULL, which is the
  precedence the frontend read them with.

Values are carried over exactly as the engine read them: a malformed value the
engine ignored is dropped, not repaired. Top-level keys no reader ever knew are
logged by stage id and dropped with the column.

``downgrade()`` rebuilds the blob from the columns and rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "stjson01"
down_revision: str | Sequence[str] | None = "stpin01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KNOWN_KEYS = frozenset(
    {
        "ranking_preset",
        "tiebreak_order",
        "scoring",
        "swiss_bye_points",
        "de_grand_final_type",
        "seed_ranking",
        "best_of",
        "ffa_scoring",
        "challonge_group_id",
        "swiss_byes",
        "swiss_stopped_scopes",
        "advance_count",
        "advanceCount",
        "top",
    }
)

#: ``settings_json`` as jsonb, ``{}`` for NULL or anything that is not an object.
_S = "(CASE WHEN json_typeof(st.settings_json) = 'object' THEN st.settings_json::jsonb ELSE '{}'::jsonb END)"

# PostgreSQL does not promise to evaluate ``a AND b`` left to right, so every
# cast below sits behind the CASE branch that proved it safe: CASE is the one
# construct whose evaluation order is defined.


def _obj(expr: str) -> str:
    return f"(CASE WHEN jsonb_typeof({expr}) = 'object' THEN {expr} ELSE '{{}}'::jsonb END)"


def _arr(expr: str) -> str:
    return f"(CASE WHEN jsonb_typeof({expr}) = 'array' THEN {expr} ELSE '[]'::jsonb END)"


def _number(expr: str) -> str:
    return f"(CASE WHEN jsonb_typeof({expr}) = 'number' THEN ({expr} #>> '{{}}')::float8 END)"


def _digits(text: str, cast: str, *, signed: bool = False, width: int = 18) -> str:
    """``text`` cast to ``cast`` when it is a plain integer literal, else NULL."""
    sign = "-?" if signed else ""
    return f"(CASE WHEN {text} ~ '^{sign}[0-9]{{1,{width}}}$' THEN ({text})::{cast} END)"


def _positive_int(expr: str) -> str:
    """A JSON integer >= 1 written without a fraction, as ``_coerce_positive_int`` accepted."""
    value = _digits(f"(CASE WHEN jsonb_typeof({expr}) = 'number' THEN {expr} #>> '{{}}' END)", "int", width=9)
    return f"(CASE WHEN {value} >= 1 THEN {value} END)"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    columns = [
        sa.Column("ranking_preset", sa.String(), nullable=True),
        sa.Column("tiebreak_order", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("win_points", sa.Float(), nullable=True),
        sa.Column("draw_points", sa.Float(), nullable=True),
        sa.Column("loss_points", sa.Float(), nullable=True),
        sa.Column("swiss_bye_points", sa.Float(), nullable=True),
        sa.Column("de_grand_final_type", sa.String(16), nullable=False, server_default="no_reset"),
        sa.Column("seed_ranking", sa.String(16), nullable=False, server_default="slot"),
        sa.Column("best_of_default", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("best_of_final", sa.Integer(), nullable=True),
        sa.Column("ffa_placement_points", postgresql.ARRAY(sa.Float()), nullable=False, server_default="{}"),
        sa.Column("ffa_score_points", sa.Float(), nullable=False, server_default="1"),
        sa.Column("ffa_score_label", sa.String(32), nullable=True),
        sa.Column("challonge_group_id", sa.BigInteger(), nullable=True),
    ]
    for column in columns:
        op.add_column("stage", column, schema="tournament")
    op.create_check_constraint(
        "ck_stage_de_grand_final_type",
        "stage",
        "de_grand_final_type IN ('no_reset', 'with_reset')",
        schema="tournament",
    )
    op.create_check_constraint(
        "ck_stage_seed_ranking",
        "stage",
        "seed_ranking IN ('slot', 'avg_sr', 'total_sr', 'random')",
        schema="tournament",
    )
    op.create_check_constraint("ck_stage_best_of_default", "stage", "best_of_default >= 1", schema="tournament")
    op.create_check_constraint(
        "ck_stage_best_of_final", "stage", "best_of_final IS NULL OR best_of_final >= 1", schema="tournament"
    )
    op.create_check_constraint("ck_stage_ffa_score_points", "stage", "ffa_score_points >= 0", schema="tournament")

    op.create_table(
        "stage_round_best_of",
        sa.Column("stage_id", sa.BigInteger(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("best_of", sa.Integer(), nullable=False),
        sa.CheckConstraint("best_of >= 1", name="ck_stage_round_best_of_best_of"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("stage_id", "round"),
        schema="tournament",
    )
    op.create_table(
        "swiss_bye",
        *_timestamps(),
        sa.Column("stage_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_item_id", sa.BigInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_item_id"], ["tournament.stage_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    op.create_index("ix_tournament_swiss_bye_stage_id", "swiss_bye", ["stage_id"], schema="tournament")
    op.create_index("ix_tournament_swiss_bye_team_id", "swiss_bye", ["team_id"], schema="tournament")
    op.create_table(
        "swiss_stopped_scope",
        *_timestamps(),
        sa.Column("stage_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_item_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_item_id"], ["tournament.stage_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    op.create_index(
        "uq_swiss_stopped_scope",
        "swiss_stopped_scope",
        ["stage_id", "stage_item_id"],
        unique=True,
        schema="tournament",
        postgresql_nulls_not_distinct=True,
    )

    _report_unknown_keys()
    _move_regulation()
    _move_swiss_state()
    op.drop_column("stage", "settings_json", schema="tournament")


def _report_unknown_keys() -> None:
    rows = (
        op.get_bind()
        .execute(sa.text(f"SELECT st.id, key FROM tournament.stage st, jsonb_object_keys({_S}) AS key ORDER BY 1, 2"))
        .all()
    )
    unknown = [(stage_id, key) for stage_id, key in rows if key not in KNOWN_KEYS]
    if unknown:
        print(f"stjson01: dropping settings_json keys no reader used, as (stage_id, key): {unknown}")


def _move_regulation() -> None:
    scoring = _obj(f"{_S} -> 'scoring'")
    best_of = _obj(f"{_S} -> 'best_of'")
    ffa = _obj(f"{_S} -> 'ffa_scoring'")
    tiebreak = _arr(f"{_S} -> 'tiebreak_order'")
    placement = _arr(f"{ffa} -> 'placement_points'")
    legacy_advance = ", ".join(_positive_int(f"{_S} -> '{key}'") for key in ("advance_count", "advanceCount", "top"))
    op.execute(
        f"""
        UPDATE tournament.stage st SET
            ranking_preset = CASE WHEN jsonb_typeof({_S} -> 'ranking_preset') = 'string'
                THEN NULLIF({_S} ->> 'ranking_preset', '') END,
            tiebreak_order = CASE WHEN jsonb_typeof({_S} -> 'tiebreak_order') = 'array' THEN ARRAY(
                SELECT e.metric #>> '{{}}'
                FROM jsonb_array_elements({tiebreak}) WITH ORDINALITY AS e(metric, ord)
                WHERE jsonb_typeof(e.metric) = 'string'
                ORDER BY e.ord
            ) END,
            win_points = {_number(f"{scoring} -> 'win'")},
            draw_points = {_number(f"{scoring} -> 'draw'")},
            loss_points = {_number(f"{scoring} -> 'loss'")},
            swiss_bye_points = {_number(f"{_S} -> 'swiss_bye_points'")},
            de_grand_final_type = CASE WHEN {_S} ->> 'de_grand_final_type' = 'with_reset'
                THEN 'with_reset' ELSE 'no_reset' END,
            seed_ranking = CASE WHEN {_S} ->> 'seed_ranking' IN ('avg_sr', 'total_sr', 'random')
                THEN {_S} ->> 'seed_ranking' ELSE 'slot' END,
            best_of_default = COALESCE({_positive_int(f"{best_of} -> 'default'")}, 3),
            best_of_final = {_positive_int(f"{best_of} -> 'final'")},
            ffa_placement_points = ARRAY(
                SELECT {_number("e.points")}
                FROM jsonb_array_elements({placement}) WITH ORDINALITY AS e(points, ord)
                WHERE jsonb_typeof(e.points) = 'number'
                ORDER BY e.ord
            ),
            ffa_score_points = COALESCE({_number(f"{ffa} -> 'score_points'")}, 1),
            ffa_score_label = CASE WHEN jsonb_typeof({ffa} -> 'score_label') = 'string'
                THEN left({ffa} ->> 'score_label', 32) END,
            challonge_group_id = {_digits(f"({_S} ->> 'challonge_group_id')", "bigint")},
            advance_count = COALESCE(st.advance_count, {legacy_advance})
        WHERE st.settings_json IS NOT NULL
        """
    )
    by_round = _obj(f"{best_of} -> 'by_round'")
    op.execute(
        f"""
        INSERT INTO tournament.stage_round_best_of (stage_id, round, best_of)
        SELECT st.id, parsed.round, parsed.best_of
        FROM tournament.stage st
        CROSS JOIN LATERAL jsonb_each({by_round}) AS kv(key, value)
        CROSS JOIN LATERAL (
            SELECT {_digits("kv.key", "int", signed=True, width=6)}, {_positive_int("kv.value")}
        ) AS parsed(round, best_of)
        WHERE parsed.round IS NOT NULL AND parsed.best_of IS NOT NULL
        """
    )


def _move_swiss_state() -> None:
    byes = _obj(f"{_S} -> 'swiss_byes'")
    op.execute(
        f"""
        INSERT INTO tournament.swiss_bye (stage_id, stage_item_id, team_id, round)
        SELECT st.id, ids.stage_item_id, ids.team_id, ids.round
        FROM tournament.stage st
        CROSS JOIN LATERAL jsonb_each({byes}) AS scope(key, value)
        CROSS JOIN LATERAL jsonb_array_elements({_arr("scope.value")}) WITH ORDINALITY AS e(raw, ord)
        CROSS JOIN LATERAL (
            SELECT CASE WHEN jsonb_typeof(e.raw) = 'object' THEN e.raw ->> 'team_id' ELSE e.raw #>> '{{}}' END,
                   CASE WHEN jsonb_typeof(e.raw) = 'object' THEN e.raw ->> 'round' END
        ) AS entry(team_text, round_text)
        CROSS JOIN LATERAL (
            SELECT {_digits("scope.key", "bigint")},
                   {_digits("entry.team_text", "bigint")},
                   {_digits("entry.round_text", "int", signed=True, width=6)}
        ) AS ids(stage_item_id, team_id, round)
        WHERE EXISTS (SELECT 1 FROM tournament.team t WHERE t.id = ids.team_id)
          AND (
              scope.key = 'stage'
              OR EXISTS (
                  SELECT 1 FROM tournament.stage_item i WHERE i.id = ids.stage_item_id AND i.stage_id = st.id
              )
          )
        ORDER BY st.id, scope.key, e.ord
        """
    )
    stopped = _arr(f"{_S} -> 'swiss_stopped_scopes'")
    op.execute(
        f"""
        INSERT INTO tournament.swiss_stopped_scope (stage_id, stage_item_id)
        SELECT DISTINCT st.id, {_digits("scope", "bigint")}
        FROM tournament.stage st, jsonb_array_elements_text({stopped}) AS scope
        WHERE scope = 'stage'
           OR EXISTS (
               SELECT 1 FROM tournament.stage_item i WHERE i.id = {_digits("scope", "bigint")} AND i.stage_id = st.id
           )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.add_column("stage", sa.Column("settings_json", sa.JSON(), nullable=True), schema="tournament")
    op.execute(
        """
        UPDATE tournament.stage st SET settings_json = NULLIF(jsonb_strip_nulls(jsonb_build_object(
            'ranking_preset', st.ranking_preset,
            'tiebreak_order', to_jsonb(st.tiebreak_order),
            'scoring', NULLIF(jsonb_strip_nulls(jsonb_build_object(
                'win', st.win_points, 'draw', st.draw_points, 'loss', st.loss_points
            )), '{}'::jsonb),
            'swiss_bye_points', st.swiss_bye_points,
            'de_grand_final_type', CASE WHEN st.stage_type = 'double_elimination' THEN st.de_grand_final_type END,
            'seed_ranking', NULLIF(st.seed_ranking, 'slot'),
            'best_of', jsonb_build_object(
                'default', st.best_of_default,
                'by_round', COALESCE(
                    (SELECT jsonb_object_agg(r.round::text, r.best_of)
                     FROM tournament.stage_round_best_of r WHERE r.stage_id = st.id),
                    '{}'::jsonb
                ),
                'final', st.best_of_final
            ),
            'ffa_scoring', CASE WHEN st.stage_type = 'ffa_league' THEN jsonb_build_object(
                'placement_points', to_jsonb(st.ffa_placement_points),
                'score_points', st.ffa_score_points,
                'score_label', st.ffa_score_label
            ) END,
            'challonge_group_id', st.challonge_group_id,
            'swiss_byes', (
                SELECT jsonb_object_agg(grouped.scope, grouped.entries)
                FROM (
                    SELECT COALESCE(b.stage_item_id::text, 'stage') AS scope,
                           jsonb_agg(
                               CASE WHEN b.round IS NULL THEN to_jsonb(b.team_id)
                                    ELSE jsonb_build_object('round', b.round, 'team_id', b.team_id) END
                               ORDER BY b.id
                           ) AS entries
                    FROM tournament.swiss_bye b WHERE b.stage_id = st.id
                    GROUP BY 1
                ) grouped
            ),
            'swiss_stopped_scopes', (
                SELECT jsonb_agg(COALESCE(s.stage_item_id::text, 'stage'))
                FROM tournament.swiss_stopped_scope s WHERE s.stage_id = st.id
            )
        )), '{}'::jsonb)::json
        """
    )
    op.drop_index("uq_swiss_stopped_scope", table_name="swiss_stopped_scope", schema="tournament")
    op.drop_table("swiss_stopped_scope", schema="tournament")
    op.drop_index("ix_tournament_swiss_bye_team_id", table_name="swiss_bye", schema="tournament")
    op.drop_index("ix_tournament_swiss_bye_stage_id", table_name="swiss_bye", schema="tournament")
    op.drop_table("swiss_bye", schema="tournament")
    op.drop_table("stage_round_best_of", schema="tournament")
    for name in (
        "ck_stage_ffa_score_points",
        "ck_stage_best_of_final",
        "ck_stage_best_of_default",
        "ck_stage_seed_ranking",
        "ck_stage_de_grand_final_type",
    ):
        op.drop_constraint(name, "stage", schema="tournament")
    for column in (
        "challonge_group_id",
        "ffa_score_label",
        "ffa_score_points",
        "ffa_placement_points",
        "best_of_final",
        "best_of_default",
        "seed_ranking",
        "de_grand_final_type",
        "swiss_bye_points",
        "loss_points",
        "draw_points",
        "win_points",
        "tiebreak_order",
        "ranking_preset",
    ):
        op.drop_column("stage", column, schema="tournament")
