"""Personal API keys of the calling user.

Transport only: parse the RPC payload, resolve the caller when the method needs
one, hand off to a service object, serialise the result. Every authorization
decision, query and error message belongs to ``src/services/**``.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.query import build_query_model
from src import schemas
from src.services.api_keys import api_keys

from . import _common as c

__all__ = ("register",)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.identity.list_api_keys")
    async def _list_api_keys(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            qp = build_query_model(schemas.ApiKeyListQueryParams, data.get("query"))
            params = schemas.ApiKeyListParams.from_query_params(qp)
            return c.paginated_dump(await api_keys.list(session, user=user, params=params))

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.create_api_key")
    async def _create_api_key(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            payload = schemas.ApiKeyCreate.model_validate(data)
            result = await api_keys.create(
                session,
                user=user,
                payload=payload,
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )
            return result.model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.update_api_key")
    async def _update_api_key(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            payload = schemas.ApiKeyUpdate.model_validate(data)
            result = await api_keys.update(
                session,
                user=user,
                api_key_id=c.require_int(data, "api_key_id"),
                payload=payload,
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )
            return result.model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.revoke_api_key")
    async def _revoke_api_key(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> None:
            await api_keys.revoke(
                session,
                user=user,
                api_key_id=c.require_int(data, "api_key_id"),
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.api_key.self")
    async def _api_key_self(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        # The one key method reachable *with* a key, and read-only: it answers
        # "which key am I, and what may I do" from the credential already
        # validated on the way in. The four CRUD handlers above stay JWT-only, so
        # a key can neither mint a sibling nor extend its own life.
        async def op(session: AsyncSession, _user: Any, api_key: Any) -> dict:
            if api_key is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key credential required",
                )
            result = await api_keys.describe_self(session, api_key_id=api_key.id)
            return result.model_dump(mode="json")

        return await c.with_active_principal(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.api_key.quota_set")
    async def _api_key_quota_set(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            payload = schemas.ApiKeyQuotaWrite.model_validate(data)
            result = await api_keys.set_quota(
                session,
                user=user,
                api_key_id=c.require_int(data, "api_key_id"),
                limits=payload.limits,
                ip_address=data.get("ip_address"),
                user_agent=data.get("user_agent"),
            )
            return result.model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.api_key.quota_usage")
    async def _api_key_quota_usage(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        async def op(session: AsyncSession, user: Any) -> dict:
            result = await api_keys.quota_usage(
                session,
                user=user,
                api_key_id=c.require_int(data, "api_key_id"),
            )
            return result.model_dump(mode="json")

        return await c.with_active_user(logger, data.get("access_token"), op)

    @broker.subscriber("rpc.identity.api_key.self_quota")
    async def _api_key_self_quota(data: dict, msg: RabbitMessage) -> dict:
        data = data or {}

        # Sibling of ``api_key.self`` rather than a field on it: the descriptor
        # is a cheap row read, this one talks to Redis, and a client polling its
        # budget must not drag the whole descriptor along.
        async def op(session: AsyncSession, _user: Any, api_key: Any) -> dict:
            if api_key is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key credential required",
                )
            result = await api_keys.self_quota_usage(session, api_key_id=api_key.id)
            return result.model_dump(mode="json")

        return await c.with_active_principal(logger, data.get("access_token"), op)
