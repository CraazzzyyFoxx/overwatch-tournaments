"""Read-only evaluation of the shift methods on the next tournament's encounter outcomes.

A shift claims a player belongs elsewhere on the ladder; the check is whether the level it implies predicts who wins
the encounters of the player's next tournament. For every tournament T′ in scope (non-hidden, one discipline, optional
workspace, chronological ``(coalesce(start_date, created_at), id)``) and every duel encounter of T′ — exactly two active
seats, both placed, placements differ, both seats with a roster — each roster player (non-substitute, ranked at T′)
gets a level per method, in canonical-ladder divisions (lower = stronger):

- ``organizer``: the division of the player's rank at T′;
- ``no_moves``: the division of the rank at T_p, the latest earlier tournament of the same workspace where the
  player's (user, role) was ranked; without a T_p every method falls back to the organizer level;
- an algorithm: ``no_moves`` minus its stored ``shift`` at (T_p, the player's slot there); no stored row → no move.

Team strength is the mean level, Δ = home − away and P(home wins) = σ(−k·Δ), with k ≥ 0 fitted per method by maximum
likelihood over every evaluated encounter. Only SELECTs are issued.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.services.workspace_scope import workspace_filter
from src.core.analytics_exports import analytics_exports, tournament_discipline
from src.domain.ratings import LINEAR, OPENSKILL, POINTS

from .canonical_division import load_source_grids

__all__ = ("EvaluationFrame", "evaluate_shift_methods", "format_table", "load_evaluation_frame", "score_methods")

ORGANIZER = "organizer"
NO_MOVES = "no_moves"
#: A method that separates every outcome perfectly would drive k to infinity.
K_MAX = 50.0
_ROLE_KEY = ["workspace_id", "user_id", "role"]


@dataclass(frozen=True)
class EvaluationFrame:
    tournament_ids: tuple[int, ...]
    #: One row per evaluated player slot, indexed by its T′ ``player_id``: ``team_id`` plus one level column per method.
    levels: pd.DataFrame
    #: Same index: per algorithm, whether the level came from a stored row at (T_p, slot).
    stored: pd.DataFrame
    #: One row per evaluated duel: ``home_team_id``, ``away_team_id``, ``home_won``.
    encounters: pd.DataFrame


async def _scoped_tournaments(
    session: AsyncSession,
    *,
    discipline: str,
    workspace_id: int | None,
    from_tournament_id: int | None,
    to_tournament_id: int | None,
) -> tuple[pd.DataFrame, list[int]]:
    """The discipline's visible tournaments through ``to`` in chronological order, and the evaluated ``from..to``."""
    chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
    result = await session.execute(
        sa.select(
            models.Tournament.id.label("tournament_id"),
            models.Tournament.workspace_id,
            models.Tournament.division_grid_version_id.label("version_id"),
        )
        .where(
            models.Tournament.discipline == discipline,
            models.Tournament.is_hidden.is_(False),
            *workspace_filter(workspace_id),
        )
        .order_by(chrono, models.Tournament.id)
    )
    tournaments = pd.DataFrame(result.mappings().all(), columns=["tournament_id", "workspace_id", "version_id"])
    ids = [int(tid) for tid in tournaments["tournament_id"]]

    def position(tournament_id: int | None, default: int) -> int:
        if tournament_id is None:
            return default
        if tournament_id not in ids:
            raise ValueError(f"tournament {tournament_id} is not a visible {discipline} tournament in this scope")
        return ids.index(tournament_id)

    start, end = position(from_tournament_id, 0), position(to_tournament_id, len(ids) - 1)
    return tournaments.iloc[: end + 1].assign(order=range(end + 1)), ids[start : end + 1]


async def load_evaluation_frame(
    session: AsyncSession,
    *,
    discipline: str,
    workspace_id: int | None = None,
    from_tournament_id: int | None = None,
    to_tournament_id: int | None = None,
) -> EvaluationFrame:
    exports = analytics_exports(discipline)
    algorithms = (POINTS, LINEAR, OPENSKILL, exports.MODELS["shift"].algorithm_name)
    methods = [ORGANIZER, NO_MOVES, *algorithms]
    tournaments, evaluated = await _scoped_tournaments(
        session,
        discipline=discipline,
        workspace_id=workspace_id,
        from_tournament_id=from_tournament_id,
        to_tournament_id=to_tournament_id,
    )
    empty = EvaluationFrame(
        tuple(evaluated),
        pd.DataFrame(columns=["team_id", *methods]),
        pd.DataFrame(columns=list(algorithms), dtype=bool),
        pd.DataFrame(columns=["home_team_id", "away_team_id", "home_won"]),
    )
    if not evaluated:
        return empty

    result = await session.execute(
        sa.select(
            models.Player.id.label("player_id"),
            models.Player.tournament_id,
            models.Player.team_id,
            models.WorkspaceMember.player_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.rank,
        )
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(
            models.Player.tournament_id.in_([int(tid) for tid in tournaments["tournament_id"]]),
            models.Player.is_substitution.is_(False),
            models.Player.rank.is_not(None),
        )
    )
    players = pd.DataFrame(
        result.mappings().all(), columns=["player_id", "tournament_id", "team_id", "user_id", "role", "rank"]
    ).merge(tournaments, on="tournament_id")
    grids = await load_source_grids(session, players["version_id"].dropna().unique())
    exports.assign_canonical_division(players, grids, rank_col="rank")
    ranked = players[players["div"].notna()].sort_values([*_ROLE_KEY, "order", "player_id"])

    # T_p: the previous ranked tournament of the same (workspace, user, role), in tournament start order.
    chain = ranked.drop_duplicates([*_ROLE_KEY, "tournament_id"], keep="last")
    by_role = chain.groupby(_ROLE_KEY, sort=False)
    chain = chain.assign(
        prev_tournament_id=by_role["tournament_id"].shift(1),
        prev_player_id=by_role["player_id"].shift(1),
        prev_div=by_role["div"].shift(1),
    )
    slots = ranked[ranked["tournament_id"].isin(evaluated)].merge(
        chain[[*_ROLE_KEY, "tournament_id", "prev_tournament_id", "prev_player_id", "prev_div"]],
        on=[*_ROLE_KEY, "tournament_id"],
        how="left",
        validate="many_to_one",
    )

    encounters = await _duels(session, evaluated, rostered={int(team) for team in slots["team_id"]})
    if encounters.empty:
        return empty
    playing = set(encounters["home_team_id"]) | set(encounters["away_team_id"])
    slots = slots[slots["team_id"].isin(playing)].set_index("player_id")

    shifts = await _stored_shifts(session, algorithms, slots["prev_tournament_id"].dropna().astype(int).unique())
    no_moves = slots["prev_div"].fillna(slots["div"])
    levels = pd.DataFrame({"team_id": slots["team_id"].astype(int), ORGANIZER: slots["div"], NO_MOVES: no_moves})
    stored = pd.DataFrame(index=slots.index)
    previous = list(zip(slots["prev_tournament_id"], slots["prev_player_id"], strict=True))
    for name in algorithms:
        shift = pd.Series(
            [None if pd.isna(tid) else shifts.get((name, int(tid), int(pid))) for tid, pid in previous],
            index=slots.index,
            dtype=float,
        )
        levels[name] = no_moves - shift.fillna(0.0)
        stored[name] = shift.notna()
    return EvaluationFrame(tuple(evaluated), levels, stored, encounters)


async def _duels(session: AsyncSession, tournament_ids: list[int], *, rostered: set[int]) -> pd.DataFrame:
    """Encounters with exactly two active seats, both placed differently, both seats' teams with a roster."""
    result = await session.execute(
        sa.select(
            models.EncounterTeam.encounter_id,
            models.EncounterTeam.slot,
            models.EncounterTeam.team_id,
            models.EncounterTeam.placement,
        )
        .join(models.Encounter, models.Encounter.id == models.EncounterTeam.encounter_id)
        .where(models.Encounter.tournament_id.in_(tournament_ids), models.EncounterTeam.active.is_(True))
    )
    seats = pd.DataFrame(result.mappings().all(), columns=["encounter_id", "slot", "team_id", "placement"])
    seats = seats[seats.groupby("encounter_id")["slot"].transform("size") == 2].sort_values(["encounter_id", "slot"])
    home = seats.drop_duplicates("encounter_id", keep="first").set_index("encounter_id")
    away = seats.drop_duplicates("encounter_id", keep="last").set_index("encounter_id")
    duels = pd.DataFrame(
        {
            "home_team_id": home["team_id"],
            "away_team_id": away["team_id"],
            "home_placement": home["placement"],
            "away_placement": away["placement"],
        }
    ).dropna()
    duels = duels[
        (duels["home_placement"] != duels["away_placement"])
        & duels["home_team_id"].astype(int).isin(rostered)
        & duels["away_team_id"].astype(int).isin(rostered)
    ]
    return pd.DataFrame(
        {
            "home_team_id": duels["home_team_id"].astype(int),
            "away_team_id": duels["away_team_id"].astype(int),
            "home_won": duels["home_placement"] < duels["away_placement"],
        }
    ).reset_index(drop=True)


async def _stored_shifts(
    session: AsyncSession, algorithms: typing.Sequence[str], tournament_ids: typing.Iterable[int]
) -> dict[tuple[str, int, int], float]:
    """``{(algorithm, tournament_id, player_id): shift}`` of the named algorithms' rows at those tournaments."""
    ids = [int(tid) for tid in tournament_ids]
    if not ids:
        return {}
    result = await session.execute(
        sa.select(
            models.AnalyticsAlgorithm.name,
            models.AnalyticsShift.tournament_id,
            models.AnalyticsShift.player_id,
            models.AnalyticsShift.shift,
        )
        .join(models.AnalyticsAlgorithm, models.AnalyticsAlgorithm.id == models.AnalyticsShift.algorithm_id)
        .where(models.AnalyticsAlgorithm.name.in_(algorithms), models.AnalyticsShift.tournament_id.in_(ids))
    )
    return {(name, int(tid), int(pid)): float(shift) for name, tid, pid, shift in result.all()}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def _fit_k(delta: np.ndarray, home_won: np.ndarray) -> float:
    """Maximum-likelihood ``k ≥ 0`` of ``P(home wins) = σ(−k·Δ)``.

    The log-likelihood is concave in k, so its derivative ``Σ (y − σ(k·z))·z`` (z = −Δ) falls monotonically: bisect it.
    """
    z = -delta

    def slope(k: float) -> float:
        return float(np.sum((home_won - _sigmoid(k * z)) * z))

    if slope(0.0) <= 0.0:
        return 0.0
    if slope(K_MAX) >= 0.0:
        return K_MAX
    lo, hi = 0.0, K_MAX
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if slope(mid) > 0.0 else (lo, mid)
    return 0.5 * (lo + hi)


def _auc(predicted: np.ndarray, home_won: np.ndarray) -> float | None:
    """Rank AUC (ties count half); ``None`` when only one outcome occurs."""
    positives = home_won == 1.0
    n_pos, n_neg = int(positives.sum()), int((~positives).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = pd.Series(predicted).rank().to_numpy()
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def score_methods(frame: EvaluationFrame) -> list[dict[str, typing.Any]]:
    """Per method: encounters, coverage, k, log-loss, Brier, AUC; best (lowest log-loss) first."""
    home_won = frame.encounters["home_won"].to_numpy(dtype=float)
    scores: list[dict[str, typing.Any]] = []
    for method in frame.levels.columns.drop("team_id"):
        coverage = float(frame.stored[method].mean()) if method in frame.stored and len(frame.stored) else None
        entry: dict[str, typing.Any] = {"method": method, "n_encounters": len(home_won), "coverage": coverage}
        if not len(home_won):
            scores.append(entry | {"k": None, "log_loss": None, "brier": None, "auc": None})
            continue
        strength = frame.levels.groupby("team_id")[method].mean()
        delta = strength.reindex(frame.encounters["home_team_id"]).to_numpy(dtype=float) - strength.reindex(
            frame.encounters["away_team_id"]
        ).to_numpy(dtype=float)
        k = _fit_k(delta, home_won)
        p = np.clip(_sigmoid(-k * delta), 1e-15, 1 - 1e-15)
        scores.append(
            entry
            | {
                "k": k,
                "log_loss": float(-np.mean(home_won * np.log(p) + (1 - home_won) * np.log(1 - p))),
                "brier": float(np.mean((p - home_won) ** 2)),
                "auc": _auc(p, home_won),
            }
        )
    return sorted(scores, key=lambda s: (s["log_loss"] is None, s["log_loss"] or 0.0))


async def evaluate_shift_methods(
    session: AsyncSession,
    *,
    discipline: str | None = None,
    workspace_id: int | None = None,
    from_tournament_id: int | None = None,
    to_tournament_id: int | None = None,
) -> dict[str, typing.Any]:
    """Score every shift method on T′ encounters from ``from`` to ``to``; the tournaments own the discipline.

    An explicit ``discipline`` contradicting either bound is rejected; without bounds it must be named.
    """
    for tournament_id in (to_tournament_id, from_tournament_id):
        if tournament_id is not None:
            owner = await tournament_discipline(session, tournament_id, explicit=discipline)
            if owner is None:
                raise LookupError(f"tournament {tournament_id} not found")
            discipline = owner
    if discipline is None:
        raise ValueError("an evaluation without --from/--to must name its discipline")
    frame = await load_evaluation_frame(
        session,
        discipline=discipline,
        workspace_id=workspace_id,
        from_tournament_id=from_tournament_id,
        to_tournament_id=to_tournament_id,
    )
    return {
        "discipline": discipline,
        "workspace_id": workspace_id,
        "tournament_ids": list(frame.tournament_ids),
        "methods": score_methods(frame),
    }


def format_table(report: dict[str, typing.Any]) -> str:
    def cell(value: typing.Any) -> str:
        return "-" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)

    columns = ("method", "n_encounters", "coverage", "k", "log_loss", "brier", "auc")
    rows = [columns, *([cell(entry[c]) for c in columns] for entry in report["methods"])]
    widths = [max(len(row[i]) for row in rows) for i in range(len(columns))]
    return "\n".join("  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)) for row in rows)
