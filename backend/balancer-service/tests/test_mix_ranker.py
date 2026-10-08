"""The mix ranker's formulas and its history fold (mixtura-ranker by @dmelackov)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core.enums import CasualTeamSide, HeroClass  # noqa: E402
from src.domain.mix_ranker import HiddenRating, Ranker, RankerSettings  # noqa: E402
from tests.mix_ranker_fakes import in_memory_ranker  # noqa: E402

_VARIANTS = ("reference", "corrected")


class MappingTests(TestCase):
    def test_a_settled_hidden_rating_projects_back_onto_the_open_one(self) -> None:
        """``f(f^-1(R)) = R`` once the uncertainty (and with it the gravity) is gone."""
        for settings in (RankerSettings(), RankerSettings(rating_min=500, rating_max=4900, rating_avg=3000)):
            ranker = Ranker(settings)
            for open_rating in (settings.rating_min + 100, settings.rating_avg, 2000, 3500, settings.rating_max - 100):
                settled = HiddenRating(ranker.initial(open_rating).mu, 0.0)
                self.assertAlmostEqual(ranker.projection(settled), open_rating, places=6)

    def test_an_average_newcomer_projects_onto_the_average(self) -> None:
        ranker = Ranker()
        self.assertAlmostEqual(ranker.projection(ranker.initial(2400)), 2400, places=6)

    def test_settings_the_formulas_cannot_run_on_are_rejected(self) -> None:
        for bad in (
            RankerSettings(rating_avg=6000),
            RankerSettings(rating_min=3000, rating_avg=2400),
            RankerSettings(sigma_init=0),
        ):
            with self.assertRaises(ValueError):
                Ranker(bad)


class OpenDeltaTests(TestCase):
    def test_the_open_rating_never_moves_against_the_result(self) -> None:
        """A favoured low-rated winner whose sigma shrinks sees its projection
        drop -- the open rating must still not go down for a win."""
        for variant in _VARIANTS:
            ranker = Ranker(RankerSettings(variant=variant))
            old = HiddenRating(-150.0, 25.0)
            new = HiddenRating(-149.5, 24.4)
            self.assertLess(ranker.projection(new), ranker.projection(old))
            self.assertEqual(ranker.open_delta(800, old, new, outcome=1), 0.0)
            self.assertLessEqual(ranker.open_delta(800, new, old, outcome=-1), 0.0)

    def test_corrected_pull_closes_the_gap_without_crossing_it(self) -> None:
        ranker = Ranker(RankerSettings(variant="corrected"))
        old, new = HiddenRating(40.0, 20.0), HiddenRating(48.0, 19.0)
        for open_rating in (1500, 2400, 2700, 2799, 3600):
            gap = ranker.projection(old) - open_rating
            moved = open_rating + ranker.open_delta(open_rating, old, new, outcome=0)
            # The pull is measured against the hidden rating the match left behind.
            new_gap = ranker.projection(new) - moved
            self.assertLessEqual(abs(new_gap), abs(gap) + 1e-9)
            self.assertGreaterEqual(new_gap * gap, 0.0)

    def test_a_rating_above_the_range_is_not_snapped_back_by_a_win(self) -> None:
        """A champion stored above rating_max must not lose rating for winning."""
        for variant in _VARIANTS:
            ranker = Ranker(RankerSettings(variant=variant))
            old = ranker.initial(4800)
            new = HiddenRating(old.mu + 5.0, old.sigma - 0.5)
            self.assertEqual(ranker.open_delta(5200, old, new, outcome=1), 0.0)
            loss = ranker.open_delta(5200, new, old, outcome=-1)
            self.assertLess(loss, 0.0)
            self.assertGreater(loss, -100.0)


class EffectiveTests(TestCase):
    def test_a_confident_hidden_rating_corrects_and_a_noisy_one_does_not(self) -> None:
        """Same 300-point gap; only the hidden rating's own uncertainty differs."""
        ranker = Ranker(RankerSettings(variant="corrected"))

        def hidden_at(projection: float, sigma: float) -> HiddenRating:
            return HiddenRating(ranker.initial(projection).mu * (1 + 0.5 * sigma / 25.0), sigma)

        confident = ranker.effective(2500, hidden_at(2800, 3.0))
        noisy = ranker.effective(2500, hidden_at(2800, 25.0))
        self.assertGreater(confident, 2750)
        self.assertLess(noisy, 2600)

    def test_no_gap_leaves_the_open_rating(self) -> None:
        for variant in _VARIANTS:
            ranker = Ranker(RankerSettings(variant=variant))
            self.assertAlmostEqual(ranker.effective(2400, ranker.initial(2400)), 2400, places=6)


class RateTests(TestCase):
    def test_the_winners_rise_the_losers_fall_and_a_draw_between_equals_moves_nobody(self) -> None:
        ranker = Ranker()
        even = [[HiddenRating(0.0, 25.0)], [HiddenRating(0.0, 25.0)]]
        (win,), (loss,) = ranker.rate(even, winner=1)
        self.assertGreater(win.mu, 0.0)
        self.assertLess(loss.mu, 0.0)
        (a,), (b,) = ranker.rate(even, winner=None)
        self.assertAlmostEqual(a.mu, 0.0, places=9)
        self.assertAlmostEqual(b.mu, 0.0, places=9)


class HistoryFoldTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    _MATCHES = (
        # (home seats, away seats, home score, away score); a seat is (member, role, rank)
        ([(1, "tank", 2400), (2, "damage", 2600)], [(3, "tank", 2500), (4, "damage", 2300)], 1, 0),
        ([(1, "tank", 2400), (3, "damage", 2500)], [(2, "tank", 2600), (4, "damage", 2300)], 0, 1),
        ([(1, "tank", 2400), (4, "damage", 2300)], [(2, "tank", 2600), (3, "damage", 2500)], 0, 0),
    )

    def _history_rows(self) -> list[tuple[object, ...]]:
        rows = []
        for match_id, (home, away, home_score, away_score) in enumerate(self._MATCHES, start=1):
            for side, seats, score in (
                (CasualTeamSide.HOME, home, home_score),
                (CasualTeamSide.AWAY, away, away_score),
            ):
                rows.extend(
                    (match_id, side.value, score, member, HeroClass.from_slot_code(role), rank)
                    for member, role, rank in seats
                )
        return rows

    async def test_a_rebuild_reproduces_the_book_recording_built(self) -> None:
        """Undo and knob changes rebuild; recording advances in place. The two
        paths must agree or an undo would silently re-rate everyone."""
        service = in_memory_ranker()
        for home, away, home_score, away_score in self._MATCHES:
            winner = 1 if home_score > away_score else 2 if away_score > home_score else None
            await service.rate_match(None, workspace_id=1, teams=[home, away], winner=winner)
        recorded = dict(service.hidden.book)

        service.casual_matches.rows = self._history_rows()
        matches, ratings = await service.rebuild(None, 1)

        self.assertEqual((matches, ratings), (3, len(recorded)))
        self.assertEqual(set(service.hidden.book), set(recorded))
        for key, (mu, sigma) in recorded.items():
            self.assertAlmostEqual(service.hidden.book[key][0], mu, places=9)
            self.assertAlmostEqual(service.hidden.book[key][1], sigma, places=9)

    async def test_a_departed_seat_counts_for_its_team_but_is_not_stored(self) -> None:
        service = in_memory_ranker()
        service.casual_matches.rows = [
            (1, "home", 1, None, HeroClass.tank, 4000),
            (1, "away", 0, 2, HeroClass.tank, 2400),
            # A one-sided record is skipped rather than rated against nobody.
            (2, "home", 1, 2, HeroClass.tank, 2400),
        ]
        matches, ratings = await service.rebuild(None, 1)

        self.assertEqual((matches, ratings), (1, 1))
        # Losing to a 4000 costs little; it is the absent seat's strength that says so.
        self.assertLess(service.hidden.book[(2, "tank")][0], 0.0)

    async def test_saving_knobs_rebuilds_only_when_the_hidden_scale_changes(self) -> None:
        service = in_memory_ranker()
        service.casual_matches.rows = self._history_rows()
        service.configs.row = None
        service.configs.create = _record_create(service.configs)

        rebuilt = await service.save_settings(
            None, workspace_id=1, settings=RankerSettings(variant="reference", gravity=1.0), updated_by=9
        )
        self.assertFalse(rebuilt)
        self.assertEqual(service.hidden.book, {})

        service.configs.update_fields = _record_update()
        rebuilt = await service.save_settings(
            None, workspace_id=1, settings=RankerSettings(sigma_init=20.0), updated_by=9
        )
        self.assertTrue(rebuilt)
        self.assertEqual(len(service.hidden.book), 6)


def _record_create(configs):
    async def create(_session, row):
        configs.row = row
        return row

    return create


def _record_update():
    async def update_fields(_session, row, fields):
        for key, value in fields.items():
            setattr(row, key, value)

    return update_fields
