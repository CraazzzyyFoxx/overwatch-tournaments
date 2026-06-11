from __future__ import annotations

from src.services.balancer.algorithm.statistics import _sample_stdev_from_sums


class Player:
    """Represents a tournament player with ratings and role preferences."""

    __slots__ = (
        "uuid",
        "name",
        "ratings",
        "preferences",
        "subclasses",
        "discomfort_map",
        "is_captain",
        "is_flex",
        "captain_role",
        "_max_rating",
        "_mask",
    )

    def __init__(
        self,
        name: str,
        ratings: dict[str, int],
        preferences: list[str],
        uuid: str,
        mask: dict[str, int],
        is_flex: bool = False,
        subclasses: dict[str, str] | None = None,
    ) -> None:
        self.uuid = uuid
        self.name = name
        self.ratings = ratings
        self.preferences = preferences
        self.subclasses: dict[str, str] = subclasses or {}
        self.is_captain = False
        self.is_flex = is_flex
        self.captain_role: str | None = None
        self._max_rating = max(ratings.values()) if ratings else 0
        self._mask = mask

        self.discomfort_map = {}
        for role in self._mask:
            if is_flex and role in ratings:
                self.discomfort_map[role] = 0
            elif role in preferences:
                self.discomfort_map[role] = preferences.index(role) * 100
            else:
                self.discomfort_map[role] = 1000 if role in ratings else 5000

    @property
    def max_rating(self) -> int:
        return self.ratings[self.preferences[0]] if self.preferences else self._max_rating

    def get_rating(self, role: str) -> int:
        return self.ratings.get(role, 0)

    def can_play(self, role: str) -> bool:
        return role in self.ratings

    def get_discomfort(self, current_role: str) -> int:
        return self.discomfort_map.get(current_role, 5000)

    def __repr__(self) -> str:
        return self.name


class Team:
    """Represents a tournament team with a roster of players."""

    __slots__ = (
        "id",
        "roster",
        "_cached_mmr",
        "_cached_total_rating",
        "_cached_discomfort",
        "_cached_intra_std",
        "_cached_max_pain",
        "_cached_subrole_collisions",
        "_cached_role_totals",
        "_cached_role_spread_var",
        "_cached_role_spread_counted",
        "_is_dirty",
        "_mask",
    )

    def __init__(self, t_id: int, mask: dict[str, int]) -> None:
        self.id = t_id
        self._mask = mask
        self.roster = {role: [] for role in mask if mask[role] > 0}
        self._cached_mmr = 0.0
        self._cached_total_rating = 0.0
        self._cached_discomfort = 0.0
        self._cached_intra_std = 0.0
        self._cached_max_pain = 0
        self._cached_subrole_collisions = 0
        self._cached_role_totals: dict[str, float] = {}
        self._cached_role_spread_var = 0.0
        self._cached_role_spread_counted = False
        self._is_dirty = True

    def copy(self) -> Team:
        new_team = Team(self.id, self._mask)
        new_team.roster = {role: players[:] for role, players in self.roster.items()}
        new_team._cached_mmr = self._cached_mmr
        new_team._cached_total_rating = self._cached_total_rating
        new_team._cached_discomfort = self._cached_discomfort
        new_team._cached_intra_std = self._cached_intra_std
        new_team._cached_max_pain = self._cached_max_pain
        new_team._cached_subrole_collisions = self._cached_subrole_collisions
        new_team._cached_role_totals = self._cached_role_totals.copy()
        new_team._cached_role_spread_var = self._cached_role_spread_var
        new_team._cached_role_spread_counted = self._cached_role_spread_counted
        new_team._is_dirty = self._is_dirty
        return new_team

    def add_player(self, role: str, player: Player) -> bool:
        if len(self.roster[role]) < self._mask[role]:
            self.roster[role].append(player)
            self._is_dirty = True
            return True
        return False

    def replace_player(self, role: str, index: int, new_player: Player) -> None:
        self.roster[role][index] = new_player
        self._is_dirty = True

    def calculate_stats(self) -> None:
        if not self._is_dirty:
            return

        sum_rating = 0.0
        sum_rating2 = 0.0
        count = 0
        total_pain = 0
        max_pain_in_team = 0
        subrole_collisions = 0

        role_totals: dict[str, float] = {}
        role_avg_sum = 0.0
        role_avg_sum2 = 0.0
        role_avg_count = 0

        for role, players in self.roster.items():
            if not players:
                continue

            role_sum_rating = 0.0
            subrole_counts: dict[str, int] = {}
            for player in players:
                rating = player.ratings.get(role, 0)
                discomfort = player.discomfort_map.get(role, 5000)
                role_sum_rating += rating
                sum_rating2 += rating * rating
                total_pain += discomfort
                count += 1
                if discomfort > max_pain_in_team:
                    max_pain_in_team = discomfort

                subtype = player.subclasses.get(role, "")
                if subtype:
                    subrole_counts[subtype] = subrole_counts.get(subtype, 0) + 1

            sum_rating += role_sum_rating
            role_totals[role] = role_sum_rating
            role_avg = role_sum_rating / len(players)
            role_avg_sum += role_avg
            role_avg_sum2 += role_avg * role_avg
            role_avg_count += 1

            for occurrences in subrole_counts.values():
                if occurrences > 1:
                    subrole_collisions += occurrences * (occurrences - 1) // 2

        self._cached_total_rating = sum_rating

        if count > 0:
            self._cached_mmr = sum_rating / count
            self._cached_intra_std = _sample_stdev_from_sums(sum_rating, sum_rating2, count)
        else:
            self._cached_mmr = 0.0
            self._cached_intra_std = 0.0

        self._cached_discomfort = total_pain
        self._cached_max_pain = max_pain_in_team
        self._cached_subrole_collisions = subrole_collisions
        self._cached_role_totals = role_totals

        if role_avg_count >= 2:
            spread_var = (role_avg_sum2 / role_avg_count) - (role_avg_sum / role_avg_count) ** 2
            self._cached_role_spread_var = spread_var if spread_var > 0.0 else 0.0
            self._cached_role_spread_counted = True
        else:
            self._cached_role_spread_var = 0.0
            self._cached_role_spread_counted = False

        self._is_dirty = False

    @property
    def mmr(self) -> float:
        if self._is_dirty:
            self.calculate_stats()
        return self._cached_mmr

    @property
    def total_rating(self) -> float:
        if self._is_dirty:
            self.calculate_stats()
        return self._cached_total_rating

    @property
    def discomfort(self) -> float:
        if self._is_dirty:
            self.calculate_stats()
        return self._cached_discomfort

    @property
    def intra_std(self) -> float:
        if self._is_dirty:
            self.calculate_stats()
        return self._cached_intra_std

    @property
    def max_pain(self) -> int:
        if self._is_dirty:
            self.calculate_stats()
        return self._cached_max_pain

    @property
    def subrole_collisions(self) -> int:
        if self._is_dirty:
            self.calculate_stats()
        return self._cached_subrole_collisions

    def is_full(self) -> bool:
        for role, needed in self._mask.items():
            if len(self.roster.get(role, [])) < needed:
                return False
        return True


__all__ = ["Player", "Team"]
