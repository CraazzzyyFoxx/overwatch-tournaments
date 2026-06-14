"""Pre-encounter OpenSkill snapshot helpers.

The v2 win-probability classifier (Phase 3) and the per-match Performance v2
target (Phase 1d) both need an estimate of *each team's strength as it was
before the encounter was played* — using the post-encounter rating would
leak the outcome.

The current OpenSkill replay in
:mod:`src.services.analytics.flows.compute_openskill_shift_map` produces
post-replay ratings. The helpers in this module run the same replay but
freeze the rating snapshot *before* applying each encounter, yielding a
``(encounter_id, team_id) → mu`` map that can be merged into feature frames.
"""

from __future__ import annotations

import typing

import pandas as pd
from openskill.models import PlackettLuce, PlackettLuceRating
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.analytics import service as v1_service
from src.services.analytics.flows import (
    get_data_frame,
    get_id_role,
    get_plackett_luce,
    prepare_openskill_data,
)

from .cache import get_or_build_dataframe, scope_cache_params

__all__ = (
    "snapshot_pre_encounter_team_mu",
)


async def snapshot_pre_encounter_team_mu(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
    look_back: int = 10,
) -> pd.DataFrame:
    params = {
        "tournament_id": int(tournament_id),
        "look_back": int(look_back),
        **scope_cache_params(workspace_id=workspace_id, workspace_ids=workspace_ids),
    }

    async def _build() -> pd.DataFrame:
        return await _snapshot_pre_encounter_team_mu_uncached(
            session,
            tournament_id,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            look_back=look_back,
        )

    return await get_or_build_dataframe("opponent_strength_snapshot", params, _build)


async def _snapshot_pre_encounter_team_mu_uncached(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
    look_back: int = 10,
) -> pd.DataFrame:
    """Return a DataFrame with one row per ``(encounter_id, team_id)`` holding
    the team-average OpenSkill ``mu`` evaluated *just before* the encounter was
    played.

    Algorithm:

    1. Build the analytics DataFrame for the ``look_back`` most recent tournaments
       up to and including ``tournament_id`` (chronological window, same range as
       the v1 OpenSkill flow).
    2. Initialise per-player ratings via :func:`prepare_openskill_data`.
    3. Replay every match in chronological order; **before** each encounter, snapshot
       the team-average mu of its home and away rosters.

    Output columns: ``encounter_id``, ``team_id``, ``avg_mu``, ``max_mu``,
    ``min_mu``, ``std_mu`` (NaN-safe).
    """
    # ``get_data_frame`` loads every analytics-eligible tournament row in one
    # query — there is no range parameter; ``look_back`` is applied via the
    # chronological window resolved by ``lookback_start_tournament_id`` below.
    df = await get_data_frame(
        session,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if df.empty:
        return pd.DataFrame(
            columns=["encounter_id", "team_id", "avg_mu", "max_mu", "min_mu", "std_mu"]
        )

    start_tid = await v1_service.lookback_start_tournament_id(
        session,
        tournament_id,
        look_back,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    matches = await v1_service.get_matches(
        session,
        start_tid,
        tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    teams = await v1_service.get_teams_with_players(session, tournament_id)

    pl: PlackettLuce = get_plackett_luce()
    _, players_rating, _ = prepare_openskill_data(df, pl, teams, matches)

    # Players keyed by (user_id, role).
    rating_map: dict[str, PlackettLuceRating] = dict(players_rating)

    # Group matches by encounter so we snapshot pre-encounter (not pre-match).
    snapshots: list[dict[str, typing.Any]] = []
    seen_encounters: set[int] = set()

    # NOTE: ``v1_service.get_matches`` returns ``Sequence[models.Encounter]``
    # (the v1 naming is historical — the analytics flow conflates the two).
    # Each row's own id is ``Encounter.id``; there is no ``encounter_id``
    # attribute on the ORM object itself.
    for encounter in matches:
        if encounter.id in seen_encounters:
            # Already snapshotted before the first match of this encounter.
            continue
        seen_encounters.add(encounter.id)

        for team in (encounter.home_team, encounter.away_team):
            if team is None or not getattr(team, "players", None):
                continue
            mus: list[float] = []
            for player in team.players:
                key = get_id_role(player)
                rating = rating_map.get(key)
                if rating is None:
                    continue
                mus.append(float(rating.mu))
            if not mus:
                continue
            snapshots.append(
                {
                    "encounter_id": int(encounter.id),
                    "team_id": int(team.id),
                    "avg_mu": float(sum(mus) / len(mus)),
                    "max_mu": float(max(mus)),
                    "min_mu": float(min(mus)),
                    "std_mu": float(pd.Series(mus).std(ddof=0)) if len(mus) > 1 else 0.0,
                }
            )

        # Update ratings *after* snapshotting, replicating the v1 replay order.
        home_team_players = [
            rating_map[get_id_role(p)]
            for p in (encounter.home_team.players if encounter.home_team else [])
            if get_id_role(p) in rating_map
        ]
        away_team_players = [
            rating_map[get_id_role(p)]
            for p in (encounter.away_team.players if encounter.away_team else [])
            if get_id_role(p) in rating_map
        ]
        if not home_team_players or not away_team_players:
            continue

        home_score = getattr(encounter, "home_score", 0) or 0
        away_score = getattr(encounter, "away_score", 0) or 0
        ranks = (
            [0, 1]
            if home_score > away_score
            else [1, 0]
            if home_score < away_score
            else [0, 0]
        )
        new_home, new_away = pl.rate(
            [home_team_players, away_team_players], ranks=ranks
        )
        for player, new_rating in zip(
            (p for p in encounter.home_team.players),
            new_home,
            strict=False,
        ):
            rating_map[get_id_role(player)] = new_rating
        for player, new_rating in zip(
            (p for p in encounter.away_team.players),
            new_away,
            strict=False,
        ):
            rating_map[get_id_role(player)] = new_rating

    return pd.DataFrame(snapshots)
