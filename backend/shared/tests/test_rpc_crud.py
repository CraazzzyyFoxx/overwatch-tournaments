"""Unit tests for the shared CRUD-over-RPC engine + identity rehydration.

Runs under stdlib unittest (no pytest-asyncio needed), matching the repo's
IsolatedAsyncioTestCase convention. Uses fake hooks + a fake session factory, so
no database is required — the generic BaseRepository path is covered by the
per-service integration tests.
"""

from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase

from fastapi import HTTPException
from pydantic import BaseModel

from shared.rpc.crud import CrudDispatcher, EntityConfig
from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission, rehydrate_user

SUPERUSER: dict[str, Any] = {"user_id": 1, "is_superuser": True}
# Member with only team.update in workspace 7.
MEMBER: dict[str, Any] = {
    "user_id": 2,
    "is_superuser": False,
    "roles": [],
    "permissions": [],
    "workspaces": [
        {
            "workspace_id": 7,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "team", "action": "update"}],
        }
    ],
}


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _session_factory() -> _FakeSession:
    return _FakeSession()


class _Dummy:
    """Stand-in for a SQLAlchemy model (the service-hook path never touches it)."""


class _CreateSchema(BaseModel):
    name: str


class _UpdateSchema(BaseModel):
    name: str | None = None


async def _ws7(session: Any, obj_id: int) -> int:
    return 7


async def _ws7_for_create(session: Any, data: dict[str, Any]) -> int:
    return 7


async def _serialize(session: Any, obj: Any) -> dict[str, Any]:
    return {"id": getattr(obj, "id", 0), "name": getattr(obj, "name", None)}


def _team_cfg(**overrides: Any) -> EntityConfig:
    base: dict[str, Any] = dict(
        entity="team",
        model=_Dummy,
        permission_resource="team",
        serializer=_serialize,
        create_schema=_CreateSchema,
        update_schema=_UpdateSchema,
        resolve_ws_from_id=_ws7,
        resolve_ws_for_create=_ws7_for_create,
        actions=frozenset({"create", "get", "update", "delete"}),
    )
    base.update(overrides)
    return EntityConfig(**base)


class RehydrateTests(IsolatedAsyncioTestCase):
    def test_superuser_passes_any_permission(self) -> None:
        user = rehydrate_user(SUPERUSER)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.has_workspace_permission(99, "team", "delete"))

    def test_workspace_permission_is_scoped(self) -> None:
        user = rehydrate_user(MEMBER)
        self.assertTrue(user.has_workspace_permission(7, "team", "update"))
        self.assertFalse(user.has_workspace_permission(7, "team", "delete"))  # action not granted
        self.assertFalse(user.has_workspace_permission(8, "team", "update"))  # other workspace

    def test_missing_identity_raises(self) -> None:
        with self.assertRaises(MissingIdentityError):
            rehydrate_user(None)
        with self.assertRaises(MissingIdentityError):
            rehydrate_user({"is_superuser": True})  # no user_id

    def test_ensure_permission_denial(self) -> None:
        user = rehydrate_user(MEMBER)
        with self.assertRaises(HTTPException) as ctx:
            ensure_workspace_permission(user, 7, "team", "delete")
        self.assertEqual(ctx.exception.status_code, 403)


class DispatcherTests(IsolatedAsyncioTestCase):
    def _dispatcher(self, cfg: EntityConfig) -> CrudDispatcher:
        return CrudDispatcher({"team": cfg}, _session_factory)

    async def test_update_via_hook_ok(self) -> None:
        async def svc_update(session: Any, obj_id: int, payload: _UpdateSchema, data: Any) -> _Dummy:
            obj = _Dummy()
            obj.id = obj_id  # type: ignore[attr-defined]
            obj.name = payload.name  # type: ignore[attr-defined]
            return obj

        dispatcher = self._dispatcher(_team_cfg(service_update=svc_update))
        res = await dispatcher.do_update({"entity": "team", "id": 5, "identity": SUPERUSER, "payload": {"name": "X"}})
        self.assertEqual(res, {"ok": True, "data": {"id": 5, "name": "X"}})

    async def test_member_allowed_action_runs(self) -> None:
        async def svc_update(session: Any, obj_id: int, payload: _UpdateSchema, data: Any) -> _Dummy:
            obj = _Dummy()
            obj.id = obj_id  # type: ignore[attr-defined]
            obj.name = "ok"  # type: ignore[attr-defined]
            return obj

        dispatcher = self._dispatcher(_team_cfg(service_update=svc_update))
        res = await dispatcher.do_update({"entity": "team", "id": 5, "identity": MEMBER, "payload": {"name": "X"}})
        self.assertTrue(res["ok"])  # MEMBER has team.update in ws 7

    async def test_delete_permission_denied(self) -> None:
        async def svc_delete(session: Any, obj_id: int, data: Any) -> None:
            raise AssertionError("hook must not run when permission is denied")

        dispatcher = self._dispatcher(_team_cfg(service_delete=svc_delete))
        res = await dispatcher.do_delete({"entity": "team", "id": 5, "identity": MEMBER})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "forbidden")

    async def test_delete_via_hook_ok_returns_null(self) -> None:
        async def svc_delete(session: Any, obj_id: int, data: Any) -> None:
            return None

        dispatcher = self._dispatcher(_team_cfg(service_delete=svc_delete))
        res = await dispatcher.do_delete({"entity": "team", "id": 5, "identity": SUPERUSER})
        self.assertEqual(res, {"ok": True, "data": None})

    async def test_create_validation_error(self) -> None:
        async def svc_create(session: Any, payload: _CreateSchema, data: Any) -> _Dummy:
            raise AssertionError("hook must not run on invalid payload")

        dispatcher = self._dispatcher(_team_cfg(service_create=svc_create))
        res = await dispatcher.do_create({"entity": "team", "identity": SUPERUSER, "payload": {}})  # missing name
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "unprocessable")

    async def test_unknown_entity(self) -> None:
        dispatcher = self._dispatcher(_team_cfg())
        res = await dispatcher.do_update({"entity": "nope", "id": 1, "identity": SUPERUSER, "payload": {}})
        self.assertEqual(res["error"]["code"], "bad_request")

    async def test_missing_identity(self) -> None:
        dispatcher = self._dispatcher(_team_cfg())
        res = await dispatcher.do_update({"entity": "team", "id": 5, "payload": {"name": "X"}})
        self.assertEqual(res["error"]["code"], "forbidden")

    async def test_missing_id(self) -> None:
        dispatcher = self._dispatcher(_team_cfg())
        res = await dispatcher.do_update({"entity": "team", "identity": SUPERUSER, "payload": {"name": "X"}})
        self.assertEqual(res["error"]["code"], "unprocessable")
