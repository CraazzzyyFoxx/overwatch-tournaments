"""A slot swap moves seeding AND the origin of a derived slot; a delete voids
what the deleted result advanced.

Three defects are pinned here. ``swap_slots`` used to write the two slots
blindly, so swapping the home slots of ``A-B`` and ``C-A`` produced ``A-A``; it
also left the ``EncounterLink`` feeding a derived slot behind, so the next
advancement overwrote the manual move and a Grand Final that had its sides
flipped was no longer the link target the reset rule looks for.
``delete_encounter`` deleted the row and recalculated, leaving the teams and
results it had already advanced downstream as an orphaned bracket, and left the
Swiss bye recorded for a round whose last encounter it had just removed.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

admin_encounter = importlib.import_module("src.services.admin.encounter")
enums = importlib.import_module("shared.core.enums")
errors = importlib.import_module("shared.core.errors")


def _encounter(
    *,
    id: int,
    home: int | None,
    away: int | None,
    stage_id: int | None = 1,
    stage_item_id: int | None = None,
    round: int = 1,
    status=enums.EncounterStatus.OPEN,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        tournament_id=7,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
        round=round,
        home_team_id=home,
        away_team_id=away,
        name="x vs y",
        status=status,
        result_status=enums.EncounterResultStatus.NONE,
        started_at=None,
        ended_at=None,
    )


def _link(*, target_encounter_id: int, target_slot) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        source_encounter_id=99,
        target_encounter_id=target_encounter_id,
        role=enums.EncounterLinkRole.WINNER,
        target_slot=target_slot,
    )


class SwapSlots(IsolatedAsyncioTestCase):
    async def _swap(self, encounters, links, *, slot, target_encounter_id, target_slot):
        by_id = {encounter.id: encounter for encounter in encounters}
        session = SimpleNamespace(
            commit=AsyncMock(),
            execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: links))),
        )
        data = SimpleNamespace(slot=slot, target_encounter_id=target_encounter_id, target_slot=target_slot)
        service = admin_encounter.AdminEncounterService()

        with (
            patch.object(
                service.encounter_repo,
                "get_for_update",
                AsyncMock(side_effect=lambda _s, eid, **_kw: by_id.get(eid)),
            ),
            patch.object(
                service.team_repo,
                "get",
                AsyncMock(side_effect=lambda _s, tid: SimpleNamespace(name=f"T{tid}")),
            ),
            patch.object(
                admin_encounter.pick_ban_session_service,
                "sync_all_pick_ban_sessions_after_team_change",
                AsyncMock(),
            ),
            patch.object(admin_encounter, "enqueue_tournament_recalculation", AsyncMock()),
        ):
            return await service.swap_slots(session, encounters[0].id, data)

    async def test_swap_refuses_to_put_one_team_in_both_slots(self):
        """``A-B`` and ``C-A``, home slots exchanged, used to yield ``A-A``."""
        first = _encounter(id=1, home=1, away=2)
        second = _encounter(id=2, home=3, away=1)

        with self.assertRaises(errors.BaseAPIException) as caught:
            await self._swap([first, second], [], slot="home", target_encounter_id=2, target_slot="home")

        self.assertEqual(400, caught.exception.status_code)
        self.assertIn("both slots", caught.exception.detail)

    async def test_home_away_flip_moves_the_feeding_link_to_the_new_slot(self):
        """The origin travels with the team: the link that filled ``home`` now
        fills ``away``, which is what keeps the Grand Final identifiable."""
        grand_final = _encounter(id=5, home=1, away=2)
        link = _link(target_encounter_id=5, target_slot=enums.EncounterLinkSlot.HOME)

        await self._swap([grand_final], [link], slot="home", target_encounter_id=5, target_slot="away")

        self.assertEqual((2, 1), (grand_final.home_team_id, grand_final.away_team_id))
        self.assertEqual(5, link.target_encounter_id)
        self.assertEqual(enums.EncounterLinkSlot.AWAY, link.target_slot)

    async def test_cross_encounter_swap_repoints_the_link_at_the_other_encounter(self):
        first = _encounter(id=1, home=1, away=2)
        second = _encounter(id=2, home=None, away=4)
        link = _link(target_encounter_id=1, target_slot=enums.EncounterLinkSlot.HOME)

        await self._swap([first, second], [link], slot="home", target_encounter_id=2, target_slot="home")

        self.assertEqual((None, 2), (first.home_team_id, first.away_team_id))
        self.assertEqual((1, 4), (second.home_team_id, second.away_team_id))
        self.assertEqual(2, link.target_encounter_id)
        self.assertEqual(enums.EncounterLinkSlot.HOME, link.target_slot)


class DeleteEncounter(IsolatedAsyncioTestCase):
    async def _delete(self, encounter, *, stage=None, siblings=()):
        calls: list[str] = []

        async def fake_delete(_obj):
            calls.append("delete")

        async def fake_reset(_session, target, **_kw):
            calls.append("reset")
            self.assertIs(encounter, target)
            return []

        session = SimpleNamespace(
            commit=AsyncMock(),
            delete=fake_delete,
            get=AsyncMock(return_value=stage),
            execute=AsyncMock(return_value=SimpleNamespace(first=lambda: (siblings[0],) if siblings else None)),
        )
        service = admin_encounter.AdminEncounterService()
        remove_bye = MagicMock()

        with (
            patch.object(service.encounter_repo, "get", AsyncMock(return_value=encounter)),
            patch.object(admin_encounter, "reset_encounter_result", AsyncMock(side_effect=fake_reset)),
            patch.object(admin_encounter, "remove_swiss_bye_round", remove_bye),
            patch.object(admin_encounter, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(admin_encounter.AdminEncounterService, "_assert_source_correction_allowed", AsyncMock()),
        ):
            await service.delete_encounter(session, encounter.id)

        return calls, remove_bye

    async def test_delete_voids_the_advancement_before_removing_the_row(self):
        encounter = _encounter(id=10, home=1, away=2, stage_id=None, status=enums.EncounterStatus.COMPLETED)

        calls, _ = await self._delete(encounter)

        self.assertEqual(["reset", "delete"], calls)

    async def test_deleting_the_rounds_last_swiss_encounter_drops_its_bye(self):
        stage = SimpleNamespace(id=4, stage_type=enums.StageType.SWISS, settings_json={})
        encounter = _encounter(id=11, home=1, away=2, stage_id=4, stage_item_id=9, round=3)

        _, remove_bye = await self._delete(encounter, stage=stage)

        remove_bye.assert_called_once_with(stage, 9, 3)

    async def test_deleting_one_of_two_swiss_encounters_keeps_the_bye(self):
        stage = SimpleNamespace(id=4, stage_type=enums.StageType.SWISS, settings_json={})
        encounter = _encounter(id=11, home=1, away=2, stage_id=4, stage_item_id=9, round=3)

        _, remove_bye = await self._delete(encounter, stage=stage, siblings=(12,))

        remove_bye.assert_not_called()
