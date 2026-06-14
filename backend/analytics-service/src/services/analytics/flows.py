import typing

import numpy as np
import pandas as pd
import sqlalchemy as sa
from loguru import logger
from openskill.models import PlackettLuce, PlackettLuceRating
from shared.division_grid import DEFAULT_GRID, DivisionGrid
from shared.services.division_grid_resolution import resolve_tournament_division
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.schemas.analytics import AnalyticsMatch

from . import service
from .linear import TournamentSignal, score_history

COEF_NOVICE_FIRST = 1 / 0.15
COEF_NOVICE_SECOND = 1 / 0.11
COEF_REGULAR = 1 / 0.065
# Number of most-recent tournaments (chronological, not numeric id offset) that
# seed the OpenSkill replay window. See service.lookback_start_tournament_id.
OPENSKILL_LOOKBACK = 10
LINEAR = "Linear"
POINTS = "Points"
OPEN_SKILL = "Open Skill"
mu = 1100


def division_delta_points(
    previous_div: int | float | None,
    current_div: int | float | None,
) -> int | None:
    if previous_div is None or pd.isna(previous_div):
        return None
    if current_div is None or pd.isna(current_div):
        return None
    return int(round((float(previous_div) - float(current_div)) * 100))


def rating_to_division(grid: DivisionGrid, rating_mu: float) -> int:
    return resolve_tournament_division(
        int(round(rating_mu)),
        tournament_grid=grid,
    )


async def get_data_frame(
    session: AsyncSession,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    data = await service.get_analytics(
        session,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    tournament_version_ids = await service.get_tournament_version_ids(
        session,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )

    rows: list[dict[str, typing.Any]] = []
    for row in data:
        tid = row["tournament_id"]
        rows.append(
            {
                "tournament_id": tid,
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
                "previous_cost": row["previous_cost"],
                "pre_previous_cost": row["pre_previous_cost"],
                "previous_div": row["previous_div"],
                "pre_previous_div": row["pre_previous_div"],
                "is_newcomer": bool(row["is_newcomer"]),
                "is_newcomer_role": bool(row["is_newcomer_role"]),
                "is_changed": False,
                "points_shift": 0.0,
                "confidence": 0.0,
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

    all_version_ids = {int(v) for v in df["version_id"].dropna().unique()}
    grids = await service.get_grid_versions(session, all_version_ids)

    def grid_for(version_id) -> DivisionGrid:
        if version_id is None or pd.isna(version_id):
            return DEFAULT_GRID
        return grids.get(int(version_id), DEFAULT_GRID)

    df["div"] = df.apply(
        lambda r: resolve_tournament_division(
            int(r["cost"]),
            tournament_grid=grid_for(r["version_id"]),
        ),
        axis=1,
    )
    df = df.sort_values(["id_role", "tournament_id"]).reset_index(drop=True)
    df["prev_version_id"] = df.groupby("id_role")["version_id"].shift(1)

    cross = df[["prev_version_id", "version_id"]].dropna().drop_duplicates()
    cross = cross[cross["prev_version_id"] != cross["version_id"]]
    pairs = [(int(r["prev_version_id"]), int(r["version_id"])) for _, r in cross.iterrows()]
    tier_mappings = await service.get_primary_division_mappings(session, pairs)

    def resolve_previous_div(row) -> int | None:
        prev_cost = row["previous_cost"]
        if prev_cost is None or pd.isna(prev_cost):
            return row["previous_div"]
        prev_vid = row["prev_version_id"]
        curr_vid = row["version_id"]
        raw = resolve_tournament_division(
            int(prev_cost),
            tournament_grid=grid_for(prev_vid),
        )
        if (
            prev_vid is not None
            and not pd.isna(prev_vid)
            and curr_vid is not None
            and not pd.isna(curr_vid)
            and int(prev_vid) != int(curr_vid)
        ):
            mapping = tier_mappings.get((int(prev_vid), int(curr_vid)))
            if mapping:
                return mapping.get(raw, raw)
        return raw

    df["previous_div"] = df.apply(resolve_previous_div, axis=1)
    df["is_changed"] = df["previous_div"] != df["div"]
    df["normalized_shift_one"] = df.apply(
        lambda row: division_delta_points(row["previous_div"], row["div"]),
        axis=1,
    )
    df["normalized_shift_two"] = df.groupby("id_role")["normalized_shift_one"].shift(1)
    df["map_diff"] = df.apply(
        lambda row: (row["wins"] - row["losses"]) / max(row["wins"] + row["losses"], 1),
        axis=1,
    )
    df["placement_score"] = df.apply(
        lambda row: 0.0
        if row["overall_position"] is None or row["team_count"] is None
        else (
            1.0
            - 2.0 * (row["overall_position"] - 1) / max((row["team_count"] - 1), 1)
        ),
        axis=1,
    )

    for (_, _role), group in df.groupby(["tournament_id", "role"], dropna=False):
        valid = group["performance_points"].dropna()
        if valid.empty:
            continue
        mean = float(valid.mean())
        std = float(valid.std(ddof=0))
        if std <= 1e-9:
            continue
        df.loc[group.index, "log_residual"] = group["performance_points"].apply(
            lambda value, mean=mean, std=std: (
                0.0 if pd.isna(value) else float(np.clip((value - mean) / std, -1.0, 1.0))
            )
        )

    return df


async def create_players_shifts_is_not_exists(
    session: AsyncSession,
    tournament_id: int,
    df: pd.DataFrame | None = None,
) -> None:
    source_df = df if df is not None else await get_data_frame(session)
    players = await service.get_players_by_tournament_id(session, tournament_id)
    players_by_id = {player.player_id: player for player in players}
    final_df = source_df[source_df["tournament_id"] == tournament_id]
    final_df = final_df.replace({np.nan: None})

    for _, row in final_df.iterrows():
        shift_one = (
            int(row["normalized_shift_one"])
            if row["normalized_shift_one"] is not None
            else None
        )
        shift_two = (
            int(row["normalized_shift_two"])
            if row["normalized_shift_two"] is not None
            else None
        )

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

    await session.commit()


def compute_points_shifts(df: pd.DataFrame) -> pd.Series:
    output = pd.Series(0.0, index=df.index, dtype=float)
    for id_role, rows in df.groupby("id_role", sort=False):
        del id_role
        rows = rows.sort_values("tournament_id")
        is_novice = True
        previous_shift = 0.0
        for index, row in rows.iterrows():
            delta = row["wins"] - row["losses"]
            if is_novice:
                if row["is_changed"]:
                    shift = delta / COEF_NOVICE_FIRST
                    is_novice = False
                else:
                    shift = delta / COEF_NOVICE_SECOND
            else:
                shift = delta / COEF_REGULAR
                if row["is_changed"]:
                    shift += delta / COEF_REGULAR
                else:
                    shift += previous_shift
            previous_shift = shift
            output.at[index] = round(float(shift), 2)
    return output


def compute_linear_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    for _, group in df.groupby("id_role", sort=False):
        group = group.sort_values("tournament_id")
        group_rows = group.to_dict("records")
        for position, (index, row) in enumerate(zip(group.index, group_rows, strict=True)):
            del row
            signals: list[TournamentSignal] = []
            for history_position in range(position + 1):
                history = group_rows[history_position]
                signals.append(
                    TournamentSignal(
                        map_diff=float(history["map_diff"]),
                        placement_score=float(history["placement_score"]),
                        log_residual=float(history["log_residual"]),
                        recency_decay=float(0.85 ** (position - history_position)),
                        coverage_weight=float(0.7 + 0.3 * history["log_available"]),
                        newcomer_weight=0.75
                        if history["is_newcomer"] or history["is_newcomer_role"]
                        else 1.0,
                        match_count=int(history["match_count"] or 0),
                        log_available=float(history["log_available"]),
                    )
                )

            metrics = score_history(signals)
            df.at[index, "confidence"] = metrics.confidence
            df.at[index, "effective_evidence"] = metrics.effective_evidence
            df.at[index, "sample_tournaments"] = metrics.sample_tournaments
            df.at[index, "sample_matches"] = metrics.sample_matches
            df.at[index, "log_coverage"] = metrics.log_coverage
            df.at[index, "linear_stable_shift"] = metrics.stable_shift
            df.at[index, "linear_trend_shift"] = metrics.trend_shift

    return df


def get_plackett_luce():
    return PlackettLuce(mu=mu, sigma=mu / 6, beta=mu / 2.75, tau=mu / 300.0, balance=True)


def get_id_role(player: models.Player) -> str:
    return f"{player.user_id}-{player.role}"


def get_player_rating(pl: PlackettLuce, player: models.Player) -> PlackettLuceRating:
    if player.is_newcomer:
        return pl.rating(mu=player.rank, sigma=mu / 4.25)
    if player.is_newcomer_role:
        return pl.rating(mu=player.rank, sigma=mu / 4.25)
    return pl.rating(mu=player.rank)


def prepare_openskill_data(
    df: pd.DataFrame,
    pl: PlackettLuce,
    teams: typing.Sequence[models.Team],
    encounters: typing.Sequence[models.Encounter],
) -> tuple[set[str], dict[str, PlackettLuceRating], list[AnalyticsMatch]]:
    agents: set[str] = set()
    players_rating: dict[str, PlackettLuceRating] = {}
    analytics_matches: list[AnalyticsMatch] = []

    for encounter in encounters:
        home_team = [get_id_role(player) for player in encounter.home_team.players]
        away_team = [get_id_role(player) for player in encounter.away_team.players]

        for player in [*encounter.home_team.players, *encounter.away_team.players]:
            id_role = get_id_role(player)
            if players_rating.get(id_role) is None:
                players_rating[id_role] = get_player_rating(pl, player)

        agents = agents.union(set(home_team))
        agents = agents.union(set(away_team))

        analytics_matches.append(
            AnalyticsMatch(
                tournament_id=encounter.tournament_id,
                home_team_id=encounter.home_team_id,
                home_team_name=encounter.home_team.name,
                away_team_id=encounter.away_team_id,
                away_team_name=encounter.away_team.name,
                home_players=home_team,
                away_players=away_team,
                home_score=encounter.home_score,
                away_score=encounter.away_score,
                time=encounter.tournament.start_date,
            )
        )

    for team in teams:
        for player in team.players:
            id_role = get_id_role(player)
            if id_role not in players_rating:
                players_rating[id_role] = get_player_rating(pl, player)

    for encounter in analytics_matches:
        home_team = [players_rating[i] for i in encounter.home_players]
        away_team = [players_rating[i] for i in encounter.away_players]
        rated_home_team, rated_away_team = pl.rate(
            [home_team, away_team],
            scores=[encounter.home_score, encounter.away_score],
        )
        for player_index in range(len(encounter.home_players)):
            players_rating[encounter.home_players[player_index]] = rated_home_team[player_index]
        for player_index in range(len(encounter.away_players)):
            players_rating[encounter.away_players[player_index]] = rated_away_team[player_index]

    return agents, players_rating, analytics_matches

async def compute_openskill_shift_map(
    session: AsyncSession,
    tournament_id: int,
    df: pd.DataFrame,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> tuple[dict[int, float], bool]:
    start_tid = await service.lookback_start_tournament_id(
        session,
        tournament_id,
        OPENSKILL_LOOKBACK,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    matches = await service.get_matches(
        session,
        start_tid,
        tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    teams = await service.get_teams_with_players(session, tournament_id)
    version_ids = {int(v) for v in df["version_id"].dropna().unique()}
    grids = await service.get_grid_versions(session, version_ids)
    pl = get_plackett_luce()
    _, players_rating, _ = prepare_openskill_data(df, pl, teams, matches)

    def grid_for(version_id) -> DivisionGrid:
        if version_id is None or pd.isna(version_id):
            return DEFAULT_GRID
        return grids.get(int(version_id), DEFAULT_GRID)

    final_df = df[df["tournament_id"] == tournament_id].replace({np.nan: None})
    shift_map: dict[int, float] = {}
    for _, row in final_df.iterrows():
        rating = players_rating.get(row["id_role"])
        if rating is None:
            continue
        predicted_div = rating_to_division(grid_for(row["version_id"]), rating.mu)
        shift_map[int(row["player_id"])] = round(float(row["div"] - predicted_div), 2)

    return shift_map, bool(matches)


async def persist_algorithm(
    session: AsyncSession,
    tournament_id: int,
    algorithm_name: str,
    current_df: pd.DataFrame,
    shift_lookup: dict[int, float],
) -> None:
    algorithm = await service.get_algorithm(session, algorithm_name)

    await session.execute(
        sa.delete(models.AnalyticsShift).where(
            sa.and_(
                models.AnalyticsShift.tournament_id == tournament_id,
                models.AnalyticsShift.algorithm_id == algorithm.id,
            )
        )
    )
    await session.commit()

    for _, row in current_df.iterrows():
        player_id = int(row["player_id"])
        session.add(
            models.AnalyticsShift(
                algorithm_id=algorithm.id,
                tournament_id=tournament_id,
                player_id=player_id,
                shift=round(float(shift_lookup.get(player_id, 0.0)), 2),
                confidence=round(float(row["confidence"]), 4),
                effective_evidence=round(float(row["effective_evidence"]), 4),
                sample_tournaments=int(row["sample_tournaments"]),
                sample_matches=int(row["sample_matches"]),
                log_coverage=round(float(row["log_coverage"]), 4),
            )
        )

    await session.commit()


def get_linear_hybrid_shift_lookup(
    current_df: pd.DataFrame,
    openskill_shift_map: dict[int, float],
    has_match_history: bool,
) -> dict[int, float]:
    output: dict[int, float] = {}
    for _, row in current_df.iterrows():
        player_id = int(row["player_id"])
        stable_shift = float(row["linear_stable_shift"])
        if not has_match_history:
            output[player_id] = round(stable_shift, 2)
            continue

        openskill_shift = openskill_shift_map.get(player_id)
        if openskill_shift is None:
            output[player_id] = round(stable_shift, 2)
            continue

        alpha_eff = 0.35 * min(1.0, int(row["sample_matches"]) / 12.0)
        output[player_id] = round((1.0 - alpha_eff) * stable_shift + alpha_eff * openskill_shift, 2)
    return output


async def recalculate_analytics(
    session: AsyncSession,
    tournament_id: int,
    algorithm_names: typing.Iterable[str] | None = None,
    workspace_id: int | None = None,
) -> list[str]:
    df = await get_data_frame(session, workspace_id=workspace_id)
    if df.empty:
        logger.warning("No analytics data found for tournament {}", tournament_id)
        return []

    df["points_shift"] = compute_points_shifts(df)
    df = compute_linear_metrics(df)
    current_df = df[df["tournament_id"] == tournament_id].replace({np.nan: None}).copy()

    await create_players_shifts_is_not_exists(session, tournament_id, df)

    supported_recalc_algorithms = {POINTS, LINEAR}
    selected_algorithms = (
        [name for name in algorithm_names if name in supported_recalc_algorithms]
        if algorithm_names is not None
        else [POINTS, LINEAR]
    )
    selected_set = set(selected_algorithms)

    if POINTS in selected_set:
        await persist_algorithm(
            session,
            tournament_id,
            POINTS,
            current_df,
            {int(row["player_id"]): float(row["points_shift"]) for _, row in current_df.iterrows()},
        )

    if LINEAR in selected_set:
        await persist_algorithm(
            session,
            tournament_id,
            LINEAR,
            current_df,
            {int(row["player_id"]): float(row["linear_stable_shift"]) for _, row in current_df.iterrows()},
        )

    return selected_algorithms


async def get_analytics(
    session: AsyncSession,
    tournament_id: int,
    workspace_id: int | None = None,
):
    await recalculate_analytics(
        session,
        tournament_id,
        [POINTS],
        workspace_id=workspace_id,
    )


async def get_analytics_openskill(
    session: AsyncSession,
    tournament_id: int,
    workspace_id: int | None = None,
) -> None:
    await recalculate_analytics(
        session,
        tournament_id,
        [OPEN_SKILL],
        workspace_id=workspace_id,
    )


async def get_predictions_openskill(
    session: AsyncSession,
    tournament_id: int,
    df: pd.DataFrame | None = None,
    workspace_id: int | None = None,
) -> None:
    source_df = df if df is not None else await get_data_frame(
        session,
        workspace_id=workspace_id,
    )
    start_tid = await service.lookback_start_tournament_id(
        session, tournament_id, OPENSKILL_LOOKBACK, workspace_id=workspace_id
    )
    matches = await service.get_matches(
        session,
        start_tid,
        tournament_id,
        workspace_id=workspace_id,
    )
    teams = await service.get_teams_with_players(session, tournament_id)
    algorithm = await service.get_algorithm(session, OPEN_SKILL)
    pl = get_plackett_luce()
    _, players_rating, _ = prepare_openskill_data(source_df, pl, teams, matches)
    predicted_teams: list[tuple[str, list[PlackettLuceRating]]] = []

    for team in teams:
        team_players = [players_rating[get_id_role(player)] for player in team.players]
        predicted_teams.append((team.name, team_players))

    predicted = pl.predict_rank([team_players for _, team_players in predicted_teams])

    await session.execute(
        sa.delete(models.AnalyticsPredictions).where(
            sa.and_(
                models.AnalyticsPredictions.tournament_id == tournament_id,
                models.AnalyticsPredictions.algorithm_id == algorithm.id,
            )
        )
    )
    await session.commit()

    for team_data, predict in zip(predicted_teams, predicted, strict=True):
        team = next((item for item in teams if item.name == team_data[0]), None)
        if team is None:
            continue

        session.add(
            models.AnalyticsPredictions(
                algorithm_id=algorithm.id,
                tournament_id=tournament_id,
                team_id=team.id,
                predicted_place=predict[0],
            )
        )

    await session.commit()
