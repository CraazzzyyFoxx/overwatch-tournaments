from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core.enums import (
    CasualTeamSide,
    HeroClass,
    MixParticipation,
    MixRoleSelectionMode,
    MixSelfSignup,
    MixStatus,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.domain.roster_shape import resolve_roster_shape
from shared.rbac import assign_workspace_system_role
from shared.repository import (
    CasualMatchRepository,
    CasualPlayerRepository,
    CasualTeamRepository,
    CustomGameCoHostRepository,
    CustomGameLobbyRepository,
    CustomGamePlayerRepository,
    CustomGamePlayerRoleRepository,
    CustomGameRepository,
    CustomGameTeamNameRepository,
    MapRepository,
    UserBalancerConfigRepository,
    UserRepository,
    WorkspaceMemberRepository,
)
from shared.repository.workspace import get_or_create_workspace_member
from shared.schemas.events import DiscordCard
from shared.schemas.roster_slots import RosterShapeRead
from shared.services.account_links import missing_account_links
from shared.services.division_grid.access import get_effective_division_grid
from shared.services.member_rank import MIX_ORDER, MemberRankService, member_rank_service
from shared.services.roster_shape_access import get_workspace_roster_slots
from shared.services.workspace_roster import (
    RosterMember,
    hosts_by_user_id,
    list_roster,
    workspace_member_user_ids,
)
from src.domain.balancer.result_serializer import as_lobby_document, seat_rating
from src.domain.mix_discord import build_lineup_embed, signup_card
from src.domain.mix_rotation import PlayerHistory, RotationRecommendation, recommend_rotation, rotation_priority
from src.domain.mix_self_service import MixSelfPolicy, mix_self_policy
from src.domain.mix_stats import SeatOutcome, aggregate_mix_stats, outcome_for
from src.services.balancer.role_naming import role_slot_code
from src.services.balancer.solver import run_mix_balance as _run_balance
from src.services.pickup_mix_realtime import emit_pickup_mix_updated

__all__ = ("CustomGameService", "custom_game_service")

_TERMINAL = frozenset({MixStatus.COMPLETED, MixStatus.CANCELLED})
#: Plenty for any pickup mix (2-3 teams in practice); guards against a
#: malformed payload turning into an unbounded dict.
_MAX_TEAMS = 8
#: Plenty for any pickup mix; guards a malformed payload from growing the
#: co-host list without bound.
_MAX_CO_HOSTS = 16
_MAX_TEAM_NAME_LEN = 60
#: A roster row owns only its lineup state. A rank correction goes into the
#: host's own layer of ``member_rank``, so it outlives the game it was made in.
_PLAYER_PATCH_FIELDS = frozenset({"participation", "roles", "is_flex", "lobby_pin"})

#: What a PLAYER may patch on their own row. Ranks are the host's book and
#: participation is the host's decision, so neither is here.
_SELF_PATCH_FIELDS = frozenset({"roles", "is_flex"})

#: HTTP status per admission blocker (``mix_self_policy``). 403 is "fix your
#: account", 409 "the mix says no", 404 "you are not in this lineup".
_BLOCKER_STATUS = {
    "mix_closed": status.HTTP_409_CONFLICT,
    "discord_not_linked": status.HTTP_403_FORBIDDEN,
    "battlenet_not_linked": status.HTTP_403_FORBIDDEN,
    "player_not_linked": status.HTTP_403_FORBIDDEN,
    "self_join_denied": status.HTTP_403_FORBIDDEN,
    "signup_closed": status.HTTP_409_CONFLICT,
    "roster_full": status.HTTP_409_CONFLICT,
    "role_edit_off": status.HTTP_409_CONFLICT,
    "not_on_roster": status.HTTP_404_NOT_FOUND,
}


def _blocker(code: str) -> HTTPException:
    """The refusal for one admission code; ``detail`` IS the code, so a client
    (site or bot) translates it instead of parsing English."""
    return HTTPException(status_code=_BLOCKER_STATUS[code], detail=code)


def _reject_unknown(patch: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown fields {unknown}")


@dataclass(frozen=True, slots=True)
class _SelfContext:
    """Everything one self-service call reads, resolved once."""

    game: models.CustomGame
    player: Any
    member: Any
    roster: list[models.CustomGamePlayer]
    row: models.CustomGamePlayer | None
    policy: MixSelfPolicy


def _require_host(actor_user_id: int, host_user_id: int | None) -> None:
    if host_user_id is None or actor_user_id != host_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the host can write this pool")


def _new_roster_row(game_id: int, member_id: int, sort_order: int) -> models.CustomGamePlayer:
    """A pool row with its lineup state spelled out.

    The column defaults say the same thing, but they only land at INSERT time --
    an object read back before its flush would carry ``None`` where the whole
    point of this feature is that a row always has exactly one participation.
    """
    return models.CustomGamePlayer(
        custom_game_id=game_id,
        workspace_member_id=member_id,
        sort_order=sort_order,
        participation=MixParticipation.POOL,
        role_selection_mode=MixRoleSelectionMode.ALL_RANKED,
        is_flex=False,
    )


def _noop_progress(*_args: Any, **_kwargs: Any) -> None:
    return None


def _uniq(ids: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _normalize_roles(raw: Any) -> list[str] | None:
    """Ordered, de-duplicated registration role codes; ``None`` means "all ranked"."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="roles must be a list")
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        code = str(item).strip().lower()
        if code not in REGISTRATION_ROLE_CODES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown role {code}")
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _normalize_team_names(raw: Mapping[str, Any]) -> dict[str, str | None]:
    """Validate a host's team-name patch, keyed by 0-based team index.

    Returns the index -> trimmed-name map to write, with ``None`` standing in
    for "clear this team's override back to its computed default" -- an
    explicit empty/whitespace value, distinct from an index the caller simply
    did not mention (which ``set_team_names`` below leaves untouched).
    """
    out: dict[str, str | None] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.isdigit():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"invalid team index: {key!r}")
        index = int(key)
        if index >= _MAX_TEAMS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"team index out of range: {index}"
            )
        if value is None:
            out[str(index)] = None
            continue
        if not isinstance(value, str):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="team name must be a string")
        trimmed = value.strip()
        if not trimmed:
            out[str(index)] = None
            continue
        if len(trimmed) > _MAX_TEAM_NAME_LEN:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"team name too long (max {_MAX_TEAM_NAME_LEN} chars)",
            )
        out[str(index)] = trimmed
    return out


def _apply_balance_result(roster: Sequence[models.CustomGamePlayer], result: Any) -> None:
    """Bench only the overflow rows explicitly returned by the solver."""
    variants = result.get("variants") if isinstance(result, dict) else None
    if not isinstance(variants, list) or not variants or not isinstance(variants[0], dict):
        return
    by_uuid = {str(row.workspace_member_id): row for row in roster}
    for uuid in variants[0].get("benched") or []:
        row = by_uuid.get(str(uuid))
        if row is not None:
            row.participation = MixParticipation.BENCHED


def _lobby_players(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """The ``players`` map of a stored ``lobby_document``: each seat's uuid resolves here."""
    players = result.get("players")
    return players if isinstance(players, Mapping) else {}


def _locate_seat(teams: Sequence[Mapping[str, Any]], uuid: str) -> tuple[int, str, int] | None:
    """Team index, role bucket and position of a seat by its player uuid."""
    for team_index, team in enumerate(teams):
        roster = team.get("roster") if isinstance(team, Mapping) else None
        if not isinstance(roster, Mapping):
            continue
        for role, entries in roster.items():
            if not isinstance(entries, list):
                continue
            for position, entry in enumerate(entries):
                if str(entry) == uuid:
                    return team_index, role, position
    return None


# Statistics a solver scored for the seating *it* produced. A hand-edited
# roster invalidates all of them at once, so they are cleared together.
_SOLVER_SCORED_STAT_KEYS = (
    "composite_score",
    "mix_balancer_fairness",
    "mix_balancer_uniformity",
    "mix_balancer_role_fairness",
    "mix_balancer_role_points",
    "mix_balancer_quality_total",
)


def _recompute_variant_stats(variant: dict[str, Any], players: Mapping[str, Any]) -> None:
    """Re-derive the read-only verdict from a manually edited roster.

    Mirrors the solver's own arithmetic for the three metrics that are pure
    functions of the roster (``calculate_team_stats`` / ``calculate_objective_breakdown``
    in ``tournament_balancer``): a team's average is the mean of its seats' ratings, the
    spread is the gap between the strongest and weakest team's *total* rating,
    and the standard deviation is the sample stdev of the teams' averages.

    ``composite_score`` is deliberately NOT one of these: it is a knee-score
    normalised against the whole Pareto archive the solver searched for that
    run, meaningless for a single hand-edited arrangement with no archive to
    normalise against -- so it is cleared rather than faked. The
    ``mix_balancer_*`` block goes the same way and for the same reason: those
    four terms and their total describe the seating the engine chose, and a
    hand-moved player invalidates every one of them (the role-priority term
    and the per-role balance most of all). Stale is worse than absent -- the
    frontend hides a metric it does not get.
    """
    teams = variant.get("teams")
    if not isinstance(teams, list):
        return
    team_totals: list[float] = []
    team_means: list[float] = []
    off_role_count = 0
    for team in teams:
        if not isinstance(team, dict):
            continue
        roster = team.get("roster")
        ratings: list[float] = []
        if isinstance(roster, Mapping):
            for role, entries in roster.items():
                if not isinstance(entries, list):
                    continue
                for uuid in entries:
                    player = players.get(str(uuid))
                    if not isinstance(player, Mapping):
                        continue
                    ratings.append(float(seat_rating(player, role)))
                    preferences = player.get("role_preferences") or []
                    is_flex = player.get("is_flex") is True
                    if not is_flex and preferences and preferences[0] != role:
                        off_role_count += 1
        total = sum(ratings)
        team["average_mmr"] = (total / len(ratings)) if ratings else None
        # Recomputed for the same reason as the average: the stored value is the
        # solver's, and ``max_total_rating_gap`` below is derived from this sum.
        team["total_rating"] = total
        team_totals.append(total)
        if ratings:
            team_means.append(total / len(ratings))

    statistics = dict(variant.get("statistics") or {})
    for stale_key in _SOLVER_SCORED_STAT_KEYS:
        statistics[stale_key] = None
    if len(team_means) >= 2:
        mean = sum(team_means) / len(team_means)
        variance = sum((value - mean) ** 2 for value in team_means) / (len(team_means) - 1)
        statistics["mmr_std_dev"] = variance**0.5
    else:
        statistics["mmr_std_dev"] = 0.0
    statistics["max_total_rating_gap"] = (max(team_totals) - min(team_totals)) if len(team_totals) >= 2 else 0.0
    statistics["off_role_count"] = off_role_count
    variant["statistics"] = statistics


class CustomGameService:
    def __init__(
        self,
        *,
        games: CustomGameRepository = CustomGameRepository(),
        roster: CustomGamePlayerRepository = CustomGamePlayerRepository(),
        co_hosts: CustomGameCoHostRepository = CustomGameCoHostRepository(),
        lobbies: CustomGameLobbyRepository = CustomGameLobbyRepository(),
        player_roles: CustomGamePlayerRoleRepository = CustomGamePlayerRoleRepository(),
        team_names: CustomGameTeamNameRepository = CustomGameTeamNameRepository(),
        casual_matches: CasualMatchRepository = CasualMatchRepository(),
        casual_teams: CasualTeamRepository = CasualTeamRepository(),
        casual_players: CasualPlayerRepository = CasualPlayerRepository(),
        maps: MapRepository = MapRepository(),
        host_prefs: UserBalancerConfigRepository = UserBalancerConfigRepository(),
        ranks: MemberRankService | None = None,
        load_roster=list_roster,
        load_hosts=hosts_by_user_id,
        load_member_user_ids=workspace_member_user_ids,
        run_balance=_run_balance,
        players: UserRepository = UserRepository(),
        workspace_members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        load_missing_links=missing_account_links,
        enroll_member=get_or_create_workspace_member,
        grant_player_role=assign_workspace_system_role,
    ) -> None:
        self.games = games
        self.roster = roster
        self.co_hosts = co_hosts
        self.lobbies = lobbies
        self.player_roles = player_roles
        self.team_names = team_names
        self.casual_matches = casual_matches
        self.casual_teams = casual_teams
        self.casual_players = casual_players
        self.maps = maps
        self.host_prefs = host_prefs
        self.ranks = ranks if ranks is not None else member_rank_service
        self.load_roster = load_roster
        self.load_hosts = load_hosts
        self.load_member_user_ids = load_member_user_ids
        self.run_balance = run_balance
        self.players = players
        self.workspace_members = workspace_members
        self.load_missing_links = load_missing_links
        self.enroll_member = enroll_member
        self.grant_player_role = grant_player_role

    async def members(
        self, session: AsyncSession, workspace_id: int, member_ids: Sequence[int]
    ) -> dict[int, RosterMember]:
        """Named roster rows for a lineup -- and the tenancy check on the way in.

        ``list_roster`` already filters by ``workspace_id``, so an id absent from
        the result either does not exist or belongs to another workspace. Both are
        the same 404 on purpose: telling them apart would leak the membership of a
        workspace the caller is not in.
        """
        ids = _uniq(member_ids)
        if not ids:
            return {}
        found = await self.load_roster(session, workspace_id=workspace_id, member_ids=ids)
        if len(found) != len(ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
        return found

    async def hosts(
        self, session: AsyncSession, workspace_id: int, host_user_ids: Sequence[int]
    ) -> dict[int, str | None]:
        """Display name for each mix's host, keyed by ``host_user_id``.

        Unlike ``members`` this never 404s: a host who has left the workspace
        has no label, and the list falls back to the raw id rather than hiding
        the whole mix.
        """
        ids = _uniq(host_user_ids)
        if not ids:
            return {}
        return await self.load_hosts(session, workspace_id=workspace_id, user_ids=ids)

    async def get(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        options: Sequence[Any] = (),
    ) -> models.CustomGame:
        game = await self.games.get(session, custom_game_id, options=options)
        if game is None or game.workspace_id != workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        return game

    async def list(self, session: AsyncSession, *, workspace_id: int) -> list[models.CustomGame]:
        return list(await self.games.list_for_workspace(session, workspace_id))

    async def _writable(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        # A superuser manages every mix as if a co-host. The flag comes from the
        # token, never a DB read: an API key is minted non-superuser on purpose.
        if not actor_is_superuser and actor_user_id != game.host_user_id:
            # The caller's workspace membership is already settled at the RPC
            # gate (``_require_mix``), so the grant itself is the only extra
            # fact left to read -- and it is keyed by ``auth.user.id``, the same
            # identity ``host_user_id`` holds.
            if actor_user_id not in await self.co_hosts.user_ids_for_game(session, game.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the host or a co-host can write this pool",
                )
        if game.status in _TERMINAL:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Game is {game.status}")
        return game

    async def _lobby(self, session: AsyncSession, game: models.CustomGame, lobby_index: int) -> models.CustomGameLobby:
        """One lobby row of this mix -- where every per-match fact lives.

        A mix has exactly ``lobby_count`` rows (``create`` opens them,
        ``set_lobby_count`` adds and removes the second), so a miss is a caller
        naming a lobby the mix does not run, not a row to conjure up.
        """
        lobby = await self.lobbies.get(session, game.id, lobby_index)
        if lobby is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lobby_not_found")
        return lobby

    async def _seed_host_ranks(
        self, session: AsyncSession, game: models.CustomGame, members: Mapping[int, RosterMember]
    ) -> None:
        """Materialise the host's own rank for everyone just added to the mix.

        A mix resolves against the host's book (``MIX_ORDER``), so an inherited
        number is one nobody in this mix owns: correcting it read as a per-game
        edit and was silently a workspace-wide one, and the sheet could offer no
        Clear because there was nothing of the host's to clear. Copying in the
        value the mix would have used anyway makes the layer explicit at the
        moment of joining -- from then on every rank in a lineup is the host's,
        editable and clearable, and the canon is a seed rather than a live
        dependency.

        Only holes are filled. An existing author rank is never overwritten, so
        re-adding somebody cannot undo a correction, and a role nobody has a
        number for anywhere stays unranked rather than being invented.
        """
        if game.host_user_id is None or not members:
            return
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            members={member_id: member.player_id for member_id, member in members.items()},
            roles=list(REGISTRATION_ROLE_CODES),
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await get_effective_division_grid(session, None),
        )
        for member_id in members:
            seed: dict[str, int] = {}
            for role in REGISTRATION_ROLE_CODES:
                rank = resolved.get((member_id, role))
                if rank is None or rank.value is None or rank.source == "author":
                    continue
                seed[role] = rank.value
            if not seed:
                continue
            await self.ranks.set_ranks(
                session,
                workspace_id=game.workspace_id,
                workspace_member_id=member_id,
                ranks=seed,
                author_user_id=game.host_user_id,
            )

    async def create(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        host_user_id: int,
        name: str,
        actor_user_id: int,
        member_ids: Sequence[int] = (),
        clone_from_game_id: int | None = None,
    ) -> models.CustomGame:
        """Open a mix, optionally starting from a previous one's setup.

        A clone copies the parts a host would otherwise re-enter every session --
        the pool and its per-seat role setup, the team names and the co-host
        grants -- but never anything that describes a *played* session: no
        balance result, no rolled map, no match history, and every seat back in
        the pool rather than carrying last week's pins and benchings. Roster
        members who have since left the workspace are dropped rather than failing
        the clone. The roster shape, the points knob and the Discord target are
        not copied because they are not the mix's: they belong to the host's
        account and the workspace, and the new mix already inherits both.
        """
        _require_host(actor_user_id, host_user_id)
        trimmed = name.strip() if isinstance(name, str) else ""
        if not trimmed:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name is required")
        ids = _uniq(member_ids)
        members = dict(await self.members(session, workspace_id, ids))

        source: models.CustomGame | None = None
        source_rows: list[models.CustomGamePlayer] = []
        if clone_from_game_id is not None:
            source = await self.games.get(session, clone_from_game_id)
            if source is None or source.workspace_id != workspace_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mix not found")
            candidates = list(await self.roster.list_for_game(session, source.id))
            # Lenient on purpose, unlike ``members`` above: a departed member is
            # dropped from the copy, not a 404 that makes the old mix
            # un-clonable forever.
            surviving = await self.load_roster(
                session,
                workspace_id=workspace_id,
                member_ids=_uniq([row.workspace_member_id for row in candidates]),
            )
            source_rows = [row for row in candidates if row.workspace_member_id in surviving]
            members.update(surviving)

        game = models.CustomGame(
            workspace_id=workspace_id,
            host_user_id=host_user_id,
            name=trimmed,
            status=MixStatus.DRAFT,
            # A clone is a new session: the host's "players edit their own roles"
            # choice carries over, the open signup window deliberately does not.
            self_signup=MixSelfSignup.CLOSED,
            self_role_edit=bool(source.self_role_edit) if source is not None else False,
            # How this host runs a session -- one lobby or two -- travels with
            # the clone; the matchups played in them do not.
            lobby_count=source.lobby_count if source is not None else 1,
        )
        await self.games.create(session, game)
        # The invariant every per-match read relies on: a mix always has its
        # lobbies. A clone copies the pool and the setup, never a played
        # session, so the fresh lobbies start empty.
        for lobby_index in range(game.lobby_count):
            await self.lobbies.create(session, models.CustomGameLobby(custom_game_id=game.id, lobby_index=lobby_index))

        cloned: list[tuple[models.CustomGamePlayer, models.CustomGamePlayer]] = []
        rows: list[models.CustomGamePlayer] = []
        for source_row in source_rows:
            row = _new_roster_row(game.id, source_row.workspace_member_id, source_row.sort_order)
            row.role_selection_mode = source_row.role_selection_mode
            row.is_flex = source_row.is_flex
            row.lobby_pin = source_row.lobby_pin
            rows.append(row)
            cloned.append((source_row, row))
        taken = {row.workspace_member_id for row in rows}
        next_order = max((row.sort_order for row in rows), default=-1) + 1
        for member_id in ids:
            if member_id in taken:
                continue
            rows.append(_new_roster_row(game.id, member_id, next_order))
            next_order += 1
        if rows:
            await self.roster.create_many(session, rows)

        if source is not None:
            roles_by_source_row = await self.player_roles.roles_for_players(
                session, [source_row.id for source_row, _row in cloned]
            )
            for source_row, row in cloned:
                roles = roles_by_source_row.get(source_row.id)
                if roles:
                    await self.player_roles.replace_for_player(session, row.id, roles)
            for index, team_name in (await self.team_names.mapping_for_game(session, source.id)).items():
                await self.team_names.set(session, game.id, index, team_name)
            for user_id in await self.co_hosts.user_ids_for_game(session, source.id):
                if user_id != host_user_id:
                    await self.co_hosts.add(session, game.id, user_id)

        await self._seed_host_ranks(
            session, game, {row.workspace_member_id: members[row.workspace_member_id] for row in rows}
        )
        return game

    async def update_roster(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        member_ids: Sequence[int],
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Set pool membership, keeping every surviving row's lineup state.

        Adding or dropping one player must not reset the bench switches and role
        orders the host already tuned for everybody else, so rows are matched by
        ``workspace_member_id`` instead of rebuilt from scratch.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        ids = _uniq(member_ids)
        members = await self.members(session, workspace_id, ids)
        existing = {row.workspace_member_id: row for row in await self.roster.list_for_game(session, game.id)}
        wanted = set(ids)
        for member_id, row in existing.items():
            if member_id not in wanted:
                await self.roster.delete(session, row)
        created: list[models.CustomGamePlayer] = []
        for index, member_id in enumerate(ids):
            row = existing.get(member_id)
            if row is None:
                created.append(_new_roster_row(game.id, member_id, index))
            else:
                row.sort_order = index
        if created:
            await self.roster.create_many(session, created)
            await self._seed_host_ranks(
                session,
                game,
                {row.workspace_member_id: members[row.workspace_member_id] for row in created},
            )
        await session.flush()
        return game

    async def update_player(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        workspace_member_id: int,
        patch: Mapping[str, Any],
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Patch one roster row's participation, role selection and flex mode."""
        # Before the game read on purpose: an unknown key is a client bug, and
        # answering 422 for it must not depend on the row existing.
        _reject_unknown(patch, _PLAYER_PATCH_FIELDS)
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        row = next((item for item in roster if item.workspace_member_id == workspace_member_id), None)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game player not found")
        await self._apply_player_patch(session, row, patch, _PLAYER_PATCH_FIELDS, lobby_count=game.lobby_count)
        await session.flush()
        return game

    async def _apply_player_patch(
        self,
        session: AsyncSession,
        row: models.CustomGamePlayer,
        patch: Mapping[str, Any],
        allowed: frozenset[str],
        *,
        lobby_count: int = 1,
    ) -> None:
        """Apply a validated lineup patch to one row, within ``allowed`` fields.

        One mutation for two callers: the host patches the whole row
        (``_PLAYER_PATCH_FIELDS``), a player only their own role order and flex
        (``_SELF_PATCH_FIELDS``). The difference between them is the gate, not
        the write -- a self edit that diverged here would be a second, subtly
        different way to set the same columns.

        ``lobby_count`` is the mix's, and only the pin reads it: pinning to a
        lobby the mix does not run is a client bug, not a silent no-op. The self
        path never carries a pin (``lobby_pin`` is not in ``_SELF_PATCH_FIELDS``),
        so it leaves the default alone.
        """
        _reject_unknown(patch, allowed)
        if "participation" in patch:
            try:
                row.participation = MixParticipation(patch["participation"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid participation",
                ) from exc
        if "roles" in patch:
            roles = _normalize_roles(patch["roles"])
            row.role_selection_mode = (
                MixRoleSelectionMode.ALL_RANKED if roles is None else MixRoleSelectionMode.EXPLICIT
            )
            await self.player_roles.replace_for_player(session, row.id, roles or ())
        if "is_flex" in patch:
            if not isinstance(patch["is_flex"], bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="is_flex must be a boolean",
                )
            row.is_flex = patch["is_flex"]
        if "lobby_pin" in patch:
            if lobby_count < 2:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="lobby_pin requires a mix with two lobbies",
                )
            row.lobby_pin = patch["lobby_pin"]

    async def set_participation(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        participation: Mapping[int, MixParticipation],
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Move several roster rows between lineup states atomically.

        The rotation hint applies a whole verdict at once. One transaction, one
        snapshot: applying it row by row raced on whose response the client
        saw last, and left the lineup mid-verdict if one call failed.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        rows = {row.workspace_member_id: row for row in await self.roster.list_for_game(session, game.id)}
        if not set(participation) <= set(rows):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game player not found")
        for member_id, state in participation.items():
            rows[member_id].participation = state
        await session.flush()
        return game

    async def set_lobby_count(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_count: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Run this mix as one lobby or two.

        Going to two opens an empty lobby B: it has no matchup until somebody
        balances it, and lobby A is not touched. Going back to one deletes
        lobby B -- its stored matchup is lost, its recorded matches stay in the
        history -- and frees every pin, because a pin to a lobby the mix no
        longer runs would quietly exclude that player from the next balance.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if lobby_count == game.lobby_count:
            return game
        if lobby_count == 2:
            await self.lobbies.create(session, models.CustomGameLobby(custom_game_id=game.id, lobby_index=1))
        else:
            lobby = await self.lobbies.get(session, game.id, 1)
            if lobby is not None:
                await self.lobbies.delete(session, lobby)
            for row in await self.roster.list_for_game(session, game.id):
                row.lobby_pin = None
        game.lobby_count = lobby_count
        await session.flush()
        return game

    async def _self_context(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None,
    ) -> _SelfContext:
        """The mix, the caller's own seat in it, and the policy over both.

        The workspace comes from the mix row, not the caller: the bot knows a
        ``custom_game_id`` and nothing else. When a ``workspace_id`` IS supplied
        (the site's route carries one) it must agree, or this is a 404 -- the same
        answer a mix of another workspace gets everywhere else.
        """
        game = await self.games.get(session, custom_game_id)
        if game is None or (workspace_id is not None and game.workspace_id != workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        player = await self.players.get_by_auth_user_id(session, auth_user.id)
        member = (
            None
            if player is None
            else await self.workspace_members.get_by_player(
                session, workspace_id=game.workspace_id, player_id=player.id
            )
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        row = None if member is None else next((item for item in roster if item.workspace_member_id == member.id), None)
        policy = mix_self_policy(
            status=game.status,
            self_signup=game.self_signup,
            self_role_edit=game.self_role_edit,
            on_roster=row is not None,
            missing_links=await self.load_missing_links(session, auth_user.id),
            has_player=player is not None,
            self_join_denied=not auth_user.can_capability("custom_game", "self_join", workspace_id=game.workspace_id),
            roster_size=len(roster),
        )
        return _SelfContext(game=game, player=player, member=member, roster=roster, row=row, policy=policy)

    async def _self_dump(self, session: AsyncSession, ctx: _SelfContext) -> dict[str, Any]:
        """One player's view of one mix: their seat, and what they may do next.

        ``ranks`` carries all three roles, ``None`` included: the Discord role
        select labels every option with a number or "no rank", and a sparse dict
        would make the bot guess. ``unranked_roles`` is the narrower list the
        warning is built from -- the roles this player actually plays.

        """
        seat: dict[str, Any] | None = None
        unranked: list[str] = []
        if ctx.row is not None:
            stored = (await self.player_roles.roles_for_players(session, [ctx.row.id])).get(ctx.row.id, [])
            explicit = ctx.row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
            resolved = await self.ranks.resolve(
                session,
                workspace_id=ctx.game.workspace_id,
                members={ctx.row.workspace_member_id: ctx.player.id if ctx.player is not None else None},
                roles=list(REGISTRATION_ROLE_CODES),
                order=MIX_ORDER,
                author_user_id=ctx.game.host_user_id,
                grid=await get_effective_division_grid(session, None),
            )
            ranks: dict[str, int | None] = {}
            for role in REGISTRATION_ROLE_CODES:
                rank = resolved.get((ctx.row.workspace_member_id, role))
                ranks[role] = rank.value if rank is not None else None
            considered = list(stored) if explicit else list(REGISTRATION_ROLE_CODES)
            unranked = [role for role in considered if ranks.get(role) is None]
            seat = {
                "participation": ctx.row.participation,
                # ``null`` means all_ranked: every role this player has a number
                # for plays, which is a different statement from an empty list.
                "roles": list(stored) if explicit else None,
                "is_flex": ctx.row.is_flex,
                "ranks": ranks,
            }
        return {
            "custom_game_id": ctx.game.id,
            "name": ctx.game.name,
            "status": ctx.game.status,
            "self_signup": ctx.game.self_signup,
            "self_role_edit": ctx.game.self_role_edit,
            "seat": seat,
            "unranked_roles": unranked,
            "policy": {
                "can_join": ctx.policy.can_join,
                "can_leave": ctx.policy.can_leave,
                "can_edit_roles": ctx.policy.can_edit_roles,
                "join_blocker": ctx.policy.join_blocker,
                "edit_blocker": ctx.policy.edit_blocker,
            },
        }

    async def self_state(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Read-only: what this account's seat is and what it may do."""
        return await self._self_dump(
            session,
            await self._self_context(
                session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
            ),
        )

    async def self_join(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Seat this account in the mix, enrolling it in the workspace if needed.

        Idempotent by design: an existing row is left EXACTLY as it is, so a
        player the host benched cannot walk that back by clicking Join again.
        """
        ctx = await self._self_context(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )
        if ctx.row is not None:
            return await self._self_dump(session, ctx)
        if ctx.policy.join_blocker is not None:
            raise _blocker(ctx.policy.join_blocker)

        # Same two idempotent steps the tournament self-registration takes
        # (tournament-service/src/services/registration/service.py): the
        # membership row anchors the roster row, the baseline RBAC role makes the
        # account an ordinary workspace player rather than a role-less anchor.
        member = ctx.member or await self.enroll_member(
            session, workspace_id=ctx.game.workspace_id, player_id=ctx.player.id
        )
        await self.grant_player_role(
            session, user_id=auth_user.id, workspace_id=ctx.game.workspace_id, role_name="player"
        )
        row = _new_roster_row(ctx.game.id, member.id, len(ctx.roster))
        row.participation = MixParticipation(ctx.game.self_signup)
        try:
            async with session.begin_nested():
                await self.roster.create(session, row)
        except IntegrityError:
            # Two clicks raced onto uq_custom_game_player_member. The other one
            # seated them, so report the state it produced instead of a 500.
            return await self.self_state(
                session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
            )
        await self._seed_host_ranks(session, ctx.game, await self.members(session, ctx.game.workspace_id, [member.id]))
        await session.flush()
        await emit_pickup_mix_updated(session, ctx.game.workspace_id, change="roster", actor_user_id=auth_user.id)
        return await self.self_state(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )

    async def self_leave(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Drop this account's own row, exactly as the host removing it would.

        Deliberately does not require the account links: somebody who unlinked
        Battle.net after joining must still be able to get out of the lineup.
        """
        ctx = await self._self_context(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )
        if not ctx.policy.can_leave or ctx.row is None:
            # A terminal mix refuses every write; anything else means this
            # account simply holds no row in this lineup.
            raise _blocker("mix_closed" if ctx.policy.join_blocker == "mix_closed" else "not_on_roster")
        await self.roster.delete(session, ctx.row)
        await session.flush()
        await emit_pickup_mix_updated(session, ctx.game.workspace_id, change="roster", actor_user_id=auth_user.id)
        return await self.self_state(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )

    async def self_update(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        patch: Mapping[str, Any],
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Re-order this account's own roles / flip its flex flag.

        The stored balance is NOT recomputed: it is a snapshot of a search the
        host ran, and a role change takes effect the next time they balance.
        """
        _reject_unknown(patch, _SELF_PATCH_FIELDS)
        ctx = await self._self_context(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )
        if ctx.row is None or not ctx.policy.can_edit_roles:
            raise _blocker(ctx.policy.edit_blocker or "not_on_roster")
        await self._apply_player_patch(session, ctx.row, patch, _SELF_PATCH_FIELDS)
        await session.flush()
        await emit_pickup_mix_updated(session, ctx.game.workspace_id, change="roster", actor_user_id=auth_user.id)
        return await self.self_state(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )

    async def set_self_service(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        patch: Mapping[str, Any],
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """The host's two switches: who may seat themselves, and who may re-role."""
        _reject_unknown(patch, frozenset({"self_signup", "self_role_edit"}))
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if "self_signup" in patch:
            try:
                game.self_signup = MixSelfSignup(patch["self_signup"]).value
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid self_signup",
                ) from exc
        if "self_role_edit" in patch:
            if not isinstance(patch["self_role_edit"], bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="self_role_edit must be a boolean",
                )
            game.self_role_edit = patch["self_role_edit"]
        await session.flush()
        return game

    async def signup_post(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        self_signup: str,
        actor_user_id: int,
        actor_is_superuser: bool = False,
        board_url_base: str,
    ) -> tuple[int, DiscordCard]:
        """Open signup and build the card that announces it.

        The mode is written HERE rather than left to a separate call: a card in
        the channel whose buttons answer ``signup_closed`` is the one outcome
        nobody wants, and the column -- not the card -- is what admits a player.

        Publishing is the RPC layer's job (that is where the broker is), so this
        returns the channel and the payload, exactly like :meth:`discord_lineup`.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        # Resolved before the write: posting nowhere and silently opening signup
        # would leave the host believing the channel has a card.
        channel_id = await self.workspace_discord_channel_id(session, workspace_id)
        if channel_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Discord channel not configured")
        try:
            game.self_signup = MixSelfSignup(self_signup).value
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid self_signup") from exc
        host_names = await self.hosts(session, workspace_id, [game.host_user_id])
        card = signup_card(
            mix_name=game.name,
            host_name=host_names.get(game.host_user_id),
            board_url=f"{board_url_base.rstrip('/')}/balancer/mix/{game.id}",
            custom_game_id=game.id,
        )
        await session.flush()
        return channel_id, card

    async def _host_config(self, session: AsyncSession, host_user_id: int | None) -> Any:
        """The host's ``balancer.user_config`` row, or ``None`` if they never saved one.

        Everything a mix is configured with hangs off this single row -- solver
        knobs, roster shape, points per win -- so a caller that needs two of them
        loads it once and reads both, instead of hitting the table per knob.
        """
        if host_user_id is None:
            return None
        return await self.host_prefs.get_by_user(session, host_user_id)

    async def _shape_for(self, session: AsyncSession, workspace_id: int, host_config: Any) -> RosterShapeRead:
        """Host's own shape -> workspace default -> built-in Overwatch 5v5."""
        host_slots = host_config.role_slots_json if host_config is not None else None
        workspace_slots = await get_workspace_roster_slots(session, workspace_id)
        shape = resolve_roster_shape(host_slots or None, workspace_slots)
        source = "host" if host_slots else "workspace" if workspace_slots else "default"
        return RosterShapeRead.from_shape(shape, source=source)

    async def roster_shape(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        host_user_id: int | None,
    ) -> RosterShapeRead:
        """The shape this mix fields, resolved from its HOST's saved preferences.

        Keyed by the host rather than by the mix: the shape describes how this
        person runs their pickup sessions (5v5, 6v6, all-flex), not what happened
        in one lobby, so it lives in ``balancer.user_config`` alongside their
        solver knobs. A co-host pressing Balance still gets the host's shape --
        same reason the ranks resolve against the host's book.
        """
        return await self._shape_for(session, workspace_id, await self._host_config(session, host_user_id))

    async def host_points_per_win(self, session: AsyncSession, host_user_id: int | None) -> int:
        """How far a decided match moves this host's rank book; 0 means "not at all"."""
        config = await self._host_config(session, host_user_id)
        return (config.points_per_win or 0) if config is not None else 0

    async def balance(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        lineup = [row for row in roster if row.participation != MixParticipation.BENCHED]
        if not lineup:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
        # If the lineup does not divide evenly into full teams, `run_balance`'s own
        # overflow trim (`domain.balancer.runtime._prepare_balance_context`) sorts the
        # players not pinned to a seat by `Player.rotation_priority` ascending and
        # benches the TAIL -- the HIGHEST values, i.e. those `rotation_priority()`
        # ranks least owed a seat (a long sat-out streak drives it negative and
        # protects the player). Same fairness rank the "Apply rotation hints" button
        # reads, computed here and carried through as one number per player, since
        # `player_loader.load_players_from_dict` sorts its input by uuid and would
        # otherwise discard any ordering placed on `lineup` itself. Left at every
        # player's default 0.0 (no map history yet), the trim falls back to whatever
        # order it always used.
        histories_by_member = {
            history.member_id: history for history in await self._rotation_histories(session, game, lineup)
        }
        members = await self.members(session, workspace_id, [row.workspace_member_id for row in lineup])
        resolved = await self.ranks.resolve(
            session,
            workspace_id=workspace_id,
            members={member_id: member.player_id for member_id, member in members.items()},
            roles=list(REGISTRATION_ROLE_CODES),
            # ``MIX_ORDER`` puts the host's own book above the workspace canon: a
            # mix balances on this host's read of these players, not the official one.
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await get_effective_division_grid(session, None),
        )
        explicit_roles = await self.player_roles.roles_for_players(
            session,
            [row.id for row in lineup if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT],
        )
        player_nodes: dict[str, Any] = {}
        for row in lineup:
            member = members[row.workspace_member_id]
            classes: dict[str, Any] = {}
            role_order = (
                explicit_roles.get(row.id, [])
                if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
                else REGISTRATION_ROLE_CODES
            )
            # An explicit empty list means no playable role; it never falls back.
            for priority, role in enumerate(role_order, start=1):
                ranked = resolved.get((member.member_id, role))
                if ranked is None or ranked.value is None:
                    continue
                classes[role] = {"isActive": True, "rank": ranked.value, "priority": priority}
            if not classes:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="missing_ranked_role")
            player_nodes[str(member.member_id)] = {
                "identity": {
                    "name": member.display_name or member.battle_tag or f"player-{member.member_id}",
                    "isFullFlex": row.is_flex,
                    "mustPlay": row.participation == MixParticipation.MUST_PLAY,
                    "rotationPriority": rotation_priority(histories_by_member[row.workspace_member_id]),
                },
                "stats": {"classes": classes},
            }
        # The HOST's row, not the acting co-host's, and read exactly once: the
        # ranks above are already resolved against the host's own book
        # (``MIX_ORDER`` + ``author_user_id=game.host_user_id``), so reading the
        # presser's preferences instead would make the same mix balance
        # differently depending on who clicked. The same row carries both the
        # solver overrides and the roster shape, so they come off one load.
        host_config = await self._host_config(session, game.host_user_id)
        role_mask = (await self._shape_for(session, workspace_id, host_config)).slots
        try:
            result = await self.run_balance(
                {"players": player_nodes},
                host_config.config_json if host_config is not None else None,
                _noop_progress,
                role_mask,
            )
        except ValueError as exc:
            # The solver raises plain ``ValueError`` for input problems it can
            # diagnose (uneven player count, short role coverage, ...). Left
            # uncaught it reaches the generic RPC handler, which cannot tell it
            # apart from a real bug and reports "internal error" -- hiding the
            # actual, actionable reason from the host.
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        lobby = await self._lobby(session, game, 0)
        lobby.balance_result_json = result
        # A fresh search renumbers every option, so whatever the host had paged
        # to describes nothing now -- back to the best one.
        lobby.selected_variant_index = 0
        lobby.balanced_at = datetime.now(UTC)
        _apply_balance_result(roster, result)
        game.status = MixStatus.BALANCED
        await session.flush()
        return game

    async def set_team_names(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        team_names: Mapping[str, Any],
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Patch the host's team-name overrides, one team at a time.

        Keyed by 0-based team index (the same position ``TeamColumn``/
        ``PickupResultControls`` render by) rather than by the solver's
        per-run ``team.id`` or captain, so a rename survives paging between
        balance options and re-running the solver -- both reshuffle rosters
        and captains but never the on-screen column order.

        Patch semantics, like ``update_player``: an index the caller does not
        mention is left exactly as it was, so renaming one team's column does
        not require resending every other team's current name. An index
        mentioned with an empty value clears back to the computed default.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        patch = _normalize_team_names(team_names)
        for index, value in patch.items():
            await self.team_names.set(session, game.id, int(index), value)
        await session.flush()
        return game

    async def set_next_map(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        map_id: int | None,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Name the map the next match is played on, or ``None`` to clear it.

        Rolled or hand-picked ahead of the lobby loading in; every viewer sees
        it through the same realtime refetch as any other mix write, and
        :meth:`record_outcome` stamps it on the recorded match and clears it.
        The roll itself lives client-side (the catalogue and this mix's match
        history are already there) -- this only stores the verdict.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if map_id is not None and await self.maps.get(session, map_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")
        lobby = await self._lobby(session, game, 0)
        lobby.next_map_id = map_id
        await session.flush()
        return game

    async def set_variant_index(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        variant_index: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Page the mix to one of its stored balance options -- for everybody.

        The option on screen is what the lobby is having read out to it, so it
        is a fact about the mix, not about the browser that happens to be
        looking: a host clicking through the options moves every viewer with
        them (same realtime signal as any other mix write), and a viewer who
        opens the page mid-session lands on the one being played, not on the
        first. Host-or-co-host only, like every other write here.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobby = await self._lobby(session, game, 0)
        result = as_lobby_document(lobby.balance_result_json)
        variants = result.get("variants") if isinstance(result, dict) else None
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        lobby.selected_variant_index = variant_index
        await session.flush()
        return game

    async def workspace_discord_channel_id(self, session: AsyncSession, workspace_id: int) -> int | None:
        """The workspace-wide mix channel: the ONLY channel a mix ever posts to.

        Kept in the workspace balancer config blob
        (``balancer.workspace_config.config_json``) next to the other
        workspace-scoped mix knobs, as digits in a string -- JSON has one
        number type and a snowflake does not survive a float64 round-trip.
        """
        raw = await session.scalar(
            sa.select(models.WorkspaceBalancerConfig.config_json).where(
                models.WorkspaceBalancerConfig.workspace_id == workspace_id
            )
        )
        value = raw.get("mix_discord_channel_id") if isinstance(raw, dict) else None
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            # A hand-edited config blob is not worth a 500 on every mix read;
            # the workspace simply has no default until an admin re-saves it.
            return None

    async def discord_lineup(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        variant_index: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        """The channel to post to plus the embed describing one balance option.

        The message is built here rather than by the bot: team names, seat names
        and balance-time ratings all live in this service's tables and the bot
        has no database of its own. Publishing is the RPC layer's job -- that is
        where the broker is -- so this returns the payload instead of sending it.

        Whichever option is on screen (``variant_index``), same as
        :meth:`swap_seats`: a host who paged to option 2 is posting that one.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        # The workspace's channel, full stop. A mix used to be able to name its
        # own, which meant an admin-only per-lobby override of the workspace's
        # Discord that nobody could see from the workspace settings that
        # nominally owned it; the workspace-wide setting is the one place it is
        # configured and the one place it is read.
        channel_id = await self.workspace_discord_channel_id(session, workspace_id)
        if channel_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Discord channel not configured")
        lobby = await self._lobby(session, game, 0)
        result = as_lobby_document(lobby.balance_result_json)
        variants = result.get("variants") if isinstance(result, dict) else None
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        variant = variants[variant_index]
        if not isinstance(variant, Mapping):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")

        team_names = await self.team_names.mapping_for_game(session, game.id)
        activity = await self.casual_matches.activity_for_games(session, [game.id])
        matches_count = activity.get(game.id, (0, None))[0]
        next_map: tuple[str, str | None] | None = None
        if lobby.next_map_id is not None:
            # The gamemode is eager-loaded: an async session raises on an
            # unawaited lazy load, and the embed names the mode next to the map.
            row = await session.scalar(
                sa.select(models.Map)
                .options(selectinload(models.Map.gamemode))
                .where(models.Map.id == lobby.next_map_id)
            )
            if row is not None:
                next_map = (row.name, row.gamemode.name if row.gamemode is not None else None)

        embed = build_lineup_embed(
            mix_name=game.name,
            match_number=matches_count + 1,
            variant=variant,
            players=_lobby_players(result),
            team_names=team_names,
            next_map=next_map,
            # The host's knob, resolved: the footer promises what recording this
            # match will actually move. ``0`` is "off", and off prints nothing.
            points_per_win=await self.host_points_per_win(session, game.host_user_id) or None,
        )
        return channel_id, embed

    async def transfer_host(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        new_host_user_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Transfer primary ownership to a signed-in member of this workspace."""
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if new_host_user_id == game.host_user_id:
            return game
        if new_host_user_id not in await self.load_member_user_ids(
            session,
            workspace_id=workspace_id,
            user_ids=[new_host_user_id],
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
        game.host_user_id = new_host_user_id
        # Nobody is simultaneously the primary host and a co-host of themselves.
        await self.co_hosts.remove(session, game.id, new_host_user_id)
        return game

    async def add_co_host(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        co_host_user_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Grant a signed-in workspace member co-host write access."""
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if co_host_user_id == game.host_user_id:
            return game
        if co_host_user_id not in await self.load_member_user_ids(
            session,
            workspace_id=workspace_id,
            user_ids=[co_host_user_id],
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
        current = await self.co_hosts.user_ids_for_game(session, game.id)
        if co_host_user_id in current:
            return game
        if len(current) >= _MAX_CO_HOSTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"A mix can have at most {_MAX_CO_HOSTS} co-hosts",
            )
        await self.co_hosts.add(session, game.id, co_host_user_id)
        return game

    async def remove_co_host(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        co_host_user_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Revoke co-host access, including a co-host removing themselves."""
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        # No membership check on the way out: an account that has since left the
        # workspace must still be revocable, or its grant is stranded forever.
        if co_host_user_id not in await self.co_hosts.user_ids_for_game(session, game.id):
            return game
        await self.co_hosts.remove(session, game.id, co_host_user_id)
        return game

    async def swap_seats(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        variant_index: int,
        first_uuid: str,
        second_uuid: str,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Swap two seated players between teams, same role only.

        A same-role swap can never break a team's role quota (1 tank / 2 damage /
        2 support stays exactly that on both sides), so it needs no eligibility
        check beyond "both seats exist and share a role" -- unlike a free move,
        which would need to know every role a player is *ranked* for, not just
        the one this balance happened to seat them in.

        Edits whichever balance option is on screen (``variant_index``), not
        only the first: a host who paged to option 2 and likes it otherwise is
        adjusting that one, not silently rewriting option 1.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobby = await self._lobby(session, game, 0)
        result = copy.deepcopy(as_lobby_document(lobby.balance_result_json))
        variants = result.get("variants") if isinstance(result, dict) else None
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        variant = variants[variant_index]
        teams = variant.get("teams") if isinstance(variant, dict) else None
        if not isinstance(teams, list):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")

        first = _locate_seat(teams, first_uuid)
        second = _locate_seat(teams, second_uuid)
        if first is None or second is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not seated in this option")
        first_team, first_role, first_pos = first
        second_team, second_role, second_pos = second
        if first_role != second_role:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Can only swap two seats in the same role",
            )
        if first_team == second_team:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Both seats are already on the same team",
            )

        first_bucket = teams[first_team]["roster"][first_role]
        second_bucket = teams[second_team]["roster"][second_role]
        first_bucket[first_pos], second_bucket[second_pos] = second_bucket[second_pos], first_bucket[first_pos]
        _recompute_variant_stats(variant, _lobby_players(result))

        lobby.balance_result_json = result
        await session.flush()
        return game

    async def _apply_points_delta(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        host_user_id: int,
        team_players: Sequence[tuple[int, str, int]],
        delta: int,
    ) -> None:
        """Bump the host's own rank book by ``delta`` for one team's seats.

        Reads the *current* author-layer value rather than each seat's
        balance-time ``rank`` snapshot, so a second match recorded the same
        night compounds on top of the first instead of re-applying from a
        stale baseline. A player with no author-layer entry yet (should not
        normally happen -- ``_seed_host_ranks`` seeds one on join) falls back
        to their balance-time rating instead of silently dropping the write.
        """
        if delta == 0 or not team_players:
            return
        member_ids = [member_id for member_id, _role, _fallback in team_players]
        current = await self.ranks.list_layer(
            session, workspace_id=workspace_id, member_ids=member_ids, author_user_id=host_user_id
        )
        for member_id, role, fallback in team_players:
            base = current.get((member_id, role), fallback)
            await self.ranks.set_ranks(
                session,
                workspace_id=workspace_id,
                workspace_member_id=member_id,
                ranks={role: base + delta},
                author_user_id=host_user_id,
            )

    async def record_outcome(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        winner: int | None,
        variant_index: int,
        map_id: int | None = None,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Freeze one played match into ``casual.match`` and its two scored sides.

        Repeatable -- a mix records many matches before its host calls
        :meth:`close`, and the frozen snapshot is the only record of each: the
        mix itself keeps no mutable copy of "the last result".

        The HOST's ``points_per_win`` (when set, and only for a decided match)
        moves both teams' host-authored ranks, and every seat that actually
        played redeems its ``MUST_PLAY`` pin back to ``POOL`` -- the pin promises
        one guaranteed seat, not every seat forever.

        ``map_id`` names the map explicitly; omitted, the match takes the lobby's
        ``next_map_id`` (see :meth:`set_next_map`), which is cleared either way
        so the following match starts with a fresh roll.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if winner not in (1, 2, None):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="winner must be 1, 2 or null")
        lobby = await self._lobby(session, game, 0)
        if map_id is None:
            map_id = lobby.next_map_id
        elif await self.maps.get(session, map_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

        result = as_lobby_document(lobby.balance_result_json) or {}
        variants = result.get("variants")
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        variant = variants[variant_index] if isinstance(variants[variant_index], dict) else {}
        teams = variant.get("teams")
        if not isinstance(teams, list) or len(teams) != 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A match can only be recorded for a two-team balance",
            )

        names = await self.team_names.mapping_for_game(session, game.id)
        scores = (1, 0) if winner == 1 else (0, 1) if winner == 2 else (0, 0)
        # The host's knob, not the mix's and not the recording co-host's -- the
        # book being moved is the host's own (see ``_apply_points_delta``).
        points_per_win = await self.host_points_per_win(session, game.host_user_id)
        match = models.CasualMatch(
            custom_game_id=game.id,
            map_id=map_id,
            recorded_by=actor_user_id,
            # Frozen on the match so :meth:`undo_last_match` rolls back what was
            # actually applied, not what the knob says by then.
            points_per_win_applied=(points_per_win if (points_per_win and winner in (1, 2)) else None),
        )
        await self.casual_matches.create(session, match)
        casual_teams = [
            models.CasualTeam(
                match_id=match.id,
                side=side,
                name=names.get(index) or f"Team {index + 1}",
                score=scores[index],
            )
            for index, side in enumerate((CasualTeamSide.HOME, CasualTeamSide.AWAY))
        ]
        await self.casual_teams.create_many(session, casual_teams)

        # Per-team (member_id, role_slot_code, balance-time rating) seats,
        # collected alongside the frozen snapshot so the points delta reuses the
        # exact same walk instead of re-parsing ``teams``.
        team_players: list[list[tuple[int, str, int]]] = [[], []]
        players = _lobby_players(result)
        for team_index, (team, casual_team) in enumerate(zip(teams, casual_teams, strict=True)):
            roster = team.get("roster") if isinstance(team, dict) else None
            if not isinstance(roster, dict):
                continue
            for bucket_name, seats in roster.items():
                if not isinstance(seats, list):
                    continue
                slot_code = role_slot_code(bucket_name)
                role = HeroClass.from_slot_code(slot_code)
                for uuid in seats:
                    player = players.get(str(uuid))
                    if not isinstance(player, Mapping):
                        continue
                    member_id = int(uuid)
                    rating = int(seat_rating(player, bucket_name))
                    await self.casual_players.create(
                        session,
                        models.CasualPlayer(
                            team_id=casual_team.id,
                            workspace_member_id=member_id,
                            # The name as it stood when the match was played --
                            # a later rename or a member leaving the workspace
                            # must not rewrite history.
                            display_name_snapshot=str(player.get("name") or f"#{member_id}"),
                            role=role,
                            rank=rating,
                        ),
                    )
                    team_players[team_index].append((member_id, slot_code, rating))

        participant_ids = {member_id for team in team_players for member_id, _, _ in team}
        if participant_ids:
            for row in await self.roster.list_for_game(session, game.id):
                if row.participation == MixParticipation.MUST_PLAY and row.workspace_member_id in participant_ids:
                    row.participation = MixParticipation.POOL

        if points_per_win and winner in (1, 2) and game.host_user_id is not None:
            winning_index = 0 if winner == 1 else 1
            await self._apply_points_delta(
                session,
                workspace_id=workspace_id,
                host_user_id=game.host_user_id,
                team_players=team_players[winning_index],
                delta=points_per_win,
            )
            await self._apply_points_delta(
                session,
                workspace_id=workspace_id,
                host_user_id=game.host_user_id,
                team_players=team_players[1 - winning_index],
                delta=-points_per_win,
            )

        lobby.next_map_id = None

        await session.flush()
        return game

    async def undo_last_match(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        match_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Delete the mix's most recent match and give back the ranks it moved.

        Newest-only on purpose: the rank book compounds match on match (see
        :meth:`_apply_points_delta`), so undoing an older result would give back
        a delta that later matches have already built on and leave every number
        after it wrong. Recording the correct result again is the way to fix an
        older mistake.

        The rollback uses ``points_per_win_applied`` frozen on the match, never
        the host's current ``points_per_win``: the host may have changed the knob
        (or turned it off) since, and the point is to return the book to exactly
        where it stood.

        What is *not* reverted: the ``MUST_PLAY`` pins that recording redeemed
        back to ``POOL``. A pin promises one seat, that seat was played, and
        re-pinning everybody would silently re-queue players the host has since
        moved on from -- rotation is the host's call, not an undo side effect.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        match = await self.casual_matches.get_for_game(session, game.id, match_id)
        if match is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
        if await self.casual_matches.newest_id_for_game(session, game.id) != match.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only the most recent match can be undone")

        applied = match.points_per_win_applied or 0
        if applied and game.host_user_id is not None:
            sides = {team.side: team for team in match.teams}
            home = sides.get(CasualTeamSide.HOME)
            away = sides.get(CasualTeamSide.AWAY)
            home_score = home.score if home is not None else 0
            away_score = away.score if away is not None else 0
            # The frozen seats carry the canonical role (``HeroClass``); the rank
            # book is keyed by its wire spelling, the same ``slot_code``
            # ``record_outcome`` mapped forward from.
            winner_team, loser_team = (home, away) if home_score > away_score else (away, home)
            for team, delta in ((winner_team, -applied), (loser_team, applied)):
                if team is None:
                    continue
                await self._apply_points_delta(
                    session,
                    workspace_id=workspace_id,
                    host_user_id=game.host_user_id,
                    team_players=[
                        (seat.workspace_member_id, seat.role.slot_code, seat.rank)
                        for seat in team.players
                        if seat.workspace_member_id is not None and seat.role is not None
                    ],
                    delta=delta,
                )

        # Teams and seats go with it: both hang off the match by ``ON DELETE
        # CASCADE``, so there is nothing left to clean up by hand.
        await self.casual_matches.delete(session, match)
        return game

    async def list_matches(
        self, session: AsyncSession, *, workspace_id: int, custom_game_id: int
    ) -> list[models.CasualMatch]:
        """Every match recorded for this mix, newest first -- read is open to
        any workspace member, same as :meth:`get` (no host gate: watching the
        history is not writing it).
        """
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        return list(await self.casual_matches.list_for_custom_game(session, game.id))

    async def mix_stats(
        self, session: AsyncSession, *, workspace_id: int, since: datetime | None
    ) -> list[dict[str, Any]]:
        """Per-member win/loss record across every mix this workspace ever ran.

        Workspace-wide on purpose: the scoreboard answers "how does this person
        do in our mixes", which no single game can say. Names come from the
        *current* roster, so a member who has since left keeps their record and
        loses only their label -- the seats still carry their member id.
        """
        rows = await self.casual_matches.seats_for_workspace(session, workspace_id, since)
        seats = [
            SeatOutcome(
                member_id=row.workspace_member_id,
                # The frozen seat carries the canonical role (``HeroClass``);
                # the wire spells it the way ``record_outcome`` mapped it in.
                role=row.role.slot_code if row.role is not None else None,
                match_id=row.match_id,
                played_at=row.created_at,
                outcome=outcome_for(row.own_score, row.other_score),
            )
            for row in rows
        ]
        stats = aggregate_mix_stats(seats)
        if not stats:
            return []

        members = await self.load_roster(
            session, workspace_id=workspace_id, member_ids=[entry.member_id for entry in stats]
        )
        return [
            {
                "workspace_member_id": entry.member_id,
                "display_name": member.display_name if member is not None else None,
                "battle_tag": member.battle_tag if member is not None else None,
                "games": entry.games,
                "wins": entry.wins,
                "losses": entry.losses,
                "draws": entry.draws,
                "win_rate": entry.win_rate,
                "streak": entry.streak,
                "last_played_at": entry.last_played_at.isoformat() if entry.last_played_at is not None else None,
                "by_role": {
                    role: {"games": tally.games, "wins": tally.wins, "losses": tally.losses, "draws": tally.draws}
                    for role, tally in entry.by_role.items()
                },
            }
            for entry, member in ((entry, members.get(entry.member_id)) for entry in stats)
        ]

    async def _rotation_histories(
        self, session: AsyncSession, game: models.CustomGame, roster: Sequence[models.CustomGamePlayer]
    ) -> list[PlayerHistory]:
        """One `PlayerHistory` per given roster row, from every map this mix recorded.

        Shared by :meth:`rotation` (ranks the whole pool for the host's hint) and
        :meth:`balance` (ranks the active lineup, so ``run_balance``'s own
        overflow trim benches the least-owed player first).
        """
        matches = list(await self.casual_matches.list_for_custom_game(session, game.id))
        matches.reverse()  # newest-first -> chronological, oldest map first
        participants = [
            {seat.workspace_member_id for team in match.teams for seat in team.players} for match in matches
        ]
        return [
            PlayerHistory(
                member_id=row.workspace_member_id,
                # Only maps recorded after this row joined the pool count --
                # a map played before they signed up is not one they sat out.
                played=tuple(
                    row.workspace_member_id in played
                    for match, played in zip(matches, participants, strict=True)
                    if row.created_at is None or match.created_at >= row.created_at
                ),
                pinned_must_play=row.participation == MixParticipation.MUST_PLAY,
            )
            for row in roster
        ]

    async def rotation(
        self, session: AsyncSession, *, workspace_id: int, custom_game_id: int
    ) -> list[RotationRecommendation]:
        """Recommend who is owed the next seat and who should sit, from this mix's own map history.

        Ranks the whole pool -- bench included, a benched player can still be
        "owed" a seat -- by :func:`recommend_rotation` against every map
        recorded via :meth:`record_outcome` for this game, then splits it at
        the same seat count :meth:`balance` would fill for the current pool
        size. A row's own ``MUST_PLAY`` participation (see :meth:`update_player`)
        is honoured the same way it is honoured there: a seat, not a vote.

        Read-only, no roster row is touched -- the host applies the verdict
        through the same ``participation`` field.
        """
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        roster = list(await self.roster.list_for_game(session, game.id))
        if not roster:
            return []

        histories = await self._rotation_histories(session, game, roster)

        role_mask = (await self.roster_shape(session, workspace_id=workspace_id, host_user_id=game.host_user_id)).slots
        players_per_team = sum(role_mask.values())
        usable_count = len(roster) if players_per_team <= 0 else (len(roster) // players_per_team) * players_per_team
        return recommend_rotation(histories, usable_count=usable_count)

    async def close(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Ends the mix. No result of its own -- matches already recorded via
        ``record_outcome`` stay recorded; this only stops further writes.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        game.status = MixStatus.COMPLETED
        await session.flush()
        return game

    async def cancel(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        game.status = MixStatus.CANCELLED
        await session.flush()
        return game

    async def hard_delete(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
    ) -> None:
        """Permanently removes the mix and every row it owns.

        Unlike :meth:`cancel` (a status flip a host can undo by starting over)
        this is irreversible, so the RPC layer gates it on workspace admin
        rather than host-or-co-host -- see ``rpc.balancer.custom.hard_delete``.
        ``custom_game_player`` and ``casual_match`` both cascade on
        ``custom_game_id`` at the DB level, so deleting the game row is enough.
        """
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        await self.games.delete(session, game)


custom_game_service = CustomGameService()
