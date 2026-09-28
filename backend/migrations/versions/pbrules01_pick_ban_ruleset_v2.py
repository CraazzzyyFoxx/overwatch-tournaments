"""Pick-ban ruleset v2: rulesets, submissions, carried bans.

Revision ID: pbrules01
Revises: mixlobby01
Create Date: 2026-09-28 00:00:00.000000

The flat token sequence (``ban_first``, ``pick_second``, ``decider``, ...) is
replaced by a *ruleset* -- phases with a ``when`` round condition, a
``pool_filter``, and either a generator or explicit steps carrying count, blind,
target, lifetime, timer and condition trees (design doc
``docs/plans/2026-09-28-pick-ban-constructor.md`` §1). Everything the v1 columns
said is expressible in one, so every stored config converts rather than resets:

- ``sequence_json`` tokens become count-1, open, single-actor steps (§11), which
  is exactly how they behaved -- a migrated config plays identically;
- ``no_repeat_scope`` becomes a ``banned_by`` condition (phase ``pool_filter``
  for ``encounter``, per-ban-step ``eligible`` for ``encounter_same_side``),
  which is why ``encounter_pick_ban_ledger`` can go: cross-round memory is now
  read from the submission log;
- ``unique_attribute_per_side_per_round='role'`` becomes a ``max_per_group``
  constraint on every ban/protect step;
- ``turn_timer_seconds`` becomes the ruleset's default ``timer_seconds``;
- a v1 flat MAP config only ever played its own ``sequence_json`` when
  ``preset = 'custom'`` -- otherwise the sequence was rebuilt from ``best_of``
  at session time -- so those configs convert to the ``bracket`` generator and
  slot-mode ones to ``slot_veto`` instead of to frozen steps.

Sessions keep playing: ``resolved_sequence_json``'s side-resolved tokens become
resolved step objects (§3) one-for-one, so a step's index is unchanged and the
entries that reference it by ``action_index`` still line up. Each committed
entry becomes one ``revealed`` submission, which is what the new runtime
projects the board from.

``round`` of a resolved step is read off the entry that committed it. A step not
yet committed has no entry to ask, so it is inferred: v1 appends a round's whole
token block and only appends the next one after that block is fully committed,
so an uncommitted step belongs to the most recently appended round -- the round
of the nearest committed entry before it (and, before the first committed entry,
the lowest round any entry of the session carries). Flat-mode sessions carry
NULL rounds throughout and come out NULL.

``downgrade()`` is best effort: a ruleset that v1 can express (single phase,
always-on, count-1 open single-actor steps) goes back to tokens and its
preset/no-repeat/role columns; anything the constructor added that v1 had no
word for comes back as an empty custom sequence. Submissions, carried entries
and dispute history are dropped; the ledger is rebuilt from the banned entries.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "pbrules01"
down_revision: str | Sequence[str] | None = "mixlobby01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_STEP_INDEX = "uq_pick_ban_entry_session_action_index"
NO_REPEAT_ENUM = "tournament.pickbannorepeatscope"

# ── frozen v1 vocabulary ─────────────────────────────────────────────────────
#
# Copies, not imports: the app's converter will keep evolving with the engine,
# and a migration must keep producing the bytes it produced the day it ran.

#: side-agnostic config token -> (action, actors)
_CONFIG_TOKENS: dict[str, tuple[str, str]] = {
    "ban_first": ("ban", "first"),
    "ban_second": ("ban", "second"),
    "pick_first": ("pick", "first"),
    "pick_second": ("pick", "second"),
    "protect_first": ("protect", "first"),
    "protect_second": ("protect", "second"),
    "decider": ("decider", "system"),
}

#: side-resolved session token -> (action, side)
_SESSION_TOKENS: dict[str, tuple[str, str]] = {
    "ban_home": ("ban", "home"),
    "ban_away": ("ban", "away"),
    "pick_home": ("pick", "home"),
    "pick_away": ("pick", "away"),
    "protect_home": ("protect", "home"),
    "protect_away": ("protect", "away"),
    "decider": ("decider", "system"),
}

_SELF_SERIES_BAN = {"NOT": {"type": "banned_by", "params": {"by": "self", "scope": "series"}}}
_ANY_SERIES_BAN = {"NOT": {"type": "banned_by", "params": {"by": "any", "scope": "series"}}}
_ROLE_CONSTRAINT = {"type": "max_per_group", "params": {"max": 1, "scope": "round", "group": None}}


def _step(
    index: int,
    action: str,
    actors: str,
    *,
    same_side_ban_memory: bool,
    unique_role: bool,
) -> dict[str, Any]:
    """§11: one v1 token -> one count-1, open, single-actor step."""
    eligible: dict[str, Any] = {}
    if action == "ban" and same_side_ban_memory:
        eligible = dict(_SELF_SERIES_BAN)
    constraints: list[dict[str, Any]] = []
    if unique_role and action in ("ban", "protect"):
        constraints = [dict(_ROLE_CONSTRAINT)]
    return {
        "id": f"s{index + 1}",
        "action": action,
        "actors": actors,
        "count": 1,
        "min": None,
        "blind": False,
        "target": None,
        "lifetime": 1,
        "timer_seconds": None,
        "on_timeout": None,
        "dispute": {"enabled": False, "max": 0},
        "eligible": eligible,
        "constraints": constraints,
    }


def _ruleset_from_v1(
    *,
    kind: str,
    mode: str,
    preset: str | None,
    sequence: Any,
    no_repeat_scope: str | None,
    unique_attribute: str | None,
    timer_seconds: int | None,
) -> dict[str, Any]:
    """§11: one v1 config row -> one single-phase ruleset."""
    same_side = no_repeat_scope == "encounter_same_side"
    unique_role = unique_attribute == "role"
    generator: str | None = None
    steps: list[dict[str, Any]] = []
    if kind == "map" and mode == "slots":
        generator = "slot_veto"
    elif kind == "map" and preset != "custom":
        # A non-custom flat map config never played its stored sequence: the
        # session rebuilt it from best_of. The generator IS that rebuild.
        generator = "bracket"
    else:
        tokens = [token for token in (sequence or []) if token in _CONFIG_TOKENS]
        if kind == "hero":
            tokens = [token for token in tokens if token != "decider"]
        steps = [
            _step(index, *_CONFIG_TOKENS[token], same_side_ban_memory=same_side, unique_role=unique_role)
            for index, token in enumerate(tokens)
        ]
    return {
        "version": 2,
        "timer_seconds": timer_seconds,
        "on_timeout": "random_fill",
        "phases": [
            {
                "id": "main",
                "name": None,
                "when": {},
                "pool_filter": dict(_ANY_SERIES_BAN) if no_repeat_scope == "encounter" else {},
                "generator": generator,
                "steps": steps,
            }
        ],
    }


def _phase_rules(ruleset: dict[str, Any]) -> tuple[bool, bool]:
    """(same-side ban memory, role uniqueness) as stored in a converted ruleset."""
    phase = (ruleset.get("phases") or [{}])[0]
    same_side = any(
        step.get("action") == "ban" and step.get("eligible") == _SELF_SERIES_BAN for step in phase.get("steps") or []
    )
    unique_role = any(_ROLE_CONSTRAINT in (step.get("constraints") or []) for step in phase.get("steps") or [])
    return same_side, unique_role


def _resolved_step(
    index: int,
    token: str,
    round_number: int | None,
    *,
    timer_seconds: int | None,
    same_side_ban_memory: bool,
    unique_role: bool,
) -> dict[str, Any]:
    """§3: one side-resolved v1 token -> one resolved step object."""
    action, side = _SESSION_TOKENS[token]
    base = _step(
        index,
        action,
        side,
        same_side_ban_memory=same_side_ban_memory,
        unique_role=unique_role,
    )
    return {
        "index": index,
        "round": round_number,
        "phase_id": "main",
        "step_id": base["id"],
        "action": action,
        "sides": ["system"] if side == "system" else [side],
        "count": 1,
        # Resolved, not inherited: v1's min was always "all of it" (count 1).
        "min": 1,
        "blind": False,
        "target": None,
        "lifetime": 1,
        "timer_seconds": timer_seconds,
        "on_timeout": "random_fill",
        "dispute": {"enabled": False, "max": 0},
        "eligible": base["eligible"],
        "constraints": base["constraints"],
    }


def _synthesized_ruleset(
    tokens: list[str],
    rounds: list[int | None],
    *,
    first_side: str | None,
    timer_seconds: int | None,
) -> dict[str, Any]:
    """Ruleset for a session whose config row is gone.

    Only the first round's block becomes the phase's steps: a progressive
    session repeats that block per round, so taking the whole resolved sequence
    would multiply it.
    """
    opener = first_side or "home"
    first_round = rounds[0] if rounds else None
    steps: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        if rounds[index] != first_round:
            break
        action, side = _SESSION_TOKENS[token]
        if side == "system":
            actors = "system"
        else:
            actors = "first" if side == opener else "second"
        steps.append(_step(len(steps), action, actors, same_side_ban_memory=False, unique_role=False))
    return {
        "version": 2,
        "timer_seconds": timer_seconds,
        "on_timeout": "random_fill",
        "phases": [{"id": "main", "name": None, "when": {}, "pool_filter": {}, "generator": None, "steps": steps}],
    }


def upgrade() -> None:
    op.add_column("pick_ban_config", sa.Column("ruleset_json", sa.JSON(), nullable=True), schema="tournament")
    op.add_column("pick_ban_session", sa.Column("ruleset_json", sa.JSON(), nullable=True), schema="tournament")
    op.add_column("pick_ban_entry", sa.Column("carried_from_round", sa.Integer(), nullable=True), schema="tournament")
    op.create_table(
        "pick_ban_submission",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("items_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("side IN ('home', 'away', 'system')", name="ck_pick_ban_submission_side"),
        sa.CheckConstraint("state IN ('draft', 'locked', 'revealed', 'voided')", name="ck_pick_ban_submission_state"),
        sa.ForeignKeyConstraint(["session_id"], ["tournament.pick_ban_session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "step_index", "side", "attempt", name="uq_pick_ban_submission_step_side_attempt"
        ),
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_pick_ban_submission_session_id"),
        "pick_ban_submission",
        ["session_id"],
        unique=False,
        schema="tournament",
    )

    bind = op.get_bind()

    # ── configs ──────────────────────────────────────────────────────────────
    rulesets: dict[int, dict[str, Any]] = {}
    configs = (
        bind.execute(
            sa.text(
                "SELECT id, kind::text AS kind, mode::text AS mode, preset, sequence_json,"
                " no_repeat_scope::text AS no_repeat_scope, unique_attribute_per_side_per_round,"
                " turn_timer_seconds"
                " FROM tournament.pick_ban_config ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    for config in configs:
        ruleset = _ruleset_from_v1(
            kind=config["kind"],
            mode=config["mode"],
            preset=config["preset"],
            sequence=config["sequence_json"],
            no_repeat_scope=config["no_repeat_scope"],
            unique_attribute=config["unique_attribute_per_side_per_round"],
            timer_seconds=config["turn_timer_seconds"],
        )
        rulesets[config["id"]] = ruleset
        bind.execute(
            sa.text("UPDATE tournament.pick_ban_config SET ruleset_json = CAST(:ruleset AS json) WHERE id = :id"),
            {"ruleset": json.dumps(ruleset), "id": config["id"]},
        )

    # ── sessions ─────────────────────────────────────────────────────────────
    insert_submission = sa.text(
        "INSERT INTO tournament.pick_ban_submission"
        " (created_at, updated_at, session_id, step_index, side, attempt, state, items_json,"
        "  locked_at, revealed_at)"
        " VALUES (:created_at, :updated_at, :session_id, :step_index, :side, 1, 'revealed',"
        "         CAST(:items AS json), :at, :at)"
    )
    sessions = (
        bind.execute(
            sa.text(
                "SELECT id, config_id, first_side::text AS first_side, resolved_sequence_json, turn_timer_seconds"
                " FROM tournament.pick_ban_session ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    for row in sessions:
        tokens = [token for token in (row["resolved_sequence_json"] or []) if token in _SESSION_TOKENS]
        entries = (
            bind.execute(
                sa.text(
                    "SELECT id, action_index, round, item_id, picked_by::text AS picked_by,"
                    " protected_by::text AS protected_by, created_at, updated_at"
                    " FROM tournament.pick_ban_entry WHERE session_id = :sid ORDER BY action_index NULLS LAST, id"
                ),
                {"sid": row["id"]},
            )
            .mappings()
            .all()
        )

        committed = {e["action_index"]: e for e in entries if e["action_index"] is not None}
        entry_rounds = [e["round"] for e in entries if e["round"] is not None]
        fallback_round: int | None = min(entry_rounds) if entry_rounds else None
        rounds: list[int | None] = []
        current = fallback_round
        for index in range(len(tokens)):
            if index in committed:
                current = committed[index]["round"]
            rounds.append(current)

        ruleset = rulesets.get(row["config_id"]) if row["config_id"] is not None else None
        if ruleset is None:
            ruleset = _synthesized_ruleset(
                tokens,
                rounds,
                first_side=row["first_side"],
                timer_seconds=row["turn_timer_seconds"],
            )
        same_side, unique_role = _phase_rules(ruleset)

        resolved = [
            _resolved_step(
                index,
                token,
                rounds[index],
                timer_seconds=row["turn_timer_seconds"],
                same_side_ban_memory=same_side,
                unique_role=unique_role,
            )
            for index, token in enumerate(tokens)
        ]
        bind.execute(
            sa.text(
                "UPDATE tournament.pick_ban_session"
                " SET ruleset_json = CAST(:ruleset AS json), resolved_sequence_json = CAST(:resolved AS json)"
                " WHERE id = :id"
            ),
            {"ruleset": json.dumps(ruleset), "resolved": json.dumps(resolved), "id": row["id"]},
        )

        for index, entry in sorted(committed.items()):
            side = entry["picked_by"] or entry["protected_by"] or "system"
            if side == "decider":
                side = "system"
            at = entry["updated_at"] or entry["created_at"]
            bind.execute(
                insert_submission,
                {
                    "created_at": entry["created_at"],
                    "updated_at": entry["updated_at"],
                    "session_id": row["id"],
                    "step_index": index,
                    "side": side,
                    "items": json.dumps([{"item_id": entry["item_id"], "target_player_id": None}]),
                    "at": at,
                },
            )

    op.alter_column("pick_ban_config", "ruleset_json", nullable=False, schema="tournament")
    op.alter_column("pick_ban_session", "ruleset_json", nullable=False, schema="tournament")

    # ── what v2 replaced ─────────────────────────────────────────────────────
    op.drop_index(ENTRY_STEP_INDEX, table_name="pick_ban_entry", schema="tournament")
    op.drop_constraint("ck_pick_ban_config_slots_not_custom", "pick_ban_config", type_="check", schema="tournament")
    for column in (
        "sequence_json",
        "preset",
        "no_repeat_scope",
        "unique_attribute_per_side_per_round",
        "allow_protect",
        "turn_timer_seconds",
    ):
        op.drop_column("pick_ban_config", column, schema="tournament")
    op.drop_column("pick_ban_session", "turn_timer_seconds", schema="tournament")
    op.drop_table("encounter_pick_ban_ledger", schema="tournament")
    op.execute(f"DROP TYPE IF EXISTS {NO_REPEAT_ENUM}")


# ── downgrade ────────────────────────────────────────────────────────────────


def _tokens_from_ruleset(ruleset: dict[str, Any]) -> list[str] | None:
    """The v1 token sequence a ruleset is equivalent to, or None if it is not."""
    phases = ruleset.get("phases") or []
    if len(phases) != 1:
        return None
    phase = phases[0]
    if phase.get("when") not in (None, {}):
        return None
    if phase.get("generator"):
        return []
    tokens: list[str] = []
    for step in phase.get("steps") or []:
        if (
            step.get("count") != 1
            or step.get("blind")
            or step.get("target")
            or (step.get("min") not in (None, 1))
            or (step.get("dispute") or {}).get("enabled")
        ):
            return None
        action, actors = step.get("action"), step.get("actors")
        if action == "decider" and actors == "system":
            tokens.append("decider")
            continue
        if f"{action}_{actors}" not in _CONFIG_TOKENS:
            return None
        tokens.append(f"{action}_{actors}")
    return tokens


def _v1_from_ruleset(ruleset: dict[str, Any], *, mode: str) -> dict[str, Any]:
    """Best-effort reverse of :func:`_ruleset_from_v1` for one config row."""
    phase = (ruleset.get("phases") or [{}])[0]
    generator = phase.get("generator")
    tokens = _tokens_from_ruleset(ruleset)
    if tokens is None:
        # Nothing v1 can say. An empty custom sequence is the honest answer --
        # except in slots mode, where 'custom' is forbidden outright.
        preset = None if mode == "slots" else "custom"
        tokens = []
    elif generator == "slot_veto":
        preset = None
    elif generator == "bracket":
        preset = "bracket"
    else:
        preset = None if mode == "slots" else "custom"
    same_side, unique_role = _phase_rules(ruleset)
    if phase.get("pool_filter") == _ANY_SERIES_BAN:
        no_repeat = "encounter"
    elif same_side:
        no_repeat = "encounter_same_side"
    else:
        no_repeat = "none"
    return {
        "preset": preset,
        "sequence": tokens,
        "no_repeat_scope": no_repeat,
        "unique_attribute": "role" if unique_role else None,
        "timer_seconds": ruleset.get("timer_seconds"),
        "allow_protect": any(token.startswith("protect_") for token in tokens),
    }


def downgrade() -> None:
    no_repeat = postgresql.ENUM(
        "none", "encounter", "encounter_same_side", name="pickbannorepeatscope", schema="tournament"
    )
    no_repeat.create(op.get_bind(), checkfirst=True)
    no_repeat_column = postgresql.ENUM(
        "none",
        "encounter",
        "encounter_same_side",
        name="pickbannorepeatscope",
        schema="tournament",
        create_type=False,
    )

    op.add_column("pick_ban_config", sa.Column("turn_timer_seconds", sa.Integer(), nullable=True), schema="tournament")
    op.add_column("pick_ban_config", sa.Column("preset", sa.String(length=32), nullable=True), schema="tournament")
    op.add_column(
        "pick_ban_config",
        sa.Column("sequence_json", sa.JSON(), server_default="[]", nullable=False),
        schema="tournament",
    )
    op.add_column(
        "pick_ban_config",
        sa.Column("no_repeat_scope", no_repeat_column, server_default="none", nullable=False),
        schema="tournament",
    )
    op.add_column(
        "pick_ban_config",
        sa.Column("unique_attribute_per_side_per_round", sa.String(length=32), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "pick_ban_config",
        sa.Column("allow_protect", sa.Boolean(), server_default="false", nullable=False),
        schema="tournament",
    )
    op.add_column("pick_ban_session", sa.Column("turn_timer_seconds", sa.Integer(), nullable=True), schema="tournament")

    bind = op.get_bind()
    configs = (
        bind.execute(sa.text("SELECT id, mode::text AS mode, ruleset_json FROM tournament.pick_ban_config ORDER BY id"))
        .mappings()
        .all()
    )
    for config in configs:
        v1 = _v1_from_ruleset(config["ruleset_json"] or {}, mode=config["mode"])
        bind.execute(
            sa.text(
                "UPDATE tournament.pick_ban_config SET preset = :preset,"
                " sequence_json = CAST(:sequence AS json), no_repeat_scope = CAST(:no_repeat AS"
                " tournament.pickbannorepeatscope), unique_attribute_per_side_per_round = :unique_attribute,"
                " allow_protect = :allow_protect, turn_timer_seconds = :timer WHERE id = :id"
            ),
            {
                "preset": v1["preset"],
                "sequence": json.dumps(v1["sequence"]),
                "no_repeat": v1["no_repeat_scope"],
                "unique_attribute": v1["unique_attribute"],
                "allow_protect": v1["allow_protect"],
                "timer": v1["timer_seconds"],
                "id": config["id"],
            },
        )

    sessions = (
        bind.execute(
            sa.text("SELECT id, ruleset_json, resolved_sequence_json FROM tournament.pick_ban_session ORDER BY id")
        )
        .mappings()
        .all()
    )
    for row in sessions:
        tokens: list[str] = []
        timer: int | None = (row["ruleset_json"] or {}).get("timer_seconds")
        for step in row["resolved_sequence_json"] or []:
            action = step.get("action")
            sides = step.get("sides") or ["home"]
            tokens.append("decider" if action == "decider" else f"{action}_{sides[0]}")
            if timer is None:
                timer = step.get("timer_seconds")
        bind.execute(
            sa.text(
                "UPDATE tournament.pick_ban_session SET resolved_sequence_json = CAST(:tokens AS json),"
                " turn_timer_seconds = :timer WHERE id = :id"
            ),
            {"tokens": json.dumps(tokens), "timer": timer, "id": row["id"]},
        )

    # Carried bans are a v2 invention: v1 kept a later round's pool clean through
    # the ledger instead, so the rows have to go before the ledger comes back.
    op.execute("DELETE FROM tournament.pick_ban_entry WHERE carried_from_round IS NOT NULL")

    op.create_table(
        "encounter_pick_ban_ledger",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM("map", "hero", name="pickbankind", schema="tournament", create_type=False),
            nullable=False,
        ),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column(
            "banned_by_side",
            postgresql.ENUM("home", "away", "decider", name="pickbanside", schema="tournament", create_type=False),
            nullable=False,
        ),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "encounter_id", "kind", "item_id", "banned_by_side", name="uq_encounter_pick_ban_ledger_entry"
        ),
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_encounter_pick_ban_ledger_encounter_id"),
        "encounter_pick_ban_ledger",
        ["encounter_id"],
        unique=False,
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_encounter_pick_ban_ledger_item_id"),
        "encounter_pick_ban_ledger",
        ["item_id"],
        unique=False,
        schema="tournament",
    )
    # Rebuilt from the board rather than left empty: every banned entry of a
    # numbered round is exactly what v1 would have booked when that ban committed.
    op.execute(
        """
        INSERT INTO tournament.encounter_pick_ban_ledger
            (created_at, updated_at, encounter_id, kind, item_id, banned_by_side, round)
        SELECT now(), NULL, s.encounter_id, s.kind, e.item_id, e.picked_by, MIN(e.round)
        FROM tournament.pick_ban_entry e
        JOIN tournament.pick_ban_session s ON s.id = e.session_id
        WHERE e.status = 'banned' AND e.picked_by IN ('home', 'away') AND e.round IS NOT NULL
        GROUP BY s.encounter_id, s.kind, e.item_id, e.picked_by
        """
    )

    op.drop_index(
        op.f("ix_tournament_pick_ban_submission_session_id"), table_name="pick_ban_submission", schema="tournament"
    )
    op.drop_table("pick_ban_submission", schema="tournament")
    op.drop_column("pick_ban_entry", "carried_from_round", schema="tournament")
    op.drop_column("pick_ban_session", "ruleset_json", schema="tournament")
    op.drop_column("pick_ban_config", "ruleset_json", schema="tournament")
    op.create_index(
        ENTRY_STEP_INDEX,
        "pick_ban_entry",
        ["session_id", "action_index"],
        unique=True,
        schema="tournament",
        postgresql_where=sa.text("action_index IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_pick_ban_config_slots_not_custom",
        "pick_ban_config",
        "NOT (mode = 'slots' AND preset = 'custom')",
        schema="tournament",
    )
    op.alter_column("pick_ban_config", "sequence_json", server_default=None, schema="tournament")
