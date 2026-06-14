import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.workspace import workspace_filter

VISIBLE_SHIFT_ALGORITHM_NAMES = ("Linear", "Points", "OpenSkill + ML")


async def get_algorithms(
    session: AsyncSession,
    *,
    only_shift_producers: bool = True,
) -> typing.Sequence[models.AnalyticsAlgorithm]:
    """List analytics algorithms.

    By default returns only algorithms that produce per-player shift rows
    (``produces_shifts = TRUE``) — these are the algorithms the UI dropdown
    can meaningfully switch between. Pass ``only_shift_producers=False`` to
    also list augmentation-only algorithms (Performance ML v2, Standings MC
    v2, Match Quality v1) — used by admin/internal pages.
    """
    query = sa.select(models.AnalyticsAlgorithm)
    if only_shift_producers:
        query = query.where(
            models.AnalyticsAlgorithm.produces_shifts.is_(True),
            models.AnalyticsAlgorithm.name.in_(VISIBLE_SHIFT_ALGORITHM_NAMES),
        )
    query = query.order_by(models.AnalyticsAlgorithm.id)
    result = await session.execute(query)
    return result.scalars().all()


async def get_algorithm_ids_with_shift_data(
    session: AsyncSession, tournament_id: int
) -> set[int]:
    """Return the algorithm IDs that have computed shift rows for a tournament.

    Used to mark which algorithms are actually populated (e.g. ``OpenSkill + ML``
    only after a v2 inference run) so the UI can prefer a richer algorithm by
    default and fall back when it has no data yet.
    """
    result = await session.scalars(
        sa.select(models.AnalyticsShift.algorithm_id)
        .where(models.AnalyticsShift.tournament_id == tournament_id)
        .distinct()
    )
    return {int(algorithm_id) for algorithm_id in result.all()}


async def get_algorithm(session: AsyncSession, id: int) -> models.AnalyticsAlgorithm:
    query = sa.select(models.AnalyticsAlgorithm).where(
        models.AnalyticsAlgorithm.id == id,
        models.AnalyticsAlgorithm.produces_shifts.is_(True),
        models.AnalyticsAlgorithm.name.in_(VISIBLE_SHIFT_ALGORITHM_NAMES),
    )
    result = await session.execute(query)
    return result.scalars().first()


async def get_analytics(
    session: AsyncSession,
    tournament_id: int,
    algorithm: models.AnalyticsAlgorithm,
    workspace_id: int | None = None,
) -> typing.Sequence[
    tuple[models.Team, models.Player, models.AnalyticsShift, models.AnalyticsPlayer]
]:
    query = (
        sa.select(
            models.Team, models.Player, models.AnalyticsShift, models.AnalyticsPlayer
        )
        .options(
            sa.orm.joinedload(models.Team.tournament).joinedload(
                models.Tournament.division_grid_version
            ),
            sa.orm.joinedload(models.Team.standings),
            sa.orm.joinedload(models.Team.standings).joinedload(models.Standing.group),
        )
        .join(models.Tournament, models.Team.tournament_id == models.Tournament.id)
        .join(models.Player, models.Player.team_id == models.Team.id)
        .join(
            models.AnalyticsPlayer, models.AnalyticsPlayer.player_id == models.Player.id
        )
        .join(
            models.AnalyticsShift,
            sa.and_(
                models.AnalyticsShift.player_id == models.Player.id,
                models.AnalyticsShift.tournament_id == tournament_id,
                models.AnalyticsShift.algorithm_id == algorithm.id,
            ),
        )
        .where(
            sa.and_(
                models.Team.tournament_id == tournament_id,
                *workspace_filter(workspace_id),
            )
        )
    )
    result = await session.execute(query)
    return result.unique().all()  # type: ignore


# v2 algorithm names — written by the analytics-worker training pipeline,
# independent of the v1 ``algorithm_id`` the UI selects for shifts/points.
_STANDINGS_V2_NAME = "Standings MC v2"


async def _algorithm_id_by_name(session: AsyncSession, name: str) -> int | None:
    return await session.scalar(
        sa.select(models.AnalyticsAlgorithm.id).where(
            models.AnalyticsAlgorithm.name == name
        )
    )


async def get_predicted_places(
    session: AsyncSession,
    tournament_id: int,
    algorithm_id: int,
) -> dict[int, int]:
    """Return ``{team_id: predicted_place}`` for a tournament.

    Sources, in increasing priority:

    1. Legacy ``analytics.predictions`` row written by the v1 algorithm currently
       selected in the UI (only OpenSkill v1 actually writes here; for other
       v1 algorithms the lookup is empty).
    2. ``analytics.standings_distribution`` row written by the v2 ``Standings
       MC v2`` algorithm — independent of the v1 selector. Overrides the v1
       integer when present.
    """
    query = sa.select(
        models.AnalyticsPredictions.team_id,
        models.AnalyticsPredictions.predicted_place,
    ).where(
        models.AnalyticsPredictions.tournament_id == tournament_id,
        models.AnalyticsPredictions.algorithm_id == algorithm_id,
    )
    result = await session.execute(query)
    predictions = {
        int(team_id): int(predicted_place)
        for team_id, predicted_place in result.all()
        if predicted_place is not None
    }

    standings_v2_id = await _algorithm_id_by_name(session, _STANDINGS_V2_NAME)
    if standings_v2_id is not None:
        distribution_query = sa.select(
            models.AnalyticsStandingsDistribution.team_id,
            models.AnalyticsStandingsDistribution.mean_position,
        ).where(
            models.AnalyticsStandingsDistribution.tournament_id == tournament_id,
            models.AnalyticsStandingsDistribution.algorithm_id == standings_v2_id,
        )
        distribution_result = await session.execute(distribution_query)
        for team_id, mean_position in distribution_result.all():
            if mean_position is not None:
                predictions[int(team_id)] = int(round(float(mean_position)))

    return predictions


async def get_match_quality_anomalies(
    session: AsyncSession,
    tournament_id: int,
    algorithm_id: int,
) -> typing.Sequence[tuple[int, list[dict[str, typing.Any]] | None]]:
    """Return unified player anomalies in the legacy encounter-grouped shape."""
    del algorithm_id

    anomalies = list(
        (
            await session.execute(
                sa.select(models.AnalyticsPlayerAnomaly).where(
                    models.AnalyticsPlayerAnomaly.tournament_id == tournament_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not anomalies:
        return []

    unresolved_player_ids = sorted(
        {
            int(anomaly.player_id)
            for anomaly in anomalies
            if anomaly.source_encounter_id is None
        }
    )
    encounter_for_player: dict[int, int] = {}
    if unresolved_player_ids:
        home_query = (
            sa.select(
                models.Player.id.label("player_id"),
                sa.func.min(models.Match.encounter_id).label("encounter_id"),
            )
            .join(models.Match, models.Match.home_team_id == models.Player.team_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .where(
                models.Encounter.tournament_id == tournament_id,
                models.Player.id.in_(unresolved_player_ids),
            )
            .group_by(models.Player.id)
        )
        away_query = (
            sa.select(
                models.Player.id.label("player_id"),
                sa.func.min(models.Match.encounter_id).label("encounter_id"),
            )
            .join(models.Match, models.Match.away_team_id == models.Player.team_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .where(
                models.Encounter.tournament_id == tournament_id,
                models.Player.id.in_(unresolved_player_ids),
            )
            .group_by(models.Player.id)
        )
        for pid, encounter_id in (await session.execute(home_query)).all() + (
            await session.execute(away_query)
        ).all():
            if pid is None or encounter_id is None:
                continue
            previous = encounter_for_player.get(int(pid))
            encounter_for_player[int(pid)] = (
                int(encounter_id)
                if previous is None
                else min(previous, int(encounter_id))
            )

    grouped: dict[int, list[dict[str, typing.Any]]] = {}
    for anomaly in anomalies:
        encounter_id = (
            int(anomaly.source_encounter_id)
            if anomaly.source_encounter_id is not None
            else encounter_for_player.get(int(anomaly.player_id))
        )
        if encounter_id is None:
            continue
        grouped.setdefault(encounter_id, []).append(
            {
                "player_id": int(anomaly.player_id),
                "kind": str(anomaly.kind),
                "score": float(anomaly.score),
                "confidence": float(anomaly.confidence),
                "reasons": list(anomaly.reasons or []),
                "evidence": anomaly.evidence or None,
                "encounter_id": encounter_id,
            }
        )

    return list(grouped.items())


async def change_shift(
    session: AsyncSession, player_id: int, shift: int
) -> tuple[models.AnalyticsPlayer, models.AnalyticsShift]:
    query = (
        sa.select(models.AnalyticsPlayer, models.AnalyticsShift)
        .join(
            models.AnalyticsShift,
            models.AnalyticsShift.player_id == models.AnalyticsPlayer.player_id,
        )
        .where(
            sa.and_(
                models.AnalyticsPlayer.player_id == player_id,
            )
        )
    )
    result = await session.execute(query)
    analytics, calculated_shift = result.first()

    analytics.shift = shift
    session.add(analytics)
    await session.commit()
    return analytics, calculated_shift


async def get_streaks(
    session: AsyncSession, tournament_id: int
) -> typing.Sequence[tuple[models.User, int, str, int]]:
    subquery = (
        sa.select(
            models.Player.user_id,
            models.Player.role,
            models.Standing.overall_position,
        )
        .join(models.Standing, models.Standing.team_id == models.Player.team_id)
        .where(
            sa.and_(
                models.Player.tournament_id <= tournament_id,
            )
        )
        .order_by(models.Player.tournament_id.desc())
    ).subquery()

    query = (
        sa.select(
            models.User,
            subquery.c.role,
            subquery.c.overall_position,
        )
        .select_from(models.Player)
        .join(subquery, subquery.c.user_id == models.Player.user_id)
        .join(models.User, models.User.id == subquery.c.user_id)
        .where(
            sa.and_(
                models.Player.tournament_id == tournament_id,
            )
        )
    )

    result = await session.execute(query)
    return result.all()
