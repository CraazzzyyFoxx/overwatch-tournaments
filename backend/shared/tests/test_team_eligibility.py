"""Pure eligibility rules: starters only, no I/O."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.domain.team_eligibility import (  # noqa: E402
    StarterRank,
    evaluate_discord_guild,
    evaluate_rank_rules,
    evaluate_unique_identity,
)


class RankRuleTests(TestCase):
    def test_unrated_starters_fail_min_or_max_not_spread(self) -> None:
        issues = evaluate_rank_rules(
            [StarterRank(1, None), StarterRank(2, 2500)],
            rank_min=1000,
            rank_max=None,
            max_spread=500,
        )
        self.assertEqual(["team_rank_unrated"], [issue.code for issue in issues])
        self.assertEqual(1, issues[0].registration_id)

    def test_substitutes_are_not_this_function_callers_problem(self) -> None:
        issues = evaluate_rank_rules(
            [StarterRank(1, 1000), StarterRank(2, 4000)],
            rank_min=1500,
            rank_max=3500,
            max_spread=500,
        )
        self.assertEqual(
            {"team_rank_too_low", "team_rank_too_high", "team_rank_spread"},
            {issue.code for issue in issues},
        )

    def test_spread_ignores_unrated_ranks(self) -> None:
        """An unrated starter must not act as a 0-SR floor: the rated pair is 40
        apart, well inside the 50 the tournament allows."""
        issues = evaluate_rank_rules(
            [StarterRank(1, None), StarterRank(2, 2000), StarterRank(3, 2040)],
            rank_min=None,
            rank_max=None,
            max_spread=50,
        )
        self.assertEqual([], issues)


class IdentityTests(TestCase):
    def test_a_key_taken_by_another_team_is_reported_once_per_player(self) -> None:
        issues = evaluate_unique_identity(
            this_keys={1: {"btag:ana", "discord:1"}, 2: {"btag:bob"}},
            taken_keys={"btag:ana", "discord:9"},
        )
        self.assertEqual([1], [issue.registration_id for issue in issues])
        self.assertEqual("team_identity_taken", issues[0].code)


class DiscordGuildTests(TestCase):
    def test_require_without_a_guild_fails_closed(self) -> None:
        issues = evaluate_discord_guild({1: "member"}, guild_id=None, require=True)
        self.assertEqual(["discord_guild_not_configured"], [issue.code for issue in issues])

    def test_off_is_a_no_op(self) -> None:
        self.assertEqual([], evaluate_discord_guild({1: "not_member"}, guild_id="9", require=False))

    def test_signals_map_to_codes(self) -> None:
        issues = evaluate_discord_guild(
            {1: "member", 2: "not_linked", 3: "not_member", 4: "unreachable"},
            guild_id="99",
            require=True,
        )
        self.assertEqual(
            {
                (2, "discord_not_linked"),
                (3, "discord_guild_not_member"),
                (4, "discord_guild_unreachable"),
            },
            {(issue.registration_id, issue.code) for issue in issues},
        )
