from __future__ import annotations

import statistics
import typing
from collections import Counter

from shared.domain.roster_shape import FLEX_SLOT_CODE
from src.domain.balancer.backends.base import BalanceMetrics
from src.domain.balancer.entities import Player, Team
from src.domain.balancer.feasibility_analyzer import FeasibilityReport
from src.services.balancer.config.defaults import MAX_RESULT_VARIANTS, AlgorithmConfig
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
                if _is_off_role(player, role):
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


def _is_off_role(player: Player, role: str) -> bool:
    """Off-role: a non-flex player sitting on a role slot that is not their main
    role. A flex SLOT names no role, so nobody is off-role on it -- and
    ``primary_role`` (not ``preferences[0]``, which the loader sets to ``flex``
    whenever the roster fields one) is what "their main role" means."""
    if player.is_flex or role == FLEX_SLOT_CODE:
        return False
    return player.primary_role is not None and player.primary_role != role


def _build_response_payload(
    result: list[Team],
    valid_players: list[Player],
    mask: dict[str, int],
    config: AlgorithmConfig,
    has_applied_overrides: bool,
    metrics: BalanceMetrics | None = None,
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
    if metrics is not None:
        stats.update({key: round(value, 4) for key, value in metrics.to_dict().items()})
    if feasibility is not None:
        actual_off_role = stats.get("off_role_count", 0)
        stats["off_role_above_minimum"] = max(0, actual_off_role - feasibility.structural_min_off_role)
        stats["feasibility"] = feasibility.to_dict()
    response_payload["statistics"] = stats
    if has_applied_overrides:
        response_payload["applied_config"] = serialize_algorithm_config(config)
    return response_payload


def lobby_document(payloads: typing.Iterable[typing.Any]) -> dict[str, typing.Any]:
    """Many ``_build_response_payload`` results of ONE run -> the lobby form.

    Every option of a run seats the same lobby, so the per-player facts that
    ``teams_to_json`` repeats in every seat of every option (name, ratings,
    preferences, flags) are written once under ``players``, and an option keeps
    only which uuid sits in which role bucket of which team plus its own
    numbers. A seat's rating is ``seat_rating(players[uuid], bucket)`` --
    exactly ``Player.get_rating``, so nothing is lost by not storing it.

    Dropped as run-level or unread: ``feasibility`` is hoisted to the root (one
    lobby, one structural floor); ``applied_config`` and the per-seat/per-team
    discomfort detail have no reader of the stored document.

    Tolerant of malformed entries because :func:`as_lobby_document` also feeds
    it documents stored by older code: a seat without a uuid is skipped, as the
    readers always did.
    """
    players: dict[str, dict[str, typing.Any]] = {}
    feasibility: typing.Any = None

    def seat(entry: typing.Any, role: str | None = None) -> str | None:
        if not isinstance(entry, typing.Mapping) or entry.get("uuid") is None:
            return None
        uuid = str(entry["uuid"])
        player = players.get(uuid)
        if player is None:
            player = players[uuid] = {
                "name": entry.get("name"),
                "is_captain": entry.get("is_captain") is True,
                "is_flex": entry.get("is_flex") is True,
                "role_preferences": list(entry.get("role_preferences") or []),
                "ratings": dict(entry.get("all_ratings") or {}),
            }
        if role is not None:
            # The seat's own rating fills a bucket the snapshot lacks (a document
            # older than ``all_ratings``); everywhere else the two already agree.
            rating = entry.get("assigned_rating")
            if role not in player["ratings"] and isinstance(rating, int | float):
                player["ratings"][role] = rating
            if entry.get("sub_role"):
                player.setdefault("sub_roles", {})[role] = entry["sub_role"]
        return uuid

    def seats(entries: typing.Any, role: str | None = None) -> list[str]:
        return (
            [uuid for entry in entries if (uuid := seat(entry, role)) is not None] if isinstance(entries, list) else []
        )

    variants = []
    for payload in payloads:
        if not isinstance(payload, typing.Mapping) or not isinstance(payload.get("teams"), list):
            continue
        stats = dict(payload.get("statistics") or {})
        feasibility = stats.pop("feasibility", feasibility)
        teams = []
        for team in payload["teams"]:
            if not isinstance(team, typing.Mapping):
                continue
            roster = team.get("roster")
            teams.append(
                {
                    "id": team.get("id"),
                    "average_mmr": team.get("average_mmr"),
                    "total_rating": team.get("total_rating"),
                    "roster": (
                        {role: seats(entries, role) for role, entries in roster.items()}
                        if isinstance(roster, typing.Mapping)
                        else {}
                    ),
                }
            )
        variants.append({"teams": teams, "statistics": stats, "benched": seats(payload.get("benched_players"))})
    return {"players": players, "feasibility": feasibility, "variants": variants}


def as_lobby_document(stored: typing.Any) -> dict[str, typing.Any] | None:
    """A mix's stored solver document in the lobby form, whichever form it was written in.

    Mixes balanced before :func:`lobby_document` hold ``{"variants": [payload, ...]}``
    (or one bare payload) and are upgraded here, on read, trimmed to the cap like
    a fresh run. Not by a migration: a release migrates while the previous
    containers are still serving, and those cannot read the lobby form.
    """
    if not isinstance(stored, typing.Mapping):
        return None
    if "players" in stored:
        return dict(stored)
    variants = stored.get("variants")
    payloads = variants if isinstance(variants, list) else [stored]
    return lobby_document(payloads[:MAX_RESULT_VARIANTS])


def seat_rating(player: typing.Mapping[str, typing.Any], bucket: str) -> int:
    """The rating a ``lobby_document`` player sits at in role ``bucket``."""
    ratings = player.get("ratings")
    return ratings.get(bucket, 0) if isinstance(ratings, typing.Mapping) else 0
