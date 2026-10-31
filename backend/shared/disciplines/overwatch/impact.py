"""Pure computation for MVP impact scoring (``impact_v2``).

Deterministic and DB-free: fight assignment, kill-feed attribution, hero stints and the z-composite scoring of
``docs/superpowers/specs/2026-10-31-mvp-impact-v2-design.md`` §3. IO (baselines, facts, rank quintiles) lives in the
callers: the live derivation (``ingest.derive_match``), the history backfill and the baseline recompute.

A **stint** is one player on one hero in one segment (a round, or the whole map at segment 0): a row of
:func:`build_stints` with ``player_id, segment, hero, role, seconds`` and one count column per ``IMPACT_FEATURES``
NAME. ``hero`` is a catalog entity id; ``role`` the hero's class (``tank``/``damage``/``support``) or ``None``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared import models
from shared.core import enums
from shared.core.impact import (
    CONTRIBUTION_STATS,
    EVENT_STATS,
    FORMULA_VERSION,
    IMPACT_FEATURES,
    MIN_SECONDS,
    SHRINK_MINUTES,
    WINSOR_LIMIT,
)
from shared.disciplines.overwatch.enums import AbilityEvent

__all__ = (
    "FIGHT_GAP_SECONDS",
    "BaselineSet",
    "KillRow",
    "Weights",
    "assign_fights",
    "baseline_set",
    "build_event_counts",
    "build_stints",
    "dominant_roles",
    "feature_terms",
    "score_match",
    "score_players",
)

Weights = Mapping[str, Mapping[str, float]]

#: A new "fight" (teamfight cluster) starts after a lull longer than this many seconds between consecutive kills — or
#: at any round boundary (see :func:`assign_fights`). Fights feed first_picks / first_deaths.
FIGHT_GAP_SECONDS = 15.0

_EVENT_COLS = list(EVENT_STATS)
_FEATURES = list(IMPACT_FEATURES)
_EVENT_INDEX = np.array([feature in EVENT_STATS for feature in IMPACT_FEATURES])
_RAW_FEATURES = [feature for feature in IMPACT_FEATURES if feature not in EVENT_STATS]


@dataclass(slots=True)
class KillRow:
    """A kill as the formulas read it: a decoded kill and a ``stats.event`` row have exactly this shape."""

    t: float
    segment: int
    actor_member_id: int | None
    target_member_id: int | None
    #: The victim's hero.
    related_entity_id: int | None
    data: dict | None = None
    #: The killer's hero.
    entity_id: int | None = None


def assign_fights(kill_feed: Sequence[KillRow | models.StatsEvent]) -> None:
    """Assign 1-indexed fight ids through tracked, complete JSON assignments.

    A new fight begins on a **new round** OR after a gap longer than ``FIGHT_GAP_SECONDS`` between consecutive kills.
    Kills are ordered by time first; ``round`` is monotonic in time, so a fight never spans rounds. Shared by the
    decoder and the history backfill so both agree on fight boundaries; deterministic, so a re-run produces identical
    fight ids.
    """
    fight = 0
    prev: KillRow | models.StatsEvent | None = None
    for kill in sorted(kill_feed, key=lambda k: k.t):
        if prev is None:
            fight = 1
        elif kill.segment != prev.segment or (kill.t - prev.t) > FIGHT_GAP_SECONDS:
            fight += 1
        kill.data = {**(kill.data or {}), "fight": fight}
        prev = kill


def build_event_counts(
    kill_feed: Sequence[KillRow | models.StatsEvent],
    hero_types: Mapping[int, enums.HeroClass],
    *,
    member_user_ids: Mapping[int, int],
) -> pd.DataFrame:
    """Kill-feed counts per ``(player_id, segment, hero)``; ``player_id`` is ``member_user_ids[member]``.

    The first kill of each fight (by time) is a FirstPick for the killer (unless a self-kill) and a FirstDeath for the
    victim. Self-kills never count as Ultimate/Support kills. FirstPicks/UltimateKills/SupportKills sit on the killer's
    hero, FirstDeaths on the victim's; ``hero`` is ``None`` when the log named no hero. Round segments only — a caller
    wanting map totals sums them.
    """
    columns = ["player_id", "segment", "hero", *_EVENT_COLS]
    if not kill_feed:
        return pd.DataFrame(columns=columns)

    def member(member_id: int | None) -> int | None:
        return member_user_ids[member_id] if member_id is not None else None

    rows = pd.DataFrame(
        {
            "time": [k.t for k in kill_feed],
            "segment": [k.segment for k in kill_feed],
            "fight": [(k.data or {}).get("fight") for k in kill_feed],
            "killer": [member(k.actor_member_id) for k in kill_feed],
            "killer_hero": [k.entity_id for k in kill_feed],
            "victim": [member(k.target_member_id) for k in kill_feed],
            "victim_hero": [k.related_entity_id for k in kill_feed],
            "is_ult": [(k.data or {}).get("ability") == AbilityEvent.Ultimate.value for k in kill_feed],
        },
        dtype=object,
    ).sort_values("time", kind="stable")
    rows["is_self"] = [k is not None and k == v for k, v in zip(rows["killer"], rows["victim"], strict=True)]

    counters: dict[tuple[int, int, int | None], dict[str, int]] = {}

    def bump(player: int | None, segment: int, hero: int | None, stat: str) -> None:
        if player is None or pd.isna(player):
            return
        key = (int(player), int(segment), None if hero is None or pd.isna(hero) else int(hero))
        counters.setdefault(key, dict.fromkeys(_EVENT_COLS, 0))[stat] += 1

    for r in rows.groupby("fight", sort=False, dropna=False).head(1).itertuples(index=False):
        if not r.is_self:
            bump(r.killer, r.segment, r.killer_hero, "FirstPicks")
        bump(r.victim, r.segment, r.victim_hero, "FirstDeaths")
    for r in rows[~rows["is_self"]].itertuples(index=False):
        if r.is_ult:
            bump(r.killer, r.segment, r.killer_hero, "UltimateKills")
        if r.victim_hero is not None and hero_types.get(int(r.victim_hero)) == enums.HeroClass.support:
            bump(r.killer, r.segment, r.killer_hero, "SupportKills")

    out = pd.DataFrame(
        [{"player_id": p, "segment": s, "hero": h, **stats} for (p, s, h), stats in counters.items()],
        columns=columns,
    )
    return out.sort_values(["player_id", "segment", "hero"], na_position="first", kind="stable").reset_index(drop=True)


def build_stints(
    stat_rows: pd.DataFrame,
    events: pd.DataFrame,
    hero_types: Mapping[int, enums.HeroClass],
) -> pd.DataFrame:
    """Hero stints of every segment from per-hero facts plus kill-feed counts.

    ``stat_rows`` columns: ``player_id, segment, hero, name`` (``LogStatsName`` member NAME), ``value``; rows with a
    null ``hero`` are ignored. ``events`` is :func:`build_event_counts` output (round segments); its map totals are
    their sum, and counts on a hero the player has no playtime row for are dropped. A stint needs playtime > 0.
    """
    columns = ["player_id", "segment", "hero", "role", "seconds", *_FEATURES]
    wanted = {*_RAW_FEATURES, "HeroTimePlayed"}
    rows = stat_rows[stat_rows["hero"].notna() & stat_rows["name"].isin(wanted)]
    if rows.empty:
        return pd.DataFrame(columns=columns)
    stints = rows.pivot_table(
        index=["player_id", "segment", "hero"], columns="name", values="value", aggfunc="sum", fill_value=0.0
    ).reset_index()
    stints.columns.name = None
    stints["seconds"] = stints.pop("HeroTimePlayed") if "HeroTimePlayed" in stints.columns else 0.0
    for feature in _RAW_FEATURES:
        if feature not in stints.columns:
            stints[feature] = 0.0
    stints = stints.astype({"player_id": "int64", "segment": "int64", "hero": "int64"})

    hero_events = events[events["hero"].notna() & (events["segment"] > 0)] if not events.empty else events
    if hero_events.empty:
        for feature in _EVENT_COLS:
            stints[feature] = 0.0
    else:
        hero_events = hero_events.astype({"player_id": "int64", "segment": "int64", "hero": "int64"})
        totals = hero_events.groupby(["player_id", "hero"], as_index=False)[_EVENT_COLS].sum().assign(segment=0)
        counts = pd.concat([hero_events[["player_id", "segment", "hero", *_EVENT_COLS]], totals], ignore_index=True)
        stints = stints.merge(counts, on=["player_id", "segment", "hero"], how="left")
        stints[_EVENT_COLS] = stints[_EVENT_COLS].fillna(0.0).astype(float)

    stints = stints[stints["seconds"] > 0.0].copy()
    stints["role"] = [_role_of(hero_types.get(int(hero))) for hero in stints["hero"]]
    return stints[columns].sort_values(["segment", "player_id", "hero"], kind="stable").reset_index(drop=True)


def _role_of(hero_class: enums.HeroClass | None) -> str | None:
    if hero_class is None or hero_class is enums.HeroClass.flex:
        return None
    return hero_class.name


def dominant_roles(stints: pd.DataFrame, keys: Sequence[str] = ()) -> dict:
    """The role with the most classed seconds per player (ties: role name order).

    Without ``keys`` the result maps ``player_id -> role``; with ``keys`` (e.g. ``match_id, segment``) it maps
    ``(*keys, player_id) -> role``.
    """
    group = [*keys, "player_id"]
    classed = stints[stints["role"].notna()]
    if classed.empty:
        return {}
    by_role = classed.groupby([*group, "role"], as_index=False)["seconds"].sum()
    best = by_role.sort_values(
        [*group, "seconds", "role"], ascending=[True] * len(group) + [False, True], kind="stable"
    ).drop_duplicates(group)
    pairs = zip(best[group].itertuples(index=False, name=None), best["role"], strict=True)
    if keys:
        return {tuple(int(v) for v in key): str(role) for key, role in pairs}
    return {int(key[0]): str(role) for key, role in pairs}


@dataclass(frozen=True)
class BaselineSet:
    """Everything §4 of the design stores for one formula version."""

    formula_version: str
    #: ``(role, hero | None, feature NAME) -> (mean, std)`` of per-10-minute rates; a hero key exists only for a hero
    #: with its own baseline.
    stats: Mapping[tuple[str, int | None, str], tuple[float, float]]
    #: ``role -> (mean, std)`` of the raw stint composite.
    role_scale: Mapping[str, tuple[float, float]]
    #: ``(role, quintile) -> (mean, std)`` of player-map quality; quintile ``-1`` is the role's all-quintile fallback.
    expectation: Mapping[tuple[str, int], tuple[float, float]]
    #: The badge needs at least this overperformance; ``None`` = no badge can be earned.
    badge_threshold: float | None

    def stat(self, role: str, hero: int | None, feature: str) -> tuple[float, float] | None:
        if hero is not None:
            entry = self.stats.get((role, hero, feature))
            if entry is not None:
                return entry
        return self.stats.get((role, None, feature))

    def expected(self, role: str, quintile: int) -> tuple[float, float] | None:
        for key in ((role, quintile), (role, -1)):
            entry = self.expectation.get(key)
            if entry is not None and entry[1] > 0.0:
                return entry
        return None


def baseline_set(
    rows: Sequence[Mapping], badge_threshold: float | None, *, formula_version: str = FORMULA_VERSION
) -> BaselineSet:
    """Assemble a :class:`BaselineSet` from baseline row dicts (``role, hero, rank_bucket, stat, mean, std``).

    ``stat == "ImpactPoints"`` rows are the role scale, ``"OverperformanceScore"`` rows the expectation, every other
    stat a feature baseline — the storage layout of design §4.
    """
    stats: dict[tuple[str, int | None, str], tuple[float, float]] = {}
    role_scale: dict[str, tuple[float, float]] = {}
    expectation: dict[tuple[str, int], tuple[float, float]] = {}
    for row in rows:
        entry = (float(row["mean"]), float(row["std"]))
        if row["stat"] == "ImpactPoints":
            role_scale[row["role"]] = entry
        elif row["stat"] == "OverperformanceScore":
            expectation[(row["role"], int(row["rank_bucket"]))] = entry
        else:
            hero = row.get("hero")
            stats[(row["role"], None if hero is None else int(hero), row["stat"])] = entry
    return BaselineSet(formula_version, stats, role_scale, expectation, badge_threshold)


def feature_terms(
    stints: pd.DataFrame, baselines: BaselineSet, weights: Weights
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per stint: ``w·z / sd_R`` per feature, the role-standardised composite ``ĉ`` and the raw composite.

    Unclassed stints (``role`` None) score zeros. A feature without a baseline (or with ``std <= 0``) has ``z = 0``;
    event features are 0 on a stint whose ``killfeed`` is false.
    """
    n = len(stints)
    values = np.nan_to_num(stints[_FEATURES].to_numpy(dtype=np.float64))
    seconds = stints["seconds"].to_numpy(dtype=np.float64)
    roles = stints["role"].to_numpy(dtype=object)
    heroes = stints["hero"].to_numpy()
    z = np.zeros((n, len(_FEATURES)))
    weight = np.zeros((n, len(_FEATURES)))
    scale_mean = np.zeros(n)
    scale_sd = np.ones(n)

    keys: dict[tuple[str, int], list[int]] = {}
    for i, (role, hero) in enumerate(zip(roles, heroes, strict=True)):
        if role is not None and seconds[i] > 0.0:
            keys.setdefault((role, int(hero)), []).append(i)
    for (role, hero), positions in keys.items():
        idx = np.asarray(positions, dtype=np.intp)
        rates = values[idx] / seconds[idx, None] * 600.0
        for j, feature in enumerate(_FEATURES):
            entry = baselines.stat(role, hero, feature)
            if entry is None or entry[1] <= 0.0:
                continue
            mean, std = entry
            z[idx, j] = np.clip((rates[:, j] - mean) / std, -WINSOR_LIMIT, WINSOR_LIMIT)
        role_weights = weights.get(role, {})
        weight[idx] = [role_weights.get(feature, 0.0) for feature in _FEATURES]
        mean, sd = baselines.role_scale.get(role, (0.0, 1.0))
        scale_mean[idx] = mean
        scale_sd[idx] = sd if sd > 0.0 else 1.0

    if "killfeed" in stints.columns:
        z[np.ix_(~stints["killfeed"].to_numpy(dtype=bool), _EVENT_INDEX)] = 0.0
    terms = z * weight
    raw = terms.sum(axis=1)
    return terms / scale_sd[:, None], (raw - scale_mean) / scale_sd, raw


def score_players(
    stints: pd.DataFrame,
    baselines: BaselineSet,
    weights: Weights,
    *,
    keys: Sequence[str] = ("segment",),
) -> pd.DataFrame:
    """Score every player of every ``keys`` group (a segment of one match, or ``match_id, segment`` across matches).

    ``stints`` may carry ``killfeed`` (bool), ``rank_role`` (str) and ``quintile`` (int, NaN = unknown) columns,
    constant per player within a group; without ``rank_role`` the player's dominant role in the group is used.
    Returns one row per player with ``keys, player_id, seconds`` (classed), ``quality`` (Q), ``scored``,
    ``ImpactPoints``, ``OverperformanceScore`` (NaN when no quintile or expectation), ``ImpactRank`` (NaN when
    unscored) and one column per feature NAME holding its contribution.
    """
    keys = list(keys)
    group = [*keys, "player_id"]
    if stints.empty:
        return pd.DataFrame(
            columns=[*group, "seconds", "quality", "scored", "ImpactPoints", "OverperformanceScore", "ImpactRank"]
        )
    terms, c_hat, _ = feature_terms(stints, baselines, weights)
    classed = stints["role"].notna().to_numpy()
    seconds = stints["seconds"].to_numpy(dtype=np.float64)
    weighted = np.where(classed, seconds, 0.0)

    frame = stints[group].copy()
    frame["all_seconds"] = seconds
    frame["seconds"] = weighted
    frame["c"] = weighted * c_hat
    frame[_FEATURES] = weighted[:, None] * terms
    players = frame.groupby(group, as_index=False, sort=True).sum()

    total = players["seconds"].to_numpy()
    safe = np.where(total > 0.0, total, 1.0)
    players["quality"] = players["c"].to_numpy() / safe
    longest = players.groupby(keys)["all_seconds"].transform("max").to_numpy()
    share = np.where(longest > 0.0, total / np.where(longest > 0.0, longest, 1.0), 0.0)
    minutes = total / 60.0
    factor = share * minutes / (minutes + SHRINK_MINUTES)
    players["scored"] = total >= MIN_SECONDS
    players["ImpactPoints"] = factor * players["quality"].to_numpy()
    players[_FEATURES] = factor[:, None] * players[_FEATURES].to_numpy() / safe[:, None]

    rank_roles = _per_player(stints, group, "rank_role")
    if rank_roles is None:
        rank_roles = dominant_roles(stints, keys)
    quintiles = _per_player(stints, group, "quintile")
    over = np.full(len(players), np.nan)
    if quintiles is not None:
        for i, key in enumerate(players[group].itertuples(index=False, name=None)):
            role, quintile = rank_roles.get(key), quintiles.get(key)
            if role is None or quintile is None or pd.isna(quintile):
                continue
            expected = baselines.expected(role, int(quintile))
            if expected is not None:
                over[i] = factor[i] * (players["quality"].iat[i] - expected[0]) / expected[1]
    players["OverperformanceScore"] = over

    players = players.drop(columns=["all_seconds", "c"])
    points = players["ImpactPoints"].where(players["scored"])
    players["ImpactRank"] = points.groupby([players[k] for k in keys]).rank(method="min", ascending=False)
    return players


def _per_player(stints: pd.DataFrame, group: list[str], column: str) -> dict[tuple, object] | None:
    if column not in stints.columns:
        return None
    first = stints.drop_duplicates(group)
    return dict(zip(first[group].itertuples(index=False, name=None), first[column], strict=True))


def score_match(
    stints: pd.DataFrame,
    baselines: BaselineSet,
    weights: Weights,
    *,
    has_killfeed: bool,
    roles: Mapping[int, str],
    quintiles: Mapping[int, int],
) -> pd.DataFrame:
    """Every impact fact of one match as rows ``player_id, segment, stat`` (``LogStatsName``), ``value``.

    ``roles``: each player's dominant role on the map (:func:`dominant_roles` of the segment-0 stints), the role their
    rank quintile is for; ``quintiles``: player -> rank quintile (absent = unknown). Unscored players get no rows;
    contributions and the badge are segment 0 only.
    """
    columns = ["player_id", "segment", "stat", "value"]
    if stints.empty:
        return pd.DataFrame(columns=columns)
    frame = stints.assign(
        killfeed=has_killfeed,
        rank_role=[roles.get(int(p)) for p in stints["player_id"]],
        quintile=[quintiles.get(int(p), np.nan) for p in stints["player_id"]],
    )
    players = score_players(frame, baselines, weights)
    players = players[players["scored"]]

    out: list[dict] = []
    for row in players.itertuples(index=False):
        segment, player = int(row.segment), int(row.player_id)
        out.append(_fact(player, segment, enums.LogStatsName.ImpactPoints, row.ImpactPoints))
        out.append(_fact(player, segment, enums.LogStatsName.ImpactRank, row.ImpactRank))
        if not pd.isna(row.OverperformanceScore):
            out.append(_fact(player, segment, enums.LogStatsName.OverperformanceScore, row.OverperformanceScore))
    match = players[players["segment"] == 0]
    for feature, stat in CONTRIBUTION_STATS.items():
        out.extend(_fact(int(p), 0, stat, v) for p, v in zip(match["player_id"], match[feature], strict=True))
    rated = match[match["OverperformanceScore"].notna()]
    threshold = baselines.badge_threshold
    if not rated.empty:
        over = rated["OverperformanceScore"]
        top = over.rank(method="min", ascending=False) == 1
        earned = top & (over >= threshold) if threshold is not None else top & False
        out.extend(
            _fact(int(p), 0, enums.LogStatsName.OverperformanceBadge, 1.0 if e else 0.0)
            for p, e in zip(rated["player_id"], earned, strict=True)
        )
    return pd.DataFrame(out, columns=columns)


def _fact(player: int, segment: int, stat: enums.LogStatsName, value: float) -> dict:
    return {"player_id": player, "segment": segment, "stat": stat, "value": float(value)}
