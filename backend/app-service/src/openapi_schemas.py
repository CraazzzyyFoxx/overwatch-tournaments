"""OpenAPI request/response model map for app-service RPC subjects.

Schemas-only module (no flows/DB) consumed by the export script — see
``shared.rpc.openapi``. Models mirror the return annotations of the flows each
handler calls (src/rpc/*.py + src/services/*/flows.py + src/services/read_registry.py).

Generic CRUD read engine keys are ``<subject>#<entity>`` (rpc.app.read.{get,list}
serve hero/map/gamemode/achievement). Coverage: reference reads + a few bespoke
reads with clear models; the heavier user.* reads are not yet mapped (they fall
back to a generic object in the gateway docs).
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op

from src import schemas

OPERATIONS: dict[str, Op] = {
    # generic CRUD read engine (rpc.app.read.{get,list}#<entity>)
    "rpc.app.read.get#hero": Op(response=schemas.HeroRead),
    "rpc.app.read.list#hero": Op(response=Paginated[schemas.HeroRead]),
    "rpc.app.read.get#map": Op(response=schemas.MapRead),
    "rpc.app.read.list#map": Op(response=Paginated[schemas.MapRead]),
    "rpc.app.read.get#gamemode": Op(response=schemas.GamemodeRead),
    "rpc.app.read.list#gamemode": Op(response=Paginated[schemas.GamemodeRead]),
    "rpc.app.read.get#achievement": Op(response=schemas.AchievementRead),
    "rpc.app.read.list#achievement": Op(response=Paginated[schemas.AchievementRead]),
    # lookups (id+name arrays)
    "rpc.app.heroes.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.maps.lookup": Op(response=schemas.LookupItem, response_array=True),
    "rpc.app.gamemodes.lookup": Op(response=schemas.LookupItem, response_array=True),
    # workspaces
    "rpc.app.workspaces.get": Op(response=schemas.WorkspaceRead),
    "rpc.app.workspaces.list": Op(response=schemas.WorkspaceRead, response_array=True),
    # bespoke reads with clear models
    "rpc.app.statistics.dashboard": Op(response=schemas.DashboardStats),
    "rpc.app.users.get_profile": Op(response=schemas.UserProfile),
}
