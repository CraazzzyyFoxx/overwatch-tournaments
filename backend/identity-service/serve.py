"""identity-svc: headless FastStream worker exposing identity RPC methods.

The Go gateway calls these over RabbitMQ request-reply (reply_to + correlation_id);
a handler simply returns the reply envelope and FastStream answers automatically.
Milestone 1A ships `rpc.identity.validate_token`; 1B+ add login/refresh/oauth/etc.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from faststream import FastStream
from faststream.rabbit.annotations import RabbitMessage
from shared.core.errors import BaseAPIException as HTTPException
from pydantic import ValidationError

from shared.observability import (
    make_rabbit_broker,
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)
from shared.rpc.query import build_query_model

from src import schemas
from src.core import db
from src.core.config import settings
from src.core.redis import close_redis, init_redis
from src.core.s3 import s3_client
from src.schemas.rpc import rpc_error, rpc_ok, status_to_code
from src.services import (
    api_key_service,
    auth_flows,
    avatar_flows,
    oauth_flows,
    player_flows,
    rbac_flows,
    service_flows,
)
from src.services.token_validation import validate_token


def _validation_detail(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "validation error"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    msg = first.get("msg", "invalid value")
    return f"{loc}: {msg}" if loc else msg


async def _with_active_user(
    access_token: Any,
    op: Callable[[Any, Any], Awaitable[Any]],
) -> dict:
    """Resolve the active user from a bearer access token, run op, map errors.

    Shared by the authenticated RPC methods (logout-all/sessions/me/set-password).
    """
    if not access_token or not isinstance(access_token, str):
        return rpc_error("forbidden", "Not authenticated")
    try:
        async with db.async_session_maker() as session:
            user = await auth_flows.resolve_active_user(session, access_token)
            result = await op(session, user)
        return rpc_ok(result)
    except ValidationError as exc:
        return rpc_error("unprocessable", _validation_detail(exc))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("authenticated RPC failed")
        return rpc_error("internal", "internal error")

logger = setup_logging(
    service_name="identity-svc",
    log_level=settings.log_level,
    logs_root_path=settings.logs_root_path,
    json_output=settings.json_logging,
)

broker = make_rabbit_broker(settings.rabbitmq_url, logger=logger, prefetch_count=settings.rpc_prefetch_count)
app = FastStream(broker)


@app.on_startup
async def setup_worker() -> None:
    setup_sentry(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        service_name="identity-svc",
        enable_logs=settings.sentry_enable_logs,
        logs_level=settings.sentry_logs_level,
        enable_metrics=settings.sentry_enable_metrics,
        environment=settings.environment,
        release=settings.version,
        http_proxy=settings.sentry_http_proxy_url,
        https_proxy=settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="identity-svc",
        otlp_endpoint=settings.otlp_endpoint,
        enabled=settings.tracing_enabled,
        sampler_name=settings.otel_traces_sampler,
        sampler_arg=settings.otel_traces_sampler_arg,
    )
    if settings.worker_metrics_port:
        start_worker_metrics_server(settings.worker_metrics_port)
    await init_redis()
    await s3_client.start()
    logger.info("identity-svc started")


@app.on_shutdown
async def teardown_worker() -> None:
    await s3_client.close()
    await close_redis()


@broker.subscriber("rpc.identity.validate_token")
async def rpc_validate_token(data: dict, msg: RabbitMessage) -> dict:
    """Validate a bearer access token / API key, returning RBAC TokenPayload."""
    token = (data or {}).get("token")
    if not token or not isinstance(token, str):
        return rpc_error("bad_request", "token is required")

    try:
        async with db.async_session_maker() as session:
            payload = await validate_token(session, token)
        return rpc_ok(payload.model_dump(mode="json"))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("validate_token RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.register")
async def rpc_register(data: dict, msg: RabbitMessage) -> dict:
    try:
        payload = schemas.UserRegister.model_validate(data or {})
    except ValidationError as exc:
        return rpc_error("unprocessable", _validation_detail(exc))
    try:
        async with db.async_session_maker() as session:
            user = await auth_flows.register(session, payload)
            result = schemas.AuthUser.model_validate(user).model_dump(mode="json")
        return rpc_ok(result)
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("register RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.login")
async def rpc_login(data: dict, msg: RabbitMessage) -> dict:
    try:
        creds = schemas.UserLogin.model_validate(data or {})
    except ValidationError as exc:
        return rpc_error("unprocessable", _validation_detail(exc))
    data = data or {}
    try:
        async with db.async_session_maker() as session:
            token = await auth_flows.login(
                session, creds.email, creds.password, data.get("user_agent"), data.get("ip_address")
            )
        return rpc_ok(token.model_dump(mode="json"))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("login RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.refresh")
async def rpc_refresh(data: dict, msg: RabbitMessage) -> dict:
    try:
        req = schemas.RefreshTokenRequest.model_validate(data or {})
    except ValidationError as exc:
        return rpc_error("unprocessable", _validation_detail(exc))
    data = data or {}
    try:
        async with db.async_session_maker() as session:
            token = await auth_flows.refresh(
                session, req.refresh_token, data.get("user_agent"), data.get("ip_address")
            )
        return rpc_ok(token.model_dump(mode="json"))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("refresh RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.logout")
async def rpc_logout(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token:
        return rpc_error("forbidden", "Not authenticated")
    if not refresh_token:
        return rpc_error("unprocessable", "refresh_token is required")
    try:
        async with db.async_session_maker() as session:
            user = await auth_flows.resolve_active_user(session, access_token)
            await auth_flows.logout(session, user, refresh_token)
        return rpc_ok(None)
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("logout RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.logout_all")
async def rpc_logout_all(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        await auth_flows.logout_all(session, user)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.list_sessions")
async def rpc_list_sessions(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> list[dict]:
        sessions = await auth_flows.list_sessions(session, user)
        return [s.model_dump(mode="json") for s in sessions]

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.revoke_session")
async def rpc_revoke_session(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}
    raw_session_id = data.get("session_id")

    async def op(session: Any, user: Any) -> None:
        try:
            session_uuid = UUID(str(raw_session_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid session id")
        await auth_flows.revoke_session(session, user, session_uuid)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.get_me")
async def rpc_get_me(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        result = await auth_flows.get_me(session, user.id)
        return result.model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.update_me")
async def rpc_update_me(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        payload = schemas.UserUpdate.model_validate(data)
        updated = await auth_flows.update_me(session, user, payload)
        return schemas.AuthUser.model_validate(updated, from_attributes=True).model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.set_password")
async def rpc_set_password(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        payload = schemas.PasswordSetRequest.model_validate(data)
        await auth_flows.set_password(session, user, payload)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.service_token")
async def rpc_service_token(data: dict, msg: RabbitMessage) -> dict:
    try:
        req = schemas.ServiceTokenRequest.model_validate(data or {})
    except ValidationError as exc:
        return rpc_error("unprocessable", _validation_detail(exc))
    try:
        token = service_flows.issue_service_token(req.client_id, req.client_secret)
        return rpc_ok(token.model_dump(mode="json"))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("service_token RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.validate_service_token")
async def rpc_validate_service_token(data: dict, msg: RabbitMessage) -> dict:
    token = (data or {}).get("token")
    if not token or not isinstance(token, str):
        return rpc_error("unauthorized", "Invalid service token")
    try:
        payload = service_flows.validate_service_token(token)
        return rpc_ok(payload.model_dump(mode="json"))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("validate_service_token RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.invalidate_session")
async def rpc_invalidate_session(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}
    token = data.get("token")
    if not token or not isinstance(token, str):
        return rpc_error("forbidden", "Not authenticated")
    try:
        user_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        return rpc_error("bad_request", "Invalid user id")
    try:
        await service_flows.invalidate_session(token, user_id)
        return rpc_ok(None)
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("invalidate_session RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.oauth_providers")
async def rpc_oauth_providers(data: dict, msg: RabbitMessage) -> dict:
    return rpc_ok([p.model_dump(mode="json") for p in oauth_flows.list_providers()])


@broker.subscriber("rpc.identity.oauth_url")
async def rpc_oauth_url(data: dict, msg: RabbitMessage) -> dict:
    provider = (data or {}).get("provider")
    if not provider or not isinstance(provider, str):
        return rpc_error("bad_request", "provider is required")
    try:
        return rpc_ok(oauth_flows.get_url(provider).model_dump(mode="json"))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("oauth_url RPC failed")
        return rpc_error("internal", "internal error")


@broker.subscriber("rpc.identity.oauth_callback")
async def rpc_oauth_callback(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}
    provider, code, state = data.get("provider"), data.get("code"), data.get("state")
    if not (provider and code and state):
        return rpc_error("unprocessable", "provider, code and state are required")
    try:
        async with db.async_session_maker() as session:
            token = await oauth_flows.callback(
                session, provider, code, state, data.get("user_agent"), data.get("ip_address")
            )
        return rpc_ok(token.model_dump(mode="json"))
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("oauth_callback RPC failed")
        return rpc_error("internal", f"OAuth authentication failed for {provider}")


@broker.subscriber("rpc.identity.oauth_link")
async def rpc_oauth_link(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}
    provider, code, state = data.get("provider"), data.get("code"), data.get("state")

    async def op(session: Any, user: Any) -> dict:
        if not (provider and code and state):
            raise HTTPException(status_code=422, detail="provider, code and state are required")
        return await oauth_flows.link(session, user, provider, code, state)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.oauth_connections")
async def rpc_oauth_connections(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> list[dict]:
        conns = await oauth_flows.connections(session, user)
        return [c.model_dump(mode="json") for c in conns]

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.oauth_unlink")
async def rpc_oauth_unlink(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}
    provider = data.get("provider")
    # Optional: target one specific connection when several of the same provider
    # are linked; omitted = unlink all connections for the provider.
    provider_user_id = data.get("provider_user_id")

    async def op(session: Any, user: Any) -> None:
        if not provider:
            raise HTTPException(status_code=400, detail="provider is required")
        await oauth_flows.unlink(session, user, provider, provider_user_id=provider_user_id)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.list_api_keys")
async def rpc_list_api_keys(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        qp = build_query_model(schemas.ApiKeyListQueryParams, data.get("query"))
        params = schemas.ApiKeyListParams.from_query_params(qp)
        res = await api_key_service.list_api_keys(session, user=user, params=params)
        return _paginated_dump(res)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.create_api_key")
async def rpc_create_api_key(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        payload = schemas.ApiKeyCreate.model_validate(data)
        result = await api_key_service.create_api_key(session, user=user, payload=payload)
        return result.model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.update_api_key")
async def rpc_update_api_key(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        try:
            api_key_id = int(data.get("api_key_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="api_key_id is required")
        payload = schemas.ApiKeyUpdate.model_validate(data)
        result = await api_key_service.update_api_key(
            session, user=user, api_key_id=api_key_id, payload=payload
        )
        return result.model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.revoke_api_key")
async def rpc_revoke_api_key(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        try:
            api_key_id = int(data.get("api_key_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="api_key_id is required")
        await api_key_service.revoke_api_key(session, user=user, api_key_id=api_key_id)

    return await _with_active_user(data.get("access_token"), op)


# --- RBAC admin (typed; ports src/routes/rbac.py via src/services/rbac_flows.py) ---
#
# Authed RPC methods resolve the active user from the gateway-injected bearer
# access_token via _with_active_user, then rbac_flows runs the full permission
# checks (mirroring the routes' Depends()), the service calls, the exact 403/404
# semantics, and the RBAC cache-invalidation side effects.


def _opt_int(data: dict, key: str) -> int | None:
    raw = data.get(key)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{key} must be an integer")


def _opt_bool(data: dict, key: str) -> bool | None:
    raw = data.get(key)
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
    raise HTTPException(status_code=422, detail=f"{key} must be a boolean")


def _opt_str(data: dict, key: str) -> str | None:
    raw = data.get(key)
    if raw is None or raw == "":
        return None
    return str(raw)


def _paginated_dump(res: dict) -> dict:
    """Serialize a service-layer ``{results, total, page, per_page}`` envelope.

    ``results`` holds Pydantic models; everything else is passed through (so an
    optional ``counts`` model is serialized too).
    """
    out: dict[str, Any] = {
        "results": [item.model_dump(mode="json") for item in res["results"]],
        "total": res["total"],
        "page": res["page"],
        "per_page": res["per_page"],
    }
    counts = res.get("counts")
    if counts is not None:
        out["counts"] = counts.model_dump(mode="json")
    return out


@broker.subscriber("rpc.identity.rbac.list_permissions")
async def rpc_rbac_list_permissions(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        qp = build_query_model(schemas.PermissionListQueryParams, data.get("query"))
        params = schemas.PermissionListParams.from_query_params(qp)
        res = await rbac_flows.list_permissions(session, user, params)
        return _paginated_dump(res)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.create_permission")
async def rpc_rbac_create_permission(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        payload = schemas.PermissionCreate.model_validate(data)
        permission = await rbac_flows.create_permission(session, user, payload)
        return schemas.PermissionRead.model_validate(permission, from_attributes=True).model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.delete_permission")
async def rpc_rbac_delete_permission(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        permission_id = _opt_int(data, "permission_id")
        if permission_id is None:
            raise HTTPException(status_code=422, detail="permission_id is required")
        await rbac_flows.delete_permission(session, user, permission_id)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.list_roles")
async def rpc_rbac_list_roles(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        qp = build_query_model(schemas.RoleListQueryParams, data.get("query"))
        params = schemas.RoleListParams.from_query_params(qp)
        res = await rbac_flows.list_roles(session, user, params)
        return _paginated_dump(res)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.get_role")
async def rpc_rbac_get_role(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        role_id = _opt_int(data, "role_id")
        if role_id is None:
            raise HTTPException(status_code=422, detail="role_id is required")
        role = await rbac_flows.get_role(session, user, role_id)
        return schemas.RoleWithPermissions.model_validate(role, from_attributes=True).model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.create_role")
async def rpc_rbac_create_role(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        payload = schemas.RoleCreate.model_validate(data)
        role = await rbac_flows.create_role(session, user, payload)
        return schemas.RoleRead.model_validate(role, from_attributes=True).model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.update_role")
async def rpc_rbac_update_role(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        role_id = _opt_int(data, "role_id")
        if role_id is None:
            raise HTTPException(status_code=422, detail="role_id is required")
        payload = schemas.RoleUpdate.model_validate(data)
        role = await rbac_flows.update_role(session, user, role_id, payload)
        return schemas.RoleRead.model_validate(role, from_attributes=True).model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.delete_role")
async def rpc_rbac_delete_role(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        role_id = _opt_int(data, "role_id")
        if role_id is None:
            raise HTTPException(status_code=422, detail="role_id is required")
        await rbac_flows.delete_role(session, user, role_id)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.list_auth_users")
async def rpc_rbac_list_auth_users(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        qp = build_query_model(schemas.AuthUserListQueryParams, data.get("query"))
        params = schemas.AuthUserListParams.from_query_params(qp)
        res = await rbac_flows.list_auth_users(session, user, params)
        return _paginated_dump(res)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.get_auth_user")
async def rpc_rbac_get_auth_user(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        user_id = _opt_int(data, "user_id")
        if user_id is None:
            raise HTTPException(status_code=422, detail="user_id is required")
        detail = await rbac_flows.get_auth_user(session, user, user_id)
        return detail.model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.assign_linked_player")
async def rpc_rbac_assign_linked_player(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        user_id = _opt_int(data, "user_id")
        if user_id is None:
            raise HTTPException(status_code=422, detail="user_id is required")
        payload = schemas.AuthUserPlayerLinkAssign.model_validate(data)
        await rbac_flows.assign_linked_player_to_auth_user(session, user, user_id, payload)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.remove_linked_player")
async def rpc_rbac_remove_linked_player(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        user_id = _opt_int(data, "user_id")
        player_id = _opt_int(data, "player_id")
        if user_id is None:
            raise HTTPException(status_code=422, detail="user_id is required")
        if player_id is None:
            raise HTTPException(status_code=422, detail="player_id is required")
        await rbac_flows.remove_linked_player_from_auth_user(session, user, user_id, player_id)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.assign_role")
async def rpc_rbac_assign_role(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        payload = schemas.UserRoleAssign.model_validate(data)
        await rbac_flows.assign_role_to_user(session, user, payload)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.remove_role")
async def rpc_rbac_remove_role(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        payload = schemas.UserRoleRemove.model_validate(data)
        await rbac_flows.remove_role_from_user(session, user, payload)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.get_user_roles")
async def rpc_rbac_get_user_roles(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> list[dict]:
        user_id = _opt_int(data, "user_id")
        if user_id is None:
            raise HTTPException(status_code=422, detail="user_id is required")
        roles = await rbac_flows.get_user_roles(session, user, user_id)
        return [schemas.RoleRead.model_validate(r, from_attributes=True).model_dump(mode="json") for r in roles]

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.list_user_denies")
async def rpc_rbac_list_user_denies(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> list[dict]:
        user_id = _opt_int(data, "user_id")
        if user_id is None:
            raise HTTPException(status_code=422, detail="user_id is required")
        return await rbac_flows.list_user_denies(session, user, user_id)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.add_user_deny")
async def rpc_rbac_add_user_deny(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> list[dict]:
        user_id = _opt_int(data, "user_id")
        permission_id = _opt_int(data, "permission_id")
        if user_id is None or permission_id is None:
            raise HTTPException(status_code=422, detail="user_id and permission_id are required")
        return await rbac_flows.add_user_deny(session, user, user_id, permission_id, reason=data.get("reason"))

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.remove_user_deny")
async def rpc_rbac_remove_user_deny(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> list[dict]:
        user_id = _opt_int(data, "user_id")
        permission_id = _opt_int(data, "permission_id")
        if user_id is None or permission_id is None:
            raise HTTPException(status_code=422, detail="user_id and permission_id are required")
        return await rbac_flows.remove_user_deny(session, user, user_id, permission_id)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.list_oauth_connections")
async def rpc_rbac_list_oauth_connections(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        qp = build_query_model(schemas.OAuthConnectionListQueryParams, data.get("query"))
        params = schemas.OAuthConnectionListParams.from_query_params(qp)
        res = await rbac_flows.list_oauth_connections(session, user, params)
        return _paginated_dump(res)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.list_sessions")
async def rpc_rbac_list_sessions(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        qp = build_query_model(schemas.SessionListQueryParams, data.get("query"))
        params = schemas.SessionListParams.from_query_params(qp)
        res = await rbac_flows.list_auth_sessions(session, user, params)
        return _paginated_dump(res)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.rbac.delete_oauth_connection")
async def rpc_rbac_delete_oauth_connection(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        connection_id = _opt_int(data, "connection_id")
        if connection_id is None:
            raise HTTPException(status_code=422, detail="connection_id is required")
        await rbac_flows.delete_oauth_connection(session, user, connection_id)

    return await _with_active_user(data.get("access_token"), op)


# --- Player linking (typed; ports src/routes/player.py via player_flows) ---


@broker.subscriber("rpc.identity.player.link")
async def rpc_player_link(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        payload = schemas.PlayerLinkRequest.model_validate(data)
        result = await player_flows.link_player(session, user, payload)
        return result.model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.player.unlink")
async def rpc_player_unlink(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> None:
        player_id = _opt_int(data, "player_id")
        if player_id is None:
            raise HTTPException(status_code=422, detail="player_id is required")
        await player_flows.unlink_player(session, user, player_id)

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.player.linked")
async def rpc_player_linked(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> list[dict]:
        players = await player_flows.get_linked_players(session, user)
        return [p.model_dump(mode="json") for p in players]

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.player.set_primary")
async def rpc_player_set_primary(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        player_id = _opt_int(data, "player_id")
        if player_id is None:
            raise HTTPException(status_code=422, detail="player_id is required")
        return await player_flows.set_primary_player(session, user, player_id)

    return await _with_active_user(data.get("access_token"), op)


# --- Current-user avatar (typed; ports POST/DELETE /me/avatar via avatar_flows) ---


@broker.subscriber("rpc.identity.me.avatar_set")
async def rpc_me_avatar_set(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        if user.is_denied("account", "avatar"):
            raise HTTPException(status_code=403, detail="You are not allowed to change your avatar")
        raw = data.get("content_b64")
        if not isinstance(raw, str) or not raw:
            raise HTTPException(status_code=422, detail="content_b64 is required")
        try:
            file_data = base64.b64decode(raw)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="invalid base64 content") from exc
        content_type = data.get("content_type")
        updated = await avatar_flows.set_avatar(
            session,
            user,
            s3_client,
            file_data,
            content_type if isinstance(content_type, str) else "application/octet-stream",
        )
        return schemas.AuthUser.model_validate(updated, from_attributes=True).model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)


@broker.subscriber("rpc.identity.me.avatar_delete")
async def rpc_me_avatar_delete(data: dict, msg: RabbitMessage) -> dict:
    data = data or {}

    async def op(session: Any, user: Any) -> dict:
        if user.is_denied("account", "avatar"):
            raise HTTPException(status_code=403, detail="You are not allowed to change your avatar")
        updated = await avatar_flows.delete_avatar(session, user, s3_client)
        return schemas.AuthUser.model_validate(updated, from_attributes=True).model_dump(mode="json")

    return await _with_active_user(data.get("access_token"), op)
