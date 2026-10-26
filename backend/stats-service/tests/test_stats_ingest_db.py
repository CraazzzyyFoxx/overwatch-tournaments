"""Task4 acceptance against migrated PostgreSQL and the actual Workshop pipeline.

Each case gets a disposable clone; the shared P3 fixture and its goldens are never
changed. Only S3/Redis/RabbitMQ transports are substituted, never database rows,
parsing, binding, observation writers, transitions, or evidence capture.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.disciplines.overwatch.enums import log_stats_index_map
from shared.repository.catalog import CatalogAliasMissRepository
from shared.repository.stats import IngestJobRepository, StatsMatchRepository
from shared.rpc.identity import rehydrate_user
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes
from shared.testing.stats_parity import (
    seed_native_sentinel,
)
from src import schemas
from src.core import db
from src.services.ingest import process as ingest_process
from src.services.match_logs import admin_reads, reaper, retention, uploads
from src.services.match_logs.log_records import compute_content_hash, log_records_service

HERO = "Ingest Ana"
MAP = "Ingest Ilios"
MODE = "Ingest Control"
STATUS = models.IngestJobStatus
ADMIN = rehydrate_user({"sub": 1, "username": "root", "is_superuser": True, "roles": ["admin"], "workspaces": []})


class RawStore:
    def __init__(self):
        self.objects = {}
        self.put_ok = True
        self.delete_ok = True
        self.deleted = []

    async def put_object(self, key, content):
        if not self.put_ok:
            return False
        self.objects[key] = content
        return True

    async def get_object(self, key):
        return self.objects.get(key)

    async def delete_object(self, key):
        if not self.delete_ok or key not in self.objects:
            return False
        del self.objects[key]
        self.deleted.append(key)
        return True


def workshop(*, eliminations=2, hero=HERO, map_name=MAP, extra="") -> bytes:
    lines = [f"0,match_start,0,{map_name},{MODE},Home,Away"]
    for side, prefix in (("Home", "H"), ("Away", "A")):
        lines.extend(f"0,player_joined,0,Ingest{prefix}{index},{side}" for index in range(3))
    lines.append("0,round_start,1,1")
    lines.extend([f"0,kill,20,Home,IngestH0,{hero},Away,IngestA0,{hero},0,100,False,False"] * 2)
    lines.extend([f"0,offensive_assist,21,Home,IngestEventOnly,{hero}"] * 2)
    lines.append(f"0,mercy_rez,22,Home,IngestH0,{hero},,IngestH1,{hero}")
    for side, prefix in (("Home", "H"), ("Away", "A")):
        for index in range(3):
            values = ["1", side, f"Ingest{prefix}{index}", hero] + ["0"] * 33
            for stat, value in (
                (enums.LogStatsName.Eliminations, eliminations),
                (enums.LogStatsName.Deaths, 1),
                (enums.LogStatsName.FinalBlows, 1),
                (enums.LogStatsName.HeroDamageDealt, 1000),
                (enums.LogStatsName.HeroTimePlayed, 60),
            ):
                values[log_stats_index_map[stat]] = str(value)
            lines.append("0,player_stat,60," + ",".join(values))
    lines.extend([f"0,meta,99,{extra}", "0,match_end,100,Home,2,0"])
    return ("\n".join(lines) + "\n").encode()


async def _game(session, env, *, position=1, map_id=None, cancelled=False):
    game = models.EncounterGame(
        encounter_id=env.encounter,
        position=position,
        map_id=map_id or env.map,
        state=enums.EncounterGameState.CANCELLED if cancelled else enums.EncounterGameState.PLANNED,
    )
    session.add(game)
    await session.flush()
    session.add_all(
        models.EncounterGameTeam(
            game_id=game.id,
            encounter_id=env.encounter,
            encounter_team_id=participant,
        )
        for participant in env.participants
    )
    await session.flush()
    return game.id


async def _seed(session, fixture_ids, *, with_game=True):
    workspace = models.Workspace(slug="ingest-native", name="Native ingest", disciplines_enabled=["overwatch", "lol"])
    session.add(workspace)
    await session.flush()
    tournament = models.Tournament(
        workspace_id=workspace.id,
        discipline="overwatch",
        name="Native ingest cup",
        slug="ingest-native-cup",
        division_grid_version_id=fixture_ids["grid_version"],
    )
    session.add(tournament)
    await session.flush()
    rule = models.ScoringRule(
        workspace_id=workspace.id,
        preset="wins",
        game_formula="win",
        end_formula="games >= best_of or max_wins * 2 > best_of",
    )
    mode = models.CatalogEntity(discipline="overwatch", kind="mode", slug="ingest-control", name=MODE, attrs={})
    hero = models.CatalogEntity(
        discipline="overwatch",
        kind="character",
        slug="ingest-ana",
        name=HERO,
        attrs={"class": "support"},
        aliases=["Ана-инжест"],
    )
    session.add_all([rule, mode, hero])
    await session.flush()
    map_ = models.CatalogEntity(
        discipline="overwatch",
        kind="map",
        slug="ingest-ilios",
        name=MAP,
        parent_id=mode.id,
        attrs={},
        aliases=["Илиос-инжест"],
    )
    encounter = models.Encounter(
        workspace_id=workspace.id,
        discipline="overwatch",
        tournament_id=tournament.id,
        scoring_rule_id=rule.id,
        name="Native series",
        slot_count=2,
        status=enums.EncounterStatus.OPEN,
    )
    session.add_all([map_, encounter])
    await session.flush()
    teams = [models.Team(tournament_id=tournament.id, name=name, balancer_name=name) for name in ("Home", "Away")]
    session.add_all(teams)
    await session.flush()
    # Workshop source order deliberately differs from live slots; historical
    # membership is valid for the game even if a seat later became inactive.
    seats = [
        models.EncounterTeam(
            encounter_id=encounter.id,
            tournament_id=tournament.id,
            team_id=team.id,
            name=team.name,
            slot=2 - index,
            active=index == 1,
        )
        for index, team in enumerate(teams)
    ]
    session.add_all(seats)
    await session.flush()
    session.add(models.User(name="Ingest id offset"))
    await session.flush()
    users, members = {}, {}
    for name in [*(f"IngestH{i}" for i in range(3)), *(f"IngestA{i}" for i in range(3)), "IngestEventOnly"]:
        user = models.User(name=name)
        session.add(user)
        await session.flush()
        member = models.WorkspaceMember(
            workspace_id=workspace.id,
            player_id=user.id,
            removed_at=datetime.now(UTC) if name == "IngestEventOnly" else None,
        )
        session.add(member)
        session.add(
            models.SocialAccount(
                user_id=user.id,
                provider="battlenet",
                username=name + "#1234",
                username_normalized=(name + "#1234").lower(),
                is_primary=True,
            )
        )
        await session.flush()
        users[name], members[name] = user.id, member.id
        if name != "IngestEventOnly":
            roster = models.Player(
                tournament_id=tournament.id,
                workspace_member_id=member.id,
                team_id=teams[0 if name.startswith("IngestH") else 1].id,
                name=name,
                rank=800,
            )
            session.add(roster)
            await session.flush()
            session.add(
                models.PlayerRole(
                    player_id=roster.id, role_id=fixture_ids["role_support"], dimension_id=fixture_ids["role_dimension"]
                )
            )
            seat = seats[0 if name.startswith("IngestH") else 1]
            snapshot = models.EncounterTeamMember(
                encounter_id=encounter.id,
                encounter_team_id=seat.id,
                active=seat.active,
                workspace_member_id=member.id,
                display_name_snapshot=name,
                rank=800,
            )
            session.add(snapshot)
            await session.flush()
            session.add(
                models.EncounterTeamMemberRole(
                    team_member_id=snapshot.id,
                    role_id=fixture_ids["role_support"],
                    dimension_id=fixture_ids["role_dimension"],
                )
            )
    env = SimpleNamespace(
        workspace=workspace.id,
        tournament=tournament.id,
        encounter=encounter.id,
        map=map_.id,
        hero=hero.id,
        participants=[seat.id for seat in seats],
        teams=[team.id for team in teams],
        users=users,
        members=members,
    )
    env.game = await _game(session, env) if with_game else None
    await session.commit()
    return env


@asynccontextmanager
async def environment(database, monkeypatch, *, with_game=True, restricted=False):
    url, fixture_ids = database
    async_url = make_url(url).set(drivername="postgresql+asyncpg")
    admin = create_async_engine(async_url)
    sf = async_sessionmaker(admin, expire_on_commit=False)
    role = "p4_ingest_" + uuid4().hex[:12] if restricted else None
    worker = None
    try:
        async with sf() as session:
            env = await _seed(session, fixture_ids, with_game=with_game)
        if role:
            async with admin.begin() as connection:
                await connection.execute(sa.text(f'CREATE ROLE "{role}"'))
                schemas = (
                    (
                        await connection.execute(
                            sa.text(
                                "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
                                "AND nspname <> 'information_schema'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for schema in schemas:
                    quoted = '"' + schema.replace('"', '""') + '"'
                    await connection.execute(sa.text(f'GRANT USAGE ON SCHEMA {quoted} TO "{role}"'))
                    await connection.execute(sa.text(f'GRANT ALL ON ALL TABLES IN SCHEMA {quoted} TO "{role}"'))
                    await connection.execute(sa.text(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA {quoted} TO "{role}"'))
            worker = create_async_engine(async_url, connect_args={"server_settings": {"role": role}})
            sf = async_sessionmaker(worker, expire_on_commit=False)
        env.sf, env.admin, env.raw, env.fixture_ids = sf, admin, RawStore(), fixture_ids
        monkeypatch.setattr(db, "async_session_maker", sf)
        yield env
    finally:
        if worker:
            await worker.dispose()
        if role:
            async with admin.begin() as connection:
                await connection.execute(sa.text(f'DROP OWNED BY "{role}"'))
                await connection.execute(sa.text(f'DROP ROLE "{role}"'))
        await admin.dispose()


async def upload(env, content=None, *, filename="same.log", **kwargs):
    async with env.sf() as session:
        return await uploads.upload_service.store_uploaded_log_bytes(
            session,
            s3=env.raw,
            tournament_id=env.tournament,
            filename=filename,
            content=content or workshop(),
            source="upload",
            uploader_id=env.users["IngestH0"],
            **kwargs,
        )


async def process(env, job_id):
    async with env.sf() as session:
        return await ingest_process.process_ingest_job(session, job_id, env.raw, is_raise=False)


async def match_for_game(env):
    async with env.sf() as session:
        return await session.scalar(sa.select(models.StatsMatch).where(models.StatsMatch.encounter_game_id == env.game))


async def snapshot(env, match_id):
    async with env.sf() as session:
        return await capture_stats_evidence(session, scopes=owner_scopes("match", (match_id,)))


async def success_events(env):
    async with env.sf() as session:
        return await session.scalar(
            sa.select(sa.func.count())
            .select_from(models.EventOutbox)
            .where(
                sa.cast(models.EventOutbox.payload_json["changed_tables"], JSONB).contains(["stats.match"]),
                models.EventOutbox.payload_json["tournament_id"].as_integer() == env.tournament,
            )
        )


def test_actual_workshop_native_ingest_runs_as_a_non_owner_role(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch, restricted=True) as env:
            job = await upload(env, filename="x" * 496 + ".log")
            assert job.raw_ref == f"logs/{env.tournament}/{compute_content_hash(workshop())}"
            assert env.raw.objects[job.raw_ref] == workshop()
            assert await process(env, job.id) == STATUS.DONE
            match = await match_for_game(env)
            assert (match.workspace_id, match.discipline, match.ingest_job_id, match.revision) == (
                env.workspace,
                "overwatch",
                job.id,
                1,
            )
            async with env.sf() as session:
                teams = (
                    await session.execute(
                        sa.select(models.StatsMatchTeam.encounter_team_id, models.StatsMatchTeam.source_position)
                        .where(models.StatsMatchTeam.match_id == match.id)
                        .order_by(models.StatsMatchTeam.source_position)
                    )
                ).all()
                assert teams == list(zip(env.participants, (1, 2), strict=True))
                players = list(
                    await session.scalars(
                        sa.select(models.StatsMatchPlayer).where(models.StatsMatchPlayer.match_id == match.id)
                    )
                )
                assert {row.workspace_member_id for row in players} == set(env.members.values())
                event_only = next(row for row in players if row.handle_snapshot == "IngestEventOnly")
                assert event_only.workspace_member_id != env.users["IngestEventOnly"]
                assert event_only.observed_role_id is None
                assert {row.observed_role_id for row in players if row is not event_only} == {
                    env.fixture_ids["role_support"]
                }
                assert (
                    await session.get(models.WorkspaceMember, event_only.workspace_member_id)
                ).removed_at is not None
                assert not (await session.get(models.EncounterTeam, env.participants[0])).active
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
                kills = list(
                    await session.scalars(
                        sa.select(models.StatsEvent)
                        .join(models.EventType)
                        .where(models.StatsEvent.match_id == match.id, models.EventType.code == "kill")
                    )
                )
                assert all(row.actor_member_id == env.members["IngestH0"] and row.data["fight"] == 1 for row in kills)
                scores = dict(
                    (
                        await session.execute(
                            sa.select(models.StatsFact.encounter_team_id, models.StatsFact.value)
                            .join(models.StatDef)
                            .where(models.StatsFact.match_id == match.id, models.StatDef.code == "score")
                        )
                    ).all()
                )
                assert scores == dict(zip(env.participants, (2.0, 0.0), strict=True))
                raw_facts = (
                    await session.execute(
                        sa.select(
                            models.StatsFact.segment,
                            models.StatsFact.entity_id,
                            models.StatsFact.value,
                        )
                        .join(models.StatDef)
                        .where(
                            models.StatsFact.match_id == match.id,
                            models.StatsFact.workspace_member_id == env.members["IngestH0"],
                            models.StatDef.code == enums.LogStatsName.Eliminations.value,
                        )
                    )
                ).all()
                assert set(raw_facts) == {(0, None, 2.0), (0, env.hero, 2.0), (1, None, 2.0), (1, env.hero, 2.0)}
                assert list(
                    await session.scalars(
                        sa.select(models.StatsSegment.segment).where(
                            models.StatsSegment.match_id == match.id,
                        )
                    )
                ) == [1]
                assert (await session.get(models.EncounterGame, env.game)).result_version == 0
                assert all(
                    value is None
                    for value in await session.scalars(
                        sa.select(models.EncounterGameTeam.score).where(models.EncounterGameTeam.game_id == env.game)
                    )
                )
            assert await success_events(env) == 1

    asyncio.run(run())


def test_actual_byte_dedup_races_scope_and_storage_failure(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            jobs = await asyncio.wait_for(asyncio.gather(upload(env), upload(env, filename="renamed.log")), 15)
            assert jobs[0].id == jobs[1].id
            job = jobs[0]
            changed = await upload(env, workshop(extra="new bytes"))
            assert changed.id != job.id and changed.filename == "same.log" and changed.raw_ref != job.raw_ref
            async with env.sf() as session:
                current = await session.get(models.IngestJob, job.id)
                await log_records_service.transition(session, current, STATUS.PROCESSING)
                await session.commit()
            duplicate = await upload(env, filename="new-name.log")
            assert (
                duplicate.status == STATUS.PROCESSING and duplicate.attempts == 1 and duplicate.filename == job.filename
            )
            async with env.sf() as session:
                another = models.Tournament(
                    workspace_id=env.workspace, discipline="overwatch", name="Other intent", slug="other-intent"
                )
                foreign = models.Tournament(
                    workspace_id=env.fixture_ids["workspace_other"],
                    discipline="overwatch",
                    name="Foreign intent",
                    slug="foreign-intent",
                )
                session.add_all([another, foreign])
                await session.commit()
                another_id, foreign_id = another.id, foreign.id
            async with env.sf() as session:
                with pytest.raises(BaseAPIException, match="stats_upload_scope_conflict"):
                    await uploads.upload_service.store_uploaded_log_bytes(
                        session,
                        s3=env.raw,
                        tournament_id=another_id,
                        filename="same.log",
                        content=workshop(),
                        source="upload",
                    )
            async with env.sf() as session:
                other = await uploads.upload_service.store_uploaded_log_bytes(
                    session,
                    s3=env.raw,
                    tournament_id=foreign_id,
                    filename="same.log",
                    content=workshop(),
                    source="upload",
                )
                assert other.id != job.id and other.workspace_id != env.workspace
            env.raw.put_ok = False
            async with env.sf() as session:
                before = await session.scalar(sa.select(sa.func.count()).select_from(models.IngestJob))
                with pytest.raises(BaseAPIException):
                    await uploads.upload_service.store_uploaded_log_bytes(
                        session,
                        s3=env.raw,
                        tournament_id=env.tournament,
                        filename="broken.log",
                        content=workshop(extra="put failure"),
                        source="upload",
                    )
                assert await session.scalar(sa.select(sa.func.count()).select_from(models.IngestJob)) == before

    asyncio.run(run())


def test_awaiting_link_is_not_success_and_explicit_game_retry_resolves_ambiguity(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch, with_game=False) as env:
            job = await upload(env)
            assert await process(env, job.id) == STATUS.AWAITING_LINK
            assert await success_events(env) == 0
            async with env.sf() as session:
                assert not await session.scalar(
                    sa.select(models.StatsMatch.id).where(models.StatsMatch.ingest_job_id == job.id)
                )
                env.game = await _game(session, env)
                await _game(session, env, position=2)
                await _game(session, env, position=3, cancelled=True)
                await session.commit()
                await log_records_service.retry(session, job.id, workspace_id=env.workspace)
            assert await process(env, job.id) == STATUS.AWAITING_LINK
            async with env.sf() as session:
                row = await log_records_service.retry(
                    session, job.id, workspace_id=env.workspace, encounter_game_id=env.game
                )
                assert row.hint_encounter_id == env.encounter and row.hint_encounter_game_id == env.game
            assert await process(env, job.id) == STATUS.DONE
            assert (await match_for_game(env)).ingest_job_id == job.id
            async with env.sf() as session:
                with pytest.raises(BaseAPIException):
                    await log_records_service.retry(session, job.id, workspace_id=env.fixture_ids["workspace_other"])
                await session.rollback()
                with pytest.raises(BaseAPIException):
                    await log_records_service.retry(
                        session, job.id, workspace_id=env.workspace, encounter_id=env.fixture_ids["encounter_other"]
                    )

    asyncio.run(run())


def test_an_encounter_with_no_live_game_takes_the_log_on_its_cancelled_position(stats_parity_database, monkeypatch):
    """A series entered whole leaves its encounter only the cancelled position its room retired (MoonRise Mix Vol.5,
    encounter 6845). A log the operator attaches to that encounter is observed there; a search never looks at a
    cancelled position, and one live game anywhere in the encounter keeps the cancelled ones out."""

    async def run():
        async with environment(stats_parity_database, monkeypatch, with_game=False) as env:
            async with env.sf() as session:
                env.game = await _game(session, env, cancelled=True)
                await session.commit()
            job = await upload(env)
            assert await process(env, job.id) == STATUS.AWAITING_LINK
            async with env.sf() as session:
                await log_records_service.retry(session, job.id, workspace_id=env.workspace, encounter_id=env.encounter)
            assert await process(env, job.id) == STATUS.DONE
            assert (await match_for_game(env)).ingest_job_id == job.id

            async with env.sf() as session:
                await _game(session, env, position=2, map_id=env.fixture_ids["map_other"])
                await session.commit()
            later = await upload(env, workshop(extra="later"), filename="later.log")
            async with env.sf() as session:
                await log_records_service.retry(
                    session, later.id, workspace_id=env.workspace, encounter_id=env.encounter
                )
            assert await process(env, later.id) == STATUS.AWAITING_LINK
            assert (await match_for_game(env)).ingest_job_id == job.id

    asyncio.run(run())


@pytest.mark.parametrize("refusal", ["missing", "conflict", "unverified", "unbound", "shared"])
def test_historical_retry_and_worker_preserve_observations(stats_parity_database, monkeypatch, refusal):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env)
            assert await process(env, job.id) == STATUS.DONE
            match = await match_for_game(env)
            async with env.sf() as session:
                current = await session.get(models.IngestJob, job.id)
                current.external_id = f"legacy:log_processing.record:{job.id}"
                if refusal in {"missing", "conflict", "unverified"}:
                    current.raw_status = models.RawSourceStatus(refusal)
                if refusal == "unbound":
                    await session.execute(
                        sa.update(models.StatsMatch)
                        .where(models.StatsMatch.id == match.id)
                        .values(encounter_game_id=None)
                    )
                if refusal == "shared":
                    session.add(
                        models.StatsMatch(
                            workspace_id=env.workspace,
                            discipline="overwatch",
                            encounter_id=env.encounter,
                            encounter_game_id=None,
                            map_entity_id=env.map,
                            ingest_job_id=job.id,
                            revision=7,
                        )
                    )
                await session.commit()
            before = await snapshot(env, match.id)
            async with env.sf() as session:
                with pytest.raises(BaseAPIException):
                    await log_records_service.retry(session, job.id, workspace_id=env.workspace)
            assert await snapshot(env, match.id) == before
            async with env.sf() as session:
                requeued = await log_records_service.requeue_tournament(session, env.tournament)
                assert job.id not in requeued.queue and requeued.replay == {}
                assert (await session.get(models.IngestJob, job.id)).status == STATUS.DONE
                # An already queued delivery must enforce the same guard as retry.
                current = await session.get(models.IngestJob, job.id)
                await log_records_service.transition(session, current, STATUS.PENDING)
                await session.commit()
            assert await process(env, job.id) == STATUS.FAILED
            assert await snapshot(env, match.id) == before
            async with env.sf() as session:
                preserved = await session.get(models.StatsMatch, match.id)
                assert (preserved.revision, preserved.ingest_job_id) == (1, job.id)
                count = await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(models.StatsMatch)
                    .where(models.StatsMatch.ingest_job_id == job.id)
                )
                assert count == (2 if refusal == "shared" else 1)

    asyncio.run(run())


def test_historical_binding_is_reparsed_only_by_its_own_available_source(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            original = await upload(env)
            assert await process(env, original.id) == STATUS.DONE
            match = await match_for_game(env)
            async with env.sf() as session:
                job = await session.get(models.IngestJob, original.id)
                job.external_id = f"legacy:log_processing.record:{job.id}"
                # Historical hashes keep their exact spelling.
                job.content_hash = job.content_hash.upper()
                await session.commit()
            before = await snapshot(env, match.id)
            replacement = await upload(env, workshop(eliminations=99))
            assert await process(env, replacement.id) == STATUS.FAILED
            assert await snapshot(env, match.id) == before
            async with env.sf() as session:
                with pytest.raises(BaseAPIException, match="reparse_required"):
                    await log_records_service.retry(session, original.id, workspace_id=env.workspace)
                await session.rollback()
                await ingest_process.reparse_ingest_job(
                    session, job_id=original.id, expected_revision=1, user=ADMIN, s3=env.raw
                )
            assert await process(env, original.id) == STATUS.DONE
            preserved = await match_for_game(env)
            assert (preserved.id, preserved.encounter_id, preserved.revision, preserved.ingest_job_id) == (
                match.id,
                env.encounter,
                2,
                original.id,
            )
            async with env.sf() as session:
                assert (await session.get(models.IngestJob, original.id)).content_hash == original.content_hash.upper()

    asyncio.run(run())


def test_history_reports_real_owner_binding_and_raw_state_for_historical_reference(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            uploaded = await upload(env)
            assert await process(env, uploaded.id) == STATUS.DONE
            match = await match_for_game(env)
            async with env.sf() as session:
                job = await session.get(models.IngestJob, uploaded.id)
                job.source_kind = "historical_reference"
                job.external_id = f"legacy:matches.match:{match.id}"
                job.raw_status = models.RawSourceStatus.MISSING
                job.content_hash = None
                job.uploader_user_id = None
                job.attempts = 0
                job.started_at = job.finished_at = None
                job.hint_encounter_id = None
                job.hint_encounter_game_id = env.game
                await session.execute(
                    sa.update(models.StatsMatch).where(models.StatsMatch.id == match.id).values(encounter_game_id=None)
                )
                await session.commit()
                rows = (
                    await session.execute(
                        admin_reads.history_query().where(
                            models.IngestJob.id == job.id,
                            *admin_reads.history_scope_conditions(
                                workspace_id=env.workspace, tournament_id=env.tournament, encounter_id=env.encounter
                            ),
                        )
                    )
                ).all()
                assert len(rows) == 1
                item = schemas.LogRecordRead.model_validate(admin_reads._record_to_dict(*rows[0]))
                assert item.source == "historical_reference"
                assert item.raw_status == models.RawSourceStatus.MISSING and not item.raw_available
                assert (item.attached_encounter_id, item.attached_encounter_game_id) == (env.encounter, None)
                assert item.attempts == 0 and item.uploader_name is None
                assert item.started_at is None and item.finished_at is None

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["fact_insert", "job_success"])
def test_reparse_failure_rolls_back_observations_success_outbox_and_evidence(
    stats_parity_database, monkeypatch, failure
):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            first = await upload(env)
            assert await process(env, first.id) == STATUS.DONE
            match = await match_for_game(env)
            before = await snapshot(env, match.id)
            queued = await success_events(env)
            second = await upload(env, workshop(eliminations=1234567))
            table = "stats.fact" if failure == "fact_insert" else "stats.ingest_job"
            predicate = "value <> 1234567" if failure == "fact_insert" else f"id <> {second.id} OR status <> 'done'"
            async with env.admin.begin() as connection:
                await connection.execute(
                    sa.text(f"ALTER TABLE {table} ADD CONSTRAINT ingest_force_failure CHECK ({predicate})")
                )
            assert await process(env, second.id) == STATUS.FAILED
            assert await snapshot(env, match.id) == before
            assert await success_events(env) == queued
            async with env.sf() as session:
                failed = await session.get(models.IngestJob, second.id)
                assert failed.status == STATUS.FAILED and failed.error_message and failed.attempts == 1
                assert (await session.get(models.StatsMatch, match.id)).ingest_job_id == first.id
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(models.AuditLog)
                        .where(
                            models.AuditLog.action == "stats.reparse",
                            models.AuditLog.entity_id == match.id,
                        )
                    )
                    == 1
                )
            async with env.admin.begin() as connection:
                await connection.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT ingest_force_failure"))
            async with env.sf() as session:
                await log_records_service.retry(session, second.id, workspace_id=env.workspace)
            assert await process(env, second.id) == STATUS.DONE
            replaced = await match_for_game(env)
            assert (replaced.id, replaced.revision, replaced.ingest_job_id) == (match.id, 2, second.id)
            async with env.sf() as session:
                assert (
                    await session.scalar(
                        sa.select(sa.func.count())
                        .select_from(models.AuditLog)
                        .where(
                            models.AuditLog.action == "stats.reparse",
                            models.AuditLog.entity_id == match.id,
                        )
                    )
                    == 2
                )
                assert set(
                    await session.scalars(
                        sa.select(models.StatsFact.value)
                        .join(models.StatDef)
                        .where(
                            models.StatsFact.match_id == match.id,
                            models.StatDef.code == enums.LogStatsName.Eliminations.value,
                        )
                    )
                ) == {1234567.0}
            assert await process(env, second.id) == STATUS.DONE
            assert (await match_for_game(env)).revision == 2

    asyncio.run(run())


def test_parallel_job_deliveries_and_distinct_revisions_serialize(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            first = await upload(env)
            outcomes = await asyncio.wait_for(asyncio.gather(process(env, first.id), process(env, first.id)), 30)
            assert STATUS.DONE in outcomes
            assert all(status in {STATUS.DONE, STATUS.PROCESSING} for status in outcomes)
            assert (await match_for_game(env)).revision == 1
            second, third = await asyncio.gather(
                upload(env, workshop(extra="second")), upload(env, workshop(extra="third"))
            )
            assert (
                await asyncio.wait_for(asyncio.gather(process(env, second.id), process(env, third.id)), 30)
                == [STATUS.DONE] * 2
            )
            assert (await match_for_game(env)).revision == 3

    asyncio.run(run())


@pytest.mark.parametrize("old_outcome", ["download_failure", "observations", "awaiting"])
def test_recovered_retry_claim_rejects_same_attempt_number_from_old_worker(
    stats_parity_database, monkeypatch, old_outcome
):
    async def run():
        async with environment(stats_parity_database, monkeypatch, with_game=old_outcome != "awaiting") as env:
            job = await upload(env)
            entered = [asyncio.Event(), asyncio.Event()]
            release = [asyncio.Event(), asyncio.Event()]
            reads = 0
            get_raw = env.raw.get_object

            async def delayed_raw(key):
                nonlocal reads
                index = reads
                reads += 1
                assert index < 2, "An active duplicate must not borrow the current claim"
                entered[index].set()
                await release[index].wait()
                if index == 0 and old_outcome == "download_failure":
                    raise RuntimeError("Delayed old download failed")
                return await get_raw(key)

            monkeypatch.setattr(env.raw, "get_object", delayed_raw)
            old_worker = asyncio.create_task(process(env, job.id))
            new_worker = None
            try:
                await asyncio.wait_for(entered[0].wait(), 10)
                async with env.sf() as session:
                    original = await session.get(models.IngestJob, job.id)
                    old_claim = (original.attempts, original.started_at)
                    assert original.status == STATUS.PROCESSING and old_claim[0] == 1
                    assert old_claim[1] is not None
                    recovered, exhausted = await reaper._claim_stalled(
                        session,
                        now=old_claim[1] + timedelta(minutes=2),
                        pending_after_seconds=60,
                        processing_after_seconds=60,
                        max_attempts=3,
                        limit=100,
                    )
                    assert job.id in [item.record_id for item in recovered]
                    assert job.id not in exhausted
                    retried = await log_records_service.retry(session, job.id, workspace_id=env.workspace)
                    assert retried.status == STATUS.PENDING and retried.attempts == 0

                new_worker = asyncio.create_task(process(env, job.id))
                await asyncio.wait_for(entered[1].wait(), 10)
                async with env.sf() as session:
                    current = await session.get(models.IngestJob, job.id)
                    new_claim = (current.attempts, current.started_at)
                    assert new_claim[0] == old_claim[0] == 1
                    assert new_claim[1] != old_claim[1]
                    before = await capture_stats_evidence(session, scopes=owner_scopes("job", (job.id,)))

                # This is a real second delivery while B owns the claim: it
                # must neither start another raw read nor publish a completion.
                assert await process(env, job.id) == STATUS.PROCESSING
                assert reads == 2
                release[0].set()
                message = (
                    "Delayed old download failed"
                    if old_outcome == "download_failure"
                    else "Ingest claim was superseded"
                )
                if old_outcome == "download_failure":
                    with pytest.raises(RuntimeError, match=message):
                        await asyncio.wait_for(old_worker, 10)
                else:
                    # A superseded attempt changes nothing and just acknowledges: the job is still being processed.
                    assert await asyncio.wait_for(old_worker, 10) == STATUS.PROCESSING
                async with env.sf() as session:
                    assert await capture_stats_evidence(session, scopes=owner_scopes("job", (job.id,))) == before
                    assert not await session.scalar(
                        sa.select(models.StatsMatch.id).where(
                            models.StatsMatch.workspace_id == env.workspace,
                        )
                    )
                    assert (
                        await session.scalar(
                            sa.select(sa.func.count())
                            .select_from(models.AuditLog)
                            .where(
                                models.AuditLog.workspace_id == env.workspace,
                                models.AuditLog.action == "stats.reparse",
                            )
                        )
                        == 0
                    )
                assert await success_events(env) == 0

                release[1].set()
                expected = STATUS.AWAITING_LINK if old_outcome == "awaiting" else STATUS.DONE
                assert await asyncio.wait_for(new_worker, 30) == expected
                async with env.sf() as session:
                    finished = await session.get(models.IngestJob, job.id)
                    assert (finished.attempts, finished.started_at) == new_claim
                    assert finished.status == expected and finished.finished_at is not None
                if expected == STATUS.DONE:
                    assert (await match_for_game(env)).revision == 1
                    assert await success_events(env) == 1
                assert await process(env, job.id) == expected
                assert reads == 2
            finally:
                for event in release:
                    event.set()
                tasks = [task for task in (old_worker, new_worker) if task is not None]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("first_lock", ["job", "encounter"])
def test_duplicate_upload_never_holds_parent_while_waiting_for_processor(
    stats_parity_database, monkeypatch, first_lock
):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env, attached_encounter_id=env.encounter)
            async with env.sf() as processor:
                model, key = (models.IngestJob, job.id) if first_lock == "job" else (models.Encounter, env.encounter)
                await processor.execute(sa.select(model.id).where(model.id == key).with_for_update())
                duplicate = asyncio.create_task(upload(env, attached_encounter_id=env.encounter))
                try:
                    if first_lock == "job":
                        # The duplicate may reach its lock first; it must never
                        # retain a parent SHARE lock while blocked on this job.
                        await asyncio.sleep(0.05)
                        await asyncio.wait_for(
                            processor.execute(
                                sa.select(models.Encounter.id)
                                .where(models.Encounter.id == env.encounter)
                                .with_for_update()
                            ),
                            5,
                        )
                    else:
                        await asyncio.wait_for(duplicate, 5)
                        await processor.execute(
                            sa.select(models.IngestJob.id).where(models.IngestJob.id == job.id).with_for_update()
                        )
                    await processor.commit()
                    assert (await asyncio.wait_for(duplicate, 5)).id == job.id
                finally:
                    if not duplicate.done():
                        duplicate.cancel()
                        await asyncio.gather(duplicate, return_exceptions=True)

    asyncio.run(run())


def test_link_retry_waits_for_parent_without_holding_job(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env)

            async def link():
                async with env.sf() as session:
                    return await log_records_service.retry(
                        session,
                        job.id,
                        workspace_id=env.workspace,
                        encounter_id=env.encounter,
                        encounter_game_id=env.game,
                    )

            async with env.sf() as owner:
                await owner.execute(
                    sa.select(models.Encounter.id)
                    .where(
                        models.Encounter.id == env.encounter,
                    )
                    .with_for_update()
                )
                retry = asyncio.create_task(link())
                try:
                    await asyncio.sleep(0.05)
                    await asyncio.wait_for(
                        owner.execute(
                            sa.select(models.IngestJob.id)
                            .where(
                                models.IngestJob.id == job.id,
                            )
                            .with_for_update()
                        ),
                        5,
                    )
                    await owner.commit()
                    linked = await asyncio.wait_for(retry, 5)
                    assert (linked.hint_encounter_id, linked.hint_encounter_game_id) == (env.encounter, env.game)
                finally:
                    if not retry.done():
                        retry.cancel()
                        await asyncio.gather(retry, return_exceptions=True)

    asyncio.run(run())


def test_alias_failure_retains_native_breadcrumb_then_retry_uses_alias(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env, workshop(hero="Unknown translated hero"))
            assert await process(env, job.id) == STATUS.FAILED
            async with env.sf() as session:
                miss = await session.scalar(
                    sa.select(models.CatalogAliasMiss).where(
                        models.CatalogAliasMiss.raw_name == "Unknown translated hero"
                    )
                )
                assert miss.last_ingest_job_id == job.id
                assert not await session.scalar(
                    sa.select(models.StatsMatch.id).where(models.StatsMatch.encounter_game_id == env.game)
                )
                hero = await session.get(models.CatalogEntity, env.hero)
                hero.aliases = [*hero.aliases, "Unknown translated hero"]
                await session.commit()
                await log_records_service.retry(session, job.id, workspace_id=env.workspace)
            assert await process(env, job.id) == STATUS.DONE

    asyncio.run(run())


def test_reaper_uses_native_attempts_skip_locked_and_never_reclaims_awaiting(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            jobs = [await upload(env, workshop(extra=str(index))) for index in range(3)]
            now = datetime.now(UTC)
            old = now - timedelta(days=3)
            async with env.sf() as session:
                for index, original in enumerate(jobs):
                    row = await session.get(models.IngestJob, original.id)
                    row.status = (STATUS.PENDING, STATUS.PROCESSING, STATUS.AWAITING_LINK)[index]
                    row.attempts = (1, 3, 0)[index]
                    row.updated_at = old
                    row.started_at = old if index == 1 else None
                await session.commit()
            async with env.sf() as locked:
                await locked.execute(
                    sa.select(models.IngestJob).where(models.IngestJob.id == jobs[0].id).with_for_update()
                )
                async with env.sf() as session:
                    requeued, exhausted = await reaper._claim_stalled(
                        session,
                        now=now,
                        pending_after_seconds=60,
                        processing_after_seconds=60,
                        max_attempts=3,
                        limit=100,
                    )
                    assert jobs[0].id not in [item.record_id for item in requeued]
                    assert jobs[1].id in exhausted
                await locked.rollback()
            async with env.sf() as session:
                requeued, _ = await reaper._claim_stalled(
                    session, now=now, pending_after_seconds=60, processing_after_seconds=60, max_attempts=3, limit=100
                )
                assert jobs[0].id in [item.record_id for item in requeued]
                pending = await session.get(models.IngestJob, jobs[0].id)
                assert pending.status == STATUS.PENDING and pending.attempts == 1 and pending.started_at is None
                assert (await session.get(models.IngestJob, jobs[2].id)).status == STATUS.AWAITING_LINK

    asyncio.run(run())


def test_retention_preserves_linked_job_shared_raw_and_storage_failures(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            linked = await upload(env)
            assert await process(env, linked.id) == STATUS.DONE
            shared = await upload(env, workshop(extra="shared"))
            orphan = await upload(env, workshop(extra="orphan"))
            old = datetime.now(UTC) - timedelta(days=3650)
            async with env.sf() as session:
                for original in (linked, shared, orphan):
                    row = await session.get(models.IngestJob, original.id)
                    await log_records_service.transition(session, row, STATUS.FAILED, error_message="expired", now=old)
                imported = models.IngestJob(
                    workspace_id=env.workspace,
                    discipline="overwatch",
                    source_kind="import",
                    external_id="historical-raw",
                    content_hash=shared.content_hash,
                    filename="historical.log",
                    raw_ref=shared.raw_ref,
                    hint_tournament_id=env.tournament,
                    status=STATUS.DONE,
                )
                session.add(imported)
                await CatalogAliasMissRepository().record_miss(
                    session, "overwatch", "character", ["retention miss"], ingest_job_id=orphan.id
                )
                await session.commit()
            monkeypatch.setattr(retention, "acquire_distributed_lock", AsyncMock(return_value="owned"))
            monkeypatch.setattr(retention, "release_distributed_lock", AsyncMock())
            env.raw.delete_ok = False
            assert await retention.purge_expired_failed_logs(redis=object(), s3=env.raw, session_factory=env.sf) == 0
            env.raw.delete_ok = True
            assert await retention.purge_expired_failed_logs(redis=object(), s3=env.raw, session_factory=env.sf) == 1
            async with env.sf() as session:
                assert await session.get(models.IngestJob, orphan.id) is None
                assert await session.get(models.IngestJob, linked.id) is not None
                assert await session.get(models.IngestJob, shared.id) is not None
                assert (
                    await session.scalar(
                        sa.select(models.CatalogAliasMiss).where(models.CatalogAliasMiss.raw_name == "retention miss")
                    )
                ).last_ingest_job_id is None
                assert (
                    await session.scalar(
                        sa.select(models.StatsMatch).where(models.StatsMatch.encounter_game_id == env.game)
                    )
                ).ingest_job_id == linked.id
            assert env.raw.deleted == [orphan.raw_ref]
            assert env.raw.objects[linked.raw_ref] == workshop()

    asyncio.run(run())


def test_history_and_bulk_requeue_use_native_scope_and_exact_raw_refs(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env, filename="literal_%_name.log")
            async with env.sf() as session:
                imported = models.IngestJob(
                    workspace_id=env.workspace,
                    discipline="overwatch",
                    source_kind="import",
                    external_id="legacy-path",
                    filename="legacy.log",
                    raw_ref="historic/preserved/path.log",
                    content_hash=compute_content_hash(workshop(extra="legacy")),
                    hint_tournament_id=env.tournament,
                    status=STATUS.FAILED,
                    error_message="old failure",
                    attempts=4,
                )
                session.add(imported)
                await session.commit()
                rows = (
                    await session.execute(
                        admin_reads.history_query().where(
                            *admin_reads.history_scope_conditions(
                                workspace_id=env.workspace, tournament_id=env.tournament, encounter_id=None
                            ),
                            admin_reads.history_search_condition("_%_"),
                        )
                    )
                ).all()
                assert [admin_reads._record_to_dict(*row)["id"] for row in rows] == [job.id]
                item = admin_reads._record_to_dict(*rows[0])
                assert item["attached_encounter_game_id"] is None
                await log_records_service.retry(
                    session,
                    job.id,
                    workspace_id=env.workspace,
                    encounter_id=env.encounter,
                    encounter_game_id=env.game,
                )
                linked_row = (
                    await session.execute(admin_reads.history_query().where(models.IngestJob.id == job.id))
                ).one()
                linked = admin_reads._record_to_dict(*linked_row)
                assert (linked["attached_encounter_id"], linked["attached_encounter_game_id"]) == (
                    env.encounter,
                    env.game,
                )
                ids = (await log_records_service.requeue_tournament(session, env.tournament)).queue
                assert set(ids) == {job.id, imported.id}
                # The imported job never had a request: the requeue committed one with its reset.
                requested = await session.scalars(
                    sa.select(models.EventOutbox.payload_json["ingest_job_id"].as_integer()).where(
                        models.EventOutbox.event_type == "process_ingest_job"
                    )
                )
                assert imported.id in set(requested)
                assert imported.raw_ref == "historic/preserved/path.log"
                assert imported.status == STATUS.PENDING and imported.attempts == 0 and imported.error_message is None

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["missing", "utf8", "empty_parser", "oversize", "wrong_hash"])
def test_preparse_failures_finish_the_actual_claim(stats_parity_database, monkeypatch, failure):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            raw = b"\xff" if failure == "utf8" else b"0,meta,0,not a log\n" if failure == "empty_parser" else workshop()
            async with env.sf() as session:
                job, created = await IngestJobRepository().create_or_get(
                    session,
                    workspace_id=env.workspace,
                    discipline="overwatch",
                    source_kind="manual",
                    external_id=None,
                    content_hash=compute_content_hash(raw),
                    filename=f"{failure}.log",
                    raw_ref=f"test/{failure}",
                    document_ref=None,
                    uploader_user_id=None,
                    api_key_id=None,
                    hint_tournament_id=env.tournament,
                    hint_encounter_id=None,
                    hint_encounter_game_id=None,
                )
                assert created
                await session.commit()
            if failure != "missing":
                env.raw.objects[job.raw_ref] = b"corrupted" if failure == "wrong_hash" else raw
            if failure == "oversize":
                monkeypatch.setattr(ingest_process.settings, "max_match_log_bytes", 1)
            assert await process(env, job.id) == STATUS.FAILED
            async with env.sf() as session:
                current = await session.get(models.IngestJob, job.id)
                assert current.attempts == 1 and current.started_at and current.finished_at and current.error_message
            assert await success_events(env) == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad_owner",
    [
        "foreign_member",
        "unknown_stat",
        "foreign_stat",
        "wrong_entity_kind",
        "foreign_entity",
        "non_finite",
        "foreign_endpoint",
    ],
)
def test_native_validation_rejects_bad_observations_before_deleting_previous_revision(
    stats_parity_database, monkeypatch, bad_owner
):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env)
            assert await process(env, job.id) == STATUS.DONE
            match = await match_for_game(env)
            before = await snapshot(env, match.id)
            async with env.sf() as session:
                if bad_owner in {"foreign_stat", "foreign_entity"}:
                    await session.run_sync(seed_native_sentinel, env.fixture_ids.copy())
                payload = {}
                for name, model in (
                    ("teams", models.StatsMatchTeam),
                    ("players", models.StatsMatchPlayer),
                    ("segments", models.StatsSegment),
                    ("facts", models.StatsFact),
                    ("events", models.StatsEvent),
                ):
                    payload[name] = [
                        dict(row)
                        for row in (
                            await session.execute(sa.select(model.__table__).where(model.match_id == match.id))
                        ).mappings()
                    ]
                payload["teams"].sort(key=lambda row: row["source_position"])
                for row in payload["events"]:
                    row.pop("id")
                if bad_owner == "foreign_member":
                    payload["players"][0]["workspace_member_id"] = env.fixture_ids["member_other"]
                elif bad_owner == "unknown_stat":
                    payload["facts"][0]["stat_id"] = 32767
                elif bad_owner == "foreign_stat":
                    foreign = await session.scalar(
                        sa.select(models.StatDef.id).where(models.StatDef.discipline == "lol").limit(1)
                    )
                    assert foreign is not None
                    payload["facts"][0]["stat_id"] = foreign
                elif bad_owner == "wrong_entity_kind":
                    payload["facts"][0]["entity_id"] = env.map
                elif bad_owner == "foreign_entity":
                    foreign = await session.scalar(
                        sa.select(models.CatalogEntity.id)
                        .where(
                            models.CatalogEntity.discipline == "lol",
                            models.CatalogEntity.kind == "character",
                        )
                        .limit(1)
                    )
                    assert foreign is not None
                    payload["facts"][0]["entity_id"] = foreign
                elif bad_owner == "non_finite":
                    payload["facts"][0]["value"] = float("nan")
                else:
                    payload["events"][0]["actor_member_id"] = env.fixture_ids["member_other"]
                stored = await session.get(models.StatsMatch, match.id)
                with pytest.raises(ValueError):
                    await StatsMatchRepository().replace_observations(session, match=stored, **payload)
                await session.rollback()
            assert await snapshot(env, match.id) == before

    asyncio.run(run())


def test_foreign_hint_and_wrong_map_game_never_authorize_a_binding(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            async with env.sf() as session:
                with pytest.raises(BaseAPIException):
                    await IngestJobRepository().create_or_get(
                        session,
                        workspace_id=env.workspace,
                        discipline="overwatch",
                        source_kind="manual",
                        external_id=None,
                        content_hash=compute_content_hash(workshop()),
                        filename="x.log",
                        raw_ref="x",
                        document_ref=None,
                        uploader_user_id=None,
                        api_key_id=None,
                        hint_tournament_id=env.tournament,
                        hint_encounter_id=env.fixture_ids["encounter_other"],
                        hint_encounter_game_id=None,
                    )
                await session.rollback()
                wrong_map_game = await _game(session, env, position=2, map_id=env.fixture_ids["map_other"])
                await session.commit()
            job = await upload(env)
            async with env.sf() as session:
                await log_records_service.retry(
                    session,
                    job.id,
                    workspace_id=env.workspace,
                    encounter_id=env.encounter,
                    encounter_game_id=wrong_map_game,
                )
            assert await process(env, job.id) == STATUS.FAILED
            assert await match_for_game(env) is None
            assert await success_events(env) == 0

    asyncio.run(run())


def test_reaper_requeues_through_the_outbox_and_retains_the_last_claim_timestamp(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env)
            old = datetime.now(UTC) - timedelta(days=3)
            async with env.sf() as session:
                row = await session.get(models.IngestJob, job.id)
                await log_records_service.transition(session, row, STATUS.PROCESSING, now=old)
                row.started_at = old
                await session.commit()
            monkeypatch.setattr(reaper.settings, "log_reaper_enabled", True)
            monkeypatch.setattr(reaper, "acquire_distributed_lock", AsyncMock(return_value="owned"))
            release = AsyncMock()
            monkeypatch.setattr(reaper, "release_distributed_lock", release)
            # No broker is involved at all: the request is committed with the reset, so an outage costs only latency.
            await reaper.reclaim_stalled_logs(redis=object(), session_factory=env.sf)
            async with env.sf() as session:
                row = await session.get(models.IngestJob, job.id)
                assert row.status == STATUS.PENDING and row.attempts == 1 and row.started_at == old
                requests = (
                    await session.scalars(
                        sa.select(models.EventOutbox).where(
                            models.EventOutbox.event_type == "process_ingest_job",
                            models.EventOutbox.payload_json["ingest_job_id"].as_integer() == job.id,
                        )
                    )
                ).all()
                # One from the upload's own commit, one from the reaper's reset.
                assert [r.status for r in requests].count("pending") == 2
            release.assert_awaited_once()
            # A disabled worker performs no claim/dispatch at all.
            monkeypatch.setattr(reaper.settings, "log_reaper_enabled", False)
            acquire = AsyncMock()
            monkeypatch.setattr(reaper, "acquire_distributed_lock", acquire)
            assert (await reaper.reclaim_stalled_logs(redis=object(), session_factory=env.sf)).touched == 0
            acquire.assert_not_awaited()

    asyncio.run(run())


def test_only_terminal_transitions_ask_for_achievements_and_a_repeated_status_gets_its_own_id(
    stats_parity_database, monkeypatch
):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env)
            first = datetime.now(UTC)
            async with env.sf() as session:
                row = await session.get(models.IngestJob, job.id)
                # A retried log fails twice: event_outbox.event_id is UNIQUE, so the second id must differ.
                for status, now in (
                    (STATUS.PROCESSING, None),
                    (STATUS.FAILED, first),
                    (STATUS.PENDING, None),
                    (STATUS.PROCESSING, None),
                    (STATUS.FAILED, first + timedelta(seconds=1)),
                ):
                    await log_records_service.transition(session, row, status, now=now)
                    await session.commit()
                ids = (
                    await session.scalars(
                        sa.select(models.EventOutbox.event_id).where(
                            models.EventOutbox.event_id.like(f"achievement:%:job:{job.id}:%")
                        )
                    )
                ).all()
            assert len(set(ids)) == len(ids) == 2 and all(f":job:{job.id}:failed:" in event_id for event_id in ids)

    asyncio.run(run())


def test_retention_skips_an_object_currently_being_uploaded(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env)
            async with env.sf() as session:
                row = await session.get(models.IngestJob, job.id)
                await log_records_service.transition(
                    session, row, STATUS.FAILED, now=datetime.now(UTC) - timedelta(days=3650)
                )
                await session.commit()
            monkeypatch.setattr(retention, "acquire_distributed_lock", AsyncMock(return_value="owned"))
            monkeypatch.setattr(retention, "release_distributed_lock", AsyncMock())
            async with env.sf() as uploading:
                await uploading.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"stats.raw:{job.raw_ref}"}
                )
                assert (
                    await asyncio.wait_for(
                        retention.purge_expired_failed_logs(redis=object(), s3=env.raw, session_factory=env.sf), 5
                    )
                    == 0
                )
                assert env.raw.objects[job.raw_ref] == workshop()
                await uploading.rollback()
            assert await retention.purge_expired_failed_logs(redis=object(), s3=env.raw, session_factory=env.sf) == 1

    asyncio.run(run())
