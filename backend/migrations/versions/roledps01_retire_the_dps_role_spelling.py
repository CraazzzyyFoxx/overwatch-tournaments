"""Retire the ``dps`` spelling of the damage role from stored data.

Revision ID: roledps01
Revises: quota0002
Create Date: 2026-09-18 00:00:00.000000

The project has one role vocabulary, ``HeroClass`` (``tank``/``damage``/
``support``/``flex``). Draft, balancer and registration used to persist the
damage role as ``dps`` -- a second spelling exposed through
``HeroClass.slot_code`` and tolerated on read in half a dozen places. The code
side of that spelling is gone; this migration moves the data with it, so there
is no reader left that would accept ``dps``.

Two shapes are rewritten:

* **Role columns** -- a ``String(16)`` holding the slot code directly.
* **JSON documents** -- role codes appear as object KEYS (``role_mask``,
  ``roster_slots_json``, ``all_ratings``, ``all_discomforts``, ``roster``,
  ``mix_role_weights``, ``by_role``), as array ELEMENTS
  (``role_preferences``), as solver knob names (``dps_impact_weight``) and as
  Google-Sheets mapping target keys (``roles.dps.rank_value``). Rather than
  enumerate every path of every document version ever written, a recursive
  rewriter walks the whole document and retires the token wherever it sits.

The token rule is deliberately narrow -- ``dps`` only as a whole
dot/underscore-delimited segment:

    dps                     -> damage
    dps_impact_weight       -> damage_impact_weight
    roles.dps.rank_value    -> roles.damage.rank_value

Display spellings (``"Damage"``, ``"DPS"``) are left alone: legacy masks saved
with capitalised role names still resolve through
``resolve_input_role_name``, and ``DPS`` is user-facing English copy.

Known and accepted false positive: a free-text value that is *exactly* ``dps``
-- a player nicknamed "dps" inside an old ``result_json``, say -- is rewritten
too. The alternative is a hand-listed path inventory across every historical
document version, where one missed path silently loses a role. A cosmetic
rename inside a stored result beats a role the solver can no longer read.

Scope note, following ``owemerald01``: the audit journals ARE included here,
unlike the rank rebase which deliberately left tournament history alone. The
difference is that a journal's role codes are read back and displayed next to
live ones, so a journal still saying ``dps`` would be the only place in the
product where that word survives. Nothing parses those blobs, so rewriting them
changes no behaviour.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "roledps01"
down_revision: str | Sequence[str] | None = "quota0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``(table, column)`` holding a bare slot code. Unqualified names resolve
#: through ``search_path`` (they live in the default schema).
ROLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("balancer.registration_role", "role"),
    ("balancer.team_slot", "role"),
    ("balancer.member_rank", "role"),
    ("balancer.custom_game_player_role", "role"),
    ("balancer.draft_pick", "target_role"),
)

#: ``(table, column)`` of every JSON/JSONB document that can carry a role code.
#: ``balancer.draft_player`` is absent on purpose -- it deliberately holds no
#: role (see its model docstring), the role lives on ``draft_pick``.
JSON_COLUMNS: tuple[tuple[str, str], ...] = (
    ("tournament.tournament", "roster_slots_json"),
    ("workspace", "default_roster_slots_json"),
    ("balancer.tournament_config", "config_json"),
    ("balancer.workspace_config", "config_json"),
    ("balancer.user_config", "config_json"),
    ("balancer.user_config", "role_slots_json"),
    ("balancer.balance", "config_json"),
    ("balancer.balance", "result_json"),
    ("balancer.balance_variant", "statistics_json"),
    ("balancer.custom_game", "balance_result_json"),
    ("balancer.draft_session", "settings_json"),
    ("balancer.draft_audit_event", "before_json"),
    ("balancer.draft_audit_event", "after_json"),
    ("balancer.registration_form", "built_in_fields_json"),
    ("balancer.registration_google_sheet_feed", "mapping_config_json"),
    ("balancer.registration_google_sheet_feed", "value_mapping_json"),
    ("balancer.registration_google_sheet_binding", "parsed_fields_json"),
    ("audit_log", "before_json"),
    ("audit_log", "after_json"),
)

# ``@`` as the LIKE escape so the pattern carries no backslash through Python.
_CREATE_REWRITER = """
CREATE FUNCTION public._retire_dps_token(token text) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT CASE
        WHEN token = 'dps' THEN 'damage'
        WHEN token LIKE 'dps@_%' ESCAPE '@' THEN 'damage' || substr(token, 4)
        WHEN token LIKE '%.dps.%' THEN replace(token, '.dps.', '.damage.')
        ELSE token
    END
$fn$;

CREATE FUNCTION public._retire_dps_document(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT CASE jsonb_typeof(value)
        WHEN 'object' THEN COALESCE(
            (
                SELECT jsonb_object_agg(
                    public._retire_dps_token(entry.key),
                    public._retire_dps_document(entry.value)
                )
                FROM jsonb_each(value) AS entry(key, value)
            ),
            '{}'::jsonb
        )
        WHEN 'array' THEN COALESCE(
            (
                SELECT jsonb_agg(public._retire_dps_document(element.value))
                FROM jsonb_array_elements(value) AS element(value)
            ),
            '[]'::jsonb
        )
        WHEN 'string' THEN to_jsonb(public._retire_dps_token(value #>> '{}'))
        ELSE value
    END
$fn$;
"""

_DROP_REWRITER = """
DROP FUNCTION IF EXISTS public._retire_dps_document(jsonb);
DROP FUNCTION IF EXISTS public._retire_dps_token(text);
"""

_COLUMN_TYPE = sa.text(
    """
    SELECT format_type(attr.atttypid, NULL)
    FROM pg_attribute AS attr
    WHERE attr.attrelid = to_regclass(:table)
      AND attr.attname = :column
      AND attr.attnum > 0
      AND NOT attr.attisdropped
    """
)


def upgrade() -> None:
    connection = op.get_bind()

    for table, column in ROLE_COLUMNS:
        if connection.execute(sa.text("SELECT to_regclass(:table)"), {"table": table}).scalar() is None:
            continue
        op.execute(f"UPDATE {table} SET \"{column}\" = 'damage' WHERE \"{column}\" = 'dps'")

    op.execute(_CREATE_REWRITER)
    try:
        for table, column in JSON_COLUMNS:
            # ``format_type`` rather than a hand-kept json/jsonb table: the
            # rewriter speaks jsonb and the value has to go back as whatever the
            # column actually is, and half of these columns are plain ``json``.
            column_type = connection.execute(_COLUMN_TYPE, {"table": table, "column": column}).scalar()
            if column_type is None:
                continue
            # The LIKE guard keeps this off every untouched row -- ``audit_log``
            # is the biggest table in the schema and almost none of it is roles.
            op.execute(
                f'UPDATE {table} SET "{column}" = '
                f'public._retire_dps_document("{column}"::jsonb)::text::{column_type} '
                f"WHERE \"{column}\"::text LIKE '%dps%'"
            )
    finally:
        op.execute(_DROP_REWRITER)


def downgrade() -> None:
    raise NotImplementedError(
        "roledps01 is one-way: after it, a stored 'damage' no longer says whether it "
        "was written as 'dps' (a slot code) or as 'damage' (the canonical HeroClass "
        "name, which audit snapshots of tournament.player.role already held). "
        "Reversing would rewrite the latter into a spelling they never had. "
        "Restore a pre-migration backup or roll forward."
    )
