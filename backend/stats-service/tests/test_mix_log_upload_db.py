"""Match logs for pickup mixes against migrated PostgreSQL (C1/C2/D8/D11): upload by encounter or lobby, the
tournament path still refusing a mix encounter, an orphaned DONE job revived after a mix Undo/Cancel, retry of a mix
job and the mix name on the history row. Same ``environment`` harness as ``test_stats_ingest_db.py``."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.platform.audit import AuditLog
from src.services.match_logs import admin_reads, uploads
from src.services.match_logs.log_records import log_records_service
from tests.encounter_seed import seed_scoring_rule
from tests.test_stats_ingest_db import ADMIN, STATUS, environment, process, upload, workshop

PENDING_CONTENT = workshop(extra="mix-a")
OTHER_CONTENT = workshop(extra="mix-b")


async def _mix(env, *, lobbies=(0,)):
    async with env.sf() as session:
        rule_id = await seed_scoring_rule(session, env.workspace)
        mix = models.CustomGame(workspace_id=env.workspace, name="Friday mix", scoring_rule_id=rule_id)
        session.add(mix)
        await session.flush()
        session.add_all(models.CustomGameLobby(custom_game_id=mix.id, lobby_index=index) for index in lobbies)
        await session.commit()
        return SimpleNamespace(id=mix.id, name=mix.name, rule=rule_id)


async def _round(env, mix, *, lobby=0, live=False, confirmed_ago=0, staffed=False):
    """One mix encounter (Bo1, owner = the mix). ``live`` leaves it on the lobby's floor; otherwise it is a recorded
    ``mix.round`` confirmed ``confirmed_ago`` seconds ago. ``staffed`` seats the log's six players (H* vs A*) and adds
    the one ``awaiting_result`` game Start creates (map not set), as the ingest tests seed a tournament encounter."""
    async with env.sf() as session:
        encounter = models.Encounter(
            workspace_id=env.workspace,
            discipline="overwatch",
            custom_game_id=mix.id,
            scoring_rule_id=mix.rule,
            name="Mix match",
            slot_count=2,
            best_of=1,
            status=enums.EncounterStatus.OPEN,
            confirmed_at=None if live else datetime.now(UTC) - timedelta(seconds=confirmed_ago),
        )
        session.add(encounter)
        await session.flush()
        seats = [
            models.EncounterTeam(encounter_id=encounter.id, slot=slot, team_id=None, name=f"Side {slot}", score=0)
            for slot in (1, 2)
        ]
        session.add_all(seats)
        await session.flush()
        if staffed:
            for seat, prefix in zip(seats, "HA", strict=True):
                for index in range(3):
                    snapshot = models.EncounterTeamMember(
                        encounter_id=encounter.id,
                        encounter_team_id=seat.id,
                        active=True,
                        workspace_member_id=env.members[f"Ingest{prefix}{index}"],
                        display_name_snapshot=f"Ingest{prefix}{index}",
                        rank=800,
                    )
                    session.add(snapshot)
                    await session.flush()
                    session.add(
                        models.EncounterTeamMemberRole(
                            team_member_id=snapshot.id,
                            role_id=env.fixture_ids["role_support"],
                            dimension_id=env.fixture_ids["role_dimension"],
                        )
                    )
            game = models.EncounterGame(
                encounter_id=encounter.id, position=1, map_id=None, state=enums.EncounterGameState.AWAITING_RESULT
            )
            session.add(game)
            await session.flush()
            session.add_all(
                models.EncounterGameTeam(game_id=game.id, encounter_id=encounter.id, encounter_team_id=seat.id)
                for seat in seats
            )
            await session.flush()
        if live:
            await session.execute(
                sa.update(models.CustomGameLobby)
                .where(models.CustomGameLobby.custom_game_id == mix.id, models.CustomGameLobby.lobby_index == lobby)
                .values(live_encounter_id=encounter.id)
            )
        else:
            session.add(models.CustomGameRound(encounter_id=encounter.id, lobby_index=lobby))
        await session.commit()
        return encounter.id


async def _record(env, mix, encounter_id, *, lobby=0):
    """Record: the live pointer is cleared and the round is written."""
    async with env.sf() as session:
        await session.execute(
            sa.update(models.CustomGameLobby)
            .where(models.CustomGameLobby.custom_game_id == mix.id, models.CustomGameLobby.lobby_index == lobby)
            .values(live_encounter_id=None)
        )
        await session.execute(
            sa.update(models.Encounter)
            .where(models.Encounter.id == encounter_id)
            .values(confirmed_at=datetime.now(UTC))
        )
        session.add(models.CustomGameRound(encounter_id=encounter_id, lobby_index=lobby))
        await session.commit()


async def _undo(env, encounter_id):
    """Undo/Cancel: the encounter is hard-deleted (its stats cascade, job hints go NULL)."""
    async with env.sf() as session:
        await session.execute(sa.delete(models.Encounter).where(models.Encounter.id == encounter_id))
        await session.commit()


async def mix_upload(env, mix, content=PENDING_CONTENT, *, user=ADMIN, **target):
    async with env.sf() as session:
        with patch.object(uploads, "quota", SimpleNamespace(charge=AsyncMock())):
            return await uploads.upload_service.upload_batch(
                session,
                env.raw,
                user=user,
                data={},
                custom_game_id=mix.id,
                files=[{"filename": "mix.log", "content_b64": base64.b64encode(content).decode()}],
                **target,
            )


async def job_of(env, job_id):
    async with env.sf() as session:
        return await session.get(models.IngestJob, job_id, populate_existing=True)


async def settle(env, job_id, status, **kwargs):
    async with env.sf() as session:
        job = await session.get(models.IngestJob, job_id)
        await log_records_service.transition(session, job, status, **kwargs)
        await session.commit()


async def ingest_requests(env, job_id):
    async with env.sf() as session:
        return await session.scalar(
            sa.select(sa.func.count())
            .select_from(models.EventOutbox)
            .where(models.EventOutbox.payload_json["ingest_job_id"].as_integer() == job_id)
        )


def test_mix_upload_by_encounter_makes_a_mix_job_hinted_at_it(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            encounter = await _round(env, mix, live=True)
            response = await mix_upload(env, mix, encounter_id=encounter)

            assert response.errors == []
            item = response.uploaded[0]
            assert item.attached_encounter_id == encounter
            job = await job_of(env, item.record_id)
            assert (job.status, job.hint_tournament_id, job.hint_encounter_id) == (STATUS.PENDING, None, encounter)
            assert (job.workspace_id, job.discipline) == (env.workspace, "overwatch")
            assert job.raw_ref == f"logs/mix/{mix.id}/{job.content_hash}"
            assert env.raw.objects[job.raw_ref] == PENDING_CONTENT

            # C2: the history row carries the mix before any stats exist (hinted encounter's mix).
            async with env.sf() as session:
                row = (await session.execute(admin_reads.history_query().where(models.IngestJob.id == job.id))).one()
            record = admin_reads._record_to_dict(*row)
            assert (record["custom_game_id"], record["custom_game_name"]) == (mix.id, "Friday mix")
            assert (record["tournament_id"], record["attached_encounter_id"]) == (None, encounter)

            audit = await _audit(env, mix)
            assert (audit.entity_type, audit.entity_id, audit.workspace_id) == ("custom_game", mix.id, env.workspace)

    asyncio.run(run())


async def _audit(env, mix):
    async with env.sf() as session:
        return await session.scalar(
            sa.select(AuditLog).where(AuditLog.action == "match_log.upload", AuditLog.entity_id == mix.id)
        )


def test_mix_upload_by_lobby_follows_live_then_the_newest_recorded_round(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env, lobbies=(0, 1))
            live = await _round(env, mix, live=True)

            first = await mix_upload(env, mix, PENDING_CONTENT, lobby_index=0)
            assert first.uploaded[0].attached_encounter_id == live

            # Record clears the live pointer while the file is still being written: the lobby still resolves.
            await _record(env, mix, live)
            second = await mix_upload(env, mix, OTHER_CONTENT, lobby_index=0)
            assert second.uploaded[0].attached_encounter_id == live

            # A later recorded round of the same lobby is the newest; another lobby's rounds do not count.
            newer = await _round(env, mix, confirmed_ago=-60)
            await _round(env, mix, lobby=1, confirmed_ago=-120)
            third = await mix_upload(env, mix, workshop(extra="mix-c"), lobby_index=0)
            assert third.uploaded[0].attached_encounter_id == newer

            # A lobby with neither a live nor a recorded encounter is refused before anything is stored.
            with pytest.raises(BaseAPIException) as refused:
                await mix_upload(env, mix, workshop(extra="mix-d"), lobby_index=5)
            assert (refused.value.status_code, refused.value.detail) == (422, "no_mix_match")

    asyncio.run(run())


def test_encounter_ownership_is_enforced_per_path(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            other = await _mix(env)
            mine = await _round(env, mix, live=True)
            theirs = await _round(env, other, live=True)

            # Mix path: another mix's encounter and a tournament encounter are both "not found".
            for wrong in (theirs, env.encounter):
                with pytest.raises(BaseAPIException) as refused:
                    await mix_upload(env, mix, encounter_id=wrong)
                assert (refused.value.status_code, refused.value.detail) == (404, "Encounter not found")

            # Tournament path: a mix encounter is refused exactly as before.
            async with env.sf() as session:
                with pytest.raises(BaseAPIException) as refused:
                    await admin_reads._validate_attached_encounter(
                        session, tournament_id=env.tournament, encounter_id=mine
                    )
            assert (refused.value.status_code, refused.value.detail) == (404, "Encounter not found")
            with pytest.raises(BaseAPIException) as refused:
                await upload(env, attached_encounter_id=mine)
            assert refused.value.status_code == 404

    asyncio.run(run())


def test_same_bytes_cannot_cross_tournament_and_mix(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            encounter = await _round(env, mix, live=True)
            await upload(env, PENDING_CONTENT)

            response = await mix_upload(env, mix, PENDING_CONTENT, encounter_id=encounter)
            assert response.uploaded == []
            assert [error.error for error in response.errors] == ["stats_upload_scope_conflict"]

    asyncio.run(run())


def test_same_bytes_cannot_move_another_mixs_job(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            ours, theirs = await _mix(env), await _mix(env)
            their_match = await _round(env, theirs, live=True)
            job_id = (await mix_upload(env, theirs, encounter_id=their_match)).uploaded[0].record_id
            await settle(env, job_id, STATUS.FAILED, error_message="roster does not match")

            response = await mix_upload(env, ours, encounter_id=await _round(env, ours, live=True))

            assert response.uploaded == []
            assert [error.error for error in response.errors] == ["stats_upload_scope_conflict"]
            job = await job_of(env, job_id)
            assert (job.status, job.hint_encounter_id) == (STATUS.FAILED, their_match)

    asyncio.run(run())


def test_reupload_revives_a_done_mix_job_orphaned_by_undo(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            first = await _round(env, mix, live=True)
            job_id = (await mix_upload(env, mix, encounter_id=first)).uploaded[0].record_id
            await settle(env, job_id, STATUS.DONE)
            await _undo(env, first)
            assert (await job_of(env, job_id)).hint_encounter_id is None

            second = await _round(env, mix, live=True)
            requests_before = await ingest_requests(env, job_id)
            response = await mix_upload(env, mix, encounter_id=second)

            assert response.errors == []
            assert (response.uploaded[0].record_id, response.uploaded[0].attached_encounter_id) == (job_id, second)
            job = await job_of(env, job_id)
            assert (job.status, job.hint_encounter_id, job.hint_encounter_game_id) == (STATUS.PENDING, second, None)
            assert (job.attempts, job.error_message, job.finished_at) == (0, None, None)
            # Exactly one fresh ingest request: the transition's, not a second from the upload.
            assert await ingest_requests(env, job_id) == requests_before + 1

            # Pending again, so the next identical upload is the plain idempotent reuse.
            await mix_upload(env, mix, encounter_id=second)
            assert (await job_of(env, job_id)).status == STATUS.PENDING

    asyncio.run(run())


def test_a_done_mix_job_that_still_has_its_match_is_not_revived(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            first = await _round(env, mix, live=True)
            job_id = (await mix_upload(env, mix, encounter_id=first)).uploaded[0].record_id
            await settle(env, job_id, STATUS.DONE)
            second = await _round(env, mix, live=True)
            async with env.sf() as session:
                with patch.object(session, "scalar", AsyncMock(return_value=True)):
                    revived = await uploads.upload_service._revive_mix_job(
                        session, await session.get(models.IngestJob, job_id), second
                    )
            assert revived is False
            job = await job_of(env, job_id)
            assert (job.status, job.hint_encounter_id) == (STATUS.DONE, first)

    asyncio.run(run())


def test_a_done_tournament_job_stays_idempotent(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            job = await upload(env, PENDING_CONTENT)
            await settle(env, job.id, STATUS.DONE)
            again = await upload(env, PENDING_CONTENT, attached_encounter_id=env.encounter)
            assert again.id == job.id
            reread = await job_of(env, job.id)
            assert (reread.status, reread.hint_encounter_id) == (STATUS.DONE, None)

    asyncio.run(run())


def test_retry_reattaches_a_mix_job_within_its_owner_world(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            first = await _round(env, mix, live=True)
            second = await _round(env, mix, confirmed_ago=30)
            job_id = (await mix_upload(env, mix, encounter_id=first)).uploaded[0].record_id
            await settle(env, job_id, STATUS.FAILED, error_message="boom")

            # A tournament encounter is a different owner world for a NULL-tournament job.
            async with env.sf() as session:
                with pytest.raises(BaseAPIException) as refused:
                    await log_records_service.retry(
                        session, job_id, workspace_id=env.workspace, encounter_id=env.encounter
                    )
            assert (refused.value.status_code, refused.value.detail) == (422, "stats_upload_hint_conflict")

            async with env.sf() as session:
                job = await log_records_service.retry(session, job_id, workspace_id=env.workspace, encounter_id=second)
            assert (job.status, job.hint_encounter_id) == (STATUS.PENDING, second)
            assert (await job_of(env, job_id)).hint_encounter_id == second

    asyncio.run(run())


def test_retry_keeps_a_tournament_job_out_of_a_mix_encounter(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            encounter = await _round(env, mix, live=True)
            job = await upload(env, PENDING_CONTENT)
            await settle(env, job.id, STATUS.FAILED, error_message="boom")
            async with env.sf() as session:
                with pytest.raises(BaseAPIException) as refused:
                    await log_records_service.retry(session, job.id, workspace_id=env.workspace, encounter_id=encounter)
            assert (refused.value.status_code, refused.value.detail) == (422, "stats_upload_hint_conflict")

    asyncio.run(run())


@pytest.mark.parametrize("status", [STATUS.FAILED, STATUS.AWAITING_LINK])
def test_reupload_from_the_right_match_repoints_a_job_that_failed_on_the_wrong_one(
    status, stats_parity_database, monkeypatch
):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env, lobbies=(0, 1))
            wrong = await _round(env, mix, lobby=1, live=True)
            right = await _round(env, mix, lobby=0, live=True)
            job_id = (await mix_upload(env, mix, encounter_id=wrong)).uploaded[0].record_id
            await settle(env, job_id, status, error_message="roster does not match")
            requests_before = await ingest_requests(env, job_id)

            response = await mix_upload(env, mix, encounter_id=right)

            assert response.errors == []
            assert (response.uploaded[0].record_id, response.uploaded[0].attached_encounter_id) == (job_id, right)
            job = await job_of(env, job_id)
            assert (job.status, job.hint_encounter_id, job.hint_encounter_game_id) == (STATUS.PENDING, right, None)
            assert (job.attempts, job.error_message, job.finished_at) == (0, None, None)
            assert await ingest_requests(env, job_id) == requests_before + 1

    asyncio.run(run())


def test_reupload_never_repoints_a_job_that_is_still_in_flight(stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env, lobbies=(0, 1))
            first = await _round(env, mix, lobby=1, live=True)
            other = await _round(env, mix, lobby=0, live=True)
            job_id = (await mix_upload(env, mix, encounter_id=first)).uploaded[0].record_id

            for status in (STATUS.PENDING, STATUS.PROCESSING):
                if status == STATUS.PROCESSING:
                    await settle(env, job_id, STATUS.PROCESSING)
                await mix_upload(env, mix, encounter_id=other)
                job = await job_of(env, job_id)
                assert (job.status, job.hint_encounter_id) == (status, first)

    asyncio.run(run())


@pytest.mark.parametrize("target", ["encounter_id", "lobby_after_record"])
def test_a_real_log_binds_to_a_mix_encounter_and_never_decides_its_result(target, stats_parity_database, monkeypatch):
    async def run():
        async with environment(stats_parity_database, monkeypatch) as env:
            mix = await _mix(env)
            encounter = await _round(env, mix, live=True, staffed=True)
            if target == "encounter_id":
                response = await mix_upload(env, mix, workshop(), encounter_id=encounter)
            else:
                # Record clears the live pointer while the file is still being written; the lobby still resolves.
                await _record(env, mix, encounter)
                response = await mix_upload(env, mix, workshop(), lobby_index=0)
            assert response.errors == []
            job_id = response.uploaded[0].record_id
            assert response.uploaded[0].attached_encounter_id == encounter

            assert await process(env, job_id) == STATUS.DONE

            async with env.sf() as session:
                game = await session.scalar(
                    sa.select(models.EncounterGame).where(models.EncounterGame.encounter_id == encounter)
                )
                matches = list(
                    await session.scalars(
                        sa.select(models.StatsMatch).where(models.StatsMatch.encounter_id == encounter)
                    )
                )
                assert len(matches) == 1
                match = matches[0]
                assert (match.encounter_game_id, match.ingest_job_id, match.workspace_id) == (
                    game.id,
                    job_id,
                    env.workspace,
                )
                players = list(
                    await session.scalars(
                        sa.select(models.StatsMatchPlayer).where(models.StatsMatchPlayer.match_id == match.id)
                    )
                )
                assert {row.workspace_member_id for row in players} >= {
                    env.members[f"Ingest{prefix}{index}"] for prefix in "HA" for index in range(3)
                }
                facts = await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(models.StatsFact)
                    .where(models.StatsFact.match_id == match.id)
                )
                assert facts > 0

                # A log never decides a mix result: the game and the encounter are exactly as Start left them.
                await session.refresh(game)
                reread = await session.get(models.Encounter, encounter, populate_existing=True)
                assert game.state == enums.EncounterGameState.AWAITING_RESULT
                assert (reread.status, reread.result_status) == (
                    enums.EncounterStatus.OPEN,
                    enums.EncounterResultStatus.NONE,
                )

    asyncio.run(run())
