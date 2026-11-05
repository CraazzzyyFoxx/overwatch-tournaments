"""Roster synergy — how much of a team has already played together, and how well.

Teams are minted per tournament, but PLAYERS persist (identity anchor:
``workspace_member.player_id``). For every roster of the target tournament this
looks at all unordered player pairs and their shared prior teams:

- ``synergy_pairs``   — share of roster pairs (0..1) with at least one decided
  encounter together on a past team. A balancer roster of strangers scores 0.
- ``synergy_winrate`` — encounter winrate of those shared teams, weighted by
  games played (NaN when the roster has no co-play history at all — the model
  handles missing natively; 0.5 would fake "average" experience).

Strictly pre-tournament: only tournaments that STARTED before the target one
count (chronology is the key of ``shared.core.chrono`` — ids are not
time-ordered in this database).
"""

from __future__ import annotations

import itertools
import typing

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.chrono import tournament_chrono_key
from shared.services.workspace_scope import workspace_scope_filter

__all__ = ("team_synergy_features",)

_COLUMNS = ["team_id", "synergy_pairs", "synergy_winrate"]


def _synergy_from_frames(
    target_roster: pd.DataFrame,
    prior_rosters: pd.DataFrame,
    prior_results: pd.DataFrame,
) -> pd.DataFrame:
    """Pure-pandas core, split out for tests.

    ``target_roster``: (team_id, uid); ``prior_rosters``: (team_id, uid) of past
    teams; ``prior_results``: (team_id, games, wins) of those past teams.
    """
    pair_games: dict[tuple[int, int], float] = {}
    pair_wins: dict[tuple[int, int], float] = {}
    if not prior_rosters.empty and not prior_results.empty:
        results = prior_results.set_index("team_id")
        for team_id, group in prior_rosters.groupby("team_id"):
            if team_id not in results.index:
                continue
            games = float(results.at[team_id, "games"])
            wins = float(results.at[team_id, "wins"])
            if games <= 0:
                continue
            uids = sorted({int(u) for u in group["uid"]})
            for pair in itertools.combinations(uids, 2):
                pair_games[pair] = pair_games.get(pair, 0.0) + games
                pair_wins[pair] = pair_wins.get(pair, 0.0) + wins

    rows: list[dict[str, typing.Any]] = []
    for team_id, group in target_roster.groupby("team_id"):
        uids = sorted({int(u) for u in group["uid"]})
        pairs = list(itertools.combinations(uids, 2))
        if not pairs:
            rows.append({"team_id": int(team_id), "synergy_pairs": 0.0, "synergy_winrate": float("nan")})
            continue
        games = 0.0
        wins = 0.0
        seen = 0
        for pair in pairs:
            g = pair_games.get(pair, 0.0)
            if g > 0:
                seen += 1
                games += g
                wins += pair_wins.get(pair, 0.0)
        rows.append(
            {
                "team_id": int(team_id),
                "synergy_pairs": seen / len(pairs),
                "synergy_winrate": (wins / games) if games > 0 else float("nan"),
            }
        )
    return pd.DataFrame(rows, columns=_COLUMNS)


async def _roster_frame(
    session: AsyncSession,
    where: list[typing.Any],
) -> pd.DataFrame:
    query = (
        sa.select(
            models.Player.team_id.label("team_id"),
            models.WorkspaceMember.player_id.label("uid"),
        )
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(models.Player.is_substitution.is_(False), models.Player.team_id.is_not(None), *where)
    )
    df = pd.DataFrame((await session.execute(query)).mappings().all())
    if df.empty:
        return pd.DataFrame(columns=["team_id", "uid"])
    return df.astype({"team_id": int, "uid": int})


async def team_synergy_features(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return ``(team_id, synergy_pairs, synergy_winrate)`` for a tournament's rosters."""
    target_key = (
        await session.execute(sa.select(*tournament_chrono_key()).where(models.Tournament.id == tournament_id))
    ).one_or_none()
    target = await _roster_frame(session, [models.Player.tournament_id == tournament_id])
    if target.empty or target_key is None:
        return pd.DataFrame(columns=_COLUMNS)

    prior_ids = [
        int(row[0])
        for row in (
            await session.execute(
                sa.select(models.Tournament.id).where(
                    sa.tuple_(*tournament_chrono_key()) < sa.tuple_(*target_key),
                    models.Tournament.is_hidden.is_(False),
                    models.Tournament.discipline == "overwatch",
                    *workspace_scope_filter(workspace_id, workspace_ids),
                )
            )
        ).all()
    ]
    if not prior_ids:
        return _synergy_from_frames(target, pd.DataFrame(columns=["team_id", "uid"]), pd.DataFrame())

    prior_rosters = await _roster_frame(session, [models.Player.tournament_id.in_(prior_ids)])

    first_seat = sa.orm.aliased(models.EncounterTeam, name="first_seat")
    second_seat = sa.orm.aliased(models.EncounterTeam, name="second_seat")
    encounters = pd.DataFrame(
        (
            await session.execute(
                sa.select(
                    first_seat.team_id.label("home_team_id"),
                    second_seat.team_id.label("away_team_id"),
                    first_seat.score.label("home_score"),
                    second_seat.score.label("away_score"),
                )
                .select_from(models.Encounter)
                .join(
                    first_seat,
                    sa.and_(
                        first_seat.encounter_id == models.Encounter.id,
                        first_seat.slot == 1,
                        first_seat.active.is_(True),
                    ),
                )
                .join(
                    second_seat,
                    sa.and_(
                        second_seat.encounter_id == models.Encounter.id,
                        second_seat.slot == 2,
                        second_seat.active.is_(True),
                    ),
                )
                .where(
                    # A duel only, decided: one seat placed ahead of the other.
                    models.Encounter.slot_count == 2,
                    models.Encounter.tournament_id.in_(prior_ids),
                    first_seat.placement.is_not(None),
                    second_seat.placement.is_not(None),
                    first_seat.placement != second_seat.placement,
                    first_seat.team_id != second_seat.team_id,
                )
            )
        )
        .mappings()
        .all()
    )
    if encounters.empty:
        prior_results = pd.DataFrame(columns=["team_id", "games", "wins"])
    else:
        home = pd.DataFrame(
            {
                "team_id": encounters["home_team_id"],
                "won": (encounters["home_score"] > encounters["away_score"]).astype(float),
            }
        )
        away = pd.DataFrame(
            {
                "team_id": encounters["away_team_id"],
                "won": (encounters["away_score"] > encounters["home_score"]).astype(float),
            }
        )
        sides = pd.concat([home, away], ignore_index=True).dropna(subset=["team_id"])
        prior_results = (
            sides.astype({"team_id": int}).groupby("team_id")["won"].agg(games="count", wins="sum").reset_index()
        )

    return _synergy_from_frames(target, prior_rosters, prior_results)
