"""Registration, login, session lifecycle and the current-user profile."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from faststream.rabbit.annotations import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from src import schemas
from src.services.auth import auth

from . import _common as c

__all__ = ("register",)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.identity.register")
    async def _register(data: dict, msg: RabbitMessage) -> dict:
        async def run(session: Any) -> dict:
            payload = schemas.UserRegister.model_validate(data or {})
            user = await auth.register(session, payload)
            return schemas.AuthUser.model_validate(user).model_dump(mode="json")

        return await c.envelope_session(logger, "register", run)

    @broker.subscriber("rpc.identity.login")
    async def _login(data: dict, msg: RabbitMessage) -> dict:
        payload = data or {}

        async def run(session: Any) -> dict:
            creds = schemas.UserLogin.model_validate(payload)
            token = await auth.login(
                session,
                creds.email,
                creds.password,
                payload.get("user_agent"),
                payload.get("ip_address"),
            )
            return token.model_dump(mode="json")

        return await c.envelope_session(logger, "login", run)

    @broker.subscriber("rpc.identity.refresh")
    async def _refresh(data: dict, msg: RabbitMessage) -> dict:
        payload = data or {}

        async def run(session: Any) -> dict:
            req = schemas.RefreshTokenRequest.model_validate(payload)
            token = await auth.refresh(
                session,
                req.refresh_token,
                payload.get("user_agent"),
                payload.get("ip_address"),
            )
            return token.model_dump(mode="json")

        return await c.envelope_session(logger, "refresh", run)

    @broker.subscriber("rpc.identity.logout")
    async def _logout(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: Any, user: Any) -> None:
            refresh_token = data.get("refresh_token")
            if not refresh_token:
                raise HTTPException(status_code=422, detail="refresh_token is required")
            await auth.logout(session, user, refresh_token)

        return await c.with_active_user(logger, data.get("access_token"), op, label="logout")

    @broker.subscriber("rpc.identity.logout_all")
    async def _logout_all(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: Any, user: Any) -> None:
            await auth.logout_all(session, user)

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.list_sessions")
    async def _list_sessions(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: Any, user: Any) -> list[dict]:
            summaries = await auth.list_sessions(session, user)
            return [item.model_dump(mode="json") for item in summaries]

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.revoke_session")
    async def _revoke_session(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}
        raw_session_id = data.get("session_id")

        async def op(session: Any, user: Any) -> None:
            try:
                session_uuid = UUID(str(raw_session_id))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid session id")
            await auth.revoke_session(
                session, user, session_uuid, ip_address=data.get("ip_address"), user_agent=data.get("user_agent")
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.get_me")
    async def _get_me(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        # The only method in this module an API key may call: "who am I" reads the
        # owner's profile and changes nothing. Every other handler here touches a
        # session, a credential or the account itself and stays JWT-only.
        async def op(session: Any, user: Any, _api_key: Any) -> dict:
            result = await auth.get_me(session, user.id)
            return result.model_dump(mode="json")

        return await c.with_active_principal(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.update_me")
    async def _update_me(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: Any, user: Any) -> dict:
            payload = schemas.UserUpdate.model_validate(data)
            updated = await auth.update_me(session, user, payload)
            return schemas.AuthUser.model_validate(updated, from_attributes=True).model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.delete_me")
    async def _delete_me(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: Any, user: Any) -> None:
            payload = schemas.AccountDeleteRequest.model_validate(data)
            await auth.delete_me(
                session,
                user,
                current_password=payload.current_password,
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.set_password")
    async def _set_password(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: Any, user: Any) -> None:
            payload = schemas.PasswordSetRequest.model_validate(data)
            await auth.set_password(session, user, payload)

        return await c.with_active_user(logger, data.get("access_token"), op)
