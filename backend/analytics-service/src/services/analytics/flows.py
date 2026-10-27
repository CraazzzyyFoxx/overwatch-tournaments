import typing

import numpy as np
import pandas as pd
import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.division_grid import DEFAULT_GRID
from shared.services.workspace_scope import get_tournament_workspace_id
from src.core.analytics_exports import analytics_exports, supports_analytics, tournament_discipline
from src.core.config import settings
from src.domain.ratings import (
    LINEAR,
    OPENSKILL,
    OPENSKILL_LOOKBACK,
    POINTS,
    compute_linear_metrics,
    compute_points_shifts,
    division_delta_points,
    get_plackett_luce,
    prepare_openskill_data,
    rank_sd_to_divisions,
)

from .canonical_division import load_source_grids
from .service import analytics_service


class AnalyticsFlowsService:
    async def get_data_frame(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
        workspace_ids: typing.Sequence[int] | None = None,
        *,
        discipline: str,
    ) -> pd.DataFrame:
        data = await analytics_service.get_analytics(
            session,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )
        tournament_version_ids = await analytics_service.get_tournament_version_ids(
            session,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )

        rows: list[dict[str, typing.Any]] = []
        for row in data:
            tid = row["tournament_id"]
            rows.append(
                {
                    "tournament_id": tid,
                    "started_at": row["started_at"],
                    "version_id": tournament_version_ids.get(tid),
                    "team_id": row["team_id"],
                    "player_name": row["player_name"],
                    "player_id": row["player_id"],
                    "user_id": row["user_id"],
                    "role": row["role"],
                    "id_role": f"{row['user_id']}-{row['role']}",
                    "cost": row["rank"],
                    "div": None,
                    "wins": row["wins"],
                    "losses": row["losses"],
                    "match_count": row["match_count"],
                    "overall_position": row["overall_position"],
                    "team_count": row["team_count"],
                    "performance_points": row["performance_points"],
                    "log_available": 1.0 if row["performance_points"] is not None else 0.0,
                    "log_residual": 0.0,
                    "map_diff": 0.0,
                    "placement_score": 0.0,
                    "is_changed": False,
                    "points_shift": 0.0,
                    "points_shift_sd": np.nan,
                    "linear_shift_sd": np.nan,
                    "effective_evidence": 0.0,
                    "sample_tournaments": 0,
                    "sample_matches": 0,
                    "log_coverage": 0.0,
                    "linear_stable_shift": 0.0,
                    "linear_trend_shift": 0.0,
                }
            )

        if not rows:
            return pd.DataFrame(rows)

        df = pd.DataFrame(rows)

        # Normalize every division to the canonical OW grid so current/previous div
        # are comparable across workspaces and grid versions.
        grids = await load_source_grids(session, df["version_id"].dropna().unique())
        canonical_div_for = analytics_exports(discipline).canonical_div_for

        df["div"] = [
            canonical_div_for(grids, version_id, cost)
            for version_id, cost in zip(df["version_id"], df["cost"], strict=False)
        ]
        # Per-player history runs in tournament chronology (start date, then id): ids are not chronological.
        df = df.sort_values(["id_role", "started_at", "tournament_id"]).reset_index(drop=True)
        # The rank chronology runs over ranked rows only: an unranked tournament has no division and does not break
        # the previous-division link of the next ranked one.
        ranked = df["cost"].notna()
        by_role = df[ranked].groupby("id_role")
        df["previous_cost"] = by_role["cost"].shift(1)
        df["pre_previous_cost"] = by_role["cost"].shift(2)
        df["prev_version_id"] = by_role["version_id"].shift(1)

        def resolve_previous_div(row) -> int | None:
            prev_cost = row["previous_cost"]
            if prev_cost is None or pd.isna(prev_cost):
                return None
            return canonical_div_for(grids, row["prev_version_id"], int(prev_cost))

        df["previous_div"] = df.apply(resolve_previous_div, axis=1)
        df["is_changed"] = ranked & (df["previous_div"] != df["div"])
        df["normalized_shift_one"] = df.apply(
            lambda row: division_delta_points(row["previous_div"], row["div"]),
            axis=1,
        )
        df["normalized_shift_two"] = df[ranked].groupby("id_role")["normalized_shift_one"].shift(1)
        df["map_diff"] = df.apply(
            lambda row: (row["wins"] - row["losses"]) / max(row["wins"] + row["losses"], 1),
            axis=1,
        )
        # A team without a standing scores a neutral 0. ``pd.isna``, not ``is None``: beside teams that have one, the
        # missing position is NaN in the frame, and a NaN signal would poison the player's Linear history and the
        # frame-wide noise estimate of its sd.
        df["placement_score"] = df.apply(
            lambda row: 0.0
            if pd.isna(row["overall_position"]) or pd.isna(row["team_count"])
            else (1.0 - 2.0 * (row["overall_position"] - 1) / max((row["team_count"] - 1), 1)),
            axis=1,
        )

        # The shift signal is team-result only (map_diff + placement_score, computed
        # above). Individual performance is intentionally NOT folded into the Linear
        # signal: it adds ~0 over team W/L.
        return df

    async def create_players_shifts_is_not_exists(
        self,
        session: AsyncSession,
        tournament_id: int,
        df: pd.DataFrame,
    ) -> None:
        players = await analytics_service.get_players_by_tournament_id(session, tournament_id)
        players_by_id = {player.player_id: player for player in players}
        final_df = df[df["tournament_id"] == tournament_id]
        final_df = final_df.replace({np.nan: None})

        for _, row in final_df.iterrows():
            shift_one = int(row["normalized_shift_one"]) if row["normalized_shift_one"] is not None else None
            shift_two = int(row["normalized_shift_two"]) if row["normalized_shift_two"] is not None else None

            analytics_player = players_by_id.get(row["player_id"])
            if analytics_player is not None:
                analytics_player.wins = int(row["wins"])
                analytics_player.losses = int(row["losses"])
                analytics_player.shift_one = shift_one
                analytics_player.shift_two = shift_two
                session.add(analytics_player)
                continue

            session.add(
                models.AnalyticsPlayer(
                    tournament_id=row["tournament_id"],
                    player_id=row["player_id"],
                    wins=row["wins"],
                    losses=row["losses"],
                    shift_one=shift_one,
                    shift_two=shift_two,
                    shift=0,
                )
            )

    async def compute_openskill_shift_map(
        self,
        session: AsyncSession,
        tournament_id: int,
        df: pd.DataFrame,
        workspace_id: int | None = None,
        workspace_ids: typing.Sequence[int] | None = None,
        *,
        discipline: str,
    ) -> tuple[dict[int, tuple[float, float]], bool]:
        """``{player_id: (os_shift, os_shift_sd)}`` for the tournament's ranked rows, and whether any match replayed.

        ``os_shift_sd`` is the rating's σ in canonical divisions, through the width of the grid tier its μ falls in.
        """
        window_ids = await analytics_service.lookback_tournament_ids(
            session,
            tournament_id,
            OPENSKILL_LOOKBACK,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )
        matches = await analytics_service.get_matches_for_tournaments(
            session,
            window_ids,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )
        teams = await analytics_service.get_teams_with_players(session, tournament_id)
        grids = await load_source_grids(session, df["version_id"].dropna().unique())
        canonical_div_for = analytics_exports(discipline).canonical_div_for
        pl = get_plackett_luce()
        rosters = await analytics_service.get_rosters(session, matches)
        _, players_rating, _ = prepare_openskill_data(df, pl, teams, matches, rosters)

        final_df = df[df["tournament_id"] == tournament_id].replace({np.nan: None})
        shift_map: dict[int, tuple[float, float]] = {}
        for _, row in final_df.iterrows():
            rating = players_rating.get(row["id_role"])
            # An unranked row has no division to shift from.
            if rating is None or row["div"] is None:
                continue
            predicted_div = canonical_div_for(grids, row["version_id"], int(round(rating.mu)))
            # The source grid ``canonical_div_for`` resolves the rating on, onto its canonical ladder.
            grid = grids.get(int(row["version_id"]), DEFAULT_GRID) if row["version_id"] is not None else DEFAULT_GRID
            shift_map[int(row["player_id"])] = (
                round(float(row["div"] - predicted_div), 2),
                rank_sd_to_divisions(grid, DEFAULT_GRID, rating.mu, rating.sigma),
            )

        return shift_map, bool(matches)

    async def persist_algorithm(
        self,
        session: AsyncSession,
        tournament_id: int,
        algorithm_name: str,
        current_df: pd.DataFrame,
        shift_lookup: dict[int, tuple[float, float | None]],
    ) -> None:
        """Replace the algorithm's rows of the tournament; ``shift_lookup`` maps player_id → (shift, shift_sd)."""
        algorithm = await analytics_service.ensure_algorithm(session, algorithm_name)

        await session.execute(
            sa.delete(models.AnalyticsShift).where(
                sa.and_(
                    models.AnalyticsShift.tournament_id == tournament_id,
                    models.AnalyticsShift.algorithm_id == algorithm.id,
                )
            )
        )
        for _, row in current_df.iterrows():
            player_id = int(row["player_id"])
            shift, shift_sd = shift_lookup.get(player_id, (0.0, None))
            session.add(
                models.AnalyticsShift(
                    algorithm_id=algorithm.id,
                    tournament_id=tournament_id,
                    player_id=player_id,
                    shift=round(float(shift), 2),
                    shift_sd=round(float(shift_sd), 4) if shift_sd is not None else None,
                    effective_evidence=round(float(row["effective_evidence"]), 4),
                    sample_tournaments=int(row["sample_tournaments"]),
                    sample_matches=int(row["sample_matches"]),
                    log_coverage=round(float(row["log_coverage"]), 4),
                )
            )

    async def recalculate_analytics(
        self,
        session: AsyncSession,
        tournament_id: int,
        algorithm_names: typing.Iterable[str] | None = None,
        workspace_id: int | None = None,
    ) -> list[str]:
        discipline = await tournament_discipline(session, tournament_id)
        if discipline is None or not supports_analytics(discipline):
            # No analytics module owns this tournament's scale: compute nothing and clear nothing already stored.
            logger.info("Tournament {} has no analytics module ({}); nothing to recalculate", tournament_id, discipline)
            return []
        # Scope to the tournament's own workspace when not given one, so the
        # Points/Linear recalc uses the same cohort the RPC job (workspace-scoped)
        # would — see get_tournament_workspace_id.
        if workspace_id is None:
            workspace_id = await get_tournament_workspace_id(session, tournament_id)
        df = await self.get_data_frame(session, workspace_id=workspace_id, discipline=discipline)
        if df.empty:
            logger.warning("No analytics data found for tournament {}", tournament_id)
            return []

        # Points and Linear are CPU over the workspace's whole history (~0.3 ms a row, a minute at ~170k rows): end the
        # read transaction first, or pgBouncer's 60 s idle-in-transaction timeout kills it. Nothing is written yet.
        await session.commit()
        df = compute_points_shifts(df)
        df = compute_linear_metrics(df, shift_scale=settings.linear_shift_scale)

        supported_recalc_algorithms = {POINTS, LINEAR, OPENSKILL}
        selected_algorithms = (
            [name for name in algorithm_names if name in supported_recalc_algorithms]
            if algorithm_names is not None
            else [POINTS, LINEAR, OPENSKILL]
        )
        selected_set = set(selected_algorithms)

        # The tournament's results feed every later history, so the later tournaments that already have v1 rows are
        # rewritten with it; never-computed ones stay untouched.
        later_ids = await analytics_service.computed_tournament_ids_after(
            session, tournament_id, workspace_id=workspace_id, discipline=discipline
        )
        for tid in (tournament_id, *later_ids):
            current_df = df[df["tournament_id"] == tid].replace({np.nan: None}).copy()
            await self.create_players_shifts_is_not_exists(session, tid, df)

            if POINTS in selected_set:
                await self.persist_algorithm(
                    session,
                    tid,
                    POINTS,
                    current_df,
                    {
                        int(row["player_id"]): (row["points_shift"], row["points_shift_sd"])
                        for _, row in current_df.iterrows()
                    },
                )

            if LINEAR in selected_set:
                await self.persist_algorithm(
                    session,
                    tid,
                    LINEAR,
                    current_df,
                    {
                        int(row["player_id"]): (row["linear_stable_shift"], row["linear_shift_sd"])
                        for _, row in current_df.iterrows()
                    },
                )

            if OPENSKILL in selected_set:
                shift_map, _ = await self.compute_openskill_shift_map(
                    session, tid, df, workspace_id=workspace_id, discipline=discipline
                )
                await self.persist_algorithm(session, tid, OPENSKILL, current_df, shift_map)

        # One transaction for the whole recalculation: readers never see a tournament whose rows are deleted but not
        # yet re-inserted.
        await session.commit()
        return selected_algorithms


flows_service = AnalyticsFlowsService()
