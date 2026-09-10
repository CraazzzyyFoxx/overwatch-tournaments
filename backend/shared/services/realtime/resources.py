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

__all__ = ("MANIFEST_PATH", "Resource", "load_manifest", "route_refresh_resources", "scope_kind_of")

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "realtime" / "resources.json"


class Resource(StrEnum):
    TOURNAMENT_DETAIL = "tournament.detail"
    TOURNAMENT_STAGES = "tournament.stages"
    TOURNAMENT_ENCOUNTERS = "tournament.encounters"
    TOURNAMENT_STANDINGS = "tournament.standings"
    TOURNAMENT_TEAMS = "tournament.teams"
    TOURNAMENT_STRUCTURE = "tournament.structure"
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


@cache
def route_refresh_resources() -> frozenset[Resource]:
    """Resources whose staleness the client cannot fix by refetching queries.

    Only ``tournament.structure`` today: the set of sections a tournament page
    has is decided during server rendering, so the client has to re-run the
    route, not a query. This replaces the former ``shouldRefreshRoute`` flag
    that hung off the ``structure_changed`` reason.
    """
    manifest = load_manifest()["resources"]
    return frozenset(Resource(name) for name, spec in manifest.items() if spec.get("route_refresh"))
