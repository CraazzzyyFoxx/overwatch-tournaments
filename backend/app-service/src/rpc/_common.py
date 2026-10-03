"""Shared helpers for the app-service typed-RPC handlers.

Re-exports ``shared.rpc.common`` — the gateway envelope/param-decoding
plumbing is identical across every typed-RPC service and lives there as the
single source of truth. Only ``gate_tournament`` is genuinely app-service
local (it wraps ``shared.services.tournament.visibility``).
"""

from __future__ import annotations

from functools import partial
from typing import Any

from shared.rpc.common import (
    actor,
    dump,
    identity_user_id,
    optional_actor,
    payload,
    q,
    q1,
    qbool,
    require_active,
    require_id,
    require_permission,
    require_query_int,
    require_superuser,
)
from shared.rpc.common import (
    envelope as _envelope,
)
from shared.services.tournament.visibility import ensure_tournament_viewable

__all__ = (
    "identity_user_id",
    "q",
    "q1",
    "qbool",
    "payload",
    "actor",
    "optional_actor",
    "gate_tournament",
    "require_active",
    "require_superuser",
    "require_permission",
    "require_id",
    "require_query_int",
    "dump",
    "envelope",
)

envelope = partial(_envelope, service="app")


async def gate_tournament(session: Any, data: dict[str, Any], tournament_id: int | None) -> None:
    """404 a hidden tournament for an ineligible viewer (issue #115).

    No-op when ``tournament_id`` is None (a cross-tournament read with no single
    tournament to gate). The route must be AuthOptional so identity reaches here.
    """
    if tournament_id is None:
        return
    await ensure_tournament_viewable(session, optional_actor(data), int(tournament_id))
