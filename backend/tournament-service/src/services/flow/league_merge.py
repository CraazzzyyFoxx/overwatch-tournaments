"""League merge (spec §15): the mapping file and the season planner.

`plan_leagues` proposes `league_merge.json` from the legacy `is_league` tournaments; the owner completes the
`aggregate` of every entry by hand and `load_mapping` refuses a file that still lacks one.
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.chrono import chrono_sort_key
from shared.domain.flow.config import AggregateNodeConfig

__all__ = (
    "LeagueDay",
    "LeagueEntry",
    "LeagueSourceRow",
    "MappingError",
    "MergeError",
    "fetch_league_rows",
    "load_mapping",
    "plan_leagues",
)

LEAGUE_NAME_SEPARATOR = " | "


class MappingError(ValueError):
    """The mapping file is unusable."""


class MergeError(RuntimeError):
    """The data does not allow the merge."""


class LeagueDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tournament_id: int
    day: int = Field(ge=1)
    division: str | None = None


class LeagueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league: str
    season: int = Field(ge=1)
    name: str = Field(min_length=1)
    target_tournament_id: int
    aggregate: AggregateNodeConfig
    days: list[LeagueDay] = Field(min_length=1)

    @model_validator(mode="after")
    def _days_are_consistent(self) -> LeagueEntry:
        ids = [d.tournament_id for d in self.days]
        if len(set(ids)) != len(ids):
            raise ValueError("a tournament is listed twice")
        slots = [(d.day, d.division) for d in self.days]
        if len(set(slots)) != len(slots):
            raise ValueError("(day, division) must be unique")
        earliest = min(d.day for d in self.days)
        if not any(d.tournament_id == self.target_tournament_id and d.day == earliest for d in self.days):
            raise ValueError("target must be a tournament of the earliest day")
        return self

    @property
    def days_latest_first(self) -> list[int]:
        ordered = sorted(self.days, key=lambda d: (d.day, d.division or ""), reverse=True)
        return [d.tournament_id for d in ordered]

    @property
    def others(self) -> list[int]:
        return [d.tournament_id for d in self.days if d.tournament_id != self.target_tournament_id]


def load_mapping(text: str) -> list[LeagueEntry]:
    raw = json.loads(text)
    if not isinstance(raw, list):
        raise MappingError("the mapping must be a JSON list")
    entries: list[LeagueEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise MappingError("the mapping must be a JSON list of objects")
        where = f"league {item.get('league')!r} season {item.get('season')}"
        if item.get("aggregate") is None:
            raise MappingError(f"{where}: aggregate is required")
        try:
            entries.append(LeagueEntry.model_validate(item))
        except ValidationError as exc:
            raise MappingError(f"{where}: {exc}") from exc
    seen: set[int] = set()
    for league in entries:
        for day in league.days:
            if day.tournament_id in seen:
                raise MappingError(f"tournament {day.tournament_id} is mapped twice")
            seen.add(day.tournament_id)
    return entries


@dataclass(frozen=True)
class LeagueSourceRow:
    id: int
    workspace_id: int
    discipline: str
    name: str
    start_date: datetime | None
    end_date: datetime | None
    created_at: datetime


def plan_leagues(rows: Iterable[LeagueSourceRow], *, season_gap_days: int = 21) -> list[dict[str, Any]]:
    """Group by workspace, game and name prefix; a gap above `season_gap_days` starts a new season."""
    groups: dict[tuple[int, str, str], list[LeagueSourceRow]] = defaultdict(list)
    for r in rows:
        groups[(r.workspace_id, r.discipline, r.name.split(LEAGUE_NAME_SEPARATOR)[0])].append(r)
    planned: list[dict[str, Any]] = []
    for (_, _, league), members in groups.items():
        members.sort(key=chrono_sort_key)
        seasons: list[list[LeagueSourceRow]] = [[members[0]]]
        for previous, current in itertools.pairwise(members):
            if chrono_sort_key(current)[0] - chrono_sort_key(previous)[0] > timedelta(days=season_gap_days):
                seasons.append([])
            seasons[-1].append(current)
        for number, season in enumerate(seasons, start=1):
            days: list[dict[str, Any]] = []
            by_start = itertools.groupby(season, key=lambda r: chrono_sort_key(r)[0])
            for day, (_, group) in enumerate(by_start, start=1):
                same = sorted(group, key=lambda r: r.id)
                for r in same:
                    division = (
                        r.name.split(LEAGUE_NAME_SEPARATOR, 1)[1]
                        if len(same) > 1 and LEAGUE_NAME_SEPARATOR in r.name
                        else None
                    )
                    days.append({"tournament_id": r.id, "day": day, "division": division})
            planned.append(
                {
                    "league": league,
                    "season": number,
                    "name": league,
                    "target_tournament_id": days[0]["tournament_id"],
                    "aggregate": None,
                    "days": days,
                }
            )
    return sorted(planned, key=lambda p: p["target_tournament_id"])


async def fetch_league_rows(session: AsyncSession) -> list[LeagueSourceRow]:
    # Raw SQL: the ORM model drops `is_league`; this runs only against a database still at `flowP6_01`.
    result = await session.execute(
        sa.text(
            "SELECT id, workspace_id, discipline, name, start_date, end_date, created_at "
            "FROM tournament.tournament WHERE is_league"
        )
    )
    return [LeagueSourceRow(*r) for r in result.all()]
