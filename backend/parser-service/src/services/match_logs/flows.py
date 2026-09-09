from __future__ import annotations

import asyncio
import csv

import pandas as pd
import sqlalchemy as sa
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.clients.s3 import S3Client
from shared.core import impact as impact_consts
from shared.core.social import SocialProvider
from shared.messaging.config import TOURNAMENT_EVENTS_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.repository.identity import UserRepository
from shared.repository.match_logs import MatchEventRepository, MatchKillFeedRepository, MatchStatisticsRepository
from shared.repository.tournament import MatchRepository
from shared.schemas.events import (
    EncounterCompletedEvent,
    TournamentStandingsInvalidatedEvent,
)
from shared.services import social_identity
from shared.services.newcomer_status import load_prior_participation
from shared.services.realtime import Resource, Scope, emit, enqueue_invalidation_outbox
from src import models
from src.core import enums, errors, pagination
from src.core.config import settings
from src.domain.match_logs import impact
from src.services import catalog_aliases
from src.services.baselines import service as baselines_service
from src.services.encounter import flows as encounter_flows
from src.services.encounter import service as encounter_service
from src.services.hero import service as hero_service
from src.services.map import flows as map_flows
from src.services.match_logs.binary import binary_match_logs
from src.services.match_logs.event_models import KillEvent, MatchEventRow, PlayerStatRow
from src.services.match_logs.limits import match_log_oversize_message
from src.services.match_logs.realtime import emit_logs_updated
from src.services.team import service as team_service
from src.services.tournament import flows as tournament_flows

from . import service

_LOG_DF_COLUMNS = ["event_type", "time", "data", "round_number"]
_LOG_EVENT_TYPE_BY_VALUE = {member.value: member for member in enums.LogEventType}


def _empty_log_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_LOG_DF_COLUMNS)


def _index_rows_by_event_type(df: pd.DataFrame) -> dict[enums.LogEventType, pd.DataFrame]:
    if df.empty:
        return {}
    return {event_type: group for event_type, group in df.groupby("event_type", sort=False)}  # noqa: C416


async def _bulk_insert(session: AsyncSession, model: type, rows: list[dict]) -> None:
    if rows:
        await session.execute(sa.insert(model), rows)


def _kill_feed_row(kill: models.MatchKillFeed) -> dict:
    return {
        "match_id": kill.match_id,
        "time": kill.time,
        "round": kill.round,
        "fight": kill.fight,
        "ability": kill.ability,
        "killer_id": kill.killer_id,
        "killer_hero_id": kill.killer_hero_id,
        "killer_team_id": kill.killer_team_id,
        "victim_id": kill.victim_id,
        "victim_hero_id": kill.victim_hero_id,
        "victim_team_id": kill.victim_team_id,
        "damage": kill.damage,
        "is_critical_hit": kill.is_critical_hit,
        "is_environmental": kill.is_environmental,
    }


def _match_event_row(event: models.MatchEvent) -> dict:
    return {
        "match_id": event.match_id,
        "time": event.time,
        "round": event.round,
        "team_id": event.team_id,
        "user_id": event.user_id,
        "hero_id": event.hero_id,
        "related_team_id": event.related_team_id,
        "related_user_id": event.related_user_id,
        "related_hero_id": event.related_hero_id,
        "name": event.name,
    }


def _processor_from_bytes(
    tournament: models.Tournament,
    name: str,
    raw_bytes: bytes,
    s3: S3Client,
    log_record_id: int | None,
) -> MatchLogProcessor:
    decoded_lines = [line for line in raw_bytes.decode().split("\n") if line]
    return MatchLogProcessor(tournament, name, decoded_lines, s3, log_record_id)


def _winner_team_id(encounter: models.Encounter) -> int | None:
    if encounter.home_score > encounter.away_score:
        return encounter.home_team_id
    if encounter.away_score > encounter.home_score:
        return encounter.away_team_id
    return None


def _encounter_is_completed(encounter: models.Encounter) -> bool:
    # Single form (encres0001 pins it to result_status == CONFIRMED).
    return encounter.status == enums.EncounterStatus.COMPLETED


async def _enqueue_match_log_tournament_events(
    session: AsyncSession,
    encounter: models.Encounter,
) -> None:
    # A parsed match log moves the encounter's score and the standings built on
    # top of it. Both halves of the invalidation: emit() for the clients and
    # this service's own caches, the outbox row for tournament-service and
    # app-service, which cache the same reads and cannot rely on Redis
    # pub/sub's at-most-once delivery.
    invalidated = (Resource.TOURNAMENT_ENCOUNTERS, Resource.TOURNAMENT_STANDINGS)
    scope = Scope.tournament(encounter.tournament_id)
    await emit(session, scope=scope, invalidates=list(invalidated), entity_ids={"encounter_ids": [encounter.id]})
    await enqueue_invalidation_outbox(session, scope=scope, resources=invalidated)

    await enqueue_outbox_event(
        session,
        TournamentStandingsInvalidatedEvent(
            tournament_id=encounter.tournament_id,
            source_service="parser-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key="tournament.standings.invalidated",
    )

    if not _encounter_is_completed(encounter):
        return

    await enqueue_outbox_event(
        session,
        EncounterCompletedEvent(
            tournament_id=encounter.tournament_id,
            encounter_id=encounter.id,
            home_team_id=encounter.home_team_id,
            away_team_id=encounter.away_team_id,
            winner_team_id=_winner_team_id(encounter),
            source_service="parser-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key="tournament.encounter.completed",
    )


_match_repo = MatchRepository()
_stats_repo = MatchStatisticsRepository()
_events_repo = MatchEventRepository()
_kill_feed_repo = MatchKillFeedRepository()
_user_repo = UserRepository()


class MatchLogProcessor:
    def __init__(
        self,
        tournament: models.Tournament,
        name: str,
        data_in: list[str],
        s3: S3Client,
        log_record_id: int | None = None,
    ):
        self.tournament: models.Tournament = tournament
        self.filename: str = name
        # The ingestion row this run came from. Recorded on every match it
        # writes so provenance is a foreign key, not a filename comparison
        # across two differently normalised columns.
        self.log_record_id: int | None = log_record_id
        self.df: pd.DataFrame = self._load_and_format_data(data_in)
        self._rows_by_type = _index_rows_by_event_type(self.df)
        self.heroes_map: dict[str, models.Hero] = {}  # Hero cache: canonical names + aliases
        # Hero names that matched neither a canonical name nor an alias. Batched
        # here rather than written on the spot: `get_hero` is synchronous (no
        # `await` possible) and runs once per kill event. Flushed in `start()`.
        self.hero_misses: set[str] = set()
        self._s3 = s3

    def _load_and_format_data(self, data_in: list[str]) -> pd.DataFrame:
        # Cap the number of lines before building the DataFrame — an oversized or
        # adversarial log would otherwise be parsed in full (review MEDIUM).
        max_lines = settings.max_match_log_lines
        if len(data_in) > max_lines:
            raise errors.ApiHTTPException(
                status_code=413,
                detail=[
                    errors.ApiExc(
                        code="match_log_too_large",
                        msg=f"Match log {self.filename} exceeds the maximum of {max_lines} lines",
                    )
                ],
            )

        valid_lines = [line for line in data_in if line.strip()]
        if not valid_lines:
            logger.warning(f"Match log {self.filename} has no valid lines.")
            return _empty_log_df()

        parsed_rows: list[tuple[enums.LogEventType, float, list[str]]] = []
        for line, row_parts in zip(valid_lines, csv.reader(valid_lines), strict=True):
            if len(row_parts) < 3:
                logger.warning(f"Skipping malformed row in {self.filename}: {line}")
                continue

            raw_event_type = row_parts[1].strip()
            if raw_event_type.lower() == "meta":
                continue

            event_type = _LOG_EVENT_TYPE_BY_VALUE.get(raw_event_type)
            if event_type is None:
                logger.warning(f"Skipping row with unknown event type '{raw_event_type}' in {self.filename}")
                continue

            try:
                time = float(row_parts[2])
            except ValueError:
                logger.warning(f"Skipping row with invalid time '{row_parts[2]}' in {self.filename}")
                continue

            parsed_rows.append((event_type, time, row_parts[3:]))

        if not parsed_rows:
            logger.warning(f"Match log {self.filename} resulted in an empty DataFrame.")
            return _empty_log_df()

        return self._assign_round_numbers(pd.DataFrame(parsed_rows, columns=["event_type", "time", "data"]))

    @staticmethod
    def _assign_round_numbers(df: pd.DataFrame) -> pd.DataFrame:
        df["round_number"] = (df["event_type"] == enums.LogEventType.RoundStart).cumsum()
        return df

    def _get_rows(
        self,
        event_type: enums.LogEventType | None = None,
        round_number: int | None = None,
    ) -> pd.DataFrame:
        if event_type is None:
            temp_df = self.df
        else:
            temp_df = self._rows_by_type.get(event_type)
            if temp_df is None:
                return _empty_log_df()
        if round_number is not None:
            temp_df = temp_df[temp_df["round_number"] == round_number]
        return temp_df

    def get_team_names(self) -> tuple[str, str] | tuple[None, None]:
        match_start_events = self._get_rows(enums.LogEventType.MatchStart)
        if match_start_events.empty:
            logger.error("MatchStart event not found.")
            raise errors.ApiHTTPException(
                status_code=400, detail=[errors.ApiExc(code="match_log_corrupt", msg="MatchStart event missing")]
            )

        row_data = match_start_events.iloc[0]["data"]
        return row_data[2], row_data[3]

    def get_teams_raw(self) -> dict[str, list[str]]:
        team1_name, team2_name = self.get_team_names()
        if not team1_name or not team2_name:
            return {"unknown1": [], "unknown2": []}

        cache: dict[str, list[str]] = {team1_name: [], team2_name: []}

        match_end_events = self._get_rows(enums.LogEventType.MatchEnd)
        boundary_time = match_end_events["time"].min() if not match_end_events.empty else float("inf")

        player_joined_df = self.df[
            (self.df["event_type"] == enums.LogEventType.PlayerJoined) & (self.df["time"] < boundary_time)
        ]

        for row in player_joined_df.itertuples(index=False):
            player, team = row.data[0], row.data[1]
            if team == team1_name and player not in cache[team1_name]:
                cache[team1_name].append(player)
            elif team == team2_name and player not in cache[team2_name]:
                cache[team2_name].append(player)

        return cache

    def get_match_score_and_time(self) -> tuple[float, int, int]:
        match_end_events = self._get_rows(enums.LogEventType.MatchEnd)
        if match_end_events.empty:
            logger.error(f"Match log {self.filename} has no MatchEnd event.")
            raise errors.ApiHTTPException(
                status_code=400, detail=[errors.ApiExc(code="match_not_finished", msg="MatchEnd event missing")]
            )

        row_data = match_end_events.iloc[0]["data"]  # Assuming one MatchEnd
        return float(match_end_events.iloc[0]["time"]), int(row_data[1]), int(row_data[2])

    async def validate(self, is_raise: bool) -> bool:
        if self._get_rows(enums.LogEventType.MatchEnd).empty:
            msg = f"Match log {self.filename} in tournament {self.tournament.name} is not finished"
            logger.warning(msg)
            await binary_match_logs.delete_log(self._s3, self.tournament.id, self.filename)
            if is_raise:
                raise errors.ApiHTTPException(
                    status_code=400,
                    detail=[errors.ApiExc(code="match_not_finished", msg=msg)],
                )
            return False
        return True

    async def get_map(self, session: AsyncSession) -> models.Map:
        match_start_events = self._get_rows(enums.LogEventType.MatchStart)
        if match_start_events.empty:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[errors.ApiExc(code="match_log_corrupt", msg="MatchStart event missing for map info")],
            )

        row_data = match_start_events.iloc[0]["data"]
        gamemode_raw, map_name_raw = row_data[1], row_data[0]
        # Raw, untranslated: `aliases` in the catalog carries what the three
        # hardcoded dicts used to, and an unresolved name lands in the miss queue.
        return await map_flows.get_by_name_or_alias_and_gamemode(
            session, map_name_raw, gamemode_raw, log_record_id=self.log_record_id
        )

    async def _preload_data(self, session: AsyncSession):
        heroes_db, _ = await hero_service.get_all(session, pagination.PaginationSortParams(per_page=-1))
        self.heroes_map = {}
        for hero in heroes_db:
            self.heroes_map[hero.name] = hero
            # `setdefault`, not `[alias] =`: one hero's canonical name must never
            # be shadowed by another hero's alias.
            for alias in hero.aliases:
                self.heroes_map.setdefault(alias, hero)

    def get_hero(self, hero_name: str) -> models.Hero:
        hero = self.heroes_map.get(hero_name)
        if not hero:
            # A hero miss is soft — all three callers swallow it (kill skipped,
            # `hero_id=None`, stat row skipped). So the name has to reach the
            # queue, otherwise the data loss shows up only in the service log.
            self.hero_misses.add(hero_name)
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="hero_not_found", msg=f"Hero '{hero_name}' not found in preloaded cache.")],
            )
        return hero

    async def get_players_by_battle_names(
        self, session: AsyncSession
    ) -> dict[str, list[tuple[str, models.User | None]]]:
        teams_raw = self.get_teams_raw()
        teams_names = list(teams_raw.keys())
        team_name_1 = teams_names[0] if len(teams_names) > 0 else "unknown1"
        team_name_2 = teams_names[1] if len(teams_names) > 1 else "unknown2"

        teams: dict[str, list[tuple[str, models.User | None]]] = {
            team_name_1: [],
            team_name_2: [],
        }

        # Resolve every log name across both teams in a single query rather than
        # one (or two) SELECTs per player (review L14).
        all_battle_names = [player for players in teams_raw.values() for player in players]
        users_by_name = await service.get_users_by_battle_names(session, all_battle_names)

        for team_name, players in teams_raw.items():
            for player in players:
                user_found = users_by_name.get(player)
                teams[team_name].append((player, user_found))

                if user_found:
                    logger.debug(
                        f"User [id={user_found.id} name={user_found.name}] "
                        f"found by battle name {player} in team {team_name}"
                    )
                else:
                    logger.warning(f"User not found by battle name {player} in team {team_name}")
        return teams

    async def find_team_by_players(
        self, session: AsyncSession, players: list[tuple[str, models.User | None]]
    ) -> models.Team:
        team_entities = ["players", "players.user", "players.workspace_member"]
        player_ids = [p.id for _, p in players if p is not None]
        if len(player_ids) >= 3:
            team_db = await team_service.get_by_players_by_ids_tournament(
                session,
                player_ids,
                self.tournament,
                team_entities,
            )
            if team_db:
                return team_db

        for reverse in [True, False]:
            team_players_search = players.copy()
            if reverse:
                team_players_search.reverse()

            resolved_ids = [p.id for _, p in team_players_search if p is not None]
            for i in range(len(team_players_search) - 2):
                current_player_ids_to_search = resolved_ids[i:]

                if len(current_player_ids_to_search) < 3:
                    continue

                team_db = await team_service.get_by_players_by_ids_tournament(
                    session,
                    current_player_ids_to_search,
                    self.tournament,
                    team_entities,
                )
                if team_db:
                    return team_db

        player_names_str = ", ".join([name for name, _ in players])
        await binary_match_logs.delete_log(self._s3, self.tournament.id, self.filename)
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="team_not_found",
                    msg=f"Team not found for players [{player_names_str}] in tournament {self.tournament.name}",
                )
            ],
        )

    async def find_teams_by_players(
        self, session: AsyncSession
    ) -> tuple[
        tuple[models.Team, list[tuple[str, models.User | None]]],
        tuple[models.Team, list[tuple[str, models.User | None]]],
    ]:
        home_team_name, away_team_name = self.get_team_names()
        logger.info(f"Home team name: {home_team_name}, away team name: {away_team_name}")

        players_by_team_log_name = await self.get_players_by_battle_names(session)
        logger.debug(f"Players from log: {players_by_team_log_name}")

        home_players_list = players_by_team_log_name.get(home_team_name, [])
        away_players_list = players_by_team_log_name.get(away_team_name, [])

        if not home_players_list:
            logger.warning(f"No players found in log for declared home team: {home_team_name}")
        if not away_players_list:
            logger.warning(f"No players found in log for declared away team: {away_team_name}")

        home_team_db = await self.find_team_by_players(session, home_players_list)
        away_team_db = await self.find_team_by_players(session, away_players_list)

        return (home_team_db, home_players_list), (
            away_team_db,
            away_players_list,
        )

    @staticmethod
    async def get_players_by_team_and_battle_name(
        session: AsyncSession,
        team: models.Team,
        players_from_log: list[tuple[str, models.User | None]],
    ) -> list[tuple[str, models.Player | None]]:
        # Resolve all roster players for the team in a single query instead of
        # one (or two) SELECTs per log name (review L14).
        battle_names = [battle_name_log for battle_name_log, _ in players_from_log]
        players_by_name = await service.get_players_by_team_and_battle_names(session, team, battle_names)

        players_out: list[tuple[str, models.Player | None]] = []
        for battle_name_log, _ in players_from_log:
            resolved_player_in_team = players_by_name.get(battle_name_log)
            players_out.append((battle_name_log, resolved_player_in_team))

            if resolved_player_in_team:
                logger.debug(
                    f"Player [id={resolved_player_in_team.id} name={resolved_player_in_team.name}] "
                    f"found for battle name '{battle_name_log}' in team '{team.name}'"
                )
            else:
                logger.warning(f"Player object not found for battle name '{battle_name_log}' in team '{team.name}'")
        return players_out

    async def process_kills(
        self,
        match: models.Match,
        players_map: dict[str, models.Player],
    ) -> list[models.MatchKillFeed]:
        kill_feed_objects: list[models.MatchKillFeed] = []

        kill_events_df = self._get_rows(enums.LogEventType.Kill)
        if kill_events_df.empty:
            return []

        kill_events_df = kill_events_df.sort_values(by="time").reset_index(drop=True)

        for row in kill_events_df.itertuples(index=False):
            try:
                kill = KillEvent.from_data(row.data)
            except (ValueError, ValidationError) as e:
                logger.warning(f"Skipping malformed kill event at t={row.time}: {e}")
                continue

            if kill.attacker not in players_map:
                logger.warning(f"Killer '{kill.attacker}' not found in players map. Skipping kill.")
                continue
            if kill.victim not in players_map:
                logger.warning(f"Victim '{kill.victim}' not found in players map. Skipping kill.")
                continue

            killer_player = players_map[kill.attacker]
            victim_player = players_map[kill.victim]

            try:
                killer_hero = self.get_hero(kill.attacker_hero)
                victim_hero = self.get_hero(kill.victim_hero)
            except errors.ApiHTTPException as e:
                logger.warning(f"Skipping kill at t={row.time} (unknown hero): {e}")
                continue

            kill_feed_objects.append(
                models.MatchKillFeed(
                    match_id=match.id,
                    time=row.time,
                    round=row.round_number,
                    fight=0,
                    killer_id=killer_player.workspace_member.player_id,
                    killer_hero_id=killer_hero.id,
                    killer_team_id=killer_player.team_id,
                    victim_id=victim_player.workspace_member.player_id,
                    victim_hero_id=victim_hero.id,
                    victim_team_id=victim_player.team_id,
                    ability=kill.ability,
                    damage=kill.damage,
                    is_critical_hit=kill.is_critical_hit,
                    is_environmental=kill.is_environmental,
                )
            )

        if not kill_feed_objects:
            return []

        # Cluster kills into fights (new round OR >15s lull). Shared with the
        # history backfill so live and backfilled first_picks/impact agree.
        impact.assign_fights(kill_feed_objects)
        return kill_feed_objects

    def _format_match_event_generic(
        self,
        match: models.Match,
        players_map: dict[str, models.Player],
        time: float,
        round_number: int,
        data: list[str],
        event_name_enum: enums.MatchEvent,
    ) -> models.MatchEvent:
        try:
            evt = MatchEventRow.from_data(data, event_name_enum)
        except (ValueError, ValidationError) as e:
            raise ValueError(f"Cannot parse {event_name_enum.value} at t={time}: {e}") from e

        if evt.player not in players_map:
            raise ValueError(f"Player '{evt.player}' for event {event_name_enum.value} at t={time} not in players_map.")

        player = players_map[evt.player]

        hero_id: int | None = None
        if evt.hero:
            try:
                hero_id = self.get_hero(evt.hero).id
            except errors.ApiHTTPException:
                logger.warning(
                    f"Unknown hero '{evt.hero}' for {event_name_enum.value} at t={time}, hero_id set to None."
                )

        related_player_id: int | None = None
        related_team_id: int | None = None
        related_hero_id: int | None = None

        if evt.related_hero:
            try:
                related_hero_id = self.get_hero(evt.related_hero).id
            except errors.ApiHTTPException:
                logger.warning(f"Unknown related_hero '{evt.related_hero}' for {event_name_enum.value} at t={time}.")

        if evt.related_player:
            if evt.related_player not in players_map:
                logger.warning(f"MercyRez target '{evt.related_player}' not in players_map.")
            else:
                related_player_obj = players_map[evt.related_player]
                related_player_id = related_player_obj.workspace_member.player_id
                related_team_id = related_player_obj.team_id

        return models.MatchEvent(
            match_id=match.id,
            time=time,
            round=round_number,
            team_id=player.team_id,
            user_id=player.workspace_member.player_id,
            hero_id=hero_id,
            related_hero_id=related_hero_id,
            related_team_id=related_team_id,
            related_user_id=related_player_id,
            name=event_name_enum,
        )

    async def process_events(
        self,
        session: AsyncSession,
        match: models.Match,
        players_map: dict[str, models.Player],
    ) -> list[models.MatchEvent]:
        event_type_map = [
            (enums.LogEventType.OffensiveAssist, enums.MatchEvent.OffensiveAssist),
            (enums.LogEventType.DefensiveAssist, enums.MatchEvent.DefensiveAssist),
            (enums.LogEventType.UltimateCharged, enums.MatchEvent.UltimateCharged),
            (enums.LogEventType.UltimateStart, enums.MatchEvent.UltimateStart),
            (enums.LogEventType.UltimateEnd, enums.MatchEvent.UltimateEnd),
            (enums.LogEventType.HeroSwap, enums.MatchEvent.HeroSwap),
            (enums.LogEventType.EchoDuplicateStart, enums.MatchEvent.EchoDuplicateStart),
            (enums.LogEventType.EchoDuplicateEnd, enums.MatchEvent.EchoDuplicateEnd),
        ]

        all_match_event_objects: list[models.MatchEvent] = []
        for log_event_type, match_event_enum in event_type_map:
            event_df = self._get_rows(log_event_type)
            for row in event_df.itertuples(index=False):
                try:
                    match_event_obj = self._format_match_event_generic(
                        match, players_map, row.time, row.round_number, row.data, match_event_enum
                    )
                    all_match_event_objects.append(match_event_obj)
                except ValueError as e:
                    logger.warning(f"Skipping event creation due to error: {e}")
                    continue

        return all_match_event_objects

    @staticmethod
    def _create_stat_object(
        match: models.Match,
        name: enums.LogStatsName,
        player: models.Player,
        match_round: int,
        hero_id: int | None,
        value: float,
    ) -> models.MatchStatistics:
        return models.MatchStatistics(
            match_id=match.id,
            round=match_round,
            team_id=player.team_id,
            user_id=player.workspace_member.player_id,
            hero_id=hero_id,
            name=name,
            value=value,
        )

    async def _get_player_stat_base_df(self, players_map: dict[str, models.Player]) -> pd.DataFrame:
        player_stat_events = self._get_rows(enums.LogEventType.PlayerStat)
        if player_stat_events.empty:
            return pd.DataFrame()

        stat_records = []
        for row in player_stat_events.itertuples(index=False):
            try:
                stat_row = PlayerStatRow.from_data(row.data)
            except (ValueError, ValidationError) as e:
                logger.warning(f"PlayerStat: Skipping malformed row at round {row.round_number}: {e}")
                continue

            if stat_row.player not in players_map:
                logger.warning(f"PlayerStat: Player '{stat_row.player}' not in players_map. Skipping.")
                continue

            player_model = players_map[stat_row.player]

            try:
                hero_model = self.get_hero(stat_row.hero)
            except errors.ApiHTTPException:
                logger.warning(
                    f"PlayerStat: Unknown hero '{stat_row.hero}' for player '{stat_row.player}' "
                    f"at round {row.round_number}. Skipping stat entry."
                )
                continue

            current_round = int(row.round_number)

            for stat_name_enum, value in stat_row.stat_values.items():
                stat_records.append(
                    {
                        "player_log_name": stat_row.player,
                        "player_id": player_model.id,
                        "player_model": player_model,
                        "hero_id": hero_model.id,
                        "hero_class": hero_model.type,
                        "round": current_round,
                        "stat_name": stat_name_enum,
                        "value": value,
                    }
                )

        return pd.DataFrame(stat_records)

    def _calculate_and_add_derived_stats(
        self,
        match: models.Match,
        df: pd.DataFrame,
        is_mvp_calc: bool = False,
        impact_ctx: impact.ImpactContext | None = None,
    ):
        required_cols = [
            enums.LogStatsName.Eliminations,
            enums.LogStatsName.Deaths,
            enums.LogStatsName.OffensiveAssists,
            enums.LogStatsName.DefensiveAssists,
            enums.LogStatsName.HeroDamageDealt,
            enums.LogStatsName.DamageTaken,
            enums.LogStatsName.FinalBlows,
            enums.LogStatsName.DamageBlocked,
            enums.LogStatsName.HealingDealt,
        ]
        temp_derived_stats = []
        for stat_col in required_cols:
            if stat_col not in df.columns:
                df[stat_col] = 0.0

        df["KD"] = df[enums.LogStatsName.Eliminations] / df[enums.LogStatsName.Deaths].replace(0, 1)
        df["Assists"] = df[enums.LogStatsName.OffensiveAssists] + df[enums.LogStatsName.DefensiveAssists]
        df["KDA"] = (df[enums.LogStatsName.Eliminations] + df["Assists"]) / df[enums.LogStatsName.Deaths].replace(0, 1)
        df["DamageDelta"] = df[enums.LogStatsName.HeroDamageDealt] - df[enums.LogStatsName.DamageTaken]
        df["FBE"] = df[enums.LogStatsName.FinalBlows] / df[enums.LogStatsName.Eliminations].replace(0, 1)
        df["DamageFB"] = df[enums.LogStatsName.HeroDamageDealt] / df[enums.LogStatsName.FinalBlows].replace(0, 1)

        derived_stat_names = {
            "KD": enums.LogStatsName.KD,
            "KDA": enums.LogStatsName.KDA,
            "DamageDelta": enums.LogStatsName.DamageDelta,
            "FBE": enums.LogStatsName.FBE,
            "DamageFB": enums.LogStatsName.DamageFB,
            "Assists": enums.LogStatsName.Assists,
        }
        for col_name, stat_enum in derived_stat_names.items():
            records = df[["player_model", "round", "hero_id", col_name]].to_dict(orient="records")
            temp_derived_stats.extend(
                self._create_stat_object(match, stat_enum, r["player_model"], r["round"], r.get("hero_id"), r[col_name])
                for r in records
            )

        if is_mvp_calc:
            df["PerformancePoints"] = (
                df[enums.LogStatsName.Eliminations] * 500
                + df[enums.LogStatsName.FinalBlows] * 250
                + df["Assists"] * 50
                + df[enums.LogStatsName.HeroDamageDealt]
                + df[enums.LogStatsName.HealingDealt] * 1
                - df[enums.LogStatsName.Deaths] * 750
                + df[enums.LogStatsName.DamageBlocked] * 0.1
            )

            perf_records = df[["player_model", "round", "hero_id", "PerformancePoints"]].to_dict(orient="records")
            temp_derived_stats.extend(
                self._create_stat_object(
                    match,
                    enums.LogStatsName.PerformancePoints,
                    r["player_model"],
                    r["round"],
                    r.get("hero_id"),
                    r["PerformancePoints"],
                )
                for r in perf_records
            )

            df_perf_rank = df.sort_values(by=["round", "PerformancePoints"], ascending=[True, False])
            df_perf_rank["Performance"] = df_perf_rank.groupby("round").cumcount() + 1

            rank_records = df_perf_rank[["player_model", "round", "hero_id", "Performance"]].to_dict(orient="records")
            temp_derived_stats.extend(
                self._create_stat_object(
                    match,
                    enums.LogStatsName.Performance,
                    r["player_model"],
                    r["round"],
                    r.get("hero_id"),
                    r["Performance"],
                )
                for r in rank_records
            )

            if impact_ctx is not None and impact_ctx.baselines is not None:
                df = impact.add_impact_scores(
                    df,
                    players=impact_ctx.players,
                    baselines=impact_ctx.baselines,
                    has_killfeed=impact_ctx.has_killfeed,
                )
                for stat_member in (
                    enums.LogStatsName.ImpactPoints,
                    enums.LogStatsName.OverperformanceScore,
                ):
                    impact_records = df[["player_model", "round", "hero_id", stat_member]].to_dict(orient="records")
                    temp_derived_stats.extend(
                        self._create_stat_object(
                            match, stat_member, r["player_model"], r["round"], r.get("hero_id"), r[stat_member]
                        )
                        for r in impact_records
                    )

                df_impact_rank = df.sort_values(by=["round", enums.LogStatsName.ImpactPoints], ascending=[True, False])
                df_impact_rank["_impact_rank"] = df_impact_rank.groupby("round").cumcount() + 1
                impact_rank_records = df_impact_rank[["player_model", "round", "hero_id", "_impact_rank"]].to_dict(
                    orient="records"
                )
                temp_derived_stats.extend(
                    self._create_stat_object(
                        match,
                        enums.LogStatsName.ImpactRank,
                        r["player_model"],
                        r["round"],
                        r.get("hero_id"),
                        r["_impact_rank"],
                    )
                    for r in impact_rank_records
                )
            elif impact_ctx is not None:
                logger.warning(
                    f"Impact baselines missing for match {match.id} — skipping impact stats "
                    f"({enums.LogStatsName.ImpactPoints.value})"
                )

        return temp_derived_stats

    async def create_stats(
        self,
        session: AsyncSession,
        match: models.Match,
        players_map: dict[str, models.Player],
        kill_feed: list[models.MatchKillFeed] | None = None,
    ) -> list[models.MatchStatistics]:
        cumulative_stats_df = await self._get_player_stat_base_df(players_map)
        if cumulative_stats_df.empty:
            logger.info(f"No PlayerStat events found for match {match.id}. Skipping stat creation.")
            return []

        player_id_to_model_map = (
            cumulative_stats_df.drop_duplicates(subset=["player_id"]).set_index("player_id")["player_model"].to_dict()
        )

        cumulative_stats_df = cumulative_stats_df.sort_values(by=["player_id", "hero_id", "stat_name", "round"])

        cumulative_stats_df["discrete_value"] = (
            cumulative_stats_df.groupby(["player_id", "hero_id", "stat_name"])["value"]
            .diff()
            .fillna(cumulative_stats_df["value"])
        )

        all_stat_objects: list[models.MatchStatistics] = []

        discrete_per_hero_df = cumulative_stats_df[cumulative_stats_df["round"] > 0].copy()
        records_per_hero = discrete_per_hero_df[
            ["stat_name", "player_model", "round", "hero_id", "discrete_value"]
        ].to_dict(orient="records")
        for r in records_per_hero:
            all_stat_objects.append(
                self._create_stat_object(
                    match, r["stat_name"], r["player_model"], r["round"], r["hero_id"], r["discrete_value"]
                )
            )

        discrete_all_heroes_per_round_df = discrete_per_hero_df.groupby(
            ["player_id", "round", "stat_name"], as_index=False
        )["discrete_value"].sum()

        records_all_heroes = discrete_all_heroes_per_round_df[
            ["player_id", "stat_name", "round", "discrete_value"]
        ].to_dict(orient="records")
        for r in records_all_heroes:
            player_model = player_id_to_model_map[r["player_id"]]
            all_stat_objects.append(
                self._create_stat_object(match, r["stat_name"], player_model, r["round"], None, r["discrete_value"])
            )

        max_round = cumulative_stats_df["round"].max()
        final_cumulative_df = cumulative_stats_df[cumulative_stats_df["round"] == max_round].copy()

        records_final_cumulative = final_cumulative_df[["stat_name", "player_model", "hero_id", "value"]].to_dict(
            orient="records"
        )
        for r in records_final_cumulative:
            all_stat_objects.append(
                self._create_stat_object(match, r["stat_name"], r["player_model"], 0, r["hero_id"], r["value"])
            )

        final_all_heroes_df = final_cumulative_df.groupby(["player_id", "stat_name"], as_index=False)["value"].sum()

        records_final_all_heroes = final_all_heroes_df[["player_id", "stat_name", "value"]].to_dict(orient="records")
        for r in records_final_all_heroes:
            player_model = player_id_to_model_map[r["player_id"]]
            all_stat_objects.append(self._create_stat_object(match, r["stat_name"], player_model, 0, None, r["value"]))

        hero_derived_df = discrete_per_hero_df.pivot_table(
            index=["player_id", "round", "hero_id"], columns="stat_name", values="discrete_value", fill_value=0
        ).reset_index()

        round_derived_df = discrete_all_heroes_per_round_df.pivot_table(
            index=["player_id", "round"], columns="stat_name", values="discrete_value", fill_value=0
        ).reset_index()
        round_derived_df["hero_id"] = None

        match_hero_derived_df = final_cumulative_df.pivot_table(
            index=["player_id", "hero_id"], columns="stat_name", values="value", fill_value=0
        ).reset_index()
        match_hero_derived_df["round"] = 0

        match_derived_df = final_all_heroes_df.pivot_table(
            index=["player_id"], columns="stat_name", values="value", fill_value=0
        ).reset_index()
        match_derived_df["round"] = 0
        match_derived_df["hero_id"] = None

        for df in [hero_derived_df, round_derived_df, match_hero_derived_df, match_derived_df]:
            df["player_model"] = df["player_id"].map(player_id_to_model_map)

        # --- MVP impact scoring inputs (spec 2026-07-10) --------------------
        # Event stats derived from the kill feed (FirstPicks/FirstDeaths/…) are
        # emitted as their own MatchStatistics rows AND merged into the two MVP
        # pivots so add_impact_scores can read them. Kill feed is keyed by
        # workspace_member.player_id (== user_id on the stat rows); the pivots
        # are keyed by roster player.id, so we bridge via user_to_player.
        hero_types = {h.id: h.type for h in self.heroes_map.values()}
        user_to_player = {p.workspace_member.player_id: p for p in players_map.values()}
        has_killfeed = bool(kill_feed)

        events_df = impact.build_event_counts(kill_feed or [], hero_types)
        if not events_df.empty:
            events_df["player_id"] = events_df["user_id"].map(
                lambda uid: user_to_player[uid].id if uid in user_to_player else None
            )
            events_df = events_df.dropna(subset=["player_id"])
            events_df["player_id"] = events_df["player_id"].astype(int)
            # Round 0 is the synthetic match-total sentinel in the pivots; the
            # per-round pivot only holds round > 0, and the match total is the
            # sum across those real rounds (mirrors the stat pipeline).
            events_df = events_df[events_df["round"] > 0]

        if not events_df.empty:
            for stat_name in impact_consts.EVENT_STATS:
                member = enums.LogStatsName[stat_name]
                for r in events_df.itertuples(index=False):
                    all_stat_objects.append(
                        self._create_stat_object(
                            match,
                            member,
                            user_to_player[r.user_id],
                            int(r.round),
                            None,
                            float(getattr(r, stat_name)),
                        )
                    )

            totals = events_df.groupby(["player_id", "user_id"], as_index=False)[list(impact_consts.EVENT_STATS)].sum()
            for stat_name in impact_consts.EVENT_STATS:
                member = enums.LogStatsName[stat_name]
                for r in totals.itertuples(index=False):
                    all_stat_objects.append(
                        self._create_stat_object(
                            match,
                            member,
                            user_to_player[r.user_id],
                            0,
                            None,
                            float(getattr(r, stat_name)),
                        )
                    )

            event_cols = ["player_id", "round", *impact_consts.EVENT_STATS]
            round_derived_df = round_derived_df.merge(
                events_df[event_cols].rename(columns={s: enums.LogStatsName[s] for s in impact_consts.EVENT_STATS}),
                on=["player_id", "round"],
                how="left",
            )
            match_events = totals.assign(round=0)
            match_derived_df = match_derived_df.merge(
                match_events[event_cols].rename(columns={s: enums.LogStatsName[s] for s in impact_consts.EVENT_STATS}),
                on=["player_id", "round"],
                how="left",
            )

        # Ensure every event column exists and is NaN-free on both MVP pivots,
        # so add_impact_scores never sees a NaN (matches with no kill feed hit
        # this path directly).
        for df_ in (round_derived_df, match_derived_df):
            for s in impact_consts.EVENT_STATS:
                member = enums.LogStatsName[s]
                if member not in df_.columns:
                    df_[member] = 0.0
                df_[member] = df_[member].fillna(0.0)

        playtime_df = final_cumulative_df[final_cumulative_df["stat_name"] == enums.LogStatsName.HeroTimePlayed][
            ["player_id", "hero_id", "value"]
        ].rename(columns={"value": "seconds"})
        roles = impact.dominant_roles(playtime_df, hero_types)

        player_refs = {
            p.id: impact.PlayerRef(
                player_id=p.id,
                user_id=p.workspace_member.player_id,
                team_id=p.team_id,
                role=roles.get(p.id) or p.role,
                rank=p.rank,
            )
            for p in players_map.values()
        }
        baselines = await baselines_service.get_active(session)
        impact_ctx = impact.ImpactContext(players=player_refs, baselines=baselines, has_killfeed=has_killfeed)

        all_stat_objects.extend(self._calculate_and_add_derived_stats(match, hero_derived_df, is_mvp_calc=False))
        all_stat_objects.extend(
            self._calculate_and_add_derived_stats(match, round_derived_df, is_mvp_calc=True, impact_ctx=impact_ctx)
        )
        all_stat_objects.extend(self._calculate_and_add_derived_stats(match, match_hero_derived_df, is_mvp_calc=False))
        all_stat_objects.extend(
            self._calculate_and_add_derived_stats(match, match_derived_df, is_mvp_calc=True, impact_ctx=impact_ctx)
        )

        return all_stat_objects

    async def start(self, session: AsyncSession, is_raise: bool = True) -> models.Match | None:
        logger.info(f"Processing match log {self.filename} in tournament {self.tournament.name}")
        if self.df.empty:
            logger.error(f"Match log {self.filename} is empty or unparseable. Aborting.")
            if is_raise:
                raise errors.ApiHTTPException(
                    status_code=400,
                    detail=[errors.ApiExc(code="match_log_empty", msg="Match log is empty or unparseable.")],
                )
            return None

        if not await self.validate(is_raise=is_raise):
            return None
        await self._preload_data(session)
        (home_team_tuple, away_team_tuple) = await self.process_teams(session)
        home_team_db, home_players_map = home_team_tuple
        away_team_db, away_players_map = away_team_tuple

        players_map = {**home_players_map, **away_players_map}

        match_map_model = await self.get_map(session)
        logger.info(
            f"Match map: {match_map_model.name} in match log {self.filename} in tournament {self.tournament.name}"
        )
        match_time, home_score, away_score = self.get_match_score_and_time()
        logger.info(f"Match time: {match_time}, home score: {home_score}, away score: {away_score}")

        encounter = await encounter_flows.get_by_teams_ids(session, home_team_db.id, away_team_db.id, [])
        match_model = await encounter_service.get_match_by_encounter_and_map(
            session, encounter.id, match_map_model.id, []
        )

        if not match_model:
            match_model = await encounter_service.create_match(
                session,
                encounter,
                time=match_time,
                log_name=self.filename,
                map=match_map_model,
                home_team_id=home_team_db.id,
                away_team_id=away_team_db.id,
                home_score=home_score,
                away_score=away_score,
                log_record_id=self.log_record_id,
            )
            logger.info(
                f"Match created [id={match_model.id}] in match log {self.filename} in tournament {self.tournament.name}"
            )
        else:
            match_model.time = match_time
            match_model.home_score = home_score
            match_model.away_score = away_score
            match_model.map_id = match_map_model.id
            match_model.home_team_id = home_team_db.id
            match_model.away_team_id = away_team_db.id
            match_model.log_name = self.filename
            # A genuine log just superseded this row (most often a
            # pre-existing ``source=captain_report`` row upserted by
            # ``map_report.submit_map_report`` before the log arrived) — stamp
            # it ``log_parser`` so both the row's own provenance and the
            # derived ``Encounter.has_logs`` (filtered on this column, see
            # ``shared/models/matches/match.py``) reflect that a real log now
            # backs it.
            match_model.source = enums.MatchSource.LOG_PARSER
            if self.log_record_id is not None:
                match_model.log_record_id = self.log_record_id
            await _match_repo.create(session, match_model)
            logger.info(f"Match updated [id={match_model.id}] for log {self.filename}")

        logger.info(f"Clearing existing stats/events/kills for match {match_model.id}")
        await _stats_repo.delete_for_match(session, match_model.id)
        await _events_repo.delete_for_match(session, match_model.id)
        await _kill_feed_repo.delete_for_match(session, match_model.id)

        logger.info(f"Processing kills for match {match_model.id}")
        kill_feed_db_objects = await self.process_kills(match_model, players_map)

        logger.info(f"Processing events for match {match_model.id}")
        events = await self.process_events(session, match_model, players_map)

        logger.info(f"Processing stats for match {match_model.id}")
        stats = await self.create_stats(session, match_model, players_map, kill_feed=kill_feed_db_objects)

        # Own transaction, and before the commit below, so the queue records the
        # gaps whether this log ends up committed or rolled back.
        if self.hero_misses:
            await catalog_aliases.record_misses(
                enums.CatalogEntityType.hero, self.hero_misses, log_record_id=self.log_record_id
            )

        try:
            await _bulk_insert(session, models.MatchKillFeed, [_kill_feed_row(k) for k in kill_feed_db_objects])
            await _bulk_insert(session, models.MatchEvent, [_match_event_row(e) for e in events])
            await _bulk_insert(
                session,
                models.MatchStatistics,
                [
                    {
                        "match_id": s.match_id,
                        "round": s.round,
                        "team_id": s.team_id,
                        "user_id": s.user_id,
                        "hero_id": s.hero_id,
                        "name": s.name,
                        "value": s.value,
                    }
                    for s in stats
                ],
            )
            await _enqueue_match_log_tournament_events(session, encounter)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        logger.info(f"Match log {self.filename} (match_id={match_model.id}) processed successfully")
        return match_model

    async def add_substitution(
        self,
        session: AsyncSession,
        team: models.Team,
        player_to_be_replaced: models.Player,
        sub_user: models.User,
    ) -> models.Player:
        logger.info(
            f"Adding substitution: user {sub_user.name} for player {player_to_be_replaced.name} in team {team.name}"
        )

        existing_player_profile_for_user = await team_service.get_player_by_user_and_role(
            session, sub_user.id, player_to_be_replaced.role, []
        )

        player_data_source = None
        if existing_player_profile_for_user:
            player_data_source = sorted(
                existing_player_profile_for_user, key=lambda p: p.tournament_id or 0, reverse=True
            )[0]

        history = await load_prior_participation(session, tournament=self.tournament, user_ids=[sub_user.id])
        new_player = await team_service.create_player(
            session,
            name=sub_user.name,
            sub_role=player_data_source.sub_role if player_data_source else None,
            rank=player_data_source.rank if player_data_source else player_to_be_replaced.rank,
            role=player_to_be_replaced.role,
            user=sub_user,
            tournament=self.tournament,
            team=team,
            is_substitution=True,
            related_player_id=player_to_be_replaced.id,
            is_newcomer=history.is_newcomer(sub_user.id),
            is_newcomer_role=history.is_newcomer_role(sub_user.id, player_to_be_replaced.role),
        )
        # create_player() sets workspace_member_id (a plain FK column) but does not
        # eagerly load the `workspace_member` relationship; readers downstream (this
        # module) access `.workspace_member.player_id` in place of the retained
        # `.user_id`, so it must be loaded before new_player leaves this method.
        await session.refresh(new_player, attribute_names=["workspace_member"])
        logger.info(f"Created substitution player: {new_player.name} (ID: {new_player.id})")
        return new_player

    async def fix_team_players_collision(
        self,
        session: AsyncSession,
        team_db: models.Team,
        players_found_in_roster_map: dict[str, models.Player],
        all_players_from_log_for_team: list[tuple[str, models.User | None]],
    ) -> tuple[models.Team, dict[str, models.Player]]:
        final_players_map = players_found_in_roster_map.copy()
        users_who_played_map: dict[str, models.User] = {
            log_name: user for log_name, user in all_players_from_log_for_team if user
        }
        roster_players_not_substituted = [p for p in team_db.players if not p.is_substitution]
        expected_roster_size = len(roster_players_not_substituted)

        if (
            len(users_who_played_map) > len(players_found_in_roster_map)
            and len(players_found_in_roster_map) < expected_roster_size
        ):
            logger.warning(
                f"Potential substitution for team {team_db.name}. "
                f"Log has {len(users_who_played_map)} users, roster matched {len(players_found_in_roster_map)}."
            )

            roster_player_user_ids_found_in_log = {
                p.workspace_member.player_id for p in players_found_in_roster_map.values()
            }
            missing_roster_player: models.Player | None = None
            for rp in roster_players_not_substituted:
                if rp.workspace_member.player_id not in roster_player_user_ids_found_in_log:
                    missing_roster_player = rp
                    break

            substitute_user: models.User | None = None
            substitute_log_name: str | None = None
            for log_name, user_model in users_who_played_map.items():
                if user_model.id not in roster_player_user_ids_found_in_log:
                    substitute_user = user_model
                    substitute_log_name = log_name
                    break

            if missing_roster_player and substitute_user and substitute_log_name:
                logger.info(
                    f"Identified substitution: {substitute_user.name} "
                    f"(log: {substitute_log_name}) for {missing_roster_player.name} in team {team_db.name}."
                )
                existing_sub_player = await team_service.get_player_by_team_and_user(
                    session, team_db.id, substitute_user.id, ["workspace_member"]
                )
                if (
                    existing_sub_player
                    and existing_sub_player.is_substitution
                    and existing_sub_player.related_player_id == missing_roster_player.id
                ):
                    logger.info(f"Existing substitution player record found for {substitute_user.name}.")
                    final_players_map[substitute_log_name] = existing_sub_player
                else:
                    new_sub_player = await self.add_substitution(
                        session, team_db, missing_roster_player, substitute_user
                    )
                    final_players_map[substitute_log_name] = new_sub_player
                    await session.refresh(team_db)
            else:
                logger.warning(f"Could not fully resolve substitution for team {team_db.name}.")

        unmatched_log_names: list[str] = [
            log_name
            for log_name, user in all_players_from_log_for_team
            if not user and log_name not in final_players_map
        ]

        if len(final_players_map) < expected_roster_size and len(unmatched_log_names) > 0:
            logger.warning(
                f"Potential battle_name change for team {team_db.name}. "
                f"Matched {len(final_players_map)}, expected {expected_roster_size}, "
                f"unmatched log names: {unmatched_log_names}."
            )

            roster_players_in_log_user_ids = {p.workspace_member.player_id for p in final_players_map.values()}
            missing_roster_players_from_log = [
                rp
                for rp in roster_players_not_substituted
                if rp.workspace_member.player_id not in roster_players_in_log_user_ids
            ]

            if len(missing_roster_players_from_log) == 1 and len(unmatched_log_names) == 1:
                player_who_changed_name = missing_roster_players_from_log[0]
                new_battle_name_from_log = unmatched_log_names[0]
                logger.info(
                    f"Player {player_who_changed_name.name} "
                    f"(User ID: {player_who_changed_name.workspace_member.player_id}) "
                    f"likely changed battle_name to '{new_battle_name_from_log}'."
                )

                user_to_update = player_who_changed_name.workspace_member.player or await _user_repo.get(
                    session, player_who_changed_name.workspace_member.player_id
                )

                if user_to_update:
                    await social_identity.upsert_social_account(
                        session,
                        user_id=user_to_update.id,
                        provider=SocialProvider.BATTLENET,
                        username=f"{new_battle_name_from_log}#0000",
                    )
                    await session.commit()
                    logger.info(
                        f"Associated new battle_name '{new_battle_name_from_log}' with User ID {user_to_update.id}."
                    )
                    final_players_map[new_battle_name_from_log] = player_who_changed_name
                else:
                    logger.error(
                        f"Could not find user for player {player_who_changed_name.name} to update battle_name."
                    )
            else:
                logger.warning(
                    f"Ambiguous situation for battle_name change in team {team_db.name}. "
                    f"Could not resolve automatically."
                )

        current_team_player_ids = {p.id for p in team_db.players}
        final_players_map_verified = {
            name: p
            for name, p in final_players_map.items()
            if p.team_id == team_db.id and p.id in current_team_player_ids
        }
        if len(final_players_map_verified) != len(final_players_map):
            logger.warning(
                f"Team {team_db.name} player map verification failed after collision fix. "
                f"Some players might not belong to the team."
            )

        return team_db, final_players_map_verified

    async def process_teams(
        self, session: AsyncSession
    ) -> tuple[
        tuple[models.Team, dict[str, models.Player]],
        tuple[models.Team, dict[str, models.Player]],
    ]:
        (home_team_tuple, away_team_tuple) = await self.find_teams_by_players(session)
        home_team_db, home_players_from_log_tuples = home_team_tuple
        away_team_db, away_players_from_log_tuples = away_team_tuple

        home_roster_players_map_initial: dict[str, models.Player] = {
            log_name: player_obj
            for log_name, player_obj in await self.get_players_by_team_and_battle_name(
                session, home_team_db, home_players_from_log_tuples
            )
            if player_obj
        }

        away_roster_players_map_initial: dict[str, models.Player] = {
            log_name: player_obj
            for log_name, player_obj in await self.get_players_by_team_and_battle_name(
                session, away_team_db, away_players_from_log_tuples
            )
            if player_obj
        }

        home_team_db_final, home_final_player_map = await self.fix_team_players_collision(
            session, home_team_db, home_roster_players_map_initial, home_players_from_log_tuples
        )

        away_team_db_final, away_final_player_map = await self.fix_team_players_collision(
            session, away_team_db, away_roster_players_map_initial, away_players_from_log_tuples
        )

        return (home_team_db_final, home_final_player_map), (away_team_db_final, away_final_player_map)


async def process_match_log(
    session: AsyncSession, tournament_id: int, filename: str, s3: S3Client, *, is_raise: bool = True
) -> None:
    from src.services.match_logs import log_records as record_service

    # LogProcessingRecord.filename is always a bare object name — uploads.py
    # rejects "/" outright — but the bulk path feeds us the full S3 key
    # ("logs/{tournament_id}/{name}") straight from list_objects. Matching
    # records on the prefixed form found nothing, forked a duplicate "manual"
    # row and left the uploaded one on `pending` ("Queued") forever, so key
    # every record lookup on the bare name.
    object_name = filename.rsplit("/", 1)[-1]
    logger.info(f"Fetching logs from S3 for tournament {tournament_id} and file {filename}")

    raw_bytes = await binary_match_logs.get_log_by_filename(s3, tournament_id, filename)
    if not raw_bytes:
        msg = f"Log file {filename} not found or empty in S3"
        # WARNING, not ERROR: a missing/empty object is a state of the uploaded
        # data, not a service defect — and it is already reported three other
        # ways (the terminal `failed` record below, the 404 raised to the caller,
        # and the `failed` result published to the bot). As an ERROR it opened a
        # second Sentry group for every occurrence that the raise below already
        # reported, so one missing file cost two issues and 300+ events.
        logger.warning(msg)
        # Terminal, not silent: this fires before set_processing, so without it
        # the row stays `pending` and the stall reaper requeues it forever.
        await record_service.fail_unstarted(session, tournament_id, object_name, msg)
        if is_raise:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="log_not_found", msg=msg)],
            )
        return

    max_log_bytes = settings.max_match_log_bytes
    oversize = match_log_oversize_message(len(raw_bytes), max_log_bytes, filename=filename)
    if oversize:
        logger.warning(oversize)
        await record_service.fail_unstarted(session, tournament_id, object_name, oversize)
        if is_raise:
            raise errors.ApiHTTPException(
                status_code=413,
                detail=[errors.ApiExc(code="match_log_too_large", msg=oversize)],
            )
        return

    content_hash = await asyncio.to_thread(record_service.compute_content_hash, raw_bytes)

    if await record_service.is_already_processed(session, tournament_id, object_name, content_hash):
        logger.info(
            f"Log {object_name} (tournament {tournament_id}) already processed with hash {content_hash[:8]}…, skipping."
        )
        await record_service.finish_duplicate_record(session, tournament_id, object_name, content_hash)
        return

    record = await record_service.set_processing(session, tournament_id, object_name, content_hash=content_hash)
    tournament = await tournament_flows.get(session, tournament_id, [])

    processor = await asyncio.to_thread(
        _processor_from_bytes,
        tournament,
        object_name,
        raw_bytes,
        s3,
        record.id if record is not None else None,
    )
    # The signal is staged, not published: ``set_done``/``set_failed`` own the
    # commit that carries it, so a state write that fails announces nothing.
    try:
        await processor.start(session, is_raise=is_raise)
        if record is not None:
            await emit_logs_updated(session, tournament.workspace_id, change="done")
            await record_service.set_done(session, record)
    except Exception as e:
        logger.exception(e)
        if record is not None:
            await emit_logs_updated(session, tournament.workspace_id, change="failed")
            await record_service.set_failed(session, record, str(e))
        if is_raise:
            raise e
