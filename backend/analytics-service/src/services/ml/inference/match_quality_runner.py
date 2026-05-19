"""Match Quality v1 inference writer.

Match Quality remains an encounter-level score. Player anomalies are computed
by the unified player-signal runner and copied onto ``analytics.match_quality``
only as a compatibility surface for legacy consumers.
"""

from __future__ import annotations

import logging

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..features.standings_features import build_standings_training_frame
from ..models.match_quality import compute_match_quality
from ..training.orchestrator import MATCH_QUALITY_ALGORITHM_NAME
from ..training.registry import ensure_algorithm

logger = logging.getLogger(__name__)

__all__ = ("run_match_quality_for_tournament",)


async def _match_scores(session: AsyncSession, tournament_id: int) -> pd.DataFrame:
    """Return ``(encounter_id, home_score, away_score)`` per ``Match``."""
    query = (
        sa.select(
            models.Match.encounter_id.label("encounter_id"),
            models.Match.home_score.label("home_score"),
            models.Match.away_score.label("away_score"),
        )
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .where(models.Encounter.tournament_id == tournament_id)
        .order_by(models.Match.encounter_id, models.Match.id)
    )
    result = await session.execute(query)
    return pd.DataFrame(result.mappings().all())


async def _standings_p_home(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
) -> pd.DataFrame:
    """Return the encounter feature frame used for Match Quality scoring."""
    return await build_standings_training_frame(
        session,
        [tournament_id],
        workspace_id=workspace_id,
    )


async def _player_anomalies(
    session: AsyncSession,
    tournament_id: int,
) -> list[models.AnalyticsPlayerAnomaly]:
    result = await session.execute(
        sa.select(models.AnalyticsPlayerAnomaly).where(
            models.AnalyticsPlayerAnomaly.tournament_id == tournament_id
        )
    )
    return list(result.scalars().all())


async def _first_encounter_by_player(
    session: AsyncSession,
    tournament_id: int,
) -> dict[int, int]:
    home_query = (
        sa.select(
            models.Player.id.label("player_id"),
            sa.func.min(models.Match.encounter_id).label("encounter_id"),
        )
        .join(models.Match, models.Match.home_team_id == models.Player.team_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .where(models.Encounter.tournament_id == tournament_id)
        .group_by(models.Player.id)
    )
    away_query = (
        sa.select(
            models.Player.id.label("player_id"),
            sa.func.min(models.Match.encounter_id).label("encounter_id"),
        )
        .join(models.Match, models.Match.away_team_id == models.Player.team_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .where(models.Encounter.tournament_id == tournament_id)
        .group_by(models.Player.id)
    )

    encounter_for_player: dict[int, int] = {}
    for pid, enc in (await session.execute(home_query)).all() + (
        await session.execute(away_query)
    ).all():
        if pid is None or enc is None:
            continue
        prev = encounter_for_player.get(int(pid))
        encounter_for_player[int(pid)] = int(enc) if prev is None else min(prev, int(enc))
    return encounter_for_player


async def run_match_quality_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
) -> int:
    """Compute Match Quality rows and attach compatibility anomaly payloads."""
    algorithm = await ensure_algorithm(session, MATCH_QUALITY_ALGORITHM_NAME)

    encounters = await _standings_p_home(
        session,
        tournament_id,
        workspace_id=workspace_id,
    )
    if encounters.empty:
        logger.info(
            "No encounters for tournament_id=%d (workspace_id=%s); nothing to score",
            tournament_id,
            workspace_id,
        )
        return 0

    encounters = encounters.copy()
    if "p_home_wins" not in encounters.columns:
        encounters["p_home_wins"] = None

    quality = compute_match_quality(
        encounters,
        await _match_scores(session, tournament_id),
    )
    if quality.empty:
        return 0

    encounter_for_player = await _first_encounter_by_player(session, tournament_id)
    fallback_encounter = (
        int(encounters["encounter_id"].astype(int).iloc[0])
        if not encounters.empty
        else None
    )
    by_encounter_anomalies: dict[int, list[dict]] = {}
    seen: set[tuple[int, str, int | None]] = set()

    for anomaly in await _player_anomalies(session, tournament_id):
        source_encounter_id = (
            int(anomaly.source_encounter_id)
            if anomaly.source_encounter_id is not None
            else None
        )
        key = (int(anomaly.player_id), str(anomaly.kind), source_encounter_id)
        if key in seen:
            continue
        seen.add(key)
        encounter_id = (
            source_encounter_id
            or encounter_for_player.get(int(anomaly.player_id))
            or fallback_encounter
        )
        if encounter_id is None:
            continue
        by_encounter_anomalies.setdefault(int(encounter_id), []).append(
            {
                "player_id": int(anomaly.player_id),
                "kind": str(anomaly.kind),
                "score": float(anomaly.score),
                "confidence": float(anomaly.confidence),
                "reasons": list(anomaly.reasons or []),
                "evidence": anomaly.evidence or None,
                "encounter_id": int(encounter_id),
            }
        )

    rows = []
    for _, row in quality.iterrows():
        encounter_id = int(row["encounter_id"])
        rows.append(
            {
                "encounter_id": encounter_id,
                "algorithm_id": algorithm.id,
                "competitiveness": float(row["competitiveness"]),
                "predictability": float(row["predictability"]),
                "skill_balance": float(row["skill_balance"]),
                "quality_score": float(row["quality_score"]),
                "anomaly_flags": by_encounter_anomalies.get(encounter_id) or None,
            }
        )

    await session.execute(
        sa.delete(models.AnalyticsMatchQuality).where(
            models.AnalyticsMatchQuality.encounter_id.in_(
                [int(e) for e in encounters["encounter_id"].astype(int).unique()]
            ),
            models.AnalyticsMatchQuality.algorithm_id == algorithm.id,
        )
    )
    if rows:
        await session.execute(sa.insert(models.AnalyticsMatchQuality), rows)
    await session.commit()
    return len(rows)
