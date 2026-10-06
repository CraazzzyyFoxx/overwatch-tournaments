from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    name: str
    resource: str
    action: str
    description: str


WORKSPACE_SYSTEM_ROLE_NAMES = ("owner", "admin", "referee", "host", "player")

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
    *_crud("role"),
    _permission("permission", "read"),
    *_crud("api_key"),
    _permission("auth_user", "read"),
    _permission("auth_user", "update"),
    *_crud("user"),
    _permission("oauth_connection", "read"),
    _permission("oauth_connection", "delete"),
    *_crud("auth_session"),
    *_crud("tournament"),
    *_crud("stage"),
    *_crud("team"),
    *_crud("player"),
    *_crud("match"),
    # Split off ``match.update`` so results can be granted without the bracket:
    # ``update`` keeps the encounter's structure (teams, stage, round, best-of,
    # schedule, slot swaps) and the match config (pick-ban rules, report form);
    # ``result`` is the score side -- confirming, reopening, per-map and FFA
    # game results, the live pick-ban overrides of one running match.
    _permission("match", "result", "Enter and correct encounter results"),
    *_crud("standing"),
    *_crud("registration_form"),
    *_crud("registration"),
    _permission("registration", "approve"),
    _permission("registration", "reject"),
    _permission("registration", "check_in"),
    # Roles and the ranks on them are what the balancer builds teams from, so
    # they are split off ``registration.update``: a registration's other fields
    # can be handed to staff who must not move a player's roles or ranks.
    _permission("registration", "roles", "Edit a registration's roles and ranks"),
    *_crud("registration_status"),
    *_crud("balancer"),
    *_crud("custom_game"),
    *_crud("analytics"),
    *_crud("achievement"),
    *_crud("division_grid"),
    *_crud("log"),
    *_crud("discord_channel"),
    *_crud("challonge"),
    *_crud("asset"),
    *_crud("tournament_link"),
    _permission("rank", "read", "Read rank-collection health and fetch history"),
    _permission("rank", "update", "Trigger a rank re-fetch"),
    _permission("subscription", "read", "Read subscription-collection health and check history"),
    _permission("subscription", "update", "Trigger a subscription re-check"),
    _permission("stream", "read", "Read stream live-status and polling health"),
    _permission("stream", "update", "Trigger a stream live-status re-poll"),
    # Workspace-scoped announcements. The platform-wide ones are deliberately
    # NOT reachable through these: a banner every visitor sees is gated on the
    # superuser flag, not on a grant an owner can hand out inside a tenant.
    *_crud("announcement"),
    # Workspace-scoped operator access to the notifications this tenant's own
    # activity produced (``notification.source_workspace_id``). Read and delete
    # only: nobody writes an inbox row by hand -- the flows that cause one do --
    # and "delete" is a retire, which takes the row out of every recipient's
    # inbox, so it is deliberately not part of the member read set.
    _permission("notification", "read", "Read the notifications this workspace produced"),
    _permission("notification", "delete", "Retire a notification this workspace produced"),
    _permission("audit", "read", "Read the platform audit log"),
    # Self-service capabilities: allowed by default for every authenticated user;
    # exist only so an admin can DENY them per user (negative RBAC).
    _permission("account", "avatar", "Change one's own avatar"),
    _permission("account", "rename", "Change one's own name"),
    _permission("account", "social", "Manage one's own social accounts"),
    _permission("registration", "self_register", "Self-register for a tournament"),
    _permission("custom_game", "self_join", "Self-join a pickup mix"),
    # Distinct from the workspace-scoped ``workspace.create`` above, which is a
    # grant held inside a workspace: this one is the platform-wide right to
    # bring a NEW workspace into existence, so denying it revokes self-service
    # creation for one account without touching any workspace role.
    _permission("workspace", "self_create", "Create one's own workspace"),
)

_ALL_PERMISSION_NAMES = frozenset(permission.name for permission in PERMISSION_CATALOG)

_GOVERNANCE_RESOURCES = frozenset(("role", "permission"))
_PLAYER_READ_RESOURCES = frozenset(
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
        "custom_game",
        "analytics",
        "achievement",
        "division_grid",
        "log",
        "discord_channel",
        "challonge",
        "asset",
        "tournament_link",
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


def _player_permission_names() -> tuple[str, ...]:
    return tuple(
        permission.name
        for permission in PERMISSION_CATALOG
        if permission.action == "read" and permission.resource in _PLAYER_READ_RESOURCES
    )


def _host_permission_names() -> tuple[str, ...]:
    """Everything a ``player`` gets, plus full authorship over mixes (custom games).

    A host still needs the ordinary player read access -- hosting a mix means
    seeing rosters, standings, etc. like anyone else -- but on top of that gets
    ``custom_game`` create/update/delete so they can actually run one. See
    ``_require_mix`` in ``balancer-service/src/rpc/custom.py``: membership alone
    no longer opens mixes, this is the grant that does.
    """
    extra = (p.name for p in PERMISSION_CATALOG if p.resource == "custom_game")
    return tuple(dict.fromkeys((*_player_permission_names(), *extra)))


def _referee_permission_names() -> tuple[str, ...]:
    """Everything a ``player`` reads, plus running matches and registrations.

    The staff role with the fewest destructive writes: results inside a bracket
    somebody else built, and the registration queue minus roles and ranks. No
    tournament, stage, team or roster write, and no delete of any kind.
    """
    extra = (
        "match.result",
        "registration.update",
        "registration.approve",
        "registration.reject",
        "registration.check_in",
    )
    return tuple(dict.fromkeys((*_player_permission_names(), *extra)))


def permission_names_for_workspace_role(role_name: str) -> tuple[str, ...]:
    if role_name == "owner":
        return ("admin.*",)
    if role_name == "admin":
        return _admin_permission_names()
    if role_name == "referee":
        return _referee_permission_names()
    if role_name == "host":
        return _host_permission_names()
    if role_name == "player":
        return _player_permission_names()
    raise ValueError(f"Unknown workspace system role: {role_name}")


def assert_catalog_consistent() -> None:
    if len(_ALL_PERMISSION_NAMES) != len(PERMISSION_CATALOG):
        raise RuntimeError("RBAC permission catalog contains duplicate names")


assert_catalog_consistent()
