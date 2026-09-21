"""Workspace trust tier — the one gate check for self-service workspaces.

Pure by design: no session parameter, no query, no auto-upgrade. A workspace
leaves ``unverified`` only through ``rpc.app.workspaces.verification_set``
(superuser-only).
"""

from __future__ import annotations

from typing import Any

__all__ = ("VERIFICATION_STATUSES", "is_verified_or_trusted")

# Convention, not a DB constraint (the column is a plain ``String(16)``).
VERIFICATION_STATUSES = ("unverified", "verified", "trusted")


def is_verified_or_trusted(workspace: Any) -> bool:
    """May this workspace use metered resources and appear in the public directory?

    One bar for both since 2026-09-07: ``trusted`` is now a badge on the public
    card, not a separate admission gate.
    """
    return workspace.verification_status in ("verified", "trusted")
