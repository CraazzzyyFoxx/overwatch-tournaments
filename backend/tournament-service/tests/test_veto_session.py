from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

from shared.core.enums import MapPickSide, VetoSeedSource  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.services.encounter.veto_session import (  # noqa: E402
    decide_seeds,
    resolve_sequence_tokens,
    select_config,
    validate_veto_config,
)


def make_config(config_id: int, *, stage_id: int | None = None, round: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=config_id, stage_id=stage_id, round=round)


class SelectConfigTests(TestCase):
    def test_stage_round_level_wins_over_stage_and_tournament(self) -> None:
        configs = [
            make_config(1),
            make_config(2, stage_id=10),
            make_config(3, stage_id=10, round=2),
        ]

        chosen = select_config(configs, stage_id=10, round=2)

        self.assertEqual(3, chosen.id)

    def test_stage_level_wins_over_tournament_when_round_differs(self) -> None:
        configs = [
            make_config(1),
            make_config(2, stage_id=10),
            make_config(3, stage_id=10, round=5),
        ]

        chosen = select_config(configs, stage_id=10, round=2)

        self.assertEqual(2, chosen.id)

    def test_tournament_level_fallback_for_other_stage(self) -> None:
        configs = [
            make_config(1),
            make_config(2, stage_id=99),
        ]

        chosen = select_config(configs, stage_id=10, round=1)

        self.assertEqual(1, chosen.id)

    def test_no_applicable_config_returns_none(self) -> None:
        configs = [make_config(2, stage_id=99), make_config(3, stage_id=10, round=7)]

        self.assertIsNone(select_config(configs, stage_id=10, round=1))

    def test_stage_configs_ignored_for_stageless_encounter(self) -> None:
        configs = [make_config(2, stage_id=10), make_config(1)]

        chosen = select_config(configs, stage_id=None, round=1)

        self.assertEqual(1, chosen.id)


class DecideSeedsTests(TestCase):
    def test_bracket_slots_lower_slot_acts_first(self) -> None:
        resolution = decide_seeds(1, 4, None, None)

        self.assertEqual(VetoSeedSource.BRACKET_SLOT, resolution.seed_source)
        self.assertEqual(MapPickSide.HOME, resolution.first_side)
        self.assertEqual(1, resolution.home_seed)
        self.assertEqual(4, resolution.away_seed)

    def test_bracket_slots_away_acts_first_when_lower(self) -> None:
        resolution = decide_seeds(8, 3, None, None)

        self.assertEqual(MapPickSide.AWAY, resolution.first_side)
        self.assertEqual(VetoSeedSource.BRACKET_SLOT, resolution.seed_source)

    def test_slot_tie_falls_back_to_home(self) -> None:
        resolution = decide_seeds(2, 2, None, None)

        self.assertEqual(VetoSeedSource.FALLBACK_HOME, resolution.seed_source)
        self.assertEqual(MapPickSide.HOME, resolution.first_side)

    def test_standings_fallback_when_slots_missing(self) -> None:
        resolution = decide_seeds(None, None, 3, 1)

        self.assertEqual(VetoSeedSource.STANDINGS, resolution.seed_source)
        self.assertEqual(MapPickSide.AWAY, resolution.first_side)
        self.assertEqual(3, resolution.home_seed)
        self.assertEqual(1, resolution.away_seed)

    def test_partial_slot_falls_through_to_standings(self) -> None:
        resolution = decide_seeds(1, None, 2, 5)

        self.assertEqual(VetoSeedSource.STANDINGS, resolution.seed_source)
        self.assertEqual(MapPickSide.HOME, resolution.first_side)

    def test_standings_tie_falls_back_to_home(self) -> None:
        resolution = decide_seeds(None, None, 1, 1)

        self.assertEqual(VetoSeedSource.FALLBACK_HOME, resolution.seed_source)
        self.assertEqual(MapPickSide.HOME, resolution.first_side)

    def test_nothing_resolvable_falls_back_to_home_without_seeds(self) -> None:
        resolution = decide_seeds(None, None, None, None)

        self.assertEqual(VetoSeedSource.FALLBACK_HOME, resolution.seed_source)
        self.assertEqual(MapPickSide.HOME, resolution.first_side)
        self.assertIsNone(resolution.home_seed)
        self.assertIsNone(resolution.away_seed)


class ResolveSequenceTokensTests(TestCase):
    SEQUENCE = ["ban_first", "ban_second", "pick_first", "pick_second", "decider"]

    def test_first_side_home(self) -> None:
        self.assertEqual(
            ["ban_home", "ban_away", "pick_home", "pick_away", "decider"],
            resolve_sequence_tokens(self.SEQUENCE, MapPickSide.HOME),
        )

    def test_first_side_away(self) -> None:
        self.assertEqual(
            ["ban_away", "ban_home", "pick_away", "pick_home", "decider"],
            resolve_sequence_tokens(self.SEQUENCE, MapPickSide.AWAY),
        )

    def test_accepts_plain_string_side(self) -> None:
        self.assertEqual(["ban_away", "pick_home"], resolve_sequence_tokens(["ban_first", "pick_second"], "away"))


class ValidateVetoConfigTests(TestCase):
    MAPS = [1, 2, 3, 4, 5]

    def test_valid_bo3_sequence_passes(self) -> None:
        validate_veto_config(["ban_first", "ban_second", "pick_first", "pick_second", "decider"], self.MAPS)

    def test_rejects_unknown_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_veto_config(["ban_home"], self.MAPS)

        self.assertEqual(422, ctx.exception.status_code)
        self.assertIn("ban_home", str(ctx.exception.detail))

    def test_rejects_empty_sequence(self) -> None:
        with self.assertRaises(HTTPException):
            validate_veto_config([], self.MAPS)

    def test_rejects_decider_not_last(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_veto_config(["decider", "pick_first"], self.MAPS)

        self.assertEqual("decider must be the last step of the sequence", ctx.exception.detail)

    def test_rejects_multiple_deciders(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_veto_config(["pick_first", "decider", "decider"], self.MAPS)

        self.assertEqual("sequence may contain at most one decider step", ctx.exception.detail)

    def test_rejects_more_steps_than_maps(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_veto_config(["ban_first", "ban_second", "pick_first"], [1, 2])

        self.assertEqual("sequence has more steps than maps in the pool", ctx.exception.detail)

    def test_rejects_duplicate_map_ids(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_veto_config(["pick_first"], [1, 1])

        self.assertEqual("map_ids must be unique", ctx.exception.detail)

    def test_rejects_bans_only_sequence(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_veto_config(["ban_first", "ban_second"], self.MAPS)

        self.assertEqual("sequence must contain at least one pick or a decider", ctx.exception.detail)
