from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from pydantic import ValidationError  # noqa: E402

from src.schemas.user_prefs import UserMixPreferencesUpsert  # noqa: E402
from src.services.user_prefs import UserMixPrefsService  # noqa: E402


class UserMixPrefsServiceTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        self.configs = MagicMock()
        self.configs.get_by_user = AsyncMock(return_value=None)
        self.configs.create = AsyncMock(side_effect=lambda _session, row: row)
        self.service = UserMixPrefsService(configs=self.configs)
        self.session = MagicMock()
        self.session.commit = AsyncMock()

    async def test_an_unset_knob_is_an_absent_key_not_a_null(self) -> None:
        """The blob is handed to the solver untouched, so a stored null would
        override the engine default with nothing."""
        config = await self.service.upsert(
            self.session,
            user_id=9,
            mix_comfort_tilt=0.75,
            mix_role_weights=None,
            max_result_variants=None,
        )

        self.assertEqual(config.config_json, {"mix_comfort_tilt": 0.75})

    async def test_an_account_that_saved_nothing_stores_an_empty_blob(self) -> None:
        config = await self.service.upsert(
            self.session,
            user_id=9,
            mix_comfort_tilt=None,
            mix_role_weights=None,
            max_result_variants=None,
        )

        self.assertEqual(config.config_json, {})


class UserMixPreferencesBoundsTests(TestCase):
    """The wire bounds, which are the only thing between a typo and the solver."""

    def test_an_unknown_knob_is_rejected_rather_than_stored(self) -> None:
        with self.assertRaises(ValidationError):
            UserMixPreferencesUpsert.model_validate(
                {
                    "mix_comfort_tilt": None,
                    "mix_role_weights": None,
                    "max_result_variants": None,
                    "population_size": 200,
                }
            )

    def test_result_variants_above_the_solver_ceiling_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            UserMixPreferencesUpsert.model_validate(
                {"mix_comfort_tilt": None, "mix_role_weights": None, "max_result_variants": 501}
            )

    def test_a_tilt_outside_the_zero_to_one_trade_off_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            UserMixPreferencesUpsert.model_validate(
                {"mix_comfort_tilt": 1.5, "mix_role_weights": None, "max_result_variants": None}
            )

    def test_a_weight_on_an_unknown_role_is_rejected(self) -> None:
        """It would weigh nothing in the engine, silently -- the host would set a
        preference and watch it do absolutely nothing."""
        with self.assertRaises(ValidationError):
            UserMixPreferencesUpsert.model_validate(
                {"mix_comfort_tilt": None, "mix_role_weights": {"jungle": 2.0}, "max_result_variants": None}
            )

    def test_the_four_roster_slots_are_accepted(self) -> None:
        body = UserMixPreferencesUpsert.model_validate(
            {
                "mix_comfort_tilt": None,
                "mix_role_weights": {"tank": 2.0, "dps": 1.0, "support": 0.5, "flex": 1.0},
                "max_result_variants": None,
            }
        )

        self.assertEqual(set(body.mix_role_weights or {}), {"tank", "dps", "support", "flex"})
