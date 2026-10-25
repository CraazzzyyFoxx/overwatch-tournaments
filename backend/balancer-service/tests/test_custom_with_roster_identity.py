"""The shared mix response builder (``_with_roster``) for a populated mix of each game.

Every create/update/detail response goes through it; it reads the roster through the owner discipline's identity
provider, so a missing discipline breaks exactly the populated mixes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
SERVICE = Path(__file__).resolve().parents[1]
for candidate in (str(ROOT), str(SERVICE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core.enums import MixParticipation, MixRoleSelectionMode  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.schemas.identity import PlayerIdentityRead  # noqa: E402
from src.rpc import custom  # noqa: E402
from src.services.custom_game import CustomGameService  # noqa: E402
from src.services.workspace_roster import RosterMember  # noqa: E402


def _service(provider_seen: list) -> CustomGameService:
    async def load_roster(_session, *, workspace_id, provider, member_ids):
        provider_seen.append(provider)
        handle = {"riot": "Riot Name#EUW", "battlenet": "Battle#1234", "steam": "Steam Name"}[provider]
        return {
            member_id: RosterMember(
                member_id=member_id,
                player_id=member_id * 10,
                identity=PlayerIdentityRead.of(provider, handle),
                display_name=None,
            )
            for member_id in member_ids
        }

    service = CustomGameService.__new__(CustomGameService)
    service.load_roster = load_roster
    service.workspace_discord_target = AsyncMock(return_value=(None, None))
    service.host_points_per_win = AsyncMock(return_value=0)
    service.roster_shape = AsyncMock(return_value=SimpleNamespace(model_dump=lambda: {}))
    service.roster = SimpleNamespace(
        list_for_game=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=1,
                    workspace_member_id=7,
                    sort_order=0,
                    participation=MixParticipation.POOL,
                    role_selection_mode=MixRoleSelectionMode.ALL_RANKED,
                    is_flex=False,
                    away=False,
                    lobby_pin=None,
                )
            ]
        )
    )
    service.co_hosts = SimpleNamespace(user_ids_for_game=AsyncMock(return_value=[]))
    service.hosts = AsyncMock(return_value={})
    service.mix_rounds = SimpleNamespace(
        activity_for_games=AsyncMock(return_value={}), activity_for_lobbies=AsyncMock(return_value={})
    )
    service.lobbies = SimpleNamespace(
        list_for_game=AsyncMock(return_value=[]),
        pregame_ids=AsyncMock(return_value=frozenset()),
        live_seats=AsyncMock(return_value={}),
    )
    service.draft_lobbies = AsyncMock(return_value={})
    service.ban_opener = AsyncMock(return_value=None)
    service.player_roles = SimpleNamespace(roles_for_players=AsyncMock(return_value={}))
    service.ranks = SimpleNamespace(list_layer_rows=AsyncMock(return_value=[]), resolve=AsyncMock(return_value={}))
    return service


class WithRosterIdentityTests(IsolatedAsyncioTestCase):
    async def test_populated_mix_reads_its_roster_under_the_owner_provider(self) -> None:
        for discipline, provider, handle in [
            ("lol", "riot", "Riot Name#EUW"),
            ("overwatch", "battlenet", "Battle#1234"),
        ]:
            with self.subTest(discipline=discipline):
                seen: list[str] = []
                game = SimpleNamespace(
                    id=3,
                    workspace_id=9,
                    discipline=discipline,
                    host_user_id=None,
                    name="Mix",
                    status="draft",
                    lobby_count=1,
                    self_signup="closed",
                    self_role_edit=False,
                    hero_ban_preset=None,
                    hero_fearless=False,
                    hero_ban_seconds=None,
                    hero_pick_seconds=None,
                    team_formation="balance",
                    draft_pick_seconds=30,
                    general_voice_channel_id=None,
                    created_at=None,
                )
                with (
                    patch.object(custom, "custom_game_service", _service(seen)),
                    patch.object(custom, "_discord_posts", AsyncMock(return_value=[])),
                    patch.object(custom, "_game_settings", AsyncMock(return_value={})),
                ):
                    body = await custom._with_roster(object(), game)

                self.assertEqual(seen, [provider])
                self.assertEqual(body["players"][0]["identity"], {"provider": provider, "handle": handle})
                self.assertNotIn("battle_tag", body["players"][0])

    async def test_create_rejects_unknown_discipline_before_provider_lookup(self) -> None:
        service = _service([])
        service.workspaces = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(disciplines_enabled=["overwatch"]))
        )
        with self.assertRaises(BaseAPIException) as caught:
            await service.create(
                object(),
                workspace_id=9,
                host_user_id=1,
                name="Mix",
                actor_user_id=1,
                member_ids=[7],
                discipline="not-a-game",
            )
        self.assertEqual(caught.exception.status_code, 422)

    async def test_unscoped_stats_stay_workspace_wide_and_merge_identity_across_providers(self) -> None:
        from datetime import datetime

        seen: list[str] = []
        service = _service(seen)
        when = datetime(2026, 3, 1, 21, 30)

        def seat(member_id: int):
            return SimpleNamespace(
                workspace_member_id=member_id,
                role=None,
                encounter_id=member_id,
                custom_game_id=1,
                created_at=when,
                recorded_at=when,
                own_score=1.0,
                other_score=0.0,
            )

        service.mix_rounds = SimpleNamespace(seats=AsyncMock(return_value=[seat(7), seat(8)]))
        wide = (await service.mix_stats(object(), workspace_id=9, discipline=None, since=None))["members"]
        self.assertEqual(service.mix_rounds.seats.await_args.kwargs["discipline"], None)
        self.assertEqual(sorted(set(seen)), ["battlenet", "riot", "steam"])
        self.assertEqual({row["workspace_member_id"] for row in wide}, {7, 8})
        self.assertTrue(all(row["identity"] is not None for row in wide))

        seen.clear()
        await service.mix_stats(object(), workspace_id=9, discipline="lol", since=None)
        self.assertEqual(service.mix_rounds.seats.await_args.kwargs["discipline"], "lol")
        self.assertEqual(seen, ["riot"])
