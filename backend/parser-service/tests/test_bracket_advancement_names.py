from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))


from shared.core import enums  # noqa: E402
from shared.models.tournament.encounter_link import EncounterLink  # noqa: E402
from shared.services.bracket import advancement  # noqa: E402


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class BracketAdvancementNameTests(IsolatedAsyncioTestCase):
    async def test_advance_winner_recomputes_target_encounter_name(self) -> None:
        source = SimpleNamespace(
            id=101,
            home_team_id=11,
            away_team_id=22,
            home_score=3,
            away_score=1,
            status=enums.EncounterStatus.COMPLETED,
        )
        target = SimpleNamespace(
            id=202,
            home_team_id=None,
            away_team_id=33,
            name="TBD vs Team Gamma",
            # advance_winner now inspects the target's recorded result to
            # decide whether a slot change invalidates it.
            home_score=0,
            away_score=0,
            status=enums.EncounterStatus.OPEN,
            result_status=enums.EncounterResultStatus.NONE,
        )
        link = EncounterLink(
            source_encounter_id=source.id,
            target_encounter_id=target.id,
            role=enums.EncounterLinkRole.WINNER,
            target_slot=enums.EncounterLinkSlot.HOME,
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=_ExecuteResult([link])),
            get=AsyncMock(return_value=target),
            flush=AsyncMock(),
        )

        with (
            patch.object(
                advancement,
                "_maybe_create_grand_final_reset",
                AsyncMock(return_value=(None, [])),
            ),
            patch.object(
                advancement,
                "_build_encounter_name_for_ids",
                AsyncMock(return_value="Team Alpha vs Team Gamma"),
            ) as build_name,
        ):
            updated = await advancement.advance_winner(session, source)

        self.assertEqual(11, target.home_team_id)
        self.assertEqual(33, target.away_team_id)
        self.assertEqual("Team Alpha vs Team Gamma", target.name)
        self.assertEqual([target], updated)
        build_name.assert_awaited_once_with(
            session,
            home_team_id=11,
            away_team_id=33,
        )
        session.flush.assert_awaited_once_with()
