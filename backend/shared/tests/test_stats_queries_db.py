"""Native observation grain, tenant/discipline boundaries and real cascade ownership."""

import asyncio
import re

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.errors import BaseAPIException
from shared.rbac.workspace_lookup import get_ingest_job_workspace_id, get_match_workspace_id
from shared.repository.stats_queries import match_context, player_facts, team_scores
from shared.services.workspace_scope import apply_workspace_filter
from shared.testing.stats_parity import (
    seed_native_sentinel,
)


def test_player_grain_and_discipline_scope_preserve_historical_rows(stats_parity_database):
    asyncio.run(_player_grain(stats_parity_database))


async def _player_grain(stats_parity_database):
    url, ids = stats_parity_database
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            await session.run_sync(lambda s: seed_native_sentinel(s.connection(), ids))
            facts = player_facts(discipline="overwatch")
            query = sa.select(facts.c.match_id, facts.c.value, facts.c.source_position).where(
                facts.c.player_id == ids["player"],
                facts.c.workspace_id == ids["workspace"],
                facts.c.stat_code == "hero_damage_dealt",
                facts.c.segment == 0,
                facts.c.entity_id.is_(None),
            )
            rows = {row.match_id: (row.value, row.source_position) for row in await session.execute(query)}
            assert rows[ids["match"]] == (18_000.0, 1)
            assert rows[ids["match_reversed"]] == (27_000.0, 2)
            assert ids["match_other"] not in rows
            assert ids["match_lol"] not in rows
            # Visibility is a reader predicate, not a lossy generic relation default.
            visible = set(
                await session.scalars(
                    sa.select(facts.c.match_id)
                    .join(models.Tournament, models.Tournament.id == facts.c.tournament_id)
                    .where(facts.c.workspace_id == ids["workspace"], models.Tournament.is_hidden.is_(False))
                    .distinct()
                )
            )
            assert ids["match"] in visible
            assert ids["match_hidden"] not in visible
            assert ids["match_other"] not in visible
            hero_rows = (
                await session.execute(
                    sa.select(facts.c.entity_id, facts.c.value).where(
                        facts.c.match_id == ids["match"],
                        facts.c.workspace_member_id == ids["member"],
                        facts.c.stat_code == "hero_damage_dealt",
                        facts.c.segment == 0,
                        facts.c.entity_id.is_not(None),
                    )
                )
            ).all()
            assert dict(hero_rows) == {ids["hero"]: 13_500.0, ids["hero_other"]: 4_500.0}
            assert (
                await session.scalar(
                    sa.select(facts.c.value).where(
                        facts.c.match_id == ids["match"],
                        facts.c.workspace_member_id == ids["member_removed"],
                        facts.c.segment == 0,
                        facts.c.entity_id.is_(None),
                        facts.c.stat_code == "hero_damage_dealt",
                    )
                )
                == 9_000.0
            )
            await session.execute(
                sa.update(models.EncounterTeam)
                .where(models.EncounterTeam.encounter_id == ids["encounter"])
                .values(active=False)
            )
            assert {row.match_id: (row.value, row.source_position) for row in await session.execute(query)} == rows
            await session.execute(
                sa.update(models.StatsMatch)
                .where(models.StatsMatch.encounter_id == ids["encounter"])
                .values(encounter_game_id=None)
            )
            assert {row.match_id: (row.value, row.source_position) for row in await session.execute(query)} == rows
            # A reader projecting neither source_position nor tournament_team_id never joins match_team or
            # encounter.team: as inner joins, their correlated keys were estimated at one row per match team and a
            # one-player read nest-looped every match team past the statement timeout.
            lean = sa.select(facts.c.value).where(facts.c.player_id == ids["player"])
            lean_sql = lean.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
            plan = "\n".join(await session.scalars(sa.text(f"EXPLAIN {lean_sql}")))
            assert not re.search(r"\bon (match_)?team\b", plan), plan
            foreign = player_facts(discipline="lol")
            assert (
                await session.scalar(
                    sa.select(foreign.c.value).where(
                        foreign.c.match_id == ids["match_lol"],
                        foreign.c.segment == 0,
                        foreign.c.entity_id.is_(None),
                        foreign.c.stat_code == "hero_damage_dealt",
                    )
                )
                == 1_000_000.0
            )
    finally:
        await engine.dispose()


def test_scores_keep_observation_order_separate_from_slots_and_official_results(stats_parity_database):
    asyncio.run(_score_orientation(stats_parity_database))


async def _score_orientation(stats_parity_database):
    url, ids = stats_parity_database
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            scores = team_scores(discipline="overwatch", stat_code="score")
            rows = (await session.execute(sa.select(scores).where(scores.c.match_id == ids["match_reversed"]))).all()
            assert {row.encounter_team_id: (row.source_position, row.slot, row.value) for row in rows} == {
                ids["encounter_team_home"]: (2, 1, 4.0),
                ids["encounter_team_away"]: (1, 2, 3.0),
            }
            official = dict(
                (
                    await session.execute(
                        sa.select(
                            models.EncounterGameTeam.encounter_team_id,
                            models.EncounterGameTeam.score,
                        ).where(models.EncounterGameTeam.game_id == ids["game_reversed"])
                    )
                ).all()
            )
            assert official == {ids["encounter_team_home"]: 9, ids["encounter_team_away"]: 7}
            context = match_context(discipline="overwatch")
            bound = (await session.execute(sa.select(context).where(context.c.id == ids["match_reversed"]))).one()
            assert (bound.encounter_game_id, bound.position, bound.encounter_id) == (
                ids["game_reversed"],
                2,
                ids["encounter"],
            )
            await session.execute(
                sa.update(models.StatsMatch)
                .where(models.StatsMatch.id == ids["match_reversed"])
                .values(encounter_game_id=None)
            )
            unbound = (await session.execute(sa.select(scores).where(scores.c.match_id == ids["match_reversed"]))).all()
            assert set(unbound) == set(rows)
            context = match_context(discipline="overwatch")
            row = (await session.execute(sa.select(context).where(context.c.id == ids["match_reversed"]))).one()
            assert (row.encounter_game_id, row.position, row.encounter_id, row.tournament_id, row.workspace_id) == (
                None,
                None,
                ids["encounter"],
                ids["tournament"],
                ids["workspace"],
            )
    finally:
        await engine.dispose()


def test_rbac_uses_native_ownership_even_without_job_hints(stats_parity_database):
    asyncio.run(_native_ownership(stats_parity_database))


async def _native_ownership(stats_parity_database):
    url, ids = stats_parity_database
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                sa.update(models.IngestJob)
                .where(models.IngestJob.id == ids["record"])
                .values(
                    hint_tournament_id=None,
                    hint_encounter_id=None,
                )
            )
            assert await get_ingest_job_workspace_id(session, ids["record"]) == ids["workspace"]
            assert await get_match_workspace_id(session, ids["match_other"]) == ids["workspace_other"]
            for lookup in (get_match_workspace_id, get_ingest_job_workspace_id):
                with pytest.raises(BaseAPIException) as missing:
                    await lookup(session, -1)
                assert missing.value.status_code == 404
            for model, column, wanted, forbidden in (
                (models.StatsMatch, models.StatsMatch.id, ids["match"], ids["match_other"]),
                (models.StatsFact, models.StatsFact.match_id, ids["match"], ids["match_other"]),
                (models.IngestJob, models.IngestJob.id, ids["record"], ids["record_other"]),
            ):
                scoped = set(
                    await session.scalars(
                        apply_workspace_filter(
                            sa.select(column).distinct(),
                            ids["workspace"],
                            root=model,
                        )
                    )
                )
                assert wanted in scoped
                assert forbidden not in scoped
    finally:
        await engine.dispose()


def test_view_only_encounter_matches_and_native_badge_follow_actual_deletion(stats_parity_database):
    asyncio.run(_encounter_deletion(stats_parity_database))


async def _encounter_deletion(stats_parity_database):
    url, ids = stats_parity_database
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                sa.update(models.StatsMatch)
                .where(models.StatsMatch.encounter_id == ids["encounter"])
                .values(encounter_game_id=None)
            )
            encounter = await session.scalar(
                sa.select(models.Encounter)
                .where(
                    models.Encounter.id == ids["encounter"],
                )
                .options(selectinload(models.Encounter.matches))
            )
            expected = [
                ids["match"],
                ids["match_reversed"],
                ids["match_no_raw"],
                *(ids[f"match_otp_{i}"] for i in range(1, 5)),
            ]
            assert [match.id for match in encounter.matches] == expected
            assert encounter.has_logs is True
            await session.delete(await session.get(models.StatsMatch, ids["match_other"]))
            await session.flush()
            assert (
                await session.scalar(
                    sa.select(models.Encounter.has_logs).where(
                        models.Encounter.id == ids["encounter_other"],
                    )
                )
                is False
            )
            await session.delete(encounter)
            await session.flush()
            await session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
            for model in (
                models.StatsMatch,
                models.StatsFact,
                models.StatsEvent,
                models.StatsMatchPlayer,
                models.StatsMatchTeam,
                models.StatsSegment,
            ):
                owner = model.id if model is models.StatsMatch else model.match_id
                assert (
                    await session.scalar(sa.select(sa.func.count()).select_from(model).where(owner.in_(expected))) == 0
                )
            assert await session.get(models.StatsMatch, ids["match_hidden"]) is not None
    finally:
        await engine.dispose()
