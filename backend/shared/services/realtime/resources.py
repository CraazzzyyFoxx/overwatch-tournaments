"""The invalidation vocabulary: WHAT went stale.

Hand-written enum, not generated: static members keep type checkers and
autocomplete useful. ``tests/test_realtime_resource_manifest.py`` asserts this
enum is exactly ``shared/realtime/resources.json``, so the two cannot drift —
the same parity check the gateway and the frontend run against their own
tables.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

from shared.services.realtime.scope import ScopeKind

__all__ = ("MANIFEST_PATH", "Resource", "load_manifest", "resource_generation", "scope_kind_of")

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "realtime" / "resources.json"


class Resource(StrEnum):
    TOURNAMENT_DETAIL = "tournament.detail"
    TOURNAMENT_STAGES = "tournament.stages"
    TOURNAMENT_ENCOUNTERS = "tournament.encounters"
    TOURNAMENT_STANDINGS = "tournament.standings"
    TOURNAMENT_TEAMS = "tournament.teams"
    TOURNAMENT_STRUCTURE = "tournament.structure"
    TOURNAMENT_FLOW = "tournament.flow"
    TOURNAMENT_REGISTRATIONS = "tournament.registrations"
    TOURNAMENT_REGISTRATION_FORM = "tournament.registration_form"
    TOURNAMENT_STREAMS = "tournament.streams"
    WORKSPACE_LOGS = "workspace.logs"
    WORKSPACE_PICKUP_MIX = "workspace.pickup_mix"
    WORKSPACE_SUBSCRIPTIONS = "workspace.subscriptions"
    WORKSPACE_ANALYTICS_JOBS = "workspace.analytics_jobs"
    USER_NOTIFICATIONS = "user.notifications"


@cache
def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@cache
def scope_kind_of(resource: Resource) -> ScopeKind:
    """The scope a resource may only ever be published under.

    ``emit`` enforces it: a ``workspace.*`` resource on a tournament scope would
    land on a topic whose subscribers are a different audience entirely.
    """
    return ScopeKind(load_manifest()["resources"][str(resource)]["scope"])


def resource_generation(resource: Resource, scope_id: int | str = "*") -> str:
    """The cache generation an invalidation of ``resource`` moves (``shared.services.cache_generations``).

    ``emit`` bumps it for the scope's id AND for ``*``: a read cached per scope depends on the former, an aggregate
    across every scope of the kind (a user's history across tournaments) on the latter. ``scope_id`` may be a key
    template (``"{params.tournament_id}"``) when a cached read names what it depends on.
    """
    return f"{scope_kind_of(resource)}:{scope_id}:{resource}"
