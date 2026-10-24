import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository import (
    AnalyticsAlgorithmRepository,
    AnalyticsPlayerRepository,
    AnalyticsShiftRepository,
)
from shared.repository.stats_queries import match_context
from shared.services.workspace_scope import workspace_filter

VISIBLE_SHIFT_ALGORITHM_NAMES = ("Linear", "Points", "OpenSkill", "OpenSkill + ML")

# v2 algorithm names — written by the analytics-worker training pipeline,
# independent of the v1 ``algorithm_id`` the UI selects for shifts/points.
_STANDINGS_V2_NAME = "Standings MC v2"

__all__ = (
    "VISIBLE_SHIFT_ALGORITHM_NAMES",
    "AnalyticsReadService",
    "analytics_read_service",
)


class AnalyticsReadService:
    def __init__(
        self,
        *,
        algorithms: AnalyticsAlgorithmRepository = AnalyticsAlgorithmRepository(),
        shifts: AnalyticsShiftRepository = AnalyticsShiftRepository(),
        players: AnalyticsPlayerRepository = AnalyticsPlayerRepository(),
    ) -> None:
        self.algorithms = algorithms
        self.shifts = shifts
        self.players = players

    async def get_algorithms(
        self,
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
        if only_shift_producers:
            return await self.algorithms.list_shift_producers(session, VISIBLE_SHIFT_ALGORITHM_NAMES)
        return await self.algorithms.list_all(session)

    async def get_algorithm_ids_with_shift_data(self, session: AsyncSession, tournament_id: int) -> set[int]:
        """Return the algorithm IDs that have computed shift rows for a tournament.

        Used to mark which algorithms are actually populated (e.g. ``OpenSkill + ML``
        only after a v2 inference run) so the UI can prefer a richer algorithm by
        default and fall back when it has no data yet.
        """
        return await self.shifts.algorithm_ids_for_tournament(session, tournament_id)

    async def get_algorithm(self, session: AsyncSession, id: int) -> models.AnalyticsAlgorithm | None:
        return await self.algorithms.get_shift_producer(session, id, VISIBLE_SHIFT_ALGORITHM_NAMES)

    async def get_analytics(
        self,
        session: AsyncSession,
        tournament_id: int,
        algorithm: models.AnalyticsAlgorithm,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.Team, models.Player, models.AnalyticsShift, models.AnalyticsPlayer]]:
        query = (
            sa.select(models.Team, models.Player, models.AnalyticsShift, models.AnalyticsPlayer)
            .options(
                sa.orm.joinedload(models.Team.tournament).joinedload(models.Tournament.division_grid_version),
                sa.orm.joinedload(models.Team.standings),
                sa.orm.joinedload(models.Team.standings).joinedload(models.Standing.stage_item),
                # PlayerRead.user_id (built by _player_to_pydantic) is resolved from
                # workspace_member.player_id; eager-load it here since models.Player
                # is selected as its own entity, not via a relationship.
                sa.orm.joinedload(models.Player.workspace_member),
            )
            .join(models.Tournament, models.Team.tournament_id == models.Tournament.id)
            .join(models.Player, models.Player.team_id == models.Team.id)
            .join(models.AnalyticsPlayer, models.AnalyticsPlayer.player_id == models.Player.id)
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

    async def get_predicted_places(
        self,
        session: AsyncSession,
        tournament_id: int,
        algorithm_id: int,
    ) -> dict[int, int]:
        """Return ``{team_id: predicted_place}`` for a tournament.

        Derived entirely from the v2 ``analytics.standings_distribution`` rows written
        by the ``Standings MC v2`` Monte-Carlo simulator: ``predicted_place`` is the
        team's ``round(mean_position)`` — the mean finishing position across
        simulations, rounded to the nearest integer place. Independent of the
        ``algorithm_id`` selected in the UI for shifts/points.
        """
        del algorithm_id  # the forecast does not depend on the shift/points algorithm

        predictions: dict[int, int] = {}
        standings_v2_id = await self.algorithms.get_id_by_name(session, _STANDINGS_V2_NAME)
        if standings_v2_id is None:
            return predictions

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
        self,
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
            {int(anomaly.player_id) for anomaly in anomalies if anomaly.source_encounter_id is None}
        )
        encounter_for_player: dict[int, int] = {}
        if unresolved_player_ids:
            discipline = await session.scalar(
                sa.select(models.Tournament.discipline).where(models.Tournament.id == tournament_id)
            )
            matches = match_context(discipline=discipline)
            query = (
                sa.select(
                    models.Player.id.label("player_id"),
                    sa.func.min(matches.c.encounter_id).label("encounter_id"),
                )
                .select_from(models.Player)
                .join(models.EncounterTeam, models.EncounterTeam.team_id == models.Player.team_id)
                .join(
                    models.StatsMatchTeam,
                    models.StatsMatchTeam.encounter_team_id == models.EncounterTeam.id,
                )
                .join(matches, matches.c.id == models.StatsMatchTeam.match_id)
                .where(
                    matches.c.tournament_id == tournament_id,
                    models.Player.id.in_(unresolved_player_ids),
                    models.StatsMatchTeam.source_position.in_((1, 2)),
                )
                .group_by(models.Player.id)
            )
            for pid, encounter_id in (await session.execute(query)).all():
                if pid is None or encounter_id is None:
                    continue
                previous = encounter_for_player.get(int(pid))
                encounter_for_player[int(pid)] = (
                    int(encounter_id) if previous is None else min(previous, int(encounter_id))
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

    async def change_shift(self, session: AsyncSession, player_id: int, shift: int) -> models.AnalyticsPlayer | None:
        """Set the organizer's manual override ``AnalyticsPlayer.shift``; ``None`` when the player has no row."""
        analytics = await self.players.get_by(session, player_id=player_id)
        if analytics is None:
            return None
        await self.players.update_fields(session, analytics, {"shift": shift})
        await session.commit()
        return analytics

    async def get_streaks(
        self, session: AsyncSession, tournament_id: int
    ) -> typing.Sequence[tuple[models.User, str | None, str | None, str, int]]:
        subquery = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.role,
                models.Player.sub_role,
                models.Tournament.discipline,
                models.Standing.overall_position,
            )
            .select_from(models.Player)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
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
                subquery.c.sub_role,
                subquery.c.discipline,
                subquery.c.overall_position,
            )
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(subquery, subquery.c.user_id == models.WorkspaceMember.player_id)
            .join(models.User, models.User.id == subquery.c.user_id)
            .where(
                sa.and_(
                    models.Player.tournament_id == tournament_id,
                )
            )
        )

        result = await session.execute(query)
        return result.all()


analytics_read_service = AnalyticsReadService()
