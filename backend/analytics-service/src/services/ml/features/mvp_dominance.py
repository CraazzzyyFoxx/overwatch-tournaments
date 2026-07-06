"""Raw match-log MVP dominance.

Performance v2 ``impact`` measures *outperformance vs the pre-match win
expectation* — it deliberately gives little credit to a strong player who wins
"as expected" on a favoured team. That misses a textbook under-ranked profile:
a player who consistently tops the raw per-match scoreboard (the match log's
``Performance`` rank, i.e. "MVP place") well above their division.

This module derives that raw-dominance signal straight from the match log:

    mvp_dominance = mean over the player's tournament matches of
                    (lobby_size - performance_rank) / (lobby_size - 1)

``performance_rank`` is the parser's per-match MVP position (1 = best); so the
score is 1.0 for a player who is always match MVP, ~0.5 for a median player and
0.0 for a player who is always last. It is consumed by the smurf detector (flag
a consistent raw dominator) and as a secondary lift for the Shift v2 individual
modifier (so such a player actually moves, not only gets flagged).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import LogStatsName
from src import models

__all__ = ("compute_mvp_dominance", "dominance_from_perf_ranks")


def dominance_from_perf_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Reduce per-match MVP ranks to per-player dominance.

    Input columns: ``player_id``, ``match_id``, ``perf_rank`` (1 = match MVP).
    Returns ``player_id``, ``mvp_dominance`` (∈ [0, 1]), ``mvp_matches``.
    """
    cols = ["player_id", "mvp_dominance", "mvp_matches"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    frame = df.copy()
    frame["perf_rank"] = pd.to_numeric(frame["perf_rank"], errors="coerce")
    frame = frame.dropna(subset=["player_id", "match_id", "perf_rank"])
    if frame.empty:
        return pd.DataFrame(columns=cols)

    lobby_n = frame.groupby("match_id")["player_id"].transform("nunique")
    # 1.0 at rank 1 (MVP), 0.0 at the bottom; single-player lobbies are neutral.
    frame["dominance"] = np.where(
        lobby_n > 1,
        ((lobby_n - frame["perf_rank"]) / (lobby_n - 1)).clip(0.0, 1.0),
        0.5,
    )
    out = (
        frame.groupby("player_id")
        .agg(mvp_dominance=("dominance", "mean"), mvp_matches=("match_id", "nunique"))
        .reset_index()
    )
    out["player_id"] = out["player_id"].astype(int)
    return out[cols]


async def compute_mvp_dominance(
    session: AsyncSession,
    tournament_id: int,
) -> pd.DataFrame:
    """Per-player raw MVP dominance for one tournament (keyed by ``player_id``).

    Reads the parser's per-match ``Performance`` rank (round 0, hero-agnostic),
    scoped to the tournament via the encounter, and maps each match participant
    back to their tournament ``player_id``. Empty when no match log exists.
    """
    query = (
        sa.select(
            models.Player.id.label("player_id"),
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.value.label("perf_rank"),
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.tournament_id == tournament_id,
            ),
        )
        .join(
            models.WorkspaceMember,
            sa.and_(
                models.WorkspaceMember.id == models.Player.workspace_member_id,
                models.WorkspaceMember.player_id == models.MatchStatistics.user_id,
            ),
        )
        .where(
            models.Encounter.tournament_id == tournament_id,
            models.Player.is_substitution.is_(False),
            models.MatchStatistics.name == LogStatsName.Performance,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
        )
    )
    df = pd.DataFrame((await session.execute(query)).mappings().all())
    return dominance_from_perf_ranks(df)
