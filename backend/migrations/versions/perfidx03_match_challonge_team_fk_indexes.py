"""FK indexes on matches.kill_feed, matches.assists, tournament.challonge_team

``MatchKillFeed`` (``matches.kill_feed``) and ``MatchEvent``
(``matches.assists``) only index a subset of their FK columns in the model
(``killer_id``/``victim_id`` on kill_feed; ``match_id``/``team_id``/``user_id``
on assists) — the remaining FK columns (killer/victim hero+team on kill_feed;
hero/related_* on assists) have no index at all. That forces sequential
scans on two of the highest-volume tables in the schema for any lookup or
``ON DELETE CASCADE`` check keyed on those columns (e.g. deleting a hero or
team cascades through kill_feed/assists with no usable index).

``tournament.challonge_team`` has three unindexed FK columns
(team_id/tournament_id/group_id) as well.

All built CONCURRENTLY (via autocommit_block) so they do not lock writes on
these hot, high-volume tables.

Revision ID: perfidx03
Revises: perfidx02
Create Date: 2026-07-04 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "perfidx03"
down_revision: str | None = "perfidx02"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None

_KILL_FEED_INDEXES = [
    ("ix_matches_kill_feed_killer_hero_id", "killer_hero_id"),
    ("ix_matches_kill_feed_killer_team_id", "killer_team_id"),
    ("ix_matches_kill_feed_victim_team_id", "victim_team_id"),
    ("ix_matches_kill_feed_victim_hero_id", "victim_hero_id"),
]

_ASSISTS_INDEXES = [
    ("ix_matches_assists_hero_id", "hero_id"),
    ("ix_matches_assists_related_team_id", "related_team_id"),
    ("ix_matches_assists_related_user_id", "related_user_id"),
    ("ix_matches_assists_related_hero_id", "related_hero_id"),
]

_CHALLONGE_TEAM_INDEXES = [
    ("ix_tournament_challonge_team_team_id", "team_id"),
    ("ix_tournament_challonge_team_tournament_id", "tournament_id"),
    ("ix_tournament_challonge_team_group_id", "group_id"),
]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, column in _KILL_FEED_INDEXES:
            op.create_index(
                name,
                "kill_feed",
                [column],
                schema="matches",
                unique=False,
                postgresql_concurrently=True,
                if_not_exists=True,
            )
        for name, column in _ASSISTS_INDEXES:
            op.create_index(
                name,
                "assists",
                [column],
                schema="matches",
                unique=False,
                postgresql_concurrently=True,
                if_not_exists=True,
            )
        for name, column in _CHALLONGE_TEAM_INDEXES:
            op.create_index(
                name,
                "challonge_team",
                [column],
                schema="tournament",
                unique=False,
                postgresql_concurrently=True,
                if_not_exists=True,
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _column in _CHALLONGE_TEAM_INDEXES:
            op.drop_index(
                name,
                table_name="challonge_team",
                schema="tournament",
                postgresql_concurrently=True,
                if_exists=True,
            )
        for name, _column in _ASSISTS_INDEXES:
            op.drop_index(
                name,
                table_name="assists",
                schema="matches",
                postgresql_concurrently=True,
                if_exists=True,
            )
        for name, _column in _KILL_FEED_INDEXES:
            op.drop_index(
                name,
                table_name="kill_feed",
                schema="matches",
                postgresql_concurrently=True,
                if_exists=True,
            )
