from __future__ import annotations

from shared.core.impact import MIN_RANK_POPULATION, RANK_QUINTILES
from shared.disciplines.overwatch.rank_quintiles import quintile_of

POPULATION = [1000.0 + 100 * i for i in range(10)]


def test_the_extremes_and_the_middle_of_a_population():
    assert quintile_of(1000.0, POPULATION) == 0
    assert quintile_of(1900.0, POPULATION) == RANK_QUINTILES - 1
    # 1400: 4 below, itself equal -> p = 4.5 / 10 -> quintile 2
    assert quintile_of(1400.0, POPULATION) == 2


def test_ties_take_the_mid_rank():
    population = [1.0, 2.0, 2.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    # 1 below + half of three equal = 2.5 / 10 -> floor(5 * 0.25) = 1
    assert quintile_of(2.0, population) == 1


def test_the_quintile_is_capped_for_a_value_above_everyone():
    assert quintile_of(10_000.0, POPULATION) == RANK_QUINTILES - 1


def test_a_value_below_everyone_is_the_lowest_quintile():
    assert quintile_of(1.0, POPULATION) == 0


def test_no_quintile_without_a_value_or_a_big_enough_population():
    assert quintile_of(None, POPULATION) is None
    assert quintile_of(1.0, POPULATION[: MIN_RANK_POPULATION - 1]) is None
    assert quintile_of(1.0, POPULATION[:MIN_RANK_POPULATION]) == 0


def test_population_order_is_irrelevant():
    assert quintile_of(1400.0, list(reversed(POPULATION))) == quintile_of(1400.0, POPULATION)
