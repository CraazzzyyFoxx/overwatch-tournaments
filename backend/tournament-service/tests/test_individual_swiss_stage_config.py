"""``individual_swiss`` stage config: defaults on create, update, validation, other types untouched."""

from __future__ import annotations

from pydantic import ValidationError

from shared.core import enums
from src import schemas
from src.services.admin.stage import stage_service
from tests._encounter_layer import EncounterLayerCase


class IndividualSwissStageConfigTests(EncounterLayerCase):
    async def _create(self, stage_type: enums.StageType, **fields):
        async with self.Session() as s:
            return await stage_service.create_stage(
                s, self.tournament_id, schemas.StageCreate(name="S", stage_type=stage_type, order=5, **fields)
            )

    async def test_create_defaults(self) -> None:
        stage = await self._create(enums.StageType.INDIVIDUAL_SWISS)
        self.assertEqual("score", stage.pairing_mode)
        self.assertEqual(4, stage.playoff_team_count)
        # Rank adjustment is off until the organizer sets it.
        self.assertEqual((0, 0), (stage.rank_win_delta, stage.rank_loss_delta))
        self.assertEqual("wins", stage.scoring_rule.preset)

        read = schemas.StageRead.model_validate(stage, from_attributes=True)
        self.assertEqual((enums.StagePairingMode.SCORE, 4), (read.pairing_mode, read.playoff_team_count))

    async def test_update_sets_pairing_mode(self) -> None:
        stage = await self._create(enums.StageType.INDIVIDUAL_SWISS)
        async with self.Session() as s:
            updated = await stage_service.update_stage(
                s, stage.id, schemas.StageUpdate(pairing_mode=enums.StagePairingMode.BALANCE, playoff_team_count=2)
            )
        self.assertEqual(("balance", 2), (updated.pairing_mode, updated.playoff_team_count))

    async def test_playoff_team_count_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            schemas.StageUpdate(playoff_team_count=0)
        with self.assertRaises(ValidationError):
            schemas.StageCreate(name="S", stage_type=enums.StageType.INDIVIDUAL_SWISS, playoff_team_count=0)
        with self.assertRaises(ValidationError):
            schemas.StageUpdate(rank_loss_delta=-50)

    async def test_other_types_keep_both_null(self) -> None:
        stage = await self._create(
            enums.StageType.SWISS,
            pairing_mode=enums.StagePairingMode.BALANCE,
            playoff_team_count=3,
            rank_win_delta=50,
            rank_loss_delta=50,
        )
        self.assertEqual(
            (None, None, None, None),
            (stage.pairing_mode, stage.playoff_team_count, stage.rank_win_delta, stage.rank_loss_delta),
        )
        async with self.Session() as s:
            updated = await stage_service.update_stage(
                s, stage.id, schemas.StageUpdate(playoff_team_count=2, rank_win_delta=50)
            )
        self.assertEqual((None, None, None), (updated.pairing_mode, updated.playoff_team_count, updated.rank_win_delta))
