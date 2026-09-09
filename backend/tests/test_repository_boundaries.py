"""Direct ORM writes must go through ``shared.repository`` — see
``backend/docs/repository-boundaries.md``.

Two lists, because "allowed" and "not migrated yet" are different claims:
``APPROVED_DIRECT_WRITE_FILES`` is access that is intentionally not CRUD (outbox
draining, bracket advancement, analytics materialization, bulk association-table
updates), and ``PENDING_REPOSITORY_MIGRATION`` is debt with a repository already
owed to it.

Both are ratcheted: an entry that no longer writes directly — or no longer exists
— fails the suite, so finishing a migration forces the line to be deleted. That
guard is why the lists are trustworthy at all; without it the allowlist silently
accumulated twelve entries for files deleted with auth-service and the old
tournament-service HTTP routes.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    "app-service",
    "balancer-service",
    "discord-service",
    "identity-service",
    "parser-service",
    "stream-service",
    "tournament-service",
    "analytics-service",
    "shared",
)

DIRECT_WRITE_RE = re.compile(
    r"session\.(?:add|add_all|delete|merge)\(|await session\.get\(|sa\.(?:insert|update|delete)\("
)

#: Deliberate non-CRUD access. Adding an entry needs a reason of this kind, not
#: convenience.
APPROVED_DIRECT_WRITE_FILES = {
    "analytics-service/src/services/analytics/flows.py",
    "analytics-service/src/services/ml/inference/match_quality_runner.py",
    "analytics-service/src/services/ml/inference/player_anomaly_runner.py",
    "analytics-service/src/services/ml/inference/runner.py",
    "parser-service/src/services/achievement/engine/runner.py",
    "shared/messaging/outbox.py",
    "shared/rbac/bootstrap.py",
    "shared/services/bracket/advancement.py",
    "shared/services/bracket/usability.py",
    "shared/services/division_grid/access.py",
    # Append-only event journal, not CRUD: the realtime rail writes one
    # WorkspaceEvent row per staged event from the session's own before_commit
    # hook, which is where the row has to be created for it to ride the
    # caller's transaction.
    "shared/services/realtime/emit.py",
    "shared/services/stage_refs.py",
    "shared/services/team_export/materialization.py",
    "shared/services/team_export/service.py",
    "tournament-service/src/services/admin/encounter.py",
    "tournament-service/src/services/admin/stage.py",
    "tournament-service/src/services/admin/team.py",
    "tournament-service/src/services/admin/tournament.py",
    "tournament-service/src/services/registration/service.py",
}

#: Direct writes that predate their repository and are owed one. Every entry is a
#: line to delete, not a pattern to copy: a new file belongs here only if the same
#: change also explains why the repository method cannot exist yet.
PENDING_REPOSITORY_MIGRATION = {
    "identity-service/src/services/auth.py",
    "identity-service/src/services/auth_users.py",
    "identity-service/src/services/oauth_accounts.py",
    "identity-service/src/services/rbac_admin.py",
    "identity-service/src/services/sessions.py",
    "shared/services/audit.py",
    "shared/services/encounter/result_audit.py",
    "shared/services/social_identity.py",
    "shared/services/subscriptions/store.py",
    "shared/services/tournament/computation.py",
    "tournament-service/src/services/encounter/captain.py",
    "tournament-service/src/services/encounter/map_report.py",
    "tournament-service/src/services/encounter/pick_ban_session.py",
    "tournament-service/src/services/scrim/service.py",
}

_EXEMPT = APPROVED_DIRECT_WRITE_FILES | PENDING_REPOSITORY_MIGRATION


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = BACKEND_ROOT / root_name
        if not root.exists():
            continue
        files.extend(
            path for path in root.rglob("*.py") if "tests" not in path.parts and "__pycache__" not in path.parts
        )
    return files


def _writes_directly(relative: str) -> bool:
    path = BACKEND_ROOT / relative
    return path.exists() and bool(DIRECT_WRITE_RE.search(path.read_text(encoding="utf-8")))


def test_new_direct_db_writes_go_through_shared_repositories() -> None:
    offenders: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if relative.startswith("shared/repository/") or relative in _EXEMPT:
            continue
        if DIRECT_WRITE_RE.search(path.read_text(encoding="utf-8")):
            offenders.append(relative)

    assert offenders == []


def test_no_exemption_outlives_the_write_it_covers() -> None:
    """A stale exemption is worse than none: it silently re-permits the next direct
    write added to that file. Deleting the listed line is the fix."""
    stale = sorted(relative for relative in _EXEMPT if not _writes_directly(relative))

    assert stale == []
