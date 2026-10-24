"""High-level read flows for the analytics HTTP surface.

Responses are serialised inline with the lightweight Pydantic readers from
:mod:`src.schemas.base`.
"""

from __future__ import annotations

import typing

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, errors, pagination
from shared.disciplines import discipline
from shared.division_grid import DEFAULT_GRID, DivisionGrid, canonical_division_number
from shared.domain.analytics import MATCH_QUALITY_MODEL, PERFORMANCE_MODEL, STANDINGS_MODEL, ModelDeclaration
from shared.repository import (
    AnalyticsAlgorithmRepository,
    AnalyticsAnomalyFeedbackRepository,
    AnalyticsMatchQualityRepository,
    AnalyticsPerformanceRepository,
    AnalyticsPlayerAnomalyRepository,
    AnalyticsStandingsDistributionRepository,
    MLModelArtifactRepository,
)
from shared.schemas.role import RoleRef
from shared.services.division_grid.resolution import resolve_tournament_division
from shared.services.workspace_scope import get_division_grid
from src import schemas
from src.core.analytics_exports import supports_analytics, tournament_discipline
from src.core.config import settings
from src.domain.forecast import predict_player_division

from .read_queries import analytics_read_service

__all__ = (
    "AnalyticsReadFlowsService",
    "flows_service",
)


# ---------------------------------------------------------------------------
# Inline serialisation helpers
# ---------------------------------------------------------------------------


def _user_to_pydantic(user: models.User | None) -> schemas.UserReadMin | None:
    if user is None:
        return None
    # Only read plain columns — relationships (battle_tag/discord/twitch) are
    # not eagerly loaded by the analytics queries and would crash with
    # ``MissingGreenlet`` once the async session is detached.
    return schemas.UserReadMin(
        id=user.id,
        created_at=user.created_at,
        updated_at=user.updated_at,
        name=getattr(user, "name", None),
        avatar_url=getattr(user, "avatar_url", None),
    )


def _tournament_to_pydantic(t: models.Tournament | None) -> schemas.TournamentMin | None:
    if t is None:
        return None
    return schemas.TournamentMin(
        id=t.id,
        created_at=t.created_at,
        updated_at=t.updated_at,
        name=getattr(t, "name", None),
        is_finished=getattr(t, "is_finished", None),
        division_grid_version_id=getattr(t, "division_grid_version_id", None),
    )


def _group_to_pydantic(item) -> schemas.TeamGroupMin | None:
    if item is None:
        return None
    return schemas.TeamGroupMin(id=item.id, name=item.name)


def _resolve_placement(team: models.Team) -> int | None:
    positions = [
        standing.overall_position
        for standing in getattr(team, "standings", []) or []
        if getattr(standing, "overall_position", None) is not None and standing.overall_position > 0
    ]
    return min(positions) if positions else None


def _team_to_pydantic(team: models.Team, *, include_tournament: bool = True) -> schemas.TeamRead:
    return schemas.TeamRead(
        id=team.id,
        created_at=team.created_at,
        updated_at=team.updated_at,
        name=team.name,
        image_url=team.image_url,
        avg_sr=team.avg_sr,
        total_sr=team.total_sr,
        captain_id=team.captain_id,
        tournament_id=team.tournament_id,
        tournament=_tournament_to_pydantic(team.tournament) if include_tournament else None,
        placement=_resolve_placement(team),
        group=next(
            (
                _group_to_pydantic(standing.stage_item)
                for standing in getattr(team, "standings", []) or []
                if getattr(standing, "stage_item", None) is not None
                and getattr(standing.stage_item, "type", None) == enums.StageItemType.GROUP
            ),
            None,
        ),
    )


def _player_to_pydantic(player: models.Player, *, grid: DivisionGrid) -> schemas.PlayerRead:
    # ``user`` is intentionally left as ``None``: the frontend analytics surface
    # reads ``player.name`` directly, and accessing ``player.user`` (or any of its
    # ``battle_tag``/``discord``/``twitch`` relationships) would trip
    # ``MissingGreenlet`` once the async session is detached.
    return schemas.PlayerRead(
        id=player.id,
        created_at=player.created_at,
        updated_at=player.updated_at,
        name=getattr(player, "name", None),
        rank=player.rank,
        division=resolve_tournament_division(player.rank, tournament_grid=grid),
        role=player.role_ref,
        tournament_id=player.tournament_id,
        # The identity anchor is workspace_member.player_id. Callers must
        # eager-load Player.workspace_member on the query that produced ``player``.
        user_id=player.workspace_member.player_id,
        team_id=player.team_id,
        is_newcomer=getattr(player, "is_newcomer", False),
        is_newcomer_role=getattr(player, "is_newcomer_role", False),
        is_substitution=getattr(player, "is_substitution", False),
        related_player_id=getattr(player, "related_player_id", None),
        user=None,
    )


def _anomaly_to_pydantic(
    payload: dict[str, typing.Any],
    *,
    encounter_id: int,
) -> schemas.AnalyticsAnomaly | None:
    player_id = payload.get("player_id")
    if player_id is None:
        return None

    raw_reasons = payload.get("reasons")
    reasons = [str(reason) for reason in raw_reasons] if isinstance(raw_reasons, list) else []
    raw_encounter_id = payload.get("encounter_id", encounter_id)

    try:
        return schemas.AnalyticsAnomaly(
            player_id=int(player_id),
            kind=str(payload.get("kind") or "unknown"),
            score=float(payload.get("score") or 0),
            confidence=(float(payload["confidence"]) if payload.get("confidence") is not None else None),
            reasons=reasons,
            encounter_id=int(raw_encounter_id) if raw_encounter_id is not None else None,
        )
    except (TypeError, ValueError):
        return None


def _build_anomalies_by_player(
    rows: typing.Sequence[tuple[int, list[dict[str, typing.Any]] | None]],
) -> dict[int, list[schemas.AnalyticsAnomaly]]:
    """Flatten legacy encounter-grouped anomaly payloads into a per-player map."""
    anomalies: dict[int, list[schemas.AnalyticsAnomaly]] = {}
    seen: set[tuple[int, str]] = set()
    for encounter_id, flags in rows:
        for flag in flags or []:
            anomaly = _anomaly_to_pydantic(flag, encounter_id=encounter_id)
            if anomaly is None:
                continue
            key = (anomaly.player_id, anomaly.kind)
            if key in seen:
                continue
            seen.add(key)
            anomalies.setdefault(anomaly.player_id, []).append(anomaly)
    return anomalies


def _average(values: typing.Iterable[float]) -> float:
    values_list = list(values)
    if not values_list:
        return 0.0
    return round(sum(values_list) / len(values_list), 4)


class AnalyticsReadFlowsService:
    def __init__(
        self,
        *,
        performance: AnalyticsPerformanceRepository = AnalyticsPerformanceRepository(),
        standings: AnalyticsStandingsDistributionRepository = AnalyticsStandingsDistributionRepository(),
        match_quality: AnalyticsMatchQualityRepository = AnalyticsMatchQualityRepository(),
        player_anomalies: AnalyticsPlayerAnomalyRepository = AnalyticsPlayerAnomalyRepository(),
        feedback: AnalyticsAnomalyFeedbackRepository = AnalyticsAnomalyFeedbackRepository(),
        artifacts: MLModelArtifactRepository = MLModelArtifactRepository(),
        algorithms: AnalyticsAlgorithmRepository = AnalyticsAlgorithmRepository(),
    ) -> None:
        self.performance = performance
        self.standings = standings
        self.match_quality = match_quality
        self.player_anomalies = player_anomalies
        self.feedback = feedback
        self.artifacts = artifacts
        self.algorithms = algorithms

    async def to_pydantic(
        self,
        session: AsyncSession,
        algorithm: models.AnalyticsAlgorithm,
        *,
        has_data: bool | None = None,
    ) -> schemas.AnalyticsAlgorithmRead:
        return schemas.AnalyticsAlgorithmRead(
            id=algorithm.id,
            created_at=algorithm.created_at,
            updated_at=algorithm.updated_at,
            name=algorithm.name,
            has_data=has_data,
        )

    async def get_algorithms(
        self,
        session: AsyncSession,
        params: pagination.PaginationParams,
        *,
        tournament_id: int | None = None,
    ) -> pagination.Paginated[schemas.AnalyticsAlgorithmRead]:
        algorithms = await analytics_read_service.get_algorithms(session)
        ids_with_data: set[int] | None = None
        if tournament_id is not None:
            # The tournament names its game: one that declares no analytics module offers no algorithm, never another
            # game's (Linear, Points and the shift model all run on the module's canonical scale).
            discipline_code = await tournament_discipline(session, tournament_id)
            if discipline_code is not None and not supports_analytics(discipline_code):
                algorithms = []
            ids_with_data = await analytics_read_service.get_algorithm_ids_with_shift_data(session, tournament_id)
        return pagination.Paginated(
            total=len(algorithms),
            results=[
                await self.to_pydantic(
                    session,
                    algorithm,
                    has_data=(algorithm.id in ids_with_data) if ids_with_data is not None else None,
                )
                for algorithm in algorithms
            ],
            page=params.page,
            per_page=params.per_page,
        )

    async def get_algorithm(self, session: AsyncSession, id: int) -> schemas.AnalyticsAlgorithmRead:
        algorithm = await analytics_read_service.get_algorithm(session, id)
        if not algorithm:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="Analytics algorithm not found.")],
            )
        return await self.to_pydantic(session, algorithm)

    async def get_analytics(
        self,
        session: AsyncSession,
        tournament_id: int,
        algorithm_id: int,
        workspace_id: int | None = None,
    ) -> schemas.TournamentAnalytics:
        algorithm = await analytics_read_service.get_algorithm(session, algorithm_id)
        if algorithm is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="Analytics algorithm not found.")],
            )
        discipline_code = await tournament_discipline(session, tournament_id)
        if discipline_code is not None and not supports_analytics(discipline_code):
            # Stored predictions of an algorithm are never served to a tournament of a game that has no module.
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="Analytics algorithm not found.")],
            )

        output: list[schemas.TeamAnalytics] = []
        cache_teams: dict[int, models.Team] = {}
        cache_players: dict[int, list[tuple[models.Player, models.AnalyticsPlayer, models.AnalyticsShift]]] = {}
        cache_teams_wins: dict[int, int] = {}
        cache_teams_losses: dict[int, int] = {}
        cache_teams_manual_shift: dict[int, int] = {}

        data = await analytics_read_service.get_analytics(session, tournament_id, algorithm, workspace_id=workspace_id)
        for team, player, shift, analytics in data:
            cache_teams[team.id] = team
            cache_players.setdefault(team.id, [])
            cache_teams_manual_shift.setdefault(team.id, 0)
            cache_teams_manual_shift[team.id] += analytics.shift_one if analytics.shift_one else 0
            cache_players[team.id].append((player, analytics, shift))
            if team.id not in cache_teams_wins:
                cache_teams_wins[team.id] = analytics.wins
            if team.id not in cache_teams_losses:
                cache_teams_losses[team.id] = analytics.losses

        grid = await get_division_grid(session, workspace_id, tournament_id=tournament_id)
        predicted_places = await analytics_read_service.get_predicted_places(session, tournament_id, algorithm.id)
        anomalies_by_player = _build_anomalies_by_player(
            await analytics_read_service.get_match_quality_anomalies(session, tournament_id, algorithm.id)
        )
        threshold = settings.forecast_confidence_threshold

        # Balancer context: a team's mean canonical division against the field's (the mean over teams), so a roster
        # stronger than the field reads negative. Unranked players carry no division; a team of them has no offset.
        canonical_means: dict[int, float] = {}
        for team_id, players in cache_players.items():
            divisions = [canonical_division_number(grid, player.rank, DEFAULT_GRID) for player, _, _ in players]
            ranked = [division for division in divisions if division is not None]
            if ranked:
                canonical_means[team_id] = sum(ranked) / len(ranked)
        field_mean = sum(canonical_means.values()) / len(canonical_means) if canonical_means else 0.0

        for team_id, team in cache_teams.items():
            players = cache_players[team_id]
            team_read = _team_to_pydantic(team)
            team_mean = canonical_means.get(team_id)
            balancer_shift = round(team_mean - field_mean, 2) if team_mean is not None else 0.0
            manual_shift_points = cache_teams_manual_shift[team_id]
            manual_shift = round(manual_shift_points / 100, 2)
            team_players: list[schemas.PlayerAnalytics] = []

            for player, analytics, shift in players:
                player_read = _player_to_pydantic(player, grid=grid)
                predicted_division, predicted_direction, predicted_delta, confidence = predict_player_division(
                    player.rank, grid, shift.shift, shift.shift_sd, threshold=threshold
                )
                team_players.append(
                    schemas.PlayerAnalytics(
                        **player_read.model_dump(),
                        move_1=analytics.shift_one,
                        move_2=analytics.shift_two,
                        points=shift.shift,
                        shift=analytics.shift,
                        confidence=confidence,
                        effective_evidence=shift.effective_evidence,
                        sample_tournaments=shift.sample_tournaments,
                        sample_matches=shift.sample_matches,
                        log_coverage=shift.log_coverage,
                        predicted_division=predicted_division,
                        predicted_direction=predicted_direction,
                        predicted_delta=predicted_delta,
                        anomalies=anomalies_by_player.get(player.id, []),
                    )
                )

            team_anomalies = [anomaly for player in team_players for anomaly in player.anomalies]
            predicted_place = predicted_places.get(team_id)
            placement_delta = (
                predicted_place - team_read.placement
                if predicted_place is not None and team_read.placement is not None
                else None
            )

            output.append(
                schemas.TeamAnalytics(
                    **team_read.model_dump(exclude={"players"}),
                    wins=cache_teams_wins.get(team_id, 0),
                    losses=cache_teams_losses.get(team_id, 0),
                    predicted_place=predicted_place,
                    placement_delta=placement_delta,
                    avg_confidence=_average(player.confidence for player in team_players),
                    manual_shift_points=manual_shift_points,
                    anomalies=team_anomalies,
                    balancer_shift=balancer_shift,
                    manual_shift=manual_shift,
                    total_shift=-sum(player.predicted_delta for player in team_players),
                    players=team_players,
                )
            )

        placement_deltas = [abs(team.placement_delta) for team in output if team.placement_delta is not None]
        summary = schemas.TournamentAnalyticsSummary(
            total_teams=len(output),
            total_players=sum(len(team.players) for team in output),
            avg_confidence=_average(team.avg_confidence for team in output),
            anomaly_count=sum(len(team.anomalies) for team in output),
            manual_shift_team_count=sum(1 for team in output if team.manual_shift_points != 0),
            newcomer_count=sum(
                1 for team in output for player in team.players if player.is_newcomer or player.is_newcomer_role
            ),
            divergent_team_count=sum(
                1 for team in output if team.placement_delta is not None and abs(team.placement_delta) >= 4
            ),
            avg_placement_delta=_average(float(delta) for delta in placement_deltas),
        )

        return schemas.TournamentAnalytics(
            teams=sorted(output, key=lambda x: ((x.placement or 9999), x.name)),
            teams_wins=cache_teams_wins,
            summary=summary,
        )

    async def change_shift(self, session: AsyncSession, player_id: int, shift: int) -> schemas.PlayerShiftUpdate:
        analytics = await analytics_read_service.change_shift(session, player_id, shift)
        if analytics is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="Player analytics not found.")],
            )
        return schemas.PlayerShiftUpdate(player_id=analytics.player_id, shift=analytics.shift)

    async def get_streaks(self, session: AsyncSession, tournament_id: int) -> list[schemas.PlayerStreak]:
        cache_pos: dict[tuple[int, RoleRef | None], list[int]] = {}
        cache_users: dict[tuple[int, RoleRef | None], schemas.UserReadMin | None] = {}
        output: list[schemas.PlayerStreak] = []
        streaks = await analytics_read_service.get_streaks(session, tournament_id)

        for user, role, sub_role, discipline_code, place in streaks:
            key = (user.id, RoleRef.of(discipline(discipline_code).rated_dimension.code, role, sub_role))
            cache_users.setdefault(key, _user_to_pydantic(user))
            cache_pos.setdefault(key, [])
            if len(cache_pos[key]) < 3:
                cache_pos[key].append(place)

        for key, positions in cache_pos.items():
            if len(positions) < 2:
                continue
            user = cache_users[key]
            if user is None:
                continue
            _, role = key
            current_position = positions[0]
            previous_position = positions[1] if len(positions) > 1 else None
            pre_previous_position = positions[2] if len(positions) > 2 else None
            sum_position = sum(p for p in positions if p is not None)

            output.append(
                schemas.PlayerStreak(
                    user=user,
                    role=role,
                    sum_position=sum_position,
                    current_position=current_position,
                    previous_position=previous_position,
                    pre_previous_position=pre_previous_position,
                )
            )

        return sorted(output, key=lambda x: (x.sum_position, x.user.name or ""))

    async def _owned(
        self,
        session: AsyncSession,
        tournament_id: int,
        declaration: ModelDeclaration | None = None,
        algorithm_id: int | None = None,
    ) -> tuple[bool, int | None]:
        """Whether stored rows of ``tournament_id`` may be served, and the algorithm id to restrict them to.

        The tournament's discipline must declare analytics models (rows preserved from another game's model, or of a
        tournament that does not exist, are never served), and a model read is restricted to the declared algorithm:
        a requested ``algorithm_id`` that names another algorithm serves nothing.
        """
        code = await tournament_discipline(session, tournament_id)
        if code is None or not supports_analytics(code):
            return False, None
        if declaration is None:
            return True, algorithm_id
        declared = await self.algorithms.get_id_by_name(session, declaration.algorithm_name)
        if declared is None or (algorithm_id is not None and algorithm_id != declared):
            return False, None
        return True, declared

    async def list_performance(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        algorithm_id: int | None = None,
    ) -> typing.Sequence[models.AnalyticsPerformance]:
        owned, declared = await self._owned(session, tournament_id, PERFORMANCE_MODEL, algorithm_id)
        if not owned:
            return []
        return await self.performance.list_by_tournament(session, tournament_id, algorithm_id=declared)

    async def list_standings(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        algorithm_id: int | None = None,
    ) -> typing.Sequence[models.AnalyticsStandingsDistribution]:
        owned, declared = await self._owned(session, tournament_id, STANDINGS_MODEL, algorithm_id)
        if not owned:
            return []
        return await self.standings.list_by_tournament(session, tournament_id, algorithm_id=declared)

    async def list_match_quality(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        algorithm_id: int | None = None,
    ) -> list[schemas.MatchQualityRow]:
        owned, declared = await self._owned(session, tournament_id, MATCH_QUALITY_MODEL, algorithm_id)
        if not owned:
            return []
        rows = await self.match_quality.list_by_tournament(session, tournament_id, algorithm_id=declared)
        grouped = dict(
            await analytics_read_service.get_match_quality_anomalies(session, tournament_id, algorithm_id or 0)
        )
        return [
            schemas.MatchQualityRow(
                encounter_id=row.encounter_id,
                algorithm_id=row.algorithm_id,
                competitiveness=row.competitiveness,
                predictability=row.predictability,
                skill_balance=row.skill_balance,
                quality_score=row.quality_score,
                anomaly_flags=grouped.get(row.encounter_id),
            )
            for row in rows
        ]

    async def list_player_anomalies(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        player_id: int | None = None,
        kind: str | None = None,
    ) -> typing.Sequence[models.AnalyticsPlayerAnomaly]:
        if not (await self._owned(session, tournament_id))[0]:
            return []
        return await self.player_anomalies.list_by_tournament(session, tournament_id, player_id=player_id, kind=kind)

    async def list_feedback(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> typing.Sequence[models.AnalyticsAnomalyFeedback]:
        if not (await self._owned(session, tournament_id))[0]:
            return []
        return await self.feedback.list_by_tournament(session, tournament_id)

    async def upsert_feedback(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        player_id: int,
        kind: str,
        verdict: str,
        note: str | None,
        reviewer_user_id: int | None,
    ) -> models.AnalyticsAnomalyFeedback:
        if not (await self._owned(session, tournament_id))[0]:  # same gate as list_feedback: no analytics, no feedback
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="Analytics is not available for this tournament.")],
            )
        existing = await self.feedback.get_by_key(
            session,
            tournament_id=tournament_id,
            player_id=player_id,
            kind=kind,
        )
        if existing is not None:
            await self.feedback.update_fields(
                session,
                existing,
                {
                    "verdict": verdict,
                    "note": note,
                    "reviewer_user_id": reviewer_user_id,
                },
            )
            return existing
        row = models.AnalyticsAnomalyFeedback(
            tournament_id=tournament_id,
            player_id=player_id,
            kind=kind,
            verdict=verdict,
            reviewer_user_id=reviewer_user_id,
            note=note,
        )
        await self.feedback.create(session, row)
        return row

    async def get_explanation(
        self,
        session: AsyncSession,
        player_id: int,
        tournament_id: int,
        *,
        algorithm_id: int | None = None,
    ) -> schemas.ExplanationRow | None:
        owned, declared = await self._owned(session, tournament_id, PERFORMANCE_MODEL, algorithm_id)
        if not owned:
            return None
        row = await self.performance.get_for_player(
            session,
            player_id=player_id,
            tournament_id=tournament_id,
            algorithm_id=declared,
        )
        if row is None or not row.contributions:
            return None
        return schemas.ExplanationRow(
            algorithm_id=row.algorithm_id,
            entity_id=row.player_id,
            entity_kind="player",
            tournament_id=row.tournament_id,
            base_value=row.base_value or 0.0,
            contributions=row.contributions,
        )

    async def list_artifacts(
        self,
        session: AsyncSession,
        *,
        model_kind: str | None = None,
        active_only: bool = False,
    ) -> list[schemas.MLArtifactRow]:
        rows = await self.artifacts.list_filtered(session, model_kind=model_kind, active_only=active_only)
        return [
            schemas.MLArtifactRow(
                **{field: getattr(row, field) for field in schemas.MLArtifactRow.model_fields if field != "role"},
                role=(
                    RoleRef(dimension=row.role_row.dimension.code, role=row.role_row.code)
                    if row.role_row is not None
                    else None
                ),
            )
            for row in rows
        ]


flows_service = AnalyticsReadFlowsService()
