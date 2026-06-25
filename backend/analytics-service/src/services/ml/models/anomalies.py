"""Player anomaly detectors for the unified ML signal pipeline.

All detectors are intentionally *signals*, not verdicts. They operate on the
residual outputs produced by Performance v2 and return rows that can be stored
in ``analytics.player_anomaly``:

    {
        "player_id": int,
        "kind": "smurf" | "troll" | "throw" | "sandbag",
        "score": float,
        "confidence": float,
        "reasons": list[str],
        "evidence": dict[str, typing.Any],
    }
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

__all__ = (
    "AnomalyReport",
    "detect_smurfs",
    "detect_trolls",
    "detect_throws",
    "detect_sandbags",
)


@dataclass
class AnomalyReport:
    flags: list[dict[str, typing.Any]] = field(default_factory=list)

    def extend(self, more: typing.Iterable[dict[str, typing.Any]]) -> None:
        self.flags.extend(more)


_SMURF_FEATURES: tuple[str, ...] = (
    "rank",
    "impact_score",
    "local_zscore",
    "local_percentile",
    "kd",
    "weapon_accuracy",
    "final_blows_p10",
)


def detect_smurfs(
    df: pd.DataFrame,
    *,
    contamination: float = 0.05,
    impact_threshold: float = 80.0,
    rank_threshold: float = 35.0,
    local_z_threshold: float = 0.9,
    local_percentile_threshold: float = 80.0,
    strong_local_z_threshold: float = 1.5,
    min_role_size: int = 3,
) -> list[dict[str, typing.Any]]:
    """Flag likely smurfs / strong cohort outliers.

    A player is flagged when EITHER:
    - the classic under-ranked smurf rule fires — high-impact within the role,
      low-rank relative to the role pool, AND clearly outperforming their own
      local division band; OR
    - they are a **strong cohort outlier** regardless of rank — their
      division-normalised ``local_zscore`` is at/above ``strong_local_z_threshold``
      (someone playing far above their role+division peers should be surfaced even
      if they are not low-rank, since cross-division ``impact_score`` and the rank
      gate otherwise hide mid/high-rank overperformers).
    """
    if df.empty or not all(c in df.columns for c in _SMURF_FEATURES):
        return []

    out: list[dict[str, typing.Any]] = []
    for role, group in df.groupby("role", dropna=False):
        feats = group[list(_SMURF_FEATURES)].fillna(0.0)
        if len(feats) < min_role_size:
            continue

        impact_cutoff = float(np.nanpercentile(group["impact_score"], impact_threshold))
        rank_cutoff = float(np.nanpercentile(group["rank"], rank_threshold))

        if len(feats) >= 5:
            clf = IsolationForest(
                contamination=contamination,
                random_state=0,
                n_estimators=200,
            )
            clf.fit(feats)
            scores = -clf.score_samples(feats)
            anomaly_mask = clf.predict(feats) == -1
        else:
            scores = np.zeros(len(feats), dtype=float)
            anomaly_mask = np.zeros(len(feats), dtype=bool)

        for idx, score, is_anom in zip(group.index, scores, anomaly_mask, strict=False):
            row = group.loc[idx]
            local_z = float(row.get("local_zscore") or 0.0)
            local_pct = float(row.get("local_percentile") or 0.0)
            impact = float(row["impact_score"] or 0.0)
            rank = float(row["rank"] or 0.0)
            rank_suspicious = rank > 0 and rank <= rank_cutoff
            impact_suspicious = impact >= impact_cutoff
            local_suspicious = (
                local_z >= local_z_threshold
                or local_pct >= local_percentile_threshold
            )
            strong_local = local_z >= strong_local_z_threshold
            classic_smurf = impact_suspicious and rank_suspicious and local_suspicious
            deterministic_review = classic_smurf or strong_local
            if deterministic_review:
                confidence = float(
                    np.clip(
                        0.25
                        + (0.15 if is_anom else 0.0)
                        + min(max(local_z, 0.0), 3.0) / 7.5
                        + max(local_pct - 50.0, 0.0) / 140.0
                        + max(impact - impact_cutoff, 0.0) / 200.0,
                        0.0,
                        1.0,
                    )
                )
                # Human-meaningful reason CODES (frontend localises them); the
                # numeric detail lives in ``evidence``. Internal method labels
                # (IsolationForest / review rule) are intentionally not surfaced.
                reasons = []
                if impact_suspicious:
                    reasons.append("top_impact")
                if rank_suspicious:
                    reasons.append("low_rank")
                if local_z >= local_z_threshold or local_pct >= local_percentile_threshold:
                    reasons.append("cohort_overperformance")
                if strong_local and not classic_smurf:
                    reasons.append("strong_cohort_outlier")
                out.append(
                    {
                        "player_id": int(row["player_id"]),
                        "kind": "smurf",
                        "score": float(max(score, confidence)),
                        "confidence": confidence,
                        "reasons": reasons,
                        "evidence": {
                            "impact_score": impact,
                            "rank": rank,
                            "local_zscore": local_z,
                            "local_percentile": local_pct,
                            "impact_cutoff": impact_cutoff,
                            "rank_cutoff": rank_cutoff,
                            "role": str(role),
                            "severity": "review",
                        },
                    }
                )
    return out


def detect_trolls(
    df: pd.DataFrame,
    *,
    window: int = 3,
    z_threshold: float = -1.35,
    single_tournament_z_threshold: float = -1.9,
    single_tournament_impact_threshold: float = 18.0,
) -> list[dict[str, typing.Any]]:
    """Flag persistent underperformance.

    The preferred path uses ``local_zscore_history`` so the detector measures
    repeated underperformance against the player's own nearby division pool.
    Older callers can still pass ``raw_value_history`` or long-format rows.
    """
    if df.empty:
        return []

    out: list[dict[str, typing.Any]] = []

    if "local_zscore_history" in df.columns:
        for _, row in df.iterrows():
            history = row.get("local_zscore_history") or []
            if len(history) < 2:
                if row.get("local_zscore") is not None:
                    current = float(row.get("local_zscore") or 0.0)
                elif history:
                    current = float(history[-1])
                else:
                    current = 0.0
                impact = float(row.get("impact_score") or 100.0)
                if (
                    current <= single_tournament_z_threshold
                    and impact <= single_tournament_impact_threshold
                ):
                    out.append(
                        {
                            "player_id": int(row["player_id"]),
                            "kind": "troll",
                            "score": float(-current),
                            "confidence": float(np.clip(abs(current) / 4.0, 0.0, 0.55)),
                            "reasons": ["single_tournament_underperformance"],
                            "evidence": {
                                "current_local_zscore": current,
                                "impact_score": impact,
                                "severity": "review",
                            },
                        }
                    )
                continue
            recent = history[-window:] if len(history) >= window else history
            recent_mean = float(np.nanmean(recent))
            if recent_mean <= z_threshold:
                out.append(
                    {
                        "player_id": int(row["player_id"]),
                        "kind": "troll",
                        "score": float(-recent_mean),
                        "confidence": float(np.clip(abs(recent_mean) / 3.0, 0.0, 1.0)),
                        "reasons": ["sustained_underperformance"],
                        "evidence": {
                            "recent_local_zscores": [float(v) for v in recent],
                            "window": len(recent),
                        },
                    }
                )
        return out

    if "raw_value_history" in df.columns:
        all_values: list[float] = []
        for hist in df["raw_value_history"]:
            if isinstance(hist, list):
                all_values.extend(float(v) for v in hist if v is not None)
        if not all_values:
            return []
        pool_mean = float(np.nanmean(all_values))
        pool_std = float(np.nanstd(all_values))
        if pool_std <= 0:
            return []
        for _, row in df.iterrows():
            history = row.get("raw_value_history") or []
            if len(history) < 2:
                continue
            recent = history[-window:] if len(history) >= window else history
            recent_mean = float(np.nanmean(recent))
            z = (recent_mean - pool_mean) / pool_std
            if z <= z_threshold:
                out.append(
                    {
                        "player_id": int(row["player_id"]),
                        "kind": "troll",
                        "score": float(-z),
                        "confidence": float(np.clip(abs(z) / 3.0, 0.0, 1.0)),
                        "reasons": ["sustained_underperformance"],
                        "evidence": {
                            "recent_raw_values": [float(v) for v in recent],
                            "window": len(recent),
                            "pool_mean": pool_mean,
                            "pool_std": pool_std,
                        },
                    }
                )
        return out

    history = df.sort_values(["player_id", "tournament_id"])
    for player_id, group in history.groupby("player_id"):
        rolling = group["raw_value"].rolling(window=window, min_periods=2).mean()
        if rolling.notna().sum() == 0:
            continue
        latest = rolling.iloc[-1]
        if pd.isna(latest):
            continue
        std = float(np.nanstd(history["raw_value"]))
        if std <= 0:
            continue
        z = (latest - float(np.nanmean(history["raw_value"]))) / std
        if z <= z_threshold:
            out.append(
                {
                    "player_id": int(player_id),
                    "kind": "troll",
                    "score": float(-z),
                    "confidence": float(np.clip(abs(z) / 3.0, 0.0, 1.0)),
                    "reasons": ["sustained_underperformance"],
                    "evidence": {"window": window, "zscore": float(z)},
                }
            )
    return out


def detect_sandbags(
    df: pd.DataFrame,
    *,
    min_history: int = 2,
    min_current_z: float = -1.25,
    min_drop_z: float = 1.45,
    prior_mean_floor: float = -0.25,
) -> list[dict[str, typing.Any]]:
    """Flag sharp one-tournament drops versus the player's own baseline."""
    if df.empty or "local_zscore_history" not in df.columns:
        return []

    out: list[dict[str, typing.Any]] = []
    for _, row in df.iterrows():
        history = row.get("local_zscore_history") or []
        if len(history) < min_history:
            continue
        prior = [float(v) for v in history[:-1] if v is not None]
        if len(prior) < min_history - 1:
            continue

        current = float(history[-1])
        prior_mean = float(np.nanmean(prior))
        drop = prior_mean - current
        if (
            current <= min_current_z
            and drop >= min_drop_z
            and prior_mean >= prior_mean_floor
        ):
            confidence_base = max(float(row.get("confidence") or 0.5), 0.25)
            out.append(
                {
                    "player_id": int(row["player_id"]),
                    "kind": "sandbag",
                    "score": float(drop),
                    "confidence": float(np.clip((drop / 3.0) * confidence_base, 0.0, 1.0)),
                    "reasons": ["sharp_recent_drop"],
                    "evidence": {
                        "prior_local_zscores": prior,
                        "prior_mean": prior_mean,
                        "current_local_zscore": current,
                        "drop": drop,
                    },
                }
            )
    return out


def detect_throws(
    round_residuals: pd.DataFrame,
    *,
    drop_threshold: float = 1.45,
    min_pre_mean: float = 0.65,
    max_post_mean: float = -0.75,
    min_post_negative_fraction: float = 0.65,
    pelt_penalty: float = 2.5,
) -> list[dict[str, typing.Any]]:
    """Flag players whose peer-centred round residuals show a sharp late drop."""
    if round_residuals.empty:
        return []
    try:
        import ruptures as rpt  # type: ignore[import-untyped]
    except Exception:  # pragma: no cover
        return []

    out: list[dict[str, typing.Any]] = []
    grouped = round_residuals.sort_values(["player_id", "encounter_id", "round"]).groupby(
        ["player_id", "encounter_id"]
    )
    for (player_id, encounter_id), group in grouped:
        series = group["y_perf"].astype(float).to_numpy()
        if len(series) < 4 or np.isnan(series).all():
            continue
        series = np.nan_to_num(series, nan=0.0)
        algo = rpt.Pelt(model="rbf").fit(series)
        try:
            cpts = algo.predict(pen=pelt_penalty)
        except Exception:  # pragma: no cover
            cpts = []
        cpts = [c for c in cpts if 0 < c < len(series)]

        if len(cpts) == 1:
            cp = cpts[0]
            detection_method = "pelt"
        else:
            # PELT can be too conservative on short BO3/BO5 series. Use a
            # simple best split fallback so obvious mid-match collapses still
            # become low/medium-confidence review signals.
            candidates = range(2, max(2, len(series) - 1))
            drops = [
                (split, float(series[:split].mean() - series[split:].mean()))
                for split in candidates
            ]
            if not drops:
                continue
            cp, best_drop = max(drops, key=lambda item: item[1])
            if best_drop < drop_threshold:
                continue
            detection_method = "best_split"

        if cp <= 0 or cp >= len(series):
            continue
        pre_mean = float(series[:cp].mean())
        post_mean = float(series[cp:].mean())
        post_negative_fraction = float(np.mean(series[cp:] <= max_post_mean))
        if (
            pre_mean >= min_pre_mean
            and post_mean <= max_post_mean
            and post_negative_fraction >= min_post_negative_fraction
            and post_mean < pre_mean - drop_threshold
        ):
            out.append(
                {
                    "player_id": int(player_id),
                    "kind": "throw",
                    "score": float(pre_mean - post_mean),
                    "confidence": float(np.clip((pre_mean - post_mean) / 3.0, 0.0, 1.0)),
                    "reasons": ["mid_series_drop"],
                    "encounter_id": int(encounter_id),
                    "evidence": {
                        "changepoint_round": int(cp),
                        "pre_mean": pre_mean,
                        "post_mean": post_mean,
                        "post_negative_fraction": post_negative_fraction,
                        "method": detection_method,
                        "severity": "review",
                    },
                }
            )
    return out
