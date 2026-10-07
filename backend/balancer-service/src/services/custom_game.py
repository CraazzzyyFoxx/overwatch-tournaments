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
    MixRatingMode,
    MixRoleSelectionMode,
    MixSelfSignup,
    MixStatus,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider
from shared.division_grid import DEFAULT_GRID
from shared.domain.mix_lobby import LOBBY_LETTERS
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
from shared.repository.discord_message import LIVE_STATUSES
from shared.repository.workspace import get_or_create_workspace_member
from shared.schemas.events import DiscordCard, DiscordCommandEvent
from shared.schemas.roster_slots import RosterShapeRead
from shared.services import discord_messages
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
from src.domain.mix_discord import SignupPlayer, lineup_card, signup_card
from src.domain.mix_lobbies import seated_member_ids
from src.domain.mix_lobby_split import LobbySplitError, SplitCandidate, split_into_lobbies
from src.domain.mix_ranker import Ranker
from src.domain.mix_rotation import PlayerHistory, RotationRecommendation, recommend_rotation, rotation_priority
from src.domain.mix_self_service import MixSelfPolicy, mix_self_policy
from src.domain.mix_stats import SeatOutcome, aggregate_mix_stats, outcome_for
from src.services.balancer.role_naming import role_slot_code
from src.services.balancer.solver import run_mix_balance as _run_balance
from src.services.mix_ranker import MixRankerService, RatedSeat, mix_ranker_service
from src.services.pickup_mix_realtime import emit_pickup_mix_changed

__all__ = ("SIGNUP_SLOT", "CustomGameService", "custom_game_service", "mix_subject")

_TERMINAL = frozenset({MixStatus.COMPLETED, MixStatus.CANCELLED})
#: Plenty for any pickup mix (2-3 teams in practice); guards against a
#: malformed payload turning into an unbounded dict.
_MAX_TEAMS = 8
#: Plenty for any pickup mix; guards a malformed payload from growing the
#: co-host list without bound.
_MAX_CO_HOSTS = 16
_MAX_TEAM_NAME_LEN = 60
#: Every Discord message a mix sends is filed under this subject, and the slot
#: says which of the mix's messages it is: one ``signup`` card plus one row per
#: lineup posted. Deleting a mix is then one read of ``discord_message``.
#: Public: the signup-card projector reads the same slot back.
SIGNUP_SLOT = "signup"
#: The file name a lineup PNG travels under, on both the card and the command.
_LINEUP_IMAGE = "lineup.png"
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


def mix_subject(custom_game_id: int) -> str:
    """The ``discord_message.subject`` every message of one mix is filed under.

    Read by the RPC layer too: the mix page lists its own Discord messages, and
    neither side should spell the string itself.
    """
    return f"mix:{custom_game_id}"


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


def _mix_channel_id(config_json: Any) -> int | None:
    """The mix channel out of a workspace balancer config blob.

    Stored as digits in a string -- JSON has one number type and a snowflake
    does not survive a float64 round-trip. A hand-edited blob is not worth a
    500 on every mix read: the workspace simply has no default until an admin
    re-saves it.
    """
    value = config_json.get("mix_discord_channel_id") if isinstance(config_json, dict) else None
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


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


def _uses_ranker(host_config: Any) -> bool:
    """Whether the host's mixes balance on, and move ranks by, the mix ranker."""
    return host_config is not None and host_config.rating_mode == MixRatingMode.RANKER


def _points_per_win(host_config: Any) -> int:
    """How far a decided match moves the host's book in points mode; 0 is "off" (and every ranker host)."""
    if host_config is None or _uses_ranker(host_config):
        return 0
    return host_config.points_per_win or 0


def _stamp_open_ratings(result: Mapping[str, Any], opens: Mapping[int, Mapping[str, int]]) -> None:
    """Keep each player's open rank next to the effective one the solver saw.

    Keyed by the same role buckets as ``ratings`` so a reader resolves both the
    same way; the lineup shows the pair, ``record_outcome`` moves the open one.
    """
    for uuid, player in _lobby_players(result).items():
        own = opens.get(int(uuid))
        ratings = player.get("ratings") if isinstance(player, dict) else None
        if own and isinstance(ratings, Mapping):
            player["open_ratings"] = {
                bucket: own[slot] for bucket in ratings if (slot := role_slot_code(bucket)) in own
            }


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
        ranker: MixRankerService | None = None,
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
        self.ranker = ranker if ranker is not None else mix_ranker_service

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
        ``set_lobby_count`` opens and drops the rest), so a miss is a caller
        naming a lobby the mix does not run, not a row to conjure up.
        """
        lobby = await self.lobbies.get(session, game.id, lobby_index)
        if lobby is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lobby_not_found")
        return lobby

    async def _other_lobby_seated(
        self, session: AsyncSession, game: models.CustomGame, lobby_index: int
    ) -> frozenset[int]:
        """Who the mix's OTHER lobbies currently have on the floor.

        Empty for a one-lobby mix: with no lobby next door, nobody is playing
        one. Membership is not stored -- it is the seats of each other lobby's
        selected option, which is what every caller here means by "busy".
        """
        if game.lobby_count < 2:
            return frozenset()
        busy: set[int] = set()
        for lobby in await self.lobbies.list_for_game(session, game.id):
            if lobby.lobby_index != lobby_index:
                busy |= seated_member_ids(lobby.balance_result_json, lobby.selected_variant_index)
        return frozenset(busy)

    async def _lobby_candidates(
        self,
        session: AsyncSession,
        game: models.CustomGame,
        rows: Sequence[models.CustomGamePlayer],
        lobby_index: int,
    ) -> list[models.CustomGamePlayer]:
        """The roster rows this lobby may seat, out of ``rows``.

        One rule, one place: whoever is on the floor next door is playing, and
        whoever is pinned to another lobby is not this one's to seat. A
        one-lobby mix owns its whole pool, so ``rows`` comes back untouched.
        """
        if game.lobby_count < 2:
            return list(rows)
        busy = await self._other_lobby_seated(session, game, lobby_index)
        return [row for row in rows if row.workspace_member_id not in busy and row.lobby_pin in (None, lobby_index)]

    async def _lobby_team_names(self, session: AsyncSession, game_id: int, lobby_index: int) -> dict[int, str]:
        """This lobby's two team-name overrides, renumbered to ``0``-``1``.

        Names are stored by GLOBAL index (``lobby_index * 2 + team``) because
        lobby B's two teams are two more rows of the same table; every reader
        wants them by position inside its own lobby's variant.
        """
        offset = lobby_index * 2
        return {
            index - offset: name
            for index, name in (await self.team_names.mapping_for_game(session, game_id)).items()
            if 0 <= index - offset < 2
        }

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
            pin = patch["lobby_pin"]
            if pin is not None and pin >= lobby_count:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"lobby_pin must name one of the mix's {lobby_count} lobbies",
                )
            row.lobby_pin = pin

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
        """Run this mix as one lobby or as several (up to ``MAX_LOBBIES``).

        Growing opens the missing lobbies empty: they have no matchup until
        somebody balances them, and the lobbies already running are not
        touched. Shrinking deletes every lobby past the new count -- their
        stored matchups are lost, their recorded matches stay in the history --
        and frees the pins that named them, because a pin to a lobby the mix no
        longer runs would quietly exclude that player from the next balance.
        Pins to surviving lobbies are kept.
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
        if lobby_count > game.lobby_count:
            for lobby_index in range(game.lobby_count, lobby_count):
                await self.lobbies.create(
                    session, models.CustomGameLobby(custom_game_id=game.id, lobby_index=lobby_index)
                )
        else:
            for lobby in await self.lobbies.list_for_game(session, game.id):
                if lobby.lobby_index >= lobby_count:
                    await self.lobbies.delete(session, lobby)
            for row in await self.roster.list_for_game(session, game.id):
                if row.lobby_pin is not None and row.lobby_pin >= lobby_count:
                    row.lobby_pin = None
        game.lobby_count = lobby_count
        await session.flush()
        return game

    async def rename(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        name: str,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Give the mix a new name; nothing else about it changes."""
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        game.name = name
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
        would make the bot guess. ``divisions`` is the same three roles read off
        the Overwatch ladder (``DEFAULT_GRID``: Bronze 5 .. Champion 1), the
        name and slug of the rank each value lands in -- the badges the bot
        ships as emoji. Not the platform grid: its tiers are bare numbers
        ("Division 1") that say nothing to a player reading Discord.
        ``unranked_roles`` is the narrower list the warning is built from -- the
        roles this player actually plays.

        ``current_lobby`` is the same derivation the board shows -- the seats of
        each lobby's selected option -- so nobody downstream re-parses a solver
        document to answer "which lobby am I in", and ``lobby_count`` is what
        tells them whether that question is worth asking at all.
        """
        seat: dict[str, Any] | None = None
        unranked: list[str] = []
        if ctx.row is not None:
            stored = (await self.player_roles.roles_for_players(session, [ctx.row.id])).get(ctx.row.id, [])
            explicit = ctx.row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
            grid = await get_effective_division_grid(session, None)
            resolved = await self.ranks.resolve(
                session,
                workspace_id=ctx.game.workspace_id,
                members={ctx.row.workspace_member_id: ctx.player.id if ctx.player is not None else None},
                roles=list(REGISTRATION_ROLE_CODES),
                order=MIX_ORDER,
                author_user_id=ctx.game.host_user_id,
                grid=grid,
            )
            ranks: dict[str, int | None] = {}
            divisions: dict[str, dict[str, str | None] | None] = {}
            for role in REGISTRATION_ROLE_CODES:
                rank = resolved.get((ctx.row.workspace_member_id, role))
                ranks[role] = rank.value if rank is not None else None
                tier = None if ranks[role] is None else DEFAULT_GRID.resolve_division(ranks[role])
                divisions[role] = None if tier is None else {"name": tier.name, "slug": tier.slug}
            considered = list(stored) if explicit else list(REGISTRATION_ROLE_CODES)
            unranked = [role for role in considered if ranks.get(role) is None]
            seat = {
                "participation": ctx.row.participation,
                # ``null`` means all_ranked: every role this player has a number
                # for plays, which is a different statement from an empty list.
                "roles": list(stored) if explicit else None,
                "is_flex": ctx.row.is_flex,
                "ranks": ranks,
                # The Overwatch rank each of those values lands in.
                "divisions": divisions,
                # 0 | 1 while a balance seats them, ``null`` while it does not.
                "current_lobby": next(
                    (
                        lobby.lobby_index
                        for lobby in await self.lobbies.list_for_game(session, ctx.game.id)
                        if ctx.row.workspace_member_id
                        in seated_member_ids(lobby.balance_result_json, lobby.selected_variant_index)
                    ),
                    None,
                ),
            }
        return {
            "custom_game_id": ctx.game.id,
            "name": ctx.game.name,
            "status": ctx.game.status,
            "self_signup": ctx.game.self_signup,
            "self_role_edit": ctx.game.self_role_edit,
            # Whether "you are in lobby A" is a sentence worth saying: a
            # one-lobby mix has nothing to distinguish.
            "lobby_count": ctx.game.lobby_count,
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

    async def self_current(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user: Any,
    ) -> dict[str, Any]:
        """The same answer as :meth:`self_state`, for whichever mix is live now.

        ``/mix`` in Discord names no id: a player typing it means "the mix we
        are running", which is the newest one that is neither completed nor
        cancelled. A workspace with nothing open is a 404, same as asking for a
        mix that does not exist -- the bot translates it into "no mix right now".

        ponytail: filters the workspace's mixes in Python (the list read the
        board already uses). A workspace with thousands of archived mixes would
        want the status in the WHERE clause.
        """
        game = next(
            (row for row in await self.games.list_for_workspace(session, workspace_id) if row.status not in _TERMINAL),
            None,
        )
        if game is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        return await self.self_state(session, custom_game_id=game.id, auth_user=auth_user, workspace_id=workspace_id)

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
        await emit_pickup_mix_changed(
            session,
            ctx.game.workspace_id,
            custom_game_id=ctx.game.id,
            change="roster",
            actor_user_id=auth_user.id,
        )
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
        await emit_pickup_mix_changed(
            session,
            ctx.game.workspace_id,
            custom_game_id=ctx.game.id,
            change="roster",
            actor_user_id=auth_user.id,
        )
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
        await emit_pickup_mix_changed(
            session,
            ctx.game.workspace_id,
            custom_game_id=ctx.game.id,
            change="roster",
            actor_user_id=auth_user.id,
        )
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

    @staticmethod
    def _board_url(board_url_base: str, custom_game_id: int) -> str:
        return f"{board_url_base.rstrip('/')}/balancer/mix/{custom_game_id}"

    async def signup_card_for(
        self, session: AsyncSession, game: models.CustomGame, *, board_url_base: str
    ) -> DiscordCard:
        """The signup card as the mix stands right now.

        Rebuilt from current state on every publish rather than kept anywhere:
        the card is the mix's roster seen from a channel, and the roster is the
        only copy of it. Names resolve exactly as the balancer resolves them.
        Public because the projector (:mod:`src.services.mix_signup_projector`)
        renders the same card for the same mix on every change event.
        """
        roster = list(await self.roster.list_for_game(session, game.id))
        stored = await self.player_roles.roles_for_players(session, [row.id for row in roster])
        members = await self.load_roster(
            session, workspace_id=game.workspace_id, member_ids=[row.workspace_member_id for row in roster]
        )
        host_names = await self.hosts(session, game.workspace_id, [game.host_user_id])
        # The numbers the balancer will balance them at: the host's own book
        # above the workspace canon (``MIX_ORDER``), as in ``balance``.
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            members={member.member_id: member.player_id for member in members.values()},
            roles=list(REGISTRATION_ROLE_CODES),
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await get_effective_division_grid(session, None),
        )
        players = []
        for row in roster:
            member_id = row.workspace_member_id
            member = members.get(member_id)
            name = (member.display_name or member.battle_tag) if member else None
            roles = stored.get(row.id, []) if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT else None
            ranks = {
                role: found.value
                for role in REGISTRATION_ROLE_CODES
                if (found := resolved.get((member_id, role))) is not None and found.value is not None
            }
            # The first role they named, or -- playing anything -- their best.
            # An explicit empty order plays nothing, so it shows no rank.
            if roles is None:
                rank = max(ranks.values(), default=None)
            else:
                rank = ranks.get(roles[0]) if roles else None
            players.append(
                SignupPlayer(
                    name=name or f"player-{member_id}",
                    roles=roles,
                    benched=row.participation == MixParticipation.BENCHED,
                    rank=rank,
                )
            )
        return signup_card(
            mix_name=game.name,
            host_name=host_names.get(game.host_user_id),
            board_url=self._board_url(board_url_base, game.id),
            custom_game_id=game.id,
            self_signup=game.self_signup,
            status=game.status,
            lobby_count=game.lobby_count,
            players=players,
            updated_at=datetime.now(UTC),
        )

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
    ) -> tuple[int, list[DiscordCommandEvent]]:
        """Open signup, retire the previous card and claim the one that replaces it.

        The mode is written HERE rather than left to a separate call: a card in
        the channel whose buttons answer ``signup_closed`` is the one outcome
        nobody wants, and the column -- not the card -- is what admits a player.

        A mix has ONE signup card: a second one would count a roster nobody
        updates any more, so every live ``signup`` message of this mix is marked
        for deletion in the same transaction that claims the new one. Queueing
        is the RPC layer's job (it owns the transaction), so this returns the
        commands in the order they must reach the outbox -- the deletes first,
        so the channel never holds two cards at once.
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
        card = await self.signup_card_for(session, game, board_url_base=board_url_base)
        await session.flush()
        subject = mix_subject(game.id)
        commands = await discord_messages.delete_commands(
            session,
            await discord_messages.repository.for_subject(session, subject, slot=SIGNUP_SLOT, statuses=LIVE_STATUSES),
        )
        posted = await discord_messages.send_command(
            session,
            subject=subject,
            slot=SIGNUP_SLOT,
            kind="mix.signup",
            card=card,
            workspace_id=workspace_id,
            channel_id=channel_id,
        )
        if posted is not None:
            commands.append(posted)
        return channel_id, commands

    async def delete_discord_post(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        post_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> tuple[models.CustomGame, list[DiscordCommandEvent]]:
        """Take one of this mix's Discord messages down, by its row.

        ``discord_message`` is one table for the whole platform, so the row has
        to carry this mix's subject: an id belonging to another mix -- or to a
        notification -- is a 404 here rather than a message this host gets to
        delete. Clicking twice is harmless: a row already on its way out yields
        no command.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        row = await discord_messages.repository.get(session, post_id)
        if row is None or row.subject != mix_subject(game.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discord post not found")
        commands = await discord_messages.delete_commands(session, [row])
        await session.flush()
        return game, commands

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
        """How far a decided match moves this host's rank book; 0 means "not at all" (or the ranker moves it)."""
        return _points_per_win(await self._host_config(session, host_user_id))

    async def _lineup_nodes(
        self,
        session: AsyncSession,
        *,
        game: models.CustomGame,
        lineup: Sequence[models.CustomGamePlayer],
        host_config: Any,
    ) -> tuple[dict[str, Any], list[SplitCandidate], dict[int, dict[str, int]]]:
        """The solver's input for these roster rows plus the same facts for the splitter.

        Split out of ``balance`` because one mix is now solved lobby by lobby:
        each lobby feeds in its own set of rows and reads them the same way. One
        pass over one set of reads: the ranks, role order and rotation priority
        the solver wants are exactly what the two-lobby splitter weighs, so the
        two cannot drift apart (and ``member_rank`` is not read twice for one
        lineup).

        A ranker host's players are balanced on their effective rating (the
        open rank corrected by the hidden one); their open ranks come back
        keyed by member so the stored lineup can show both. Empty otherwise.
        """
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
        members = await self.members(session, game.workspace_id, [row.workspace_member_id for row in lineup])
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            members={member_id: member.player_id for member_id, member in members.items()},
            roles=list(REGISTRATION_ROLE_CODES),
            # ``MIX_ORDER`` puts the host's own book above the workspace canon: a
            # mix balances on this host's read of these players, not the official one.
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await get_effective_division_grid(session, None),
        )
        open_ranks = {
            key: ranked.value for key, ranked in resolved.items() if ranked is not None and ranked.value is not None
        }
        ranker = _uses_ranker(host_config)
        ranks = (
            await self.ranker.effective_ratings(session, workspace_id=game.workspace_id, open_ranks=open_ranks)
            if ranker
            else open_ranks
        )
        explicit_roles = await self.player_roles.roles_for_players(
            session,
            [row.id for row in lineup if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT],
        )
        player_nodes: dict[str, Any] = {}
        candidates: list[SplitCandidate] = []
        for row in lineup:
            member = members[row.workspace_member_id]
            classes: dict[str, Any] = {}
            explicit = row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
            role_order = explicit_roles.get(row.id, []) if explicit else REGISTRATION_ROLE_CODES
            # An explicit empty list means no playable role; it never falls back.
            for priority, role in enumerate(role_order, start=1):
                rank = ranks.get((member.member_id, role))
                if rank is None:
                    continue
                classes[role] = {"isActive": True, "rank": rank, "priority": priority}
            if not classes:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="missing_ranked_role")
            fairness = rotation_priority(histories_by_member[row.workspace_member_id])
            player_nodes[str(member.member_id)] = {
                "identity": {
                    "name": member.display_name or member.battle_tag or f"player-{member.member_id}",
                    "isFullFlex": row.is_flex,
                    "mustPlay": row.participation == MixParticipation.MUST_PLAY,
                    "rotationPriority": fairness,
                },
                "stats": {"classes": classes},
            }
            ratings = {role: entry["rank"] for role, entry in classes.items()}
            candidates.append(
                SplitCandidate(
                    member_id=member.member_id,
                    ratings=ratings,
                    # Which role the player is seated on first: ``classes`` is built
                    # in priority order, so the first entry is that one. All-ranked
                    # states no preference, hence its best rank.
                    strength=next(iter(ratings.values())) if explicit else max(ratings.values()),
                    pin=row.lobby_pin,
                    must_play=row.participation == MixParticipation.MUST_PLAY,
                    rotation_priority=fairness,
                )
            )
        opens: dict[int, dict[str, int]] = {}
        if ranker:
            for (member_id, role), rank in open_ranks.items():
                opens.setdefault(member_id, {})[role] = rank
        return player_nodes, candidates, opens

    async def _solve_lobby(
        self,
        session: AsyncSession,
        game: models.CustomGame,
        lobby: models.CustomGameLobby,
        lineup: Sequence[models.CustomGamePlayer],
    ) -> None:
        """Run the solver on exactly these players and store the run on this lobby."""
        # The HOST's row, not the acting co-host's, and read exactly once: the
        # ranks below are resolved against the host's own book
        # (``MIX_ORDER`` + ``author_user_id=game.host_user_id``), so reading the
        # presser's preferences instead would make the same mix balance
        # differently depending on who clicked. The same row carries the solver
        # overrides, the roster shape and the rating mode, so they come off one load.
        host_config = await self._host_config(session, game.host_user_id)
        player_nodes, _candidates, opens = await self._lineup_nodes(
            session, game=game, lineup=lineup, host_config=host_config
        )
        role_mask = (await self._shape_for(session, game.workspace_id, host_config)).slots
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
        if opens:
            _stamp_open_ratings(result, opens)
        lobby.balance_result_json = result
        # A fresh search renumbers every option, so whatever the host had paged
        # to describes nothing now -- back to the best one.
        lobby.selected_variant_index = 0
        lobby.balanced_at = datetime.now(UTC)

    async def balance(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        scope: str = "lobby",
        lobby_index: int = 0,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Rebuild the teams of ONE lobby (the default) or of every lobby at once.

        For a one-lobby mix ``scope="lobby"`` is today's behaviour whole: the
        non-benched pool minus whoever the other lobbies are already playing goes
        to the solver and lands in this lobby's document. ``scope="all"`` exists
        only for a mix running two lobbies or more: the pool is first cut into
        that many equally strong parts (``domain.mix_lobby_split``), then each
        part is solved by the same engine.
        """
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
        if scope == "all":
            await self._balance_all(session, game, lineup)
        else:
            lobby = await self._lobby(session, game, lobby_index)
            candidates = await self._lobby_candidates(session, game, lineup, lobby_index)
            if not candidates:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
            await self._solve_lobby(session, game, lobby, candidates)
            # Benching the overflow is the one-lobby answer. With more lobbies the
            # players left out WAIT for the next one (§Derived state), and a
            # BENCHED row would drop out of its candidate pool too.
            if game.lobby_count < 2:
                _apply_balance_result(roster, lobby.balance_result_json)
        game.status = MixStatus.BALANCED
        await session.flush()
        return game

    async def _balance_all(
        self,
        session: AsyncSession,
        game: models.CustomGame,
        lineup: Sequence[models.CustomGamePlayer],
    ) -> None:
        """Cut the pool into ``lobby_count`` equal lobbies and solve each with its own run.

        The splitter hands back exactly ``seats`` players per lobby, so the
        engine's own trim inside each run is a no-op and whoever did not make it
        into a game stays in the pool waiting -- not one roster row is benched.
        """
        if game.lobby_count < 2:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="single_lobby")
        # ponytail: ranks, rotation histories and the host config are resolved once
        # per lobby on top of this run (``_solve_lobby`` builds its own nodes); pass
        # these nodes down instead if a reshuffle ever shows up as slow.
        host_config = await self._host_config(session, game.host_user_id)
        _player_nodes, candidates, _opens = await self._lineup_nodes(
            session, game=game, lineup=lineup, host_config=host_config
        )
        role_mask = (await self._shape_for(session, game.workspace_id, host_config)).slots
        try:
            split = split_into_lobbies(candidates, mask=role_mask, lobby_count=game.lobby_count)
        except LobbySplitError as exc:
            # The machine-readable reason (not_enough_players / too_many_must_play
            # / too_many_pinned / roles_infeasible): the UI shows it as text, not a trace.
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.code) from exc
        rows = {row.workspace_member_id: row for row in lineup}
        for lobby_index, member_ids in enumerate(split.lobbies):
            lobby = await self._lobby(session, game, lobby_index)
            await self._solve_lobby(session, game, lobby, [rows[member_id] for member_id in member_ids])

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
        lobby_index: int = 0,
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
        lobby = await self._lobby(session, game, lobby_index)
        lobby.next_map_id = map_id
        await session.flush()
        return game

    async def set_variant_index(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
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
        lobby = await self._lobby(session, game, lobby_index)
        result = as_lobby_document(lobby.balance_result_json)
        variants = result.get("variants") if isinstance(result, dict) else None
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        # An option that seats somebody the other lobby has already put on the
        # floor is not a matchup anyone can play; the host picks another or
        # re-balances. Cheaper and clearer than silently benching them.
        busy = await self._other_lobby_seated(session, game, lobby_index)
        if busy & seated_member_ids(lobby.balance_result_json, variant_index):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="seat_conflict")
        lobby.selected_variant_index = variant_index
        await session.flush()
        return game

    async def workspace_discord_target(self, session: AsyncSession, workspace_id: int) -> tuple[int | None, str | None]:
        """Where this workspace posts, and in which guild: ``(channel_id, guild_id)``.

        The guild is the workspace's own verified binding and is read here, in
        the same statement as the channel, rather than in a second round trip:
        the mix page needs the channel for its settings and the guild for the
        jump links of its Discord posts (Discord addresses a message by all
        three ids), so the single-mix read would otherwise ask twice.
        """
        row = (
            await session.execute(
                sa.select(models.WorkspaceBalancerConfig.config_json, models.Workspace.discord_guild_id)
                .select_from(models.Workspace)
                .outerjoin(
                    models.WorkspaceBalancerConfig,
                    models.WorkspaceBalancerConfig.workspace_id == models.Workspace.id,
                )
                .where(models.Workspace.id == workspace_id)
            )
        ).first()
        if row is None:
            return None, None
        raw, guild_id = row
        return _mix_channel_id(raw), guild_id

    async def workspace_discord_channel_id(self, session: AsyncSession, workspace_id: int) -> int | None:
        """The workspace-wide mix channel: the ONLY channel a mix ever posts to.

        Kept in the workspace balancer config blob
        (``balancer.workspace_config.config_json``) next to the other
        workspace-scoped mix knobs, as digits in a string -- JSON has one
        number type and a snowflake does not survive a float64 round-trip.
        """
        return _mix_channel_id(
            await session.scalar(
                sa.select(models.WorkspaceBalancerConfig.config_json).where(
                    models.WorkspaceBalancerConfig.workspace_id == workspace_id
                )
            )
        )

    async def discord_mentions(self, session: AsyncSession, member_ids: Sequence[int]) -> list[str]:
        """The Discord ids of those workspace members who linked an account.

        One batched read down the identity chain -- workspace member -> player
        -> auth user -> ``auth.oauth_connections`` -- rather than a lookup per
        seat. A member with no linked Discord simply does not ping; the lineup
        is not worth failing over somebody's unlinked account.
        """
        ids = _uniq(member_ids)
        if not ids:
            return []
        rows = (
            await session.execute(
                sa.select(models.WorkspaceMember.id, models.OAuthConnection.provider_user_id)
                .select_from(models.WorkspaceMember)
                .join(models.User, models.User.id == models.WorkspaceMember.player_id)
                .join(models.OAuthConnection, models.OAuthConnection.auth_user_id == models.User.auth_user_id)
                .where(
                    models.WorkspaceMember.id.in_(ids),
                    models.OAuthConnection.provider == SocialProvider.DISCORD,
                    models.OAuthConnection.provider_user_id.is_not(None),
                )
            )
        ).all()
        by_member = {member_id: str(discord_id) for member_id, discord_id in rows if discord_id}
        return [by_member[member_id] for member_id in ids if member_id in by_member]

    async def discord_lineup(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
        variant_index: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
        board_url_base: str,
        image_b64: str | None = None,
    ) -> tuple[int, list[DiscordCommandEvent]]:
        """The channel to post to plus the command that posts one balance option.

        The message is built here rather than by the bot: team names, seat names
        and balance-time ratings all live in this service's tables and the bot
        has no database of its own. The row it will become is claimed here too
        (``slot='lineup:<lobby>:<match>'``), so the mix page can show the post
        and the host can take it down again; publishing is the RPC layer's job
        -- that is where the broker is -- so this returns the command.

        ``image_b64`` is the host's own capture of the matchup card: the picture
        then IS the lineup and the card drops the per-team seat lists it would
        otherwise print.

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
        lobby = await self._lobby(session, game, lobby_index)
        result = as_lobby_document(lobby.balance_result_json)
        variants = result.get("variants") if isinstance(result, dict) else None
        if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
        variant = variants[variant_index]
        if not isinstance(variant, Mapping):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")

        team_names = await self._lobby_team_names(session, game.id, lobby_index)
        # Per lobby: two lobbies keep two paces, so "game 5" in one is not
        # "game 5" in the other.
        activity = await self.casual_matches.activity_for_lobbies(session, game.id)
        matches_count = activity.get(lobby_index, (0, None))[0]
        next_map: tuple[str, str | None] | None = None
        if lobby.next_map_id is not None:
            # The gamemode is eager-loaded: an async session raises on an
            # unawaited lazy load, and the card names the mode next to the map.
            row = await session.scalar(
                sa.select(models.Map)
                .options(selectinload(models.Map.gamemode))
                .where(models.Map.id == lobby.next_map_id)
            )
            if row is not None:
                next_map = (row.name, row.gamemode.name if row.gamemode is not None else None)

        card = lineup_card(
            mix_name=game.name,
            match_number=matches_count + 1,
            variant=variant,
            players=_lobby_players(result),
            team_names=team_names,
            next_map=next_map,
            # The host's knob, resolved: the card promises what recording this
            # match will actually move. ``0`` is "off", and off prints nothing.
            points_per_win=await self.host_points_per_win(session, game.host_user_id) or None,
            board_url=self._board_url(board_url_base, game.id),
            # Every lobby posts into the same channel, so a multi-lobby mix says
            # which one this lineup is; a one-lobby mix has nothing to qualify.
            lobby_label=LOBBY_LETTERS[lobby_index] if game.lobby_count > 1 else None,
            image_filename=_LINEUP_IMAGE if image_b64 else None,
            # Everyone this matchup seats, so the lobby hears about it.
            mentions=await self.discord_mentions(
                session, sorted(seated_member_ids(lobby.balance_result_json, variant_index))
            ),
        )
        command = await discord_messages.send_command(
            session,
            subject=mix_subject(game.id),
            # One row per lineup the mix posts: the lobby it belongs to and the
            # match it announces, which is what the page labels the post with.
            slot=f"lineup:{lobby_index}:{matches_count + 1}",
            kind="mix.lineup",
            card=card,
            workspace_id=workspace_id,
            channel_id=channel_id,
            image_b64=image_b64,
            image_filename=_LINEUP_IMAGE,
            # The card mentions the players it seats; a lineup nobody is pinged
            # by is a lineup half the lobby misses.
            allow_mentions=True,
        )
        return channel_id, [] if command is None else [command]

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
        lobby_index: int = 0,
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
        lobby = await self._lobby(session, game, lobby_index)
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

    async def _shift_host_ranks(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        host_user_id: int,
        shifts: Sequence[tuple[int, str, int, int]],
    ) -> None:
        """Move the host's own rank book by a per-seat delta.

        ``shifts`` are ``(member_id, role, fallback, delta)``. Reads the
        *current* author-layer value rather than each seat's balance-time
        ``rank`` snapshot, so a second match recorded the same night compounds
        on top of the first instead of re-applying from a stale baseline. A
        player with no author-layer entry yet (should not normally happen --
        ``_seed_host_ranks`` seeds one on join) falls back to ``fallback``
        instead of silently dropping the write.
        """
        shifts = [shift for shift in shifts if shift[3]]
        if not shifts:
            return
        current = await self.ranks.list_layer(
            session,
            workspace_id=workspace_id,
            member_ids=[member_id for member_id, *_rest in shifts],
            author_user_id=host_user_id,
        )
        for member_id, role, fallback, delta in shifts:
            base = current.get((member_id, role), fallback)
            await self.ranks.set_ranks(
                session,
                workspace_id=workspace_id,
                workspace_member_id=member_id,
                ranks={role: base + delta},
                author_user_id=host_user_id,
            )

    async def _move_by_ranker(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        host_user_id: int,
        ranker: Ranker,
        winner: int | None,
        seats: Sequence[Sequence[tuple[int, str, int, models.CasualPlayer, RatedSeat]]],
    ) -> None:
        """Move each seat's open rank in the host's book by the ranker's formula.

        ``seats`` per team: ``(member_id, role, open rank at balance time,
        frozen seat row, hidden before/after)``. The base is the book's current
        value, like the points path, and the applied delta is frozen on the seat
        so undo gives back exactly it.
        """
        current = await self.ranks.list_layer(
            session,
            workspace_id=workspace_id,
            member_ids=[seat[0] for team in seats for seat in team],
            author_user_id=host_user_id,
        )
        for team_index, team in enumerate(seats):
            outcome = 0 if winner is None else 1 if winner == team_index + 1 else -1
            for member_id, role, open_rank, row, (old, new) in team:
                base = current.get((member_id, role), open_rank)
                moved = round(base + ranker.open_delta(base, old, new, outcome))
                row.rank_delta_applied = moved - base
                if moved != base:
                    await self.ranks.set_ranks(
                        session,
                        workspace_id=workspace_id,
                        workspace_member_id=member_id,
                        ranks={role: moved},
                        author_user_id=host_user_id,
                    )

    async def record_outcome(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
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

        The HOST's rating mode decides how both teams' host-authored ranks
        move: ``points_per_win`` (when set, and only for a decided match) or
        the mix ranker, seat by seat. The workspace's hidden ratings advance
        either way. Every seat that actually played redeems its ``MUST_PLAY``
        pin back to ``POOL`` -- the pin promises one guaranteed seat, not every
        seat forever.

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
        lobby = await self._lobby(session, game, lobby_index)
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

        names = await self._lobby_team_names(session, game.id, lobby_index)
        scores = (1, 0) if winner == 1 else (0, 1) if winner == 2 else (0, 0)
        # The host's knobs, not the mix's and not the recording co-host's -- the
        # book being moved is the host's own (see ``_shift_host_ranks``).
        host_config = await self._host_config(session, game.host_user_id)
        points_per_win = _points_per_win(host_config)
        match = models.CasualMatch(
            custom_game_id=game.id,
            lobby_index=lobby_index,
            map_id=map_id,
            recorded_by=actor_user_id,
            # Frozen on the match so :meth:`undo_last_match` rolls back what was
            # actually applied, not what the knob says by then.
            points_per_win_applied=(points_per_win if (points_per_win and winner in (1, 2)) else None),
        )
        await self.casual_matches.create(session, match)
        # Whoever was on the floor next door neither played this match nor sat
        # it out; rotation must not read their absence as a rest.
        busy = await self._other_lobby_seated(session, game, lobby_index)
        if busy:
            await self.casual_matches.set_busy_players(session, match.id, sorted(busy))
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
        # collected alongside the frozen snapshot so the rank moves reuse the
        # exact same walk instead of re-parsing ``teams``. The open rank and the
        # frozen row ride along for the ranker, which moves each seat on its own.
        team_players: list[list[tuple[int, str, int]]] = [[], []]
        open_ranks: list[list[int]] = [[], []]
        seat_rows: list[list[models.CasualPlayer]] = [[], []]
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
                    row = models.CasualPlayer(
                        team_id=casual_team.id,
                        workspace_member_id=member_id,
                        # The name as it stood when the match was played --
                        # a later rename or a member leaving the workspace
                        # must not rewrite history.
                        display_name_snapshot=str(player.get("name") or f"#{member_id}"),
                        role=role,
                        rank=rating,
                    )
                    await self.casual_players.create(session, row)
                    team_players[team_index].append((member_id, slot_code, rating))
                    # A ranker lineup stored the open rank beside the effective
                    # one it balanced on; a points lineup only has the one.
                    opens = player.get("open_ratings")
                    open_ranks[team_index].append(
                        int(opens.get(bucket_name, rating)) if isinstance(opens, Mapping) else rating
                    )
                    seat_rows[team_index].append(row)

        participant_ids = {member_id for team in team_players for member_id, _, _ in team}
        if participant_ids:
            for row in await self.roster.list_for_game(session, game.id):
                if row.participation == MixParticipation.MUST_PLAY and row.workspace_member_id in participant_ids:
                    row.participation = MixParticipation.POOL

        ranker, rated = await self.ranker.rate_match(
            session, workspace_id=workspace_id, teams=team_players, winner=winner
        )
        if game.host_user_id is not None and _uses_ranker(host_config):
            await self._move_by_ranker(
                session,
                workspace_id=workspace_id,
                host_user_id=game.host_user_id,
                ranker=ranker,
                winner=winner,
                seats=[
                    [
                        (member_id, role, open_rank, row, hidden)
                        for (member_id, role, _rating), open_rank, row, hidden in zip(
                            team_players[index], open_ranks[index], seat_rows[index], rated[index], strict=True
                        )
                    ]
                    for index in range(2)
                ],
            )
        elif points_per_win and winner in (1, 2) and game.host_user_id is not None:
            winning_index = 0 if winner == 1 else 1
            await self._shift_host_ranks(
                session,
                workspace_id=workspace_id,
                host_user_id=game.host_user_id,
                shifts=[
                    (member_id, role, rating, points_per_win if index == winning_index else -points_per_win)
                    for index in range(2)
                    for member_id, role, rating in team_players[index]
                ],
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
        """Delete a lobby's most recent match and give back the ranks it moved.

        Newest-only on purpose: the rank book compounds match on match (see
        :meth:`_shift_host_ranks`), so undoing an older result would give back
        a delta that later matches have already built on and leave every number
        after it wrong. Recording the correct result again is the way to fix an
        older mistake. Newest *of the match's own lobby*: two lobbies record at
        two paces, and a host looking at lobby A must be able to take back A's
        last result while B has already put down a newer one.

        The rollback uses what was frozen at record time -- the match's
        ``points_per_win_applied`` or each seat's ``rank_delta_applied`` --
        never the host's current knobs: the host may have changed them (or the
        rating mode) since, and the point is to return the book to exactly
        where it stood. The workspace's hidden ratings are then rebuilt from the
        history that is left, since later matches may already have built on
        this one's.

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
        if await self.casual_matches.newest_id_for_lobby(session, game.id, match.lobby_index) != match.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Only the most recent match of this lobby can be undone"
            )

        shifts: list[tuple[int, str, int, int]] = []
        applied = match.points_per_win_applied or 0
        sides = {team.side: team for team in match.teams}
        home = sides.get(CasualTeamSide.HOME)
        away = sides.get(CasualTeamSide.AWAY)
        home_score = home.score if home is not None else 0
        away_score = away.score if away is not None else 0
        winner_team = home if home_score > away_score else away
        for team in (home, away):
            if team is None:
                continue
            points_back = (-applied if team is winner_team else applied) if applied else 0
            # The frozen seats carry the canonical role (``HeroClass``); the rank
            # book is keyed by its wire spelling, the same ``slot_code``
            # ``record_outcome`` mapped forward from.
            shifts.extend(
                (seat.workspace_member_id, seat.role.slot_code, seat.rank, points_back - (seat.rank_delta_applied or 0))
                for seat in team.players
                if seat.workspace_member_id is not None and seat.role is not None
            )
        if game.host_user_id is not None:
            await self._shift_host_ranks(
                session, workspace_id=workspace_id, host_user_id=game.host_user_id, shifts=shifts
            )

        # Teams and seats go with it: both hang off the match by ``ON DELETE
        # CASCADE``, so there is nothing left to clean up by hand.
        await self.casual_matches.delete(session, match)
        await session.flush()
        await self.ranker.rebuild(session, game.workspace_id)
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

        A map the member spent in the mix's OTHER lobby drops out of their
        history entirely: it is neither a game they played nor one they sat out,
        and counting it as a rest would let somebody who has been playing
        non-stop next door outrank the people actually waiting. Empty for every
        one-lobby mix, which is why the verdict there is unchanged.
        """
        matches = list(await self.casual_matches.list_for_custom_game(session, game.id))
        matches.reverse()  # newest-first -> chronological, oldest map first
        participants = [
            {seat.workspace_member_id for team in match.teams for seat in team.players} for match in matches
        ]
        busy = [{row.workspace_member_id for row in match.busy_players} for match in matches]
        return [
            PlayerHistory(
                member_id=row.workspace_member_id,
                # Only maps recorded after this row joined the pool count --
                # a map played before they signed up is not one they sat out.
                played=tuple(
                    row.workspace_member_id in played
                    for match, played, elsewhere in zip(matches, participants, busy, strict=True)
                    if (row.created_at is None or match.created_at >= row.created_at)
                    and row.workspace_member_id not in elsewhere
                ),
                pinned_must_play=row.participation == MixParticipation.MUST_PLAY,
            )
            for row in roster
        ]

    async def rotation(
        self, session: AsyncSession, *, workspace_id: int, custom_game_id: int, lobby_index: int = 0
    ) -> list[RotationRecommendation]:
        """Recommend who is owed the next seat and who should sit, from this mix's own map history.

        Ranks the whole pool -- bench included, a benched player can still be
        "owed" a seat -- by :func:`recommend_rotation` against every map
        recorded via :meth:`record_outcome` for this game, then splits it at
        the same seat count :meth:`balance` would fill for the current pool
        size. A row's own ``MUST_PLAY`` participation (see :meth:`update_player`)
        is honoured the same way it is honoured there: a seat, not a vote.

        Per lobby when the mix runs two: ``lobby_index`` ranks the candidates
        that lobby may seat (see :meth:`_lobby_candidates`) and splits at that
        lobby's own seat count, not at the whole pool's.

        Read-only, no roster row is touched -- the host applies the verdict
        through the same ``participation`` field.
        """
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        roster = list(await self.roster.list_for_game(session, game.id))
        if not roster:
            return []

        candidates = await self._lobby_candidates(session, game, roster, lobby_index)
        if not candidates:
            return []

        histories = await self._rotation_histories(session, game, candidates)

        role_mask = (await self.roster_shape(session, workspace_id=workspace_id, host_user_id=game.host_user_id)).slots
        players_per_team = sum(role_mask.values())
        if players_per_team <= 0:
            usable_count = len(candidates)
        else:
            usable_count = (len(candidates) // players_per_team) * players_per_team
            if game.lobby_count > 1:
                # One lobby is exactly two teams; the rest of the pool is the
                # other lobbies' business.
                usable_count = min(usable_count, 2 * players_per_team)
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
    ) -> list[DiscordCommandEvent]:
        """Permanently removes the mix, every row it owns and every post it made.

        Unlike :meth:`cancel` (a status flip a host can undo by starting over)
        this is irreversible, so the RPC layer gates it on workspace admin
        rather than host-or-co-host -- see ``rpc.balancer.custom.hard_delete``.
        ``custom_game_player`` and ``casual_match`` both cascade on
        ``custom_game_id`` at the DB level, so deleting the game row is enough.

        Its Discord messages do not cascade -- ``discord_message`` is filed by
        subject, not by a foreign key -- and a mix that no longer exists has no
        business leaving cards in the channel, so they are all marked for
        deletion here. The caller publishes the returned commands after the
        commit that destroys the mix.
        """
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        commands = await discord_messages.delete_commands(
            session, await discord_messages.repository.for_subject(session, mix_subject(custom_game_id))
        )
        await self.games.delete(session, game)
        return commands


custom_game_service = CustomGameService()
