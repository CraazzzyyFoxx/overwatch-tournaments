from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import ApiExc, ApiHTTPException
from shared.disciplines import discipline as discipline_spec
from shared.division_grid import DivisionGrid
from shared.repository import CatalogEntityRepository
from shared.schemas.catalog import CatalogEntityRead
from shared.schemas.role import RoleRef
from shared.services.division_grid.access import load_division_grid_version_read_payloads
from shared.services.person_display import load_person_displays
from src import schemas

from .queries import HeroQueries

__all__ = ("HeroService", "heroes")


class HeroService:
    """One discipline's character statistics: playtime shares and the per-character leaderboard."""

    @staticmethod
    def to_read(hero: models.CatalogEntity) -> CatalogEntityRead:
        """A character row as the catalog's entity DTO (a character has no parent to load)."""
        return CatalogEntityRead.from_entity(hero, with_parent=False)

    async def get_hero_leaderboard(
        self,
        session: AsyncSession,
        *,
        discipline: str,
        entity_id: int,
        params: schemas.CharacterLeaderboardParams,
        workspace_id: int | None = None,
        grid: DivisionGrid | None,
    ) -> schemas.CharacterLeaderboardResponse:
        """The ranking of one character of ``discipline``; an id of another game or kind is a 404, never an empty board."""
        entity = await CatalogEntityRepository("character", discipline=discipline).get(session, entity_id)
        if entity is None:
            raise ApiHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="not_found", msg=f"No character {entity_id} in discipline {discipline!r}")],
            )
        rows, total = await HeroQueries.of(discipline).get_hero_leaderboard(
            session,
            hero_id=entity_id,
            tournament_id=params.tournament_id,
            stat=params.stat,
            params=pagination.PaginationParams(page=params.page, per_page=params.per_page),
            workspace_id=workspace_id,
            grid=grid,
        )
        displays = await load_person_displays(
            session,
            {row.user_id for row in rows},
            discipline=discipline,
            workspace_id=workspace_id,
            snapshots={row.user_id: row.player_name for row in rows},
        )
        # Every grid the page's divisions are numbers on, once each (cached reads, one query for the misses); none in
        # the all-workspaces read, whose divisions are on the in-code native ladder.
        grid_payloads = await load_division_grid_version_read_payloads(
            session,
            {row.division_grid_version_id for row in rows if row.division_grid_version_id is not None},
        )
        return schemas.CharacterLeaderboardResponse(
            page=params.page,
            per_page=params.per_page,
            total=total,
            division_grids=[
                schemas.DivisionGridVersionRead.model_validate(grid_payloads[version_id])
                for version_id in sorted(grid_payloads)
            ],
            results=[
                schemas.CharacterLeaderboardEntry(
                    rank=row.rank,
                    user_id=row.user_id,
                    display=displays[row.user_id],
                    role=RoleRef.of(discipline_spec(row.discipline).rated_dimension.code, row.role, row.sub_role),
                    div=row.div,
                    division_grid_version_id=row.division_grid_version_id,
                    team=row.team,
                    team_id=row.team_id,
                    games_played=int(row.games_played),
                    playtime_seconds=float(row.playtime_seconds),
                    per10_eliminations=float(row.per10_eliminations),
                    per10_healing=float(row.per10_healing),
                    per10_deaths=float(row.per10_deaths),
                    per10_damage=float(row.per10_damage),
                    per10_final_blows=float(row.per10_final_blows),
                    per10_damage_blocked=float(row.per10_damage_blocked),
                    per10_solo_kills=float(row.per10_solo_kills),
                    per10_obj_kills=float(row.per10_obj_kills),
                    per10_defensive_assists=float(row.per10_defensive_assists),
                    per10_offensive_assists=float(row.per10_offensive_assists),
                    per10_all_damage=float(row.per10_all_damage),
                    per10_damage_taken=float(row.per10_damage_taken),
                    per10_self_healing=float(row.per10_self_healing),
                    per10_ultimates_used=float(row.per10_ultimates_used),
                    per10_multikills=float(row.per10_multikills),
                    per10_env_kills=float(row.per10_env_kills),
                    per10_crit_hits=float(row.per10_crit_hits),
                    avg_weapon_accuracy=float(row.avg_weapon_accuracy),
                    avg_crit_accuracy=float(row.avg_crit_accuracy),
                    kd=float(row.kd),
                    kda=float(row.kda),
                )
                for row in rows
            ],
        )

    async def get_playtime(
        self,
        session: AsyncSession,
        params: schemas.CharacterPlaytimePaginationParams,
        *,
        discipline: str,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.CharacterPlaytime]:
        """One game's character playtime shares — delegates to `CatalogEntityRepository.playtime`."""
        user_id: int | None = None if params.user_id == "all" else params.user_id
        characters = await CatalogEntityRepository("character", discipline=discipline).playtime(
            session,
            user_id=user_id,
            tournament_id=params.tournament_id,
            workspace_id=workspace_id,
        )
        characters = sorted(characters, key=lambda row: float(row[1]), reverse=True)
        total = len(characters)
        paginated = params.paginate_data(characters)
        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=[
                schemas.CharacterPlaytime(
                    entity=self.to_read(character),
                    playtime=round(float(playtime), 4),
                )
                for character, playtime in paginated
            ],
        )


heroes = HeroService()
