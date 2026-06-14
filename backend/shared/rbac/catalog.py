from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    name: str
    resource: str
    action: str
    description: str


WORKSPACE_SYSTEM_ROLE_NAMES = ("owner", "admin", "member")

CRUD = ("read", "create", "update", "delete")


def _permission(resource: str, action: str, description: str | None = None) -> PermissionSpec:
    name = "admin.*" if resource == "*" and action == "*" else f"{resource}.{action}"
    return PermissionSpec(
        name=name,
        resource=resource,
        action=action,
        description=description or f"{resource}.{action}",
    )


def _crud(resource: str) -> tuple[PermissionSpec, ...]:
    return tuple(_permission(resource, action) for action in CRUD)


PERMISSION_CATALOG: tuple[PermissionSpec, ...] = (
    _permission("*", "*", "Workspace-scoped wildcard permission"),
    *_crud("workspace"),
    *_crud("workspace_member"),
    _permission("role", "read"),
    _permission("role", "create"),
    _permission("role", "update"),
    _permission("role", "delete"),
    _permission("role", "assign"),
    _permission("permission", "read"),
    *_crud("api_key"),
    _permission("auth_user", "read"),
    _permission("auth_user", "update"),
    *_crud("user"),
    _permission("oauth_connection", "read"),
    _permission("oauth_connection", "delete"),
    _permission("auth_session", "read"),
    _permission("auth_session", "revoke"),
    *_crud("tournament"),
    *_crud("stage"),
    *_crud("team"),
    _permission("team", "import"),
    _permission("team", "export"),
    *_crud("player"),
    _permission("player", "import"),
    _permission("player", "export"),
    *_crud("match"),
    _permission("match", "sync"),
    *_crud("standing"),
    _permission("standing", "recalculate"),
    *_crud("registration_form"),
    *_crud("registration"),
    _permission("registration", "approve"),
    _permission("registration", "reject"),
    _permission("registration", "check_in"),
    *_crud("registration_status"),
    _permission("registration_status", "check_in"),
    *_crud("balancer"),
    _permission("balancer", "calculate"),
    _permission("balancer", "generate"),
    _permission("balancer", "publish"),
    _permission("balancer", "export"),
    *_crud("analytics"),
    _permission("analytics", "export"),
    _permission("analytics", "recalculate"),
    *_crud("achievement"),
    _permission("achievement", "calculate"),
    _permission("achievement", "import"),
    _permission("achievement", "export"),
    *_crud("hero"),
    _permission("hero", "sync"),
    *_crud("gamemode"),
    _permission("gamemode", "sync"),
    *_crud("map"),
    _permission("map", "sync"),
    *_crud("division_grid"),
    _permission("division_grid", "import"),
    _permission("division_grid", "export"),
    _permission("division_grid", "publish"),
    _permission("division_grid", "sync"),
    *_crud("log"),
    _permission("log", "upload"),
    _permission("log", "stream"),
    _permission("log", "reprocess"),
    *_crud("discord_channel"),
    _permission("discord_channel", "sync"),
    *_crud("challonge"),
    _permission("challonge", "sync"),
    *_crud("asset"),
    _permission("asset", "upload"),
)

_ALL_PERMISSION_NAMES = frozenset(permission.name for permission in PERMISSION_CATALOG)

_GOVERNANCE_RESOURCES = frozenset(("role", "permission"))
_MEMBER_READ_RESOURCES = frozenset(
    (
        "workspace",
        "workspace_member",
        "user",
        "tournament",
        "stage",
        "team",
        "player",
        "match",
        "standing",
        "registration_form",
        "registration",
        "registration_status",
        "balancer",
        "analytics",
        "achievement",
        "hero",
        "gamemode",
        "map",
        "division_grid",
        "log",
        "discord_channel",
        "challonge",
        "asset",
    )
)


def _admin_permission_names() -> tuple[str, ...]:
    names: list[str] = []
    for permission in PERMISSION_CATALOG:
        if permission.name == "admin.*":
            continue
        if permission.resource in _GOVERNANCE_RESOURCES:
            continue
        if permission.name in {"workspace.delete", "workspace_member.delete"}:
            continue
        names.append(permission.name)
    return tuple(names)


def _member_permission_names() -> tuple[str, ...]:
    return tuple(
        permission.name
        for permission in PERMISSION_CATALOG
        if permission.action == "read" and permission.resource in _MEMBER_READ_RESOURCES
    )


def permission_names_for_workspace_role(role_name: str) -> tuple[str, ...]:
    if role_name == "owner":
        return ("admin.*",)
    if role_name == "admin":
        return _admin_permission_names()
    if role_name == "member":
        return _member_permission_names()
    raise ValueError(f"Unknown workspace system role: {role_name}")


def assert_catalog_consistent() -> None:
    if len(_ALL_PERMISSION_NAMES) != len(PERMISSION_CATALOG):
        raise RuntimeError("RBAC permission catalog contains duplicate names")


assert_catalog_consistent()
