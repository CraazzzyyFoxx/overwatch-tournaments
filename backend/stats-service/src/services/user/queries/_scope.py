"""Shared SQL scope predicates and load-option helpers for the user queries.

Pure stateless builders, reused by :mod:`.overview`, :mod:`.compare`,
:mod:`.profile` and :mod:`.encounters`.
"""

import typing

import sqlalchemy as sa
from sqlalchemy.orm import aliased, joinedload, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import enums, utils
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import DivisionGrid, division_filter_predicates, ladder_grid
from shared.models.catalog.role import CatalogRole, RoleDimension
from shared.models.tournament.player_role import PlayerRole
from shared.repository.stats_queries import player_facts
from shared.schemas.role import RoleRef
from shared.services.division_grid.access import canonical_division_expr, tournament_grid_versions


def team_has_played_encounter(team_id_column: typing.Any = models.Team.id) -> sa.ColumnElement[bool]:
    """Indexable EXISTS (``ix_team_team_id``): the team holds a live seat in some encounter."""
    return sa.exists(
        sa.select(1)
        .select_from(models.EncounterTeam)
        .where(models.EncounterTeam.team_id == team_id_column, models.EncounterTeam.active.is_(True))
    )


def _team_load_options(entities: list[str]) -> list[_AbstractLoad]:
    """Load options for selecting Team with optional related entities."""
    opts: list[_AbstractLoad] = []
    if "tournament" in entities:
        opts.append(joinedload(models.Team.tournament))
    if "placement" in entities:
        opts.append(selectinload(models.Team.standings))
    return opts


def user_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """SQLAlchemy load options for the related entities named in ``in_entities``.

    ``child`` is an existing relationship/join entity to chain the options onto
    instead of loading straight off ``User``.
    """
    entities = []
    # Unified identity source consumed by ``UserService.to_read``, loaded when ``social_accounts`` is requested.
    if "social_accounts" in in_entities:
        # Eager-load each account's visibility rows alongside it so ``to_read`` can
        # compute ``visible_global`` and (on public reads) drop hidden accounts
        # without a lazy load outside the async greenlet.
        social_load = utils.join_entity(child, models.User.social_accounts)
        entities.append(social_load.selectinload(models.SocialAccount.visibilities))
    return entities


def _hero_direction_score(value_column: sa.ColumnElement[typing.Any], name_column: sa.ColumnElement[typing.Any]):
    ascending_stats = [stat for stat, direction in enums.LOG_STATS_DEFAULT_DIRECTION.items() if direction == "asc"]
    direction_multiplier = sa.case(
        (name_column.in_(ascending_stats), -1.0),
        else_=1.0,
    )
    return value_column * direction_multiplier


def _build_eligible_hero_stats_cte(
    *,
    discipline: str,
    user_id: int | None,
    stats: list[enums.LogStatsName] | None,
    cte_name: str,
    tournament_id: int | None = None,
    workspace_id: int | None = None,
) -> sa.CTE:
    facts = player_facts(discipline=discipline)
    # Qualification is at observed member/entity grain, not today's roster.
    qualified_where = [
        facts.c.segment == 0,
        facts.c.stat_code == enums.LogStatsName.HeroTimePlayed.value,
        facts.c.value > 60,
    ]
    if user_id is not None:
        qualified_where.append(facts.c.player_id == user_id)
    qualified_combos = (
        sa.select(facts.c.match_id, facts.c.workspace_member_id, facts.c.entity_id)
        .where(*qualified_where)
        .distinct()
        .cte(f"{cte_name}_qualified")
    )
    base_select = (
        sa.select(
            facts.c.match_id,
            facts.c.workspace_member_id,
            facts.c.player_id,
            facts.c.entity_id,
            facts.c.stat_code,
            facts.c.value,
        )
        .select_from(facts)
        .join(
            qualified_combos,
            sa.and_(
                qualified_combos.c.match_id == facts.c.match_id,
                qualified_combos.c.workspace_member_id == facts.c.workspace_member_id,
                qualified_combos.c.entity_id == facts.c.entity_id,
            ),
        )
        # Mix stats live only inside the mix (mix encounters have no tournament).
        .where(facts.c.segment == 0, facts.c.entity_id.isnot(None), facts.c.tournament_id.is_not(None))
    )
    if user_id is not None:
        base_select = base_select.where(facts.c.player_id == user_id)
    if stats:
        base_select = base_select.where(facts.c.stat_code.in_([stat.value for stat in stats]))
    if tournament_id is not None:
        base_select = base_select.where(facts.c.tournament_id == tournament_id)
    if workspace_id is not None:
        base_select = base_select.where(facts.c.workspace_id == workspace_id)
    return base_select.cte(cte_name)


def canonical_division_predicates(
    rank_column: sa.ColumnElement[int],
    tournament_id_column: sa.ColumnElement[int],
    discipline: str,
    *,
    divisions: typing.Sequence[int] = (),
    div_min: int | None = None,
    div_max: int | None = None,
) -> list[typing.Any]:
    """The all-workspaces division filter, on each row's canonical (native-ladder) number.

    The rank resolves on its own tournament's effective grid version, semi-joined from
    :func:`tournament_grid_versions` (one resolution per tournament), and the matched tier's stored
    ``canonical_number`` is compared. A game without a native ladder has no canonical number: 422.
    """
    wanted = sorted(set(divisions))
    if not wanted and div_min is None and div_max is None:
        return []
    ladder = ladder_grid(discipline)
    if ladder is None:
        raise HTTPException(
            status_code=422,
            detail=f"division_grid_required: {discipline!r} has no native ladder for cross-workspace divisions",
        )
    versions = tournament_grid_versions(discipline)
    division = canonical_division_expr(rank_column, versions.c.version_id, ladder)
    conditions: list[typing.Any] = []
    if wanted:
        conditions.append(division.in_(wanted))
    if div_min is not None and div_max is not None:
        conditions.append(division.between(div_min, div_max))
    elif div_min is not None:
        conditions.append(division >= div_min)
    elif div_max is not None:
        conditions.append(division <= div_max)
    return [
        sa.exists(
            sa.select(1)
            .select_from(versions)
            .where(versions.c.tournament_id == tournament_id_column, *conditions)
            .correlate_except(versions)
        )
    ]


def division_set_predicates(
    rank_column: sa.ColumnElement[int],
    tournament_id_column: sa.ColumnElement[int],
    divisions: typing.Sequence[int],
    grid: DivisionGrid,
    workspace_id: int | None,
    discipline: str,
) -> list[typing.Any]:
    """``division(rank) IN divisions`` for the scope's division numbers.

    Scoped reads keep the indexable rank ranges of
    :func:`division_filter_predicates` — one OR'd range per selected division,
    so a contiguous pick stays a plain ``rank`` comparison. The all-workspaces
    read matches canonical ladder numbers (:func:`canonical_division_predicates`).
    """
    wanted = sorted(set(divisions))
    if not wanted:
        return []
    if workspace_id is None:
        return canonical_division_predicates(rank_column, tournament_id_column, discipline, divisions=wanted)
    return [
        sa.or_(
            *[sa.and_(*division_filter_predicates(rank_column, number, number, grid)) for number in wanted],
        )
    ]


def player_role_filter(player_model: type[models.Player], ref: RoleRef | None) -> sa.ColumnElement[bool]:
    """Match a submitted leaf or top-level role without trusting its output-only parent."""
    role = CatalogRole
    if ref is None:
        return ~player_model.assignments.any(PlayerRole.role.has(role.dimension.has(RoleDimension.rated.is_(True))))
    return player_model.assignments.any(
        PlayerRole.role.has(
            sa.and_(
                role.dimension.has(RoleDimension.code == ref.dimension),
                sa.or_(role.code == ref.role, role.parent.has(role.code == ref.role)),
            )
        )
    )


def _apply_overview_role_filters(
    query: sa.Select,
    *,
    discipline: str,
    role: RoleRef | None,
    has_role_filter: bool = False,
    divisions: typing.Sequence[int] = (),
    grid: DivisionGrid,
    workspace_id: int | None = None,
) -> sa.Select:
    """Keep users who have a player row matching the role/division chips.

    Workspace-scoped reads resolve the selected divisions against the one
    workspace grid. The all-workspaces read (``workspace_id is None``) cannot:
    the same rank is a different division in different grids, so each player
    row is matched by its canonical number on the game's native ladder.
    """
    role_filters: list[typing.Any] = [
        models.Player.workspace_member.has(models.WorkspaceMember.player_id == models.User.id),
        models.Player.is_substitution.is_(False),
        models.Player.tournament.has(models.Tournament.discipline == discipline),
    ]

    if has_role_filter or role is not None:
        role_filters.append(player_role_filter(models.Player, role))
    role_filters.extend(
        division_set_predicates(
            models.Player.rank,
            models.Player.tournament_id,
            divisions,
            grid,
            workspace_id,
            discipline,
        )
    )

    role_exists = sa.exists(sa.select(1).select_from(models.Player).where(*role_filters).correlate(models.User))
    return query.where(role_exists)


def user_has_logs(user_id: typing.Any, *, discipline: str | None) -> sa.Exists:
    """The user owns a parsed player-total row of the game (``None``: of any game).

    A total row exists for every observed player of a match (``fk_fact_player`` pins facts to ``match_player``), and
    probing totals per member rides the partial ``ix_fact_member_stat_total``. A bare ``player_facts`` EXISTS has no
    member index to use and hash-joins every fact: 47 s on the dev dataset against 20 ms here.
    """
    f, m, wm, e = models.StatsFact, models.StatsMatch, models.WorkspaceMember, models.Encounter
    return sa.exists().where(
        wm.player_id == user_id,
        f.workspace_member_id == wm.id,
        f.segment == 0,
        f.entity_id.is_(None),
        m.id == f.match_id,
        m.workspace_id == wm.workspace_id,
        # Mix stats live only inside the mix (mix encounters have no tournament).
        e.id == m.encounter_id,
        e.tournament_id.is_not(None),
        *([m.discipline == discipline] if discipline is not None else []),
    )


def apply_has_logs_filter(query: sa.Select, *, discipline: str | None) -> sa.Select:
    """Keep users with observed facts of the selected game (``None``: of any game)."""
    return query.where(user_has_logs(models.User.id, discipline=discipline))


def _apply_workspace_member_filter(query: sa.Select, workspace_id: int | None) -> sa.Select:
    """Scope a ``User``-selecting query to members of the given workspace.

    Workspace membership is anchored on
    ``workspace_member.player_id -> players.user.id``. When ``workspace_id`` is
    ``None`` the query is returned unchanged (no scoping), matching the
    ``workspace_filter`` contract in ``core.workspace``.
    """
    if workspace_id is None:
        return query
    member_exists = sa.exists(
        sa.select(1)
        .select_from(models.WorkspaceMember)
        .where(
            models.WorkspaceMember.player_id == models.User.id,
            models.WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return query.where(member_exists)


def _compare_player_scope_filters(
    player_model: type[models.Player],
    user_id_column: sa.ColumnElement[typing.Any] | int,
    *,
    discipline: str | None,
    role: RoleRef | None,
    div_min: int | None,
    div_max: int | None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
    workspace_id: int | None,
) -> list[typing.Any]:
    filters: list[typing.Any] = [
        player_model.workspace_member.has(models.WorkspaceMember.player_id == user_id_column),
        player_model.is_substitution.is_(False),
    ]
    # ``None`` is the cross-game read: every game's rows count.
    if discipline is not None:
        filters.append(player_model.tournament.has(models.Tournament.discipline == discipline))

    if role is not None:
        filters.append(player_role_filter(player_model, role))
    # All-workspaces bounds are canonical ladder numbers; a no-game read carries no division filter.
    if workspace_id is None and discipline is not None:
        filters.extend(
            canonical_division_predicates(
                player_model.rank, player_model.tournament_id, discipline, div_min=div_min, div_max=div_max
            )
        )
    else:
        filters.extend(division_filter_predicates(player_model.rank, div_min, div_max, grid))
    if tournament_id is not None:
        filters.append(player_model.tournament_id == tournament_id)

    return filters


def _compare_tournament_scope_exists(
    user_id_column: sa.ColumnElement[typing.Any] | int,
    tournament_id_column: sa.ColumnElement[typing.Any],
    *,
    discipline: str,
    role: RoleRef | None,
    div_min: int | None,
    div_max: int | None,
    tournament_id: int | None = None,
    grid: DivisionGrid,
    workspace_id: int | None,
) -> sa.ColumnElement[bool]:
    """``workspace_id`` only picks the division numbering (``None``: canonical); the caller scopes rows itself."""
    scoped_player = aliased(models.Player)
    scoped_tournament = aliased(models.Tournament)
    filters = _compare_player_scope_filters(
        scoped_player,
        user_id_column,
        discipline=discipline,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
        workspace_id=workspace_id,
    )
    filters.append(scoped_player.tournament_id == tournament_id_column)
    filters.extend(
        [
            scoped_tournament.id == scoped_player.tournament_id,
            scoped_tournament.is_finished.is_(True),
        ]
    )
    return sa.exists(sa.select(1).select_from(scoped_player).select_from(scoped_tournament).where(*filters))


def _compare_user_scope_exists(
    user_id_column: sa.ColumnElement[typing.Any] | int,
    *,
    discipline: str,
    role: RoleRef | None,
    div_min: int | None,
    div_max: int | None,
    tournament_id: int | None = None,
    workspace_id: int | None = None,
    grid: DivisionGrid,
) -> sa.ColumnElement[bool]:
    scoped_player = aliased(models.Player)
    scoped_tournament = aliased(models.Tournament)
    filters = _compare_player_scope_filters(
        scoped_player,
        user_id_column,
        discipline=discipline,
        role=role,
        div_min=div_min,
        div_max=div_max,
        tournament_id=tournament_id,
        grid=grid,
        workspace_id=workspace_id,
    )
    filters.extend(
        [
            scoped_tournament.id == scoped_player.tournament_id,
            scoped_tournament.is_finished.is_(True),
        ]
    )
    if workspace_id is not None:
        filters.append(scoped_tournament.workspace_id == workspace_id)
    return sa.exists(sa.select(1).select_from(scoped_player).select_from(scoped_tournament).where(*filters))


def _hero_compare_stat_visibility_condition(
    name_column: sa.ColumnElement[typing.Any],
    hero_id_column: sa.ColumnElement[typing.Any],
    *,
    hero_id: int | None,
) -> sa.ColumnElement[bool]:
    if hero_id is not None:
        return hero_id_column == hero_id

    return sa.or_(
        hero_id_column.isnot(None),
        name_column == enums.LogStatsName.ImpactRank,
    )
