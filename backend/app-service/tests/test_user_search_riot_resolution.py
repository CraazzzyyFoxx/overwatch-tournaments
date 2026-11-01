"""A game-handle autocomplete result must open the player it was found through (real DB, rolled back)."""

from __future__ import annotations

import asyncio
import sys
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.services.social_identity import social_identity_service
from shared.testing import create_test_async_engine
from src.rpc.users import register
from src.services.user.service import users


class _Broker:
    def __init__(self) -> None:
        self.handlers = {}

    def subscriber(self, subject):
        def add(fn):
            self.handlers[subject] = fn
            return fn

        return add


class RiotSearchResolutionTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.session = AsyncSession(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.session.rollback()
        await self.session.close()
        await self.engine.dispose()

    async def _by_name(self, name: str) -> dict:
        from contextlib import asynccontextmanager

        from src.rpc import users as users_rpc

        broker = _Broker()
        register(broker, type("L", (), {"exception": lambda *a, **k: None})())

        @asynccontextmanager
        async def factory():
            yield self.session

        original = users_rpc._SF
        users_rpc._SF = factory
        try:
            return await broker.handlers["rpc.app.users.by_name"]({"name": name, "query": {"entities": []}}, None)
        finally:
            users_rpc._SF = original

    async def test_riot_account_resolves_to_its_player_even_when_names_differ_and_collide(self) -> None:
        marker = uuid4().hex[:6]
        handle = f"Mid-Lane {marker}#EUW"
        owner = models.User(name=f"Legacy Owner {marker}")
        other = models.User(name=handle)  # another player whose canonical name equals the Riot handle
        self.session.add_all([owner, other])
        await self.session.flush()
        await social_identity_service.upsert(self.session, user_id=owner.id, provider="riot", username=handle)

        found = await users.search_by_name(self.session, f"Mid-Lane {marker}")
        # `other` matches by its own profile name; the Riot handle finds `owner`, shown under owner's name.
        assert {row.id: row.name for row in found} == {owner.id: owner.name, other.id: other.name}

        # What the profile route does with the selected result: slug -> by_name.
        slug = owner.name.replace("#", "-")
        reply = await self._by_name(slug)
        assert reply["ok"], reply
        assert reply["data"]["id"] == owner.id

        # A canonical name with its own hyphens and tag resolves without mangling.
        hyphenated = models.User(name=f"Top-Side {marker}#KR1")
        self.session.add(hyphenated)
        await self.session.flush()
        reply = await self._by_name(hyphenated.name.replace("#", "-"))
        assert reply["ok"], reply
        assert reply["data"]["id"] == hyphenated.id

    async def test_search_reaches_profile_name_and_public_discord_and_twitch(self) -> None:
        marker = uuid4().hex[:6]
        player = models.User(name=f"Canon{marker}#1111")
        self.session.add(player)
        await self.session.flush()
        for provider, handle in (("discord", f"disc{marker}"), ("twitch", f"twch{marker}")):
            await social_identity_service.upsert(self.session, user_id=player.id, provider=provider, username=handle)
        # Own marker: sharing the visible handles' marker would trigram-match them and find the player anyway.
        unlisted = uuid4().hex[:8]
        await social_identity_service.upsert(
            self.session, user_id=player.id, provider="boosty", username=f"bst{unlisted}"
        )
        await social_identity_service.upsert(
            self.session,
            user_id=player.id,
            provider="discord",
            username=f"hid{unlisted}",
            ensure_global_visibility=False,
        )

        for query in (f"Canon{marker}", f"disc{marker}", f"twch{marker}"):
            found = await users.search_by_name(self.session, query)
            assert [(row.id, row.name) for row in found] == [(player.id, player.name)], query
        # Other socials, and accounts hidden from the profile, stay out of search.
        for query in (f"bst{unlisted}", f"hid{unlisted}"):
            assert await users.search_by_name(self.session, query) == [], query

    async def test_search_reaches_a_public_steam_persona_but_not_a_hidden_one(self) -> None:
        marker = uuid4().hex[:8]
        unlisted = uuid4().hex[:8]  # own marker: sharing one would trigram-match the owner's profile name
        player = models.User(name=f"Plain{marker}#2222")
        hidden_owner = models.User(name=f"Quiet{uuid4().hex[:8]}#3333")
        self.session.add_all([player, hidden_owner])
        await self.session.flush()
        # The Steam handle is the numeric account id; the persona is the only searchable text.
        await social_identity_service.upsert(
            self.session,
            user_id=player.id,
            provider="steam",
            username=str(200_000_000 + int(marker, 16) % 10**8),
            display_name=f"Persona {marker}",
        )
        await social_identity_service.upsert(
            self.session,
            user_id=hidden_owner.id,
            provider="steam",
            username=str(300_000_000 + int(unlisted, 16) % 10**8),
            display_name=f"Ghost {unlisted}",
            ensure_global_visibility=False,
        )

        found = await users.search_by_name(self.session, f"Persona {marker}")
        assert [(row.id, row.name) for row in found] == [(player.id, player.name)]
        assert await users.search_by_name(self.session, f"Ghost {unlisted}") == []

    async def test_canonical_name_wins_over_a_game_handle_and_handles_only_back_old_links(self) -> None:
        marker = uuid4().hex[:6]
        # B's canonical name has a hyphen; A's Riot handle is the same text with the tag separator.
        canonical = models.User(name=f"Mid-Lane{marker}")
        riot_owner = models.User(name=f"Riot Owner {marker}")
        self.session.add_all([canonical, riot_owner])
        await self.session.flush()
        await social_identity_service.upsert(
            self.session, user_id=riot_owner.id, provider="riot", username=f"Mid#Lane{marker}"
        )

        reply = await self._by_name(f"Mid-Lane{marker}")
        assert reply["ok"], reply
        assert reply["data"]["id"] == canonical.id, "a generated link is the canonical name, not a handle"

        # An old shared link built from the Riot handle still opens its owner when no canonical name matches.
        old = await self._by_name(f"Mid#Lane{marker}")
        assert old["ok"], old
        assert old["data"]["id"] == riot_owner.id

    async def test_hash_name_keeps_precedence_over_its_hyphen_twin(self) -> None:
        marker = uuid4().hex[:6]
        tagged = models.User(name=f"Name{marker}#EUW")
        twin = models.User(name=f"Name{marker}-EUW")
        self.session.add_all([tagged, twin])
        await self.session.flush()

        reply = await self._by_name(f"Name{marker}-EUW")
        assert reply["ok"], reply
        assert reply["data"]["id"] == tagged.id, "the slug inverts getPlayerSlug: '#' reading first"

        # Without a '#' twin the literal hyphenated name is reached.
        await self.session.delete(tagged)
        await self.session.flush()
        reply = await self._by_name(f"Name{marker}-EUW")
        assert reply["ok"], reply
        assert reply["data"]["id"] == twin.id
