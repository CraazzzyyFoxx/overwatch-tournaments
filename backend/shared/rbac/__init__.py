from .bootstrap import (
    assign_workspace_system_role,
    ensure_permission_catalog,
    ensure_workspace_system_roles,
    get_workspace_system_role,
    legacy_workspace_role_name_for_user,
    replace_user_workspace_roles,
    user_has_only_workspace_owner_role,
)
from .catalog import (
    PERMISSION_CATALOG,
    WORKSPACE_SYSTEM_ROLE_NAMES,
    PermissionSpec,
    permission_names_for_workspace_role,
)

__all__ = (
    "PERMISSION_CATALOG",
    "WORKSPACE_SYSTEM_ROLE_NAMES",
    "PermissionSpec",
    "assign_workspace_system_role",
    "ensure_permission_catalog",
    "ensure_workspace_system_roles",
    "get_workspace_system_role",
    "legacy_workspace_role_name_for_user",
    "permission_names_for_workspace_role",
    "replace_user_workspace_roles",
    "user_has_only_workspace_owner_role",
)
