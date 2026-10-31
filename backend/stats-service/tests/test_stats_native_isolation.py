"""Parser consumers under native-only, non-owner PostgreSQL privileges.

Reuse the full frozen-output collectors, not a smaller isolation-only seed. Every
transaction (including ones opened after production commits) sets and verifies
its restricted role before executing consumer SQL. Main runs these proofs.
"""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from shared import models
from shared.repository.support import AchievementRuleRepository
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, validate_transition
from shared.testing.stats_access import native_role
from tests import test_stats_condition_parity as condition_parity
from tests import test_stats_derived_parity as derived_parity
from tests import test_stats_ingest_db as ingest


@asynccontextmanager
async def native_sessions(url):
    """Keep SET LOCAL ROLE effective across service-owned commit/rollback calls."""
    with native_role(url, write=True) as role:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))

        class NativeSession(Session):
            pass

        @sa.event.listens_for(NativeSession, "after_begin")
        def restrict(session, transaction, connection):
            connection.execute(sa.text(f'SET LOCAL ROLE "{role}"'))
            current, superuser, owns_relation, owns_schema, owns_database = connection.execute(
                sa.text("""
                SELECT current_user, r.rolsuper,
                       EXISTS (SELECT 1 FROM pg_class WHERE relowner = r.oid),
                       EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner = r.oid),
                       EXISTS (SELECT 1 FROM pg_database WHERE datdba = r.oid)
                FROM pg_roles r WHERE r.rolname = current_user
            """)
            ).one()
            assert current == role
            assert not (superuser or owns_relation or owns_schema or owns_database)

        try:
            yield async_sessionmaker(engine, expire_on_commit=False, sync_session_class=NativeSession)
        finally:
            await engine.dispose()


async def _audit_ids(session):
    return list(await session.scalars(sa.select(models.AuditLog.id).order_by(models.AuditLog.id)))


async def _assert_transitions(session, initial_ids, operations):
    audits = list(
        await session.scalars(
            sa.select(models.AuditLog)
            .where(
                models.AuditLog.id > max(initial_ids, default=0),
                models.AuditLog.action.in_(operations),
            )
            .order_by(models.AuditLog.id)
        )
    )
    assert {audit.action for audit in audits} == set(operations)
    for audit in audits:
        assert validate_transition(
            audit.action,
            audit.before_json["stats_evidence"]["states"],
            audit.after_json["stats_evidence"]["states"],
            before_values=audit.before_json.get("stats_values", ()),
            after_values=audit.after_json.get("stats_values", ()),
        )


def test_native_conditions_and_runner_preserve_full_outputs_and_atomic_evidence(stats_parity_database):
    url, ids = stats_parity_database

    async def exercise():
        async with native_sessions(url) as sf:
            async with sf() as session:
                initial_ids = await _audit_ids(session)
                actual = await condition_parity.collect_outputs(session, ids)
                await condition_parity.assert_condition_golden(session, ids, actual)
                await session.commit()
            # A fresh restricted session observes durable runner results and audits.
            async with sf() as session:
                assert (
                    await condition_parity._stored_state(session, ids["workspace"])
                    == actual["runner"]["revoke_deleted"]
                )
                await _assert_transitions(session, initial_ids, {"stats.reference_update"})
                rule = await session.get(models.AchievementRule, ids["rule"])
                original_dependencies = list(rule.depends_on)
                original_audits = await _audit_ids(session)
                await AchievementRuleRepository().update_fields(session, rule, {"depends_on": ["stats.event"]})
                await session.flush()
                assert rule.depends_on != original_dependencies
                assert len(await _audit_ids(session)) > len(original_audits)
                await session.rollback()
                await session.refresh(rule)
                assert rule.depends_on == original_dependencies
                assert await _audit_ids(session) == original_audits

    asyncio.run(exercise())


def test_native_baseline_backfill_and_scores_preserve_full_outputs_and_evidence(stats_parity_database):
    url, ids = stats_parity_database

    async def exercise():
        async with native_sessions(url) as sf:
            async with sf() as session:
                initial_ids = await _audit_ids(session)
                actual = await derived_parity.collect_outputs(session, ids)
                derived_parity.assert_derived_parity(actual)
                for result in actual["matches"].values():
                    assert derived_parity._preserved_facts(result["facts_before"]) == derived_parity._preserved_facts(
                        result["facts_first"]
                    )
                    assert result["facts_first"] == result["facts_second"]
                await derived_parity._assert_native_slots(session, ids)
                await session.commit()
            async with sf() as session:
                assert await derived_parity._baselines(session) == actual["baseline"]["after"]
                for name, result in actual["matches"].items():
                    assert await derived_parity._facts(session, [ids[name]]) == result["facts_second"]
                await _assert_transitions(session, initial_ids, {"stats.baseline_recompute", "stats.derived_backfill"})
                # The real backfill restores fight assignments, but neither its
                # data nor its evidence may survive an enclosing rollback.
                scopes = owner_scopes("match", (ids["match"],))
                before = await capture_stats_evidence(session, scopes=scopes)
                before_audits = await _audit_ids(session)
                transaction = await session.begin_nested()
                kill = await session.scalar(
                    sa.select(models.StatsEvent)
                    .join(models.EventType)
                    .where(
                        models.StatsEvent.match_id == ids["match"],
                        models.EventType.code == "kill",
                    )
                    .order_by(models.StatsEvent.id)
                    .limit(1)
                )
                assert kill is not None
                kill.data = {**kill.data, "fight": -1}
                await session.flush()
                assert await derived_parity.BackfillService().backfill_match(session, ids["match"])
                await session.flush()
                assert len(await _audit_ids(session)) > len(before_audits)
                await _assert_transitions(session, before_audits, {"stats.derived_backfill"})
                await transaction.rollback()
                session.expire_all()
                assert await capture_stats_evidence(session, scopes=scopes) == before
                assert await _audit_ids(session) == before_audits
                # The backfill cached its hand-built baselines process-wide; the next test must not derive from them.
                await derived_parity.baseline_module.baseline_service.invalidate_cache(discipline="overwatch")

    asyncio.run(exercise())


def test_native_ingest_and_reparse_commit_observations_outbox_and_evidence_atomically(
    stats_parity_database, monkeypatch
):
    url, _ = stats_parity_database

    async def exercise():
        # Existing synthetic Workshop CSV bytes and native seed; no parser or
        # repository doubles. RawStore replaces only object-store transport.
        async with ingest.environment(stats_parity_database, monkeypatch) as env:
            async with native_sessions(url) as sf:
                env.sf = sf
                monkeypatch.setattr(ingest.db, "async_session_maker", sf)
                async with sf() as session:
                    initial_ids = await _audit_ids(session)
                first_bytes = ingest.workshop(eliminations=2)
                first = await ingest.upload(env, first_bytes)
                assert first.content_hash == hashlib.sha256(first_bytes).hexdigest()
                assert first.raw_ref == f"logs/{env.tournament}/{first.content_hash}"
                assert env.raw.objects[first.raw_ref] == first_bytes
                assert await ingest.process(env, first.id) == ingest.STATUS.DONE
                match = await ingest.match_for_game(env)
                assert (match.workspace_id, match.discipline, match.ingest_job_id, match.revision) == (
                    env.workspace,
                    "overwatch",
                    first.id,
                    1,
                )
                before = await ingest.snapshot(env, match.id)
                assert await ingest.success_events(env) == 1
                async with sf() as session:
                    before_facts = await derived_parity._facts(session, [match.id])
                    eliminations = [
                        row["value"]
                        for row in before_facts
                        if row["stat_code"] == "eliminations" and row["round"] == 0 and row["hero_id"] is None
                    ]
                    assert eliminations == [2.0] * 6
                    counts = dict(
                        (
                            await session.execute(
                                sa.select(models.EventType.code, sa.func.count())
                                .join(models.StatsEvent, models.StatsEvent.type_id == models.EventType.id)
                                .where(models.StatsEvent.match_id == match.id)
                                .group_by(models.EventType.code)
                            )
                        ).all()
                    )
                    assert counts == {"kill": 2, "offensive_assist": 2, "mercy_rez": 1}
                    players = list(
                        await session.scalars(
                            sa.select(models.StatsMatchPlayer).where(
                                models.StatsMatchPlayer.match_id == match.id,
                            )
                        )
                    )
                    assert {row.workspace_member_id for row in players} == set(env.members.values())
                    seats = (
                        await session.execute(
                            sa.select(
                                models.StatsMatchTeam.encounter_team_id,
                                models.StatsMatchTeam.source_position,
                            )
                            .where(models.StatsMatchTeam.match_id == match.id)
                            .order_by(models.StatsMatchTeam.source_position)
                        )
                    ).all()
                    assert seats == list(zip(env.participants, (1, 2), strict=True))
                    before_reparse_ids = list(
                        await session.scalars(
                            sa.select(models.AuditLog.id)
                            .where(
                                models.AuditLog.action == "stats.reparse",
                                models.AuditLog.entity_id == match.id,
                            )
                            .order_by(models.AuditLog.id)
                        )
                    )
                    assert before_reparse_ids

                second_bytes = ingest.workshop(eliminations=3)
                second = await ingest.upload(env, second_bytes)
                assert second.id != first.id
                assert second.content_hash == hashlib.sha256(second_bytes).hexdigest()
                assert env.raw.objects[second.raw_ref] == second_bytes
                # Existing ingestion-test convention: a real DB constraint fails
                # the final DONE write, after observations/evidence/outbox staged.
                async with env.admin.begin() as connection:
                    await connection.execute(
                        sa.text(
                            "ALTER TABLE stats.ingest_job ADD CONSTRAINT native_isolation_failure "
                            f"CHECK (id <> {second.id} OR status <> 'done')"
                        )
                    )
                try:
                    assert await ingest.process(env, second.id) == ingest.STATUS.FAILED
                    assert await ingest.snapshot(env, match.id) == before
                    assert await ingest.success_events(env) == 1
                    async with sf() as session:
                        assert await derived_parity._facts(session, [match.id]) == before_facts
                        assert (
                            list(
                                await session.scalars(
                                    sa.select(models.AuditLog.id)
                                    .where(
                                        models.AuditLog.action == "stats.reparse",
                                        models.AuditLog.entity_id == match.id,
                                    )
                                    .order_by(models.AuditLog.id)
                                )
                            )
                            == before_reparse_ids
                        )
                        failed = await session.get(models.IngestJob, second.id)
                        assert failed.status == ingest.STATUS.FAILED and failed.error_message
                finally:
                    async with env.admin.begin() as connection:
                        await connection.execute(
                            sa.text("ALTER TABLE stats.ingest_job DROP CONSTRAINT native_isolation_failure")
                        )

                async with sf() as session:
                    await ingest.log_records_service.retry(session, second.id, workspace_id=env.workspace)
                assert await ingest.process(env, second.id) == ingest.STATUS.DONE
                replaced = await ingest.match_for_game(env)
                assert (replaced.id, replaced.revision, replaced.ingest_job_id) == (match.id, 2, second.id)
                after = await ingest.snapshot(env, match.id)
                assert after != before
                old_states = {state["subset"]: state for state in before}
                new_states = {state["subset"]: state for state in after}
                for subset in ("players", "team_scores", "event_body", "event_fight"):
                    assert old_states[subset] == new_states[subset]
                assert await ingest.success_events(env) == 2
                async with sf() as session:
                    after_facts = await derived_parity._facts(session, [match.id])
                    eliminations = [
                        row["value"]
                        for row in after_facts
                        if row["stat_code"] == "eliminations" and row["round"] == 0 and row["hero_id"] is None
                    ]
                    assert eliminations == [3.0] * 6
                    scores = dict(
                        (
                            await session.execute(
                                sa.select(
                                    models.StatsFact.encounter_team_id,
                                    models.StatsFact.value,
                                )
                                .join(models.StatDef)
                                .where(
                                    models.StatsFact.match_id == match.id,
                                    models.StatDef.code == "score",
                                )
                            )
                        ).all()
                    )
                    assert scores == dict(zip(env.participants, (2.0, 0.0), strict=True))
                    audit = await session.scalar(
                        sa.select(models.AuditLog)
                        .where(
                            models.AuditLog.action == "stats.reparse",
                            models.AuditLog.entity_id == match.id,
                        )
                        .order_by(models.AuditLog.id.desc())
                        .limit(1)
                    )
                    assert audit.before_json["stats_evidence"]["states"] == before
                    assert audit.after_json["stats_evidence"]["states"] == after
                    await _assert_transitions(session, initial_ids, {"stats.reparse", "stats.job_transition"})
                    before_repeat_audits = await _audit_ids(session)
                    assert (await session.get(models.EncounterGame, env.game)).result_version == 0
                    assert all(
                        score is None
                        for score in await session.scalars(
                            sa.select(models.EncounterGameTeam.score).where(
                                models.EncounterGameTeam.game_id == env.game
                            )
                        )
                    )
                assert await ingest.process(env, second.id) == ingest.STATUS.DONE
                assert await ingest.snapshot(env, match.id) == after
                assert await ingest.success_events(env) == 2
                async with sf() as session:
                    assert await derived_parity._facts(session, [match.id]) == after_facts
                    assert await _audit_ids(session) == before_repeat_audits

    asyncio.run(exercise())
