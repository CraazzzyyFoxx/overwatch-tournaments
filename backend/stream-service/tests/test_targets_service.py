"""``StreamTargetsService`` — the domain rules on top of the shared repositories.

Two things live here that the SQL-shape guards in
``backend/tests/test_stream_repository.py`` cannot cover, because they are
Python, not SQL:

1. **Which statuses count as "active".** Finished tournaments are never polled.
2. **The merge rule when both consent sources name the same login.** Verified
   wins a collision because it carries ``provider_user_id``, which survives a
   channel rename; a typo'd self-declared nick must never shadow the proven one.

Repositories are faked in-process — no database, no compiled SQL — because these
tests are about the Python merge logic, not the queries underneath it.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any
from unittest import IsolatedAsyncioTestCase

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums  # noqa: E402
from shared.repository.stream import SelfDeclaredChannelRow, VerifiedChannelRow  # noqa: E402
from shared.testing import create_test_async_engine, ensure_test_postgres
from src.services import targets  # noqa: E402


class _FakeLinks:
    async def list_active_by_kind(self, session: Any, tournament_id: int, kind: str) -> list[Any]:
        return []

    async def list_active_by_kind_bulk(
        self, session: Any, tournament_ids: list[int], kind: str
    ) -> dict[int, list[Any]]:
        return {tid: [] for tid in tournament_ids}


class _FakeTargets:
    def __init__(self, *, self_declared: list[Any] | None = None, verified: list[Any] | None = None) -> None:
        self._self_declared = self_declared or []
        self._verified = verified or []

    async def list_active_tournaments(self, session: Any, statuses: Any) -> list[Any]:
        return []

    async def list_self_declared_channels(self, session: Any, tournament_ids: list[int]) -> list[Any]:
        return self._self_declared

    async def list_verified_channels(self, session: Any, tournament_ids: list[int]) -> list[Any]:
        return self._verified


def _service(
    *, self_declared: list[Any] | None = None, verified: list[Any] | None = None
) -> targets.StreamTargetsService:
    return targets.StreamTargetsService(
        links=_FakeLinks(),  # type: ignore[arg-type]
        targets=_FakeTargets(self_declared=self_declared, verified=verified),  # type: ignore[arg-type]
    )


class PolledTournamentTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def test_only_live_tournaments_with_a_lifecycle_node_in_play_are_polled(self) -> None:
        """Finished tournaments are never polled. A registration that is merely ``open`` can run for weeks with
        nobody broadcasting; polling it would burn a Helix bucket shared with identity-service for nothing."""
        ensure_test_postgres()
        tag = uuid.uuid4().hex[:10]
        engine = create_test_async_engine()
        connection = await engine.connect()
        transaction = await connection.begin()
        session = AsyncSession(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            workspace = models.Workspace(slug=f"tgt-{tag}", name=f"tgt-{tag}", disciplines_enabled=["overwatch"])
            session.add(workspace)
            await session.flush()
            cases = {
                "check_in": (enums.TournamentStatus.LIVE, [("registration", "check_in")], True),
                "open_only": (enums.TournamentStatus.LIVE, [("registration", "open")], False),
                "closed_registration_draft_formation": (
                    enums.TournamentStatus.LIVE,
                    [("registration", "closed"), ("formation", "draft")],
                    False,
                ),
                "forming": (enums.TournamentStatus.LIVE, [("formation", "forming")], True),
                "stage_ready": (enums.TournamentStatus.LIVE, [("stage", "ready")], True),
                "announcement": (enums.TournamentStatus.ANNOUNCEMENT, [("registration", "draft")], False),
                "completed": (enums.TournamentStatus.COMPLETED, [("stage", "completed")], False),
                "archived": (enums.TournamentStatus.ARCHIVED, [("stage", "completed")], False),
            }
            rule = models.ScoringRule(
                workspace_id=workspace.id, preset="wins", game_formula="win", end_formula="games >= best_of"
            )
            session.add(rule)
            await session.flush()
            ids: dict[str, int] = {}
            for name, (status, nodes, _polled) in cases.items():
                tournament = models.Tournament(
                    workspace_id=workspace.id,
                    discipline="overwatch",
                    name=f"{name} {tag}",
                    slug=f"{name}-{tag}",
                    status=status,
                )
                session.add(tournament)
                await session.flush()
                for kind, node_status in nodes:
                    stage_id = None
                    if kind == "stage":
                        stage = models.Stage(
                            tournament_id=tournament.id,
                            name="S",
                            stage_type=enums.StageType.ROUND_ROBIN,
                            scoring_rule_id=rule.id,
                        )
                        session.add(stage)
                        await session.flush()
                        stage_id = stage.id
                    session.add(
                        models.FlowNode(
                            tournament_id=tournament.id,
                            kind=kind,
                            name=kind,
                            status=node_status,
                            config={},
                            stage_id=stage_id,
                        )
                    )
                ids[name] = tournament.id
            await session.flush()

            polled = {t.tournament_id for t in await targets.StreamTargetsService().active_tournaments(session)}
        finally:
            await session.close()
            await transaction.rollback()
            await connection.close()
            await engine.dispose()

        self.assertEqual({ids[name] for name, case in cases.items() if case[2]}, polled & set(ids.values()))


class ParticipantMergeTests(IsolatedAsyncioTestCase):
    async def test_verified_wins_a_login_collision(self) -> None:
        """Same channel from both sources: keep the one carrying a stable id."""
        service = _service(
            self_declared=[SelfDeclaredChannelRow(tournament_id=7, player_id=11, twitch_login="CasterOne")],
            verified=[
                VerifiedChannelRow(
                    tournament_id=7,
                    user_id=11,
                    username="CasterOne",
                    username_normalized="casterone",
                    provider_user_id="id-42",
                )
            ],
        )

        result = await service.participant_channels_bulk(object(), [7])

        [channel] = result[7]
        self.assertEqual(channel.source, "verified")
        self.assertEqual(channel.provider_user_id, "id-42")
        self.assertEqual(channel.login, "casterone")

    async def test_self_declared_survives_without_a_verified_twin(self) -> None:
        service = _service(
            self_declared=[SelfDeclaredChannelRow(tournament_id=7, player_id=11, twitch_login=" SoloCaster ")],
        )

        result = await service.participant_channels_bulk(object(), [7])

        [channel] = result[7]
        self.assertEqual(channel.source, "self_declared")
        self.assertEqual(channel.login, "solocaster")
        self.assertIsNone(channel.provider_user_id)

    async def test_a_whitespace_only_login_is_dropped(self) -> None:
        """``registration_identity.handle`` is NOT NULL, so a useless answer
        arrives as blank text rather than as a missing value."""
        service = _service(
            self_declared=[SelfDeclaredChannelRow(tournament_id=7, player_id=11, twitch_login="   ")],
        )

        result = await service.participant_channels_bulk(object(), [7])

        self.assertEqual(result[7], [])

    async def test_every_requested_tournament_gets_an_entry_even_with_no_channels(self) -> None:
        """The poll tick indexes this dict by tournament id unconditionally; a
        missing key would be a KeyError on a perfectly normal empty tournament."""
        service = _service()

        result = await service.participant_channels_bulk(object(), [7, 8])

        self.assertEqual(result, {7: [], 8: []})

    async def test_channels_are_bucketed_by_their_own_tournament(self) -> None:
        """A channel from tournament 8 must never leak into tournament 7's plan."""
        service = _service(
            self_declared=[
                SelfDeclaredChannelRow(tournament_id=7, player_id=11, twitch_login="alice"),
                SelfDeclaredChannelRow(tournament_id=8, player_id=12, twitch_login="bob"),
            ],
        )

        result = await service.participant_channels_bulk(object(), [7, 8])

        self.assertEqual([c.login for c in result[7]], ["alice"])
        self.assertEqual([c.login for c in result[8]], ["bob"])


class UrlHelperTests(IsolatedAsyncioTestCase):
    async def test_channel_urls_yield_a_pollable_login(self) -> None:
        self.assertEqual(targets.twitch_channel_from_url("https://twitch.tv/CasterOne"), "casterone")
        self.assertEqual(targets.twitch_channel_from_url("https://www.twitch.tv/casterone/"), "casterone")

    async def test_unpollable_twitch_urls_yield_none(self) -> None:
        """A VOD or a category page has no live status — the reader must render
        ``live=None`` ("no detection"), never ``live=False`` ("checked, offline")."""
        self.assertIsNone(targets.twitch_channel_from_url("https://twitch.tv/videos/123456"))
        self.assertIsNone(targets.twitch_channel_from_url("https://twitch.tv/directory/game/Overwatch"))
        self.assertIsNone(targets.twitch_channel_from_url("https://twitch.tv/"))
        self.assertIsNone(targets.twitch_channel_from_url("https://youtube.com/@owt"))

    async def test_platform_detection(self) -> None:
        self.assertEqual(targets.platform_from_url("https://www.twitch.tv/casterone"), "twitch")
        self.assertEqual(targets.platform_from_url("https://youtu.be/abc"), "youtube")
        self.assertEqual(targets.platform_from_url("https://vk.com/video1"), "other")
