"""Native, discipline-scoped impact baselines: loading the inputs, the cached read and the atomic audited recompute.

``impact_v2`` (design §4): the aggregation itself is pure (``baseline_rows.build_baseline_rows``); this module reads
the last year's per-hero segment-0 facts, kill feeds and rank quintiles, and replaces a formula version's rows.
Observation ownership and encounter snapshots are not rewritten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd
import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, impact_weights
from shared.core.impact import (
    BASELINE_MAX_MATCHES,
    BASELINE_WINDOW_DAYS,
    EVENT_STATS,
    FORMULA_VERSION,
    IMPACT_FEATURES,
)
from shared.disciplines.overwatch import impact
from shared.disciplines.overwatch.baseline_rows import build_baseline_rows
from shared.disciplines.overwatch.rank_quintiles import match_quintiles
from shared.repository.baselines import StatBaselineRepository
from shared.repository.roles import CatalogRoleRepository
from shared.repository.stats import StatDefRepository
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, stage_stats_evidence

__all__ = (
    "BaselineInputs",
    "BaselineService",
    "baseline_service",
    "get_active",
    "hero_catalog",
    "invalidate_cache",
    "load_baseline_inputs",
    "recompute",
)

logger = logging.getLogger(__name__)
_CACHE_TTL = "10m"
#: Features read from the per-hero facts; the event features come from the kill feed.
_FACT_FEATURES = tuple(feature for feature in IMPACT_FEATURES if feature not in EVENT_STATS)
_FACT_CODES = {enums.LogStatsName[name].value: name for name in (*_FACT_FEATURES, "HeroTimePlayed")}
_STINT_COLUMNS = [
    "player_id",
    "segment",
    "hero",
    "role",
    "seconds",
    *IMPACT_FEATURES,
    "match_id",
    "team_id",
    "killfeed",
    "played_at",
]
#: Fight ids are numbered per match; ``match_id * _MAX_FIGHTS + fight`` keeps matches apart in one kill-feed frame.
_MAX_FIGHTS = 1_000_000


@dataclass
class BaselineInputs:
    """What ``build_baseline_rows`` aggregates (and the weight fit reads): one stint per player, hero and match."""

    #: Segment-0 :func:`impact.build_stints` rows with ``match_id``, ``team_id`` (``encounter.team`` id), ``killfeed``
    #: (bool: the match has a stored kill feed) and ``played_at``; ``player_id`` is the workspace member id.
    stints: pd.DataFrame
    #: ``(match_id, player_id) -> rank quintile`` of the player's dominant role on the map; absent = unknown.
    quintiles: dict[tuple[int, int], int]


async def hero_catalog(session: AsyncSession, *, discipline: str) -> dict[str, tuple[int, enums.HeroClass | None]]:
    """Character slug -> ``(catalog id, class)``; the class is ``None`` for a hero without one."""
    entity = models.CatalogEntity
    rows = await session.execute(
        sa.select(entity.slug, entity.id, entity.attrs["class"].astext).where(
            entity.discipline == discipline, entity.kind == "character"
        )
    )
    return {slug: (hero_id, enums.HeroClass.__members__.get(hero_class)) for slug, hero_id, hero_class in rows}


async def load_baseline_inputs(
    session: AsyncSession, *, discipline: str, since: datetime | None, max_matches: int | None = None
) -> BaselineInputs:
    """Every match of the discipline played at/after ``since`` (``coalesce(played_at, created_at)``; ``None`` = all),
    or the most recent ``max_matches`` of them."""
    catalog = await hero_catalog(session, discipline=discipline)
    hero_types = {hero_id: hero_class for hero_id, hero_class in catalog.values() if hero_class is not None}

    match = models.StatsMatch
    window = [match.discipline == discipline]
    if since is not None:
        window.append(sa.func.coalesce(match.played_at, match.created_at) >= since)
    played = sa.func.coalesce(match.played_at, match.created_at)
    query = sa.select(match.id, match.encounter_id, played).where(*window).order_by(played.desc(), match.id.desc())
    if max_matches is not None:
        query = query.limit(max_matches)
    matches = {
        match_id: (encounter_id, played_at) for match_id, encounter_id, played_at in await session.execute(query)
    }
    if max_matches is not None:
        window = [match.id.in_(list(matches))]
    empty = BaselineInputs(pd.DataFrame(columns=_STINT_COLUMNS), {})
    if not matches:
        return empty

    # ponytail: the window's per-hero facts are held in memory (a few million rows for a year of a busy deployment);
    # chunk by match id when that stops fitting.
    fact, stat = models.StatsFact, models.StatDef
    facts = (
        await session.execute(
            sa.select(
                fact.match_id, fact.workspace_member_id, fact.encounter_team_id, fact.entity_id, stat.code, fact.value
            )
            .join(match, match.id == fact.match_id)
            .join(stat, sa.and_(stat.id == fact.stat_id, stat.discipline == match.discipline))
            .where(
                *window,
                fact.segment == 0,
                fact.entity_id.is_not(None),
                fact.workspace_member_id.is_not(None),
                stat.code.in_(_FACT_CODES),
            )
            # Float reductions must not depend on the plan: immutable keys define the input order.
            .order_by(fact.match_id, fact.workspace_member_id, fact.entity_id, stat.code)
        )
    ).all()
    if not facts:
        return empty

    event, kind = models.StatsEvent, models.EventType
    kills = (
        await session.execute(
            sa.select(
                event.match_id,
                event.segment,
                event.t,
                event.actor_member_id,
                event.target_member_id,
                event.entity_id,
                event.related_entity_id,
                event.data,
            )
            .join(match, match.id == event.match_id)
            .join(kind, sa.and_(kind.id == event.type_id, kind.discipline == match.discipline))
            .where(*window, kind.code == "kill", event.data.has_key("fight"))
            .order_by(event.match_id, event.t, event.id)
        )
    ).all()

    # One synthetic player per (match, member): the stint and kill-feed builders then run once for every match, and
    # fights (numbered per match) stay apart because the fight key carries the match.
    pids: dict[tuple[int, int], int] = {}
    team_of: dict[int, int] = {}
    for match_id, member_id, team_id, *_ in facts:
        team_of[pids.setdefault((match_id, member_id), len(pids))] = team_id
    feed = []
    for match_id, segment, t, actor, target, hero, victim_hero, data in kills:
        feed.append(
            impact.KillRow(
                t=t,
                segment=segment,
                actor_member_id=None if actor is None else pids.setdefault((match_id, actor), len(pids)),
                target_member_id=None if target is None else pids.setdefault((match_id, target), len(pids)),
                related_entity_id=victim_hero,
                data={**data, "fight": match_id * _MAX_FIGHTS + data["fight"]},
                entity_id=hero,
            )
        )
    events = impact.build_event_counts(feed, hero_types, member_user_ids={pid: pid for pid in pids.values()})
    stat_rows = pd.DataFrame(
        [
            (pids[(match_id, member_id)], 0, hero, _FACT_CODES[code], value)
            for match_id, member_id, _, hero, code, value in facts
        ],
        columns=["player_id", "segment", "hero", "name", "value"],
    )
    stints = impact.build_stints(stat_rows, events, hero_types)
    if stints.empty:
        return empty

    keys = list(pids)
    match_ids = [keys[pid][0] for pid in stints["player_id"]]
    killfeed_matches = {match_id for match_id, *_ in kills}
    stints = stints.assign(
        match_id=match_ids,
        team_id=[team_of.get(pid) for pid in stints["player_id"]],
        killfeed=[match_id in killfeed_matches for match_id in match_ids],
        played_at=[matches[match_id][1] for match_id in match_ids],
        player_id=[keys[pid][1] for pid in stints["player_id"]],
    )

    roles = impact.dominant_roles(stints, ("match_id",))
    by_encounter = await match_quintiles(
        session, [(matches[match_id][0], member_id, role) for (match_id, member_id), role in roles.items()]
    )
    quintiles = {
        (match_id, member_id): by_encounter[(matches[match_id][0], member_id)]
        for (match_id, member_id) in roles
        if (matches[match_id][0], member_id) in by_encounter
    }
    return BaselineInputs(stints, quintiles)


class BaselineService:
    """Cached baseline read + the atomic recompute that replaces a formula version."""

    def __init__(self, *, repo: StatBaselineRepository = StatBaselineRepository()) -> None:
        self.repo = repo

    async def get_active(self, session: AsyncSession, *, discipline: str) -> impact.BaselineSet | None:
        key = f"backend:parser:impact_baselines:{discipline}:{FORMULA_VERSION}"
        if cache.is_setup():
            try:
                cached = await cache.get(key)
            except Exception:  # pragma: no cover - cache is best-effort
                logger.debug("impact baselines cache get failed", exc_info=True)
                cached = None
            if cached is not None:
                return cached

        baseline, role, dimension, stat = models.StatsBaseline, models.CatalogRole, models.RoleDimension, models.StatDef
        rows = (
            await session.execute(
                sa.select(baseline, role.code, stat.code)
                .join(role, role.id == baseline.role_id)
                .join(dimension, dimension.id == role.dimension_id)
                .join(stat, stat.id == baseline.stat_id)
                .where(
                    baseline.formula_version == FORMULA_VERSION,
                    dimension.discipline == discipline,
                    dimension.rated.is_(True),
                    stat.discipline == discipline,
                )
            )
        ).all()
        if not rows:
            return None

        threshold = next(
            (row.meta["badge_threshold"] for row, _, _ in rows if row.meta and "badge_threshold" in row.meta), None
        )
        baseline_set = impact.baseline_set(
            [
                {
                    "role": role_code,
                    "hero": row.entity_id,
                    "rank_bucket": row.rank_bucket,
                    "stat": enums.LogStatsName(stat_code).name,
                    "mean": row.mean,
                    "std": row.std,
                }
                for row, role_code, stat_code in rows
            ],
            threshold,
        )
        if cache.is_setup():
            try:
                await cache.set(key, baseline_set, expire=_CACHE_TTL)
            except Exception:  # pragma: no cover - cache is best-effort
                logger.debug("impact baselines cache set failed", exc_info=True)
        return baseline_set

    async def invalidate_cache(self, *, discipline: str) -> None:
        if not cache.is_setup():
            return
        try:
            await cache.delete(f"backend:parser:impact_baselines:{discipline}:{FORMULA_VERSION}")
        except Exception:  # pragma: no cover - cache is best-effort
            logger.debug("impact baselines cache invalidate failed", exc_info=True)

    async def recompute(self, session: AsyncSession, *, discipline: str) -> int:
        """Replace OW formula rows, sealing evidence before the existing commit."""
        if discipline != "overwatch":
            raise ValueError("impact baseline computation is only defined for overwatch")
        if not impact_weights.FITTED:
            raise RuntimeError(
                "impact weights are not fitted — run stats-service/fit_impact_weights.py and commit "
                "shared/core/impact_weights.py before recomputing baselines"
            )
        scopes = owner_scopes("baseline", (discipline, FORMULA_VERSION))
        before = await capture_stats_evidence(session, scopes=scopes)
        since = datetime.now(UTC) - timedelta(days=BASELINE_WINDOW_DAYS)
        inputs = await load_baseline_inputs(
            session, discipline=discipline, since=since, max_matches=BASELINE_MAX_MATCHES
        )
        rows, threshold = build_baseline_rows(inputs.stints, inputs.quintiles, impact_weights.IMPACT_WEIGHTS)
        if not rows:
            raise RuntimeError("impact baseline recompute produced 0 rows; refusing to wipe existing baselines")
        roles = await CatalogRoleRepository().rated_rows(session, discipline=discipline, workspace_id=None)
        stat_ids = await StatDefRepository().ids(session, discipline=discipline)
        baseline_rows = [
            models.StatsBaseline(
                formula_version=FORMULA_VERSION,
                role_id=roles[row["role"]].id,
                rank_bucket=row["rank_bucket"],
                stat_id=stat_ids[enums.LogStatsName[row["stat"]].value],
                entity_id=row["hero"],
                mean=row["mean"],
                std=row["std"],
                meta={
                    "n": row["n"],
                    "badge_threshold": threshold,
                    "window_days": BASELINE_WINDOW_DAYS,
                    "max_matches": BASELINE_MAX_MATCHES,
                },
            )
            for row in rows
        ]
        await self.repo.replace_for_version(session, FORMULA_VERSION, baseline_rows, discipline=discipline)
        after = await capture_stats_evidence(session, scopes=scopes)
        if before != after:
            await stage_stats_evidence(
                session,
                operation="stats.baseline_recompute",
                before=before,
                after=after,
                workspace_id=None,
                entity_type="stats_baseline",
                entity_id=None,
            )
        await session.commit()
        await self.invalidate_cache(discipline=discipline)
        return len(rows)


baseline_service = BaselineService()
get_active = baseline_service.get_active
invalidate_cache = baseline_service.invalidate_cache
recompute = baseline_service.recompute
