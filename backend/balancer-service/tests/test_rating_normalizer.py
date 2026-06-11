from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from src.services.balancer.algorithm.entities import Player, Team  # noqa: E402
from src.services.balancer.algorithm.rating_normalizer import RatingNormalizer  # noqa: E402


MASK = {"Tank": 1, "Damage": 2, "Support": 2}


def make_player(uuid: str, ratings: dict[str, int], preferences: list[str] | None = None) -> Player:
    return Player(
        name=f"P{uuid}",
        ratings=ratings,
        preferences=preferences or list(ratings.keys()),
        uuid=uuid,
        mask=MASK,
    )


class TestRatingNormalizerScale:
    def test_identity_when_observed_max_equals_target(self) -> None:
        players = [
            make_player("a", {"Tank": 3500, "Damage": 3000}),
            make_player("b", {"Damage": 2500, "Support": 2000}),
        ]
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        assert normalizer.is_identity
        assert normalizer.scale == pytest.approx(1.0)

    def test_scales_up_for_low_range_dataset(self) -> None:
        players = [
            make_player("a", {"Tank": 2000, "Damage": 1800}),
            make_player("b", {"Damage": 1500, "Support": 1000}),
        ]
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        assert normalizer.scale == pytest.approx(3500 / 2000)

    def test_scales_down_for_high_range_dataset(self) -> None:
        players = [make_player("a", {"Tank": 5000, "Damage": 4500})]
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        assert normalizer.scale == pytest.approx(3500 / 5000)

    def test_empty_player_list_collapses_to_identity(self) -> None:
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit([])
        assert normalizer.is_identity

    def test_invalid_target_raises(self) -> None:
        with pytest.raises(ValueError):
            RatingNormalizer(target_max=0)
        with pytest.raises(ValueError):
            RatingNormalizer(target_max=-100)

    def test_apply_before_fit_raises(self) -> None:
        normalizer = RatingNormalizer()
        with pytest.raises(RuntimeError):
            normalizer.apply([])

    def test_restore_before_fit_raises(self) -> None:
        normalizer = RatingNormalizer()
        with pytest.raises(RuntimeError):
            normalizer.restore_players([])


class TestRatingNormalizerApply:
    def test_apply_scales_player_ratings_in_place(self) -> None:
        players = [
            make_player("a", {"Tank": 2000, "Damage": 1500}),
            make_player("b", {"Damage": 1000, "Support": 800}),
        ]
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        normalizer.apply(players)

        assert players[0].ratings["Tank"] == 3500
        assert players[0].ratings["Damage"] == round(1500 * 3500 / 2000)
        assert players[1].ratings["Damage"] == round(1000 * 3500 / 2000)
        assert players[1].ratings["Support"] == round(800 * 3500 / 2000)

    def test_apply_updates_max_rating_cache(self) -> None:
        player = Player(
            name="P", ratings={"Tank": 2000, "Damage": 1500},
            preferences=[], uuid="x", mask=MASK,
        )
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit([player])
        normalizer.apply([player])
        assert player.max_rating == 3500
        assert player._max_rating == 3500

    def test_identity_apply_is_noop(self) -> None:
        players = [make_player("a", {"Tank": 3500, "Damage": 3000})]
        original = dict(players[0].ratings)
        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        normalizer.apply(players)
        assert players[0].ratings == original


class TestRatingNormalizerRoundTrip:
    def test_apply_then_restore_returns_original_within_rounding(self) -> None:
        players = [
            make_player("a", {"Tank": 2000, "Damage": 1600}),
            make_player("b", {"Damage": 1200, "Support": 800}),
        ]
        originals = [dict(player.ratings) for player in players]

        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        normalizer.apply(players)
        normalizer.restore_players(players)

        for player, original in zip(players, originals):
            for role, expected in original.items():
                assert abs(player.ratings[role] - expected) <= 1


class TestRatingNormalizerTeamRefresh:
    def test_refresh_recomputes_cached_team_stats(self) -> None:
        players = [
            make_player("a", {"Tank": 2000}),
            make_player("b", {"Damage": 1800}),
            make_player("c", {"Damage": 1600}),
            make_player("d", {"Support": 1400}),
            make_player("e", {"Support": 1200}),
        ]
        team = Team(1, MASK)
        team.add_player("Tank", players[0])
        team.add_player("Damage", players[1])
        team.add_player("Damage", players[2])
        team.add_player("Support", players[3])
        team.add_player("Support", players[4])
        team.calculate_stats()
        assert team.total_rating == pytest.approx(2000 + 1800 + 1600 + 1400 + 1200)

        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        normalizer.apply(players)
        normalizer.refresh_team_stats([team])

        scale = 3500 / 2000
        expected_total = sum(round(r * scale) for r in (2000, 1800, 1600, 1400, 1200))
        assert team.total_rating == pytest.approx(expected_total)

    def test_full_round_trip_restores_team_stats(self) -> None:
        players = [
            make_player("a", {"Tank": 2000}),
            make_player("b", {"Damage": 1600}),
            make_player("c", {"Damage": 1200}),
            make_player("d", {"Support": 800}),
            make_player("e", {"Support": 400}),
        ]
        team = Team(1, MASK)
        team.add_player("Tank", players[0])
        team.add_player("Damage", players[1])
        team.add_player("Damage", players[2])
        team.add_player("Support", players[3])
        team.add_player("Support", players[4])
        team.calculate_stats()
        original_total = team.total_rating

        normalizer = RatingNormalizer(target_max=3500)
        normalizer.fit(players)
        normalizer.apply(players)
        normalizer.refresh_team_stats([team])
        normalizer.restore_players(players)
        normalizer.refresh_team_stats([team])

        assert abs(team.total_rating - original_total) <= len(players)
