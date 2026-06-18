"""identity-svc: headless FastStream worker exposing identity RPC methods.

The Go gateway calls these over RabbitMQ request-reply (reply_to + correlation_id);
a handler simply returns the reply envelope and FastStream answers automatically.
Milestone 1A ships `rpc.identity.validate_token`; 1B+ add login/refresh/oauth/etc.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from faststream import FastStream
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from fastapi import HTTPException
from pydantic import ValidationError

from shared.observability import (
    setup_logging,
    setup_sentry,
    setup_tracing,
    start_worker_metrics_server,
)

from src import schemas
from src.core import db
from src.core.config import settings
from src.core.redis import close_redis, init_redis
from src.schemas.rpc import rpc_error, rpc_ok, status_to_code
from src.services import auth_flows, oauth_flows, service_flows
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

broker = RabbitBroker(settings.rabbitmq_url, logger=logger)
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
    logger.info("identity-svc started")


@app.on_shutdown
async def teardown_worker() -> None:
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

    async def op(session: Any, user: Any) -> None:
        if not provider:
            raise HTTPException(status_code=400, detail="provider is required")
        await oauth_flows.unlink(session, user, provider)

    return await _with_active_user(data.get("access_token"), op)
