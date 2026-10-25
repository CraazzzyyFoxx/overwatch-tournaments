"""Immutable P3 reader parity and native historical-consumer regressions.

The golden was captured before native cutover. Tests only read it; intentional
wire/identity changes are projected without changing its numeric expectations.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from difflib import unified_diff
from enum import Enum
from itertools import groupby, islice
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared import models
from shared.core.errors import BaseAPIException
from shared.services.match_reads import match_statistics_read
from shared.services.tournament.visibility import ensure_tournament_viewable
from src import schemas
from src.services.admin.matches import matches_service
from src.services.encounter.flows import flows_service as encounters
from src.services.tournament.flows import flows_service as tournaments
from src.services.visibility_resolvers import visibility_resolvers_service as visibility

GOLDEN = Path(__file__).parent / "fixtures" / "stats_reader_parity.json"
_MATCH_KEYS = ("match", "match_reversed", "match_no_raw", "match_other", "match_hidden")
_USER_KEYS = ("player", "player_away", "player_event_only", "player_other", "player_removed", "player_no_member")
_ENCOUNTER_ENTITIES = (
    "tournament",
    "teams",
    "teams.players",
    "matches",
    "matches.map",
    "matches.teams",
)
_MATCH_ENTITIES = ("map", "teams", "teams.players", "encounter", "encounter.tournament")


async def _uncached(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Bypass only decorators, never the real reader/serializer or its SQL."""
    return await inspect.unwrap(method.__func__)(method.__self__, *args, **kwargs)


def _normalize(value: Any) -> Any:
    """Representation only: JSON-comparable scalars and the order of unordered relationship aggregates."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("parity timestamps must have a timezone")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # The reader returns NUMERIC(10, 2); compare its number, not Decimal's spelling.
        return float(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if not isinstance(value, dict):
        return value

    row = {str(_normalize(key)): _normalize(item) for key, item in value.items()}
    # These are unordered relationship/JSON aggregates, not ranked result lists.
    if isinstance(row.get("matches"), list):
        row["matches"].sort(key=lambda match: (match["map_index"] is None, match["map_index"] or 0, match["id"]))
    if isinstance(row.get("players"), list):
        row["players"].sort(
            key=lambda player: (
                player["user_id"] is None,
                player["user_id"],
                player.get("workspace_member_id", player.get("id")),
            )
        )
    if isinstance(row.get("heroes"), dict):
        for heroes in row["heroes"].values():
            heroes.sort(key=lambda hero: hero["id"])
    if "position" in row and isinstance(row.get("teams"), list):
        row["teams"].sort(key=lambda team: team["encounter_team_id"])
    return row


_HERO_FIELDS = ("id", "slug", "name", "image_path", "type", "color")


def _score(participant: dict[str, Any]) -> int | float | None:
    """The participant's observed ``score`` team fact; the frozen oracle spelled whole scores as integers."""
    value = participant["team_facts"].get("score")
    return int(value) if value is not None and float(value).is_integer() else value


def _cents(value: float) -> float:
    """What ``sum(value)::numeric(10, 2)`` returned for one observation."""
    return float(Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _observed_players(statistics: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """The pre-native observed-player view of a native statistics document, keyed by participation.

    Projection only: members are the match's observed identities, ``stats`` their segment-keyed values without an
    entity grain, ``heroes`` the characters they played longer than a minute in each segment. Native facts are never
    reduced or recomputed; the numeric cast is the old reader's.
    """
    entities = {entity["id"]: entity for entity in statistics["entities"]}
    players = {
        (member["encounter_team_id"], member["workspace_member_id"]): {
            "workspace_member_id": member["workspace_member_id"],
            "user_id": member["player_id"],
            "name": member["handle_snapshot"],
            "stats": {},
            "heroes": {},
        }
        for member in statistics["members"]
    }
    for fact in statistics["facts"]:
        if fact["workspace_member_id"] is None:
            continue
        player = players[fact["encounter_team_id"], fact["workspace_member_id"]]
        if fact["entity_id"] is None:
            player["stats"].setdefault(fact["segment"], {})[fact["stat_code"]] = _cents(fact["value"])
        elif fact["stat_code"] == "hero_time_played" and fact["value"] > 60:
            entity = entities[fact["entity_id"]]
            player["heroes"].setdefault(fact["segment"], []).append(
                {
                    "id": entity["id"],
                    "created_at": entity["created_at"],
                    "updated_at": entity["updated_at"],
                    "name": entity["name"],
                    "slug": entity["slug"],
                    "image_path": entity["image_path"] or "",
                    "color": entity["attrs"].get("color") or "#ffffff",
                    "type": entity["attrs"].get("class"),
                }
            )
    by_seat: dict[int, list[dict[str, Any]]] = {}
    for (seat, _member), player in players.items():
        by_seat.setdefault(seat, []).append(player)
    return by_seat


def _legacy_map(entity: dict[str, Any] | None) -> dict[str, Any] | None:
    """A native map entity in the frozen ``MapRead`` representation (its mode is ``gamemode``)."""
    if entity is None:
        return None
    parent = entity["parent"]
    return {
        "id": entity["id"],
        "name": entity["name"],
        "image_path": entity["image_path"] or "",
        "gamemode_id": entity["parent_id"],
        "in_competitive": entity["attrs"].get("in_competitive", True),
        "gamemode": None
        if parent is None
        else {
            "id": parent["id"],
            "slug": parent["slug"],
            "name": parent["name"],
            "image_path": parent["image_path"] or "",
            "description": parent["attrs"].get("description"),
        },
    }


async def _source_team(session: AsyncSession, team_id: int, entities: list[str]) -> dict[str, Any]:
    """The source team through the production team reader, as the pre-native match expanded it."""
    from shared.repository import TeamRepository

    team = await TeamRepository().get(
        session, team_id, options=TeamRepository.team_entities(entities), populate_existing=True
    )
    return (await encounters.teams.to_pydantic(session, team, entities)).model_dump(mode="python")


async def _golden_match(
    session: AsyncSession,
    match: dict[str, Any],
    entities: list[str],
    statistics: dict[str, Any] | None = None,
    team_cache: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One native match (``MatchRead``/``MatchReadWithStats`` dump) in the frozen per-participant representation.

    Scores are the participants' observed ``score`` team facts, the source teams are the production team reader's
    output for each participant's source team, and ``time`` is the duration. Nothing is invented: a participant with
    no source team has no team, one with no ``score`` fact has no score. ``team_cache`` is what the frozen encounter
    read had already expanded for its seats: a match nested in it reused those team reads, richer than its own
    ``teams`` entity asked for.
    """
    from shared.core import utils

    team_entities = utils.prepare_entities(entities, "teams")
    row: dict[str, Any] = {
        "id": match["id"],
        "workspace_id": match["workspace_id"],
        "discipline": match["discipline"],
        "encounter_id": match["encounter_id"],
        "map_id": match["map_id"],
        "map_index": match["map_index"],
        "time": match["duration_s"],
        "log_name": match["log_name"],
        "map": _legacy_map(match["map"]),
        "encounter": None if match["encounter"] is None else await _golden(session, match["encounter"], []),
        "scores_by_participant": {},
        "teams_by_participant": {},
        "team_ids_by_participant": {},
    }
    observed = _observed_players(statistics) if statistics is not None else {}
    for participant in match["participants"]:
        seat, source = participant["encounter_team_id"], participant["tournament_team_id"]
        key = str(seat)
        row["scores_by_participant"][key] = _score(participant)
        row["team_ids_by_participant"][key] = source
        team = None
        if ("teams" in entities) and source is not None:
            team = (team_cache or {}).get(source) or await _source_team(session, source, team_entities)
            team = deepcopy(team)
            if statistics is not None and "players" in team:
                present = {player["user_id"]: player for player in observed.get(seat, [])}
                assert len(present) == len(observed.get(seat, []))
                roster_ids = {player["user_id"] for player in team["players"]}
                assert all(
                    player["user_id"] in roster_ids or not (player["stats"] or player["heroes"])
                    for player in present.values()
                )
                team["players"] = [
                    {
                        **player,
                        "stats": present[player["user_id"]]["stats"],
                        "heroes": {
                            segment: [{key: hero[key] for key in _HERO_FIELDS} for hero in heroes]
                            for segment, heroes in present[player["user_id"]]["heroes"].items()
                        },
                    }
                    for player in team["players"]
                    if player["user_id"] in present and present[player["user_id"]]["heroes"]
                ]
        row["teams_by_participant"][key] = team
    if statistics is not None:
        row["rounds"] = max(
            (segment for players in observed.values() for player in players for segment in player["stats"]), default=0
        )
    return row


async def _golden(
    session: AsyncSession,
    value: Any,
    entities: list[str],
    team_cache: dict[int, dict[str, Any]] | None = None,
    *,
    page: bool = False,
) -> Any:
    """Dump native output and replace every match in it (``entities`` is what its reader expanded) and every
    ``EncounterGameRead.map`` by the frozen representation. ``page`` marks a paginated encounter read, the one that
    shared a team cache between an encounter's seats and its matches."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, (list, tuple)):
        return [await _golden(session, item, entities, team_cache, page=page) for item in value]
    if not isinstance(value, dict):
        return value
    if {"participants", "encounter_id", "map_id"} <= value.keys():
        return await _golden_match(session, value, entities, team_cache=team_cache)
    cache = team_cache
    if page and isinstance(value.get("matches"), list) and isinstance(value.get("teams"), list):
        cache = {
            **(team_cache or {}),
            **{seat["team"]["id"]: seat["team"] for seat in value["teams"] if seat.get("team")},
        }
    row = {key: await _golden(session, item, entities, cache, page=page) for key, item in value.items()}
    if "position" in row and "map" in row and "teams" in row:
        row["map"] = _legacy_map(value["map"])
    return row


async def _golden_admin(session: AsyncSession, row: Any) -> dict[str, Any]:
    """An admin row/detail in the frozen representation: the source teams by participant, ``time``, ``map_name``."""
    data = row.model_dump(mode="python")
    names = dict(
        (
            await session.execute(
                sa.select(models.Team.id, models.Team.name).where(
                    models.Team.id.in_(
                        [p["tournament_team_id"] for p in data["participants"] if p["tournament_team_id"]]
                    )
                )
            )
        ).all()
    )
    golden = {
        key: data[key]
        for key in (
            "id",
            "encounter_id",
            "encounter_name",
            "tournament_id",
            "tournament_name",
            "map_id",
            "log_name",
            "created_at",
            "log_record",
            "rounds",
            "statistics_count",
            "kill_feed_count",
            "event_count",
        )
        if key in data
    }
    golden["map_name"] = data["map"]["name"]
    golden["time"] = data["duration_s"]
    golden["scores_by_participant"] = {str(p["encounter_team_id"]): _score(p) for p in data["participants"]}
    golden["team_ids_by_participant"] = {
        str(p["encounter_team_id"]): p["tournament_team_id"] for p in data["participants"]
    }
    golden["teams_by_participant"] = {
        str(p["encounter_team_id"]): None
        if p["tournament_team_id"] is None
        else {"id": p["tournament_team_id"], "name": names[p["tournament_team_id"]]}
        for p in data["participants"]
    }
    return golden


def _golden_killfeed(feed: Any, statistics: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
    """A native event timeline in the frozen kill-feed/timeline representation.

    Actors resolve to their global player and source team through the match's own members and participants; only
    kills and the three timeline types the old reader selected are kept.
    """
    from shared.core.enums import HeroClass

    data = feed.model_dump(mode="python")
    player = {member["workspace_member_id"]: member["player_id"] for member in statistics["members"]}
    source = {participant["encounter_team_id"]: participant["tournament_team_id"] for participant in participants}
    entities = {entity["id"]: entity for entity in data["entities"]}

    def hero(entity_id: int | None) -> Any:
        """The frozen OW hero object (the pre-native ``HeroRead`` wire, removed by §4.1) of a native entity."""
        if entity_id is None:
            return None
        entity = entities[entity_id]
        attrs = entity["attrs"]
        return {
            "id": entity["id"],
            "slug": entity["slug"],
            "name": entity["name"],
            "image_path": entity["image_path"] or "",
            "type": HeroClass[attrs["class"]].value,
            "color": attrs.get("color", "#ffffff"),
        }

    def team(seat: int | None) -> int | None:
        return None if seat is None else source[seat]

    def who(member: int | None) -> int | None:
        return None if member is None else player[member]

    kills, events = [], []
    for event in data["events"]:
        extra = event["data"] or {}
        if event["type"] == "kill":
            kills.append(
                {
                    "time": event["t"],
                    "round": event["segment"],
                    "fight": extra.get("fight"),
                    "ability": extra.get("ability"),
                    "damage": extra.get("damage"),
                    "is_critical_hit": extra.get("is_critical_hit"),
                    "is_environmental": extra.get("is_environmental"),
                    "killer_user_id": who(event["actor_member_id"]),
                    "killer_team_id": team(event["actor_team_id"]),
                    "killer_hero": hero(event["entity_id"]),
                    "victim_user_id": who(event["target_member_id"]),
                    "victim_team_id": team(event["target_team_id"]),
                    "victim_hero": hero(event["related_entity_id"]),
                }
            )
        elif event["type"] in ("ultimate_start", "ultimate_end", "mercy_rez"):
            events.append(
                {
                    "time": event["t"],
                    "round": event["segment"],
                    "name": event["type"],
                    "user_id": who(event["actor_member_id"]),
                    "team_id": team(event["actor_team_id"]),
                    "hero": hero(event["entity_id"]),
                    "related_user_id": who(event["target_member_id"]),
                    "related_team_id": team(event["target_team_id"]),
                }
            )
    return {"match_id": data["match_id"], "kills": kills, "events": events}


def _stats_result(player: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "statistics": {} if player is None else player["stats"],
        "heroes": {} if player is None else player["heroes"],
    }


async def _not_found(operation: Any) -> dict:
    """Capture the actual denial, and refuse to bless an unexpected successful read."""
    with pytest.raises(BaseAPIException) as caught:
        await operation
    assert caught.value.status_code == 404
    return {"status_code": caught.value.status_code, "detail": caught.value.detail, "headers": caught.value.headers}


async def collect_outputs(session: AsyncSession, ids: dict[str, int]) -> dict:
    """Project native reader outputs onto the frozen P3 numeric and metadata oracle."""
    from shared.core import utils

    workspace = ids["workspace"]
    outputs: dict[str, Any] = {}

    encounter_cases = {
        "platform_first": (None, {"page": 1, "per_page": 1}),
        "platform_second": (None, {"page": 2, "per_page": 1}),
        "platform_past_end": (None, {"page": 3, "per_page": 1}),
        "platform_desc": (None, {"order": "desc"}),
        "workspace_expanded": (workspace, {"entities": list(_ENCOUNTER_ENTITIES)}),
        "other_workspace": (ids["workspace_other"], {"entities": list(_ENCOUNTER_ENTITIES)}),
        "only_count": (workspace, {"only_count": True, "entities": ["matches", "matches.map"]}),
        "with_logs": (workspace, {"has_logs": True}),
        "without_logs": (workspace, {"has_logs": False}),
        "name_search": (workspace, {"query": "P4 encounter", "fields": ["name"], "status": "completed", "best_of": 3}),
        "foreign_tournament": (workspace, {"tournament_id": ids["tournament_other"]}),
        "my_team_anonymous": (workspace, {"scope": "my_team"}),
    }
    outputs["encounter_pages"] = {}
    for name, (scope, options) in encounter_cases.items():
        page = await _uncached(
            encounters.get_all_encounters,
            session,
            schemas.EncounterSearchParams(**options),
            workspace_id=scope,
        )
        outputs["encounter_pages"][name] = await _golden(
            session, page, utils.prepare_entities(options.get("entities", []), "matches"), page=True
        )
    outputs["encounter_pages"]["my_team_global"] = await _golden(
        session,
        await _uncached(
            encounters.get_all_encounters,
            session,
            schemas.EncounterSearchParams(scope="my_team"),
            viewer_auth_user_id=ids["auth_user"],
        ),
        [],
    )

    outputs["encounter_details"] = {}
    for name in ("encounter", "encounter_other"):
        tournament_id = await visibility.tournament_id_for_encounter(session, ids[name])
        await ensure_tournament_viewable(session, None, tournament_id)
        outputs["encounter_details"][name] = await _golden(
            session,
            await encounters.get_encounter(session, ids[name], list(_ENCOUNTER_ENTITIES)),
            utils.prepare_entities(list(_ENCOUNTER_ENTITIES), "matches"),
        )

    outputs["encounter_overviews"] = {}
    outputs["tournament_overviews"] = {}
    for name, scope in (("platform", None), ("workspace", workspace), ("other_workspace", ids["workspace_other"])):
        # Collected so the read runs over the parity data; the redesigned shape is not compared (``comparable``).
        outputs["encounter_overviews"][name] = await _golden(
            session,
            await _uncached(
                encounters.get_encounters_overview,
                session,
                schemas.EncounterSearchParams(),
                workspace_id=scope,
            ),
            ["map"],
        )
        outputs["tournament_overviews"][name] = await tournaments.get_tournaments_overall(session, workspace_id=scope)

    match_cases = {
        "platform": (None, {"per_page": -1}),
        "workspace_first": (workspace, {"page": 1, "per_page": 2, "entities": list(_MATCH_ENTITIES)}),
        "workspace_second": (workspace, {"page": 2, "per_page": 2, "entities": list(_MATCH_ENTITIES)}),
        "workspace_past_end": (workspace, {"page": 3, "per_page": 2}),
        "workspace_desc": (workspace, {"order": "desc"}),
        "other_workspace": (ids["workspace_other"], {"entities": list(_MATCH_ENTITIES)}),
        "only_count": (workspace, {"only_count": True, "entities": ["teams", "teams.players"]}),
        "tournament": (
            workspace,
            {"tournament_id": ids["tournament"], "sort": "map_index", "entities": ["map", "teams"]},
        ),
        "foreign_tournament": (workspace, {"tournament_id": ids["tournament_other"]}),
        "log_name_search": (workspace, {"query": "reverse", "fields": ["log_name"], "entities": ["map", "teams"]}),
        "duration_desc": (workspace, {"order": "desc", "sort": "duration_s"}),
    }
    outputs["match_pages"] = {}
    for name, (scope, options) in match_cases.items():
        outputs["match_pages"][name] = await _golden(
            session,
            await encounters.get_all_matches(
                session,
                schemas.MatchSearchParams(**options),
                workspace_id=scope,
            ),
            options.get("entities", []),
        )

    outputs["match_details"] = {}
    outputs["match_details_with_stats"] = {}
    outputs["killfeeds"] = {}
    for name in _MATCH_KEYS[:-1]:
        scope = ids["workspace_other"] if name == "match_other" else workspace
        tournament_id = await visibility.tournament_id_for_match(session, ids[name])
        await ensure_tournament_viewable(session, None, tournament_id)
        outputs["match_details"][name] = await _golden(
            session,
            await encounters.get_match(
                session,
                ids[name],
                list(_MATCH_ENTITIES),
                workspace_id=scope,
            ),
            list(_MATCH_ENTITIES),
        )
        detail = (
            await _uncached(
                encounters.get_match_with_stats,
                session,
                ids[name],
                list(_MATCH_ENTITIES),
                workspace_id=scope,
            )
        ).model_dump(mode="python")
        outputs["match_details_with_stats"][name] = await _golden_match(
            session, detail, list(_MATCH_ENTITIES), detail["statistics"]
        )
        # Do not sort/deduplicate either array: round/time/source order is behavior.
        outputs["killfeeds"][name] = _golden_killfeed(
            await _uncached(
                encounters.get_match_kill_feed,
                session,
                ids[name],
                workspace_id=scope,
            ),
            detail["statistics"],
            detail["participants"],
        )

    outputs["single_user_stats"] = {}
    outputs["batch_user_stats"] = {}
    for match in _MATCH_KEYS:
        statistics = (await match_statistics_read(session, ids[match])).model_dump(mode="python")
        players = [player for seat in _observed_players(statistics).values() for player in seat]
        by_user = {player["user_id"]: player for player in players}
        assert len(by_user) == len(players)
        outputs["single_user_stats"][match] = {user: _stats_result(by_user.get(ids[user])) for user in _USER_KEYS}
        outputs["batch_user_stats"][match] = {ids[user]: _stats_result(by_user.get(ids[user])) for user in _USER_KEYS}

    # The old admin DTO requires non-null time/log_name. Use its real provenance
    # filter for row pages; unfiltered count still includes the no-raw match.
    outputs["admin_pages"] = {}
    admin_cases = {
        "workspace_first": (workspace, {"page": 1, "per_page": 2, "log_status": ["done"]}),
        "workspace_second": (workspace, {"page": 2, "per_page": 2, "log_status": ["done"]}),
        "other_workspace": (ids["workspace_other"], {"log_status": ["done"]}),
        "all_rows_count": (workspace, {"only_count": True}),
        "tournament": (workspace, {"tournament_id": ids["tournament"], "log_status": ["done"]}),
        "map": (workspace, {"map_id": ids["map_other"], "log_status": ["done"]}),
        "name_search": (workspace, {"query": "reverse", "log_status": ["done"]}),
        "foreign_tournament": (workspace, {"tournament_id": ids["tournament_other"], "log_status": ["done"]}),
    }
    for name, (scope, options) in admin_cases.items():
        page = await matches_service.list_admin_matches(
            session,
            workspace_id=scope,
            params=schemas.AdminMatchesSearchParams(**options),
        )
        outputs["admin_pages"][name] = {
            **page.model_dump(mode="python", exclude={"results"}),
            "results": [await _golden_admin(session, row) for row in page.results],
        }
    outputs["admin_details"] = {}
    for name in ("match", "match_reversed", "match_other", "match_hidden"):
        outputs["admin_details"][name] = await _golden_admin(
            session,
            await matches_service.get_admin_match(
                session,
                workspace_id=ids["workspace_other"] if name == "match_other" else workspace,
                match_id=ids[name],
            ),
        )

    outputs["visibility"] = {}
    for kind, resolve in (
        ("encounter", visibility.tournament_id_for_encounter),
        ("match", visibility.tournament_id_for_match),
    ):
        owners = {
            name: await resolve(session, ids[f"{kind}{suffix}"])
            for name, suffix in (("visible", ""), ("foreign", "_other"), ("hidden", "_hidden"))
        }
        outputs["visibility"][f"{kind}_owners"] = owners
        outputs["visibility"][f"hidden_{kind}"] = await _not_found(
            ensure_tournament_viewable(session, None, owners["hidden"]),
        )
    outputs["visibility"]["foreign_match"] = await _not_found(
        encounters.get_match(session, ids["match_other"], [], workspace_id=workspace),
    )
    outputs["visibility"]["foreign_match_stats"] = await _not_found(
        _uncached(
            encounters.get_match_with_stats,
            session,
            ids["match_other"],
            [],
            workspace_id=workspace,
        )
    )
    outputs["visibility"]["foreign_killfeed"] = await _not_found(
        _uncached(
            encounters.get_match_kill_feed,
            session,
            ids["match_other"],
            workspace_id=workspace,
        )
    )
    outputs["visibility"]["foreign_admin_match"] = await _not_found(
        matches_service.get_admin_match(session, workspace_id=workspace, match_id=ids["match_other"]),
    )
    return _normalize(outputs)


def assert_tournament_golden(actual: dict) -> None:
    def without_post_capture_fields(value):
        """Fields added after the frozen P4 capture are not reader output: ``TournamentRead.logs_official`` (P5) and
        ``pov_stream_delay_s``, the owner context (``workspace_id``/``discipline``) P7 added to ``EncounterRead`` and
        ``MatchRead``, and the browse's ``played_at``/``is_live``/``is_final`` on ``EncounterRead`` (a match's own
        ``played_at`` was captured and stays). The golden's nested ``tournament`` objects already carried theirs and
        keep them."""
        if isinstance(value, dict):
            encounter = value.keys() >= {"scoring_preset", "tournament_id"}
            owner = encounter or value.keys() >= {"encounter_id", "map_id"}
            dropped = {
                "logs_official",
                "pov_stream_delay_s",
                *(("workspace_id", "discipline") if owner else ()),
                *(("played_at", "is_live", "is_final") if encounter else ()),
            }
            return {key: without_post_capture_fields(item) for key, item in value.items() if key not in dropped}
        if isinstance(value, list):
            return [without_post_capture_fields(item) for item in value]
        return value

    def comparable(payload):
        payload = without_post_capture_fields(deepcopy(payload))
        # The removed roster/user-batch API's empty-input shape has no facts.
        payload.pop("empty_user_batch", None)
        # The encounters overview was redesigned after the capture (the browse's counts and live strip, its
        # analytics moved to the insights read); ``test_encounter_board_db.py`` pins the new numbers.
        payload.pop("encounter_overviews", None)
        page = payload["match_pages"]["duration_desc"]
        # SQL orders only by duration. Preserve every group and its position;
        # incidental order inside equal-duration groups is not a reader contract.
        page["results"] = [
            row
            for _, tied_rows in groupby(page["results"], key=lambda row: row["time"])
            for row in sorted(tied_rows, key=lambda row: row["id"])
        ]
        return payload

    expected = comparable(json.loads(GOLDEN.read_text(encoding="utf-8")))
    normalized = comparable(actual)
    if normalized != expected:
        difference = unified_diff(
            json.dumps(expected, indent=2, sort_keys=True).splitlines(),
            json.dumps(normalized, indent=2, sort_keys=True).splitlines(),
            fromfile="frozen",
            tofile="native",
            lineterm="",
        )
        raise AssertionError("\n".join(islice(difference, 200)))


def test_duration_ties_keep_primary_order_and_exact_rows():
    actual = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows = actual["match_pages"]["duration_desc"]["results"]
    tied = next(index for index in range(len(rows) - 1) if rows[index]["time"] == rows[index + 1]["time"])
    rows[tied], rows[tied + 1] = rows[tied + 1], rows[tied]
    assert_tournament_golden(actual)

    for change in ("primary_order", "missing_row", "observed_score"):
        changed = deepcopy(actual)
        changed_rows = changed["match_pages"]["duration_desc"]["results"]
        if change == "primary_order":
            unequal = next(
                index
                for index in range(len(changed_rows) - 1)
                if changed_rows[index]["time"] != changed_rows[index + 1]["time"]
            )
            changed_rows[unequal], changed_rows[unequal + 1] = changed_rows[unequal + 1], changed_rows[unequal]
        elif change == "missing_row":
            changed_rows.pop()
        else:
            scores = changed_rows[0]["scores_by_participant"]
            scores[next(iter(scores))] += 1
        with pytest.raises(AssertionError):
            assert_tournament_golden(changed)


def test_native_readers_preserve_captured_p3_outputs(stats_parity_database):
    async def exercise():
        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                assert_tournament_golden(await collect_outputs(session, ids))
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_native_readers_serve_a_match_of_another_discipline_under_its_own_discipline(stats_parity_database):
    async def exercise():
        from shared.models.stats.match import StatsMatch
        from shared.testing.stats_parity import seed_native_sentinel

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                overall_before = await _uncached(
                    tournaments.get_tournaments_overall,
                    session,
                    workspace_id=ids["workspace"],
                )
                # Only this adversarial clone gains LoL rows. The base golden and
                # genuinely multigame overview/count readers keep their own contract.
                await session.run_sync(lambda sync: seed_native_sentinel(sync.connection(), ids))
                foreign = await session.get(StatsMatch, ids["match_lol"])
                assert foreign is not None
                assert (foreign.workspace_id, foreign.discipline) == (ids["workspace"], "lol")
                overall_after = await _uncached(
                    tournaments.get_tournaments_overall,
                    session,
                    workspace_id=ids["workspace"],
                )
                assert overall_after.maps == overall_before.maps + 1
                public = await _uncached(
                    encounters.get_all_matches,
                    session,
                    schemas.MatchSearchParams(per_page=-1),
                    workspace_id=ids["workspace"],
                )
                # No game is special: the LoL observation lists with its own discipline and both participants.
                listed = next(row for row in public.results if row.id == foreign.id)
                assert (listed.discipline, listed.workspace_id) == ("lol", ids["workspace"])
                assert [(p.encounter_team_id, p.team_facts) for p in listed.participants] == [
                    (ids["encounter_team_lol_home"], {"score": 1.0}),
                    (ids["encounter_team_lol_away"], {"score": 2.0}),
                ]
                from src.services.admin.encounter import encounter_service as admin

                with pytest.raises(BaseAPIException) as caught:
                    await admin.update_match(session, ids["match"], schemas.MatchUpdate(map_id=ids["map_lol"]))
                assert caught.value.status_code == 409
                # Its own discipline governs the edit: a duration is editable, and so is a declared ``score``.
                await admin.update_match(
                    session,
                    foreign.id,
                    schemas.MatchUpdate(
                        duration_s=10,
                        team_facts=[
                            schemas.MatchTeamFactIn(
                                encounter_team_id=ids["encounter_team_lol_home"], stat_code="score", value=5
                            )
                        ],
                    ),
                )
                direct = await encounters.get_match(session, foreign.id, [], workspace_id=ids["workspace"])
                assert (direct.discipline, direct.duration_s) == ("lol", 10)
                assert [p.team_facts for p in direct.participants] == [{"score": 5.0}, {"score": 2.0}]
                with_stats = await _uncached(
                    encounters.get_match_with_stats, session, foreign.id, [], workspace_id=ids["workspace"]
                )
                assert {entity.id for entity in with_stats.statistics.entities} == {ids["hero_lol"]}
                assert {fact.stat_code for fact in with_stats.statistics.facts} == {
                    "hero_damage_dealt",
                    "hero_time_played",
                    "score",
                }
                feed = await _uncached(
                    encounters.get_match_kill_feed, session, foreign.id, workspace_id=ids["workspace"]
                )
                assert [(event.type, event.entity_id) for event in feed.events] == [("kill", ids["hero_lol"])]
                detail = await matches_service.get_admin_match(
                    session, workspace_id=ids["workspace"], match_id=foreign.id
                )
                assert (detail.discipline, detail.statistics_count, detail.event_count) == ("lol", 4, 0)
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_encounter_and_match_reads_carry_their_owner_context(stats_parity_database):
    async def exercise():
        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                detail = await encounters.get_encounter(session, ids["encounter"], ["tournament", "matches"])
                owner = (detail.tournament.workspace_id, detail.tournament.discipline)
                assert owner[0] == ids["workspace"]
                assert (detail.workspace_id, detail.discipline) == owner
                page = await encounters.get_all_matches(
                    session,
                    schemas.MatchSearchParams(tournament_id=ids["tournament"]),
                    workspace_id=ids["workspace"],
                )
                direct = await encounters.get_match(session, ids["match"], ["encounter"], workspace_id=ids["workspace"])
                with_stats = await _uncached(
                    encounters.get_match_with_stats, session, ids["match"], [], workspace_id=ids["workspace"]
                )
                assert direct.encounter is not None
                for read in (*detail.matches, *page.results, direct, with_stats, direct.encounter):
                    assert (read.workspace_id, read.discipline) == owner
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_native_slots_preserve_observed_scores_for_retired_participants(stats_parity_database):
    async def exercise():
        # Local import: capture loads this module with frozen P3 production packages.
        from shared import models
        from shared.models.stats.match import StatsMatchTeam

        url, ids = stats_parity_database
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                for retired in (False, True):
                    if retired:
                        await session.execute(
                            sa.update(models.EncounterTeam)
                            .where(
                                models.EncounterTeam.id.in_([ids["encounter_team_home"], ids["encounter_team_away"]]),
                            )
                            .values(active=False)
                        )
                        session.add_all(
                            [
                                models.EncounterTeam(
                                    encounter_id=ids["encounter"],
                                    tournament_id=ids["tournament"],
                                    slot=slot,
                                    team_id=ids[f"team_{side}"],
                                    name=f"Replacement {side}",
                                )
                                for slot, side in ((1, "home"), (2, "away"))
                            ]
                        )
                        await session.flush()
                        session.expire_all()
                    seats = (
                        await session.execute(
                            sa.select(
                                StatsMatchTeam.encounter_id,
                                StatsMatchTeam.encounter_team_id,
                                StatsMatchTeam.source_position,
                                models.EncounterTeam.slot,
                            )
                            .join(models.EncounterTeam, models.EncounterTeam.id == StatsMatchTeam.encounter_team_id)
                            .where(StatsMatchTeam.match_id == ids["match_reversed"])
                            .order_by(models.EncounterTeam.slot)
                        )
                    ).all()
                    assert seats == [
                        (ids["encounter"], ids["encounter_team_home"], 2, 1),
                        (ids["encounter"], ids["encounter_team_away"], 1, 2),
                    ]
                    page = await encounters.get_all_matches(
                        session,
                        schemas.MatchSearchParams(tournament_id=ids["tournament"], entities=["map"]),
                        workspace_id=ids["workspace"],
                    )
                    detail = await encounters.get_encounter(session, ids["encounter"], ["matches"])
                    assert all(seat.active for seat in detail.teams)
                    if retired:
                        assert {seat.id for seat in detail.teams}.isdisjoint(
                            {ids["encounter_team_home"], ids["encounter_team_away"]}
                        )
                    for name in ("match", "match_reversed", "match_no_raw"):
                        golden = expected["match_details"][name]
                        direct = await encounters.get_match(session, ids[name], ["map"], workspace_id=ids["workspace"])
                        with_stats = await _uncached(
                            encounters.get_match_with_stats,
                            session,
                            ids[name],
                            ["map"],
                            workspace_id=ids["workspace"],
                        )
                        listed = next(match for match in page.results if match.id == ids[name])
                        nested = next(match for match in detail.matches if match.id == ids[name])
                        for match in (direct, with_stats, listed, nested):
                            # The historical participations, live or retired, in slot order; the source team is
                            # a per-participant fact and the observed score a per-participant team fact.
                            assert [
                                (p.encounter_team_id, p.slot, p.tournament_team_id) for p in match.participants
                            ] == [
                                (ids["encounter_team_home"], 1, ids["team_home"]),
                                (ids["encounter_team_away"], 2, ids["team_away"]),
                            ]
                            assert {
                                str(p.encounter_team_id): p.team_facts["score"] for p in match.participants
                            } == golden["scores_by_participant"]
                            assert all(float(p.team_facts["score"]).is_integer() for p in match.participants)
                            assert (match.map_index, match.map_id) == (golden["map_index"], golden["map_id"])
                            assert {"source", "code", "score", "home_participation", "home_team"}.isdisjoint(
                                match.model_dump()
                            )
                        # Source positions are the log's order, never the seat: the reversed log lists away first.
                        assert [p.source_position for p in direct.participants] == (
                            [2, 1] if name == "match_reversed" else [1, 2]
                        )
                        official = next(
                            game
                            for game in expected["encounter_details"]["encounter"]["games"]
                            if game["position"] == golden["map_index"]
                        )
                        assert golden["scores_by_participant"] != {
                            str(team["encounter_team_id"]): team["score"] for team in official["teams"]
                        }
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "field", ["home_team_id", "away_team_id", "home_score", "away_score", "time", "code", "source", "log_name"]
)
def test_match_update_rpc_rejects_removed_fields(stats_parity_database, field):
    async def exercise():
        from types import SimpleNamespace
        from unittest.mock import patch

        from src.rpc import _helpers, admin_misc
        from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                broker = CapturingBroker()
                admin_misc.register(broker, SimpleNamespace(exception=lambda *args, **kwargs: None))
                identity = make_identity(user_id=ids["auth_user"], is_superuser=True)
                before = await encounters.get_match(session, ids["match"], [])
                with patch.object(_helpers.db, "async_session_maker", FakeSessionMaker(session)):
                    result = await broker.handlers["rpc.tournament.encounter_update_match"](
                        {"identity": identity, "id": ids["match"], "payload": {field: 1}},
                        None,
                    )
                assert result["ok"] is False
                assert result["error"]["code"] == "unprocessable"
                after = await encounters.get_match(session, ids["match"], [])
                assert after == before
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_native_admin_no_raw_rows_and_map_conflict(stats_parity_database):
    async def exercise():
        from shared.models import StatsFact, StatsMatch
        from src.services.admin.encounter import encounter_service as admin

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                detail = await matches_service.get_admin_match(
                    session,
                    workspace_id=ids["workspace"],
                    match_id=ids["match_no_raw"],
                )
                assert detail.duration_s is None and detail.log_name is None and detail.log_record is None
                assert (detail.rounds, detail.statistics_count, detail.kill_feed_count, detail.event_count) == (
                    0,
                    0,
                    0,
                    0,
                )
                page = await matches_service.list_admin_matches(
                    session,
                    workspace_id=ids["workspace"],
                    params=schemas.AdminMatchesSearchParams(unlinked_only=True),
                )
                assert ids["match_no_raw"] in {row.id for row in page.results}
                before = (
                    await session.execute(
                        sa.select(StatsFact.__table__).where(
                            StatsFact.match_id == ids["match"],
                        )
                    )
                ).all()
                with pytest.raises(BaseAPIException) as caught:
                    await admin.update_match(session, ids["match"], schemas.MatchUpdate(map_id=ids["map_other"]))
                assert caught.value.status_code == 409
                assert (await session.get(StatsMatch, ids["match"])).map_entity_id == ids["map"]
                assert (
                    await session.execute(
                        sa.select(StatsFact.__table__).where(
                            StatsFact.match_id == ids["match"],
                        )
                    )
                ).all() == before
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_native_admin_edits_keep_narrow_evidence_and_official_results(stats_parity_database):
    async def exercise():
        from shared.models import AuditLog, EncounterGameTeam, StatsMatch
        from src.services.admin.encounter import encounter_service as admin

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                official = (
                    await session.execute(
                        sa.select(EncounterGameTeam.__table__)
                        .where(
                            EncounterGameTeam.game_id == ids["game_reversed"],
                        )
                        .order_by(EncounterGameTeam.encounter_team_id)
                    )
                ).all()
                await admin.update_match(
                    session,
                    ids["match_reversed"],
                    schemas.MatchUpdate(
                        duration_s=123.5,
                        team_facts=[
                            schemas.MatchTeamFactIn(
                                encounter_team_id=ids["encounter_team_home"], stat_code="score", value=9
                            ),
                            schemas.MatchTeamFactIn(
                                encounter_team_id=ids["encounter_team_away"], stat_code="score", value=8
                            ),
                        ],
                    ),
                )
                actual = await encounters.get_match(session, ids["match_reversed"], [])
                assert {p.encounter_team_id: p.team_facts["score"] for p in actual.participants} == {
                    ids["encounter_team_home"]: 9,
                    ids["encounter_team_away"]: 8,
                }
                assert actual.duration_s == 123.5
                assert (await session.get(StatsMatch, ids["match_reversed"])).revision == 1
                assert (
                    await session.execute(
                        sa.select(EncounterGameTeam.__table__)
                        .where(
                            EncounterGameTeam.game_id == ids["game_reversed"],
                        )
                        .order_by(EncounterGameTeam.encounter_team_id)
                    )
                ).all() == official
                audits = (
                    await session.scalars(
                        sa.select(AuditLog)
                        .where(
                            AuditLog.action.in_(["stats.score_edit", "stats.match_edit"]),
                            AuditLog.entity_id == ids["match_reversed"],
                        )
                        .order_by(AuditLog.id)
                    )
                ).all()
                assert [audit.action for audit in audits] == ["stats.score_edit", "stats.match_edit"]
                for audit in audits:
                    before = {state["subset"]: state for state in audit.before_json["stats_evidence"]["states"]}
                    after = {state["subset"]: state for state in audit.after_json["stats_evidence"]["states"]}
                    changed = {key for key in before if before[key] != after[key]}
                    assert changed == (
                        {"team_scores"} if audit.action == "stats.score_edit" else {"duration", "updated_at"}
                    )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_tournament_registry_delete_stages_native_owner_evidence(stats_parity_database):
    async def exercise():
        import hashlib
        from unittest.mock import patch

        from shared.models import AuditLog, IngestJob, StatsMatch
        from src.services.admin.registry import dispatcher
        from tests._rpc_fakes import FakeSessionMaker, make_identity

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add_all(
                    [
                        IngestJob(
                            workspace_id=ids["workspace"],
                            discipline="overwatch",
                            source_kind="upload",
                            content_hash=hashlib.sha256(f"native-delete-job-{i}".encode()).hexdigest(),
                            raw_ref=f"logs/{ids['tournament']}/native-delete-{i}.csv",
                            filename=f"native-delete-{i}.csv",
                            status="pending",
                            hint_tournament_id=ids["tournament"],
                        )
                        for i in range(101)
                    ]
                )
                await session.commit()
                with patch.object(dispatcher, "_session_factory", FakeSessionMaker(session)):
                    result = await dispatcher.do_delete(
                        {
                            "entity": "tournament",
                            "id": ids["tournament"],
                            "identity": make_identity(user_id=ids["auth_user"], is_superuser=True),
                        }
                    )
                assert result["ok"] is True, result
                assert await session.scalar(sa.select(StatsMatch.id).where(StatsMatch.id == ids["match"])) is None
                job = await session.get(IngestJob, ids["record"])
                assert job is not None
                assert job.hint_tournament_id is None and job.hint_encounter_id is None
                audits = (
                    await session.scalars(
                        sa.select(AuditLog).where(
                            AuditLog.action == "stats.owner_delete",
                            AuditLog.entity_type == "tournament",
                            AuditLog.entity_id == ids["tournament"],
                        )
                    )
                ).all()
                assert len(audits) >= 2
                for audit in audits:
                    owners = {
                        (state["owner_kind"], tuple(state["owner_key"]))
                        for state in audit.before_json["stats_evidence"]["states"]
                    }
                    assert len(owners) <= 100
                states = [state for audit in audits for state in audit.after_json["stats_evidence"]["states"]]
                assert any(
                    state["owner_kind"] == "match"
                    and state["owner_key"] == [ids["match"]]
                    and not state["owner_exists"]
                    for state in states
                )
                assert any(
                    state["owner_kind"] == "job" and state["owner_key"] == [ids["record"]] and state["owner_exists"]
                    for state in states
                )
                assert await session.get(StatsMatch, ids["match_other"]) is not None
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_native_owner_delete_and_evidence_roll_back_together(stats_parity_database):
    async def exercise():
        from shared.models import AuditLog, IngestJob, StatsMatch, Tournament
        from shared.services.stats_owner_delete import capture_owner_delete, stage_owner_delete

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                with pytest.raises(RuntimeError, match="abort owner deletion"):
                    async with session.begin():
                        before = await capture_owner_delete(session, tournament_id=ids["tournament"])
                        await session.execute(sa.delete(Tournament).where(Tournament.id == ids["tournament"]))
                        audits = await stage_owner_delete(
                            session,
                            before,
                            workspace_id=ids["workspace"],
                            entity_type="tournament",
                            entity_id=ids["tournament"],
                        )
                        assert audits
                        raise RuntimeError("abort owner deletion")
                assert (
                    await session.scalar(sa.select(StatsMatch.id).where(StatsMatch.id == ids["match"])) == ids["match"]
                )
                assert (
                    await session.scalar(
                        sa.select(IngestJob.hint_tournament_id).where(
                            IngestJob.id == ids["record"],
                        )
                    )
                    == ids["tournament"]
                )
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(AuditLog)
                        .where(
                            AuditLog.action == "stats.owner_delete",
                            AuditLog.entity_id == ids["tournament"],
                        )
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_native_nullable_events_and_historical_source_teams_are_not_dropped(stats_parity_database):
    async def exercise():
        from shared.models import EncounterTeam, StatsEvent, StatsMatchPlayer, Team

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                before = await _uncached(
                    encounters.get_match_kill_feed,
                    session,
                    ids["match"],
                    workspace_id=ids["workspace"],
                )
                assert {"kill", "ultimate_start", "ultimate_end", "mercy_rez"} <= {
                    event.type for event in before.events
                }
                assert before.entities
                await session.execute(
                    sa.update(StatsEvent)
                    .where(StatsEvent.match_id == ids["match"])
                    .values(
                        actor_member_id=None,
                        target_member_id=None,
                        actor_team_id=None,
                        target_team_id=None,
                        entity_id=None,
                        related_entity_id=None,
                        data=None,
                    )
                )
                after = await _uncached(
                    encounters.get_match_kill_feed,
                    session,
                    ids["match"],
                    workspace_id=ids["workspace"],
                )
                assert [(e.id, e.segment, e.t, e.type) for e in after.events] == [
                    (e.id, e.segment, e.t, e.type) for e in before.events
                ]
                for event in after.events:
                    assert all(
                        value is None
                        for key, value in event.model_dump().items()
                        if key not in {"id", "segment", "t", "type"}
                    )
                assert after.entities == []
                await session.execute(
                    sa.update(StatsMatchPlayer)
                    .where(
                        StatsMatchPlayer.match_id == ids["match"],
                        StatsMatchPlayer.workspace_member_id == ids["member"],
                    )
                    .values(handle_snapshot="HistoricalHandle#1234")
                )
                await session.execute(
                    sa.update(EncounterTeam).where(EncounterTeam.encounter_id == ids["encounter"]).values(active=False)
                )
                await session.execute(sa.delete(Team).where(Team.id.in_([ids["team_home"], ids["team_away"]])))
                session.expire_all()
                detail = await _uncached(
                    encounters.get_match_with_stats,
                    session,
                    ids["match"],
                    [],
                    workspace_id=ids["workspace"],
                )
                # The retired seats keep their snapshot and their observed score; the deleted source teams are null.
                assert [(p.encounter_team_id, p.tournament_team_id) for p in detail.participants] == [
                    (ids["encounter_team_home"], None),
                    (ids["encounter_team_away"], None),
                ]
                assert [p.team_facts["score"] for p in detail.participants] == [2, 1]
                assert all(segment.segment >= 1 for segment in detail.statistics.segments)
                golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["batch_user_stats"]["match"]
                observed = _observed_players(detail.statistics.model_dump(mode="python"))
                assert set(observed) == {ids["encounter_team_home"], ids["encounter_team_away"]}
                for players in observed.values():
                    for player in players:
                        if player["user_id"] is None:
                            continue
                        expected = golden[str(player["user_id"])]
                        assert _normalize(player["stats"]) == expected["statistics"]
                        assert _normalize({"heroes": player["heroes"]})["heroes"] == expected["heroes"]
                members = {m.workspace_member_id: m for m in detail.statistics.members}
                assert members[ids["member"]].handle_snapshot == "HistoricalHandle#1234"
                assert {"id", "rank", "role", "team_id"}.isdisjoint(members[ids["member"]].model_dump())
                home = next(
                    p for p in observed[ids["encounter_team_home"]] if p["workspace_member_id"] == ids["member"]
                )
                away = next(
                    p for p in observed[ids["encounter_team_away"]] if p["workspace_member_id"] == ids["member_away"]
                )
                assert home["stats"][0]["hero_damage_dealt"] == 18000
                assert away["stats"][0]["hero_damage_dealt"] == 36000
                # An event-only member is a member without a single fact, never dropped and never given zeros.
                assert ids["member_event_only"] in members
                assert [f for f in detail.statistics.facts if f.workspace_member_id == ids["member_event_only"]] == []
                event_only = next(
                    p
                    for players in observed.values()
                    for p in players
                    if p["workspace_member_id"] == ids["member_event_only"]
                )
                assert event_only["stats"] == {} and event_only["heroes"] == {}
                current = await encounters.get_encounter(session, ids["encounter"], ["teams"])
                assert current.teams == []
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_parsed_non_roster_member_keeps_snapshot_and_side_scoped_numbers(stats_parity_database):
    async def exercise():
        from shared.models import EncounterTeamMember, Player, StatDef, StatsFact, StatsMatchPlayer, WorkspaceMember

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await session.execute(
                    sa.delete(EncounterTeamMember).where(
                        EncounterTeamMember.encounter_id == ids["encounter"],
                        EncounterTeamMember.workspace_member_id == ids["member"],
                    )
                )
                await session.execute(
                    sa.delete(Player).where(
                        Player.tournament_id == ids["tournament"],
                        Player.workspace_member_id == ids["member"],
                    )
                )
                await session.execute(
                    sa.update(StatsMatchPlayer)
                    .where(
                        StatsMatchPlayer.match_id == ids["match"],
                        StatsMatchPlayer.workspace_member_id == ids["member"],
                    )
                    .values(handle_snapshot="ParsedNonRoster#1234")
                )
                detail = await _uncached(
                    encounters.get_match_with_stats,
                    session,
                    ids["match"],
                    [],
                    workspace_id=ids["workspace"],
                )
                member = next(m for m in detail.statistics.members if m.workspace_member_id == ids["member"])
                assert member.handle_snapshot == "ParsedNonRoster#1234"
                assert member.player_id == ids["player"]
                assert member.encounter_team_id == ids["encounter_team_home"]
                observed = _observed_players(detail.statistics.model_dump(mode="python"))
                player = next(
                    p for p in observed[ids["encounter_team_home"]] if p["workspace_member_id"] == ids["member"]
                )
                assert player["stats"][0]["hero_damage_dealt"] == 18000
                assert player["stats"][1]["hero_damage_dealt"] == 9000
                assert {hero["id"] for hero in player["heroes"][0]} == {ids["hero"], ids["hero_other"]}
                # The roster is a separate fact: the source team no longer lists the parsed member.
                source_team = await _source_team(session, ids["team_home"], ["players"])
                assert all(p["user_id"] != ids["player"] for p in source_team["players"])
                assert {"id", "rank", "role", "team_id"}.isdisjoint(member.model_dump())

                # Changing linked global identities must not move native numbers
                # between the observed sides or replace their handle snapshots.
                await session.execute(
                    sa.update(WorkspaceMember)
                    .where(WorkspaceMember.id == ids["member"])
                    .values(player_id=ids["player_no_member"])
                )
                await session.execute(
                    sa.update(WorkspaceMember)
                    .where(WorkspaceMember.id == ids["member_away"])
                    .values(player_id=ids["player"])
                )
                await session.execute(
                    sa.update(WorkspaceMember)
                    .where(WorkspaceMember.id == ids["member"])
                    .values(player_id=ids["player_away"])
                )
                await session.execute(
                    sa.update(StatsFact)
                    .where(
                        StatsFact.match_id == ids["match"],
                        StatsFact.workspace_member_id == ids["member"],
                        StatsFact.entity_id.is_not(None),
                        StatsFact.stat_id.in_(
                            sa.select(StatDef.id).where(
                                StatDef.discipline == "overwatch", StatDef.code == "hero_time_played"
                            )
                        ),
                    )
                    .values(value=30)
                )
                session.expire_all()
                changed = await _uncached(
                    encounters.get_match_with_stats,
                    session,
                    ids["match"],
                    [],
                    workspace_id=ids["workspace"],
                )
                members = {m.workspace_member_id: m for m in changed.statistics.members}
                assert members[ids["member"]].player_id == ids["player_away"]
                assert members[ids["member_away"]].player_id == ids["player"]
                assert members[ids["member"]].handle_snapshot == "ParsedNonRoster#1234"
                observed = _observed_players(changed.statistics.model_dump(mode="python"))
                home = next(
                    p for p in observed[ids["encounter_team_home"]] if p["workspace_member_id"] == ids["member"]
                )
                away = next(
                    p for p in observed[ids["encounter_team_away"]] if p["workspace_member_id"] == ids["member_away"]
                )
                assert home["stats"] == player["stats"] and home["heroes"] == {}
                assert away["stats"][0]["hero_damage_dealt"] == 36000
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_unbound_history_preserves_complete_reader_outputs_and_visibility(stats_parity_database):
    async def exercise():
        from shared.models import IngestJob, RawSourceStatus, StatsMatch, Workspace

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                before = await collect_outputs(session, ids)
                assert_tournament_golden(before)
                unbound_ids = {ids[name] for name in _MATCH_KEYS}
                await session.execute(
                    sa.update(StatsMatch)
                    .where(StatsMatch.id.in_([ids[name] for name in _MATCH_KEYS]))
                    .values(encounter_game_id=None, source_map_index=99, updated_at=StatsMatch.updated_at)
                )
                session.expire_all()
                after = await collect_outputs(session, ids)

                def without_proven_order(value):
                    if isinstance(value, list):
                        return [without_proven_order(item) for item in value]
                    if not isinstance(value, dict):
                        return value
                    result = {key: without_proven_order(item) for key, item in value.items()}
                    if result.get("id") in unbound_ids and "map_index" in result:
                        result["map_index"] = None
                    if isinstance(result.get("matches"), list):
                        result["matches"].sort(
                            key=lambda match: (match["map_index"] is None, match["map_index"] or 0, match["id"])
                        )
                    return result

                expected = without_proven_order(before)
                # Explicit map-index sorting has a stable ID tie-break only for
                # presentation; none of these IDs is exposed as official order.
                expected["match_pages"]["tournament"]["results"].sort(
                    key=lambda match: (match["map_index"] is None, match["map_index"] or 0, match["id"])
                )
                assert after == expected
                assert all(
                    row["map_index"] is None
                    for row in after["match_pages"]["platform"]["results"]
                    if row["id"] in unbound_ids
                )
                await session.execute(
                    sa.update(StatsMatch)
                    .where(StatsMatch.id == ids["match_no_raw"])
                    .values(encounter_game_id=ids["game_no_raw"])
                )
                bound_history = [
                    (row["id"], row["map_index"])
                    for row in before["match_pages"]["tournament"]["results"]
                    if row["id"] not in unbound_ids
                ]
                for order in ("asc", "desc"):
                    page = await encounters.get_all_matches(
                        session,
                        schemas.MatchSearchParams(tournament_id=ids["tournament"], sort="map_index", order=order),
                        workspace_id=ids["workspace"],
                    )
                    bound = sorted(
                        [(ids["match_no_raw"], 3), *bound_history], key=lambda row: row[1], reverse=order == "desc"
                    )
                    assert [(row.id, row.map_index) for row in page.results] == bound + [
                        (ids["match"], None),
                        (ids["match_reversed"], None),
                    ]
                await session.execute(
                    sa.update(IngestJob).where(IngestJob.id == ids["record"]).values(raw_status=RawSourceStatus.MISSING)
                )
                detail = await encounters.get_match(session, ids["match"], [], workspace_id=ids["workspace"])
                assert detail.raw_status == RawSourceStatus.MISSING
                assert detail.raw_available is False
                assert detail.log_name == before["match_details"]["match"]["log_name"]

                # An unbound source remains linked to its job; unlinked_only
                # continues to mean no ingestion record, not no official game.
                unlinked = await matches_service.list_admin_matches(
                    session,
                    workspace_id=ids["workspace"],
                    params=schemas.AdminMatchesSearchParams(unlinked_only=True),
                )
                # The seed's matches without a log record: their job-less native rows.
                expected_recordless = {
                    ids["match_no_raw"],
                    *(ids[f"match_otp_{i}"] for i in range(1, 5)),
                    *(ids[f"match_career_{i}"] for i in range(1, 4)),
                }
                assert {row.id for row in unlinked.results} == expected_recordless
                await session.execute(
                    sa.update(Workspace).where(Workspace.id == ids["workspace"]).values(is_hidden=True)
                )
                owner = await visibility.tournament_id_for_match(session, ids["match"])
                assert owner == ids["tournament"]
                await _not_found(ensure_tournament_viewable(session, None, owner))
                page = await encounters.get_all_matches(session, schemas.MatchSearchParams(per_page=-1))
                assert ids["match"] not in {row.id for row in page.results}
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_unbound_match_update_rpc_audits_direct_owner_without_changing_official_results(stats_parity_database):
    async def exercise():
        from types import SimpleNamespace
        from unittest.mock import patch

        from shared.models import AuditLog, EncounterGameTeam, StatsMatch
        from src.rpc import _helpers, admin_misc
        from src.services.admin.encounter import encounter_service as admin
        from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

        url, ids = stats_parity_database
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await session.execute(
                    sa.update(StatsMatch).where(StatsMatch.id == ids["match"]).values(encounter_game_id=None)
                )
                official_query = (
                    sa.select(EncounterGameTeam.__table__)
                    .where(EncounterGameTeam.game_id == ids["game"])
                    .order_by(EncounterGameTeam.encounter_team_id)
                )
                official = (await session.execute(official_query)).all()
                with pytest.raises(BaseAPIException) as caught:
                    await admin.update_match(session, ids["match"], schemas.MatchUpdate(map_id=ids["map_other"]))
                assert caught.value.status_code == 409

                broker = CapturingBroker()
                admin_misc.register(broker, SimpleNamespace(exception=lambda *args, **kwargs: None))
                identity = make_identity(user_id=ids["auth_user"], is_superuser=True)
                with patch.object(_helpers.db, "async_session_maker", FakeSessionMaker(session)):
                    result = await broker.handlers["rpc.tournament.encounter_update_match"](
                        {
                            "identity": identity,
                            "id": ids["match"],
                            "payload": {
                                "map_id": ids["map"],
                                "duration_s": 123.5,
                                "team_facts": [
                                    {"encounter_team_id": ids["encounter_team_home"], "stat_code": "score", "value": 9},
                                    {"encounter_team_id": ids["encounter_team_away"], "stat_code": "score", "value": 8},
                                ],
                            },
                        },
                        None,
                    )
                assert result["ok"] is True, result
                assert result["data"]["encounter_id"] == ids["encounter"]
                assert result["data"]["duration_s"] == 123.5
                assert {p["encounter_team_id"]: p["team_facts"]["score"] for p in result["data"]["participants"]} == {
                    ids["encounter_team_home"]: 9,
                    ids["encounter_team_away"]: 8,
                }
                audit = (
                    await session.scalars(sa.select(AuditLog).where(AuditLog.action == "encounter.update_match"))
                ).one()
                assert (audit.entity_type, audit.entity_id, audit.workspace_id) == (
                    "encounter",
                    ids["encounter"],
                    ids["workspace"],
                )
                assert (await session.execute(official_query)).all() == official
                detail = await encounters.get_match(session, ids["match"], [])
                assert (detail.encounter_id, detail.map_index) == (ids["encounter"], None)
        finally:
            await engine.dispose()

    asyncio.run(exercise())
