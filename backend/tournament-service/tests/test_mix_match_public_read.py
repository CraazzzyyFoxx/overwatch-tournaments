"""C4: a stats match of a pickup mix is served publicly (D6) with the frontend's default entities; a tournament's match
keeps its visibility gate and a missing id stays a 404. Encounter reads of a mix stay guarded
(``test_mix_encounter_guard``)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from shared.core.errors import BaseAPIException
from shared.models import CatalogEntity, EncounterGame, EncounterTeam, StatsMatch, StatsMatchTeam, Tournament
from shared.models.tenancy.workspace import Workspace
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.rpc import _helpers as rpc_helpers
from src.rpc import reads
from src.services.visibility_resolvers import visibility_resolvers_service as visibility
from tests._rpc_fakes import CapturingBroker

ENTITIES = [
    "map",
    "map.parent",
    "encounter",
    "encounter.teams",
    "encounter.teams.players",
    "encounter.tournament",
    "encounter.stage",
    "encounter.stage_item",
]
MISSING = 2_000_000_000


class MixMatchPublicReadTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:12]
        broker = CapturingBroker()
        reads.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.get_match = broker.handlers["rpc.tournament.get_match"]
        self.kill_feed = broker.handlers["rpc.tournament.get_match_kill_feed"]
        async with self.Session() as s:
            mode = CatalogEntity(discipline="overwatch", kind="mode", slug=f"mixm-{suffix}", name="m", image_path="x")
            s.add(mode)
            await s.flush()
            played_map = CatalogEntity(
                discipline="overwatch", kind="map", slug=f"mixm-{suffix}", parent_id=mode.id, name="p", image_path="x"
            )
            s.add(played_map)
            await s.flush()
            self.catalog_ids = [played_map.id, mode.id]
            mix = await self.mix_encounter(s)
            self.mix_match = await self._match(s, mix.id, played_map.id, with_game=True)
            self.tournament_match = await self._match(s, self.ids["e"], played_map.id, with_game=False)
            await s.commit()

    async def asyncTearDown(self) -> None:
        # The workspace goes first: its matches hold the map.
        async with self.Session() as s:
            await s.execute(sa.delete(Workspace).where(Workspace.id.in_(self.workspaces)))
            await s.execute(sa.delete(CatalogEntity).where(CatalogEntity.id.in_(self.catalog_ids)))
            await s.commit()
        await super().asyncTearDown()

    async def _match(self, s, encounter_id: int, map_id: int, *, with_game: bool) -> int:
        game_id = None
        if with_game:
            game = EncounterGame(encounter_id=encounter_id, position=1)
            s.add(game)
            await s.flush()
            game_id = game.id
        match = StatsMatch(
            workspace_id=self.ids["ws"],
            discipline="overwatch",
            encounter_id=encounter_id,
            encounter_game_id=game_id,
            map_entity_id=map_id,
        )
        s.add(match)
        await s.flush()
        seats = await s.scalars(select_seats(encounter_id))
        s.add_all(
            StatsMatchTeam(
                match_id=match.id, encounter_id=encounter_id, encounter_team_id=seat.id, source_position=seat.slot
            )
            for seat in seats
        )
        await s.flush()
        return match.id

    async def _ask(self, handler, match_id: int, entities: list[str] = ENTITIES) -> dict:
        with patch.object(rpc_helpers.db, "async_session_maker", self.Session):
            return await handler({"id": str(match_id), "query": {"entities": entities}}, None)

    async def test_an_anonymous_viewer_reads_a_mix_match_with_the_default_entities(self) -> None:
        reply = await self._ask(self.get_match, self.mix_match)
        self.assertTrue(reply["ok"], reply)
        data = reply["data"]
        self.assertEqual(self.mix_match, data["id"])
        self.assertIsNone(data["encounter"]["tournament_id"])
        self.assertIsNone(data["encounter"]["tournament"])
        self.assertIsNone(data["encounter"]["stage"])
        self.assertIsNone(data["encounter"]["stage_item"])
        self.assertEqual([None, None], [p["tournament_team_id"] for p in data["participants"]])
        self.assertEqual([], data["statistics"]["facts"])

    async def test_an_anonymous_viewer_reads_a_mix_kill_feed(self) -> None:
        reply = await self._ask(self.kill_feed, self.mix_match)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual((self.mix_match, []), (reply["data"]["match_id"], reply["data"]["events"]))

    async def test_a_visible_tournament_match_is_still_served(self) -> None:
        # No ``encounter.tournament``: the seeded tournament has no dates, which ``TournamentRead`` requires.
        self.assertTrue((await self._ask(self.get_match, self.tournament_match, ["map", "encounter"]))["ok"])

    async def test_a_hidden_tournaments_match_still_refuses(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.update(Tournament).where(Tournament.id == self.ids["t"]).values(is_hidden=True))
            await s.commit()
        for handler in (self.get_match, self.kill_feed):
            reply = await self._ask(handler, self.tournament_match)
            self.assertEqual(("not_found", False), (reply["error"]["code"], reply["ok"]))

    async def test_a_missing_match_is_a_404(self) -> None:
        for handler in (self.get_match, self.kill_feed):
            reply = await self._ask(handler, MISSING)
            self.assertEqual(("not_found", False), (reply["error"]["code"], reply["ok"]))

    async def test_the_tournament_resolver_still_refuses_a_mix_match(self) -> None:
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as caught:
                await visibility.tournament_id_for_match(s, self.mix_match)
            self.assertEqual(404, caught.exception.status_code)
            self.assertIsNone(await visibility.owner_tournament_id_for_match(s, self.mix_match))
            self.assertEqual(self.ids["t"], await visibility.owner_tournament_id_for_match(s, self.tournament_match))


def select_seats(encounter_id: int) -> sa.Select:
    return sa.select(EncounterTeam).where(EncounterTeam.encounter_id == encounter_id).order_by(EncounterTeam.slot)
