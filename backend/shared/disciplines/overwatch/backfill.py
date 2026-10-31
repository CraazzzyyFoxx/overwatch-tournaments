"""Idempotent native OW backfill at every non-character segment.

Raw and character facts remain untouched. The kill-feed event counts and every ``impact_v2`` fact are recomputed from
the stored per-hero facts, the stored kill feed (fights are re-assigned deterministically) and the active baselines;
ownership always comes from match_player, even after a roster change or removal. Each caller's per-match commit
includes complete evidence and tracked JSON fight updates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import sqlalchemy as sa
from loguru import logger

from shared import models
from shared.core import enums, impact_weights
from shared.core.impact import EVENT_STATS
from shared.disciplines.overwatch import baselines as baselines_service
from shared.disciplines.overwatch import impact
from shared.disciplines.overwatch.impact_backfill import NEW_STAT_MEMBERS
from shared.disciplines.overwatch.rank_quintiles import match_quintiles
from shared.repository.stats import StatDefRepository, StatsMatchRepository
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, stage_stats_evidence

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = (
    "MAX_CONSECUTIVE_FAILURES",
    "BackfillService",
    "backfill_all",
    "backfill_match",
    "backfill_service",
)

#: Circuit breaker for ``backfill_all``: abort the run after this many
#: per-match failures IN A ROW (resets on any success). Guards against a
#: systemic bug (e.g. schema/code mismatch) silently burning a multi-hour
#: run over thousands of matches before anyone reads the summary — isolated
#: bad matches below this threshold still just increment ``failed`` and
#: the loop continues.
MAX_CONSECUTIVE_FAILURES = 10


class BackfillService:
    def __init__(self, *, stats_repo: StatsMatchRepository = StatsMatchRepository()) -> None:
        self._stats_repo = stats_repo
        self._hero_types_cache: dict[int, enums.HeroClass] = {}

    def _fact_objects(
        self,
        match_id: int,
        ownership: dict[int, int],
        stat_ids: dict[str, int],
        facts: list[tuple[int, int, enums.LogStatsName, float]],
    ) -> list[dict]:
        """Native facts of ``(member, segment, stat, value)`` using actual participant ownership, never roster teams."""
        return [
            {
                "match_id": match_id,
                "segment": segment,
                "encounter_team_id": ownership[member_id],
                "workspace_member_id": member_id,
                "entity_id": None,
                "stat_id": stat_ids[stat.value],
                "value": float(value),
            }
            for member_id, segment, stat, value in facts
        ]

    async def _load_stat_rows(self, session: AsyncSession, match_id: int) -> pd.DataFrame:
        """Every stored fact of a member that is not one of the derived codes (segment, hero, name, value)."""
        fact, stat = models.StatsFact, models.StatDef
        rows = (
            await session.execute(
                sa.select(fact.workspace_member_id, fact.segment, fact.entity_id, stat.code, fact.value)
                .join(stat, stat.id == fact.stat_id)
                .where(
                    fact.match_id == match_id,
                    stat.discipline == "overwatch",
                    fact.workspace_member_id.is_not(None),
                    stat.code.not_in([member.value for member in NEW_STAT_MEMBERS]),
                )
            )
        ).all()
        df = pd.DataFrame(rows, columns=["player_id", "segment", "hero", "name", "value"])
        df["name"] = df["name"].map({stat.value: stat.name for stat in enums.LogStatsName})
        return df[df["name"].notna()]

    async def _load_ownership(self, session: AsyncSession, match_id: int) -> dict[int, int]:
        """Every observed player (including event-only and no-longer-rostered members) -> encounter team id."""
        player = models.StatsMatchPlayer
        rows = await session.execute(
            sa.select(player.workspace_member_id, player.encounter_team_id).where(player.match_id == match_id)
        )
        return dict(rows.all())

    async def _load_kills(self, session: AsyncSession, match_id: int) -> list[models.StatsEvent]:
        event, match, kind = models.StatsEvent, models.StatsMatch, models.EventType
        return list(
            await session.scalars(
                sa.select(event)
                .join(match, match.id == event.match_id)
                .join(
                    kind,
                    kind.id == event.type_id,
                )
                .where(
                    event.match_id == match_id,
                    match.discipline == "overwatch",
                    kind.discipline == "overwatch",
                    kind.code == "kill",
                )
                .order_by(event.t, event.id)
            )
        )

    async def _load_hero_types(self, session: AsyncSession) -> dict[int, enums.HeroClass]:
        if not self._hero_types_cache:
            catalog = await baselines_service.hero_catalog(session, discipline="overwatch")
            self._hero_types_cache.update(
                {hero_id: hero_class for hero_id, hero_class in catalog.values() if hero_class is not None}
            )
        return self._hero_types_cache

    async def backfill_match(self, session: AsyncSession, match_id: int) -> bool:
        """Recompute the event counts, impact facts and fights; flush/evidence here, commit in the caller."""
        match = await session.scalar(
            sa.select(models.StatsMatch)
            .where(
                models.StatsMatch.id == match_id,
                models.StatsMatch.discipline == "overwatch",
            )
            .with_for_update()
        )
        if match is None:
            return False
        stat_rows = await self._load_stat_rows(session, match_id)
        if stat_rows.empty:
            return False
        scopes = owner_scopes("match", (match_id,))
        before = await capture_stats_evidence(session, scopes=scopes)
        kill_feed = await self._load_kills(session, match_id)
        impact.assign_fights(kill_feed)
        ownership = await self._load_ownership(session, match_id)
        hero_types = await self._load_hero_types(session)
        baselines = await baselines_service.get_active(session, discipline="overwatch")
        if baselines is None:
            raise RuntimeError("Impact baselines are not computed — run recompute first")

        events = impact.build_event_counts(kill_feed, hero_types, member_user_ids={m: m for m in ownership})
        stints = impact.build_stints(stat_rows, events, hero_types)
        roles = impact.dominant_roles(stints[stints["segment"] == 0])
        by_encounter = await match_quintiles(session, [(match.encounter_id, m, role) for m, role in roles.items()])
        scored = impact.score_match(
            stints,
            baselines,
            impact_weights.IMPACT_WEIGHTS,
            has_killfeed=bool(kill_feed),
            roles=roles,
            quintiles={m: quintile for (_, m), quintile in by_encounter.items()},
        )
        facts = [
            (int(row.player_id), int(row.segment), row.stat, row.value) for row in scored.itertuples(index=False)
        ] + self._event_facts(stat_rows, events)
        stat_ids = await StatDefRepository().ids(session, discipline="overwatch")
        objects = self._fact_objects(match_id, ownership, stat_ids, facts)
        await self._stats_repo.replace_fact_codes(
            session,
            match_id=match_id,
            discipline="overwatch",
            stat_codes=[member.value for member in NEW_STAT_MEMBERS],
            rows=objects,
        )
        await session.flush()
        after = await capture_stats_evidence(session, scopes=scopes)
        if before != after:
            await stage_stats_evidence(
                session,
                operation="stats.derived_backfill",
                before=before,
                after=after,
                workspace_id=match.workspace_id,
                entity_type="stats_match",
                entity_id=match_id,
            )
        return True

    @staticmethod
    def _event_facts(stat_rows: pd.DataFrame, events: pd.DataFrame) -> list[tuple[int, int, enums.LogStatsName, float]]:
        """The kill-feed counts of every ``(member, segment)`` that has hero-less facts: per round, and the total at 0
        (the sum of the rounds); 0 where the player has no event."""
        cols = list(EVENT_STATS)
        rounds = (
            events[events["segment"] > 0].groupby(["player_id", "segment"])[cols].sum()
            if not events.empty
            else pd.DataFrame(columns=cols)
        )
        totals = rounds.groupby(level="player_id").sum() if not rounds.empty else rounds
        out = []
        hero_less = stat_rows[stat_rows["hero"].isna()]
        for member, segment in sorted(set(zip(hero_less["player_id"], hero_less["segment"], strict=True))):
            source = totals if segment == 0 else rounds
            key = member if segment == 0 else (member, segment)
            for name in EVENT_STATS:
                value = float(source.at[key, name]) if key in source.index else 0.0
                out.append((int(member), int(segment), enums.LogStatsName[name], value))
        return out

    async def backfill_all(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tournament_id: int | None = None,
    ) -> dict[str, int]:
        """Backfill every match with existing stats (optionally scoped to one tournament).

        Commits once per match, so a mid-run failure only loses the in-flight
        match — ``backfill_match``'s delete-then-insert is idempotent per match,
        so rerunning after a fix safely reprocesses everything from the start.

        Raises ``RuntimeError`` if ``MAX_CONSECUTIVE_FAILURES`` matches fail in a
        row — that pattern indicates a systemic bug (e.g. a schema/code
        mismatch that fails every match), not isolated bad data, so the run
        aborts fast instead of burning hours over thousands of matches before
        anyone reads the summary. The consecutive-failure counter resets on any
        success (processed or skipped); the total ``failed`` count keeps
        accumulating for genuinely-isolated bad matches under the threshold.
        """
        async with session_factory() as session:
            if await baselines_service.get_active(session, discipline="overwatch") is None:
                raise RuntimeError("Impact baselines are not computed — run recompute first")

            query = (
                sa.select(models.StatsMatch.id)
                .join(
                    models.EncounterGame,
                    models.EncounterGame.id == models.StatsMatch.encounter_game_id,
                )
                .join(
                    models.Encounter,
                    sa.and_(
                        models.Encounter.id == models.EncounterGame.encounter_id,
                        models.Encounter.workspace_id == models.StatsMatch.workspace_id,
                        models.Encounter.discipline == models.StatsMatch.discipline,
                    ),
                )
                .where(models.StatsMatch.discipline == "overwatch")
            )
            if tournament_id is not None:
                query = query.where(models.Encounter.tournament_id == tournament_id)
            match_ids = (await session.execute(query.order_by(models.StatsMatch.id))).scalars().all()

        total = len(match_ids)
        processed = 0
        skipped = 0
        failed = 0
        logger.info(
            f"Impact backfill starting: {total} matches"
            + (f" (tournament_id={tournament_id})" if tournament_id is not None else "")
        )

        consecutive_failures = 0
        for i, match_id in enumerate(match_ids, start=1):
            try:
                async with session_factory() as session:
                    did_backfill = await self.backfill_match(session, match_id)
                    await session.commit()
            except Exception:
                logger.exception(f"Impact backfill failed for match_id={match_id}")
                failed += 1
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    summary = {"total": total, "processed": processed, "skipped": skipped, "failed": failed}
                    logger.error(f"Impact backfill aborting: {summary}")
                    raise RuntimeError(
                        f"Impact backfill aborted after {consecutive_failures} consecutive failures "
                        f"(most recently match_id={match_id}) — likely a systemic bug, not isolated "
                        f"bad matches; summary so far: {summary}"
                    )
                continue
            else:
                consecutive_failures = 0

            if did_backfill:
                processed += 1
            else:
                skipped += 1

            if i % 100 == 0:
                logger.info(
                    f"Impact backfill progress: {i}/{total} processed={processed} skipped={skipped} failed={failed}"
                )

        summary = {"total": total, "processed": processed, "skipped": skipped, "failed": failed}
        logger.info(f"Impact backfill done: {summary}")
        return summary


backfill_service = BackfillService()

backfill_match = backfill_service.backfill_match
backfill_all = backfill_service.backfill_all
