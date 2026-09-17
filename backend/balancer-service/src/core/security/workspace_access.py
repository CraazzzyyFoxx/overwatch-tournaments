from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rbac import scope_grants
from shared.rpc.identity import credential_type


class WorkspaceAccessPolicy:
    def ensure_workspace_access(
        self,
        user,
        workspace_id: int | None,
        *,
        resource: str = "team",
        action: str = "create",
        api_key_id: int | None = None,
        require_api_key_job_match: bool = False,
    ) -> None:
        if workspace_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required",
            )
        if credential_type(user) == "api_key":
            user_workspace_id = getattr(user, "_api_key_workspace_id", None)
            user_api_key_id = getattr(user, "_api_key_id", None)
            try:
                user_workspace_id = int(user_workspace_id)
                user_api_key_id = int(user_api_key_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key principal")
            if user_workspace_id != int(workspace_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key is not scoped to this workspace",
                )
            if require_api_key_job_match and api_key_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key cannot access jobs created without this key",
                )
            if api_key_id is not None and user_api_key_id != int(api_key_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key cannot access jobs created by another key",
                )
            # Scopes are catalog permission names, so this gate speaks the same
            # vocabulary as RBAC below. It is pinned to ``team.create`` -- the
            # permission every balancer job path guards -- rather than to the
            # ``resource``/``action`` arguments, so it stays a floor a caller
            # cannot lower by declaring a weaker pair. ``scope_grants`` is
            # wildcard-aware, so an ``admin.*`` key passes without enumerating.
            scopes = getattr(user, "_api_key_scopes", []) or []
            if not scope_grants(scopes, "team", "create"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key scope required: team.create",
                )
            if user.has_workspace_permission(workspace_id, resource, action):
                return
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied for workspace {workspace_id}: {resource}.{action} required",
            )

        if user.has_workspace_permission(workspace_id, resource, action):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied for workspace {workspace_id}: {resource}.{action} required",
        )
