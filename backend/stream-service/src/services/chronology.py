"""Read model for the POV VOD chronology: which matches each participant's past broadcast shows, and where.

Sources, all batched (a fixed number of statements per read, never one per VOD or per encounter):

* ``stream.session`` — broadcasts the poll tick saw live whose VOD Helix resolved and has not reported gone;
* consent — ``StreamTargetsService.participant_channels_bulk``, the same approved-registration + opt-in + veto
  rules the poll tick polls by, applied NOW rather than when the broadcast was recorded: a player who withdrew
  consent disappears from past broadcasts too;
* players and teams — ``StreamTargetRepository.list_roster``, ranked by ``publishable_players`` exactly as the
  live block ranks them; every team the player is rostered on counts for chapters (a substitute on two teams
  gets both);
* timings — ``StreamChronologyRepository``; the chapter rules themselves are ``src.domain.chronology``.

READ-ONLY: the only writer of ``stream.session`` is the poll tick.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import StreamChronologyRepository, StreamSessionRepository, StreamTargetRepository
from src.domain.chronology import EncounterTiming, LoggedMap, chapters
from src.schemas.stream import StreamChapterRead, StreamVodRead, StreamVodsRead
from src.services.targets import StreamTargetsService
from src.services.tournament_streams import publishable_players

__all__ = ("StreamChronologyReader", "stream_chronology_reader")


class StreamChronologyReader:
    """Assembles the chronology of one tournament's POV VODs, optionally narrowed to one encounter."""

    def __init__(
        self,
        *,
        targets: StreamTargetsService = StreamTargetsService(),
        rosters: StreamTargetRepository = StreamTargetRepository(),
        sessions: StreamSessionRepository = StreamSessionRepository(),
        chronology: StreamChronologyRepository = StreamChronologyRepository(),
    ) -> None:
        self._targets = targets
        self._rosters = rosters
        self._sessions = sessions
        self._chronology = chronology

    async def encounter_tournament_id(self, session: AsyncSession, encounter_id: int) -> int | None:
        """The encounter's tournament; ``None`` for a mix's encounter. 404 for an unknown encounter."""
        owner = await self._chronology.encounter_owner(session, encounter_id)
        if owner is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
        return owner.tournament_id

    async def build(
        self, session: AsyncSession, tournament_id: int, *, encounter_id: int | None = None
    ) -> StreamVodsRead:
        """Every alive VOD of a consenting participant with at least one chapter.

        Tournament-wide: newest broadcast first. With ``encounter_id``: only that encounter's chapters, ordered by
        (team name, player name, start). Caller MUST have gated visibility already.
        """
        recorded = await self._sessions.list_alive_vods(session, tournament_id)
        if not recorded:
            return StreamVodsRead(vods=[])
        consenting = {
            channel.player_id
            for channel in (await self._targets.participant_channels_bulk(session, [tournament_id])).get(
                tournament_id, []
            )
        }
        recorded = [row for row in recorded if row.user_id in consenting]
        if not recorded:
            return StreamVodsRead(vods=[])

        roster = await self._rosters.list_roster(session, tournament_id, {row.user_id for row in recorded})
        players = publishable_players(roster)
        teams_of: dict[int, set[int]] = defaultdict(set)
        for row in roster:
            if row.stream_visible is not False and row.team_id is not None:
                teams_of[row.user_id].add(row.team_id)

        seats = await self._chronology.team_encounters(
            session, tournament_id, {team for teams in teams_of.values() for team in teams}, encounter_id=encounter_id
        )
        maps: dict[int, list[LoggedMap]] = defaultdict(list)
        for logged in await self._chronology.logged_maps(session, {seat.encounter_id for seat in seats}):
            maps[logged.encounter_id].append(
                LoggedMap(
                    played_at=logged.played_at,
                    duration_s=logged.duration_s,
                    position=logged.map_position,
                    map_name=logged.map_name,
                )
            )
        timings: dict[int, EncounterTiming] = {}
        encounters_of_team: dict[int, set[int]] = defaultdict(set)
        for seat in seats:
            encounters_of_team[seat.team_id].add(seat.encounter_id)
            timings[seat.encounter_id] = EncounterTiming(
                encounter_id=seat.encounter_id,
                name=seat.name,
                started_at=seat.started_at,
                ended_at=seat.ended_at,
                maps=tuple(maps[seat.encounter_id]),
            )
        delay_s = await self._chronology.pov_stream_delay_s(session, tournament_id)

        vods: list[StreamVodRead] = []
        for row in recorded:
            player = players.get(row.user_id)
            if player is None:
                continue
            encounter_ids = {e for team in teams_of[row.user_id] for e in encounters_of_team[team]}
            found = chapters(
                (timings[e] for e in encounter_ids),
                started_at=row.started_at,
                last_seen_at=row.last_seen_at,
                delay_s=delay_s,
            )
            if not found:
                continue
            vods.append(
                StreamVodRead(
                    vod_id=row.vod_id,
                    url=f"https://www.twitch.tv/videos/{row.vod_id}",
                    channel=row.channel,
                    started_at=row.started_at,
                    ended_at=row.last_seen_at,
                    player=player,
                    chapters=[StreamChapterRead(**asdict(chapter)) for chapter in found],
                )
            )

        if encounter_id is not None:
            # The query already returns newest first, which is the tournament-wide order.
            vods.sort(
                key=lambda vod: (vod.player.team.name if vod.player.team else "", vod.player.name, vod.started_at)
            )
        return StreamVodsRead(vods=vods)


stream_chronology_reader = StreamChronologyReader()
