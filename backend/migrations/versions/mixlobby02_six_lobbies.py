"""Raise a mix's ceiling from two lobbies to six.

Revision ID: mixlobby02
Revises: roleset01
Create Date: 2026-10-08 00:00:00.000000

Nothing about the shape of the data changes -- a lobby was already a row, a pin
was already an index -- only the four CHECKs that spelled "two" do. Lobbies are
now ``A``..``F``: ``custom_game.lobby_count`` is ``1..6``, and every lobby index
(a lobby row, a pin, the lobby a recorded match was played in) is ``0..5``.

``downgrade()`` has to make the data fit two lobbies again before it can narrow
the CHECKs: lobby rows past B are deleted (their stored matchup is lost, same as
``set_lobby_count`` going down), pins past B are cleared and ``lobby_count`` is
clamped. Recorded matches are NOT rewritten -- a played match belongs to the
lobby that played it, and moving it to lobby B would be an invented fact -- so a
downgrade with such matches in the history raises instead.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "mixlobby02"
down_revision: str | Sequence[str] | None = "roleset01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (schema, table, constraint, wide CHECK, old two-lobby CHECK)
_CHECKS = (
    (
        "balancer",
        "custom_game",
        "ck_custom_game_lobby_count",
        "lobby_count BETWEEN 1 AND 6",
        "lobby_count BETWEEN 1 AND 2",
    ),
    (
        "balancer",
        "custom_game_lobby",
        "ck_custom_game_lobby_index",
        "lobby_index BETWEEN 0 AND 5",
        "lobby_index BETWEEN 0 AND 1",
    ),
    (
        "balancer",
        "custom_game_player",
        "ck_custom_game_player_lobby_pin",
        "lobby_pin BETWEEN 0 AND 5",
        "lobby_pin BETWEEN 0 AND 1",
    ),
    (
        "casual",
        "match",
        "ck_casual_match_lobby_index",
        "lobby_index BETWEEN 0 AND 5",
        "lobby_index BETWEEN 0 AND 1",
    ),
)


def _recreate(wide: bool) -> None:
    for schema, table, name, wide_sql, narrow_sql in _CHECKS:
        op.drop_constraint(name, table, schema=schema, type_="check")
        op.create_check_constraint(name, table, wide_sql if wide else narrow_sql, schema=schema)


def upgrade() -> None:
    _recreate(wide=True)


def downgrade() -> None:
    played = op.get_bind().exec_driver_sql("SELECT count(*) FROM casual.match WHERE lobby_index > 1").scalar()
    if played:
        raise RuntimeError(f"{played} recorded match(es) were played in lobby C..F; refusing to rewrite their lobby")
    op.execute("DELETE FROM balancer.custom_game_lobby WHERE lobby_index > 1")
    op.execute("UPDATE balancer.custom_game_player SET lobby_pin = NULL WHERE lobby_pin > 1")
    op.execute("UPDATE balancer.custom_game SET lobby_count = 2 WHERE lobby_count > 2")
    _recreate(wide=False)
