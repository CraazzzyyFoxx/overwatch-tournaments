"""Task 4 behavior of identity resolution, N-team binding, admin bind and the public ``workshop_csv`` document.

Real PostgreSQL (a migrated, disposable clone per test), real rosters/identities/games from ``ingest_seed``; only S3 is
an in-memory store. Nothing here asserts on prepared rows or SQL text: every claim reads the native tables or the real
authorization/visibility services back.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.repository.workspace import WorkspaceMemberRepository, get_or_create_workspace_member
from shared.rpc.identity import rehydrate_user
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes
from shared.services.tournament.visibility import can_view_workspace_tournaments
from src.schemas.ingest import BindIngestRequest
from src.services.ingest import jobs, process
from src.services.ingest.jobs import IngestRejected
from tests._ingest_support import body, make_doc, open_environment, user_of
from tests.ingest_seed import (
    add_game,
    build_document,
    create_job,
    observation_snapshot,
    seed_ingest_case,
    shuffled,
    side_effects,
    success_events,
)

Status = models.IngestJobStatus


def run(ingest_database, scenario):
    url, seeded = ingest_database

    async def main():
        async with open_environment(url, seeded) as env:
            return await scenario(env)

    return asyncio.run(main())


@asynccontextmanager
async def db(env):
    async with env.sf() as session:
        yield session


async def new_case(env, slug, **kwargs):
    async with db(env) as session:
        case = await seed_ingest_case(session, workspace_slug=f"bind-{slug}", **kwargs)
        await session.commit()
        return case


async def submit(env, case, document=None, **kwargs):
    async with db(env) as session:
        return await create_job(session, env.s3, case, document, **kwargs)


async def process_job(env, job_id):
    async with db(env) as session:
        return await process.process_ingest_job(session, job_id, env.s3, is_raise=False)


async def job_row(env, job_id):
    async with db(env) as session:
        return (
            await session.scalars(
                sa.select(models.IngestJob)
                .where(models.IngestJob.id == job_id)
                .execution_options(populate_existing=True)
            )
        ).one()


async def snapshot(env, case):
    async with db(env) as session:
        return await observation_snapshot(session, case.game_id)


def admin(_case=None):
    return rehydrate_user({"sub": 1, "username": "root", "is_superuser": True, "workspaces": [], "roles": ["admin"]})


def stranger():
    return rehydrate_user({"sub": 2, "username": "nobody", "is_superuser": False, "workspaces": []})


def team_map(case):
    return {f"t{i + 1}": seat for i, seat in enumerate(case.team_ids)}


# -- binding ---------------------------------------------------------------------------------------------------


def test_three_shuffled_teams_bind_by_identity_and_keep_document_order(ingest_database):
    async def scenario(env):
        case = await new_case(env, "n3", teams=3)
        document = shuffled(case.document, seed=11)
        keys = [team["key"] for team in document["teams"]]
        assert keys != ["t1", "t2", "t3"], "the fixture must really reorder the teams"
        job_id = await submit(env, case, document)

        assert await process_job(env, job_id) == Status.DONE
        snap = await snapshot(env, case)
        slot_of = {f"t{i + 1}": seat for i, seat in enumerate(case.team_ids)}
        assert [(row["source_position"], row["encounter_team_id"]) for row in snap["teams"]] == [
            (position, slot_of[key]) for position, key in enumerate(keys, start=1)
        ]
        seat_of_member = {member: case.team_ids[t] for t, members in enumerate(case.member_ids) for member in members}
        assert {row["workspace_member_id"]: row["encounter_team_id"] for row in snap["players"]} == seat_of_member
        assert snap["revision"] == 1
        assert (await job_row(env, job_id)).status == Status.DONE

    run(ingest_database, scenario)


def test_the_same_social_identity_in_two_workspaces_gets_one_anchor_in_each(ingest_database):
    async def scenario(env):
        first = await new_case(env, "xa")
        second = await new_case(env, "xb")
        async with db(env) as session:
            # The first workspace's captain also plays (as a sixth man) for the second workspace's first team.
            player = first.player_ids[0][0]
            anchor = models.WorkspaceMember(workspace_id=second.workspace_id, player_id=player)
            session.add(anchor)
            await session.flush()
            session.add(
                models.EncounterTeamMember(
                    encounter_id=second.encounter_id,
                    encounter_team_id=second.team_ids[0],
                    active=True,
                    workspace_member_id=anchor.id,
                    display_name_snapshot="shared",
                    rank=700,
                )
            )
            await session.commit()
        doc_b = build_document(second, external_id="x-b")
        doc_b["participants"].append(
            {
                "key": "shared",
                "team": "t1",
                "identity": {"provider": second.provider, "id": first.handles[0][0]},
            }
        )
        jobs_done = [
            await process_job(env, await submit(env, first)),
            await process_job(env, await submit(env, second, doc_b)),
        ]
        assert jobs_done == [Status.DONE, Status.DONE]
        async with db(env) as session:
            anchors = (
                await session.execute(
                    sa.select(models.WorkspaceMember.workspace_id, models.WorkspaceMember.id).where(
                        models.WorkspaceMember.player_id == player
                    )
                )
            ).all()
            assert sorted(w for w, _ in anchors) == sorted([first.workspace_id, second.workspace_id])
            by_workspace = dict(anchors)
            used = {
                (match.workspace_id, row.workspace_member_id)
                for match, row in (
                    await session.execute(
                        sa.select(models.StatsMatch, models.StatsMatchPlayer)
                        .join(models.StatsMatchPlayer, models.StatsMatchPlayer.match_id == models.StatsMatch.id)
                        .where(models.StatsMatchPlayer.workspace_member_id.in_(list(by_workspace.values())))
                    )
                ).all()
            }
            assert used == set(by_workspace.items())

    run(ingest_database, scenario)


def test_same_role_code_in_another_discipline_resolves_to_that_disciplines_role(ingest_database):
    async def scenario(env):
        case = await new_case(env, "lol", discipline="lol")
        job_id = await submit(env, case)
        assert await process_job(env, job_id) == Status.DONE
        async with db(env) as session:
            roles = (
                await session.execute(
                    sa.select(models.CatalogRole.code, models.RoleDimension.code, models.RoleDimension.discipline)
                    .join(models.RoleDimension, models.RoleDimension.id == models.CatalogRole.dimension_id)
                    .join(models.StatsMatchPlayer, models.StatsMatchPlayer.observed_role_id == models.CatalogRole.id)
                    .join(models.StatsMatch, models.StatsMatch.id == models.StatsMatchPlayer.match_id)
                    .where(models.StatsMatch.encounter_game_id == case.game_id)
                )
            ).all()
            assert roles and {(dim, discipline) for _, dim, discipline in roles} == {("position", "lol")}
        # The overwatch role vocabulary does not leak into lol: its dimension is not lol's rated one.
        wrong = build_document(case, external_id="wrong-dim")
        for person in wrong["participants"]:
            person["role"] = {"dimension": "player_role", "role": "support"}
        failed = await process_job(env, await submit(env, case, wrong))
        assert failed == Status.FAILED

    run(ingest_database, scenario)


def test_a_discipline_without_a_raw_decoder_never_fetches_envelopes_for_the_workshop_repair(
    ingest_database, monkeypatch
):
    async def scenario(env):
        from src.services.match_logs.objectiveless import load_producers

        case = await new_case(env, "lolprod", discipline="lol")
        job_id = await submit(env, case)
        assert await process_job(env, job_id) == Status.DONE
        fetched = []

        async def spy(s3, ref):
            fetched.append(ref)
            raise AssertionError("an envelope was fetched")

        monkeypatch.setattr(jobs, "load_document", spy)
        async with db(env) as session:
            assert await load_producers(session, env.s3, case.encounter_id) == {}
        assert fetched == []

    run(ingest_database, scenario)


# -- identities ------------------------------------------------------------------------------------------------


def test_unknown_identities_become_virtual_players_without_access_and_concurrent_creation_is_single(ingest_database):
    async def scenario(env):
        case = await new_case(env, "virt")
        second_game = None
        async with db(env) as session:
            second_game = await add_game(session, case)
            await session.commit()
        newcomer = {"provider": case.provider, "id": "Newcomer#9001"}

        def with_newcomer(external_id, game):
            doc = build_document(case, external_id=external_id)
            doc["participants"].append({"key": "new", "team": "t1", "identity": newcomer})
            doc["hint"] = {"encounter_game_id": game}
            return doc

        first = await submit(env, case, with_newcomer("virt-1", case.game_id))
        second = await submit(env, case, with_newcomer("virt-2", second_game))
        statuses = await asyncio.gather(process_job(env, first), process_job(env, second))
        assert statuses == [Status.DONE, Status.DONE]
        async with db(env) as session:
            accounts = (
                await session.execute(
                    sa.select(models.SocialAccount.user_id).where(
                        models.SocialAccount.provider == case.provider,
                        models.SocialAccount.username_normalized == "newcomer#9001",
                    )
                )
            ).all()
            assert len(accounts) == 1
            user = await session.get(models.User, accounts[0][0])
            assert user.auth_user_id is None
            visible = await session.scalar(
                sa.select(sa.func.count())
                .select_from(models.SocialAccountVisibility)
                .join(models.SocialAccount, models.SocialAccount.id == models.SocialAccountVisibility.account_id)
                .where(models.SocialAccount.user_id == user.id)
            )
            assert visible == 0
            anchors = (
                await session.scalars(
                    sa.select(models.WorkspaceMember).where(
                        models.WorkspaceMember.player_id == user.id,
                        models.WorkspaceMember.workspace_id == case.workspace_id,
                    )
                )
            ).all()
            assert len(anchors) == 1
            # the event-only participant is an extra on the match layer's side, never a roster row written here
            roster = await session.scalar(
                sa.select(sa.func.count())
                .select_from(models.EncounterTeamMember)
                .where(models.EncounterTeamMember.workspace_member_id == anchors[0].id)
            )
            assert roster == 0

    run(ingest_database, scenario)


def test_one_statement_takes_every_identity_lock_for_the_transaction(ingest_database):
    async def scenario(env):
        from src.services.ingest.identity import _lock_identities

        identities = {("battlenet", "zed#3"), ("battlenet", "amy#1"), ("discord", "kim")}
        async with db(env) as holder, db(env) as probe:
            await _lock_identities(holder, identities)
            for provider, normalized in identities:
                free = await probe.scalar(
                    sa.text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                    {"key": f"stats.identity:{provider}:{normalized}"},
                )
                assert free is False, (provider, normalized)
            await holder.rollback()
            await probe.rollback()

    run(ingest_database, scenario)


async def _auth_linked_player(session, handle, tag):
    auth = models.AuthUser(email=f"{tag}@example.com", username=tag, hashed_password=None)
    session.add(auth)
    await session.flush()
    user = models.User(name=f"auth-{tag}", auth_user_id=auth.id)
    session.add(user)
    await session.flush()
    session.add(
        models.SocialAccount(
            user_id=user.id, provider="battlenet", username=handle, username_normalized=handle.lower(), is_primary=True
        )
    )
    await session.flush()
    return auth, user


async def _visible(session, auth_user_id, workspace_id):
    """The real read the gateway-side authorization makes: the token's memberships come from workspace_member rows."""
    memberships = await WorkspaceMemberRepository().list_memberships_for_auth_user(session, auth_user_id)
    user = rehydrate_user(
        {
            "sub": auth_user_id,
            "workspaces": [
                {"workspace_id": ws, "slug": slug, "rbac_roles": [], "rbac_permissions": []} for ws, slug in memberships
            ],
        }
    )
    workspace_hidden = await session.scalar(
        sa.select(models.Workspace.is_hidden).where(models.Workspace.id == workspace_id)
    )
    return can_view_workspace_tournaments(user, workspace_id, workspace_hidden), sorted(ws for ws, _ in memberships)


async def _grants(session, auth_user_id):
    roles = await session.scalar(
        sa.select(sa.func.count()).select_from(models.user_roles).where(models.user_roles.c.user_id == auth_user_id)
    )
    return roles


@pytest.mark.parametrize("already_removed", [False, True])
def test_logged_foreign_auth_player_gains_neither_visibility_nor_grants_and_removed_stays_removed(
    ingest_database, already_removed
):
    async def scenario(env):
        case = await new_case(env, f"vis{already_removed}")
        other = await new_case(env, f"vis-other{already_removed}")
        async with db(env) as session:
            await session.execute(
                sa.update(models.Workspace).where(models.Workspace.id == case.workspace_id).values(is_hidden=True)
            )
            auth, user = await _auth_linked_player(session, "Foreigner#7777", f"foreign{already_removed}")
            # an ordinary member of the other workspace, not of the hidden one
            await WorkspaceMemberRepository().create(
                session, models.WorkspaceMember(workspace_id=other.workspace_id, player_id=user.id)
            )
            if already_removed:
                from datetime import UTC, datetime

                await WorkspaceMemberRepository().create(
                    session,
                    models.WorkspaceMember(
                        workspace_id=case.workspace_id, player_id=user.id, removed_at=datetime(2026, 1, 1, tzinfo=UTC)
                    ),
                )
            await session.commit()
            auth_id, user_id = auth.id, user.id
        async with db(env) as session:
            before = (await _visible(session, auth_id, case.workspace_id), await _grants(session, auth_id))
        assert before[0][0] is False and case.workspace_id not in before[0][1]

        doc = build_document(case, external_id="visible-1")
        doc["participants"].append(
            {"key": "guest", "team": "t2", "identity": {"provider": "battlenet", "id": "Foreigner#7777"}}
        )
        # The guest is on no line-up: only a hint lets the rostered participants bind it.
        hinted = {"encounter_game_id": case.game_id}
        assert await process_job(env, await submit(env, case, doc, hint=hinted)) == Status.DONE

        async with db(env) as session:
            after = (await _visible(session, auth_id, case.workspace_id), await _grants(session, auth_id))
            anchor = (
                await session.scalars(
                    sa.select(models.WorkspaceMember).where(
                        models.WorkspaceMember.workspace_id == case.workspace_id,
                        models.WorkspaceMember.player_id == user_id,
                    )
                )
            ).one()
            observed = await session.scalar(
                sa.select(sa.func.count())
                .select_from(models.StatsMatchPlayer)
                .where(models.StatsMatchPlayer.workspace_member_id == anchor.id)
            )
        assert after == before, "an observation must change neither the protected read nor the auth grants"
        assert observed == 1
        if already_removed:
            assert anchor.observed_only is False, "an existing row is never rewritten"
            assert anchor.removed_at.year == 2026 and anchor.removed_at.month == 1, "never revived or restamped"
            return
        assert anchor.observed_only is True and anchor.removed_at is None, "an observation anchor, not a fake removal"
        async with db(env) as session:
            # the link-time role autofill reads these workspaces: the observed workspace is not among them
            assert case.workspace_id not in await WorkspaceMemberRepository().workspace_ids_for_player(session, user_id)
            assert other.workspace_id in await WorkspaceMemberRepository().workspace_ids_for_player(session, user_id)
        # a real admission turns the anchor into a membership and is visible on the same real reads
        async with db(env) as session:
            member = await get_or_create_workspace_member(session, workspace_id=case.workspace_id, player_id=user_id)
            assert member.id == anchor.id and member.observed_only is False
            await session.commit()
        async with db(env) as session:
            admitted = await _visible(session, auth_id, case.workspace_id)
        assert admitted[0] is True and case.workspace_id in admitted[1]

    run(ingest_database, scenario)


# -- no unique game --------------------------------------------------------------------------------------------


def test_repeated_games_on_one_map_leave_the_document_awaiting_even_when_one_is_occupied(ingest_database):
    async def scenario(env):
        case = await new_case(env, "amb")
        async with db(env) as session:
            await add_game(session, case)
            await session.commit()
        before = None
        async with db(env) as session:
            before = await side_effects(session, case.workspace_id)
        job_id = await submit(env, case)
        assert await process_job(env, job_id) == Status.AWAITING_LINK
        row = await job_row(env, job_id)
        assert row.document_ref and row.finished_at is not None
        assert jobs.decode_error(row.error_message).code == "awaiting_link"
        async with db(env) as session:
            assert await side_effects(session, case.workspace_id) == before

        # Occupy one of the two games through an explicit hint: the unhinted document stays ambiguous, because
        # an occupied game is not more certain than an empty one.
        hinted = await submit(env, case, external_id="amb-hinted", hint={"encounter_game_id": case.game_id})
        assert await process_job(env, hinted) == Status.DONE
        again = await submit(env, case, external_id="amb-again")
        assert await process_job(env, again) == Status.AWAITING_LINK
        assert (await snapshot(env, case))["revision"] == 1

    run(ingest_database, scenario)


def test_without_a_hint_a_participant_outside_the_line_up_leaves_the_document_awaiting(ingest_database):
    async def scenario(env):
        case = await new_case(env, "whole")

        def with_outsider(external_id):
            doc = build_document(case, external_id=external_id)
            doc["participants"].append(
                {"key": "out", "team": "t1", "identity": {"provider": case.provider, "id": "Outsider#9200"}}
            )
            return doc

        # Every rostered participant agrees with one game, but one participant is on no line-up: nothing narrows
        # the search, so the game is not proven and nothing is written.
        loose = await submit(env, case, with_outsider("whole-loose"))
        assert await process_job(env, loose) == Status.AWAITING_LINK
        assert await snapshot(env, case) == {}
        # A hint narrows the search to the game; its line-up then binds the same people.
        hinted = await submit(env, case, with_outsider("whole-hinted"), hint={"encounter_game_id": case.game_id})
        assert await process_job(env, hinted) == Status.DONE
        assert (await snapshot(env, case))["revision"] == 1
        # A document whose every participant is on the line-up still corrects the game without a hint.
        whole = await submit(env, case, external_id="whole-fix")
        assert await process_job(env, whole) == Status.DONE
        assert (await snapshot(env, case))["revision"] == 2

    run(ingest_database, scenario)


def test_a_valid_hint_narrows_candidates_and_team_keys_stay_opaque(ingest_database):
    async def scenario(env):
        case = await new_case(env, "hint")
        # a second encounter of the same workspace whose game carries other people
        other_game = None
        async with db(env) as session:
            second = await add_game(session, case)
            await session.commit()
            other_game = second
        # valid hint narrows two plausible games to one
        ok = await submit(env, case, external_id="hint-ok", hint={"encounter_game_id": other_game})
        assert await process_job(env, ok) == Status.DONE
        async with db(env) as session:
            match = await session.scalar(
                sa.select(models.StatsMatch.encounter_game_id).where(
                    models.StatsMatch.workspace_id == case.workspace_id
                )
            )
            assert match == other_game

        swapped = build_document(case, external_id="hint-swapped")
        for person in swapped["participants"]:
            person["team"] = "t2" if person["team"] == "t1" else "t1"
        # Team keys are opaque: swapping which key holds which people still binds, t1 -> seat 2. Identity decides.
        swap_job = await submit(env, case, swapped, hint={"encounter_game_id": case.game_id})
        assert await process_job(env, swap_job) == Status.DONE
        snap = await snapshot(env, case)
        assert {row["source_position"]: row["encounter_team_id"] for row in snap["teams"]} == {
            1: case.team_ids[1],
            2: case.team_ids[0],
        }

    run(ingest_database, scenario)


def test_forged_hint_is_a_nondisclosing_refusal_and_creates_no_job(ingest_database):
    async def scenario(env):
        document = make_doc("forged", hint={"encounter_game_id": env.ids["B"]["game"]})
        for name, user in (("foreign game", user_of(env, "ok")),):
            async with db(env) as session:
                with pytest.raises(IngestRejected) as refused:
                    await jobs.submit_document(session, raw=body(document), user=user, s3=env.s3)
            assert refused.value.status_code == 404 and refused.value.code == "binding_target_not_found", name
            assert str(env.ids["B"]["game"]) not in str(refused.value.detail)
        async with db(env) as session:
            count = await session.scalar(
                sa.select(sa.func.count()).select_from(models.IngestJob).where(models.IngestJob.external_id == "forged")
            )
        assert count == 0

    run(ingest_database, scenario)


def test_contradicting_participants_on_a_hinted_game_are_a_mismatch(ingest_database):
    async def scenario(env):
        case = await new_case(env, "mismatch")
        doc = build_document(case, external_id="mismatch-1")
        # one participant of team t1 is rostered on team t2: the hinted game's rosters refute the document
        doc["participants"][0]["identity"] = {"provider": case.provider, "id": case.handles[1][0]}
        doc["participants"][3]["identity"] = {"provider": case.provider, "id": "Newcomer#9100"}
        job_id = await submit(env, case, doc, hint={"encounter_game_id": case.game_id})
        assert await process_job(env, job_id) == Status.FAILED
        assert jobs.decode_error((await job_row(env, job_id)).error_message).code == "binding_mismatch"
        assert await snapshot(env, case) == {}

    run(ingest_database, scenario)


def test_all_unknown_teams_wait_without_creating_identities_or_facts(ingest_database):
    async def scenario(env):
        case = await new_case(env, "unknown")
        doc = build_document(case, external_id="unknown-1")
        for index, person in enumerate(doc["participants"]):
            person["identity"] = {"provider": case.provider, "id": f"Stranger{index}#{5000 + index}"}
        async with db(env) as session:
            before = await side_effects(session, case.workspace_id)
        job_id = await submit(env, case, doc, hint={"encounter_game_id": case.game_id})
        assert await process_job(env, job_id) == Status.AWAITING_LINK
        async with db(env) as session:
            assert await side_effects(session, case.workspace_id) == before
            assert await success_events(session, case.workspace_id) == 0

    run(ingest_database, scenario)


# -- admin bind ------------------------------------------------------------------------------------------------


def _unknown_doc(case, external_id):
    doc = build_document(case, external_id=external_id)
    for index, person in enumerate(doc["participants"]):
        person["identity"] = {"provider": case.provider, "id": f"Nobody{index}#{6000 + index}"}
    return doc


def test_admin_bind_resolves_zero_overlap_teams_and_materializes_identities_only_then(ingest_database):
    async def scenario(env):
        case = await new_case(env, "zero")
        job_id = await submit(env, case, _unknown_doc(case, "zero-1"))
        assert await process_job(env, job_id) == Status.AWAITING_LINK
        parked = await job_row(env, job_id)
        async with db(env) as session:
            before = await side_effects(session, case.workspace_id)

        # a partial or non-bijective map is refused before anything changes
        async with db(env) as session:
            with pytest.raises(IngestRejected) as refused:
                await process.bind_ingest_job(
                    session,
                    job_id=job_id,
                    request=BindIngestRequest(encounter_game_id=case.game_id, teams={"t1": case.team_ids[0]}),
                    user=admin(case),
                    s3=env.s3,
                )
            assert refused.value.code == "invalid_team_map"
        async with db(env) as session:
            assert await side_effects(session, case.workspace_id) == before

        async with db(env) as session:
            read = await process.bind_ingest_job(
                session,
                job_id=job_id,
                request=BindIngestRequest(encounter_game_id=case.game_id, teams=team_map(case)),
                user=admin(case),
                s3=env.s3,
            )
        assert read.status == Status.DONE and read.binding.revision == 1
        assert read.binding.encounter_game_id == case.game_id
        done = await job_row(env, job_id)
        assert done.document_ref == parked.document_ref
        async with db(env) as session:
            after = await side_effects(session, case.workspace_id)
        assert after["matches"] == 1 and after["users"] > before["users"] and after["members"] > before["members"]
        snap = await snapshot(env, case)
        assert [(row["source_position"], row["encounter_team_id"]) for row in snap["teams"]] == [
            (i + 1, seat) for i, seat in enumerate(case.team_ids)
        ]

    run(ingest_database, scenario)


def test_admin_bind_refuses_unauthorized_busy_done_and_stale_revisions_and_keeps_the_parked_job(ingest_database):
    async def scenario(env):
        case = await new_case(env, "stale")
        occupied = await submit(env, case, external_id="stale-occupied")
        assert await process_job(env, occupied) == Status.DONE
        job_id = await submit(env, case, _unknown_doc(case, "stale-1"))
        assert await process_job(env, job_id) == Status.AWAITING_LINK
        parked = await job_row(env, job_id)

        async def bind(user=None, **request):
            async with db(env) as session:
                return await process.bind_ingest_job(
                    session,
                    job_id=job_id,
                    request=BindIngestRequest(encounter_game_id=case.game_id, teams=team_map(case), **request),
                    user=user or admin(case),
                    s3=env.s3,
                )

        with pytest.raises(IngestRejected) as denied:
            await bind(user=stranger())
        assert denied.value.status_code == 403
        with pytest.raises(IngestRejected) as required:
            await bind()
        assert required.value.code == "expected_revision_required"
        for expected in (0, 2):
            with pytest.raises(IngestRejected) as stale:
                await bind(expected_revision=expected)
            assert stale.value.code == "stale_revision"
        again = await job_row(env, job_id)
        assert (again.status, again.document_ref, again.attempts) == (
            Status.AWAITING_LINK,
            parked.document_ref,
            parked.attempts,
        )
        assert (await snapshot(env, case))["revision"] == 1

        async def header():
            async with db(env) as session:
                states = await capture_stats_evidence(
                    session, scopes=owner_scopes("match", ((await snapshot(env, case))["match_id"],))
                )
            return [state for state in states if state["subset"] == "header"]

        header_before = await header()
        read = await bind(expected_revision=1)
        assert read.status == Status.DONE and read.binding.revision == 2
        assert await header() == header_before, "bind never rebinds the immutable match header"
        with pytest.raises(IngestRejected) as done:
            await bind(expected_revision=2)
        assert done.value.code == "reparse_required"

    run(ingest_database, scenario)


def test_admin_bind_keeps_the_provenance_refusals_of_the_queue_and_reparse_paths(ingest_database):
    async def scenario(env):
        case = await new_case(env, "prov")
        occupied = await submit(env, case, external_id="prov-occupied")
        assert await process_job(env, occupied) == Status.DONE
        unverified = await submit(env, case, _unknown_doc(case, "prov-unverified"))
        assert await process_job(env, unverified) == Status.AWAITING_LINK
        async with db(env) as session:
            await session.execute(
                sa.update(models.IngestJob)
                .where(models.IngestJob.id == unverified)
                .values(status=Status.FAILED, raw_status=models.RawSourceStatus.UNVERIFIED)
            )
            await session.execute(  # a failed job that already owns an observation
                sa.update(models.IngestJob).where(models.IngestJob.id == occupied).values(status=Status.FAILED)
            )
            await session.commit()
        before = await snapshot(env, case)

        async def bind(job_id):
            async with db(env) as session:
                return await process.bind_ingest_job(
                    session,
                    job_id=job_id,
                    request=BindIngestRequest(
                        encounter_game_id=case.game_id, teams=team_map(case), expected_revision=1
                    ),
                    user=admin(case),
                    s3=env.s3,
                )

        with pytest.raises(IngestRejected) as refused:
            await bind(unverified)
        assert (refused.value.status_code, refused.value.code) == (409, "stats_raw_unavailable")
        with pytest.raises(IngestRejected) as owned:
            await bind(occupied)
        assert (owned.value.status_code, owned.value.code) == (409, "already_bound")
        assert await snapshot(env, case) == before, "a refused bind replaces nothing"
        assert (await job_row(env, unverified)).status == Status.FAILED

    run(ingest_database, scenario)


def test_admin_bind_refuses_a_map_the_tournament_rosters_contradict_on_seats_without_a_line_up(ingest_database):
    async def scenario(env):
        case = await new_case(env, "owners")
        async with db(env) as session:
            # The seats are tournament teams whose rosters own the participants, but carry no line-up snapshot (a
            # stage encounter seated before generation snapshotted rosters), so no line-up contradicts any map.
            teams = [
                models.Team(tournament_id=case.tournament_id, name=f"Owners {i}", balancer_name=f"owners-{i}")
                for i in range(3)
            ]
            session.add_all(teams)
            await session.flush()
            for seat, team in zip(case.team_ids, teams, strict=False):
                await session.execute(
                    sa.update(models.EncounterTeam).where(models.EncounterTeam.id == seat).values(team_id=team.id)
                )
            roster = [
                models.Player(
                    tournament_id=case.tournament_id,
                    team_id=team.id,
                    workspace_member_id=member,
                    name=f"m{member}",
                    rank=800,
                )
                for team, members in zip(teams, case.member_ids, strict=False)
                for member in members
            ]
            session.add_all(roster)
            await session.execute(
                sa.delete(models.EncounterTeamMember).where(
                    models.EncounterTeamMember.encounter_id == case.encounter_id
                )
            )
            await session.commit()
        job_id = await submit(env, case)
        assert await process_job(env, job_id) == Status.AWAITING_LINK
        parked = await job_row(env, job_id)
        async with db(env) as session:
            before = await side_effects(session, case.workspace_id)

        async def bind(teams):
            async with db(env) as session:
                return await process.bind_ingest_job(
                    session,
                    job_id=job_id,
                    request=BindIngestRequest(encounter_game_id=case.game_id, teams=teams, expected_revision=0),
                    user=admin(case),
                    s3=env.s3,
                )

        async def refused(teams):
            with pytest.raises(IngestRejected) as refusal:
                await bind(teams)
            assert (refusal.value.status_code, refusal.value.code) == (409, "binding_mismatch")
            row = await job_row(env, job_id)
            assert (row.status, row.document_ref, row.attempts) == (
                Status.AWAITING_LINK,
                parked.document_ref,
                parked.attempts,
            )
            assert await snapshot(env, case) == {}
            async with db(env) as session:
                assert await side_effects(session, case.workspace_id) == before

        # Reversed: every participant is rostered on the other seat's team.
        await refused({"t1": case.team_ids[1], "t2": case.team_ids[0]})
        # A member of a third team of the tournament, in a map that is otherwise right.
        foreign = roster[0]
        async with db(env) as session:
            await session.execute(
                sa.update(models.Player).where(models.Player.id == foreign.id).values(team_id=teams[2].id)
            )
            await session.commit()
        await refused(team_map(case))
        async with db(env) as session:
            await session.execute(
                sa.update(models.Player).where(models.Player.id == foreign.id).values(team_id=teams[0].id)
            )
            await session.commit()
        read = await bind(team_map(case))
        assert read.status == Status.DONE and read.binding.revision == 1

    run(ingest_database, scenario)


# -- canonical documents are never decoded or derived ----------------------------------------------------------


def test_public_workshop_csv_document_never_reaches_the_decoder_or_derivation(ingest_database, monkeypatch):
    async def scenario(env):
        case = await new_case(env, "csv")
        calls = []

        class Forbidden(dict):
            def get(self, *args, **kwargs):
                calls.append(("decoder", args))
                raise AssertionError("a canonical document must not be decoded")

        async def derive(*args, **kwargs):
            calls.append(("derive", args))
            raise AssertionError("a canonical document must not be derived")

        monkeypatch.setattr(process, "INGESTORS", Forbidden())
        monkeypatch.setattr(
            process, "DISCIPLINES", {case.discipline: SimpleNamespace(derive_match=derive)}, raising=True
        )
        doc = build_document(case, external_id="csv-1")
        doc["source"] = {"kind": "workshop_csv", "external_id": "csv-1"}
        job_id = await submit(env, case, doc)
        assert await process_job(env, job_id) == Status.DONE
        assert calls == []
        async with db(env) as session:
            stored = (
                await session.execute(
                    sa.select(models.StatDef.code, models.StatsFact.value, models.StatsFact.workspace_member_id)
                    .join(models.StatDef, models.StatDef.id == models.StatsFact.stat_id)
                    .join(models.StatsMatch, models.StatsMatch.id == models.StatsFact.match_id)
                    .where(models.StatsMatch.encounter_game_id == case.game_id)
                )
            ).all()
        # exactly the supplied facts: nothing derived (performance/impact) was added, no value recomputed
        assert sorted((code, value) for code, value, _ in stored) == sorted(
            (fact["stat"], float(fact["value"])) for fact in doc["facts"]
        )

    run(ingest_database, scenario)


def test_failed_documents_are_failed_jobs_with_structured_errors_not_exceptions(ingest_database):
    async def scenario(env):
        case = await new_case(env, "fail")
        doc = build_document(case, external_id="fail-1")
        doc["map"] = "no-such-map"
        job_id = await submit(env, case, doc)
        assert await process_job(env, job_id) == Status.FAILED
        error = jobs.decode_error((await job_row(env, job_id)).error_message)
        assert error.code == "unknown_code" and error.issues[0].kind == "map"
        # a redelivery of the failed job does nothing
        assert await process_job(env, job_id) == Status.FAILED
        with pytest.raises(BaseAPIException):
            async with db(env) as session:
                await process.process_ingest_job(session, 999_999_999, env.s3)

    run(ingest_database, scenario)


def test_a_canonical_identity_owned_by_two_players_is_a_conflict_whatever_the_workspace_anchors(ingest_database):
    async def scenario(env):
        case = await new_case(env, "ident")
        handle = case.handles[0][0]
        async with db(env) as session:
            twin = models.User(name="twin-without-anchor")
            session.add(twin)
            await session.flush()
            session.add(
                models.SocialAccount(
                    user_id=twin.id,
                    provider=case.provider,
                    username=handle,
                    username_normalized=handle.lower(),
                    is_primary=True,
                )
            )
            await session.commit()
        async with db(env) as session:
            before = await side_effects(session, case.workspace_id)
        # Only one of the two owners is anchored in this workspace; that must not make the identity definite.
        job = await submit(env, case, external_id="ident-1")
        assert await process_job(env, job) == Status.FAILED
        error = jobs.decode_error((await job_row(env, job)).error_message)
        assert error.code == "identity_conflict" and handle.lower() in error.message
        async with db(env) as session:
            after = await side_effects(session, case.workspace_id)
        assert (after["matches"], after["users"], after["accounts"]) == (
            before["matches"],
            before["users"],
            before["accounts"],
        )

    run(ingest_database, scenario)


def test_a_decoded_bare_name_matching_several_players_narrows_to_the_workspaces_own(ingest_database):
    async def scenario(env):
        case = await new_case(env, "bare")
        full = case.handles[0][0]
        bare = full.split("#")[0]
        async with db(env) as session:
            stranger_user = models.User(name="bare-twin")
            session.add(stranger_user)
            await session.flush()
            session.add(
                models.SocialAccount(
                    user_id=stranger_user.id,
                    provider=case.provider,
                    username=f"{bare}#9999",
                    username_normalized=f"{bare}#9999".lower(),
                    is_primary=True,
                )
            )
            await session.commit()
        from shared.schemas.match_doc import MatchDoc
        from src.services.ingest.identity import lookup_identities

        doc = build_document(case, external_id="bare-1")
        doc["participants"] = [
            {**doc["participants"][0], "identity": {"provider": case.provider, "id": bare}},
        ]
        doc["teams"] = doc["teams"][:1]
        doc["facts"], doc["events"] = [], []
        async with db(env) as session:
            found = await lookup_identities(
                session, workspace_id=case.workspace_id, doc=MatchDoc.model_validate(doc), producer="decoded"
            )
        assert found == {doc["participants"][0]["key"]: case.player_ids[0][0]}

    run(ingest_database, scenario)


def test_derivation_uses_the_tournament_registration_rank_not_the_roster_snapshot(ingest_database):
    async def scenario(env):
        from shared.schemas.match_doc import MatchDoc
        from src.services.ingest.binding import bound_match, bound_participants, load_game_seats

        case = await new_case(env, "rank")
        async with db(env) as session:
            team = models.Team(tournament_id=case.tournament_id, name="Reg", balancer_name="Reg")
            session.add(team)
            await session.flush()
            await session.execute(
                sa.update(models.EncounterTeam)
                .where(models.EncounterTeam.id == case.team_ids[0])
                .values(team_id=team.id)
            )
            session.add(
                models.Player(
                    tournament_id=case.tournament_id,
                    workspace_member_id=case.member_ids[0][0],
                    team_id=team.id,
                    name="registered",
                    rank=1700,
                )
            )
            # a registered substitute of the second team: P4's lookup matched it like any roster player
            substitutes = models.Team(tournament_id=case.tournament_id, name="Reg2", balancer_name="Reg2")
            session.add(substitutes)
            await session.flush()
            await session.execute(
                sa.update(models.EncounterTeam)
                .where(models.EncounterTeam.id == case.team_ids[1])
                .values(team_id=substitutes.id)
            )
            session.add(
                models.Player(
                    tournament_id=case.tournament_id,
                    workspace_member_id=case.member_ids[1][0],
                    team_id=substitutes.id,
                    name="registered-sub",
                    rank=1500,
                    is_substitution=True,
                )
            )
            await session.commit()
        async with db(env) as session:
            doc = MatchDoc.model_validate(case.document)
            (game,) = await load_game_seats(
                session, workspace_id=case.workspace_id, discipline=case.discipline, game_ids=[case.game_id]
            )
            binding = bound_match(
                case.workspace_id, case.discipline, game, {f"t{i + 1}": s for i, s in enumerate(case.team_ids)}
            )
            members = {
                person.key: await session.get(
                    models.WorkspaceMember, case.member_ids[int(person.key[1]) - 1][int(person.key[2]) - 1]
                )
                for person in doc.participants
            }
            bound = await bound_participants(session, doc=doc, binding=binding, game=game, members=members)
        assert bound["p11"].rank == 1700, "the current registration rank, as P4 fed the baselines"
        assert bound["p12"].rank == 800, "no tournament-player row: the roster snapshot (P4's substitute input)"
        assert bound["p21"].rank == 1500, "a registered substitute keeps its registration rank too"
        assert bound["p22"].rank == 800

    run(ingest_database, scenario)


def test_a_map_outside_the_configured_pool_is_refused_before_any_replacement(ingest_database):
    async def scenario(env):
        case = await new_case(env, "pool")
        assert await process_job(env, await submit(env, case, external_id="pool-1")) == Status.DONE
        old = await snapshot(env, case)
        parked = await submit(env, case, _unknown_doc(case, "pool-parked"))
        assert await process_job(env, parked) == Status.AWAITING_LINK
        async with db(env) as session:
            other = models.CatalogEntity(
                discipline=case.discipline, kind="map", slug="pool-other", name="Pool other", attrs={}
            )
            session.add(other)
            await session.flush()
            config = models.PickBanConfig(
                tournament_id=case.tournament_id, kind=enums.PickBanKind.MAP, ruleset_json={"phases": []}
            )
            session.add(config)
            await session.flush()
            session.add(models.PickBanConfigItem(pick_ban_config_id=config.id, item_id=other.id))
            await session.commit()

        refused = await submit(env, case, external_id="pool-2")
        assert await process_job(env, refused) == Status.FAILED
        assert jobs.decode_error((await job_row(env, refused)).error_message).code == "map_not_in_pool"
        assert await snapshot(env, case) == old

        async with db(env) as session:
            with pytest.raises(IngestRejected) as admin_refused:
                await process.bind_ingest_job(
                    session,
                    job_id=parked,
                    request=BindIngestRequest(
                        encounter_game_id=case.game_id, teams=team_map(case), expected_revision=1
                    ),
                    user=admin(case),
                    s3=env.s3,
                )
        assert admin_refused.value.code == "map_not_in_pool" and admin_refused.value.status_code == 400
        assert (await job_row(env, parked)).status == Status.AWAITING_LINK
        assert await snapshot(env, case) == old

    run(ingest_database, scenario)
