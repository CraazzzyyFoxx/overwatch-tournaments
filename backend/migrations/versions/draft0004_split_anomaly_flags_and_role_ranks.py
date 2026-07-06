"""split draft_player.anomaly_flags into typed per-role fields + draft_pick.target_rank_value

Promotes the per-role rank/hero data that was buried in the misnamed
``draft_player.anomaly_flags`` bag into dedicated typed columns:
``role_ranks`` (role -> SR), ``role_top_heroes`` (role -> heroes) and a
properly named ``additional_info`` bag for the rest (e.g. ``notes``). Adds
``draft_pick.target_rank_value`` so a pick is a complete (player, role, rank)
record. Backfills existing rows, then drops ``anomaly_flags``.

Revision ID: draft0004
Revises: searchtrgm01
Create Date: 2026-06-25 00:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "draft0004"
down_revision: str | Sequence[str] | None = "searchtrgm01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _as_dict(value: object) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value) or {}
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def upgrade() -> None:
    op.add_column(
        "draft_player",
        sa.Column("role_ranks", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "draft_player",
        sa.Column("role_top_heroes", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "draft_player",
        sa.Column("additional_info", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "draft_pick",
        sa.Column("target_rank_value", sa.Integer(), nullable=True),
        schema="balancer",
    )

    bind = op.get_bind()

    # Backfill draft_player: split anomaly_flags.roles_ranks -> role_ranks/role_top_heroes,
    # keep everything else (e.g. notes) in additional_info.
    players = bind.execute(sa.text("SELECT id, anomaly_flags FROM balancer.draft_player")).fetchall()
    for pid, raw_flags in players:
        flags = _as_dict(raw_flags)
        roles_ranks = _as_dict(flags.get("roles_ranks"))
        role_ranks: dict[str, int] = {}
        role_top_heroes: dict[str, object] = {}
        for role, data in roles_ranks.items():
            data = _as_dict(data)
            rv = data.get("rank_value")
            if rv is not None:
                role_ranks[role] = rv
            heroes = data.get("top_heroes")
            if heroes:
                role_top_heroes[role] = heroes
        additional = {k: v for k, v in flags.items() if k != "roles_ranks"}
        bind.execute(
            sa.text(
                "UPDATE balancer.draft_player "
                "SET role_ranks = CAST(:rr AS json), "
                "    role_top_heroes = CAST(:th AS json), "
                "    additional_info = CAST(:ai AS json) "
                "WHERE id = :id"
            ),
            {
                "rr": json.dumps(role_ranks),
                "th": json.dumps(role_top_heroes),
                "ai": json.dumps(additional),
                "id": pid,
            },
        )

    # Backfill draft_pick.target_rank_value from the picked player's roles_ranks at target_role.
    picks = bind.execute(
        sa.text(
            "SELECT pk.id, pk.target_role, pl.anomaly_flags "
            "FROM balancer.draft_pick pk "
            "JOIN balancer.draft_player pl ON pl.id = pk.picked_player_id "
            "WHERE pk.picked_player_id IS NOT NULL AND pk.target_role IS NOT NULL"
        )
    ).fetchall()
    for pkid, target_role, raw_flags in picks:
        roles_ranks = _as_dict(_as_dict(raw_flags).get("roles_ranks"))
        rv = _as_dict(roles_ranks.get(target_role)).get("rank_value")
        if rv is not None:
            bind.execute(
                sa.text("UPDATE balancer.draft_pick SET target_rank_value = :rv WHERE id = :id"),
                {"rv": rv, "id": pkid},
            )

    op.drop_column("draft_player", "anomaly_flags", schema="balancer")


def downgrade() -> None:
    op.add_column(
        "draft_player",
        sa.Column("anomaly_flags", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, role_ranks, role_top_heroes, additional_info FROM balancer.draft_player")
    ).fetchall()
    for pid, role_ranks, role_top_heroes, additional in rows:
        role_ranks = _as_dict(role_ranks)
        role_top_heroes = _as_dict(role_top_heroes)
        additional = _as_dict(additional)
        roles_ranks: dict[str, object] = {}
        for role in set(role_ranks) | set(role_top_heroes):
            roles_ranks[role] = {
                "rank_value": role_ranks.get(role),
                "division_number": None,
                "top_heroes": role_top_heroes.get(role, []),
            }
        flags = {**additional, "roles_ranks": roles_ranks}
        bind.execute(
            sa.text("UPDATE balancer.draft_player SET anomaly_flags = CAST(:f AS json) WHERE id = :id"),
            {"f": json.dumps(flags), "id": pid},
        )

    op.drop_column("draft_pick", "target_rank_value", schema="balancer")
    op.drop_column("draft_player", "additional_info", schema="balancer")
    op.drop_column("draft_player", "role_top_heroes", schema="balancer")
    op.drop_column("draft_player", "role_ranks", schema="balancer")
