"""split_domain_schemas

Revision ID: b8e2f4a1c903
Revises: a7634c02717d
Create Date: 2026-04-05 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b8e2f4a1c903"
down_revision: Union[str, None] = "a7634c02717d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create new schemas
    for schema in [
        "overwatch",
        "auth",
        "players",
        "tournament",
        "matches",
        "analytics",
        "achievements",
        "log_processing",
    ]:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # --- Overwatch (static game data) ---
    for t in ["gamemode", "hero", "map"]:
        op.execute(f"ALTER TABLE public.{t} SET SCHEMA overwatch")

    # --- Auth / RBAC ---
    for t in [
        "auth_user",
        "refresh_token",
        "auth_user_player",
        "oauth_connections",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
    ]:
        op.execute(f"ALTER TABLE public.{t} SET SCHEMA auth")
    # Rename: drop auth_ prefix
    op.execute('ALTER TABLE auth.auth_user RENAME TO "user"')
    op.execute("ALTER TABLE auth.auth_user_player RENAME TO user_player")

    # --- Players (game identity) ---
    for t in ["user", "user_discord", "user_battle_tag", "user_twitch"]:
        op.execute(f"ALTER TABLE public.{t} SET SCHEMA players")
    # Rename: drop user_ prefix
    op.execute("ALTER TABLE players.user_discord RENAME TO discord")
    op.execute("ALTER TABLE players.user_battle_tag RENAME TO battle_tag")
    op.execute("ALTER TABLE players.user_twitch RENAME TO twitch")

    # --- Tournament (core structure) ---
    for t in [
        "tournament",
        "tournament_group",
        "team",
        "player",
        "challonge_team",
        "encounter",
        "standing",
    ]:
        op.execute(f"ALTER TABLE public.{t} SET SCHEMA tournament")
    # Rename: drop tournament_ prefix
    op.execute('ALTER TABLE tournament.tournament_group RENAME TO "group"')

    # --- Matches (high-volume match data) ---
    for t in ["match", "match_statistics", "match_kill_feed", "match_assists"]:
        op.execute(f"ALTER TABLE public.{t} SET SCHEMA matches")
    # Rename: drop match_ prefix
    op.execute("ALTER TABLE matches.match_statistics RENAME TO statistics")
    op.execute("ALTER TABLE matches.match_kill_feed RENAME TO kill_feed")
    op.execute("ALTER TABLE matches.match_assists RENAME TO assists")

    # --- Analytics (move + rename: drop analytics_ prefix) ---
    for old, new in [
        ("analytics_algorithms", "algorithms"),
        ("analytics_tournament", "tournament"),
        ("analytics_shifts", "shifts"),
        ("analytics_predictions", "predictions"),
    ]:
        op.execute(f"ALTER TABLE public.{old} SET SCHEMA analytics")
        op.execute(f"ALTER TABLE analytics.{old} RENAME TO {new}")

    # --- Achievements ---
    for t in ["achievement", "achievement_user"]:
        op.execute(f"ALTER TABLE public.{t} SET SCHEMA achievements")
    # Rename: drop achievement_ prefix
    op.execute('ALTER TABLE achievements.achievement_user RENAME TO "user"')

    # --- Log processing ---
    for t in ["log_processing_record", "tournament_discord_channel"]:
        op.execute(f"ALTER TABLE public.{t} SET SCHEMA log_processing")
    # Rename: drop prefixes
    op.execute("ALTER TABLE log_processing.log_processing_record RENAME TO record")
    op.execute(
        "ALTER TABLE log_processing.tournament_discord_channel RENAME TO discord_channel"
    )

    # workspace, workspace_member stay in public


def downgrade() -> None:
    # --- Log processing -> public ---
    op.execute("ALTER TABLE log_processing.record RENAME TO log_processing_record")
    op.execute(
        "ALTER TABLE log_processing.discord_channel RENAME TO tournament_discord_channel"
    )
    for t in ["log_processing_record", "tournament_discord_channel"]:
        op.execute(f"ALTER TABLE log_processing.{t} SET SCHEMA public")

    # --- Achievements -> public ---
    op.execute('ALTER TABLE achievements."user" RENAME TO achievement_user')
    for t in ["achievement", "achievement_user"]:
        op.execute(f"ALTER TABLE achievements.{t} SET SCHEMA public")

    # --- Analytics -> public ---
    for old, new in [
        ("algorithms", "analytics_algorithms"),
        ("tournament", "analytics_tournament"),
        ("shifts", "analytics_shifts"),
        ("predictions", "analytics_predictions"),
    ]:
        op.execute(f"ALTER TABLE analytics.{old} RENAME TO {new}")
        op.execute(f"ALTER TABLE analytics.{new} SET SCHEMA public")

    # --- Matches -> public ---
    op.execute("ALTER TABLE matches.statistics RENAME TO match_statistics")
    op.execute("ALTER TABLE matches.kill_feed RENAME TO match_kill_feed")
    op.execute("ALTER TABLE matches.assists RENAME TO match_assists")
    for t in ["match", "match_statistics", "match_kill_feed", "match_assists"]:
        op.execute(f"ALTER TABLE matches.{t} SET SCHEMA public")

    # --- Tournament -> public ---
    op.execute('ALTER TABLE tournament."group" RENAME TO tournament_group')
    for t in [
        "tournament",
        "tournament_group",
        "team",
        "player",
        "challonge_team",
        "encounter",
        "standing",
    ]:
        op.execute(f"ALTER TABLE tournament.{t} SET SCHEMA public")

    # --- Players -> public ---
    op.execute("ALTER TABLE players.discord RENAME TO user_discord")
    op.execute("ALTER TABLE players.battle_tag RENAME TO user_battle_tag")
    op.execute("ALTER TABLE players.twitch RENAME TO user_twitch")
    for t in ["user", "user_discord", "user_battle_tag", "user_twitch"]:
        op.execute(f"ALTER TABLE players.{t} SET SCHEMA public")

    # --- Auth -> public ---
    op.execute('ALTER TABLE auth."user" RENAME TO auth_user')
    op.execute("ALTER TABLE auth.user_player RENAME TO auth_user_player")
    for t in [
        "auth_user",
        "refresh_token",
        "auth_user_player",
        "oauth_connections",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
    ]:
        op.execute(f"ALTER TABLE auth.{t} SET SCHEMA public")

    # --- Overwatch -> public ---
    for t in ["gamemode", "hero", "map"]:
        op.execute(f"ALTER TABLE overwatch.{t} SET SCHEMA public")

    # Drop schemas (reverse order)
    for schema in [
        "log_processing",
        "achievements",
        "analytics",
        "matches",
        "tournament",
        "players",
        "auth",
        "overwatch",
    ]:
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
