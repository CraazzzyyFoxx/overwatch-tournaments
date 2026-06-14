"""Unified player-signal inference runner.

Writes tournament-level and encounter-level anomaly signals into
``analytics.player_anomaly``. Match Quality keeps a denormalised copy only for
legacy consumers; this table is the source of truth.
"""

from __future__ import annotations

import logging
import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..features.extractors import extract_round_residuals
from ..features.player_profile import load_player_signal_profile
from ..models.anomalies import (
    detect_sandbags,
    detect_smurfs,
    detect_throws,
    detect_trolls,
)

logger = logging.getLogger(__name__)

__all__ = ("run_player_anomalies_for_tournament",)


def _normalise_flag(
    flag: dict[str, typing.Any],
) -> dict[str, typing.Any] | None:
    player_id = flag.get("player_id")
    kind = flag.get("kind")
    if player_id is None or kind is None:
        return None

    reasons = flag.get("reasons")
    evidence = flag.get("evidence")
    return {
        "player_id": int(player_id),
        "kind": str(kind),
        "score": float(flag.get("score") or 0.0),
        "confidence": float(flag.get("confidence") or 0.0),
        "reasons": [str(reason) for reason in reasons] if isinstance(reasons, list) else [],
        "evidence": evidence if isinstance(evidence, dict) else None,
        "source_encounter_id": (
            int(flag["encounter_id"])
            if flag.get("encounter_id") is not None
            else None
        ),
    }


async def run_player_anomalies_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
) -> int:
    """Compute and persist the unified player anomaly set for a tournament."""
    profile = await load_player_signal_profile(
        session,
        tournament_id,
        workspace_id=workspace_id,
    )
    flags: list[dict[str, typing.Any]] = []
    if not profile.empty:
        flags.extend(detect_smurfs(profile))
        flags.extend(detect_trolls(profile))
        flags.extend(detect_sandbags(profile))

    round_residuals = await extract_round_residuals(
        session,
        tournament_id,
        workspace_id=workspace_id,
    )
    if not round_residuals.empty:
        flags.extend(detect_throws(round_residuals))

    rows: list[dict[str, typing.Any]] = []
    seen: set[tuple[int, str, int | None]] = set()
    for flag in flags:
        normalised = _normalise_flag(flag)
        if normalised is None:
            continue
        key = (
            normalised["player_id"],
            normalised["kind"],
            normalised["source_encounter_id"],
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "tournament_id": tournament_id,
                **normalised,
            }
        )

    await session.execute(
        sa.delete(models.AnalyticsPlayerAnomaly).where(
            models.AnalyticsPlayerAnomaly.tournament_id == tournament_id
        )
    )
    if rows:
        await session.execute(sa.insert(models.AnalyticsPlayerAnomaly), rows)
    await session.commit()
    logger.info(
        "Player anomaly runner wrote %d rows for tournament_id=%d",
        len(rows),
        tournament_id,
    )
    return len(rows)
