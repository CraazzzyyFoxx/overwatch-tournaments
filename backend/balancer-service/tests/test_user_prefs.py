from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from pydantic import ValidationError  # noqa: E402

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.rpc import prefs  # noqa: E402
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
            role_mask=None,
            points_per_win=None,
        )

        self.assertEqual(config.config_json, {"mix_comfort_tilt": 0.75})

    async def test_an_account_that_saved_nothing_stores_an_empty_blob(self) -> None:
        config = await self.service.upsert(
            self.session,
            user_id=9,
            mix_comfort_tilt=None,
            mix_role_weights=None,
            max_result_variants=None,
            role_mask=None,
            points_per_win=None,
        )

        self.assertEqual(config.config_json, {})
        self.assertIsNone(config.role_slots_json)
        self.assertIsNone(config.points_per_win)

    async def test_the_shape_and_the_points_are_columns_not_solver_overrides(self) -> None:
        """They must never reach the solver's override blob: the engine would
        either reject the key or, worse, silently weigh it."""
        config = await self.service.upsert(
            self.session,
            user_id=9,
            mix_comfort_tilt=None,
            mix_role_weights=None,
            max_result_variants=None,
            role_mask={"tank": 1, "flex": 4},
            points_per_win=50,
        )

        self.assertEqual(config.role_slots_json, {"tank": 1, "flex": 4})
        self.assertEqual(config.points_per_win, 50)
        self.assertEqual(config.config_json, {})

    async def test_zero_points_stores_as_unset(self) -> None:
        """ "Off" has one spelling in the column, whichever of null/0 was sent."""
        config = await self.service.upsert(
            self.session,
            user_id=9,
            mix_comfort_tilt=None,
            mix_role_weights=None,
            max_result_variants=None,
            role_mask=None,
            points_per_win=0,
        )

        self.assertIsNone(config.points_per_win)

    async def test_an_impossible_roster_shape_is_rejected_with_its_code(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self.service.upsert(
                self.session,
                user_id=9,
                mix_comfort_tilt=None,
                mix_role_weights=None,
                max_result_variants=None,
                role_mask={"healer": 2},
                points_per_win=None,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("roster_slots_unknown_code", str(ctx.exception.detail))
        self.configs.create.assert_not_awaited()


class UserMixPreferencesBoundsTests(TestCase):
    """The wire bounds, which are the only thing between a typo and the solver."""

    #: Every key is required, so each case below overrides one of these.
    _UNSET = {
        "mix_comfort_tilt": None,
        "mix_role_weights": None,
        "max_result_variants": None,
        "role_mask": None,
        "points_per_win": None,
    }

    def _validate(self, **overrides: object) -> UserMixPreferencesUpsert:
        return UserMixPreferencesUpsert.model_validate({**self._UNSET, **overrides})

    def test_an_unknown_knob_is_rejected_rather_than_stored(self) -> None:
        with self.assertRaises(ValidationError):
            self._validate(population_size=200)

    def test_a_missing_key_is_rejected_rather_than_defaulted(self) -> None:
        """A PUT is a full replacement: a client that forgets a key must not
        silently clear it."""
        with self.assertRaises(ValidationError):
            UserMixPreferencesUpsert.model_validate(
                {key: value for key, value in self._UNSET.items() if key != "points_per_win"}
            )

    def test_result_variants_above_the_solver_ceiling_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._validate(max_result_variants=501)

    def test_a_tilt_outside_the_zero_to_one_trade_off_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._validate(mix_comfort_tilt=1.5)

    def test_a_weight_on_an_unknown_role_is_rejected(self) -> None:
        """It would weigh nothing in the engine, silently -- the host would set a
        preference and watch it do absolutely nothing."""
        with self.assertRaises(ValidationError):
            self._validate(mix_role_weights={"jungle": 2.0})

    def test_the_four_roster_slots_are_accepted(self) -> None:
        body = self._validate(mix_role_weights={"tank": 2.0, "dps": 1.0, "support": 0.5, "flex": 1.0})

        self.assertEqual(set(body.mix_role_weights or {}), {"tank", "dps", "support", "flex"})

    def test_points_above_the_ceiling_are_rejected(self) -> None:
        """A fat-fingered 10000 would wreck the host's whole rank book in one
        recorded match."""
        with self.assertRaises(ValidationError):
            self._validate(points_per_win=1001)

    def test_negative_points_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._validate(points_per_win=-1)


class UserMixPreferencesReadTests(TestCase):
    """``roster_shape`` is derived on the way out: the settings screen previews
    the shape it is about to balance into without re-implementing the chain."""

    def test_a_stored_mask_resolves_and_is_reported_as_the_users_own(self) -> None:
        read = prefs._to_read(
            SimpleNamespace(config_json={}, role_slots_json={"tank": 1, "flex": 4}, points_per_win=50)
        )

        self.assertEqual(read.role_mask, {"tank": 1, "flex": 4})
        self.assertEqual(read.points_per_win, 50)
        self.assertEqual(read.roster_shape.slots, {"tank": 1, "flex": 4})
        self.assertEqual(read.roster_shape.team_size, 5)
        self.assertEqual(read.roster_shape.source, "user")

    def test_no_stored_mask_previews_the_builtin_shape(self) -> None:
        read = prefs._to_read(None)

        self.assertIsNone(read.role_mask)
        self.assertIsNone(read.points_per_win)
        self.assertEqual(read.roster_shape.slots, {"tank": 1, "dps": 2, "support": 2})
        self.assertEqual(read.roster_shape.source, "default")
