from __future__ import annotations

import math


def _sample_stdev_from_sums(sum_x: float, sum_x2: float, n: int) -> float:
    """Fast sample stdev (like statistics.stdev) from sum(x), sum(x^2)."""
    if n < 2:
        return 0.0

    variance = (sum_x2 - (sum_x * sum_x) / n) / (n - 1)
    if variance <= 0.0:
        return 0.0

    return math.sqrt(variance)


def calculate_gap_penalty(max_team_gap: float) -> float:
    """Apply a non-linear penalty to the gap between the strongest and weakest teams."""
    if max_team_gap <= 25:
        return max_team_gap
    if max_team_gap <= 50:
        return max_team_gap * 2.0
    if max_team_gap <= 100:
        return max_team_gap * 5.0
    if max_team_gap <= 200:
        return max_team_gap * 12.0
    return max_team_gap * 30.0
