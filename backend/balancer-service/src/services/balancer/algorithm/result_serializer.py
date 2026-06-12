from __future__ import annotations

import statistics
import typing
from collections import Counter

from src.services.balancer.algorithm.entities import Player, Team
from src.services.balancer.algorithm.feasibility_analyzer import FeasibilityReport
from src.services.balancer.config.defaults import AlgorithmConfig
from src.services.balancer.config.public_contract import serialize_algorithm_config


def teams_to_json(
    teams: list[Team],
    mask: dict[str, int],
    benched_players: list[Player] | None = None,
) -> dict[str, typing.Any]:
    """Convert teams to a JSON-serializable dictionary for API responses."""
    result = {"teams": [], "statistics": {}, "benched_players": []}
    # Канонический порядок отображения: сильнейшая команда первой, слабейшая — последней.
    # Даёт стабильное side-by-side сравнение между вариантами (независимо от того, какой
    # backend сгенерировал решение) и убирает "прыжки" команд между слотами в UI.
    teams = sorted(teams, key=lambda team: team.total_rating, reverse=True)

    for team in teams:
        captain_name = None
        for players in team.roster.values():
            for player in players:
                if player.is_captain:
                    captain_name = player.name
                    break
            if captain_name:
                break

        team_data = {
            "id": team.id,
            "name": captain_name or f"Team {team.id}",
            "average_mmr": round(team.mmr, 2),
            "total_rating": round(team.total_rating, 2),
            "rating_variance": round(team.intra_std, 2),
            "total_discomfort": team.discomfort,
            "max_discomfort": team.max_pain,
            "roster": {},
        }

        for role, players in team.roster.items():
            team_data["roster"][role] = [
                {
                    "uuid": player.uuid,
                    "name": player.name,
                    "assigned_rating": player.get_rating(role),
                    "role_discomfort": player.get_discomfort(role),
                    "is_captain": player.is_captain,
                    "is_flex": player.is_flex,
                    "role_preferences": player.preferences,
                    "all_ratings": player.ratings,
                    "all_discomforts": player.discomfort_map,
                    "sub_role": player.subclasses.get(role) or None,
                }
                for player in players
            ]

        result["teams"].append(team_data)

    all_totals = [team.total_rating for team in teams]
    all_mmrs = [team.mmr for team in teams]

    off_role_count = 0
    for team in teams:
        for role, players in team.roster.items():
            for player in players:
                if not player.is_flex and player.preferences and player.preferences[0] != role:
                    off_role_count += 1

    sub_role_collision_count = 0
    for team in teams:
        role_subclass_list: list[tuple[str, str]] = []
        for role, players in team.roster.items():
            for player in players:
                subclass = player.subclasses.get(role, "")
                if subclass:
                    role_subclass_list.append((role, subclass))
        counts = Counter(role_subclass_list)
        for count in counts.values():
            if count > 1:
                sub_role_collision_count += count * (count - 1) // 2

    total_placed_players = sum(len(players) for team in teams for players in team.roster.values())
    off_role_rate = off_role_count / total_placed_players if total_placed_players else 0.0

    if len(all_totals) > 1:
        result["statistics"] = {
            "average_mmr": round(statistics.mean(all_mmrs), 2),
            "mmr_std_dev": round(statistics.stdev(all_mmrs), 2),
            "average_total_rating": round(statistics.mean(all_totals), 2),
            "total_rating_std_dev": round(statistics.stdev(all_totals), 2),
            "max_total_rating_gap": round(max(all_totals) - min(all_totals), 2),
            "total_teams": len(teams),
            "players_per_team": sum(mask.values()),
            "off_role_count": off_role_count,
            "off_role_rate": round(off_role_rate, 4),
            "sub_role_collision_count": sub_role_collision_count,
        }
    else:
        result["statistics"] = {
            "average_mmr": round(all_mmrs[0], 2) if all_mmrs else 0,
            "mmr_std_dev": 0,
            "average_total_rating": round(all_totals[0], 2) if all_totals else 0,
            "total_rating_std_dev": 0,
            "max_total_rating_gap": 0,
            "total_teams": len(teams),
            "players_per_team": sum(mask.values()),
            "off_role_count": off_role_count,
            "off_role_rate": round(off_role_rate, 4),
            "sub_role_collision_count": sub_role_collision_count,
        }

    if benched_players:
        result["benched_players"] = [
            {
                "uuid": player.uuid,
                "name": player.name,
                "assigned_rating": player.max_rating,
                "role_discomfort": 0,
                "is_captain": player.is_captain,
                "is_flex": player.is_flex,
                "role_preferences": player.preferences,
                "all_ratings": player.ratings,
                "all_discomforts": player.discomfort_map,
            }
            for player in benched_players
        ]

    return result


def _build_response_payload(
    result: list[Team],
    valid_players: list[Player],
    mask: dict[str, int],
    config: AlgorithmConfig,
    has_applied_overrides: bool,
    metrics: dict[str, float] | None = None,
    feasibility: FeasibilityReport | None = None,
) -> dict[str, typing.Any]:
    placed_uuids: set[str] = set()
    for team in result:
        for role_players in team.roster.values():
            for player in role_players:
                placed_uuids.add(player.uuid)

    benched = [player for player in valid_players if player.uuid not in placed_uuids]
    response_payload = teams_to_json(result, mask, benched_players=benched)
    stats = response_payload.get("statistics") or {}
    if metrics:
        stats["balance_objective"] = round(float(metrics.get("balance_objective", 0.0)), 4)
        stats["comfort_objective"] = round(float(metrics.get("comfort_objective", 0.0)), 4)
        stats["balance_objective_norm"] = round(float(metrics.get("balance_objective_norm", 0.0)), 4)
        stats["comfort_objective_norm"] = round(float(metrics.get("comfort_objective_norm", 0.0)), 4)
        stats["composite_score"] = round(float(metrics.get("composite_score", 0.0)), 4)
    if feasibility is not None:
        actual_off_role = stats.get("off_role_count", 0)
        stats["off_role_above_minimum"] = max(0, actual_off_role - feasibility.structural_min_off_role)
        stats["feasibility"] = feasibility.to_dict()
    response_payload["statistics"] = stats
    if has_applied_overrides:
        response_payload["applied_config"] = serialize_algorithm_config(config)
    return response_payload
