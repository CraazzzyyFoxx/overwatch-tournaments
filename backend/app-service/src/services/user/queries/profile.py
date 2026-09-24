"""Profile / dossier read queries for one user."""

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.social import SocialProvider, normalize_social_handle
from shared.division_grid import DivisionGrid, division_case_expr
from shared.models import mv_hero_global_stats
from src import models
from src.core import enums, pagination

from ._scope import (
    _build_eligible_hero_stats_cte,
    _hero_direction_score,
    _team_load_options,
    team_has_played_encounter,
    union_encounter_team_sides,
    user_entities,
)


class UserProfileQueries:
    """Single-user reads: identity lookups, tournaments, roles and hero statistics."""

    async def get(self, session: AsyncSession, user_id: int, entities: list[str]) -> models.User | None:
        """A user by ID, with the related entities named in ``entities`` eager-loaded."""
        query = sa.select(models.User).options(*user_entities(entities)).where(sa.and_(models.User.id == user_id))
        result = await session.execute(query)
        return result.unique().scalar_one_or_none()

    async def get_all(
        self, session: AsyncSession, params: pagination.PaginationSortSearchParams
    ) -> tuple[typing.Sequence[models.User], int]:
        """Paginated users matching ``params``, plus the total match count."""
        query = sa.select(models.User).options(*user_entities(params.entities))
        total_query = sa.select(sa.func.count(sa.distinct(models.User.id)))

        if params.query:
            query = params.apply_search(query, models.User)
            total_query = params.apply_search(total_query, models.User)

        query = params.apply_pagination_sort(query, models.User)

        result = await session.execute(query)
        result_total = await session.execute(total_query)
        return result.unique().scalars().all(), result_total.scalar_one()

    async def search_by_name(
        self, session: AsyncSession, query: str, fields: list[str]
    ) -> typing.Sequence[models.SocialAccount]:
        """Search battlenet ``social_account`` rows by handle (autocomplete).

        ``fields`` is accepted for API compatibility; search is always on the unified
        ``social_account.username`` (battlenet). Returns up to 10 matches ranked by
        exact / prefix / trigram similarity.
        """
        query = query.strip().replace("-", "#")
        if not query or len(query) < 2:
            return []

        column = models.SocialAccount.username
        like_query = f"{query}%" if len(query) < 3 else f"%{query}%"
        query_lower = query.lower()

        exact_score = sa.case((sa.func.lower(column) == query_lower, 0), else_=1)
        prefix_score = sa.case((sa.func.lower(column).like(f"{query_lower}%"), 0), else_=1)
        similarity_score = sa.func.word_similarity(column, query)

        conditions = [column.ilike(like_query)]
        if len(query) >= 3:
            conditions.append(column.op("%")(query))

        stmt = (
            sa.select(models.SocialAccount)
            .where(
                models.SocialAccount.provider == SocialProvider.BATTLENET,
                sa.or_(*conditions),
                # Accounts hidden from the public profile (no global visibility row)
                # must not surface in search either.
                sa.select(models.SocialAccountVisibility.id)
                .where(
                    models.SocialAccountVisibility.account_id == models.SocialAccount.id,
                    models.SocialAccountVisibility.workspace_id.is_(None),
                )
                .exists(),
            )
            .order_by(
                exact_score.asc(),
                prefix_score.asc(),
                similarity_score.desc(),
                column.asc(),
            )
            .limit(10)
        )
        result = await session.scalars(stmt)
        return result.unique().all()

    async def find_by_battle_tag(
        self, session: AsyncSession, battle_tag: str, entities: list[str]
    ) -> models.User | None:
        """A user by battle tag, with ``entities`` eager-loaded.

        Matches on the normalized handle (``-`` folded to ``#``) or on the in-game name
        part before ``#``, case-insensitively.
        """
        normalized_battle_tag = battle_tag.strip().replace("-", "#")
        if not normalized_battle_tag:
            return None

        battle_tag_lower = normalized_battle_tag.lower()
        exact_user_name_match = sa.func.lower(models.User.name) == battle_tag_lower
        # Battlenet identity now lives in players.social_account; match the full
        # normalized handle or the in-game name part (before ``#``), case-insensitive.
        bnet_name_part = sa.func.lower(sa.func.split_part(models.SocialAccount.username, "#", 1))

        query = (
            sa.select(models.User)
            .options(*user_entities(entities))
            .outerjoin(
                models.SocialAccount,
                sa.and_(
                    models.User.id == models.SocialAccount.user_id,
                    models.SocialAccount.provider == SocialProvider.BATTLENET,
                ),
            )
            .where(
                sa.or_(
                    exact_user_name_match,
                    models.SocialAccount.username_normalized
                    == normalize_social_handle(SocialProvider.BATTLENET, normalized_battle_tag),
                    bnet_name_part == battle_tag_lower,
                )
            )
            .order_by(
                sa.case((exact_user_name_match, 0), else_=1),
                models.User.id.asc(),
            )
            .limit(1)
        )
        result = await session.execute(query)
        return result.unique().scalar_one_or_none()

    async def get_by_discord(self, session: AsyncSession, discord: str, entities: list[str]) -> models.User | None:
        """A user by Discord handle, with ``entities`` eager-loaded."""
        query = (
            sa.select(models.User)
            .options(*user_entities(entities))
            .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
            .where(
                models.SocialAccount.provider == SocialProvider.DISCORD,
                models.SocialAccount.username_normalized == normalize_social_handle(SocialProvider.DISCORD, discord),
            )
        )
        result = await session.scalars(query)
        return result.unique().first()

    async def get_overall_statistics(
        self, session: AsyncSession, user_id: int, workspace_id: int | None = None
    ) -> tuple[int, int, int]:
        """A user's ``(maps won, maps lost, average encounter closeness)`` across all
        tournaments, or the workspace's tournaments when ``workspace_id`` is given.
        """

        def _side(team_fk, won, lost):
            q = (
                sa.select(
                    models.WorkspaceMember.player_id.label("user_id"),
                    won.label("maps_won"),
                    lost.label("maps_lost"),
                    models.Encounter.closeness.label("closeness"),
                )
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .where(
                    models.Player.is_substitution.is_(False),
                    models.WorkspaceMember.player_id == user_id,
                )
            )
            if workspace_id is not None:
                q = q.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id).where(
                    models.Tournament.workspace_id == workspace_id
                )
            return q

        sides = union_encounter_team_sides(_side).subquery("profile_map_sides")
        query = (
            sa.select(
                sa.func.sum(sides.c.maps_won).label("won_maps"),
                sa.func.sum(sides.c.maps_lost).label("lost_maps"),
                sa.func.avg(sides.c.closeness).label("closeness"),
            )
            .select_from(sides)
            .group_by(sides.c.user_id)
        )
        matches = await session.execute(query)
        return matches.first()

    async def get_teams(
        self,
        session: AsyncSession,
        user_id: int,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[models.Team], int]:
        """Paginated teams a user has played for, plus the total count.

        Scoped exactly like ``get_tournaments_with_stats`` (which powers the
        Tournaments tab): a tournament belongs to a user's history as soon as the
        user has played an encounter in it, not once ``is_finished`` flips. Gating on
        ``is_finished`` left the profile of a player whose only event is the live one
        completely empty even though every other read (maps, heroes, roles,
        encounters) already counted it. Hidden tournaments (issue #115) never appear.
        """
        played_encounter = team_has_played_encounter()
        scope = (
            models.WorkspaceMember.player_id == user_id,
            models.Player.is_substitution.is_(False),
            models.Tournament.is_hidden.is_(False),
            played_encounter,
        )

        total_query = (
            sa.select(sa.func.count(sa.distinct(models.Team.id)))
            .join(models.Player, models.Player.team_id == models.Team.id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(sa.and_(*scope))
        )

        query = (
            sa.select(models.Team)
            .options(*_team_load_options(params.entities))
            .join(models.Player, models.Player.team_id == models.Team.id)
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(sa.and_(*scope))
        )
        if workspace_id is not None:
            total_query = total_query.where(models.Tournament.workspace_id == workspace_id)
            query = query.where(models.Tournament.workspace_id == workspace_id)

        query = params.apply_pagination_sort(query, models.Team)
        result = await session.scalars(query)
        teams = result.unique().all()
        if params.per_page == -1:
            return teams, len(teams)
        result_total = await session.execute(total_query)
        return teams, result_total.scalar_one()

    async def get_roles(
        self, session: AsyncSession, user_id: int, workspace_id: int | None = None
    ) -> typing.Sequence[tuple[enums.HeroClass, int, int, list[dict]]]:
        """Per-role ``(role, maps won, maps lost, tournament entries)`` rows for a user.

        Each tournament entry is a dict of ``tournament``, ``rank`` and
        ``division_grid_version_id`` — the rank is raw, so the caller resolves the
        division against the grid version that tournament was played on.
        """

        def _side(team_fk, won, lost):
            q = (
                sa.select(
                    models.Player.role,
                    won.label("maps_won"),
                    lost.label("maps_lost"),
                    models.Team.tournament_id.label("tournament_id"),
                    models.Player.rank.label("rank"),
                    models.Tournament.division_grid_version_id.label("division_grid_version_id"),
                )
                .join(models.Team, models.Team.id == models.Player.team_id)
                .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .where(
                    models.Player.is_substitution.is_(False),
                    models.WorkspaceMember.player_id == user_id,
                )
            )
            if workspace_id is not None:
                q = q.where(models.Tournament.workspace_id == workspace_id)
            return q

        sides = union_encounter_team_sides(_side).subquery("profile_role_sides")
        query = (
            sa.select(
                sides.c.role,
                sa.func.sum(sides.c.maps_won).label("won_maps"),
                sa.func.sum(sides.c.maps_lost).label("lost_maps"),
                sa.func.jsonb_agg(
                    sa.func.jsonb_build_object(
                        "tournament",
                        sides.c.tournament_id,
                        "rank",
                        sides.c.rank,
                        "division_grid_version_id",
                        sides.c.division_grid_version_id,
                    )
                ),
            )
            .select_from(sides)
            .group_by(sides.c.role)
        )
        result = await session.execute(query)
        return result.all()  # type: ignore

    async def get_tournament_role(
        self, session: AsyncSession, tournament: models.Tournament, user_id: int, *, grid: DivisionGrid
    ) -> tuple[enums.HeroClass, int]:
        """A user's ``(role, division)`` in one tournament — the division already resolved
        against ``grid``, not the raw rank.
        """
        query = (
            sa.select(models.Player.role, division_case_expr(models.Player.rank, grid).label("div"))
            .select_from(models.Player)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(
                sa.and_(
                    models.Team.tournament_id == tournament.id,
                    models.WorkspaceMember.player_id == user_id,
                    models.Player.is_substitution.is_(False),
                )
            )
        )
        result_role = await session.execute(query)
        return result_role.one()  # type: ignore

    async def get_tournaments_with_stats(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.Team, int, int, int]]:
        """A user's tournament history as ``(team, maps won, maps lost, average encounter
        closeness)`` rows.
        """

        def _side(team_fk, won, lost):
            q = (
                sa.select(
                    models.Team.id.label("team_id"),
                    won.label("maps_won"),
                    lost.label("maps_lost"),
                    models.Encounter.closeness.label("closeness"),
                )
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .where(
                    models.WorkspaceMember.player_id == user_id,
                    models.Player.is_substitution.is_(False),
                    # Hidden tournaments (issue #115) never appear in a user's public
                    # tournament list. This read is cashews-cached without the viewer,
                    # so exclude unconditionally; admins/allowlisted view hidden
                    # tournaments through the gated tournament pages instead.
                    models.Tournament.is_hidden.is_(False),
                )
            )
            if workspace_id is not None:
                q = q.where(models.Tournament.workspace_id == workspace_id)
            return q

        sides = union_encounter_team_sides(_side).subquery("profile_tournament_sides")
        agg = (
            sa.select(
                sides.c.team_id,
                sa.func.sum(sides.c.maps_won).label("won_maps"),
                sa.func.sum(sides.c.maps_lost).label("lost_maps"),
                sa.func.avg(sides.c.closeness).label("closeness"),
            )
            .group_by(sides.c.team_id)
            .subquery("profile_tournament_stats")
        )
        query = (
            sa.select(
                models.Team,
                agg.c.won_maps,
                agg.c.lost_maps,
                agg.c.closeness,
            )
            .options(
                selectinload(models.Team.players).selectinload(models.Player.workspace_member),
                selectinload(models.Team.tournament).selectinload(models.Tournament.standings),
                selectinload(models.Team.tournament).selectinload(models.Tournament.division_grid_version),
                selectinload(models.Team.standings).selectinload(models.Standing.stage_item),
            )
            .join(agg, agg.c.team_id == models.Team.id)
        )

        result = await session.execute(query)
        return result.unique().all()

    async def get_tournament_stats_overall(
        self, session: AsyncSession, tournament: models.Tournament, user_id: int
    ) -> tuple[int, int, int, float]:
        """A user's totals for one tournament: ``(maps won, maps lost, average encounter
        closeness, total playtime in seconds)``.
        """

        def _playtime_side(team_fk, _won, _lost):
            return (
                sa.select(models.MatchStatistics.value.label("value"))
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(models.Match, models.Match.encounter_id == models.Encounter.id)
                .join(models.MatchStatistics, models.MatchStatistics.match_id == models.Match.id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .where(
                    models.WorkspaceMember.player_id == user_id,
                    models.Player.is_substitution.is_(False),
                    models.Team.tournament_id == tournament.id,
                    models.MatchStatistics.user_id == models.WorkspaceMember.player_id,
                    models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                    models.MatchStatistics.hero_id.is_(None),
                    models.MatchStatistics.round == 0,
                )
            )

        playtime_sides = union_encounter_team_sides(_playtime_side).subquery("profile_playtime_sides")
        playtime_subquery = sa.select(sa.func.sum(playtime_sides.c.value)).scalar_subquery()

        def _maps_side(team_fk, won, lost):
            return (
                sa.select(
                    won.label("maps_won"),
                    lost.label("maps_lost"),
                    models.Encounter.closeness.label("closeness"),
                )
                .select_from(models.Player)
                .join(models.Team, models.Team.id == models.Player.team_id)
                .join(models.Encounter, team_fk == models.Team.id)
                .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
                .where(
                    models.WorkspaceMember.player_id == user_id,
                    models.Player.is_substitution.is_(False),
                    models.Team.tournament_id == tournament.id,
                )
            )

        map_sides = union_encounter_team_sides(_maps_side).subquery("profile_tournament_map_sides")
        query = sa.select(
            sa.func.coalesce(sa.func.sum(map_sides.c.maps_won), 0).label("won_maps"),
            sa.func.coalesce(sa.func.sum(map_sides.c.maps_lost), 0).label("lost_maps"),
            sa.func.coalesce(sa.func.avg(map_sides.c.closeness), 0).label("closeness"),
            sa.func.coalesce(playtime_subquery, 0).label("playtime"),
        ).select_from(map_sides)
        result = await session.execute(query)
        row = result.one_or_none()
        if not row:
            return 0, 0, 0, 0

        won_maps, lost_maps, closeness, playtime = row
        return won_maps, lost_maps, closeness, playtime

    def _statistics_by_heroes_query(
        self,
        *,
        user_id: int,
        stats: list[enums.LogStatsName] | None,
        tournament_id: int | None,
        workspace_id: int | None,
    ) -> sa.Select:
        """Build the per-(hero, stat) totals + best-performance query for one user.

        Uses the deferred-metadata-join rewrite (same shape as the precomputed
        ``matches.mv_hero_global_stats`` view; see migration ``herostatmv01``): rank
        the slim eligible set with a bare window function, then join the four
        metadata tables (match/map/encounter/tournament) only for the
        ~(#heroes x #stats) winning rows. The previous form joined those tables
        *into* the window CTE, so ``row_number()`` ranked the full eligible set
        already fanned out across four tables — which blew past ``statement_timeout``
        for heavy users (e.g. an unfiltered workspace-wide read).
        """
        eligible_stats = _build_eligible_hero_stats_cte(
            user_id=user_id,
            stats=stats,
            cte_name="eligible_user_hero_stats",
            tournament_id=tournament_id,
            workspace_id=workspace_id,
        )
        direction_score = _hero_direction_score(eligible_stats.c.value, eligible_stats.c.name)

        # Totals per (hero, stat). Joins matches.match only for playtime (the
        # per-10min average denominator); no metadata tables, no window function.
        agg_cte = (
            sa.select(
                eligible_stats.c.hero_id,
                eligible_stats.c.name,
                sa.func.sum(eligible_stats.c.value).label("total_value"),
                sa.func.sum(models.Match.time).label("total_time"),
            )
            .select_from(eligible_stats)
            .join(models.Match, models.Match.id == eligible_stats.c.match_id)
            .group_by(eligible_stats.c.hero_id, eligible_stats.c.name)
            .cte("hero_stats_agg")
        )

        # Rank eligible rows per (hero, stat) on the slim set alone. The tiebreaker
        # is the match id, which equals ``eligible.match_id``, so no join is needed
        # here (the old form joined matches.match purely for ``match.id``).
        ranked_cte = (
            sa.select(
                eligible_stats.c.hero_id,
                eligible_stats.c.name,
                eligible_stats.c.match_id,
                eligible_stats.c.value,
                sa.func.row_number()
                .over(
                    partition_by=[
                        eligible_stats.c.hero_id,
                        eligible_stats.c.name,
                    ],
                    order_by=[direction_score.desc(), eligible_stats.c.match_id.desc()],
                )
                .label("row_num"),
            )
            .select_from(eligible_stats)
            .cte("hero_stats_ranked")
        )

        # Hydrate map/tournament metadata only for the winning row per (hero, stat).
        best_result_cte = (
            sa.select(
                ranked_cte.c.hero_id,
                ranked_cte.c.name,
                ranked_cte.c.value.label("best_value"),
                models.Match.encounter_id,
                models.Map.name.label("map_name"),
                models.Map.image_path.label("map_link"),
                models.Tournament.name.label("tournament_name"),
            )
            .select_from(ranked_cte)
            .join(models.Match, models.Match.id == ranked_cte.c.match_id)
            .join(models.Map, models.Map.id == models.Match.map_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(ranked_cte.c.row_num == 1)
            .cte("best_result_cte")
        )

        return (
            sa.select(
                agg_cte.c.name,
                models.Hero,
                agg_cte.c.total_value.label("total_value"),
                best_result_cte.c.best_value.label("best_value"),
                (agg_cte.c.total_value / sa.func.nullif(agg_cte.c.total_time, 0) * 600).label("avg_per_10min"),
                sa.func.jsonb_build_object(
                    "encounter_id",
                    best_result_cte.c.encounter_id,
                    "map_name",
                    best_result_cte.c.map_name,
                    "map_image_path",
                    best_result_cte.c.map_link,
                    "tournament_name",
                    best_result_cte.c.tournament_name,
                ).label("best_metadata"),
            )
            .select_from(agg_cte)
            .join(models.Hero, models.Hero.id == agg_cte.c.hero_id)
            .join(
                best_result_cte,
                sa.and_(
                    best_result_cte.c.hero_id == agg_cte.c.hero_id,
                    best_result_cte.c.name == agg_cte.c.name,
                ),
            )
        )

    async def get_statistics_by_heroes(
        self,
        session: AsyncSession,
        user_id: int,
        stats: list[enums.LogStatsName] | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[enums.LogStatsName, models.Hero, float, float, float, dict]]:
        """A user's hero statistics as ``(stat name, hero, total, best value, per-10-minute
        average, best-performance metadata)`` rows.

        The metadata dict carries the encounter id, map name, map image path and
        tournament name of the best result.
        """
        query = self._statistics_by_heroes_query(
            user_id=user_id,
            stats=stats,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
        )
        result = await session.execute(query)
        return result.all()

    def _read_hero_global_stats_query(self, stats: list[enums.LogStatsName] | None) -> sa.Select:
        """Read precomputed global per-(hero, stat) records from the materialized
        view ``matches.mv_hero_global_stats``.

        The heavy aggregation that used to run here on every cache miss (a window
        function over the whole eligible set joined to 5 tables) blew past
        ``statement_timeout``. It now lives in the view body and is refreshed
        out-of-band by the app-worker (see ``hero_stats_refresh``); reads are a
        cheap indexed scan, so the per-request cache is no longer needed.
        """
        mv = mv_hero_global_stats
        query = sa.select(
            mv.c.name,
            mv.c.hero_id,
            mv.c.best_value,
            mv.c["avg"],
            mv.c["metadata"],
        )
        if stats:
            query = query.where(mv.c.name.in_(stats))
        return query.order_by(mv.c.hero_id)

    async def get_statistics_by_heroes_all_values(
        self,
        session: AsyncSession,
        stats: list[enums.LogStatsName] | None = None,
    ) -> typing.Sequence[tuple[enums.LogStatsName, int, float, float, dict]]:
        """Best value (+ metadata) and global per-10min average for every (hero, stat).

        Served from the precomputed ``matches.mv_hero_global_stats`` view. Returns an
        empty sequence until the view's first refresh has populated it, so callers
        degrade gracefully (per-user stats render without the global comparison).
        ``stats=None`` reads every stat; a non-empty list narrows the view scan.
        """
        result = await session.execute(self._read_hero_global_stats_query(stats))
        return result.all()  # type: ignore[return-value]

    async def get_best_teammates(
        self,
        session: AsyncSession,
        user_id: int,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[tuple[models.User, float, int, int, float | None, float | None]], int]:
        """A user's best teammates as ``(teammate, win rate together, tournaments together,
        distinct maps together, average performance, average KDA)`` rows, plus the total count.
        """
        self_player = sa.orm.aliased(models.Player, name="self_player")
        teammate_player = sa.orm.aliased(models.Player, name="teammate_player")
        self_member = sa.orm.aliased(models.WorkspaceMember, name="self_member")
        teammate_member = sa.orm.aliased(models.WorkspaceMember, name="teammate_member")

        shared_teams_select = (
            sa.select(
                teammate_member.player_id.label("teammate_id"),
                teammate_player.team_id.label("team_id"),
                teammate_player.tournament_id.label("tournament_id"),
            )
            .select_from(self_player)
            .join(teammate_player, teammate_player.team_id == self_player.team_id)
            .join(self_member, self_member.id == self_player.workspace_member_id)
            .join(teammate_member, teammate_member.id == teammate_player.workspace_member_id)
            .where(
                self_member.player_id == user_id,
                self_player.is_substitution.is_(False),
                teammate_player.is_substitution.is_(False),
                teammate_member.player_id != user_id,
            )
            .distinct()
        )

        if workspace_id is not None:
            shared_teams_select = shared_teams_select.join(
                models.Tournament, models.Tournament.id == self_player.tournament_id
            ).where(models.Tournament.workspace_id == workspace_id)

        shared_teams = shared_teams_select.cte("shared_teams")

        def _encounter_side(team_fk, won, lost):
            return (
                sa.select(
                    shared_teams.c.teammate_id.label("teammate_id"),
                    models.Encounter.tournament_id.label("tournament_id"),
                    won.label("won_score"),
                    lost.label("lost_score"),
                )
                .select_from(shared_teams)
                .join(models.Encounter, team_fk == shared_teams.c.team_id)
            )

        teammate_encounters = union_encounter_team_sides(_encounter_side).cte("teammate_encounters")

        teammates_query = (
            sa.select(
                teammate_encounters.c.teammate_id.label("user_id"),
                (
                    sa.func.sum(teammate_encounters.c.won_score)
                    / sa.func.nullif(
                        sa.func.sum(teammate_encounters.c.won_score + teammate_encounters.c.lost_score),
                        0,
                    )
                ).label("winrate"),
                sa.func.count(sa.distinct(teammate_encounters.c.tournament_id)).label("tournaments"),
            )
            .group_by(teammate_encounters.c.teammate_id)
            .having(sa.func.count(sa.distinct(teammate_encounters.c.tournament_id)) > 1)
        ).cte("teammates_query")

        # Teammate "MVP" column spans two LogStatsName columns: ImpactRank when the
        # impact-scoring pipeline computed it for a match, legacy Performance
        # otherwise — same COALESCE(ImpactRank, Performance) per-match average as
        # services.user.queries.encounters.get_roster_avg_mvp_bulk. First collapse each
        # match's rows into one (impact_rank, performance, kda) tuple via an
        # outer join (keeps a teammate with zero stat rows in the result with
        # NULLs, matching the prior behaviour), THEN average per teammate.
        stats_per_match = (
            sa.select(
                shared_teams.c.teammate_id.label("user_id"),
                models.MatchStatistics.match_id.label("match_id"),
                sa.func.max(
                    sa.case(
                        (models.MatchStatistics.name == enums.LogStatsName.ImpactRank, models.MatchStatistics.value)
                    )
                ).label("impact_rank"),
                sa.func.max(
                    sa.case(
                        (models.MatchStatistics.name == enums.LogStatsName.Performance, models.MatchStatistics.value)
                    )
                ).label("performance"),
                sa.func.max(
                    sa.case((models.MatchStatistics.name == enums.LogStatsName.KDA, models.MatchStatistics.value))
                ).label("kda"),
            )
            .select_from(shared_teams)
            .join(teammates_query, teammates_query.c.user_id == shared_teams.c.teammate_id)
            .outerjoin(
                models.MatchStatistics,
                sa.and_(
                    models.MatchStatistics.team_id == shared_teams.c.team_id,
                    models.MatchStatistics.user_id == shared_teams.c.teammate_id,
                    models.MatchStatistics.round == 0,
                    models.MatchStatistics.hero_id.is_(None),
                    models.MatchStatistics.name.in_(
                        [
                            enums.LogStatsName.ImpactRank,
                            enums.LogStatsName.Performance,
                            enums.LogStatsName.KDA,
                        ]
                    ),
                ),
            )
            .group_by(shared_teams.c.teammate_id, models.MatchStatistics.match_id)
        ).cte("teammate_stats_per_match")

        mvp_placement = sa.func.coalesce(stats_per_match.c.impact_rank, stats_per_match.c.performance)
        stats_query = (
            sa.select(
                stats_per_match.c.user_id,
                sa.func.avg(mvp_placement).label("performance"),
                sa.func.avg(stats_per_match.c.kda).label("kda"),
            ).group_by(stats_per_match.c.user_id)
        ).cte("stats_query")

        # Distinct maps played together (separate CTE so the encounter→match fan-out
        # does not skew the winrate/tournament aggregates in teammates_query).
        def _map_side(team_fk, _won, _lost):
            return (
                sa.select(
                    shared_teams.c.teammate_id.label("user_id"),
                    models.Match.map_id.label("map_id"),
                )
                .select_from(shared_teams)
                .join(teammates_query, teammates_query.c.user_id == shared_teams.c.teammate_id)
                .join(models.Encounter, team_fk == shared_teams.c.team_id)
                .outerjoin(models.Match, models.Match.encounter_id == models.Encounter.id)
            )

        map_sides = union_encounter_team_sides(_map_side).subquery("teammate_map_sides")
        maps_query = (
            sa.select(
                map_sides.c.user_id,
                sa.func.count(sa.distinct(map_sides.c.map_id)).label("maps"),
            ).group_by(map_sides.c.user_id)
        ).cte("maps_query")

        count_query = sa.select(sa.func.count(teammates_query.c.user_id))

        query = (
            sa.select(
                models.User,
                teammates_query.c.winrate,
                teammates_query.c.tournaments,
                maps_query.c.maps,
                stats_query.c.performance,
                stats_query.c.kda,
            )
            .select_from(teammates_query)
            .join(models.User, models.User.id == teammates_query.c.user_id)
            .join(stats_query, stats_query.c.user_id == teammates_query.c.user_id)
            .join(maps_query, maps_query.c.user_id == teammates_query.c.user_id)
        )

        query = params.apply_pagination_sort(query)
        result = await session.execute(query)
        count_result = await session.execute(count_query)
        return result.all(), count_result.scalar_one()  # type: ignore


profile = UserProfileQueries()
