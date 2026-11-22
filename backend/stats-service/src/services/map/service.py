import typing
from dataclasses import replace

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import pagination
from shared.repository.stats_reads import duel_matches
from shared.services.cache_generations import versioned
from shared.services.user_cache import user_generations
from src import schemas
from src.core import config
from src.services.encounter_seats import teamless_seat_ids
from src.services.hero.queries import HeroQueries
from src.services.hero.service import heroes as hero_service
from src.services.user.service import users as user_service

__all__ = ("MapService", "maps")


class MapService:
    """One game's per-user map statistics (the map catalog itself is the native catalog read)."""

    @staticmethod
    def to_read(game_map: models.CatalogEntity, entities: list[str]) -> schemas.CatalogEntityRead:
        """The catalog entity of a map; its mode is ``parent`` (loaded by the caller when requested)."""
        return schemas.CatalogEntityRead.from_entity(game_map, with_parent="parent" in entities)

    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.users_cache_ttl,
        key=(
            "backend:user_maps:v2:{id}:{discipline}:{workspace_id}:{params.page}:{params.per_page}:{params.sort}:"
            "{params.order}:{params.query}:{params.fields}:{params.min_count}:"
            "{params.mode_id}:{params.tournament_id}:{params.entities}"
        ),
        lock=True,
    )
    async def get_top_user(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserMapsSearchParams,
        *,
        discipline: str,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.UserMap]:
        """Paginated top maps of ``discipline`` for a user, with per-map statistics.

        ``workspace_id`` scopes the stats to a single workspace; ``None`` spans all of them.
        """
        user = await user_service.get(session, id, [])
        maps, total = await self.get_top_maps(
            session, user.id, params, discipline=discipline, workspace_id=workspace_id
        )
        queries = HeroQueries.of(discipline)
        results: list[schemas.UserMap] = []

        for map_, count, win, loss, draw, win_rate in maps:
            results.append(
                schemas.UserMap(
                    map=self.to_read(map_, params.entities),
                    count=count,
                    win=win,
                    loss=loss,
                    draw=draw,
                    win_rate=win_rate,
                    characters=[],
                )
            )

        if "characters" in params.entities:
            maps_ids = [result.map.id for result in results]
            characters_data = await queries.get_heroes_playtime_by_maps(
                session, maps_ids, user.id, tournament_id=params.tournament_id, workspace_id=workspace_id
            )
            characters_per_map: dict[int, list[schemas.CharacterPlaytime]] = {map_id: [] for map_id in maps_ids}
            for character, map_id, playtime in characters_data:
                characters_per_map[map_id].append(
                    schemas.CharacterPlaytime(entity=hero_service.to_read(character), playtime=playtime)
                )

            for result in results:
                result.characters = characters_per_map[result.map.id][:5]

        if "character_stats" in params.entities:
            maps_ids = [result.map.id for result in results]
            character_rows = await queries.get_user_hero_stats_by_maps(
                session,
                maps_ids,
                user.id,
                limit_per_map=5,
                tournament_id=params.tournament_id,
                workspace_id=workspace_id,
            )
            stats_per_map: dict[int, list[schemas.UserMapCharacterStats]] = {map_id: [] for map_id in maps_ids}
            for character, map_id, games, win, loss, draw, win_rate, playtime_seconds, playtime_share in character_rows:
                stats_per_map[map_id].append(
                    schemas.UserMapCharacterStats(
                        character=hero_service.to_read(character),
                        games=games,
                        win=win,
                        loss=loss,
                        draw=draw,
                        win_rate=win_rate,
                        playtime_seconds=playtime_seconds,
                        playtime_share_on_map=playtime_share,
                    )
                )

            for result in results:
                result.character_stats = stats_per_map.get(result.map.id, [])

        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=results,
        )

    async def get_top_user_summary(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserMapsSearchParams,
        *,
        discipline: str,
        workspace_id: int | None = None,
    ) -> schemas.UserMapsSummary:
        """Build a summary for the user's map performance in ``discipline``.

        The summary is computed for the full filtered dataset (not just one page).
        To keep it cheap, this endpoint ignores heavy entities like character stats.
        """

        user = await user_service.get(session, id, [])

        safe_entities = [e for e in params.entities if e in {"parent"}]
        all_params = replace(
            params,
            page=1,
            per_page=-1,
            sort="count",
            order="desc",
            entities=safe_entities,
        )

        rows, total = await self.get_top_maps(
            session, user.id, all_params, discipline=discipline, workspace_id=workspace_id
        )

        if not rows:
            return schemas.UserMapsSummary(
                overall=schemas.UserMapsOverall(
                    total_maps=0,
                    total_games=0,
                    win=0,
                    loss=0,
                    draw=0,
                    win_rate=0,
                ),
                most_played=None,
                best=None,
                worst=None,
            )

        total_games = 0
        total_win = 0
        total_loss = 0
        total_draw = 0

        highlights: list[schemas.UserMapHighlight] = []
        for map_, count, win, loss, draw, win_rate in rows:
            count_i = int(count)
            win_i = int(win)
            loss_i = int(loss)
            draw_i = int(draw)
            win_rate_f = float(win_rate)

            total_games += count_i
            total_win += win_i
            total_loss += loss_i
            total_draw += draw_i

            highlights.append(
                schemas.UserMapHighlight(
                    map=self.to_read(map_, all_params.entities),
                    count=count_i,
                    win=win_i,
                    loss=loss_i,
                    draw=draw_i,
                    win_rate=win_rate_f,
                )
            )

        overall_winrate = (total_win / total_games) if total_games else 0

        most_played = max(highlights, key=lambda item: (item.count, item.map.id))
        best = max(highlights, key=lambda item: (item.win_rate, item.count, item.map.id))
        worst = min(highlights, key=lambda item: (item.win_rate, -item.count, item.map.id))

        return schemas.UserMapsSummary(
            overall=schemas.UserMapsOverall(
                total_maps=total,
                total_games=total_games,
                win=total_win,
                loss=total_loss,
                draw=total_draw,
                win_rate=overall_winrate,
            ),
            most_played=most_played,
            best=best,
            worst=worst,
        )

    async def get_top_maps(
        self,
        session: AsyncSession,
        user_id: int,
        params: schemas.UserMapsSearchParams,
        *,
        discipline: str,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[tuple[models.CatalogEntity, int, int, int, int, float]], int]:
        """Paginated top maps of ``discipline`` for a user as ``(map, matches, wins, losses, draws, win_rate)``
        rows plus the total map count.

        ``workspace_id`` scopes the stats to a single workspace; ``None`` spans all of them.
        """
        # The user's match ids, found from their own teams' seats and their team-less ones (an individual Swiss
        # lobby): a superset of the duel rows kept below, so the duel participant aggregate and its score lookups run
        # for those matches, not every match of the game.
        user_match_ids = sa.union(
            sa.select(models.StatsMatchTeam.match_id)
            .join(
                models.EncounterTeam,
                sa.and_(
                    models.EncounterTeam.id == models.StatsMatchTeam.encounter_team_id,
                    models.EncounterTeam.encounter_id == models.StatsMatchTeam.encounter_id,
                ),
            )
            .join(models.Player, models.Player.team_id == models.EncounterTeam.team_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(models.WorkspaceMember.player_id == user_id, models.Player.is_substitution.is_(False)),
            sa.select(models.StatsMatchTeam.match_id).where(
                models.StatsMatchTeam.encounter_team_id.in_(teamless_seat_ids(user_id))
            ),
        )
        matches = duel_matches(discipline=discipline, match_ids=sa.select(user_match_ids.subquery()))
        match_columns = (
            matches.c.id.label("match_id"),
            matches.c.map_entity_id.label("map_id"),
            matches.c.mode_entity_id.label("mode_id"),
            matches.c.encounter_id,
            matches.c.home_score,
            matches.c.away_score,
        )
        # DISTINCT (UNION) avoids fan-out when a roster has multiple rows for one player.
        team_sides = (
            sa.select(*match_columns, (models.Team.id == matches.c.home_tournament_team_id).label("user_is_home"))
            .select_from(matches)
            .join(
                models.Team,
                sa.or_(
                    models.Team.id == matches.c.home_tournament_team_id,
                    models.Team.id == matches.c.away_tournament_team_id,
                ),
            )
            .join(models.Player, models.Player.team_id == models.Team.id)
            .join(
                models.WorkspaceMember,
                sa.and_(
                    models.WorkspaceMember.id == models.Player.workspace_member_id,
                    models.WorkspaceMember.workspace_id == matches.c.workspace_id,
                ),
            )
            .where(
                models.WorkspaceMember.player_id == user_id,
                models.Player.is_substitution.is_(False),
            )
        )
        teamless = teamless_seat_ids(user_id).subquery("user_teamless_seats")
        teamless_sides = (
            sa.select(
                *match_columns,
                (teamless.c.encounter_team_id == matches.c.home_encounter_team_id).label("user_is_home"),
            )
            .select_from(matches)
            .join(
                teamless,
                sa.or_(
                    teamless.c.encounter_team_id == matches.c.home_encounter_team_id,
                    teamless.c.encounter_team_id == matches.c.away_encounter_team_id,
                ),
            )
        )
        user_match_teams = sa.union(team_sides, teamless_sides).cte("user_match_teams")

        user_home_score = sa.case(
            (user_match_teams.c.user_is_home, user_match_teams.c.home_score),
            else_=user_match_teams.c.away_score,
        )
        user_away_score = sa.case(
            (user_match_teams.c.user_is_home, user_match_teams.c.away_score),
            else_=user_match_teams.c.home_score,
        )
        user_win = sa.case((user_home_score > user_away_score, 1), else_=0)
        user_loss = sa.case((user_home_score < user_away_score, 1), else_=0)
        user_draw = sa.case((user_home_score == user_away_score, 1), else_=0)

        subquery_query = (
            sa.select(
                models.CatalogEntity.id.label("map_id"),
                sa.func.count(user_match_teams.c.match_id).label("count"),
                sa.func.sum(user_win).label("win"),
                sa.func.sum(user_loss).label("loss"),
                sa.func.sum(user_draw).label("draw"),
                (sa.func.sum(user_win) / sa.func.count(user_match_teams.c.match_id))
                .cast(sa.Numeric(10, 2))
                .label("winrate"),
            )
            .select_from(user_match_teams)
            .join(models.CatalogEntity, models.CatalogEntity.id == user_match_teams.c.map_id)
            .where(models.CatalogEntity.kind == "map", models.CatalogEntity.discipline == discipline)
            .group_by(models.CatalogEntity.id)
        )

        if params.tournament_id or workspace_id:
            subquery_query = subquery_query.join(
                models.Encounter, models.Encounter.id == user_match_teams.c.encounter_id
            )

            if params.tournament_id:
                subquery_query = subquery_query.where(models.Encounter.tournament_id == params.tournament_id)

            if workspace_id:
                subquery_query = subquery_query.join(
                    models.Tournament, models.Tournament.id == models.Encounter.tournament_id
                ).where(models.Tournament.workspace_id == workspace_id)

        if params.mode_id:
            # The match's own mode, not the map's catalog parent: one map can be played in several modes.
            subquery_query = subquery_query.where(user_match_teams.c.mode_id == params.mode_id)

        if params.query:
            fields = params.fields if params.fields else ["name"]
            subquery_query = pagination.apply_search(models.CatalogEntity, subquery_query, params.query, fields)

        if params.min_count:
            subquery_query = subquery_query.having(sa.func.count(user_match_teams.c.match_id) >= params.min_count)

        subquery = subquery_query.subquery("user_map_stats")

        total_query = sa.select(sa.func.count()).select_from(subquery)

        query = sa.select(
            models.CatalogEntity,
            subquery.c.count,
            subquery.c.win,
            subquery.c.loss,
            subquery.c.draw,
            subquery.c.winrate,
        ).join(subquery, subquery.c.map_id == models.CatalogEntity.id)
        if "parent" in params.entities:
            query = query.options(selectinload(models.CatalogEntity.parent))

        sort_params = replace(params, sort="parent_id") if params.sort == "mode_id" else params
        query = sort_params.apply_sort(query)
        if params.sort == "winrate":
            query = query.order_by(subquery.c.count.desc())
        query = query.order_by(models.CatalogEntity.id.asc())
        query = params.apply_pagination(query)

        rows = (await session.execute(query)).all()
        # Unpaginated (a map catalog never reaches the 10k cap): the rows are the total; skip re-running it as a COUNT.
        if params.per_page == -1 and not params.only_count:
            return rows, len(rows)  # type: ignore
        result_total = await session.execute(total_query)
        return rows, result_total.scalar_one()  # type: ignore


maps = MapService()
