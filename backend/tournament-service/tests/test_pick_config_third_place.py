"""Cascade ranking of the bronze match: its own round-level scope, never the final's config."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core.enums import MapVetoMode, PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.domain.pick_ban_config import pick_config, pool_items  # noqa: E402
from shared.models.tournament.pick_ban import PickBanConfig, PickBanConfigItem  # noqa: E402
from src.services.encounter.pick_ban_config import validate_config_payload  # noqa: E402

STAGE, ROUND = 7, 4


def _config(item_id: int, *, stage_id: int | None = STAGE, round: int | None = ROUND, third_place: bool = False):
    return PickBanConfig(
        tournament_id=1,
        kind=PickBanKind.MAP,
        stage_id=stage_id,
        round=round,
        third_place=third_place,
        mode=MapVetoMode.POOL,
        ruleset_json={},
        items=[PickBanConfigItem(item_id=item_id, sort_order=0)],
    )


class PickConfigThirdPlaceTest(TestCase):
    def test_bronze_encounter_picks_the_bronze_config(self) -> None:
        final, bronze = _config(1), _config(2, third_place=True)
        picked = pick_config([final, bronze], stage_id=STAGE, round=ROUND, third_place=True)
        assert picked is bronze

    def test_final_ignores_the_bronze_config(self) -> None:
        final, bronze = _config(1), _config(2, third_place=True)
        assert pick_config([bronze, final], stage_id=STAGE, round=ROUND) is final
        assert pick_config([bronze], stage_id=STAGE, round=ROUND) is None

    def test_bronze_without_its_own_config_falls_to_stage_wide_not_the_final(self) -> None:
        final, stage_wide, tournament_wide = _config(1), _config(2, round=None), _config(3, stage_id=None, round=None)
        assert pick_config([final, stage_wide, tournament_wide], stage_id=STAGE, round=ROUND, third_place=True) is (
            stage_wide
        )
        assert pick_config([final, tournament_wide], stage_id=STAGE, round=ROUND, third_place=True) is tournament_wide
        assert pick_config([final], stage_id=STAGE, round=ROUND, third_place=True) is None

    def test_pool_items_follow_the_bronze_flag(self) -> None:
        configs = [_config(1), _config(2, third_place=True)]
        assert pool_items(configs, stage_id=STAGE, round=ROUND, third_place=True) == {2}
        assert pool_items(configs, stage_id=STAGE, round=ROUND) == {1}


class ThirdPlaceNeedsRoundTest(TestCase):
    def test_bronze_without_round_is_rejected(self) -> None:
        with self.assertRaises(BaseAPIException) as caught:
            validate_config_payload(
                kind=PickBanKind.MAP,
                mode=MapVetoMode.POOL,
                ruleset={},
                item_ids=[],
                slots=[],
                stage_id=STAGE,
                round=None,
                discipline="overwatch",
                third_place=True,
            )
        assert caught.exception.status_code == 422


if __name__ == "__main__":
    import unittest

    unittest.main()
