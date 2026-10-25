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
from shared.repository import StreamChronologyRepository, StreamSessionObservation, StreamSessionRepository
from shared.repository.stream_session import ChronologyPregameRow
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

        # Logged: King's Row has a real log time; Ilios's time is the job's creation (the decoder's fallback) and
        # its log has no clock in the name, so it falls to the end of round 2's bans; Busan has no log time but a
        # UTC+3 host's clock in its file name, decided by round 3's bans.
        self.logged = encounter("Alpha vs Bravo", _at(10), _at(70))
        # No logs: one open series chapter, from the pre-game room's opening rather than the organizer's start.
        self.series = encounter("Bravo vs Alpha", _at(120), None)
        await self._add(self.logged, self.series)
        seats: dict[tuple[int, int], models.EncounterTeam] = {}
        for enc in (self.logged, self.series):
            for slot, team in enumerate((self.alpha, self.bravo), 1):
                seats[enc.id, slot] = models.EncounterTeam(
                    encounter_id=enc.id,
                    tournament_id=self.tournament.id,
                    slot=slot,
                    team_id=team.id,
                    name=team.name,
                )
        await self._add(*seats.values())

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
        named_job = models.IngestJob(
            workspace_id=self.ws.id,
            discipline=DISCIPLINE,
            source_kind="test",
            external_id=f"chr-named-{self.tag}",
            content_hash="1" * 64,
            raw_ref="test",
            filename="Log-2026-10-25-21-00-00.txt",
            status=IngestJobStatus.DONE,
            created_at=_at(80),
        )
        await self._add(*maps, job, named_job)
        games = [models.EncounterGame(encounter_id=self.logged.id, position=position) for position in (1, 2, 3)]
        games[1].map_id = maps[1].id
        # A cancelled position is history: its round's bans below must not make it a chapter.
        cancelled = models.EncounterGame(
            encounter_id=self.logged.id, position=4, state=enums.EncounterGameState.CANCELLED
        )
        await self._add(*games, cancelled)
        await self._add(
            *(
                models.StatsMatch(
                    workspace_id=self.ws.id,
                    discipline=DISCIPLINE,
                    encounter_id=self.logged.id,
                    encounter_game_id=game.id,
                    ingest_job_id=ingest.id,
                    map_entity_id=entity.id,
                    played_at=played_at,
                    duration_s=600.0,
                )
                for game, entity, ingest, played_at in zip(
                    games, maps, (job, job, named_job), (_at(10), _at(40), None), strict=True
                )
            )
        )

        def event(enc: models.Encounter, action: str, minutes: float, **data: object) -> models.EncounterRoomEvent:
            return models.EncounterRoomEvent(
                encounter_id=enc.id, action=action, source="system", kind="map", data=data, created_at=_at(minutes)
            )

        await self._add(
            event(self.logged, "step_revealed", 45, step_index=3, round=2),
            event(self.logged, "step_auto_resolved", 44, step_index=2, round=2),
            event(self.logged, "step_revealed", 59, step_index=5, round=3),
            event(self.logged, "step_revealed", 100, step_index=7, round=4),
            event(self.logged, "acted", 150, step_index=3, round=2),  # not a reveal
            event(self.logged, "step_revealed", 200, step_index=0, round=None),  # a flat session: no round
        )
        await self._add(
            models.EncounterReadiness(
                encounter_id=self.series.id, encounter_team_id=seats[self.series.id, 1].id, created_at=_at(110)
            ),
            models.EncounterReadiness(
                encounter_id=self.series.id, encounter_team_id=seats[self.series.id, 2].id, created_at=_at(112)
            ),
            models.PickBanSession(
                encounter_id=self.series.id,
                kind=enums.PickBanKind.MAP,
                pool_json={},
                seed_source=enums.VetoSeedSource.BRACKET_SLOT,
                resolved_sequence_json=[],
                ruleset_json={},
                started_at=_at(115),
            ),
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

        chronology = StreamChronologyRepository()
        # The room journal's rounds: the last reveal per round, a round-less (flat) reveal and a non-reveal ignored.
        self.assertEqual(
            sorted(await chronology.round_ends(self.session, [self.logged.id])),
            [(self.logged.id, 2, _at(45)), (self.logged.id, 3, _at(59)), (self.logged.id, 4, _at(100))],
        )
        self.assertEqual(
            await chronology.pregame_starts(self.session, [self.series.id]),
            [ChronologyPregameRow(self.series.id, _at(115), _at(112))],
        )

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

        def chapter(enc: models.Encounter, offset_s: int, *, position: int | None = None, name: str = "") -> dict:
            return {
                "encounter_id": enc.id,
                "encounter_name": enc.name,
                "kind": "series" if position is None else "map",
                "map_position": position,
                "map_name": None if position is None else f"{name} {self.tag}",
                "offset_s": offset_s,
            }

        # Delay 60 s, so Ann's window opens at T0 - 1 min. King's Row by its log time (T0 + 10 min); Ilios at round
        # 2's last reveal (T0 + 45), named by its game; Busan's 21:00 on a UTC+3 host is T0 + 60, a minute after
        # round 3's bans; the series at the room's opening (T0 + 115), not the organizer's T0 + 120.
        logged = [
            chapter(self.logged, 660, position=1, name="kings"),
            chapter(self.logged, 2760, position=2, name="ilios"),
            chapter(self.logged, 3660, position=3, name="busan"),
        ]
        ann_vod = {
            "vod_id": "900",
            "url": "https://www.twitch.tv/videos/900",
            "channel": "ann",
            "started_at": T0,
            "ended_at": _at(180),
            "player": player(ann, self.alpha),
            "chapters": [*logged, chapter(self.series, 6960)],
        }
        # Bob's window opens at T0 + 29 min, after King's Row ended.
        bob_logged = [
            chapter(self.logged, 960, position=2, name="ilios"),
            chapter(self.logged, 1860, position=3, name="busan"),
        ]
        bob_vod = {
            "vod_id": "901",
            "url": "https://www.twitch.tv/videos/901",
            "channel": "bob",
            "started_at": _at(30),
            "ended_at": _at(180),
            "player": player(bob, self.bravo),
            "chapters": [*bob_logged, chapter(self.series, 5160)],
        }
        # Vic is vetoed, the gone VOD is hidden, the unresolved broadcast has no VOD; the cancelled position 4 is
        # no chapter despite its round. Newest first.
        self.assertEqual(tournament.model_dump(), {"vods": [bob_vod, ann_vod]})
        # By team name: Alpha before Bravo.
        self.assertEqual(
            first.model_dump(),
            {"vods": [{**ann_vod, "chapters": logged}, {**bob_vod, "chapters": bob_logged}]},
        )
        self.assertEqual(
            second.model_dump(),
            {
                "vods": [
                    {**ann_vod, "chapters": [chapter(self.series, 6960)]},
                    {**bob_vod, "chapters": [chapter(self.series, 5160)]},
                ]
            },
        )
