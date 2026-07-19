"""Pure computation for MVP impact scoring (spec 2026-07-10).

Everything here is deterministic and DB-free: kill-feed event counting,
role attribution, and the z-composite scoring. IO (baselines fetch,
persistence) lives in the callers.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from shared.core.impact import (
    EVENT_STATS,
    IMPACT_WEIGHTS,
    MIN_SECONDS,
    WINSOR_LIMIT,
)
from src import models
from src.core import enums

__all__ = (
    "FIGHT_GAP_SECONDS",
    "BaselineSet",
    "ImpactContext",
    "PlayerRef",
    "add_impact_scores",
    "assign_fights",
    "build_event_counts",
    "dominant_roles",
)

_EVENT_COLS = list(EVENT_STATS)

#: A new "fight" (teamfight cluster) starts after a lull longer than this many
#: seconds between consecutive kills — or at any round boundary (see
#: :func:`assign_fights`). Fights feed first_picks / first_deaths in scoring.
FIGHT_GAP_SECONDS = 15.0


def assign_fights(kill_feed: Sequence[models.MatchKillFeed]) -> None:
    """Assign 1-indexed ``fight`` ids in place (mutates each row's ``.fight``).

    A new fight begins on a **new round** OR after a gap longer than
    ``FIGHT_GAP_SECONDS`` between consecutive kills. Kills are ordered by time
    first; ``round`` is monotonic in time (``round_number`` = RoundStart
    cumsum), so a round change is a hard fight boundary and a fight never spans
    rounds.

    Shared by the live parser pipeline (``flows.process_kills``) and the history
    backfill so both agree on fight boundaries — this matters because fights
    determine first_picks / first_deaths, which feed impact scoring. Deterministic,
    so re-running the backfill produces identical fight ids (idempotent).
    """
    fight = 0
    prev: models.MatchKillFeed | None = None
    for kill in sorted(kill_feed, key=lambda k: k.time):
        if prev is None:
            fight = 1
        elif kill.round != prev.round or (kill.time - prev.time) > FIGHT_GAP_SECONDS:
            fight += 1
        kill.fight = fight
        prev = kill


@dataclass(frozen=True)
class PlayerRef:
    player_id: int  # tournament.player.id (pivot key)
    user_id: int  # players.user.id (stat rows / kill_feed key)
    team_id: int
    role: enums.HeroClass | None
    rank: int


@dataclass(frozen=True)
class BaselineSet:
    formula_version: str
    #: ascending inner bounds; rank <= bounds[i] -> bucket i, else last bucket
    bucket_bounds: tuple[float, ...]
    #: (role value, bucket | -1, stat NAME) -> (mean, std)
    values: Mapping[tuple[str, int, str], tuple[float, float]]

    def bucket_for(self, rank: int) -> int:
        for i, bound in enumerate(self.bucket_bounds):
            if rank <= bound:
                return i
        return len(self.bucket_bounds)

    def z(self, role: str, bucket: int, stat: str, rate: float) -> float:
        entry = self.values.get((role, bucket, stat))
        if entry is None:
            return 0.0
        mean, std = entry
        if std <= 0.0:
            return 0.0
        z = (rate - mean) / std
        return max(-WINSOR_LIMIT, min(WINSOR_LIMIT, z))


@dataclass(frozen=True)
class ImpactContext:
    """Everything :func:`add_impact_scores` needs, resolved once per match.

    ``baselines`` is ``None`` when no active baseline set exists yet (fresh
    system); callers must skip impact emission gracefully in that case.
    """

    players: Mapping[int, PlayerRef]
    baselines: "BaselineSet | None"
    has_killfeed: bool


def build_event_counts(
    kill_feed: Sequence[models.MatchKillFeed],
    hero_types: Mapping[int, enums.HeroClass],
) -> pd.DataFrame:
    """Per (user_id, round) event counts derived from the kill feed.

    First kill of each fight (by time) yields a FirstPick for the killer
    (unless a self-kill) and a FirstDeath for the victim. Self-kills never
    count as kills for Ultimate/Support tallies.
    """
    if not kill_feed:
        return pd.DataFrame(columns=["user_id", "round", *_EVENT_COLS])

    rows = pd.DataFrame(
        {
            "time": [k.time for k in kill_feed],
            "round": [k.round for k in kill_feed],
            "fight": [k.fight for k in kill_feed],
            "killer_id": [k.killer_id for k in kill_feed],
            "victim_id": [k.victim_id for k in kill_feed],
            "victim_hero_id": [k.victim_hero_id for k in kill_feed],
            "is_ult": [k.ability == enums.AbilityEvent.Ultimate for k in kill_feed],
        }
    ).sort_values("time")

    rows["is_self"] = rows["killer_id"] == rows["victim_id"]
    rows["victim_is_support"] = rows["victim_hero_id"].map(lambda h: hero_types.get(h) == enums.HeroClass.support)
    first = rows.groupby("fight", as_index=False).first()

    counters: dict[tuple[int, int], dict[str, int]] = {}

    def bump(user_id: int, rnd: int, stat: str) -> None:
        key = (int(user_id), int(rnd))
        counters.setdefault(key, dict.fromkeys(_EVENT_COLS, 0))[stat] += 1

    for r in first.itertuples(index=False):
        if not r.is_self:
            bump(r.killer_id, r.round, "FirstPicks")
        bump(r.victim_id, r.round, "FirstDeaths")
    for r in rows[~rows["is_self"]].itertuples(index=False):
        if r.is_ult:
            bump(r.killer_id, r.round, "UltimateKills")
        if r.victim_is_support:
            bump(r.killer_id, r.round, "SupportKills")

    out = pd.DataFrame([{"user_id": uid, "round": rnd, **stats} for (uid, rnd), stats in counters.items()])
    return out.sort_values(["user_id", "round"]).reset_index(drop=True)


def dominant_roles(
    playtime: pd.DataFrame,
    hero_types: Mapping[int, enums.HeroClass],
) -> dict[int, enums.HeroClass]:
    """player_id -> role with the most summed hero seconds."""
    if playtime.empty:
        return {}
    df = playtime.copy()
    df["role"] = df["hero_id"].map(hero_types)
    df = df.dropna(subset=["role"])
    grouped = df.groupby(["player_id", "role"], observed=True)["seconds"].sum().reset_index()
    grouped = grouped.sort_values("seconds", ascending=False)
    best = grouped.drop_duplicates("player_id")
    return dict(zip(best["player_id"].astype(int), best["role"], strict=True))


def add_impact_scores(
    df: pd.DataFrame,
    *,
    players: Mapping[int, PlayerRef],
    baselines: BaselineSet,
    has_killfeed: bool,
) -> pd.DataFrame:
    """Add ImpactPoints / OverperformanceScore columns to a stat pivot.

    ``df`` rows are one player within one scoring group (a round or the
    whole match); stat columns are ``LogStatsName`` members. time_share is
    computed inside each ``round`` group.
    """
    df = df.copy()
    seconds = df.get(enums.LogStatsName.HeroTimePlayed)
    if seconds is None:
        seconds = pd.Series(0.0, index=df.index)
    seconds = seconds.fillna(0.0)
    max_seconds = seconds.groupby(df["round"]).transform("max").replace(0, 1.0)
    time_share = seconds / max_seconds

    impact_scores: list[float] = []
    overperf_scores: list[float] = []
    for idx, row in df.iterrows():
        ref = players.get(int(row["player_id"]))
        secs = float(seconds.loc[idx])
        if ref is None or ref.role is None or secs < MIN_SECONDS:
            impact_scores.append(0.0)
            overperf_scores.append(0.0)
            continue
        role = ref.role.value.lower() if hasattr(ref.role, "value") else str(ref.role).lower()
        bucket = baselines.bucket_for(ref.rank)
        base_score = 0.0
        rank_score = 0.0
        for stat_name, weight in IMPACT_WEIGHTS.items():
            member = enums.LogStatsName[stat_name]
            raw = row.get(member, 0.0)
            value = 0.0 if pd.isna(raw) else float(raw)
            if stat_name in EVENT_STATS and not has_killfeed:
                continue
            rate = value / secs * 600.0
            base_score += weight * baselines.z(role, -1, stat_name, rate)
            rank_score += weight * baselines.z(role, bucket, stat_name, rate)
        share = float(time_share.loc[idx])
        impact_scores.append(base_score * share)
        overperf_scores.append(rank_score * share)

    df[enums.LogStatsName.ImpactPoints] = impact_scores
    df[enums.LogStatsName.OverperformanceScore] = overperf_scores
    return df
