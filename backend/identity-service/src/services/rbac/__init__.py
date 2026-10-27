"""RBAC administration: the write surface behind ``rpc.identity.rbac.*``.

Every guard lives in ``rbac_policy``, every statement in the repository layer;
what is left in these services is the flow — ordering, audit trail, cache
invalidation and the transaction boundary.

Audit rows are staged **before** the flow's own ``commit()`` so a rolled-back
mutation cannot keep its trail and a committed one cannot lose it. Where another
service owns the commit (the linked-player flows), the audit row is staged
before handing over, for the same reason. RBAC cache entries are dropped only
after the commit, or a request in between re-caches the RBAC that is going away.
"""

from src.services.rbac.auth_user_admin import AuthUserAdminService, auth_user_admin
from src.services.rbac.permission_admin import PermissionAdminService, permission_admin
from src.services.rbac.permission_denies import PermissionDenyService, permission_denies
from src.services.rbac.role_admin import RoleAdminService, role_admin
from src.services.rbac.session_admin import SessionAdminService, session_admin

__all__ = (
    "AuthUserAdminService",
    "PermissionAdminService",
    "PermissionDenyService",
    "RoleAdminService",
    "SessionAdminService",
    "auth_user_admin",
    "permission_admin",
    "permission_denies",
    "role_admin",
    "session_admin",
)
