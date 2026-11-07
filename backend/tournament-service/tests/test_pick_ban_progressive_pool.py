"""The map-by-map pool: one shared map pool, one round per game, played maps drop out.

Real Postgres, like the room loop it extends: rounds open off confirmed games, which the encounter's scoring rule
reads.
"""

from __future__ import annotations

import sqlalchemy as sa

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.domain import pick_ban_rules as pbr
from shared.models.encounter import Encounter
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.pick_ban import PickBanConfig, PickBanConfigItem
from src.services.encounter import pick_ban_config
from src.services.encounter.pick_ban_action import pick_ban_action_service
from src.services.encounter.pick_ban_session import pick_ban_session_service
from tests.test_pregame_room_loop import LoopCase

MAPS = (1_930_000_001, 1_930_000_002, 1_930_000_003, 1_930_000_004, 1_930_000_005)
BAN_A, BAN_B, FIRST, SECOND, THIRD = MAPS
MAP_BY_MAP = pbr.GENERIC_PRESETS_BY_ID["map_by_map"].ruleset.to_json()


class ProgressivePoolCase(LoopCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            for map_id in MAPS:
                await s.execute(
                    sa.text(
                        "INSERT INTO catalog.entity (id, discipline, kind, slug, name, attrs)"
                        " VALUES (:id, :discipline, 'map', :slug, :slug, CAST('{}' AS JSONB)) ON CONFLICT (id) DO NOTHING"
                    ),
                    {"id": map_id, "discipline": self.discipline, "slug": f"m{map_id}"},
                )
            await s.commit()

    async def open_map_room(self, maps: tuple[int, ...] = MAPS) -> None:
        async with self.Session() as s:
            config = PickBanConfig(
                tournament_id=self.tournament_id,
                kind=enums.PickBanKind.MAP,
                mode=enums.MapVetoMode.PROGRESSIVE,
                first_ban_rotation=enums.FirstBanRotation.FIXED,
                ruleset_json=MAP_BY_MAP,
            )
            config.items = [PickBanConfigItem(item_id=map_id, sort_order=index) for index, map_id in enumerate(maps)]
            s.add(config)
            await s.commit()
        async with self.Session() as s:
            encounter = await s.get_one(Encounter, self.encounter_id)
            for seat in self.seats:
                await pick_ban_session_service.mark_ready(s, encounter, seat, None)
            assert await pick_ban_session_service.ensure_pick_ban_session(s, encounter, enums.PickBanKind.MAP)

    async def map_state(self) -> dict:
        async with self.Session() as s:
            return await pick_ban_action_service.get_pick_ban_state(s, self.encounter_id, enums.PickBanKind.MAP)

    async def map_act(self, actor: int, item_id: int, action: str) -> None:
        async with self.Session() as s:
            await pick_ban_action_service.perform_pick_ban_action(
                s, self.encounter_id, enums.PickBanKind.MAP, actor, item_id=item_id, action=action
            )

    async def offered(self, round_number: int) -> set[int]:
        return {
            entry["item_id"]
            for entry in (await self.map_state())["pool"]
            if entry["round"] == round_number and entry["status"] == "available"
        }


class MapByMapTests(ProgressivePoolCase):
    async def test_each_game_opens_the_next_map_out_of_what_is_left_for_the_loser(self) -> None:
        await self.open_map_room()
        self.assertEqual(set(MAPS), await self.offered(1))
        await self.map_act(self.slot1, BAN_A, "ban")
        await self.map_act(self.slot2, BAN_B, "ban")
        await self.map_act(self.slot1, FIRST, "pick")

        await self.confirm_position(1, winner=self.slot1)
        await self.reconcile()
        state = await self.map_state()
        self.assertEqual((2, [self.slot2]), (state["current_round"], state["acting_team_ids"]))
        # Both series bans stay out, and so does the map just played.
        self.assertEqual({SECOND, THIRD}, await self.offered(2))
        await self.map_act(self.slot2, SECOND, "pick")

        await self.confirm_position(2, winner=self.slot2)
        await self.reconcile()
        state = await self.map_state()
        self.assertEqual((3, [self.slot1]), (state["current_round"], state["acting_team_ids"]))
        self.assertEqual({THIRD}, await self.offered(3))


class PoolSizeGateTests(ProgressivePoolCase):
    async def validate(self, maps: tuple[int, ...]) -> None:
        async with self.Session() as s:
            await pick_ban_config.validate_config(
                s,
                kind=enums.PickBanKind.MAP,
                mode=enums.MapVetoMode.PROGRESSIVE,
                ruleset=MAP_BY_MAP,
                item_ids=list(maps),
                slots=[],
                stage_id=None,
                round=None,
                discipline=self.discipline,
                tournament_id=self.tournament_id,
            )

    async def test_a_pool_too_small_for_the_bracket_series_is_refused_at_save(self) -> None:
        # No bracket yet: nothing to size against, the editor's preview is the check.
        await self.validate(MAPS[:4])
        async with self.Session() as s:
            s.add(BracketEncounter(encounter_id=self.encounter_id, tournament_id=self.tournament_id, round=1))
            await s.commit()
        # Bo3 with two series bans needs five maps.
        with self.assertRaises(BaseAPIException) as refused:
            await self.validate(MAPS[:4])
        self.assertEqual("pool_too_small", refused.exception.detail[0].code)
        await self.validate(MAPS)
