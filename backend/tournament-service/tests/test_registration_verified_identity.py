"""Unit tests for ``require_verified`` registration identity validation.

Covers A6: an identity field flagged ``require_verified`` must carry a handle
matching one of the registrant's OAuth-verified ``social_account`` rows.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from shared.core.errors import BaseAPIException as HTTPException

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

validation = importlib.import_module("src.services.registration.validation")


class _FakeResult:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _FakeSession:
    """Minimal stand-in: returns canned (provider, username_normalized) rows."""

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows
        self.executed = 0

    async def execute(self, _stmt: object) -> _FakeResult:
        self.executed += 1
        return _FakeResult(self._rows)


def _form(built_in_fields: dict) -> SimpleNamespace:
    return SimpleNamespace(built_in_fields_json=built_in_fields, custom_fields_json=[])


def _payload(**values: str | None) -> SimpleNamespace:
    base = {"battle_tag": None, "discord_nick": None, "twitch_nick": None}
    base.update(values)
    return SimpleNamespace(**base)


class VerifiedIdentityValidationTests(IsolatedAsyncioTestCase):
    async def test_ungated_field_skips_query(self) -> None:
        session = _FakeSession([])
        await validation.validate_verified_identity(
            session,
            form=_form({"battle_tag": {"enabled": True, "required": True}}),
            payload=_payload(battle_tag="Player#1234"),
            player_id=42,
        )
        self.assertEqual(session.executed, 0)

    async def test_gated_without_player_is_rejected(self) -> None:
        session = _FakeSession([])
        with self.assertRaises(HTTPException):
            await validation.validate_verified_identity(
                session,
                form=_form({"battle_tag": {"enabled": True, "require_verified": True}}),
                payload=_payload(battle_tag="Player#1234"),
                player_id=None,
            )

    async def test_gated_without_verified_account_is_rejected(self) -> None:
        session = _FakeSession([])  # no verified rows
        with self.assertRaises(HTTPException):
            await validation.validate_verified_identity(
                session,
                form=_form({"battle_tag": {"enabled": True, "require_verified": True}}),
                payload=_payload(battle_tag="Player#1234"),
                player_id=42,
            )

    async def test_matching_verified_account_passes(self) -> None:
        session = _FakeSession([("battlenet", "crazzzyyfoxx#2875")])
        await validation.validate_verified_identity(
            session,
            form=_form({"battle_tag": {"enabled": True, "require_verified": True}}),
            payload=_payload(battle_tag=" CrazzzyyFoxx # 2875 "),
            player_id=42,
        )

    async def test_mismatched_value_is_rejected(self) -> None:
        session = _FakeSession([("battlenet", "crazzzyyfoxx#2875")])
        with self.assertRaises(HTTPException):
            await validation.validate_verified_identity(
                session,
                form=_form({"battle_tag": {"enabled": True, "require_verified": True}}),
                payload=_payload(battle_tag="Other#9999"),
                player_id=42,
            )

    async def test_empty_value_is_rejected_when_gated(self) -> None:
        session = _FakeSession([("discord", "verified_user")])
        with self.assertRaises(HTTPException):
            await validation.validate_verified_identity(
                session,
                form=_form({"discord_nick": {"enabled": True, "require_verified": True}}),
                payload=_payload(discord_nick=""),
                player_id=42,
            )

    async def test_disabled_gated_field_is_ignored(self) -> None:
        session = _FakeSession([])
        await validation.validate_verified_identity(
            session,
            form=_form({"battle_tag": {"enabled": False, "require_verified": True}}),
            payload=_payload(battle_tag="Player#1234"),
            player_id=None,
        )
        self.assertEqual(session.executed, 0)
