"""Price the operations the quota gate now charges.

Revision ID: quota0002
Revises: quota0001
Create Date: 2026-09-17 00:00:00.000000

``quota0001`` seeded only ``balancer.job``, because a row in ``quota.operation``
with no call site is dead weight -- and a call site with no row costs nothing
beyond its request token, which is the safe direction. This revision adds a row
for every operation that now calls ``shared.quota``, so the expensive ones
finally spend the daily budget they were always meant to.

Costs are relative, not absolute: 1 is "a normal job", and the rest are
multiples of how much CPU, third-party quota or storage one call consumes. They
are data precisely so re-pricing an operation is an ops decision rather than a
deploy -- ``analytics.train`` at 10 is a guess to be corrected against live
numbers, not a fact.

The seeded plans allow 100 heavy units per day per key, so these prices mean
roughly 100 balancer jobs, 20 Challonge imports or 10 model trainings a day on
the launch defaults. Nothing here tightens a per-request cap.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "quota0002"
down_revision: str | Sequence[str] | None = "quota0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (slug, cost, description)
OPERATIONS: tuple[tuple[str, int, str], ...] = (
    ("balancer.balance_export", 3, "Materializes a balance into tournament teams, players and standings"),
    ("balancer.balance_ranks_export", 3, "Rewrites tournament.player ranks from a saved balance"),
    ("balancer.teams_import", 2, "Imports a multi-MB team payload and rewrites the roster"),
    ("balancer.teams_export", 2, "Materializes every complete registered team"),
    ("parser.logs.upload", 1, "Stores an uploaded match log and queues its parse"),
    ("parser.logs.process_tournament", 5, "Re-parses every log of one tournament"),
    ("parser.ach.import", 5, "Imports portable achievement rules, S3 and DB writes per rule"),
    ("parser.ach.export", 2, "Exports achievement rules"),
    ("parser.ach.lib_import", 5, "Imports the achievement library"),
    ("parser.ach.calculate", 3, "Recomputes achievements for a workspace"),
    ("parser.ach.calculate_tournament", 2, "Recomputes achievements for one tournament"),
    ("tournament.challonge_import", 5, "Imports a bracket from Challonge, spends their API quota"),
    ("tournament.challonge_export", 5, "Pushes a bracket to Challonge, spends their API quota"),
    ("tournament.sheet_sync", 3, "Syncs a registration Google Sheet"),
    ("tournament.sheet_players_export", 2, "Exports registered players to a Google Sheet"),
    ("analytics.train", 10, "Trains the analytics models: the most CPU-expensive call in the platform"),
    ("analytics.infer", 5, "Runs inference over a tournament"),
    ("analytics.recalculate", 5, "Recomputes analytics for a tournament"),
    ("app.assets.upload", 1, "Stores a workspace asset"),
    ("app.workspace_icon_upload", 1, "Stores a workspace icon"),
    ("stream.repoll", 3, "Re-polls every live tournament against the shared Helix bucket"),
)


def _values() -> str:
    # Literal SQL, not bound parameters: ``op.execute`` also renders offline
    # (``alembic upgrade --sql``), where a parameter list cannot follow.
    rows = []
    for slug, cost, description in OPERATIONS:
        assert "'" not in slug and "'" not in description, slug
        rows.append(f"    ('{slug}', {cost}, true, '{description}')")
    return ",\n".join(rows)


def upgrade() -> None:
    op.execute(
        "INSERT INTO quota.operation (slug, cost, enabled, description) VALUES\n"
        f"{_values()}\n"
        "ON CONFLICT (slug) DO UPDATE SET cost = EXCLUDED.cost, description = EXCLUDED.description"
    )


def downgrade() -> None:
    slugs = ", ".join(f"'{slug}'" for slug, _, _ in OPERATIONS)
    op.execute(f"DELETE FROM quota.operation WHERE slug IN ({slugs})")
