"""Roll-up helpers that combine extractor frames with opponent-strength snapshots.

Wired by :mod:`src.services.ml.training.orchestrator` and
:mod:`src.services.ml.inference.runner`; kept thin so the underlying
extractors stay reusable in tests.
"""

from __future__ import annotations

import typing

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from .cache import get_or_build_dataframe, scope_cache_params
from .extractors import extract_match_features, extract_tournament_features
from .opponent_strength import snapshot_pre_encounter_team_mu

__all__ = (
    "build_match_features_with_strength",
    "build_tournament_feature_frame",
)


async def build_match_features_with_strength(
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
        return await _build_match_features_with_strength_uncached(
            session,
            tournament_id,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            look_back=look_back,
        )

    return await get_or_build_dataframe("match_features_with_strength", params, _build)


async def _build_match_features_with_strength_uncached(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
    look_back: int = 10,
) -> pd.DataFrame:
    """Return :func:`extract_match_features` enriched with pre-encounter OpenSkill mu.

    Adds columns ``team_avg_mu``, ``opp_avg_mu``, ``opp_max_mu``, ``opp_min_mu``,
    ``mu_gap`` to each match row by joining the snapshot returned by
    :func:`snapshot_pre_encounter_team_mu` on ``(encounter_id, team_id)``.
    """
    matches = await extract_match_features(
        session,
        [tournament_id],
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if matches.empty:
        return matches

    snapshots = await snapshot_pre_encounter_team_mu(
        session,
        tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
        look_back=look_back,
    )
    if snapshots.empty:
        for col in ("team_avg_mu", "opp_avg_mu", "opp_max_mu", "opp_min_mu", "mu_gap"):
            matches[col] = np.nan
        return matches

    own = snapshots.rename(columns={"avg_mu": "team_avg_mu", "max_mu": "team_max_mu", "min_mu": "team_min_mu"})[
        ["encounter_id", "team_id", "team_avg_mu", "team_max_mu", "team_min_mu"]
    ]

    opp = snapshots.rename(columns={"avg_mu": "opp_avg_mu", "max_mu": "opp_max_mu", "min_mu": "opp_min_mu"})[
        ["encounter_id", "team_id", "opp_avg_mu", "opp_max_mu", "opp_min_mu"]
    ]

    merged = matches.merge(own, on=["encounter_id", "team_id"], how="left")

    # Map opponent team_id per row: home rows use away team's snapshot and vv.
    def _opp_team_id(row: pd.Series) -> typing.Any:
        return row["away_team_id"] if row["is_home"] else row["home_team_id"]

    merged["opp_team_id"] = merged.apply(_opp_team_id, axis=1)
    merged = merged.merge(
        opp.rename(columns={"team_id": "opp_team_id"}),
        on=["encounter_id", "opp_team_id"],
        how="left",
    )
    merged["mu_gap"] = merged["team_avg_mu"] - merged["opp_avg_mu"]
    return merged


async def build_tournament_feature_frame(
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
        return await _build_tournament_feature_frame_uncached(
            session,
            tournament_id,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            look_back=look_back,
        )

    return await get_or_build_dataframe("tournament_feature_frame", params, _build)


async def _build_tournament_feature_frame_uncached(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
    look_back: int = 10,
) -> pd.DataFrame:
    """Convenience wrapper used by the Performance v2 inference runner."""
    df = await extract_tournament_features(
        session,
        [tournament_id],
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if df.empty:
        return df

    # Aggregate mu features into per-(player, tournament) rows by averaging
    # the per-match snapshots already merged for the training step.
    matches = await build_match_features_with_strength(
        session,
        tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
        look_back=look_back,
    )
    if matches.empty:
        for col in ("team_avg_mu", "opp_avg_mu", "mu_gap"):
            df[col] = np.nan
        return df

    mu = (
        matches.groupby(["tournament_id", "player_id"], dropna=False)[["team_avg_mu", "opp_avg_mu", "mu_gap"]]
        .mean()
        .reset_index()
    )
    return df.merge(mu, on=["tournament_id", "player_id"], how="left")
