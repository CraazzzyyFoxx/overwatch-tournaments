"""
Data migration script: anak_v4 -> anak_v5

Hybrid approach:
- Phase A: Bulk copy unchanged tables via INSERT...SELECT over dblink
- Phase B: Python-driven migration for transformed tables (tournament + workspace)
- Phase C: Reset sequences
- Phase D: Validate row counts

Usage:
    cd backend
    uv run python scripts/migrate_v4_to_v5.py
"""

import sys

import psycopg


V4_DSN = "postgresql://system:0wJxwO4x3OQXw9unSolw@home.craazzzyyfoxx.me:6432/anak_v4"
V5_DSN = "postgresql://system:0wJxwO4x3OQXw9unSolw@home.craazzzyyfoxx.me:6432/anak_v5"

# Tables that can be copied as-is (no structural changes)
# Order matters: parents before children (FK dependencies)
BULK_COPY_TABLES = [
    # Reference / global tables (no FKs to tournament)
    ("public", "hero"),
    ("public", "gamemode"),
    ("public", "map"),
    ("public", "user"),
    ("public", "user_discord"),
    ("public", "user_battle_tag"),
    ("public", "user_twitch"),
    ("public", "auth_user"),
    ("public", "refresh_token"),
    ("public", "auth_user_player"),
    ("public", "roles"),
    ("public", "permissions"),
    ("public", "user_roles"),
    ("public", "role_permissions"),
    ("public", "oauth_connections"),
    ("public", "achievement"),
    ("public", "analytics_algorithms"),
    # Tournament-dependent tables (tournament must be migrated first via Phase B)
    ("public", "tournament_group"),
    ("public", "team"),
    ("public", "player"),
    ("public", "challonge_team"),
    ("public", "encounter"),
    ("public", "match"),
    ("public", "match_statistics"),
    ("public", "match_kill_feed"),
    ("public", "match_assists"),
    ("public", "standing"),
    ("public", "achievement_user"),
    ("public", "analytics_tournament"),
    ("public", "analytics_shifts"),
    ("public", "analytics_predictions"),
    ("public", "tournament_discord_channel"),
    ("public", "log_processing_record"),
    # Balancer schema
    ("balancer", "tournament_sheet"),
    ("balancer", "balance"),
    ("balancer", "application"),
    ("balancer", "team"),
    ("balancer", "player"),
]


def get_columns(conn: psycopg.Connection, schema: str, table: str) -> list[str]:
    """Get column names for a table."""
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    ).fetchall()
    return [r[0] for r in rows]


def get_v5_columns(conn: psycopg.Connection, schema: str, table: str) -> list[str]:
    """Get column names for a v5 table."""
    return get_columns(conn, schema, table)


def qualify(schema: str, table: str) -> str:
    """Get fully qualified, quoted table name."""
    return f'"{schema}"."{table}"'


def get_row_count(conn: psycopg.Connection, schema: str, table: str) -> int:
    """Get row count for a table."""
    return conn.execute(f"SELECT COUNT(*) FROM {qualify(schema, table)}").fetchone()[0]


def phase_a_bulk_copy(v4: psycopg.Connection, v5: psycopg.Connection) -> None:
    """Copy tables that have identical structure between v4 and v5."""
    print("\n=== Phase A: Bulk copy unchanged tables ===")

    # Disable FK checks for bulk loading
    v5.execute("SET session_replication_role = replica")

    for schema, table in BULK_COPY_TABLES:
        qualified = qualify(schema, table)

        # Get columns that exist in BOTH v4 and v5
        v4_cols = set(get_columns(v4, schema, table))
        v5_cols = set(get_v5_columns(v5, schema, table))
        common_cols = sorted(v4_cols & v5_cols)

        if not common_cols:
            print(f"  SKIP {qualified}: no common columns")
            continue

        cols_str = ", ".join(f'"{c}"' for c in common_cols)

        # Export from v4
        print(f"  Copying {qualified}...", end=" ", flush=True)

        with v4.cursor().copy(f'COPY (SELECT {cols_str} FROM {qualified}) TO STDOUT') as v4_copy:
            with v5.cursor().copy(f'COPY {qualified} ({cols_str}) FROM STDIN') as v5_copy:
                for data in v4_copy:
                    v5_copy.write(data)

        count = get_row_count(v5, schema, table)
        print(f"{count} rows")

    # Re-enable FK checks
    v5.execute("SET session_replication_role = DEFAULT")
    v5.commit()
    print("  FK checks re-enabled")


def phase_b_transform(v4: psycopg.Connection, v5: psycopg.Connection) -> None:
    """Migrate tables that need transformation."""
    print("\n=== Phase B: Transform and migrate ===")

    # 1. Create default workspace
    print("  Creating default workspace...", end=" ", flush=True)
    v5.execute(
        """
        INSERT INTO workspace (id, slug, name, description, is_active, created_at)
        VALUES (1, 'default', 'Default Workspace', 'Migrated from anak_v4', true, now())
        """
    )
    print("done")

    # 2. Migrate tournaments with workspace_id
    print("  Migrating tournaments with workspace_id...", end=" ", flush=True)
    v4_cols = get_columns(v4, "public", "tournament")
    v5_existing_cols = set(get_v5_columns(v5, "public", "tournament"))
    # Only use columns that exist in both v4 and v5 (skip removed cols like league_id)
    common_cols = [c for c in v4_cols if c in v5_existing_cols and c != "workspace_id"]
    cols_str = ", ".join(f'"{c}"' for c in common_cols)

    # Read all tournaments from v4
    rows = v4.execute(f'SELECT {cols_str} FROM "public"."tournament" ORDER BY id').fetchall()

    for row in rows:
        # Build INSERT with workspace_id added
        insert_cols = list(common_cols) + ["workspace_id"]
        insert_values = list(row) + [1]  # workspace_id = 1 (default)
        placeholders = ", ".join(["%s"] * len(insert_values))
        insert_cols_str = ", ".join(f'"{c}"' for c in insert_cols)
        v5.execute(
            f'INSERT INTO "public"."tournament" ({insert_cols_str}) VALUES ({placeholders})',
            insert_values,
        )

    count = get_row_count(v5, "public", "tournament")
    print(f"{count} rows")

    # 3. Create workspace_member for all auth_users
    print("  Creating workspace members...", end=" ", flush=True)
    v5.execute(
        """
        INSERT INTO workspace_member (workspace_id, auth_user_id, role, created_at)
        SELECT 1, id,
            CASE WHEN is_superuser THEN 'owner' ELSE 'member' END,
            now()
        FROM auth_user
        """
    )
    member_count = get_row_count(v5, "public", "workspace_member")
    print(f"{member_count} rows")

    v5.commit()


def phase_c_reset_sequences(v5: psycopg.Connection) -> None:
    """Reset all sequences to max(id) + 1."""
    print("\n=== Phase C: Reset sequences ===")

    all_tables = [("public", t) for _, t in BULK_COPY_TABLES if _ == "public"]
    all_tables.append(("public", "tournament"))
    all_tables.append(("public", "workspace"))
    all_tables.append(("public", "workspace_member"))
    all_tables.extend([("balancer", t) for _, t in BULK_COPY_TABLES if _ == "balancer"])

    for schema, table in all_tables:
        qualified = qualify(schema, table)
        try:
            seq = v5.execute(
                f"SELECT pg_get_serial_sequence('{schema}.{table}', 'id')"
            ).fetchone()[0]
            if seq:
                v5.execute(
                    f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {qualified}), 0) + 1, false)"
                )
        except Exception:
            pass  # Table might not have a serial/identity column

    v5.commit()
    print("  All sequences reset")


def phase_d_validate(v4: psycopg.Connection, v5: psycopg.Connection) -> None:
    """Validate row counts match between v4 and v5."""
    print("\n=== Phase D: Validation ===")

    errors = []
    all_tables = [("public", "tournament")] + list(BULK_COPY_TABLES)

    for schema, table in all_tables:
        v4_count = get_row_count(v4, schema, table)
        v5_count = get_row_count(v5, schema, table)
        status = "OK" if v4_count == v5_count else "MISMATCH"
        qualified = f"{schema}.{table}" if schema != "public" else table
        print(f"  {qualified}: v4={v4_count} v5={v5_count} [{status}]")
        if v4_count != v5_count:
            errors.append(f"{qualified}: v4={v4_count} v5={v5_count}")

    # Check new tables
    ws_count = get_row_count(v5, "public", "workspace")
    wm_count = get_row_count(v5, "public", "workspace_member")
    print(f"  workspace: {ws_count} (new)")
    print(f"  workspace_member: {wm_count} (new)")

    if errors:
        print(f"\n  ERRORS: {len(errors)} table(s) have mismatched row counts:")
        for e in errors:
            print(f"    - {e}")
        return False
    else:
        print("\n  All row counts match!")
        return True


def main() -> None:
    print("anak_v4 -> anak_v5 Data Migration")
    print("=" * 50)

    v4 = psycopg.connect(V4_DSN, autocommit=False)
    v5 = psycopg.connect(V5_DSN, autocommit=False)

    try:
        # Phase B first: create workspace + tournaments (needed as FK target)
        phase_b_transform(v4, v5)

        # Phase A: bulk copy all other tables
        phase_a_bulk_copy(v4, v5)

        # Phase C: reset sequences
        phase_c_reset_sequences(v5)

        # Phase D: validate
        success = phase_d_validate(v4, v5)

        if success:
            print("\nMigration completed successfully!")
            print("Next steps:")
            print("  1. Update backend/env/common.env: POSTGRES_DB=anak_v5")
            print("  2. Restart all services")
            print("  3. Run smoke tests")
        else:
            print("\nMigration completed with warnings. Review mismatches above.")

    except Exception as e:
        print(f"\nERROR: {e}")
        v5.rollback()
        raise
    finally:
        v4.close()
        v5.close()


if __name__ == "__main__":
    main()
