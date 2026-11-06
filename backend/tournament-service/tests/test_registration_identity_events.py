"""Registration player refreshes serialize only the owner's position-zero provider identity into the real outbox."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

for root in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared import models  # noqa: E402
from shared.core.social import normalize_social_handle  # noqa: E402
from shared.messaging.config import PLAYER_REFRESH_REQUESTED_ROUTING_KEY  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from src.services.tournament import events  # noqa: E402

#: Nobody here has an inbox, so the node id is never looked up.
NODE_ID = 1


class RegistrationIdentityEventsTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        self.engine = create_test_async_engine()
        self.session = AsyncSession(self.engine, expire_on_commit=False)
        self.workspace = models.Workspace(
            slug=f"ev-{uuid4().hex}", name="Event identities", disciplines_enabled=["overwatch", "lol"]
        )
        self.session.add(self.workspace)
        await self.session.flush()

    async def asyncTearDown(self):
        await self.session.rollback()
        await self.session.close()
        await self.engine.dispose()

    async def _registration(self, discipline, providers, *, with_player=True):
        tournament = models.Tournament(
            workspace_id=self.workspace.id, discipline=discipline, name="Identity events", slug=f"ev-{uuid4().hex}"
        )
        self.session.add(tournament)
        member_id = None
        if with_player:
            player = models.User(name=f"p-{uuid4().hex[:12]}")
            self.session.add(player)
            await self.session.flush()
            member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=player.id)
            self.session.add(member)
            await self.session.flush()
            member_id = member.id
        await self.session.flush()
        registration = models.Registration(
            tournament_id=tournament.id,
            workspace_member_id=member_id,
            identities=[
                models.RegistrationIdentity(
                    provider=provider,
                    position=position,
                    handle=handle,
                    handle_normalized=normalize_social_handle(provider, handle),
                )
                for provider, handles in providers.items()
                for position, handle in enumerate(handles)
            ],
        )
        self.session.add(registration)
        await self.session.flush()
        return registration

    async def _refreshes(self, registration):
        rows = await self.session.scalars(
            sa.select(models.EventOutbox).where(models.EventOutbox.routing_key == PLAYER_REFRESH_REQUESTED_ROUTING_KEY)
        )
        return [row for row in rows if row.payload_json["registration_id"] == registration.id]

    async def test_approval_and_recheck_outbox_choose_each_owner_provider(self):
        for discipline, provider, expected in [
            ("lol", "riot", "Riot Name#EUW"),
            ("overwatch", "battlenet", "Battle#1234"),
        ]:
            registration = await self._registration(
                discipline, {"battlenet": ["Battle # 1234", "Alt#1234"], "riot": [" Riot Name # EUW "]}
            )
            await events.enqueue_registration_approved(self.session, registration, registration_node_id=NODE_ID)
            await events.enqueue_registration_rank_check(self.session, registration)
            await self.session.flush()
            owned = await self._refreshes(registration)
            assert sorted(row.payload_json["source"] for row in owned) == [
                "tournament_recheck",
                "tournament_registration",
            ]
            for row in owned:
                assert row.exchange == "player.events"
                assert row.payload_json["identity"] == {"provider": provider, "handle": expected}
                assert row.payload_json["discipline"] == discipline
                assert row.payload_json["workspace_id"] == self.workspace.id
                assert row.status == "pending"

    async def test_missing_owner_provider_stays_null_even_when_other_game_is_present(self):
        registration = await self._registration("lol", {"battlenet": ["Foreign#1234"]})
        await events.enqueue_registration_approved(self.session, registration, registration_node_id=NODE_ID)
        await self.session.flush()
        [row] = await self._refreshes(registration)
        assert row.payload_json["identity"] is None

    async def test_a_registration_without_a_player_requests_no_refresh(self):
        registration = await self._registration("overwatch", {"battlenet": ["Battle#1234"]}, with_player=False)
        await events.enqueue_registration_approved(self.session, registration, registration_node_id=NODE_ID)
        await events.enqueue_registration_rank_check(self.session, registration)
        await self.session.flush()
        assert await self._refreshes(registration) == []
