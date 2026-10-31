"""Real P3/native app-reader parity; only the controller writes the old golden.

``collect_outputs`` is also loaded with production imports pointing at frozen
P3. Keep native-only imports inside the adversarial tests below.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from inspect import unwrap
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared import models
from shared.core import enums, pagination
from shared.core.errors import ApiHTTPException
from shared.division_grid import DEFAULT_GRID
from shared.schemas.role import RoleRef
from shared.testing import configure_test_cache
from src import schemas
from src.services.achievement_reads.service import achievements
from src.services.hero.queries import HeroQueries
from src.services.hero.service import heroes
from src.services.map.service import maps
from src.services.statistics.queries import StatisticsQueries
from src.services.statistics.service import statistics
from src.services.user.service import UserService, _tournament_grid_versions, tournament_stats

#: Every reader of the frozen capture was the OW-bound one; the native readers take the game explicitly.
OW = "overwatch"
users = UserService.of(OW)
statistics_queries = StatisticsQueries.of(OW)
hero_queries = HeroQueries.of(OW)

GOLDEN = Path(__file__).parent / "fixtures" / "stats_reader_parity.json"
#: The stats the frozen capture requested and the proof still compares: the readers' ``count / len(stats)`` ranked
#: population divides by the request, so the MVP stats (``shared.testing.stats_parity.MVP_STATS``, spelled out because
#: the frozen capture imports this module) are not requested.
ALL_STATS = [
    stat
    for stat in enums.LogStatsName
    if stat.value not in {"impact_points", "impact_rank", "overperformance_score", "overperformance_badge"}
    and not stat.value.startswith("contrib_")
]
DAMAGE = RoleRef(dimension="player_role", role="damage")
#: Every expansion of a user encounter read: the frozen capture shipped them all.
ALL_ENCOUNTERS = ["tournament", "stage", "stage_item", "teams", "teams.players", "matches"]


def _json(value: Any) -> Any:
    """Keep complete DTOs/rows, normalizing representation, not calculations."""
    if isinstance(value, BaseModel):
        return _json(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return _json(value.value)
    if isinstance(value, datetime):
        # Legacy timestamp-without-time-zone columns contain UTC fixture dates.
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, sa.Row):
        return _json(tuple(value))
    if isinstance(value, Mapping):
        result = {str(_json(key)): _json(item) for key, item in value.items()}
        if {"participants", "encounter_id", "map_id", "duration_s"} <= result.keys():
            return _frozen_match(result)
        if {"workspace_id", "discipline"} <= result.keys() and (
            {"is_league", "team_id", "players"} <= result.keys() or {"playtime", "stats"} <= result.keys()
        ):
            # The owner context P7 added to a user's tournament row and tournament stats; it is not reader output the
            # frozen capture had.
            del result["workspace_id"], result["discipline"]
        if {"slot_count", "user_team_id", "discipline"} <= result.keys():
            # The game a user's encounter row gained for the cross-game tabs (spec §6.6); not reader output the frozen
            # capture had.
            del result["discipline"]
        if {"disciplines", "roles", "top_characters"} <= result.keys():
            # The games a users-index row/card gained for the cross-game index (spec §8.2); not reader output the frozen
            # capture had.
            del result["disciplines"]
        if result.keys() == {"id", "name", "discipline", "is_league", "is_finished", "status"}:
            # The game a profile's tournament card gained for the cross-game profile (spec §6.6); not reader output the
            # frozen capture had.
            del result["discipline"]
        if {"games", "roles", "character_statistics", "tournaments"} <= result.keys():
            # The per-game summaries a profile gained for the cross-game profile (spec §6.6); not reader output the
            # frozen capture had.
            del result["games"]
        return result
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unnormalized app parity value: {type(value).__name__}")


#: Source teams as the frozen achievement link carried them; loaded by ``collect_outputs`` from the real rows.
_TEAMS: dict[int, dict[str, Any]] = {}


def _whole(value: float | None) -> int | float | None:
    """The frozen oracle spelled whole scores as integers."""
    return int(value) if value is not None and float(value).is_integer() else value


def _frozen_hero(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "aliases": entity["aliases"],
        "color": entity["attrs"].get("color") or "#ffffff",
        "id": entity["id"],
        "image_path": entity["image_path"] or "",
        "name": entity["name"],
        "slug": entity["slug"],
        "type": entity["attrs"].get("class"),
    }


def _read_hero(entity: dict[str, Any]) -> dict[str, Any]:
    """A native character in the frozen app ``HeroRead`` representation (``type`` spelled as the ``HeroClass`` value)."""
    return {**_frozen_hero(entity), "type": enums.HeroClass[entity["attrs"]["class"]].value}


#: §4.1 renames, mapped back to the frozen field names (projection only).
_LEGACY_KEYS = {
    "characters": "heroes",
    "character": "hero",
    "top_characters": "top_heroes",
    "most_played_character": "most_played_hero",
    "characters_count": "heroes_count",
    "character_statistics": "hero_statistics",
    "character_stats": "hero_stats",
    "subject_character": "subject_hero",
    "target_character": "target_hero",
}


def _legacy_catalog(value: Any, *, roster: bool = False) -> Any:
    """Native catalog entities and the renamed character fields in the frozen OW representation.

    Characters become the app ``HeroRead`` (roster players' top heroes were JSON-built: ``type`` is the class label),
    maps the frozen ``MapRead``; a playtime row's ``entity`` is its ``hero``; a draft-card row regains its class slot
    code. Values are untouched.
    """
    if isinstance(value, list):
        return [_legacy_catalog(item, roster=roster) for item in value]
    if not isinstance(value, dict):
        return value
    if {"kind", "discipline", "attrs", "aliases", "active"} <= value.keys():
        if value["kind"] == "map":
            return _frozen_map(value)
        return _frozen_hero(value) if roster else _read_hero(value)
    if value.keys() == {"entity", "playtime"}:
        value = {"hero": value["entity"], "playtime": value["playtime"]}
    # Achievement payloads went native in P6; ``_accept_p6_achievement_wire`` projects those, not this walker.
    result = {
        _LEGACY_KEYS.get(key, key): item
        if key == "achievements"
        else _legacy_catalog(item, roster=roster or key == "players")
        for key, item in value.items()
    }
    if "role_counts" in value:
        # Users index chip counts are per rated role code now; the frozen read named Overwatch's three.
        counts = result.pop("role_counts")
        result.update({f"{code}_count": counts.get(code, 0) for code in ("tank", "damage", "support")})
    if "character" in value and {"maps", "maps_won"} <= value.keys():
        result["role"] = enums.HeroClass[value["character"]["attrs"]["class"]].slot_code
    return result


def _frozen_map(entity: dict[str, Any] | None) -> dict[str, Any] | None:
    """A native map entity in the frozen ``MapRead`` representation (its mode is ``gamemode``)."""
    if entity is None:
        return None
    parent = entity["parent"]
    return {
        "aliases": entity["aliases"],
        "id": entity["id"],
        "name": entity["name"],
        "image_path": entity["image_path"] or "",
        "gamemode_id": entity["parent_id"],
        "in_competitive": entity["attrs"].get("in_competitive", True),
        "gamemode": None
        if parent is None
        else {
            "aliases": parent["aliases"],
            "description": parent["attrs"].get("description"),
            "id": parent["id"],
            "image_path": parent["image_path"] or "",
            "name": parent["name"],
            "slug": parent["slug"],
        },
    }


def _frozen_match(match: dict[str, Any]) -> dict[str, Any]:
    """A native match row in the frozen per-participant representation (projection only, never a recomputation).

    The frozen user row carried the viewer's impact/overperformance values, a badge and their heroes. The MVP values
    are not projected (``without_mvp`` drops them from both sides of the proof); the heroes are the viewer's.
    """
    participants = sorted(
        (
            {
                "team_id": participant["tournament_team_id"],
                "score": _whole(participant["team_facts"].get("score")),
                "encounter_team_id": participant["encounter_team_id"],
                **(
                    {"team": _TEAMS[participant["tournament_team_id"]]}
                    if "viewer" not in match and participant["tournament_team_id"] is not None
                    else {}
                ),
            }
            for participant in match["participants"]
        ),
        key=lambda participant: participant["encounter_team_id"],
    )
    row = {
        "id": match["id"],
        "encounter_id": match["encounter_id"],
        "map_id": match["map_id"],
        "log_name": match["log_name"],
        "time": match["duration_s"],
        "participants": participants,
    }
    if "member_totals" not in match:
        return row
    viewer = match["viewer"]
    row.update(
        map_index=match["map_index"],
        map=_frozen_map(match["map"]),
        heroes=[] if viewer is None else [_frozen_hero(entity) for entity in viewer["characters"]],
    )
    return row


def _hero_stat_rows(rows: Any) -> list[Any]:
    # The query groups by (hero, stat) without an ORDER BY.
    return [
        _json((name, _read_hero(_json(heroes.to_read(hero))), *values))
        for name, hero, *values in sorted(rows, key=lambda row: (row[1].id, row[0].value))
    ]


def _hero_page(page: Any) -> dict[str, Any]:
    result = _json(page)
    # These are unordered SQL aggregate groups, not a leaderboard.
    result["results"].sort(key=lambda row: row["character"]["id"])
    for row in result["results"]:
        row["stats"].sort(key=lambda stat: stat["name"])
        # The hover card's record/win-rate fields a row gained; not reader output the frozen capture had.
        for key in ("games", "win", "loss", "draw", "win_rate_all", "record"):
            row.pop(key, None)
    return result


def _leaderboard_page(page: Any) -> dict[str, Any]:
    result = _json(page)
    # SQL orders by rank only; retain ranks, stabilize equal-rank peers.
    result["results"].sort(key=lambda row: (row["rank"], row["user_id"]))
    # The grid each row's division lives on, and those grids; not reader output the frozen capture had.
    del result["division_grids"]
    for row in result["results"]:
        del row["division_grid_version_id"]
    return result


async def _uncached(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Invoke the real decorated service body, never a replacement reader."""
    return await unwrap(method.__func__)(method.__self__, *args, **kwargs)


@asynccontextmanager
async def _database_session(url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


async def _frozen_history(session: AsyncSession, listing: schemas.UserTournamentList) -> list[dict[str, Any]]:
    """The tournament list in the frozen per-row shape (projection only).

    Each row regains the grid version its ``division_grid_version_id`` names and its always-empty ``encounters``; a
    roster player's character references become the entities they name, proven equal on every field they carry.
    """
    versions = {version.id: _json(version) for version in listing.division_grid_versions}
    refs = [ref for row in listing.results for player in row.players for ref in player.characters]
    entities = {
        entity.id: schemas.CatalogEntityRead.from_entity(entity, with_parent=False)
        for entity in await session.scalars(
            sa.select(models.CatalogEntity).where(models.CatalogEntity.id.in_({ref.id for ref in refs}))
        )
    }
    for ref in refs:
        assert ref.model_dump() == entities[ref.id].model_dump(include=set(ref.model_dump()))
    history = []
    for row in listing.results:
        frozen = _json(row)
        frozen["division_grid_version"] = versions.get(frozen.pop("division_grid_version_id"))
        frozen["encounters"] = []
        for player, native in zip(frozen["players"], row.players, strict=True):
            player["characters"] = [_json(entities[ref.id]) for ref in native.characters]
        frozen["players"].sort(key=lambda player: player["id"])
        history.append(frozen)
    return history


async def _frozen_profile(session: AsyncSession, profile: schemas.UserProfile) -> dict[str, Any]:
    """The profile with each tournament card's effective grid version, which the frozen capture shipped on it."""
    frozen = _json(profile)
    version_by_tournament, reads = await _tournament_grid_versions(session, [card.id for card in profile.tournaments])
    for card in frozen["tournaments"]:
        card["division_grid_version"] = _json(reads.get(version_by_tournament.get(card["id"])))
    return frozen


async def _user_outputs(session: AsyncSession, user_id: int, workspace_id: int | None) -> dict[str, Any]:
    hero_rows = await users.profile.get_statistics_by_heroes(session, user_id, workspace_id=workspace_id)
    history = await _frozen_history(
        session, await users.get_tournaments(session, user_id, workspace_id=workspace_id, grid=DEFAULT_GRID)
    )
    return {
        "profile": await _frozen_profile(
            session, await users.get_profile(session, user_id, workspace_id=workspace_id, grid=DEFAULT_GRID)
        ),
        "draft_card": _json(await users.get_draft_card(session, user_id, workspace_id=workspace_id)),
        "hero_statistics": _hero_stat_rows(hero_rows),
        "heroes": _hero_page(
            await users.get_heroes(
                session, user_id, pagination.PaginationParams(per_page=100), workspace_id=workspace_id
            )
        ),
        "tournaments": history,
        "teammates": _json(
            await users.get_best_teammates(
                session, user_id, pagination.PaginationSortParams(per_page=100, sort="id"), workspace_id=workspace_id
            )
        ),
        "encounters": _json(
            await users.get_encounters_by_user(
                session,
                user_id,
                pagination.PaginationSortParams(per_page=100, sort="played_at", order="desc", entities=ALL_ENCOUNTERS),
                workspace_id=workspace_id,
            )
        ),
        "matches_summary": _json(await users.get_matches_summary(session, user_id, workspace_id=workspace_id)),
    }


async def _achievement_outputs(session: AsyncSession, ids: dict[str, int], workspace_id: int | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "catalog": _json(
            await achievements.get_all(
                session,
                pagination.PaginationSortParams(per_page=100, sort="id", entities=["entity", "count"]),
                workspace_id=workspace_id,
            )
        ),
    }
    for player in ("player", "player_away", "player_event_only", "player_removed"):
        result[player] = _json(
            await achievements.get_user_achievements(
                session,
                ids[player],
                ["tournaments", "matches"],
                workspace_id=workspace_id,
                include_locked=True,
            )
        )
    result["without_tournament"] = _json(
        await achievements.get_user_achievements(
            session,
            ids["player"],
            ["tournaments", "matches"],
            workspace_id=workspace_id,
            without_tournament=True,
        )
    )
    if workspace_id != ids["workspace_other"]:
        result["detail"] = _json(
            await achievements.get(
                session,
                ids["rule"],
                ["entity", "count"],
                workspace_id=workspace_id,
                merge_slugs=workspace_id is None,
            )
        )
        earners = _json(
            await achievements.get_achievement_users(
                session,
                ids["rule"],
                pagination.PaginationParams(per_page=100),
                merge_slugs=workspace_id is None,
            )
        )
        earners["results"].sort(key=lambda row: (-row["count"], row["user"]["id"]))
        result["earners"] = earners
    return result


async def collect_outputs(session: AsyncSession, ids: dict[str, int]) -> dict[str, Any]:
    """Collect real app reads against either the frozen P3 or upgraded clone.

    The supplied clone must already contain the committed shared seed. Overview
    enrichment opens independent sessions; bind its REAL factory to this same
    clone and restore it even if a reader fails. No SQL/readers are mocked.
    """
    if session.bind is None:
        raise ValueError("App parity requires an AsyncSession bound to its isolated database")
    configure_test_cache()
    _TEAMS.clear()
    _TEAMS.update(
        {
            team_id: {"id": team_id, "image_url": image_url, "name": name}
            for team_id, name, image_url in (
                await session.execute(sa.select(models.Team.id, models.Team.name, models.Team.image_url))
            ).all()
        }
    )
    output: dict[str, Any] = {}
    for scope, workspace_id in (
        ("all", None),
        ("workspace", ids["workspace"]),
        ("workspace_other", ids["workspace_other"]),
    ):
        scoped: dict[str, Any] = {}
        output[scope] = scoped
        scoped["user"] = await _user_outputs(session, ids["player"], workspace_id)
        overview: dict[str, Any] = {}
        for label, filters in (
            ("all", {}),
            ("has_logs", {"has_logs": True}),
            ("damage", {"role": DAMAGE}),
            ("winrate", {"has_logs": True, "sort": "winrate", "min_encounters": 0}),
            ("winrate_threshold", {"has_logs": True, "sort": "winrate", "min_encounters": 2}),
        ):
            overview[label] = _json(
                await users.get_overview(
                    session,
                    schemas.UserOverviewParams(per_page=100, **({"sort": "id"} | filters)),
                    workspace_id=workspace_id,
                    grid=DEFAULT_GRID,
                )
            )
        for has_logs in (False, True):
            overview[f"kpis_logs_{has_logs}"] = _json(
                await users.get_overview_stats(
                    session,
                    schemas.UserOverviewStatsQueryParams(has_logs=has_logs),
                    workspace_id=workspace_id,
                    grid=DEFAULT_GRID,
                )
            )
        scoped["overview"] = overview
        scoped["compare_population"] = sorted(
            _json(await users.compare.get_compare_population(session, workspace_id=workspace_id, grid=DEFAULT_GRID)),
            key=lambda row: row["id"],
        )
        scoped["compare"] = {}
        opponent = ids["player_other"] if workspace_id == ids["workspace_other"] else ids["player_away"]
        for label, params in (
            ("global", schemas.UserCompareParams()),
            ("target", schemas.UserCompareParams(baseline="target_user", target_user_id=opponent)),
            ("damage", schemas.UserCompareParams(baseline="cohort", role=DAMAGE)),
        ):
            scoped["compare"][label] = _json(
                await users.get_compare(
                    session,
                    ids["player"],
                    params,
                    workspace_id=workspace_id,
                    grid=DEFAULT_GRID,
                )
            )
        scoped["hero_compare"] = {}
        for label, filters in (
            ("all_stats", {}),
            ("damage", {"baseline": "cohort", "role": DAMAGE}),
            ("hero_and_map", {"left_entity_id": ids["hero"], "right_entity_id": ids["hero"], "map_id": ids["map"]}),
            (
                "target",
                {
                    "baseline": "target_user",
                    "target_user_id": opponent,
                    "left_entity_id": ids["hero"],
                    "right_entity_id": ids["hero_other"],
                },
            ),
            ("no_stats_target", {"baseline": "target_user", "target_user_id": ids["player_event_only"]}),
        ):
            scoped["hero_compare"][label] = _json(
                await users.get_hero_compare(
                    session,
                    ids["player"],
                    schemas.UserCharacterCompareParams(stats=ALL_STATS, **filters),
                    workspace_id=workspace_id,
                    grid=DEFAULT_GRID,
                )
            )
        playtimes, values = await users.compare.get_users_hero_compare_stats(
            session,
            user_ids=None,
            hero_id=None,
            map_id=None,
            stats=ALL_STATS,
            workspace_id=workspace_id,
            grid=DEFAULT_GRID,
        )
        scoped["hero_compare_raw"] = {
            "playtime_by_user": _json(playtimes),
            "values": [
                _json((user_id, stat, value))
                for (user_id, stat), value in sorted(values.items(), key=lambda item: (item[0][0], item[0][1].value))
            ],
        }
        scoped["hero_leaderboards"] = {}
        for hero_key in ("hero", "hero_other"):
            for stat in (
                enums.LogStatsName.Eliminations,
                enums.LogStatsName.Deaths,
                enums.LogStatsName.WeaponAccuracy,
                enums.LogStatsName.KD,
                enums.LogStatsName.KDA,
            ):
                scoped["hero_leaderboards"][f"{hero_key}:{stat.value}"] = _leaderboard_page(
                    await heroes.get_hero_leaderboard(
                        session,
                        discipline=OW,
                        entity_id=ids[hero_key],
                        params=schemas.CharacterLeaderboardParams(per_page=100, stat=stat),
                        workspace_id=workspace_id,
                        grid=DEFAULT_GRID,
                    )
                )
        scoped["hero_playtime_all_players"] = _json(
            await heroes.get_playtime(
                session,
                schemas.CharacterPlaytimePaginationParams(per_page=100),
                discipline=OW,
                workspace_id=workspace_id,
            )
        )
        map_params = schemas.UserMapsSearchParams(
            per_page=100,
            sort="count",
            order="desc",
            entities=["parent", "characters", "character_stats"],
        )
        scoped["maps"] = _json(
            await maps.get_top_user(session, ids["player"], map_params, discipline=OW, workspace_id=workspace_id)
        )
        scoped["maps_summary"] = _json(
            await maps.get_top_user_summary(
                session,
                ids["player"],
                map_params,
                discipline=OW,
                workspace_id=workspace_id,
            )
        )
        scoped["map_min_count"] = _json(
            await maps.get_top_user(
                session,
                ids["player"],
                schemas.UserMapsSearchParams(per_page=100, sort="id", min_count=2),
                discipline=OW,
                workspace_id=workspace_id,
            )
        )
        scoped["statistics"] = {}
        for name, reader in (
            ("champions", statistics.get_most_champions),
            ("winrate", statistics.get_to_winrate_players),
        ):
            for label, params in (
                ("ranked", pagination.PaginationSortParams(per_page=100, sort="value", order="desc")),
                ("only_count", pagination.PaginationSortParams(only_count=True)),
            ):
                scoped["statistics"][f"{name}:{label}"] = _json(
                    await reader(
                        session,
                        params,
                        discipline=OW,
                        workspace_id=workspace_id,
                    )
                )
                scoped["statistics"][f"{name}:{label}"]["results"].sort(key=lambda row: (-row["value"], row["id"]))
        scoped["achievements"] = await _achievement_outputs(session, ids, workspace_id)
        scoped["encounter_pages"] = {}
        for page in (1, 2, 100):
            scoped["encounter_pages"][str(page)] = _json(
                await users.get_encounters_by_user(
                    session,
                    ids["player"],
                    pagination.PaginationSortParams(page=page, per_page=1, sort="played_at", entities=ALL_ENCOUNTERS),
                    workspace_id=workspace_id,
                )
            )
        for label, filters in (
            ("win", {"result_filter": "win"}),
            ("loss", {"result_filter": "loss"}),
            ("draw", {"result_filter": "draw"}),
            ("mvp", {"mvp1": True}),
            ("logs", {"has_logs": True}),
            ("no_logs", {"has_logs": False}),
            ("opponent", {"opponent": "away"}),
            ("group", {"stage": "group"}),
        ):
            scoped["encounter_pages"][label] = _json(
                await users.get_encounters_by_user(
                    session,
                    ids["player"],
                    pagination.PaginationSortParams(per_page=100, sort="played_at", entities=ALL_ENCOUNTERS),
                    workspace_id=workspace_id,
                    **filters,
                )
            )

    output["edge_users"] = {}
    for player in ("player_away", "player_event_only", "player_removed", "player_no_member", "player_other"):
        output["edge_users"][player] = await _user_outputs(session, ids[player], ids["workspace"])
    output["global_hero_records"] = [
        _json(tuple(row))
        for row in sorted(
            await users.profile.get_statistics_by_heroes_all_values(session),
            key=lambda row: (row[1], row[0].value),
        )
    ]
    output["tournaments"] = {}
    for tournament_key in ("tournament", "tournament_other", "tournament_hidden"):
        tournament_id = ids[tournament_key]
        tournament = await session.get(models.Tournament, tournament_id)
        if tournament is None:
            raise AssertionError(f"Missing shared fixture tournament {tournament_key}")
        by_stat = await statistics_queries.get_tournament_avg_match_stat_for_user_bulk(
            session,
            tournament,
            ids["player"],
            ALL_STATS,
        )
        item = {
            "profile": _json(
                await users.get_tournament_with_stats(
                    session,
                    ids["player"],
                    tournament_id,
                    grid=DEFAULT_GRID,
                )
            ),
            "encounters": _json(await users.get_tournament_encounters(session, ids["player"], tournament_id)),
            "all_stat_averages": [_json(tuple(row)) for row in sorted(by_stat, key=lambda row: row[0].value)],
            "mvp": _json(await statistics_queries.get_tournament_mvp_stat_for_user(session, tournament, ids["player"])),
            "mvp_no_stats": _json(
                await statistics_queries.get_tournament_mvp_stat_for_user(
                    session,
                    tournament,
                    ids["player_event_only"],
                )
            ),
            "leaderboards": {},
        }
        for stat in tournament_stats:
            item["leaderboards"][stat.value] = _json(
                await users.get_tournament_leaderboard(session, tournament_id, stat)
            )
        item["hero_leaderboard"] = _leaderboard_page(
            await heroes.get_hero_leaderboard(
                session,
                discipline=OW,
                entity_id=ids["hero"],
                params=schemas.CharacterLeaderboardParams(
                    per_page=100,
                    tournament_id=tournament_id,
                    stat=enums.LogStatsName.Eliminations,
                ),
                grid=DEFAULT_GRID,
            )
        )
        item["hero_statistics"] = _hero_stat_rows(
            await users.profile.get_statistics_by_heroes(
                session,
                ids["player"],
                tournament_id=tournament_id,
            )
        )
        item["maps"] = _json(
            await maps.get_top_user(
                session,
                ids["player"],
                schemas.UserMapsSearchParams(
                    per_page=100,
                    sort="id",
                    tournament_id=tournament_id,
                    entities=["characters", "character_stats", "parent"],
                ),
                discipline=OW,
            )
        )
        item["achievements"] = _json(
            await achievements.get_user_achievements(
                session,
                ids["player"],
                ["matches", "tournaments"],
                tournament_id=tournament_id,
            )
        )
        output["tournaments"][tournament_key] = item
    return _legacy_catalog(_json(output))


def test_app_readers_preserve_captured_p3_outputs(stats_parity_database: tuple[str, dict[str, int]]) -> None:
    """Missing scope/grain predicates, changed denominators/ranks or DTOs fail here."""
    from tests.stats_reader_numeric_parity import assert_app_golden

    url, ids = stats_parity_database

    async def run() -> None:
        async with _database_session(url) as session:
            await assert_app_golden(session, ids, await collect_outputs(session, ids))

    asyncio.run(run())


@pytest.mark.parametrize("seconds", [0, 60, 61, 599, 600])
def test_native_hero_thresholds_and_distinct_denominators(
    stats_parity_database: tuple[str, dict[str, int]],
    seconds: int,
) -> None:
    """Strict >60 per-match eligibility differs from the >=600 population gate."""
    from shared.models.stats.defs import StatDef
    from shared.models.stats.match import StatsFact

    url, ids = stats_parity_database

    async def run() -> None:
        configure_test_cache()
        async with _database_session(url) as session:
            stat_id = (
                await session.execute(
                    sa.select(StatDef.id).where(
                        StatDef.discipline == "overwatch",
                        StatDef.code == enums.LogStatsName.HeroTimePlayed.value,
                    )
                )
            ).scalar_one()
            facts = StatsFact.__table__
            where = (
                facts.c.workspace_member_id == ids["member"],
                facts.c.segment == 0,
                facts.c.entity_id.is_not(None),
                facts.c.stat_id == stat_id,
            )
            await session.execute(sa.update(facts).where(*where).values(value=0))
            await session.execute(
                sa.update(facts)
                .where(
                    *where,
                    facts.c.match_id == ids["match"],
                    facts.c.entity_id == ids["hero"],
                )
                .values(value=seconds)
            )
            rows = await users.profile.get_statistics_by_heroes(
                session,
                ids["player"],
                [enums.LogStatsName.Eliminations],
                tournament_id=ids["tournament"],
                workspace_id=ids["workspace"],
            )
            map_rows = await hero_queries.get_user_hero_stats_by_maps(
                session,
                [ids["map"]],
                ids["player"],
                tournament_id=ids["tournament"],
                workspace_id=ids["workspace"],
            )
            shares = await hero_queries.get_heroes_playtime_by_maps(
                session,
                [ids["map"]],
                ids["player"],
                tournament_id=ids["tournament"],
                workspace_id=ids["workspace"],
            )
            if seconds <= 60:
                assert rows == []
                assert map_rows == []
                assert shares == []
            else:
                assert len(rows) == len(map_rows) == len(shares) == 1
                stat, hero, total, best, per10, _metadata = rows[0]
                assert stat == enums.LogStatsName.Eliminations and hero.id == ids["hero"]
                # Frozen fixture: 24 eliminations * .75 hero share; 7200s MATCH duration.
                assert (total, best, per10) == (18, 18, 1.5)
                assert map_rows[0][0].id == ids["hero"]
                assert tuple(map_rows[0][1:]) == (ids["map"], 1, 1, 0, 0, 1, seconds, 1)
                assert (shares[0][0].id, shares[0][1], shares[0][2]) == (ids["hero"], ids["map"], 1)
            leaderboard = await heroes.get_hero_leaderboard(
                session,
                discipline=OW,
                entity_id=ids["hero"],
                params=schemas.CharacterLeaderboardParams(
                    per_page=100,
                    tournament_id=ids["tournament"],
                    stat=enums.LogStatsName.Eliminations,
                ),
                workspace_id=ids["workspace"],
                grid=DEFAULT_GRID,
            )
            subject = [row for row in leaderboard.results if row.user_id == ids["player"]]
            if seconds < 600:
                assert subject == []
            else:
                assert len(subject) == 1
                # Leaderboard divides by HERO playtime, unlike profile/compare.
                assert (subject[0].games_played, subject[0].playtime_seconds, subject[0].per10_eliminations) == (
                    1,
                    600,
                    18,
                )
            comparison = await users.get_hero_compare(
                session,
                ids["player"],
                schemas.UserCharacterCompareParams(
                    baseline="target_user",
                    target_user_id=ids["player_event_only"],
                    left_entity_id=ids["hero"],
                    right_entity_id=ids["hero"],
                    map_id=ids["map"],
                    tournament_id=ids["tournament"],
                    stats=[enums.LogStatsName.Eliminations],
                ),
                workspace_id=ids["workspace"],
                grid=DEFAULT_GRID,
            )
            assert comparison.left_playtime_seconds == seconds
            assert comparison.metrics[0].left_value == (1.5 if seconds == 600 else 0)
            assert comparison.metrics[0].right_value == 0
            assert comparison.metrics[0].delta_percent is None
            await session.rollback()

    asyncio.run(run())


def test_native_mvp_reads_impact_rank_only(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    from shared.models.stats.defs import StatDef
    from shared.models.stats.match import StatsFact

    url, ids = stats_parity_database

    async def run() -> None:
        configure_test_cache()
        async with _database_session(url) as session:
            impact_id = await session.scalar(
                sa.select(StatDef.id).where(
                    StatDef.discipline == "overwatch", StatDef.code == enums.LogStatsName.ImpactRank.value
                )
            )
            facts = StatsFact.__table__
            whole = (
                facts.c.workspace_member_id == ids["member"],
                facts.c.segment == 0,
                facts.c.entity_id.is_(None),
                facts.c.stat_id == impact_id,
            )
            # One subject match isolates the placement from unrelated career history.
            await session.execute(sa.delete(facts).where(*whole, facts.c.match_id != ids["match"]))
            tournament = await session.get(models.Tournament, ids["tournament"])
            assert tournament is not None
            for expected in (2, 1):
                await session.execute(sa.update(facts).where(*whole).values(value=expected))
                row = await statistics_queries.get_tournament_mvp_stat_for_user(session, tournament, ids["player"])
                assert row is not None and row.value == expected
                _, merged = await statistics_queries.get_tournament_user_ranks(
                    session, tournament, ids["player"], [enums.LogStatsName.KDA]
                )
                assert merged is not None and (merged.value, merged.rank, merged.total) == (
                    row.value,
                    row.rank,
                    row.total,
                )
                leaderboard = await statistics_queries.get_tournament_mvp_stat_leaderboard(session, tournament.id)
                assert next(item.value for item in leaderboard if item.user_id == ids["player"]) == expected
                assert await users.encounters.count_user_mvp_maps(session, ids["player"], ids["workspace"]) == int(
                    expected == 1
                )
                page = await _uncached(
                    users.get_encounters_by_user,
                    session,
                    ids["player"],
                    pagination.PaginationSortParams(per_page=100, sort="played_at"),
                    workspace_id=ids["workspace"],
                    mvp1=True,
                )
                assert [encounter.id for encounter in page.results] == ([ids["encounter"]] if expected == 1 else [])
            # No rank fact: no placement, never a zero.
            await session.execute(sa.delete(facts).where(*whole))
            assert await statistics_queries.get_tournament_mvp_stat_for_user(session, tournament, ids["player"]) is None
            await session.rollback()

    asyncio.run(run())


def test_native_public_matches_use_slots_and_achievement_revoke_is_effective(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    from shared.models.achievements.achievement import AchievementOverride

    url, ids = stats_parity_database

    async def run() -> None:
        configure_test_cache()
        async with _database_session(url) as session:
            encounters = await _uncached(users.get_tournament_encounters, session, ids["player"], ids["tournament"])
            reverse = next(
                match for encounter in encounters for match in encounter.matches if match.id == ids["match_reversed"]
            )
            assert [(p.tournament_team_id, p.team_facts["score"]) for p in reverse.participants] == [
                (ids["team_home"], 4),
                (ids["team_away"], 3),
            ]
            earned = await achievements.get_user_achievements(
                session,
                ids["player_away"],
                ["matches", "tournaments"],
                workspace_id=ids["workspace"],
            )
            assert [rule.id for rule in earned] == [ids["rule"]]
            link = next(match for match in earned[0].matches if match.id == ids["match_reversed"])
            assert [(p.tournament_team_id, p.team_facts["score"]) for p in link.participants] == [
                (ids["team_home"], 4),
                (ids["team_away"], 3),
            ]
            await session.execute(
                sa.update(AchievementOverride.__table__)
                .where(
                    AchievementOverride.id == ids["override"],
                )
                .values(action="revoke")
            )
            assert (
                await achievements.get_user_achievements(
                    session,
                    ids["player_away"],
                    ["matches", "tournaments"],
                    workspace_id=ids["workspace"],
                )
                == []
            )
            earners = await achievements.get_achievement_users(
                session, ids["rule"], pagination.PaginationParams(per_page=100)
            )
            assert earners.total == 1
            assert [(row.user.id, row.count) for row in earners.results] == [(ids["player"], 1)]
            assert await achievements.queries.get_count_users(session, [ids["rule"]]) == {ids["rule"]: 1}
            assert (
                await achievements.get_user_achievements(
                    session,
                    ids["player"],
                    ["matches", "tournaments"],
                    workspace_id=ids["workspace_other"],
                )
                == []
            )
            await session.rollback()

    asyncio.run(run())


@pytest.mark.parametrize("workspace_scoped", [False, True])
def test_native_ow_readers_exclude_same_player_foreign_discipline(
    stats_parity_database: tuple[str, dict[str, int]],
    workspace_scoped: bool,
) -> None:
    from shared.models.stats.match import StatsFact
    from shared.testing.stats_parity import seed_native_sentinel

    url, ids = stats_parity_database
    workspace_id = ids["workspace"] if workspace_scoped else None

    async def run() -> None:
        configure_test_cache()
        async with _database_session(url) as session:

            async def ow_outputs(map_ids: list[int]) -> Any:
                playtime, values = await users.compare.get_users_hero_compare_stats(
                    session,
                    user_ids=[ids["player"]],
                    hero_id=None,
                    map_id=None,
                    stats=ALL_STATS,
                    workspace_id=workspace_id,
                    grid=DEFAULT_GRID,
                )
                map_playtime = await hero_queries.get_heroes_playtime_by_maps(
                    session,
                    map_ids,
                    ids["player"],
                    workspace_id=workspace_id,
                )
                map_stats = await hero_queries.get_user_hero_stats_by_maps(
                    session,
                    map_ids,
                    ids["player"],
                    workspace_id=workspace_id,
                )
                return _json(
                    {
                        "profile_hero_statistics": _hero_stat_rows(
                            await users.profile.get_statistics_by_heroes(
                                session,
                                ids["player"],
                                workspace_id=workspace_id,
                            )
                        ),
                        "hero_playtime": await heroes.get_playtime(
                            session,
                            schemas.CharacterPlaytimePaginationParams(user_id=ids["player"], per_page=100),
                            discipline=OW,
                            workspace_id=workspace_id,
                        ),
                        "hero_comparison": {
                            "playtime": playtime,
                            "stats": [
                                (user_id, stat, value)
                                for (user_id, stat), value in sorted(
                                    values.items(), key=lambda item: (item[0][0], item[0][1].value)
                                )
                            ],
                        },
                        "map_playtime": [(heroes.to_read(hero), *values) for hero, *values in map_playtime],
                        "map_statistics": [(heroes.to_read(hero), *values) for hero, *values in map_stats],
                    }
                )

            before = await ow_outputs([ids["map"], ids["map_other"]])
            assert before["profile_hero_statistics"]
            assert before["hero_playtime"]["total"] > 0
            assert before["hero_comparison"]["stats"]
            # Only this adversarial clone gets LoL data; the golden template stays
            # exactly the migrated legacy population, including generic counts.
            await session.run_sync(lambda sync_session: seed_native_sentinel(sync_session.connection(), ids))
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(StatsFact)
                    .where(
                        StatsFact.match_id == ids["match_lol"],
                        StatsFact.workspace_member_id == ids["member"],
                    )
                )
                == 4
            )
            after = await ow_outputs([ids["map"], ids["map_other"], ids["map_lol"]])
            assert after == before

            assert await users.compare.get_compare_catalog_entities(
                session,
                left_hero_id=ids["hero_lol"],
                right_hero_id=ids["hero_lol"],
                map_id=ids["map_lol"],
            ) == (None, None, None)
            # Another game's character is not a character of this game: a 404, never an empty OW board.
            with pytest.raises(ApiHTTPException) as foreign_character:
                await heroes.get_hero_leaderboard(
                    session,
                    discipline=OW,
                    entity_id=ids["hero_lol"],
                    params=schemas.CharacterLeaderboardParams(per_page=100, stat=enums.LogStatsName.HeroDamageDealt),
                    workspace_id=workspace_id,
                    grid=DEFAULT_GRID,
                )
            assert foreign_character.value.status_code == 404
            foreign = await session.get(models.Tournament, ids["tournament_lol"])
            assert foreign is not None
            assert (
                await statistics_queries.get_tournament_avg_match_stat_for_user_bulk(
                    session,
                    foreign,
                    ids["player"],
                    ALL_STATS,
                )
                == []
            )
            assert await statistics_queries.get_tournament_user_ranks(session, foreign, ids["player"], ALL_STATS) == (
                [],
                None,
            )
            assert (
                await statistics_queries.get_tournament_stat_leaderboard(
                    session,
                    foreign.id,
                    enums.LogStatsName.HeroDamageDealt,
                )
                == []
            )
            await session.rollback()

    asyncio.run(run())


@pytest.mark.parametrize("workspace_scoped", [False, True])
def test_hero_leaderboard_ships_the_grid_each_division_is_a_number_on(
    stats_parity_database: tuple[str, dict[str, int]],
    workspace_scoped: bool,
) -> None:
    """A scoped row's ``div`` names the workspace grid the page carries once; an all-workspaces row's ``div`` is a
    native-ladder number with no stored grid behind it."""
    from shared.division_grid import DivisionGrid, ladder_grid
    from shared.services.division_grid.access import tournament_effective_version_id_expr

    url, ids = stats_parity_database

    async def run() -> None:
        configure_test_cache()
        async with _database_session(url) as session:
            # A real grid version for the scoped read: the one the seed tournament resolves to.
            version_id = await session.scalar(
                sa.select(tournament_effective_version_id_expr(sa.literal(ids["tournament"])))
            )
            assert version_id is not None
            page = await heroes.get_hero_leaderboard(
                session,
                discipline=OW,
                entity_id=ids["hero"],
                params=schemas.CharacterLeaderboardParams(per_page=100, stat=enums.LogStatsName.Eliminations),
                workspace_id=ids["workspace"] if workspace_scoped else None,
                grid=DivisionGrid(version_id=version_id, tiers=DEFAULT_GRID.tiers),
            )
            assert page.results
            if workspace_scoped:
                assert [grid.id for grid in page.division_grids] == [version_id]
                assert {row.division_grid_version_id for row in page.results} == {version_id}
            else:
                assert page.division_grids == []
                ladder_numbers = {tier.number for tier in ladder_grid(OW).tiers}
                for row in page.results:
                    assert row.division_grid_version_id is None
                    assert row.div in ladder_numbers

    asyncio.run(run())


def test_native_match_expansions_keep_inactive_game_participants(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    """Live participation removal must not erase or reorient a historical game."""
    from shared.models import EncounterTeam
    from src.services.achievement_reads._mappers import to_match_link
    from src.services.user._mappers import to_match_with_user_stats

    url, ids = stats_parity_database

    async def run() -> None:
        async with _database_session(url) as session:
            await session.execute(
                sa.update(EncounterTeam)
                .where(
                    EncounterTeam.id.in_([ids["encounter_team_home"], ids["encounter_team_away"]]),
                )
                .values(active=False)
            )
            reads = await achievements.queries.get_matches_bulk(session, [ids["match_reversed"]])
            assert len(reads) == 1
            profile = to_match_with_user_stats(reads[0])
            achievement = to_match_link(reads[0])
            expected = [
                (ids["encounter_team_home"], ids["team_home"], 4),
                (ids["encounter_team_away"], ids["team_away"], 3),
            ]
            for match in (profile, achievement):
                assert [
                    (p.encounter_team_id, p.tournament_team_id, p.team_facts["score"]) for p in match.participants
                ] == expected
            assert profile.map_index == 2
            await session.rollback()

    asyncio.run(run())


def test_unbound_history_survives_retired_seats_and_roster_changes(stats_parity_database) -> None:
    """A missing game or today's roster must not remove observed dossier facts."""
    from shared.models import EncounterTeam, IngestJob, Player, StatsMatch

    url, ids = stats_parity_database

    async def run() -> None:
        configure_test_cache()
        async with _database_session(url) as session:
            before = _hero_stat_rows(
                await users.profile.get_statistics_by_heroes(session, ids["player"], workspace_id=ids["workspace"])
            )
            await session.execute(
                sa.update(StatsMatch)
                .where(StatsMatch.id == ids["match_reversed"])
                .values(encounter_game_id=None, source_map_index=99)
            )
            assert (
                _hero_stat_rows(
                    await users.profile.get_statistics_by_heroes(session, ids["player"], workspace_id=ids["workspace"])
                )
                == before
            )
            job_id = await session.scalar(
                sa.select(StatsMatch.ingest_job_id).where(StatsMatch.id == ids["match_reversed"])
            )
            await session.execute(sa.update(IngestJob).where(IngestJob.id == job_id).values(raw_status="missing"))
            await session.execute(
                sa.update(EncounterTeam)
                .where(EncounterTeam.id.in_([ids["encounter_team_home"], ids["encounter_team_away"]]))
                .values(active=False)
            )
            await session.execute(
                sa.update(Player)
                .where(
                    Player.workspace_member.has(models.WorkspaceMember.player_id == ids["player"]),
                    Player.tournament_id == ids["tournament"],
                )
                .values(is_substitution=True)
            )
            dossier = await _uncached(users.get_tournament_encounters, session, ids["player"], ids["tournament"])
            history = next(encounter for encounter in dossier if encounter.id == ids["encounter"])
            assert len({match.id for match in history.matches}) == len(history.matches)
            match = next(match for match in history.matches if match.id == ids["match_reversed"])
            assert match.encounter_id == ids["encounter"]
            assert match.map_index is None  # source_map_index is never official order.
            assert [(p.tournament_team_id, p.team_facts["score"]) for p in match.participants] == [
                (ids["team_home"], 4),
                (ids["team_away"], 3),
            ]
            assert history.teams == []  # Historical observations do not resurrect live seats.
            assert match.raw_status == "missing"
            assert match.raw_available is False
            earned = await achievements.get_user_achievements(
                session, ids["player_away"], ["matches", "tournaments"], workspace_id=ids["workspace"]
            )
            link = next(match for match in earned[0].matches if match.id == ids["match_reversed"])
            assert link.encounter_id == ids["encounter"]
            assert [(p.tournament_team_id, p.team_facts["score"]) for p in link.participants] == [
                (ids["team_home"], 4),
                (ids["team_away"], 3),
            ]
            page = await _uncached(
                users.get_encounters_by_user,
                session,
                ids["player"],
                pagination.PaginationSortParams(per_page=100, sort="played_at", entities=["matches"]),
                workspace_id=ids["workspace"],
            )
            historical = [encounter for encounter in page.results if encounter.id == ids["encounter"]]
            assert len(historical) == 1
            assert ids["match_reversed"] in {match.id for match in historical[0].matches}
            foreign, _ = await users.encounters.get_user_encounters_paginated(
                session,
                ids["player"],
                pagination.PaginationSortParams(per_page=100, sort="played_at"),
                workspace_id=ids["workspace_other"],
            )
            assert all(encounter.id != ids["encounter"] for encounter, *_ in foreign)
            wins, _ = await users.encounters.get_user_encounters_paginated(
                session,
                ids["player"],
                pagination.PaginationSortParams(per_page=100, sort="played_at"),
                workspace_id=ids["workspace"],
                result="win",
            )
            assert all(encounter.id != ids["encounter"] for encounter, *_ in wins)
            await session.rollback()

    asyncio.run(run())


def test_native_match_hero_arrays_ignore_fact_insertion_order(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    """Both match-list consumers order their complete character arrays explicitly."""
    from shared.models.stats import StatDef, StatsFact

    url, ids = stats_parity_database

    async def run() -> None:
        async with _database_session(url) as session:
            playtime_id = await session.scalar(
                sa.select(StatDef.id).where(
                    StatDef.discipline == "overwatch",
                    StatDef.code == enums.LogStatsName.HeroTimePlayed.value,
                )
            )
            facts = StatsFact.__table__
            grain = sa.and_(
                facts.c.match_id == ids["match"],
                facts.c.segment == 0,
                facts.c.workspace_member_id == ids["member"],
                facts.c.stat_id == playtime_id,
                facts.c.entity_id.in_([ids["hero"], ids["hero_other"]]),
            )
            rows = (
                (await session.execute(sa.select(facts).where(grain).order_by(facts.c.entity_id.desc())))
                .mappings()
                .all()
            )
            assert len(rows) == 2
            await session.execute(facts.delete().where(grain))
            await session.execute(facts.insert(), [dict(row) for row in rows])
            paginated, _ = await users.encounters.get_user_encounters_paginated(
                session,
                ids["player"],
                pagination.PaginationSortParams(per_page=100, sort="played_at"),
                workspace_id=ids["workspace"],
            )
            unpaginated = await users.encounters.get_user_encounter_matches_unpaginated(
                session,
                ids["player"],
                tournament_id=ids["tournament"],
            )
            paginated_heroes = next(
                row[2].viewer.characters for row in paginated if row[1] is not None and row[1].match.id == ids["match"]
            )
            unpaginated_heroes = next(
                row[3].viewer.characters
                for row in unpaginated
                if row[2] is not None and row[2].match.id == ids["match"]
            )
            assert [hero.id for hero in paginated_heroes] == [ids["hero"], ids["hero_other"]]
            assert [hero.id for hero in unpaginated_heroes] == [ids["hero"], ids["hero_other"]]
            await session.rollback()

    asyncio.run(run())


def test_native_reductions_ignore_physical_fact_order(
    stats_parity_database: tuple[str, dict[str, int]],
) -> None:
    """Equal observations have one binary64 result, independent of heap insertion."""
    from shared.models.stats import StatDef, StatsFact, StatsMatch

    url, ids = stats_parity_database

    async def run() -> None:
        async with _database_session(url) as session:
            codes = (enums.LogStatsName.ScopedAccuracy, enums.LogStatsName.WeaponAccuracy)
            definitions = dict(
                (
                    await session.execute(
                        sa.select(StatDef.id, StatDef.code).where(
                            StatDef.discipline == "overwatch",
                            StatDef.code.in_([code.value for code in codes]),
                        )
                    )
                ).all()
            )
            facts = StatsFact.__table__
            grain = sa.and_(
                facts.c.workspace_member_id == ids["member_away"],
                facts.c.entity_id == ids["hero_other"],
                facts.c.segment == 0,
                facts.c.stat_id.in_(definitions),
            )
            rows = [
                dict(row)
                for row in (
                    await session.execute(sa.select(facts).where(grain).order_by(facts.c.match_id, facts.c.stat_id))
                ).mappings()
            ]
            match_ids = sorted({row["match_id"] for row in rows})
            assert len(match_ids) >= 3
            values = dict(
                zip(
                    match_ids,
                    [0.5, 2.0**-54, 2.0**-54] + [0.0] * (len(match_ids) - 3),
                    strict=True,
                )
            )
            expected = 0.0
            reverse = 0.0
            for match_id in match_ids:
                expected += values[match_id]
            for match_id in reversed(match_ids):
                reverse += values[match_id]
            assert expected.hex() != reverse.hex()  # The fixture actually exposes unordered addition.
            for row in rows:
                row["value"] = values[row["match_id"]]
            durations = dict(
                (
                    await session.execute(
                        sa.select(StatsMatch.id, StatsMatch.duration_s).where(
                            StatsMatch.id.in_(match_ids),
                        )
                    )
                ).all()
            )
            denominator = 0.0
            for match_id in match_ids:
                denominator += durations[match_id]
            observed = []
            for physical_rows in (rows, list(reversed(rows))):
                await session.execute(facts.delete().where(grain))
                await session.execute(facts.insert(), physical_rows)
                profile = await users.profile.get_statistics_by_heroes(
                    session,
                    ids["player_away"],
                    list(codes),
                    workspace_id=ids["workspace"],
                )
                selected = {
                    code: (float(total).hex(), float(avg).hex())
                    for code, hero, total, _best, avg, _meta in profile
                    if hero.id == ids["hero_other"]
                }
                assert selected == {code: (expected.hex(), (expected / denominator * 600).hex()) for code in codes}
                _, comparison = await users.compare.get_users_hero_compare_stats(
                    session,
                    user_ids=[ids["player_away"]],
                    hero_id=ids["hero_other"],
                    map_id=None,
                    stats=list(codes),
                    workspace_id=ids["workspace"],
                    grid=DEFAULT_GRID,
                )
                assert {code: comparison[(ids["player_away"], code)].hex() for code in codes} == {
                    code: (expected / denominator * 600).hex() for code in codes
                }
                observed.append((selected, comparison))
            assert observed[0] == observed[1]
            await session.rollback()

    asyncio.run(run())
