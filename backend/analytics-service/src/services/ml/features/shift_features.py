"""Shift v2 feature frame builder: service-side loading and dispatch.

The cache, the v1 linear history, the v1 OpenSkill shift map and the per-tournament feature frames are loaded here;
the module-owned SQL (rank chronology on the canonical scale, materialised Performance rows, MVP dominance) and the
column construction come from the discipline's analytics module.

The result is the input to :func:`train_shift_v2` and :meth:`ShiftModelV2.predict`.
"""

from __future__ import annotations

import logging
import typing

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.analytics_exports import analytics_exports
from src.core.config import settings
from src.domain.ratings import compute_linear_metrics
from src.services.analytics.flows import flows_service

from .aggregations import build_tournament_feature_frame
from .cache import get_or_build_dataframe, scope_cache_params

__all__ = ("build_shift_feature_frame",)

logger = logging.getLogger(__name__)


async def _linear_history_frame(
    session: AsyncSession,
    *,
    discipline: str,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    params = scope_cache_params(workspace_id=workspace_id, workspace_ids=workspace_ids)

    async def _build() -> pd.DataFrame:
        df = await flows_service.get_data_frame(
            session,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )
        return compute_linear_metrics(df, shift_scale=settings.linear_shift_scale) if not df.empty else df

    return await get_or_build_dataframe("shift_linear_history", params, _build, discipline=discipline)


async def _openskill_shift_frame(
    session: AsyncSession,
    tournament_id: int,
    df_history: pd.DataFrame,
    *,
    discipline: str,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    params = {
        "tournament_id": int(tournament_id),
        **scope_cache_params(workspace_id=workspace_id, workspace_ids=workspace_ids),
    }

    async def _build() -> pd.DataFrame:
        shift_map, _ = await flows_service.compute_openskill_shift_map(
            session,
            tournament_id,
            df_history,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )
        return pd.DataFrame(
            [
                {"player_id": int(player_id), "os_shift": float(shift), "os_shift_sd": float(sd)}
                for player_id, (shift, sd) in shift_map.items()
            ],
            columns=["player_id", "os_shift", "os_shift_sd"],
        )

    return await get_or_build_dataframe("shift_openskill_map", params, _build, discipline=discipline)


async def build_shift_feature_frame(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    discipline: str,
    history_through_tournament_id: int | None = None,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return the per-(player, tournament) shift training frame.

    For each tournament in ``tournament_ids``:
    - compute v1 OpenSkill shift map (``compute_openskill_shift_map``)
    - compute tournament-level feature aggregates
    - join the player rank chronology to produce ``prior_div``,
      ``next_tournament_div``, ``tournaments_played``,
      ``tournaments_at_current_div``
    """
    tournament_ids = sorted({int(t) for t in tournament_ids})
    if not tournament_ids:
        return pd.DataFrame()

    exports = analytics_exports(discipline)
    rank_history = await exports.load_player_rank_history(
        session,
        tournament_ids,
        history_through_tournament_id=history_through_tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if rank_history.empty:
        return pd.DataFrame()

    performance_features = await exports.load_performance_features(session, tournament_ids)
    df_history = await _linear_history_frame(
        session,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
        discipline=discipline,
    )
    if df_history.empty:
        return pd.DataFrame()

    all_frames: list[pd.DataFrame] = []
    for tid in tournament_ids:
        tournament_features = await build_tournament_feature_frame(
            session,
            tid,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )
        if tournament_features.empty:
            continue

        # ``get_data_frame`` takes no range — it loads every analytics row;
        # ``compute_openskill_shift_map`` slices internally via ``tournament_id``.
        try:
            shift_frame = await _openskill_shift_frame(
                session,
                tid,
                df_history,
                workspace_id=workspace_id,
                workspace_ids=workspace_ids,
                discipline=discipline,
            )
            shift_map = {
                int(row.player_id): (float(row.os_shift), float(row.os_shift_sd))
                for row in shift_frame.itertuples(index=False)
            }
        except Exception:
            logger.exception(
                "Failed to compute OpenSkill shift map for tournament_id=%d",
                tid,
            )
            shift_map = {}

        all_frames.append(
            exports.assemble_shift_tournament_frame(
                tid,
                tournament_features=tournament_features,
                rank_history=rank_history,
                history=df_history,
                shift_map=shift_map,
                performance_features=performance_features,
                dominance=await exports.compute_mvp_dominance(session, tid),
            )
        )

    return exports.concat_shift_frames(all_frames)
