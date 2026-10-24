from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

analytics_flows = importlib.import_module("src.services.analytics.reads")


class ChangeShiftTests(IsolatedAsyncioTestCase):
    """The manual override writes only ``AnalyticsPlayer.shift`` of the player's own row."""

    def setUp(self) -> None:
        async def update_fields(_session, instance, fields):
            for name, value in fields.items():
                setattr(instance, name, value)
            return instance

        self.session = SimpleNamespace(commit=AsyncMock())
        self.repository = SimpleNamespace(get_by=AsyncMock(), update_fields=AsyncMock(side_effect=update_fields))
        patcher = patch.object(analytics_flows.analytics_read_service, "players", self.repository)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_missing_player_row_is_404_and_writes_nothing(self) -> None:
        self.repository.get_by.return_value = None

        with self.assertRaises(analytics_flows.errors.ApiHTTPException) as raised:
            await analytics_flows.flows_service.change_shift(self.session, 42, 3)

        self.assertEqual(404, raised.exception.status_code)
        self.repository.update_fields.assert_not_awaited()
        self.session.commit.assert_not_awaited()

    async def test_updates_only_the_manual_shift_and_returns_it(self) -> None:
        row = SimpleNamespace(player_id=42, shift=0, shift_one=100, shift_two=-200)
        self.repository.get_by.return_value = row

        result = await analytics_flows.flows_service.change_shift(self.session, 42, 3)

        self.repository.get_by.assert_awaited_once_with(self.session, player_id=42)
        self.repository.update_fields.assert_awaited_once_with(self.session, row, {"shift": 3})
        self.session.commit.assert_awaited_once()
        self.assertEqual((100, -200), (row.shift_one, row.shift_two))
        self.assertEqual(analytics_flows.schemas.PlayerShiftUpdate(player_id=42, shift=3), result)
