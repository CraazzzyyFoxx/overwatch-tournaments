"""Fit the ``impact_v2`` weights against map wins and gate them (design R2.Q2, R3.Q8, R4).

Usage::

    cd backend/stats-service && uv run python fit_impact_weights.py [--since-days 365] [--max-maps 3000] [--write]

Read-only and bounded: one ``READ ONLY`` transaction with a statement timeout, reading only the ``--max-maps`` most
recent maps of the window. Per role and feature, a team's exposure is the playtime-weighted sum of its stints'
winsorised z-scores (map baselines from the training split); a ridge-regularised logistic regression on
``home − away`` exposure predicts the home win of decisive maps and is shrunk towards the v1 weights. The ridge λ is
the smallest one on the grid that leaves every v1 weight's sign intact (R4.Q1): the contributions the tooltip shows
keep their meaning. The last 20 % of maps (by time) are held out for the acceptance checks; ``--write`` rewrites
``shared/core/impact_weights.py`` only when every check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from shared.core.impact import HERO_BASELINE_MIN_ROWS, IMPACT_FEATURES, IMPACT_ROLES, PRIOR_WEIGHTS
from shared.disciplines.overwatch import impact
from shared.disciplines.overwatch.baseline_rows import build_baseline_rows

HOLDOUT_SHARE = 0.2
LAMBDAS = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0)
ROLE_SHARE_TOLERANCE = 0.05
#: Hero stints scored against the baselines they were built from must sit this close to their role (R4.Q2).
HERO_FIT_TOLERANCE = 0.05
DEFAULT_MAX_MAPS = 3000
STATEMENT_TIMEOUT = "120s"
WEIGHTS_FILE = pathlib.Path(__file__).resolve().parents[1] / "shared" / "core" / "impact_weights.py"
_UNIT = {role: dict.fromkeys(IMPACT_FEATURES, 1.0) for role in IMPACT_ROLES}
_COLUMNS = [(role, feature) for role in IMPACT_ROLES for feature in IMPACT_FEATURES]


def exposures(stints: pd.DataFrame, baselines: impact.BaselineSet) -> pd.DataFrame:
    """Per ``(match_id, team_id)``: Σ over the team's classed stints of ``seconds / map seconds · z`` per (role, feature).

    ``baselines`` must carry no role scale, so the unit-weight terms are the raw winsorised z-scores.
    """
    terms, _, _ = impact.feature_terms(stints, baselines, _UNIT)
    longest = stints.groupby("match_id")["seconds"].transform("max").to_numpy()
    weight = stints["seconds"].to_numpy() / longest
    frame = pd.DataFrame(terms * weight[:, None], columns=list(IMPACT_FEATURES), index=stints.index)
    frame[["match_id", "team_id", "role"]] = stints[["match_id", "team_id", "role"]]
    frame = frame[frame["role"].notna()]
    wide = frame.groupby(["match_id", "team_id", "role"])[list(IMPACT_FEATURES)].sum().unstack("role", fill_value=0.0)
    wide = wide.swaplevel(axis=1).reindex(columns=pd.MultiIndex.from_tuples(_COLUMNS), fill_value=0.0)
    return wide


def design(exposure: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``home − away`` exposure rows, home-win labels and match ids for the decisive maps present in both frames."""
    rows, labels, matches = [], [], []
    for match in outcomes.itertuples(index=False):
        home, away = (match.match_id, match.home_team_id), (match.match_id, match.away_team_id)
        if home in exposure.index and away in exposure.index:
            rows.append(exposure.loc[home].to_numpy() - exposure.loc[away].to_numpy())
            labels.append(1.0 if match.home_won else 0.0)
            matches.append(match.match_id)
    return np.asarray(rows).reshape(-1, len(_COLUMNS)), np.asarray(labels), np.asarray(matches)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, -z))


def _objective(x: np.ndarray, y: np.ndarray, w: np.ndarray, prior: np.ndarray, lam: float) -> float:
    z = x @ w
    return float(np.sum(np.logaddexp(0.0, z) - y * z) + lam * np.sum((w - prior) ** 2))


def ridge_logistic(x: np.ndarray, y: np.ndarray, prior: np.ndarray, lam: float, iterations: int = 100) -> np.ndarray:
    """Damped Newton for ``Σ logloss(x·w) + lam·|w − prior|²`` from ``w = 0``.

    No intercept: the home/away difference is symmetric. Backtracking halves a step until the objective drops.
    """
    w = np.zeros(x.shape[1])
    current = _objective(x, y, w, prior, lam)
    for _ in range(iterations):
        p = _sigmoid(x @ w)
        gradient = x.T @ (p - y) + 2.0 * lam * (w - prior)
        hessian = (x * (p * (1.0 - p))[:, None]).T @ x + 2.0 * lam * np.eye(len(w))
        step = np.linalg.lstsq(hessian, gradient, rcond=None)[0]
        size = 1.0
        while size > 1e-6:
            candidate = _objective(x, y, w - size * step, prior, lam)
            if candidate <= current:
                break
            size /= 2.0
        w -= size * step
        improvement, current = current - candidate, candidate
        if np.max(np.abs(size * step)) < 1e-9 or improvement < 1e-12:
            break
    return w


def auc(score: np.ndarray, y: np.ndarray) -> float:
    """Mann–Whitney AUC; ties count half."""
    ranks = pd.Series(score).rank(method="average").to_numpy()
    positives = y == 1.0
    n_pos, n_neg = int(positives.sum()), int((~positives).sum())
    if not n_pos or not n_neg:
        return float("nan")
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


@dataclass(frozen=True)
class Fit:
    weights: dict[str, dict[str, float]]
    lam: float
    scale: float
    train_maps: int


def fit_weights(x: np.ndarray, y: np.ndarray) -> Fit:
    """Scale the prior to log-odds, then take the smallest grid λ whose fit flips no v1 weight's sign (R4.Q1).

    Features the prior leaves at 0 may take either sign. As λ grows the fit tends to the prior, so the grid's top
    normally qualifies; when even it flips a sign the fit is refused rather than shipped with misleading contributions.
    """
    prior = np.asarray([PRIOR_WEIGHTS[feature] for _, feature in _COLUMNS])
    scale = float(ridge_logistic((x @ prior)[:, None], y, np.ones(1), 1e-6)[0])
    if scale <= 0.0:
        raise RuntimeError(f"The v1 composite does not predict wins (scale {scale:.3f}); refusing to fit around it")
    signed = prior != 0.0
    for lam in LAMBDAS:
        w = ridge_logistic(x, y, scale * prior, lam) / scale
        if np.all(np.sign(w[signed]) == np.sign(prior[signed])):
            break
    else:
        raise RuntimeError(f"Every λ up to {LAMBDAS[-1]} flips a v1 weight's sign; refusing to write")
    weights = {role: {} for role in IMPACT_ROLES}
    for (role, feature), value in zip(_COLUMNS, w, strict=True):
        weights[role][feature] = round(float(value), 4)
    return Fit(weights, lam, scale, len(y))


def hero_deviations(
    stints: pd.DataFrame, baselines: impact.BaselineSet, weights: dict[str, dict[str, float]]
) -> dict[int, float]:
    """Per hero with ``HERO_BASELINE_MIN_ROWS`` stints of ≥ 3 min: its mean standardised composite minus its role's, in
    units of the role's sd."""
    base = stints[(stints["role"].notna()) & (stints["seconds"] >= 180.0)]
    _, c_hat, _ = impact.feature_terms(base, baselines, weights)
    frame = pd.DataFrame({"hero": base["hero"].to_numpy(), "role": base["role"].to_numpy(), "c": c_hat})
    role_stats = frame.groupby("role")["c"].agg(["mean", "std"])
    out = {}
    for hero, cell in frame.groupby("hero"):
        if len(cell) >= HERO_BASELINE_MIN_ROWS:
            role = cell["role"].iat[0]
            out[int(hero)] = float(
                (cell["c"].mean() - role_stats.at[role, "mean"]) / (role_stats.at[role, "std"] or 1.0)
            )
    return out


def _spread(deviations: dict[int, float]) -> tuple[float, float]:
    values = np.abs(np.asarray(list(deviations.values()) or [0.0]))
    return float(values.max()), float(values.mean())


@dataclass(frozen=True)
class Report:
    auc_v2: float
    auc_v1: float
    role_mvp_share: dict[str, float]
    role_slot_share: dict[str, float]
    #: Max |hero deviation| on the training stints, against the baselines built from them.
    hero_fit: float
    #: (max, mean) |hero deviation| on the holdout with hero baselines, and with role-only baselines.
    hero_holdout: tuple[float, float]
    hero_holdout_role_only: tuple[float, float]
    worst_hero: tuple[int | None, float]

    @property
    def checks(self) -> dict[str, bool]:
        return {
            "auc": not np.isnan(self.auc_v2) and (np.isnan(self.auc_v1) or self.auc_v2 >= self.auc_v1),
            "role_share": all(
                abs(self.role_mvp_share.get(role, 0.0) - self.role_slot_share.get(role, 0.0)) <= ROLE_SHARE_TOLERANCE
                for role in IMPACT_ROLES
            ),
            "hero_fit": self.hero_fit <= HERO_FIT_TOLERANCE,
            "hero_holdout": self.hero_holdout[0] < self.hero_holdout_role_only[0]
            and self.hero_holdout[1] < self.hero_holdout_role_only[1],
        }


def validate(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    rows: list[dict],
    threshold: float | None,
    weights: dict[str, dict[str, float]],
    outcomes: pd.DataFrame,
    v1_points: pd.DataFrame,
) -> Report:
    """The R3.Q8/R4.Q2 checks: held-out segment-0 stints scored with the fitted weights and the training baselines
    (``rows``); hero bias in-sample on ``train`` and, on the holdout, against role-only baselines."""
    baselines = impact.baseline_set(rows, threshold)
    role_only = impact.baseline_set([row for row in rows if row.get("hero") is None], threshold)
    players = impact.score_players(holdout, baselines, weights, keys=["match_id", "segment"])
    players = players[players["scored"]]
    teams = holdout.drop_duplicates(["match_id", "player_id"]).set_index(["match_id", "player_id"])["team_id"]
    players = players.assign(
        team_id=[teams[(m, p)] for m, p in zip(players["match_id"], players["player_id"], strict=True)]
    )

    def team_auc(points: pd.DataFrame, column: str) -> float:
        sums = points.groupby(["match_id", "team_id"])[column].sum()
        score, label = [], []
        for match in outcomes.itertuples(index=False):
            home, away = (match.match_id, match.home_team_id), (match.match_id, match.away_team_id)
            if home in sums.index and away in sums.index:
                score.append(sums[home] - sums[away])
                label.append(1.0 if match.home_won else 0.0)
        return auc(np.asarray(score), np.asarray(label))

    roles = impact.dominant_roles(holdout, ["match_id", "segment"])
    players = players.assign(
        role=[roles.get(k) for k in players[["match_id", "segment", "player_id"]].itertuples(index=False, name=None)]
    )
    top = players[players["ImpactRank"] == 1]
    top_weight = 1.0 / top.groupby("match_id")["player_id"].transform("count")
    mvp_share = (top_weight.groupby(top["role"]).sum() / top["match_id"].nunique()).to_dict()
    slot_share = players["role"].value_counts(normalize=True).to_dict()

    holdout_deviations = hero_deviations(holdout, baselines, weights)
    worst = max(holdout_deviations.items(), key=lambda item: abs(item[1]), default=(None, 0.0))
    return Report(
        auc_v2=team_auc(players, "ImpactPoints"),
        auc_v1=team_auc(v1_points, "value") if not v1_points.empty else float("nan"),
        role_mvp_share={str(k): float(v) for k, v in mvp_share.items()},
        role_slot_share={str(k): float(v) for k, v in slot_share.items()},
        hero_fit=_spread(hero_deviations(train, baselines, weights))[0],
        hero_holdout=_spread(holdout_deviations),
        hero_holdout_role_only=_spread(hero_deviations(holdout, role_only, weights)),
        worst_hero=worst,
    )


def render_weights_module(fit: Fit, report: Report, *, maps: int, since: datetime) -> str:
    lines = [
        '"""Fitted ``impact_v2`` weights — generated by ``backend/stats-service/fit_impact_weights.py``; do not edit by hand.',
        "",
        f"Fitted {datetime.now(UTC):%Y-%m-%d} on {fit.train_maps} decisive training maps ({maps} maps since {since:%Y-%m-%d});",
        f"ridge λ={fit.lam}, prior scale {fit.scale:.4f}. Holdout: AUC v2 {report.auc_v2:.4f} vs v1 {report.auc_v1:.4f};",
        "MVP share by role "
        + ", ".join(f"{r} {report.role_mvp_share.get(r, 0.0):.3f}" for r in IMPACT_ROLES)
        + " vs slots "
        + ", ".join(f"{r} {report.role_slot_share.get(r, 0.0):.3f}" for r in IMPACT_ROLES)
        + ";",
        f"hero bias: in-sample max {report.hero_fit:.3f} σ; holdout max/mean {report.hero_holdout[0]:.3f}/"
        f"{report.hero_holdout[1]:.3f} σ vs role-only {report.hero_holdout_role_only[0]:.3f}/"
        f"{report.hero_holdout_role_only[1]:.3f} σ (largest: hero {report.worst_hero[0]}, {report.worst_hero[1]:+.3f} σ).",
        '"""',
        "",
        "from typing import Final",
        "",
        "FITTED: Final = True",
        "",
        "IMPACT_WEIGHTS: Final[dict[str, dict[str, float]]] = {",
    ]
    for role in IMPACT_ROLES:
        lines.append(f'    "{role}": {{')
        lines.extend(f'        "{feature}": {fit.weights[role][feature]!r},' for feature in IMPACT_FEATURES)
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


async def _load(since: datetime, max_maps: int) -> tuple:
    """Everything the fit reads, bounded: the ``max_maps`` most recent maps of the window, and only their scores,
    stored v1 points and dates. One ``READ ONLY`` transaction with a statement timeout."""
    import sqlalchemy as sa

    from shared import models
    from shared.core.enums import LogStatsName
    from shared.disciplines.overwatch.baselines import load_baseline_inputs
    from shared.repository.stats_queries import player_facts, team_scores
    from src.core import db

    async with db.async_session_maker() as session:
        await session.execute(sa.text("SET TRANSACTION READ ONLY"))
        await session.execute(sa.text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        inputs = await load_baseline_inputs(session, discipline="overwatch", since=since, max_matches=max_maps)
        ids = sorted({int(match_id) for match_id in inputs.stints["match_id"]})
        scores = team_scores(discipline="overwatch", stat_code="score")
        score_rows = (
            await session.execute(
                sa.select(scores.c.match_id, scores.c.encounter_team_id, scores.c.value).where(
                    scores.c.match_id.in_(ids)
                )
            )
        ).all()
        facts = player_facts(discipline="overwatch")
        v1 = (
            await session.execute(
                sa.select(facts.c.match_id, facts.c.encounter_team_id.label("team_id"), facts.c.value).where(
                    facts.c.match_id.in_(ids),
                    facts.c.stat_code == LogStatsName.ImpactPoints.value,
                    facts.c.segment == 0,
                    facts.c.entity_id.is_(None),
                )
            )
        ).all()
        played = (
            await session.execute(
                sa.select(
                    models.StatsMatch.id, sa.func.coalesce(models.StatsMatch.played_at, models.StatsMatch.created_at)
                ).where(models.StatsMatch.id.in_(ids))
            )
        ).all()
    return inputs, score_rows, v1, dict(played)


def outcomes_from_scores(score_rows: list, played: dict) -> pd.DataFrame:
    """Decisive maps only (two teams, different scores); home = the lower encounter team id."""
    frame = pd.DataFrame(score_rows, columns=["match_id", "team_id", "value"])
    out = []
    for match_id, teams in frame.groupby("match_id"):
        if len(teams) != 2:
            continue
        home, away = teams.sort_values("team_id").itertuples(index=False)
        if home.value != away.value:
            out.append((match_id, home.team_id, away.team_id, home.value > away.value, played.get(match_id)))
    return pd.DataFrame(out, columns=["match_id", "home_team_id", "away_team_id", "home_won", "played_at"])


async def _main(since_days: int, max_maps: int, write: bool) -> None:
    since = datetime.now(UTC) - timedelta(days=since_days)
    inputs, score_rows, v1_rows, played = await _load(since, max_maps)
    stints = inputs.stints
    outcomes = outcomes_from_scores(score_rows, played)
    outcomes = outcomes[outcomes["match_id"].isin(set(stints["match_id"]))].sort_values(["played_at", "match_id"])
    cut = int(len(outcomes) * (1.0 - HOLDOUT_SHARE))
    train_ids, holdout_ids = set(outcomes["match_id"].iloc[:cut]), set(outcomes["match_id"].iloc[cut:])
    train, holdout = stints[stints["match_id"].isin(train_ids)], stints[stints["match_id"].isin(holdout_ids)]
    print(
        f"maps: {stints['match_id'].nunique()} with stints, {len(outcomes)} decisive; train {len(train_ids)}, holdout {len(holdout_ids)}"
    )

    stat_rows, _ = build_baseline_rows(train, inputs.quintiles, _UNIT)
    feature_rows = [row for row in stat_rows if row["stat"] not in ("ImpactPoints", "OverperformanceScore")]
    x, y, _ = design(exposures(train, impact.baseline_set(feature_rows, None)), outcomes)
    fit = fit_weights(x, y)
    rows, threshold = build_baseline_rows(train, inputs.quintiles, fit.weights)
    v1 = pd.DataFrame(v1_rows, columns=["match_id", "team_id", "value"])
    report = validate(train, holdout, rows, threshold, fit.weights, outcomes, v1[v1["match_id"].isin(holdout_ids)])

    print(f"λ={fit.lam} scale={fit.scale:.4f} badge threshold (train)={threshold}")
    for role in IMPACT_ROLES:
        print(f"{role:8s}", " ".join(f"{f}={fit.weights[role][f]:+.3f}" for f in IMPACT_FEATURES))
    print(f"AUC v2 {report.auc_v2:.4f} vs v1 {report.auc_v1:.4f}")
    print("MVP share", report.role_mvp_share, "slot share", report.role_slot_share)
    print(
        f"hero bias: in-sample max {report.hero_fit:.3f}; holdout max/mean {report.hero_holdout[0]:.3f}/"
        f"{report.hero_holdout[1]:.3f} vs role-only {report.hero_holdout_role_only[0]:.3f}/"
        f"{report.hero_holdout_role_only[1]:.3f}; largest {report.worst_hero}"
    )
    print("checks", report.checks)
    if write:
        if not all(report.checks.values()):
            raise SystemExit("Acceptance checks failed: weights not written")
        WEIGHTS_FILE.write_text(render_weights_module(fit, report, maps=len(outcomes), since=since), encoding="utf-8")
        print(f"wrote {WEIGHTS_FILE}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fit and gate the impact_v2 weights (read-only).")
    parser.add_argument("--since-days", type=int, default=365, help="History window in days (default 365).")
    parser.add_argument(
        "--max-maps", type=int, default=DEFAULT_MAX_MAPS, help=f"Most recent maps to read (default {DEFAULT_MAX_MAPS})."
    )
    parser.add_argument(
        "--write", action="store_true", help="Rewrite shared/core/impact_weights.py if every check passes."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(_main(args.since_days, args.max_maps, args.write))
