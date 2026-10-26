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
    "stats-service",
    "stream-service",
    "tournament-service",
    "analytics-service",
    "shared",
)

DIRECT_WRITE_RE = re.compile(
    r"session\.(?:add|add_all|delete|merge)\(|await session\.get\(|sa\.(?:insert|update|delete)\("
)
#: ``from sqlalchemy import update`` followed by a bare ``update(Model)`` is the same write
#: spelled so that the pattern above cannot see it.
_BARE_WRITE_IMPORT_RE = re.compile(r"^from sqlalchemy import [^\n]*\b(?:insert|update|delete)\b", re.M)
_BARE_WRITE_CALL_RE = re.compile(r"(?<![\w.])(?:insert|update|delete)\(")


def _has_direct_write(text: str) -> bool:
    if DIRECT_WRITE_RE.search(text):
        return True
    return bool(_BARE_WRITE_IMPORT_RE.search(text) and _BARE_WRITE_CALL_RE.search(text))


#: Deliberate non-CRUD access. Adding an entry needs a reason of this kind, not
#: convenience.
APPROVED_DIRECT_WRITE_FILES = {
    # Profile merge: set-based repoints of arbitrary reference tables from the source player to the target.
    "app-service/src/services/admin/user_merge.py",
    "analytics-service/src/services/analytics/flows.py",
    "analytics-service/src/services/ml/inference/match_quality_runner.py",
    "analytics-service/src/services/ml/inference/player_anomaly_runner.py",
    "analytics-service/src/services/ml/inference/runner.py",
    "stats-service/src/services/achievement/engine/runner.py",
    "shared/messaging/outbox.py",
    "shared/rbac/bootstrap.py",
    "tournament-service/src/services/bracket/advancement.py",
    "tournament-service/src/services/bracket/usability.py",
    # Append-only event journal, not CRUD: the realtime rail writes one
    # WorkspaceEvent row per staged event from the session's own before_commit
    # hook, which is where the row has to be created for it to ride the
    # caller's transaction.
    "shared/services/realtime/emit.py",
    # Append-only notification journal, same category as the realtime rail
    # above: ``notify`` stages one row per domain event so it rides the
    # caller's transaction, and a repository ``create`` would flush per
    # recipient -- a fan-out to a six-player roster is one INSERT batch today
    # and would become six round trips. Nothing ever updates or deletes the
    # row either; "delete" is an ``expires_at`` stamp, which DOES go through
    # ``NotificationRepository.retire``.
    "shared/services/notifications.py",
    "tournament-service/src/services/challonge/stage_refs.py",
    # Replacing a delete-orphan collection, not CRUD: ``_apply_seeding`` is a
    # deliberately SYNCHRONOUS helper whose delete half is a collection
    # ``remove``; the insert half is the matching ``session.add``. An async
    # repository create would make the whole seeding path async to move one
    # line.
    "tournament-service/src/services/admin/stage_common.py",
    "balancer-service/src/services/team_export/materialization.py",
    "balancer-service/src/services/team_export/service.py",
    "tournament-service/src/services/admin/encounter.py",
    "tournament-service/src/services/admin/stage/crud.py",
    "tournament-service/src/services/admin/stage/lifecycle.py",
    "tournament-service/src/services/admin/stage/merge.py",
    "tournament-service/src/services/admin/stage/qualification.py",
    "tournament-service/src/services/admin/stage/seeding.py",
    "tournament-service/src/services/admin/team.py",
    "tournament-service/src/services/admin/tournament.py",
    "tournament-service/src/services/registration/service.py",
}

#: Direct writes that predate their repository and are owed one. Every entry is a
#: line to delete, not a pattern to copy: a new file belongs here only if the same
#: change also explains why the repository method cannot exist yet.
PENDING_REPOSITORY_MIGRATION: set[str] = set()

_EXEMPT = APPROVED_DIRECT_WRITE_FILES | PENDING_REPOSITORY_MIGRATION


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = BACKEND_ROOT / root_name
        if not root.exists():
            continue
        files.extend(
            path for path in root.rglob("*.py") if not {"tests", "testing", "scripts", "__pycache__"} & set(path.parts)
        )
    return files


def _writes_directly(relative: str) -> bool:
    path = BACKEND_ROOT / relative
    return path.exists() and _has_direct_write(path.read_text(encoding="utf-8"))


def test_new_direct_db_writes_go_through_shared_repositories() -> None:
    offenders: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if relative.startswith("shared/repository/") or relative in _EXEMPT:
            continue
        if _has_direct_write(path.read_text(encoding="utf-8")):
            offenders.append(relative)

    assert offenders == []


def test_no_exemption_outlives_the_write_it_covers() -> None:
    """A stale exemption is worse than none: it silently re-permits the next direct
    write added to that file. Deleting the listed line is the fix."""
    stale = sorted(relative for relative in _EXEMPT if not _writes_directly(relative))

    assert stale == []
