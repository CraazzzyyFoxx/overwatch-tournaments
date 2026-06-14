from fastapi import HTTPException, status

from src.core.security.api_key_limiter import is_api_key_principal


class WorkspaceAccessPolicy:
    def ensure_workspace_access(
        self,
        user,
        workspace_id: int | None,
        *,
        resource: str = "team",
        action: str = "import",
        api_key_id: int | None = None,
        require_api_key_job_match: bool = False,
    ) -> None:
        if workspace_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required",
            )
        if is_api_key_principal(user):
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
            scopes = getattr(user, "_api_key_scopes", []) or []
            if "balancer.jobs" not in scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key scope required: balancer.jobs",
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
