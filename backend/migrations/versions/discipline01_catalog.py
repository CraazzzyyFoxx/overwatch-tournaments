"""The catalog of every discipline (V3 P1; D84, D85, D101, spec §14.2).

``catalog.entity`` replaces ``overwatch.hero/map/gamemode`` with new ids, ``catalog.alias_miss`` replaces
``overwatch.catalog_alias_miss``, ``catalog.entity_legacy`` maps the old ids for the reconcile and the redirect of old
URLs. New ids start above every id the three legacy tables ever issued (their sequences AND their maxima): an old id
and a new id never coincide, so a hard reference left unrewritten fails its new FK and a soft one left behind shows in
``scripts/discipline01_reconcile.sql``.

``overwatch.*`` stays until the gated ``discipline02``. Forward-fix only.

Revision ID: discipline01
Revises: mixround01
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "discipline01"
down_revision: str | Sequence[str] | None = "mixround01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: SQL twin of the map slug rule (``re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "map"``, which
#: also names every mirrored map image). Copied, not imported: a migration keeps meaning what it meant when it ran.
MAP_SLUG = "coalesce(nullif(btrim(regexp_replace(lower(btrim(m.name)), '[^a-z0-9]+', '-', 'g'), '-'), ''), 'map')"

#: Questions the data must answer before anything moves; a non-empty answer stops the revision (spec §14.5).
#: Kept text for text in backend/scripts/discipline01_preflight.sql (tests/test_discipline01_preflight_sql.py).
PREFLIGHT: tuple[tuple[str, str], ...] = (
    (
        "maps whose names collide after slugify",
        f"""
        SELECT s.slug, array_agg(s.id ORDER BY s.id) AS map_ids, array_agg(s.name ORDER BY s.id) AS names
          FROM (SELECT m.id, m.name, {MAP_SLUG} AS slug FROM overwatch.map m) s
         GROUP BY s.slug
        HAVING count(*) > 1
         ORDER BY s.slug
        """,
    ),
    (
        "catalog values too long",
        f"""
        SELECT v.legacy_kind, v.legacy_id, v.field, v.value_length
          FROM (
            SELECT 'hero' AS legacy_kind, h.id AS legacy_id, 'slug' AS field,
                   char_length(h.slug) AS value_length, 64 AS max_length FROM overwatch.hero h
            UNION ALL
            SELECT 'gamemode', g.id, 'slug', char_length(g.slug), 64 FROM overwatch.gamemode g
            UNION ALL
            SELECT 'map', m.id, 'slug', char_length({MAP_SLUG}), 64 FROM overwatch.map m
            UNION ALL
            SELECT 'hero', h.id, 'name', char_length(h.name), 128 FROM overwatch.hero h
            UNION ALL
            SELECT 'gamemode', g.id, 'name', char_length(g.name), 128 FROM overwatch.gamemode g
            UNION ALL
            SELECT 'map', m.id, 'name', char_length(m.name), 128 FROM overwatch.map m
          ) v
         WHERE v.value_length > v.max_length
         ORDER BY v.legacy_kind, v.legacy_id, v.field
        """,
    ),
)
PREFLIGHT_SAMPLE = 20

#: Not a stop: a soft id naming no legacy row (its map or hero was deleted) is left as it is. It lies below every
#: new id, so it can never come to name an entity, and the reconcile does not count it as uncarried.
DANGLING_PICK_BAN_IDS = """
SELECT count(*) AS dangling_pick_ban_ids
  FROM (SELECT c.kind::text AS kind, i.item_id::bigint AS item_id
          FROM tournament.pick_ban_config_item i JOIN tournament.pick_ban_config c ON c.id = i.pick_ban_config_id
        UNION ALL
        SELECT c.kind::text, si.item_id
          FROM tournament.pick_ban_config_slot_item si
          JOIN tournament.pick_ban_config_slot sl ON sl.id = si.pick_ban_config_slot_id
          JOIN tournament.pick_ban_config c ON c.id = sl.pick_ban_config_id
        UNION ALL
        SELECT c.kind::text, sl.reserve_item_id
          FROM tournament.pick_ban_config_slot sl JOIN tournament.pick_ban_config c ON c.id = sl.pick_ban_config_id
         WHERE sl.reserve_item_id IS NOT NULL
        UNION ALL
        SELECT s.kind::text, e.item_id
          FROM encounter.pick_ban_entry e JOIN encounter.pick_ban_session s ON s.id = e.session_id) x
 WHERE (x.kind = 'map' AND NOT EXISTS (SELECT 1 FROM overwatch.map m WHERE m.id = x.item_id))
    OR (x.kind = 'hero' AND NOT EXISTS (SELECT 1 FROM overwatch.hero h WHERE h.id = x.item_id))
"""


def _preflight() -> None:
    bind = op.get_bind()
    failures: list[str] = []
    for question, query in PREFLIGHT:
        rows = bind.execute(sa.text(query)).mappings().all()
        if rows:
            sample = "; ".join(str(dict(row)) for row in rows[:PREFLIGHT_SAMPLE])
            rest = len(rows) - PREFLIGHT_SAMPLE
            failures.append(f"{question} [{len(rows)}]: {sample}" + (f"; … {rest} more" if rest > 0 else ""))
    if failures:
        raise RuntimeError("discipline01 pre-flight failed; resolve these rows by hand first:\n" + "\n".join(failures))


#: Copied from enclayer01's name-agnostic DDL, generalized to PK/unique constraints too.
#: A restored live schema need not use the names assigned by the migration chain.
_CONSTRAINTS_ON = """
    SELECT c.conname FROM pg_constraint c
     WHERE c.conrelid = CAST(:table AS regclass) AND c.contype = :contype
       AND (:contype = 'p' OR
            ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                   ORDER BY k.ord) = CAST(:columns AS text[]))
     ORDER BY c.conname
"""
_PLAIN_INDEXES_ON = """
    SELECT ic.relname FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
     WHERE i.indrelid = CAST(:table AS regclass)
       AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
       AND ARRAY(SELECT a.attname::text FROM unnest(CAST(i.indkey AS int2[])) WITH ORDINALITY AS k(attnum, ord)
                   JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                  ORDER BY k.ord) = CAST(:columns AS text[])
     ORDER BY ic.relname
"""


def _name(table: str, columns: Sequence[str], contype: str) -> str:
    bind = op.get_bind()
    names = (
        bind.execute(
            sa.text(_PLAIN_INDEXES_ON if contype == "index" else _CONSTRAINTS_ON),
            {"table": table, "columns": list(columns), "contype": contype},
        )
        .scalars()
        .all()
    )
    if len(names) != 1:
        raise RuntimeError(f"discipline01 expected exactly one {contype} on {table}{tuple(columns)}, found {names}")
    return bind.dialect.identifier_preparer.quote(names[0])


def _drop_fks(table: str, *columns: str):
    def run() -> None:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {_name(table, columns, 'f')}")

    return run


def _rename_registration_objects() -> None:
    table = "balancer.registration_role_entity"
    sequence = (
        op.get_bind().execute(sa.text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table}).scalar_one()
    )
    op.execute(f"ALTER SEQUENCE {sequence} RENAME TO registration_role_entity_id_seq")
    for columns, contype, new in (
        ((), "p", "registration_role_entity_pkey"),
        (("role_id",), "f", "registration_role_entity_role_id_fkey"),
        (("role_id", "priority"), "u", "uq_reg_role_entity_role_priority"),
        (("role_id", "entity_id"), "u", "uq_reg_role_entity_role_entity"),
    ):
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {_name(table, columns, contype)} TO {new}")
    index = _name(table, ("role_id",), "index")
    op.execute(f"ALTER INDEX balancer.{index} RENAME TO ix_balancer_registration_role_entity_role_id")


def _retired_map(table: str, on_delete: str):
    def run() -> None:
        if op.get_bind().execute(sa.text("SELECT to_regclass(:table)"), {"table": table}).scalar_one() is None:
            return
        _drop_fks(table, "map_id")()
        op.execute(
            f"UPDATE {table} t SET map_id = l.entity_id FROM catalog.entity_legacy l"
            " WHERE l.legacy_kind = 'map' AND l.legacy_id = t.map_id"
        )
        op.execute(f"ALTER TABLE {table} ADD FOREIGN KEY (map_id) REFERENCES catalog.entity (id) ON DELETE {on_delete}")

    return run


_SCHEMA = (
    "INSERT INTO catalog.discipline (code, name) VALUES ('lol', 'League of Legends') ON CONFLICT (code) DO NOTHING",
    """
    CREATE TABLE catalog.entity (
      id          BIGSERIAL PRIMARY KEY,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ,
      discipline  VARCHAR(32) NOT NULL CONSTRAINT fk_entity_discipline REFERENCES catalog.discipline (code),
      kind        VARCHAR(16) NOT NULL,
      slug        VARCHAR(64) NOT NULL,
      name        VARCHAR(128) NOT NULL,
      image_path  VARCHAR,
      parent_id   BIGINT,
      attrs       JSONB NOT NULL DEFAULT '{}'::jsonb,
      aliases     JSONB NOT NULL DEFAULT '[]'::jsonb,
      active      BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_entity_kind CHECK (kind IN ('character', 'map', 'mode')),
      CONSTRAINT ck_entity_attrs CHECK (jsonb_typeof(attrs) = 'object'),
      CONSTRAINT ck_entity_aliases CHECK (jsonb_typeof(aliases) = 'array'),
      CONSTRAINT uq_entity_slug UNIQUE (discipline, kind, slug),
      CONSTRAINT uq_entity_name UNIQUE (discipline, kind, name),
      CONSTRAINT uq_entity_id_kind UNIQUE (id, kind),
      CONSTRAINT uq_entity_id_discipline UNIQUE (id, discipline),
      CONSTRAINT uq_entity_key UNIQUE (id, discipline, kind),
      CONSTRAINT fk_entity_parent FOREIGN KEY (parent_id, discipline) REFERENCES catalog.entity (id, discipline)
    )
    """,
    """
    CREATE TABLE catalog.alias_miss (
      id                 BIGSERIAL PRIMARY KEY,
      created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at         TIMESTAMPTZ,
      discipline         VARCHAR(32) NOT NULL CONSTRAINT fk_alias_miss_discipline REFERENCES catalog.discipline (code),
      kind               VARCHAR(16) NOT NULL CONSTRAINT ck_alias_miss_kind CHECK (kind IN ('character', 'map', 'mode')),
      raw_name           VARCHAR(128) NOT NULL,
      occurrences        INTEGER NOT NULL DEFAULT 1,
      first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_ingest_job_id BIGINT,
      resolved_at        TIMESTAMPTZ,
      CONSTRAINT uq_alias_miss UNIQUE (discipline, kind, raw_name)
    )
    """,
    """
    CREATE TABLE catalog.entity_legacy (
      legacy_kind VARCHAR(16) NOT NULL CONSTRAINT ck_entity_legacy_kind CHECK (legacy_kind IN ('hero', 'map', 'gamemode')),
      legacy_id   BIGINT NOT NULL,
      entity_id   BIGINT NOT NULL CONSTRAINT fk_entity_legacy_entity REFERENCES catalog.entity (id),
      PRIMARY KEY (legacy_kind, legacy_id)
    )
    """,
)

_NEXT_ENTITY_ID = "nextval(pg_get_serial_sequence('catalog.entity', 'id'))"

# Set-based. nextval in an ordered select list runs after ORDER BY (PG >= 9.6): ids follow the legacy order.
_COPY = (
    """
    SELECT setval(pg_get_serial_sequence('catalog.entity', 'id'), greatest(
      coalesce(pg_sequence_last_value(pg_get_serial_sequence('overwatch.hero', 'id')::regclass), 1),
      coalesce(pg_sequence_last_value(pg_get_serial_sequence('overwatch.map', 'id')::regclass), 1),
      coalesce(pg_sequence_last_value(pg_get_serial_sequence('overwatch.gamemode', 'id')::regclass), 1),
      (SELECT coalesce(max(id), 1) FROM overwatch.hero),
      (SELECT coalesce(max(id), 1) FROM overwatch.map),
      (SELECT coalesce(max(id), 1) FROM overwatch.gamemode)
    ))
    """,
    """
    CREATE TEMP TABLE discipline01_entity (legacy_kind VARCHAR(16), legacy_id BIGINT, entity_id BIGINT) ON COMMIT DROP
    """,
    f"INSERT INTO discipline01_entity SELECT 'gamemode', g.id, {_NEXT_ENTITY_ID} FROM overwatch.gamemode g ORDER BY g.id",
    f"INSERT INTO discipline01_entity SELECT 'hero', h.id, {_NEXT_ENTITY_ID} FROM overwatch.hero h ORDER BY h.id",
    f"INSERT INTO discipline01_entity SELECT 'map', m.id, {_NEXT_ENTITY_ID} FROM overwatch.map m ORDER BY m.id",
    """
    INSERT INTO catalog.entity (id, created_at, updated_at, discipline, kind, slug, name, image_path, attrs, aliases)
    SELECT x.entity_id, g.created_at, g.updated_at, 'overwatch', 'mode', g.slug, g.name, g.image_path,
           jsonb_strip_nulls(jsonb_build_object('description', g.description)), g.aliases
      FROM discipline01_entity x JOIN overwatch.gamemode g ON g.id = x.legacy_id
     WHERE x.legacy_kind = 'gamemode'
    """,
    """
    INSERT INTO catalog.entity (id, created_at, updated_at, discipline, kind, slug, name, image_path, attrs, aliases)
    SELECT x.entity_id, h.created_at, h.updated_at, 'overwatch', 'character', h.slug, h.name, h.image_path,
           jsonb_build_object('class', h.type::text, 'color', h.color), h.aliases
      FROM discipline01_entity x JOIN overwatch.hero h ON h.id = x.legacy_id
     WHERE x.legacy_kind = 'hero'
    """,
    f"""
    INSERT INTO catalog.entity
           (id, created_at, updated_at, discipline, kind, slug, name, image_path, parent_id, attrs, aliases)
    SELECT x.entity_id, m.created_at, m.updated_at, 'overwatch', 'map', {MAP_SLUG}, m.name, m.image_path, p.entity_id,
           jsonb_build_object('in_competitive', m.in_competitive), m.aliases
      FROM discipline01_entity x
      JOIN overwatch.map m ON m.id = x.legacy_id
      JOIN discipline01_entity p ON p.legacy_kind = 'gamemode' AND p.legacy_id = m.gamemode_id
     WHERE x.legacy_kind = 'map'
    """,
    "INSERT INTO catalog.entity_legacy (legacy_kind, legacy_id, entity_id) SELECT legacy_kind, legacy_id, entity_id FROM discipline01_entity",
    """
    INSERT INTO catalog.alias_miss
           (created_at, updated_at, discipline, kind, raw_name, occurrences, first_seen_at, last_seen_at,
            last_ingest_job_id, resolved_at)
    SELECT a.created_at, a.updated_at, 'overwatch',
           CASE a.entity_type::text WHEN 'hero' THEN 'character' WHEN 'gamemode' THEN 'mode' ELSE 'map' END,
           a.raw_name, a.occurrences, a.first_seen_at, a.last_seen_at, a.last_log_record_id, a.resolved_at
      FROM overwatch.catalog_alias_miss a ORDER BY a.id
    """,
)

#: Every hard map reference, rewritten through entity_legacy and repointed. The new FK is the proof: an id left behind
#: lies below every new id and fails it. ``matches.*`` and ``casual.match`` die in P9; their plain FK keeps today's
#: ON DELETE, their kind is enforced where their data goes (``stats.*``).
_MAPS = (
    _drop_fks("encounter.game", "map_id"),
    """
    ALTER TABLE encounter.game
      ADD COLUMN map_kind VARCHAR(16) NOT NULL DEFAULT 'map' CONSTRAINT ck_game_map_kind CHECK (map_kind = 'map')
    """,
    "UPDATE encounter.game g SET map_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'map' AND l.legacy_id = g.map_id",
    """
    ALTER TABLE encounter.game ADD CONSTRAINT fk_game_map FOREIGN KEY (map_id, map_kind)
      REFERENCES catalog.entity (id, kind) ON DELETE RESTRICT
    """,
    _drop_fks("balancer.custom_game_lobby", "next_map_id"),
    """
    ALTER TABLE balancer.custom_game_lobby
      ADD COLUMN next_map_kind VARCHAR(16) NOT NULL DEFAULT 'map'
        CONSTRAINT ck_custom_game_lobby_next_map_kind CHECK (next_map_kind = 'map')
    """,
    """
    UPDATE balancer.custom_game_lobby b SET next_map_id = l.entity_id
      FROM catalog.entity_legacy l WHERE l.legacy_kind = 'map' AND l.legacy_id = b.next_map_id
    """,
    """
    ALTER TABLE balancer.custom_game_lobby ADD CONSTRAINT fk_custom_game_lobby_next_map
      FOREIGN KEY (next_map_id, next_map_kind) REFERENCES catalog.entity (id, kind) ON DELETE SET NULL (next_map_id)
    """,
    _drop_fks("matches.match", "map_id"),
    "UPDATE matches.match m SET map_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'map' AND l.legacy_id = m.map_id",
    "ALTER TABLE matches.match ADD CONSTRAINT match_map_id_fkey FOREIGN KEY (map_id) REFERENCES catalog.entity (id) ON DELETE CASCADE",
    # Legacy mix rows: mixround01_reconcile compares their map with encounter.game's, and mixround02 trusts it.
    _retired_map("casual.match", "SET NULL"),
    # Survives only where enclayer02 ran as a stamp; the release drops it before this revision.
    _retired_map("tournament.encounter_map_code", "SET NULL"),
)

#: Every hard hero reference, rewritten through entity_legacy and repointed (the FK is the proof, as for maps).
_HEROES = (
    _drop_fks("matches.statistics", "hero_id"),
    "UPDATE matches.statistics s SET hero_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'hero' AND l.legacy_id = s.hero_id",
    "ALTER TABLE matches.statistics ADD CONSTRAINT statistics_hero_id_fkey FOREIGN KEY (hero_id) REFERENCES catalog.entity (id) ON DELETE CASCADE",
    _drop_fks("matches.event", "hero_id"),
    _drop_fks("matches.event", "related_hero_id"),
    "UPDATE matches.event e SET hero_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'hero' AND l.legacy_id = e.hero_id",
    "UPDATE matches.event e SET related_hero_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'hero' AND l.legacy_id = e.related_hero_id",
    """
    ALTER TABLE matches.event
      ADD CONSTRAINT assists_hero_id_fkey FOREIGN KEY (hero_id) REFERENCES catalog.entity (id) ON DELETE CASCADE,
      ADD CONSTRAINT assists_related_hero_id_fkey FOREIGN KEY (related_hero_id) REFERENCES catalog.entity (id) ON DELETE CASCADE
    """,
    _drop_fks("matches.kill_feed", "killer_hero_id"),
    _drop_fks("matches.kill_feed", "victim_hero_id"),
    "UPDATE matches.kill_feed k SET killer_hero_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'hero' AND l.legacy_id = k.killer_hero_id",
    "UPDATE matches.kill_feed k SET victim_hero_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'hero' AND l.legacy_id = k.victim_hero_id",
    """
    ALTER TABLE matches.kill_feed
      ADD CONSTRAINT kill_feed_killer_hero_id_fkey FOREIGN KEY (killer_hero_id) REFERENCES catalog.entity (id) ON DELETE CASCADE,
      ADD CONSTRAINT kill_feed_victim_hero_id_fkey FOREIGN KEY (victim_hero_id) REFERENCES catalog.entity (id) ON DELETE CASCADE
    """,
    # A registration's top heroes become preferred catalog entities (spec §14.2, §8.3 "registration_role_entity").
    "ALTER TABLE balancer.registration_role_hero RENAME TO registration_role_entity",
    _drop_fks("balancer.registration_role_entity", "hero_id"),
    "ALTER TABLE balancer.registration_role_entity RENAME COLUMN hero_id TO entity_id",
    _rename_registration_objects,
    """
    ALTER TABLE balancer.registration_role_entity
      ADD COLUMN entity_kind VARCHAR(16) NOT NULL DEFAULT 'character'
        CONSTRAINT ck_registration_role_entity_kind CHECK (entity_kind = 'character')
    """,
    """
    UPDATE balancer.registration_role_entity r SET entity_id = l.entity_id
      FROM catalog.entity_legacy l WHERE l.legacy_kind = 'hero' AND l.legacy_id = r.entity_id
    """,
    """
    ALTER TABLE balancer.registration_role_entity ADD CONSTRAINT fk_registration_role_entity_entity
      FOREIGN KEY (entity_id, entity_kind) REFERENCES catalog.entity (id, kind) ON DELETE CASCADE
    """,
    # Achievements: the rule gets its discipline and an entity of that discipline (D96).
    _drop_fks("achievements.rule", "hero_id"),
    """
    ALTER TABLE achievements.rule
      ADD COLUMN discipline VARCHAR(32) NOT NULL DEFAULT 'overwatch'
        CONSTRAINT fk_rule_discipline REFERENCES catalog.discipline (code),
      ADD COLUMN entity_kind VARCHAR(16) NOT NULL DEFAULT 'character' CONSTRAINT ck_rule_entity_kind CHECK (entity_kind = 'character')
    """,
    "ALTER TABLE achievements.rule RENAME COLUMN hero_id TO entity_id",
    "UPDATE achievements.rule r SET entity_id = l.entity_id FROM catalog.entity_legacy l WHERE l.legacy_kind = 'hero' AND l.legacy_id = r.entity_id",
    """
    ALTER TABLE achievements.rule ADD CONSTRAINT fk_rule_entity FOREIGN KEY (entity_id, entity_kind, discipline)
      REFERENCES catalog.entity (id, kind, discipline) ON DELETE SET NULL (entity_id)
    """,
)

#: The interim hero-stats view (P4 replaces it with stats.mv_entity_global_stats) joined ``overwatch.map``. Created
#: WITH NO DATA as before: the app-worker's first refresh is a plain REFRESH (hero_stats_refresh.py).
_STATS_VIEW = (
    "DROP MATERIALIZED VIEW matches.mv_hero_global_stats",
    """
    CREATE MATERIALIZED VIEW matches.mv_hero_global_stats AS
    WITH qualified AS (
        SELECT DISTINCT s.match_id, s.user_id, s.hero_id
        FROM matches.statistics s
        WHERE s.round = 0 AND s.name = 'HeroTimePlayed' AND s.value > 60
    ),
    eligible AS (
        SELECT st.match_id, st.user_id, st.hero_id, st.name, st.value
        FROM matches.statistics st
        JOIN qualified q
          ON q.match_id = st.match_id AND q.user_id = st.user_id AND q.hero_id = st.hero_id
        WHERE st.round = 0 AND st.hero_id IS NOT NULL
    ),
    agg AS (
        SELECT e.hero_id, e.name, sum(e.value) AS sum_value, sum(m."time") AS sum_time
        FROM eligible e
        JOIN matches.match m ON m.id = e.match_id
        GROUP BY e.hero_id, e.name
    ),
    ranked AS (
        SELECT e.hero_id, e.name, e.match_id, e.user_id, e.value,
               row_number() OVER (
                 PARTITION BY e.hero_id, e.name
                 ORDER BY e.value * CASE WHEN e.name IN (
                              'Deaths', 'DamageTaken', 'EnvironmentalDeaths',
                              'ShotsMissed', 'DamageFB', 'Performance'
                          ) THEN -1.0 ELSE 1.0 END DESC,
                          e.match_id DESC
               ) AS rn
        FROM eligible e
    ),
    best AS (
        SELECT r.hero_id, r.name, r.value AS best_value,
               m.encounter_id,
               mp.name AS map_name, mp.image_path AS map_image_path,
               t.name AS tournament_name,
               u.name AS username
        FROM ranked r
        JOIN matches.match m          ON m.id = r.match_id
        JOIN catalog.entity mp        ON mp.id = m.map_id
        JOIN encounter.encounter enc  ON enc.id = m.encounter_id
        JOIN tournament.tournament t  ON t.id = enc.tournament_id
        JOIN players."user" u         ON u.id = r.user_id
        WHERE r.rn = 1
    )
    SELECT
        a.name AS name,
        a.hero_id AS hero_id,
        b.best_value AS best_value,
        (a.sum_value / nullif(a.sum_time, 0)) * 600 AS avg,
        jsonb_build_object(
            'encounter_id', b.encounter_id,
            'map_name', b.map_name,
            'map_image_path', b.map_image_path,
            'tournament_name', b.tournament_name,
            'username', b.username
        ) AS metadata
    FROM agg a
    JOIN best b ON b.hero_id = a.hero_id AND b.name = a.name
    WITH NO DATA
    """,
    "CREATE UNIQUE INDEX ix_mv_hero_global_stats_name_hero ON matches.mv_hero_global_stats (name, hero_id)",
)

# ── pick-ban soft ids (D84): columns set-based, documents row by row ─────────────────────────────────────────────

_PICK_BAN_COLUMNS = (
    """
    UPDATE tournament.pick_ban_config_item i SET item_id = l.entity_id
      FROM tournament.pick_ban_config c, catalog.entity_legacy l
     WHERE c.id = i.pick_ban_config_id AND c.kind::text = :kind AND l.legacy_kind = :kind AND l.legacy_id = i.item_id
    """,
    """
    UPDATE tournament.pick_ban_config_slot_item si SET item_id = l.entity_id
      FROM tournament.pick_ban_config_slot sl, tournament.pick_ban_config c, catalog.entity_legacy l
     WHERE sl.id = si.pick_ban_config_slot_id AND c.id = sl.pick_ban_config_id AND c.kind::text = :kind
       AND l.legacy_kind = :kind AND l.legacy_id = si.item_id
    """,
    """
    UPDATE tournament.pick_ban_config_slot sl SET reserve_item_id = l.entity_id
      FROM tournament.pick_ban_config c, catalog.entity_legacy l
     WHERE c.id = sl.pick_ban_config_id AND c.kind::text = :kind AND l.legacy_kind = :kind AND l.legacy_id = sl.reserve_item_id
    """,
    """
    UPDATE encounter.pick_ban_entry e SET item_id = l.entity_id
      FROM encounter.pick_ban_session s, catalog.entity_legacy l
     WHERE s.id = e.session_id AND s.kind::text = :kind AND l.legacy_kind = :kind AND l.legacy_id = e.item_id
    """,
)
_JOURNAL_ACTIONS = ("acted", "draft_locked", "draft_set", "step_auto_resolved")


def _remap(value: Any, ids: Mapping[int, int]) -> Any:
    """One soft id; anything that is not an int (or is a bool) is not an id and stays."""
    return ids.get(value, value) if isinstance(value, int) and not isinstance(value, bool) else value


def remap_condition(node: Any, ids: Mapping[int, int]) -> Any:
    """Every ``item_in`` leaf's ``item_ids`` at any depth of a ruleset or step document."""
    if isinstance(node, list):
        return [remap_condition(value, ids) for value in node]
    if not isinstance(node, dict):
        return node
    out = {key: remap_condition(value, ids) for key, value in node.items()}
    params = out.get("params")
    if out.get("type") == "item_in" and isinstance(params, dict) and isinstance(params.get("item_ids"), list):
        out["params"] = {**params, "item_ids": [_remap(value, ids) for value in params["item_ids"]]}
    return out


def remap_pool(pool: dict, ids: Mapping[int, int]) -> dict:
    out = dict(pool)
    if isinstance(out.get("items"), list):
        out["items"] = [_remap(value, ids) for value in out["items"]]
    if isinstance(out.get("slots"), list):
        out["slots"] = [
            [_remap(value, ids) for value in slot] if isinstance(slot, list) else slot for slot in out["slots"]
        ]
    return out


def remap_reserves(reserves: dict | None, ids: Mapping[int, int]) -> dict | None:
    return None if reserves is None else {position: _remap(value, ids) for position, value in reserves.items()}


def side_pick_steps(sequence: list | None) -> frozenset[int]:
    """Step indexes whose answers are side indexes, not catalog ids."""
    return frozenset(
        step["index"] for step in sequence or () if isinstance(step, dict) and step.get("action") == "side_pick"
    )


def remap_items(items: list | None, ids: Mapping[int, int]) -> list:
    return [
        {**item, "item_id": _remap(item["item_id"], ids)} if isinstance(item, dict) and "item_id" in item else item
        for item in items or []
    ]


def remap_journal(data: dict, ids: Mapping[int, int]) -> dict:
    out = dict(data)
    if "item_id" in out:
        out["item_id"] = _remap(out["item_id"], ids)
    if isinstance(out.get("items"), list):
        out["items"] = remap_items(out["items"], ids)
    if isinstance(out.get("item_ids"), list):
        out["item_ids"] = [_remap(value, ids) for value in out["item_ids"]]
    return out


def _rewrite_documents(
    bind, select_sql: str, update_sql: str, kind: str, remap: Callable[[Any], dict[str, Any]]
) -> None:
    changes: list[dict[str, Any]] = []
    for row in bind.execute(sa.text(select_sql), {"kind": kind}).mappings().all():
        new = remap(row)
        if any(new[column] != row[column] for column in new):
            changes.append(
                {
                    "id": row["id"],
                    **{column: None if value is None else json.dumps(value) for column, value in new.items()},
                }
            )
    if changes:
        bind.execute(sa.text(update_sql), changes)


def _rewrite_pick_ban(kind: str) -> None:
    """Every soft reference of one pick-ban kind (``map`` | ``hero``, equal to the legacy kind)."""
    bind = op.get_bind()
    for statement in _PICK_BAN_COLUMNS:
        bind.execute(sa.text(statement), {"kind": kind})
    ids = dict(
        bind.execute(
            sa.text("SELECT legacy_id, entity_id FROM catalog.entity_legacy WHERE legacy_kind = :kind"), {"kind": kind}
        ).all()
    )
    _rewrite_documents(
        bind,
        "SELECT id, ruleset_json FROM tournament.pick_ban_config WHERE kind::text = :kind",
        "UPDATE tournament.pick_ban_config SET ruleset_json = CAST(:ruleset_json AS JSON) WHERE id = :id",
        kind,
        lambda row: {"ruleset_json": remap_condition(row["ruleset_json"], ids)},
    )
    _rewrite_documents(
        bind,
        "SELECT id, pool_json, slot_reserves_json, ruleset_json, resolved_sequence_json"
        "  FROM encounter.pick_ban_session WHERE kind::text = :kind",
        "UPDATE encounter.pick_ban_session SET pool_json = CAST(:pool_json AS JSON),"
        " slot_reserves_json = CAST(:slot_reserves_json AS JSON), ruleset_json = CAST(:ruleset_json AS JSON),"
        " resolved_sequence_json = CAST(:resolved_sequence_json AS JSON) WHERE id = :id",
        kind,
        lambda row: {
            "pool_json": remap_pool(row["pool_json"], ids),
            "slot_reserves_json": remap_reserves(row["slot_reserves_json"], ids),
            "ruleset_json": remap_condition(row["ruleset_json"], ids),
            "resolved_sequence_json": remap_condition(row["resolved_sequence_json"], ids),
        },
    )
    _rewrite_documents(
        bind,
        "SELECT sub.id, sub.step_index, sub.items_json, s.resolved_sequence_json"
        "  FROM encounter.pick_ban_submission sub JOIN encounter.pick_ban_session s ON s.id = sub.session_id"
        " WHERE s.kind::text = :kind",
        "UPDATE encounter.pick_ban_submission SET items_json = CAST(:items_json AS JSON) WHERE id = :id",
        kind,
        lambda row: {
            "items_json": row["items_json"]
            if row["step_index"] in side_pick_steps(row["resolved_sequence_json"])
            else remap_items(row["items_json"], ids)
        },
    )
    _rewrite_documents(
        bind,
        "SELECT r.id, r.data, s.resolved_sequence_json"
        "  FROM encounter.room_event r"
        "  LEFT JOIN encounter.pick_ban_session s ON s.encounter_id = r.encounter_id AND s.kind::text = r.kind"
        f" WHERE r.kind = :kind AND r.action IN {_JOURNAL_ACTIONS!r}",
        "UPDATE encounter.room_event SET data = CAST(:data AS JSON) WHERE id = :id",
        kind,
        lambda row: {
            "data": row["data"]
            if row["data"].get("action") == "side_pick"
            or row["data"].get("step_index") in side_pick_steps(row["resolved_sequence_json"])
            else remap_journal(row["data"], ids)
        },
    )


def upgrade() -> None:
    # Earlier revisions in the same invocation can leave RI events pending on any of these tables.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    immediate = (
        op.get_bind()
        .execute(
            sa.text("SELECT conrelid::regclass, conname FROM pg_constraint WHERE condeferrable AND NOT condeferred")
        )
        .all()
    )
    if immediate:
        raise RuntimeError(f"discipline01 cannot restore INITIALLY IMMEDIATE constraints: {immediate}")
    _preflight()
    for statement in (*_SCHEMA, *_COPY, *_MAPS, *_HEROES):
        if isinstance(statement, str):
            op.execute(statement)
        else:
            statement()
    _rewrite_pick_ban("map")
    _rewrite_pick_ban("hero")
    for statement in _STATS_VIEW:
        op.execute(statement)
    op.execute("SET CONSTRAINTS ALL DEFERRED")


def downgrade() -> None:
    raise RuntimeError("discipline01 is forward-fix only; restore from a backup to go back")
