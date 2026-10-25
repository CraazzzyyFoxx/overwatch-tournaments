"""The VOD chronology end to end on real PostgreSQL: the session upsert and VOD stamps, the chronology SQL, and the
two RPC reads' JSON. One rolled-back transaction; skipped when the test database is unreachable.

Consent (``participant_channels_bulk``) is stubbed: its queries are guarded in ``backend/tests/test_stream_repository.py``,
and stubbing it to include a vetoed player is what proves the roster veto drops that player on its own.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.models.stats.ingest import IngestJobStatus
from shared.repository import StreamSessionObservation, StreamSessionRepository
from shared.testing import create_test_async_engine, ensure_test_postgres
from src.rpc import reads
from src.services.chronology import stream_chronology_reader
from src.services.targets import ParticipantChannel

T0 = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)
DISCIPLINE = "overwatch"


def _at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


class ChronologyDbTest(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        self.tag = uuid.uuid4().hex[:10]
        self.sessions = StreamSessionRepository()

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def _add(self, *rows: object) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def _seed(self) -> None:
        s = self.session
        self.ws = models.Workspace(slug=f"chr-{self.tag}", name=f"chr-{self.tag}", disciplines_enabled=[DISCIPLINE])
        await self._add(self.ws)
        self.tournament = models.Tournament(
            workspace_id=self.ws.id,
            discipline=DISCIPLINE,
            name=f"chr {self.tag}",
            slug=f"chr-{self.tag}",
            status=enums.TournamentStatus.LIVE,
            start_date=T0,
            end_date=T0 + timedelta(days=1),
            pov_stream_delay_s=60,
        )
        rule = models.ScoringRule(
            workspace_id=self.ws.id, preset="wins", game_formula="win", end_formula="games >= best_of"
        )
        await self._add(self.tournament, rule)
        self.alpha = models.Team(tournament_id=self.tournament.id, name=f"Alpha {self.tag}", balancer_name="a")
        self.bravo = models.Team(tournament_id=self.tournament.id, name=f"Bravo {self.tag}", balancer_name="b")
        await self._add(self.alpha, self.bravo)

        self.users: dict[str, models.User] = {}
        for key, team, visible in (("ann", self.alpha, True), ("bob", self.bravo, True), ("vic", self.alpha, False)):
            user = models.User(name=f"{key}-{self.tag}", stream_visible=visible)
            await self._add(user)
            member = models.WorkspaceMember(workspace_id=self.ws.id, player_id=user.id)
            await self._add(member)
            await self._add(
                models.Player(
                    tournament_id=self.tournament.id,
                    team_id=team.id,
                    workspace_member_id=member.id,
                    name=key,
                    is_substitution=False,
                    is_newcomer=False,
                    is_newcomer_role=False,
                )
            )
            self.users[key] = user

        def encounter(name: str, started: datetime, ended: datetime | None) -> models.Encounter:
            return models.Encounter(
                workspace_id=self.ws.id,
                discipline=DISCIPLINE,
                tournament_id=self.tournament.id,
                scoring_rule_id=rule.id,
                name=name,
                slot_count=2,
                started_at=started,
                ended_at=ended,
            )

        # Logged: one valid map, one whose time is the job's creation time, one with none -> map chapters only.
        self.logged = encounter("Alpha vs Bravo", _at(10), _at(70))
        # No logs: one open series chapter.
        self.series = encounter("Bravo vs Alpha", _at(120), None)
        await self._add(self.logged, self.series)
        for enc in (self.logged, self.series):
            for slot, team in enumerate((self.alpha, self.bravo), 1):
                s.add(
                    models.EncounterTeam(
                        encounter_id=enc.id,
                        tournament_id=self.tournament.id,
                        slot=slot,
                        team_id=team.id,
                        name=team.name,
                    )
                )
        await s.flush()

        maps = [
            models.CatalogEntity(
                discipline=DISCIPLINE, kind="map", slug=f"{name}-{self.tag}", name=f"{name} {self.tag}"
            )
            for name in ("kings", "ilios", "busan")
        ]
        job = models.IngestJob(
            workspace_id=self.ws.id,
            discipline=DISCIPLINE,
            source_kind="test",
            external_id=f"chr-{self.tag}",
            content_hash="0" * 64,
            raw_ref="test",
            status=IngestJobStatus.DONE,
            created_at=_at(40),
        )
        games = [models.EncounterGame(encounter_id=self.logged.id, position=position) for position in (1, 2, 3)]
        await self._add(*maps, job, *games)
        await self._add(
            *(
                models.StatsMatch(
                    workspace_id=self.ws.id,
                    discipline=DISCIPLINE,
                    encounter_id=self.logged.id,
                    encounter_game_id=game.id,
                    ingest_job_id=job.id,
                    map_entity_id=entity.id,
                    played_at=played_at,
                    duration_s=600.0,
                )
                for game, entity, played_at in zip(games, maps, (_at(10), _at(40), None), strict=True)
            )
        )

    async def _record(self, key: str, stream_id: str, started: datetime, seen: datetime) -> None:
        await self.sessions.record_observed(
            self.session,
            [
                StreamSessionObservation(
                    tournament_id=self.tournament.id,
                    user_id=self.users[key].id,
                    channel=key,
                    broadcaster_id=f"b-{key}",
                    stream_id=f"{stream_id}-{self.tag}",
                    started_at=started,
                )
            ],
            seen_at=seen,
        )

    async def _ids(self) -> dict[str, int]:
        rows = await self.session.execute(
            sa.select(models.StreamSession.stream_id, models.StreamSession.id).where(
                models.StreamSession.tournament_id == self.tournament.id
            )
        )
        return {stream_id.removesuffix(f"-{self.tag}"): session_id for stream_id, session_id in rows.all()}

    async def test_sessions_resolve_and_read_back_as_chapters(self) -> None:
        await self._seed()
        await self._record("ann", "s-ann", T0, _at(60))
        await self._record("ann", "s-ann", T0, _at(180))  # the same broadcast seen again: one row, moved end
        await self._record("bob", "s-bob", _at(30), _at(180))
        await self._record("vic", "s-vic", T0, _at(180))
        await self._record("ann", "s-gone", _at(-300), _at(-200))
        await self._record("bob", "s-open", _at(30), _at(180))
        ids = await self._ids()
        self.assertEqual(len(ids), 5)

        now = datetime.now(UTC)
        pending = await self.sessions.list_unresolved(
            self.session, seen_since=_at(-600), checked_before=now - timedelta(minutes=10)
        )
        self.assertLessEqual({ids["s-ann"], ids["s-open"]}, {row.id for row in pending})
        await self.sessions.mark_vod_attempts(
            self.session,
            attempted=[ids[key] for key in ("s-ann", "s-bob", "s-vic", "s-gone", "s-open")],
            resolved={ids["s-ann"]: "900", ids["s-bob"]: "901", ids["s-vic"]: "902", ids["s-gone"]: "903"},
            checked_at=now,
        )
        await self.sessions.mark_rechecked(self.session, alive=[], gone=[ids["s-gone"]], checked_at=now)
        pending = await self.sessions.list_unresolved(
            self.session, seen_since=_at(-600), checked_before=now - timedelta(minutes=10)
        )
        self.assertFalse({ids["s-ann"], ids["s-open"]} & {row.id for row in pending})

        consenting = AsyncMock(
            return_value={
                self.tournament.id: [
                    ParticipantChannel(
                        player_id=self.users[key].id, login=key, provider_user_id=None, source="verified"
                    )
                    for key in ("ann", "bob", "vic")
                ]
            }
        )
        with patch.object(stream_chronology_reader._targets, "participant_channels_bulk", consenting):
            tournament = await reads.tournament_vods(self.session, {"tournament_id": str(self.tournament.id)})
            first = await reads.encounter_vods(self.session, {"encounter_id": str(self.logged.id)})
            second = await reads.encounter_vods(self.session, {"encounter_id": str(self.series.id)})

        ann, bob = self.users["ann"], self.users["bob"]

        def player(user: models.User, team: models.Team) -> dict:
            return {"id": user.id, "name": user.name, "avatar_url": None, "team": {"id": team.id, "name": team.name}}

        def chapter(enc: models.Encounter, offset_s: int, *, position: int | None = None) -> dict:
            return {
                "encounter_id": enc.id,
                "encounter_name": enc.name,
                "kind": "series" if position is None else "map",
                "map_position": position,
                "map_name": None if position is None else f"kings {self.tag}",
                "offset_s": offset_s,
            }

        # Delay 60 s. Ann's window opens at T0 - 1 min: King's Row (T0 + 10 min) at 660 s, the open series
        # (T0 + 2 h) at 7260 s; Ilios's time is the job's creation time and Busan has none, so neither is a chapter.
        ann_vod = {
            "vod_id": "900",
            "url": "https://www.twitch.tv/videos/900",
            "channel": "ann",
            "started_at": T0,
            "ended_at": _at(180),
            "player": player(ann, self.alpha),
            "chapters": [chapter(self.logged, 660, position=1), chapter(self.series, 7260)],
        }
        # Bob's window opens at T0 + 29 min, after King's Row ended: only the series, at 5460 s.
        bob_vod = {
            "vod_id": "901",
            "url": "https://www.twitch.tv/videos/901",
            "channel": "bob",
            "started_at": _at(30),
            "ended_at": _at(180),
            "player": player(bob, self.bravo),
            "chapters": [chapter(self.series, 5460)],
        }
        # Vic is vetoed, the gone VOD is hidden, the unresolved broadcast has no VOD. Newest first.
        self.assertEqual(tournament.model_dump(), {"vods": [bob_vod, ann_vod]})
        self.assertEqual(
            first.model_dump(), {"vods": [{**ann_vod, "chapters": [chapter(self.logged, 660, position=1)]}]}
        )
        # By team name: Alpha before Bravo.
        self.assertEqual(
            second.model_dump(),
            {"vods": [{**ann_vod, "chapters": [chapter(self.series, 7260)]}, bob_vod]},
        )
