"""Sheet sync change detection, rank keeping, failure atomicity and per-feed exclusion, against PostgreSQL.

Real tables on purpose: every claim is about what a sync leaves committed (registrations, ranks, bindings, the
invalidation rows) or about two transactions meeting on one feed, which a fake session cannot witness.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.domain.forms import FormField, FormSchema, FormSection
from shared.models.platform.realtime import WorkspaceEvent
from shared.models.registration.registration import (
    RegistrationForm,
    RegistrationFormVersion,
    RegistrationGoogleSheetFeed,
)
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import Tournament
from shared.services.ontology import project_disciplines
from shared.services.realtime import INVALIDATION_EVENT_TYPE, Resource
from shared.testing import real_db_sessionmaker
from src.services.registration import sheet_sync

_SCHEMA = FormSchema(
    sections=[
        FormSection(
            key="accounts",
            fields=[
                FormField(key="identity_battlenet", kind="builtin", required=True),
                FormField(key="public_notes", kind="builtin"),
            ],
        )
    ]
)
_HEADERS = ["BattleTag", "Role", "Note"]
# A role column and no rank column: the sheet has nothing to say about any rank.
_MAPPING = {
    "targets": {
        "source_record_key": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
        "identity_battlenet": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag_list"},
        "source_roles.primary": {"mode": "columns", "columns": ["Role"], "parser": "role_token"},
        "public_notes": {"mode": "columns", "columns": ["Note"], "parser": "join_lines"},
    }
}


async def _seed(session: Any) -> dict[str, Any]:
    await project_disciplines(session)
    suffix = uuid.uuid4().hex[:8]
    workspace = Workspace(slug=f"sheetchg-{suffix}", name=f"Sheet changes {suffix}", disciplines_enabled=["overwatch"])
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Sheet changes {suffix}",
        slug=f"sheetchg-{suffix}",
        discipline="overwatch",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    form = RegistrationForm(tournament_id=tournament.id, workspace_id=workspace.id)
    session.add(form)
    await session.flush()
    form.current_version = RegistrationFormVersion(
        form_id=form.id, number=1, schema_json=_SCHEMA.model_dump(mode="json")
    )
    session.add(
        RegistrationGoogleSheetFeed(
            tournament_id=tournament.id,
            source_url="http://sheet.example/changes",
            sheet_id="sheet-changes",
            mapping_config_json=_MAPPING,
            value_mapping_json={"roles": {"Support": "support"}},
        )
    )
    await session.commit()
    return {
        "workspace_id": workspace.id,
        "tournament_id": tournament.id,
        "tags": (f"Sy{suffix}#1111", f"Sz{suffix}#2222"),
    }


def _serve(monkeypatch: pytest.MonkeyPatch, rows: list[list[str]]) -> None:
    """The sheet every following fetch sees. ``rows`` stays live, so a test edits a cell between syncs."""

    async def _fetch(*_args: Any, **_kwargs: Any) -> list[list[str]]:
        return [_HEADERS, *rows]

    monkeypatch.setattr(sheet_sync, "fetch_google_sheet_rows", _fetch)


async def _sync(session: Any, seeded: dict[str, Any]) -> sheet_sync.SheetSyncResult:
    return await sheet_sync.sheet_sync_service.sync_google_sheet_feed(session, seeded["tournament_id"])


async def _registration_invalidations(session: Any, tournament_id: int) -> int:
    payloads = (
        await session.scalars(
            sa.select(WorkspaceEvent.payload).where(
                WorkspaceEvent.tournament_id == tournament_id,
                WorkspaceEvent.event_type == INVALIDATION_EVENT_TYPE,
            )
        )
    ).all()
    return sum(Resource.TOURNAMENT_REGISTRATIONS.value in payload["resources"] for payload in payloads)


async def _registration_count(session: Any, tournament_id: int) -> int:
    return await session.scalar(
        sa.select(sa.func.count())
        .select_from(models.Registration)
        .where(models.Registration.tournament_id == tournament_id)
    )


def _roles(what: Any, tournament_id: int) -> sa.Select:
    return (
        sa.select(what)
        .join(models.Registration, models.Registration.id == models.RegistrationRole.registration_id)
        .where(models.Registration.tournament_id == tournament_id)
    )


def _bindings(what: Any, tournament_id: int) -> sa.Select:
    return (
        sa.select(what)
        .select_from(models.RegistrationGoogleSheetBinding)
        .join(
            RegistrationGoogleSheetFeed,
            RegistrationGoogleSheetFeed.id == models.RegistrationGoogleSheetBinding.feed_id,
        )
        .where(RegistrationGoogleSheetFeed.tournament_id == tournament_id)
    )


async def _drop(session: Any, seeded: dict[str, Any]) -> None:
    player_ids = (
        await session.scalars(
            sa.select(models.WorkspaceMember.player_id).where(
                models.WorkspaceMember.workspace_id == seeded["workspace_id"]
            )
        )
    ).all()
    await session.execute(sa.delete(WorkspaceEvent).where(WorkspaceEvent.tournament_id == seeded["tournament_id"]))
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded["workspace_id"]))
    await session.execute(sa.delete(models.User).where(models.User.id.in_(player_ids)))
    await session.commit()


def test_an_unchanged_sheet_applies_counts_and_invalidates_nothing(db_session, monkeypatch) -> None:
    """The second sync of an identical sheet skips the row: not updated, its binding not re-stamped, and no
    ``TOURNAMENT_REGISTRATIONS`` invalidation, so no cache drop and no client refetch every five minutes."""

    async def _run() -> None:
        seeded = await _seed(db_session)
        _serve(monkeypatch, [[seeded["tags"][0], "Support", "a note"]])
        seen_at = _bindings(models.RegistrationGoogleSheetBinding.last_seen_at, seeded["tournament_id"])

        first = await _sync(db_session, seeded)
        invalidations = await _registration_invalidations(db_session, seeded["tournament_id"])
        first_seen_at = await db_session.scalar(seen_at)
        again = await _sync(db_session, seeded)

        assert (first.created, first.updated) == (1, 0)
        assert invalidations >= 1, "the creating sync must be visible here, or the next check proves nothing"
        assert (again.created, again.updated, again.withdrawn, again.total) == (0, 0, 0, 1)
        assert again.feed.last_sync_status == "success"
        assert await _registration_invalidations(db_session, seeded["tournament_id"]) == invalidations
        assert await db_session.scalar(seen_at) == first_seen_at

        await _drop(db_session, seeded)

    asyncio.run(_run())


def test_a_rank_the_sheet_does_not_map_survives_a_changed_row(db_session, monkeypatch) -> None:
    """Autofill writes ``rank_value`` without pinning the balancer profile. When the row changes and is re-applied,
    a sheet with no rank column must leave that rank where autofill put it."""

    async def _run() -> None:
        seeded = await _seed(db_session)
        rows = [[seeded["tags"][0], "Support", "first note"]]
        _serve(monkeypatch, rows)
        await _sync(db_session, seeded)
        role = (await db_session.scalars(_roles(models.RegistrationRole, seeded["tournament_id"]))).one()
        role.rank_value = 2500  # what rank_autofill's apply writes; balancer_profile_overridden_at stays NULL
        await db_session.commit()

        rows[0][2] = "second note"
        again = await _sync(db_session, seeded)

        assert again.updated == 1
        ranks = (await db_session.scalars(_roles(models.RegistrationRole.rank_value, seeded["tournament_id"]))).all()
        assert ranks == [2500]

        await _drop(db_session, seeded)

    asyncio.run(_run())


def test_a_failure_mid_sync_commits_none_of_the_rows_before_it(db_session, monkeypatch) -> None:
    """The second row fails after the first was written: the failure is stamped on the feed, and nothing the
    sync wrote before it reaches the tables with that stamp."""

    async def _run() -> None:
        seeded = await _seed(db_session)
        first_tag, second_tag = seeded["tags"]
        _serve(monkeypatch, [[first_tag, "Support", "one"], [second_tag, "Support", "two"]])
        monkeypatch.setattr(
            sheet_sync.registration_service,
            "ensure_player_identity",
            AsyncMock(side_effect=[None, BaseAPIException(status_code=409, detail="handle taken")]),
        )

        with pytest.raises(BaseAPIException):
            await _sync(db_session, seeded)

        assert await _registration_count(db_session, seeded["tournament_id"]) == 0
        assert await db_session.scalar(_bindings(sa.func.count(), seeded["tournament_id"])) == 0
        stamp = (
            await db_session.execute(
                sa.select(RegistrationGoogleSheetFeed.last_sync_status, RegistrationGoogleSheetFeed.last_error).where(
                    RegistrationGoogleSheetFeed.tournament_id == seeded["tournament_id"]
                )
            )
        ).one()
        assert tuple(stamp) == ("failed", "handle taken")

        await _drop(db_session, seeded)

    asyncio.run(_run())


def test_a_feed_another_sync_is_applying_is_skipped(monkeypatch) -> None:
    """Scheduler and RPC meeting on one feed: while the first sync is mid-apply, the second returns ``locked``
    with nothing done, instead of racing the first into the same binding rows."""

    async def _run() -> None:
        async with real_db_sessionmaker() as Session:
            async with Session() as session:
                seeded = await _seed(session)
            _serve(monkeypatch, [[seeded["tags"][0], "Support", "a note"]])
            entered, release = asyncio.Event(), asyncio.Event()

            async def _hold_first_apply(*_args: Any, **_kwargs: Any) -> None:
                if not entered.is_set():
                    entered.set()
                    await release.wait()

            monkeypatch.setattr(sheet_sync.registration_service, "ensure_player_identity", _hold_first_apply)

            async with Session() as first, Session() as second:
                running = asyncio.create_task(_sync(first, seeded))
                await asyncio.wait_for(entered.wait(), timeout=30)
                try:
                    skipped = await asyncio.wait_for(_sync(second, seeded), timeout=30)
                finally:
                    release.set()
                done = await running

            assert skipped.locked
            assert (skipped.created, skipped.updated, skipped.withdrawn, skipped.total) == (0, 0, 0, 0)
            assert not done.locked and done.created == 1
            async with Session() as session:
                assert await _registration_count(session, seeded["tournament_id"]) == 1
                await _drop(session, seeded)

    asyncio.run(_run())
