from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.enums import (
    DraftPlayerStatus,
    DraftStatus,
    MixParticipation,
    MixRatingMode,
    MixRoleSelectionMode,
    MixSelfSignup,
    MixStatus,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES, rated_role_codes
from shared.division_grid import DivisionGrid, ladder_grid
from shared.domain.custom_game_round import winner_slot
from shared.domain.encounter_scoring import WINS_END_FORMULA
from shared.domain.member_rank import ResolvedRank
from shared.domain.mix_lobby import LOBBY_LETTERS
from shared.domain.pick_ban_rules import mix_ban_preset
from shared.domain.roster import PlayerRoster, RosterRole
from shared.domain.roster_shape import FLEX_SLOT_CODE
from shared.rbac import assign_workspace_system_role
from shared.repository import (
    CatalogEntityRepository,
    CustomGameCoHostRepository,
    CustomGameLobbyRepository,
    CustomGamePlayerRepository,
    CustomGamePlayerRoleRepository,
    CustomGameRepository,
    CustomGameRoundRepository,
    CustomGameTeamNameRepository,
    ScoringRuleRepository,
    UserBalancerConfigRepository,
    UserRepository,
    WorkspaceBalancerConfigRepository,
    WorkspaceMemberRepository,
    WorkspaceRepository,
)
from shared.repository.discord_message import LIVE_STATUSES
from shared.repository.draft import (
    DraftPickRepository,
    DraftPlayerRepository,
    DraftSessionRepository,
    DraftTeamRepository,
)
from shared.repository.roles import CatalogRoleRepository
from shared.repository.workspace import get_or_create_workspace_member
from shared.schemas.events import DiscordCommandEvent
from shared.schemas.role import RoleRef
from shared.schemas.roster_slots import RosterShapeRead
from shared.services import discord_messages
from shared.services.discord_client import DiscordClient
from shared.services.discord_errors import DiscordError
from shared.services.discord_messages import SIGNUP_SLOT, lineup_slot, mix_subject
from shared.services.division_grid.access import (
    get_effective_division_grid,
    get_effective_division_grid_version_id,
    require_event_grid,
)
from shared.services.member_rank import MIX_ORDER, MemberRankService, member_rank_service
from shared.services.ontology import assert_discipline_enabled, resolve_role_ref
from shared.services.pickup_mix_realtime import emit_pickup_mix_changed
from shared.services.team_format import (
    copy_for_custom_game,
    custom_game_format,
    custom_game_slot_shape,
    team_format_read,
)
from src.domain.balancer.result_serializer import as_lobby_document, seat_rating
from src.domain.balancer.role_naming import role_slot_code
from src.domain.draft import ranks as draft_ranks
from src.domain.mix_lobbies import current_lobbies, lobby_state, seated_member_ids, seated_teams, with_captains
from src.domain.mix_lobby_split import LobbySplitError, SplitCandidate, split_into_lobbies
from src.domain.mix_opener import ban_opener
from src.domain.mix_ranker import Ranker
from src.domain.mix_rotation import PlayerHistory, RotationRecommendation, recommend_rotation, rotation_priority
from src.domain.mix_self_service import MixSelfPolicy, mix_self_policy
from src.domain.mix_stats import SeatOutcome, aggregate_mix_stats, outcome_for
from src.domain.mix_voice import LobbyVoice, MixVoiceConfig, VoicePlan, plan_move, report, snowflake, voice_config_from
from src.services.account_links import missing_account_links
from src.services.balancer.solver import run_mix_balance as _run_balance
from src.services.balancer.solver import serialize_format_context
from src.services.draft import realtime as draft_rt
from src.services.mix_ranker import MixRankerService, RatedSeat, mix_ranker_service
from src.services.mix_room_dms import notify_mix_captain
from src.services.mix_rounds import MixMatchDraft, MixMatchSeat, MixResultDraft, record_mix_result, start_mix_match
from src.services.workspace_roster import (
    RosterMember,
    hosts_by_user_id,
    list_roster,
    workspace_member_user_ids,
)

__all__ = ("CustomGameService", "custom_game_service")

_TERMINAL = frozenset({MixStatus.COMPLETED, MixStatus.CANCELLED})
#: The list's ``status`` tab -> the mix statuses it shows.
_LIST_STATUSES = {"open": frozenset({MixStatus.DRAFT, MixStatus.BALANCED}), "history": _TERMINAL}
#: Plenty for any pickup mix (2-3 teams in practice); guards against a
#: malformed payload turning into an unbounded dict.
_MAX_TEAMS = 8
#: Plenty for any pickup mix; guards a malformed payload from growing the
#: co-host list without bound.
_MAX_CO_HOSTS = 16
_MAX_TEAM_NAME_LEN = 60

#: A roster row owns only its lineup state. A rank correction goes into the
#: host's own layer of ``member_rank``, so it outlives the game it was made in.
_PLAYER_PATCH_FIELDS = frozenset({"participation", "roles", "is_flex", "lobby_pin", "away"})

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
    (site or bot) translates it instead of parsing English. Any ``<provider>_not_linked`` is "fix your account"."""
    status_code = _BLOCKER_STATUS.get(code) or (status.HTTP_403_FORBIDDEN if code.endswith("_not_linked") else None)
    if status_code is None:
        raise KeyError(code)
    return HTTPException(status_code=status_code, detail=code)


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
        away=False,
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


def _discipline_facts(code: str) -> dict[str, Any]:
    """The mix game's own role vocabulary, for the bot (spec §12.1 R3-1): its code, its rated roles as ``{code,
    label}`` in declaration order, and whether it has Full flex. One role means no role UI at all."""
    spec = DISCIPLINES[code]
    return {
        "discipline": code,
        "discipline_roles": [{"code": role.code, "label": role.name} for role in spec.rated_dimension.roles],
        "discipline_flex": spec.flex,
    }


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


def _refuse_live(lobby: models.CustomGameLobby) -> None:
    """The frozen lineup (spec §5.1): a lobby whose match is live is not re-formed, re-seated or re-mapped."""
    if lobby.live_encounter_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="match_live")


def _two_team_lineup(lobby: models.CustomGameLobby) -> tuple[dict[str, Any], list[Any]]:
    """The lobby's shown option as a captained two-team lineup: a copy of its document, and that option's teams."""
    result = with_captains(copy.deepcopy(as_lobby_document(lobby.balance_result_json))) or {}
    variants = result.get("variants")
    index = lobby.selected_variant_index
    if not isinstance(variants, list) or not (0 <= index < len(variants)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance option not found")
    teams = variants[index].get("teams") if isinstance(variants[index], dict) else None
    if not isinstance(teams, list) or len(teams) != 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A match can only be played by a two-team balance",
        )
    return result, teams


def _lineup_seats(
    result: Mapping[str, Any], teams: Sequence[Any]
) -> tuple[list[list[MixMatchSeat]], list[list[tuple[int, str, int]]], list[list[int]]]:
    """One walk over a two-team lineup: the seats a match snapshots, and per team ``(member, slot code, rating)`` plus
    each seat's open rank (the ranker's base). The name and rating are the lineup's, as they stood when it was formed."""
    team_seats: list[list[MixMatchSeat]] = [[], []]
    team_players: list[list[tuple[int, str, int]]] = [[], []]
    open_ranks: list[list[int]] = [[], []]
    players = _lobby_players(result)
    for team_index, team in enumerate(teams):
        roster = team.get("roster") if isinstance(team, dict) else None
        if not isinstance(roster, dict):
            continue
        captain = team.get("captain_member_id")
        for bucket_name, seats in roster.items():
            if not isinstance(seats, list):
                continue
            slot_code = role_slot_code(bucket_name)
            for uuid in seats:
                player = players.get(str(uuid))
                if not isinstance(player, Mapping):
                    continue
                member_id = int(uuid)
                rating = int(seat_rating(player, bucket_name))
                team_seats[team_index].append(
                    MixMatchSeat(
                        member_id, str(player.get("name") or f"#{member_id}"), slot_code, rating, member_id == captain
                    )
                )
                team_players[team_index].append((member_id, slot_code, rating))
                opens = player.get("open_ratings")
                open_ranks[team_index].append(
                    int(opens.get(bucket_name, rating)) if isinstance(opens, Mapping) else rating
                )
    return team_seats, team_players, open_ranks


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
        mix_rounds: CustomGameRoundRepository = CustomGameRoundRepository(),
        open_match=start_mix_match,
        write_result=record_mix_result,
        maps: CatalogEntityRepository = CatalogEntityRepository("map"),
        host_prefs: UserBalancerConfigRepository = UserBalancerConfigRepository(),
        ranks: MemberRankService | None = None,
        scoring_rules: ScoringRuleRepository = ScoringRuleRepository(),
        load_roster=list_roster,
        load_hosts=hosts_by_user_id,
        load_member_user_ids=workspace_member_user_ids,
        run_balance=_run_balance,
        players: UserRepository = UserRepository(),
        workspace_members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        workspaces: WorkspaceRepository = WorkspaceRepository(),
        workspace_configs: WorkspaceBalancerConfigRepository = WorkspaceBalancerConfigRepository(),
        load_missing_links=missing_account_links,
        enroll_member=get_or_create_workspace_member,
        grant_player_role=assign_workspace_system_role,
        ranker: MixRankerService | None = None,
        drafts: DraftSessionRepository = DraftSessionRepository(),
    ) -> None:
        self.games = games
        self.scoring_rules = scoring_rules
        self.roster = roster
        self.co_hosts = co_hosts
        self.lobbies = lobbies
        self.player_roles = player_roles
        self.team_names = team_names
        self.mix_rounds = mix_rounds
        self.open_match = open_match
        self.write_result = write_result
        self.maps = maps
        self.host_prefs = host_prefs
        self.ranks = ranks if ranks is not None else member_rank_service
        self.load_roster = load_roster
        self.load_hosts = load_hosts
        self.load_member_user_ids = load_member_user_ids
        self.run_balance = run_balance
        self.players = players
        self.workspace_members = workspace_members
        self.workspaces = workspaces
        self.workspace_configs = workspace_configs
        self.load_missing_links = load_missing_links
        self.enroll_member = enroll_member
        self.grant_player_role = grant_player_role
        self.ranker = ranker if ranker is not None else mix_ranker_service
        self.drafts = drafts

    async def members(
        self, session: AsyncSession, workspace_id: int, member_ids: Sequence[int], *, discipline: str
    ) -> dict[int, RosterMember]:
        """Named roster rows for a lineup, identified by ``discipline``'s provider -- and the tenancy check on the way in.

        ``list_roster`` already filters by ``workspace_id``, so an id absent from
        the result either does not exist or belongs to another workspace. Both are
        the same 404 on purpose: telling them apart would leak the membership of a
        workspace the caller is not in.
        """
        ids = _uniq(member_ids)
        if not ids:
            return {}
        found = await self.load_roster(
            session,
            workspace_id=workspace_id,
            provider=DISCIPLINES[discipline].identity_provider,
            member_ids=ids,
        )
        if len(found) != len(ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
        return found

    async def grid(self, session: AsyncSession, game: models.CustomGame) -> DivisionGrid:
        """The scale a mix's ranks live on: the game's own ladder, the same in every workspace.

        A workspace grid is its tournament divisions -- the 1-20 system default reads every Overwatch rank >= 2000 as
        its top tier, so a native rank resolved on it seeded 2000 into the host's book. Only a game without a ladder
        reads the workspace grid, the one its ranks are entered on (``create`` requires it to have tiers).
        """
        return ladder_grid(game.discipline) or await get_effective_division_grid(
            session, game.workspace_id, discipline=game.discipline
        )

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
        workspace_id: int | None,
        custom_game_id: int,
        options: Sequence[Any] = (),
    ) -> models.CustomGame:
        game = await self.games.get(session, custom_game_id, options=options)
        if game is None or (workspace_id is not None and game.workspace_id != workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        return game

    async def list(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        discipline: str | None = None,
        status: str | None = None,
        search: str | None = None,
        before_id: int | None = None,
        limit: int,
    ) -> tuple[list[models.CustomGame], int | None]:
        """One page of the workspace's mixes, newest first, and the ``before_id`` of the next page.

        Reads one row past ``limit`` to learn whether another page exists, so the
        cursor is ``None`` on the last page instead of pointing at an empty one.
        """
        rows = list(
            await self.games.list_for_workspace(
                session,
                workspace_id,
                discipline,
                statuses=_LIST_STATUSES[status] if status is not None else None,
                search=search,
                before_id=before_id,
                limit=limit + 1,
            )
        )
        page = rows[:limit]
        return page, (page[-1].id if len(rows) > limit else None)

    async def _writable(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        # Locked, and re-read: the host writes of one mix run one at a time -- two Starts of one lobby, a Start
        # against a Close or a lineup write -- so each reads the lobbies as the write before it committed them.
        game = await self.games.get(session, custom_game_id, for_update=True)
        if game is None or game.workspace_id != workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
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
        selected option and, in draft mode, each other lobby's active draft pool
        until its lineup exists (spec §9.2; ``draft_lobbies``, the membership the
        board and a player's own seat read too), which is what every caller here
        means by "busy".
        """
        if game.lobby_count < 2:
            return frozenset()
        pools = await self.draft_lobbies(session, game.id)
        busy: set[int] = set()
        for lobby in await self.lobbies.list_for_game(session, game.id):
            if lobby.lobby_index != lobby_index:
                busy |= seated_member_ids(lobby.balance_result_json, lobby.selected_variant_index)
                if lobby.lobby_index in pools:
                    busy |= pools[lobby.lobby_index][2]
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
        number is one nobody in this mix owns: correcting it would silently be a
        workspace-wide edit, and the sheet could offer no Clear. Copying in the
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
            discipline=game.discipline,
            members={member_id: member.player_id for member_id, member in members.items()},
            roles=list(rated_role_codes(game.discipline)),
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await self.grid(session, game),
        )
        for member_id in members:
            seed: dict[str, int] = {}
            for role in rated_role_codes(game.discipline):
                rank = resolved.get((member_id, role))
                if rank is None or rank.value is None or rank.source == "author":
                    continue
                seed[role] = rank.value
            if not seed:
                continue
            await self.ranks.set_ranks(
                session,
                workspace_id=game.workspace_id,
                discipline=game.discipline,
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
        # The mix's game: the host's explicit choice (a clone keeps its source's).
        discipline: str,
        team_format_preset: str | None = None,
    ) -> models.CustomGame:
        """Open a mix, optionally starting from a previous one's setup.

        A clone copies the parts a host would otherwise re-enter every session --
        the pool and its per-seat role setup, the team names and the co-host
        grants -- but never anything that describes a *played* session: no
        balance result, no rolled map, no match history, and every seat back in
        the pool rather than carrying last week's pins and benchings. Roster
        members who have since left the workspace are dropped rather than failing
        the clone. The points knob and Discord target belong to the host and workspace.
        The team format is frozen per mix: a clone keeps its source's,
        otherwise the host's preset or the workspace default.
        The hero ban preset, the team formation and the pick clock are the source's on a clone, else the host's
        defaults for the game.
        """
        _require_host(actor_user_id, host_user_id)
        trimmed = name.strip() if isinstance(name, str) else ""
        if not trimmed:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name is required")
        ids = _uniq(member_ids)

        source: models.CustomGame | None = None
        source_rows: list[models.CustomGamePlayer] = []
        if clone_from_game_id is not None:
            source = await self.games.get(session, clone_from_game_id)
            if source is None or source.workspace_id != workspace_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mix not found")

        effective = source.discipline if source is not None else discipline
        workspace = await self.workspaces.get(session, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        assert_discipline_enabled(workspace, effective)
        members = dict(await self.members(session, workspace_id, ids, discipline=effective))
        if not DISCIPLINES[effective].native_ladder:
            await require_event_grid(
                session,
                version_id=await get_effective_division_grid_version_id(session, workspace_id, discipline=effective),
                discipline=effective,
            )

        if source is not None:
            candidates = list(await self.roster.list_for_game(session, source.id))
            # Lenient on purpose, unlike ``members`` above: a departed member is
            # dropped from the copy, not a 404 that makes the old mix
            # un-clonable forever.
            surviving = await self.load_roster(
                session,
                workspace_id=workspace_id,
                provider=DISCIPLINES[effective].identity_provider,
                member_ids=_uniq([row.workspace_member_id for row in candidates]),
            )
            source_rows = [row for row in candidates if row.workspace_member_id in surviving]
            members.update(surviving)

        # The mix's own wins rule: every round encounter it records is scored by it.
        rule = await self.scoring_rules.create(
            session,
            models.ScoringRule(
                workspace_id=workspace_id, preset="wins", game_formula="win", end_formula=WINS_END_FORMULA
            ),
        )
        # A clone keeps its source's bans, Fearless, clocks, pickers and formation; a new mix starts from its host's
        # defaults for this game (spec §4.3). A stored ban default the game no longer offers is no default.
        if source is not None:
            ban_preset = source.hero_ban_preset
            team_formation, draft_pick_seconds = source.team_formation, source.draft_pick_seconds
        else:
            host_config = await self._host_config(session, host_user_id)
            default = (host_config.hero_ban_presets or {}).get(effective) if host_config is not None else None
            ban_preset = default if default is not None and mix_ban_preset(effective, default) is not None else None
            formation = (host_config.formation_defaults or {}).get(effective, {}) if host_config is not None else {}
            team_formation = formation.get("team_formation", "balance")
            draft_pick_seconds = formation.get("draft_pick_seconds", 30)
        game = models.CustomGame(
            scoring_rule_id=rule.id,
            workspace_id=workspace_id,
            discipline=effective,
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
            hero_ban_preset=ban_preset,
            hero_fearless=source.hero_fearless if source is not None else False,
            hero_ban_seconds=source.hero_ban_seconds if source is not None else None,
            hero_pick_seconds=source.hero_pick_seconds if source is not None else None,
            hero_free_order=source.hero_free_order if source is not None else False,
            hero_captains_only=source.hero_captains_only if source is not None else False,
            team_formation=team_formation,
            draft_pick_seconds=draft_pick_seconds,
        )
        await self.games.create(session, game)
        await copy_for_custom_game(
            session, game, preset_code=team_format_preset, source_game_id=None if source is None else source.id
        )
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
                    await self.player_roles.replace_for_player(session, row.id, roles, discipline=game.discipline)
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
        members = await self.members(session, workspace_id, ids, discipline=game.discipline)
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
        on_away: Callable[..., Awaitable[None]] | None = None,
    ) -> models.CustomGame:
        """Patch one roster row's participation, role selection and flex mode.

        ``on_away`` (``MixDraftService.on_away``) hears an away flag that flipped, under this write's lock: the
        lobby's running draft follows its player (spec §9.5)."""
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
        was_away = row.away
        await self._apply_player_patch(
            session, row, patch, _PLAYER_PATCH_FIELDS, game=game, lobby_count=game.lobby_count
        )
        await session.flush()
        if on_away is not None and row.away != was_away:
            await on_away(
                session,
                custom_game_id=game.id,
                workspace_member_id=workspace_member_id,
                away=row.away,
                actor_auth_user_id=actor_user_id,
            )
        return game

    async def _apply_player_patch(
        self,
        session: AsyncSession,
        row: models.CustomGamePlayer,
        patch: Mapping[str, Any],
        allowed: frozenset[str],
        *,
        game: models.CustomGame,
        lobby_count: int = 1,
    ) -> None:
        """Apply a validated lineup patch to one row, within ``allowed`` fields.

        One mutation for two callers: the host patches the whole row
        (``_PLAYER_PATCH_FIELDS``, away included), a player only their own role order and flex
        (``_SELF_PATCH_FIELDS``). The difference between them is the gate, not
        the write -- a self edit that diverged here would be a second, subtly
        different way to set the same columns.

        ``lobby_count`` is the mix's, and only the pin reads it: pinning to a
        lobby the mix does not run is a client bug, not a silent no-op. The self
        path never carries a pin (``lobby_pin`` is not in ``_SELF_PATCH_FIELDS``),
        so it leaves the default alone.
        """
        _reject_unknown(patch, allowed)
        if patch.get("is_flex") is True and not DISCIPLINES[game.discipline].flex:
            # A game without open slots has no Full flex player (``DisciplineSpec.flex``). Refused before any field is
            # written; ``False`` still goes through, so a flag stored before the game lost it can be cleared.
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="full_flex_unsupported")
        if "participation" in patch:
            try:
                row.participation = MixParticipation(patch["participation"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="invalid participation",
                ) from exc
        if "roles" in patch:
            refs = patch["roles"]
            roles = None if refs is None else []
            if refs is not None:
                for ref in refs:
                    role = await resolve_role_ref(
                        session,
                        discipline=game.discipline,
                        workspace_id=game.workspace_id,
                        ref=RoleRef.model_validate(ref),
                        top_level_only=True,
                    )
                    if role.code not in roles:
                        roles.append(role.code)
            row.role_selection_mode = (
                MixRoleSelectionMode.ALL_RANKED if roles is None else MixRoleSelectionMode.EXPLICIT
            )
            await self.player_roles.replace_for_player(session, row.id, roles or (), discipline=game.discipline)
        if "is_flex" in patch:
            if not isinstance(patch["is_flex"], bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="is_flex must be a boolean",
                )
            row.is_flex = patch["is_flex"]
        if "away" in patch:
            if not isinstance(patch["away"], bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="away must be a boolean",
                )
            row.away = patch["away"]
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
        snapshot: applied row by row, the calls race on whose response the
        client sees last and leave the lineup mid-verdict if one fails.
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
        Pins to surviving lobbies are kept. A lobby it would drop must not have a live match (409 ``match_live``).
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
            dropped = [
                lobby
                for lobby in await self.lobbies.list_for_game(session, game.id)
                if lobby.lobby_index >= lobby_count
            ]
            # Checked before anything is deleted: dropping a lobby mid-match would orphan its open encounter.
            for lobby in dropped:
                _refuse_live(lobby)
            for lobby in dropped:
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
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
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
            missing_links=await self.load_missing_links(session, auth_user.id, game.discipline),
            has_player=player is not None,
            self_join_denied=not auth_user.can_capability("custom_game", "self_join", workspace_id=game.workspace_id),
            roster_size=len(roster),
        )
        return _SelfContext(game=game, player=player, member=member, roster=roster, row=row, policy=policy)

    async def _self_dump(self, session: AsyncSession, ctx: _SelfContext) -> dict[str, Any]:
        """One player's view of one mix: their seat, and what they may do next.

        ``ranks`` carries every rated role, ``None`` included: the Discord role
        select labels every option with a number or "no rank". ``divisions``
        uses the discipline's native ladder when it has one (the bot's badges),
        otherwise the organiser's effective grid, never another game's ladder.
        ``unranked_roles`` is the narrower list the warning is built from -- the
        roles this player actually plays.

        ``current_lobby`` is the same derivation the board shows -- the seats of
        each lobby's selected option, and each drafting lobby's pool
        (``current_lobbies``) -- so nobody downstream re-parses a solver
        document to answer "which lobby am I in", and ``lobby_count`` is what
        tells them whether that question is worth asking at all.
        """
        seat: dict[str, Any] | None = None
        unranked: list[str] = []
        if ctx.row is not None:
            stored = (await self.player_roles.roles_for_players(session, [ctx.row.id])).get(ctx.row.id, [])
            explicit = ctx.row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
            grid = await self.grid(session, ctx.game)
            resolved = await self.ranks.resolve(
                session,
                workspace_id=ctx.game.workspace_id,
                discipline=ctx.game.discipline,
                members={ctx.row.workspace_member_id: ctx.player.id if ctx.player is not None else None},
                roles=list(rated_role_codes(ctx.game.discipline)),
                order=MIX_ORDER,
                author_user_id=ctx.game.host_user_id,
                grid=grid,
            )
            ranks: dict[str, int | None] = {}
            divisions: dict[str, dict[str, str | None] | None] = {}
            for role in rated_role_codes(ctx.game.discipline):
                rank = resolved.get((ctx.row.workspace_member_id, role))
                ranks[role] = rank.value if rank is not None else None
                tier = None if ranks[role] is None else grid.resolve_division(ranks[role])
                divisions[role] = None if tier is None else {"name": tier.name, "slug": tier.slug}
            considered = list(stored) if explicit else list(rated_role_codes(ctx.game.discipline))
            unranked = [role for role in considered if ranks.get(role) is None]
            lobbies = list(await self.lobbies.list_for_game(session, ctx.game.id))
            current_lobby = current_lobbies(lobbies, await self.draft_lobbies(session, ctx.game.id)).get(
                ctx.row.workspace_member_id
            )
            voice_channel: int | None = None
            for lobby in lobbies:
                teams = seated_teams(lobby.balance_result_json, lobby.selected_variant_index)
                for team_index, members in enumerate(teams):
                    if ctx.row.workspace_member_id in members and team_index < 2:
                        voice_channel = (lobby.team1_voice_channel_id, lobby.team2_voice_channel_id)[team_index]
            voice_url: str | None = None
            if voice_channel is not None:
                _channel_id, guild_id = await self.workspace_discord_target(session, ctx.game.workspace_id)
                if guild_id is not None:
                    voice_url = f"https://discord.com/channels/{guild_id}/{voice_channel}"
            seat = {
                "participation": ctx.row.participation,
                # ``null`` means all_ranked: every role this player has a number
                # for plays, which is a different statement from an empty list.
                "roles": [
                    RoleRef(dimension=DISCIPLINES[ctx.game.discipline].rated_dimension.code, role=code).model_dump()
                    for code in stored
                ]
                if explicit
                else None,
                "is_flex": ctx.row.is_flex,
                "ranks": ranks,
                "divisions": divisions,
                "workspace_member_id": ctx.row.workspace_member_id,
                "away": ctx.row.away,
                # The lobby whose shown option seats them, ``null`` while none does.
                "current_lobby": current_lobby,
                # Their own team's voice in Discord, when the lobby has one and the workspace a verified guild.
                "voice_url": voice_url,
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
            # The game's roles, so the bot asks for exactly them -- or for none in a one-role game.
            **_discipline_facts(ctx.game.discipline),
            "seat": seat,
            "unranked_roles": unranked,
            "policy": {
                "can_join": ctx.policy.can_join,
                "can_leave": ctx.policy.can_leave,
                "can_edit_roles": ctx.policy.can_edit_roles,
                "can_set_away": ctx.policy.can_set_away,
                "join_blocker": ctx.policy.join_blocker,
                "edit_blocker": ctx.policy.edit_blocker,
                "away_blocker": ctx.policy.away_blocker,
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

    async def hosted_active(self, session: AsyncSession, *, workspace_id: int, auth_user: Any) -> list[dict[str, Any]]:
        """The open mixes this account may run, newest first -- what ``/mix move`` offers."""
        rows = await self.games.list_open_runnable(
            session, workspace_id, user_id=None if auth_user.is_superuser else auth_user.id
        )
        return [{"id": game_id, "name": name, "lobby_count": lobby_count} for game_id, name, lobby_count in rows]

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

        # Two idempotent steps: the membership row anchors the roster row, the
        # baseline RBAC role makes the account an ordinary workspace player
        # rather than a role-less anchor.
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
        await self._seed_host_ranks(
            session,
            ctx.game,
            await self.members(session, ctx.game.workspace_id, [member.id], discipline=ctx.game.discipline),
        )
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
        await self._apply_player_patch(session, ctx.row, patch, _SELF_PATCH_FIELDS, game=ctx.game)
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

    async def self_set_away(
        self,
        session: AsyncSession,
        *,
        custom_game_id: int,
        auth_user: Any,
        away: bool,
        workspace_id: int | None = None,
        on_away: Callable[..., Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Step away from the mix, or come back (spec §7.4).

        Gated like a role edit minus the host's switch (``MixSelfPolicy.can_set_away``): a break is the player's own
        business. It never clears itself. The stored balance is left alone -- an away player already in a lineup stays
        there with a badge, and Start match warns about them. ``on_away`` is ``update_player``'s: the lobby's running
        draft hears a flag that flipped.
        """
        # Owner first, as every host write (``_writable``): the mix row is locked before this player's own row is
        # touched, so a host write that holds the mix and edits that row never deadlocks with this one.
        await self.games.get(session, custom_game_id, for_update=True)
        ctx = await self._self_context(
            session, custom_game_id=custom_game_id, auth_user=auth_user, workspace_id=workspace_id
        )
        if ctx.row is None or not ctx.policy.can_set_away:
            raise _blocker(ctx.policy.away_blocker or "not_on_roster")
        was_away = ctx.row.away
        ctx.row.away = away
        await session.flush()
        if on_away is not None and away != was_away:
            await on_away(
                session,
                custom_game_id=ctx.game.id,
                workspace_member_id=ctx.row.workspace_member_id,
                away=away,
                actor_auth_user_id=auth_user.id,
            )
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

    async def set_ban_preset(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        hero_ban_preset: str | None,
        hero_fearless: bool | None = None,
        clocks: Mapping[str, int | None] | None = None,
        hero_free_order: bool | None = None,
        hero_captains_only: bool | None = None,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """The hero ban preset the next Start opens a room on (spec §4.3): a preset of the mix's own game, or ``None``.

        A live match keeps the room it started with; the change applies from the next Start. 422 ``unknown_ban_preset``.
        ``hero_fearless`` (when given) turns Fearless on or off; it too applies from the next room (spec §11.4).
        ``clocks`` holds the sent ones of ``hero_ban_seconds`` / ``hero_pick_seconds``: the next room's seconds per
        ban / per pick step, ``None`` for the preset's own clock. ``hero_free_order`` / ``hero_captains_only`` (when
        given) set who a turn-by-turn pick is for / who picks; both apply from the next room too.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        if hero_ban_preset is not None and mix_ban_preset(game.discipline, hero_ban_preset) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unknown_ban_preset")
        game.hero_ban_preset = hero_ban_preset
        if hero_fearless is not None:
            game.hero_fearless = hero_fearless
        clocks = clocks or {}
        if "hero_ban_seconds" in clocks:
            game.hero_ban_seconds = clocks["hero_ban_seconds"]
        if "hero_pick_seconds" in clocks:
            game.hero_pick_seconds = clocks["hero_pick_seconds"]
        if hero_free_order is not None:
            game.hero_free_order = hero_free_order
        if hero_captains_only is not None:
            game.hero_captains_only = hero_captains_only
        await session.flush()
        return game

    async def set_draft_settings(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        team_formation: str,
        draft_pick_seconds: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """How the lobbies form their teams by default and the draft's pick clock (spec §4.3). A running draft keeps
        the clock it was seeded with; both apply from the next formation."""
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        game.team_formation = team_formation
        game.draft_pick_seconds = draft_pick_seconds
        await session.flush()
        return game

    @staticmethod
    def _board_url(board_url_base: str, custom_game_id: int) -> str:
        return f"{board_url_base.rstrip('/')}/balancer/mix/{custom_game_id}"

    async def discord_view(
        self,
        session: AsyncSession,
        custom_game_id: int,
        lineups: Sequence[tuple[int, int]],
        *,
        board_url_base: str,
    ) -> dict[str, Any]:
        """What discord-service renders this mix's cards from (``rpc.balancer.custom.discord_view``).

        The bot owns every card; this answers the facts only the balancer's
        tables hold: the signup roster, and one entry per ``(lobby_index,
        match_number)`` lineup the bot is about to post or re-render -- the
        match number is the one in the row's slot, so a card keeps announcing
        the match it was posted for. It also names the game's roles
        (``_discipline_facts``) and, on the signup facts, each lobby's stage and
        who is away (spec §12.1).
        """
        game = await self.games.get(session, custom_game_id)
        if game is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        activity = await self.mix_rounds.activity_for_lobbies(session, game.id)
        lobbies = {lobby.lobby_index: lobby for lobby in await self.lobbies.list_for_game(session, game.id)}
        # The host's knob, resolved: the card promises what recording this
        # match will actually move. ``0`` is "off", and off prints nothing.
        points_per_win = await self.host_points_per_win(session, game.host_user_id) or None
        return {
            "custom_game_id": game.id,
            "workspace_id": game.workspace_id,
            "status": game.status,
            "board_url": self._board_url(board_url_base, game.id),
            **_discipline_facts(game.discipline),
            "signup": await self._signup_view(session, game, list(lobbies.values())),
            "lineups": [
                await self._lineup_view(
                    session,
                    game,
                    lobbies.get(lobby_index),
                    lobby_index=lobby_index,
                    match_number=match_number,
                    matches_recorded=activity.get(lobby_index, (0, None))[0],
                    points_per_win=points_per_win,
                )
                for lobby_index, match_number in lineups
            ],
        }

    async def _signup_view(
        self, session: AsyncSession, game: models.CustomGame, lobbies: Sequence[models.CustomGameLobby]
    ) -> dict[str, Any]:
        """The signup card's facts as the mix stands right now.

        Rebuilt from current state on every render rather than kept anywhere:
        the card is the mix's roster seen from a channel, and the roster is the
        only copy of it. Names resolve exactly as the balancer resolves them.
        """
        roster = list(await self.roster.list_for_game(session, game.id))
        stored = await self.player_roles.roles_for_players(session, [row.id for row in roster])
        members = await self.load_roster(
            session,
            workspace_id=game.workspace_id,
            provider=DISCIPLINES[game.discipline].identity_provider,
            member_ids=[row.workspace_member_id for row in roster],
        )
        host_names = await self.hosts(session, game.workspace_id, [game.host_user_id])
        # The numbers the balancer will balance them at: the host's own book
        # above the workspace canon (``MIX_ORDER``), as in ``balance``.
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            discipline=game.discipline,
            members={member.member_id: member.player_id for member in members.values()},
            roles=list(rated_role_codes(game.discipline)),
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await self.grid(session, game),
        )
        players = []
        for row in roster:
            member_id = row.workspace_member_id
            member = members.get(member_id)
            name = (member.display_name or member.handle) if member else None
            roles = stored.get(row.id, []) if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT else None
            ranks = {
                role: found.value
                for role in rated_role_codes(game.discipline)
                if (found := resolved.get((member_id, role))) is not None and found.value is not None
            }
            # The role they come for: the first they named or -- playing
            # anything -- their best. An explicit empty order plays nothing.
            if roles is None:
                role = max(ranks, key=ranks.__getitem__, default=None)
            else:
                role = roles[0] if roles else None
            players.append(
                {
                    "name": name or f"player-{member_id}",
                    # Only Full Flex is flex; everyone else counts on their own role.
                    "role": "flex" if row.is_flex else role,
                    "benched": row.participation == MixParticipation.BENCHED,
                    "rank": ranks.get(role) if role else None,
                    "away": row.away,
                }
            )
        # When the mix or its roster last changed: the card's "updated" stamp,
        # stable across re-renders of an unchanged mix so the bot can skip them.
        moments = [game.updated_at or game.created_at, *(row.updated_at or row.created_at for row in roster)]
        updated_at = max((moment for moment in moments if moment is not None), default=None) or datetime.now(UTC)
        return {
            "mix_name": game.name,
            "host_name": host_names.get(game.host_user_id),
            "self_signup": game.self_signup,
            "status": game.status,
            "lobby_count": game.lobby_count,
            "players": players,
            "lobbies": await self._lobby_stages(session, game.id, lobbies),
            "updated_at": updated_at.isoformat(),
        }

    async def _lobby_stages(
        self, session: AsyncSession, custom_game_id: int, lobbies: Sequence[models.CustomGameLobby]
    ) -> list[dict[str, Any]]:
        """Each lobby's stage for the signup card (spec §12.1 R3-4), derived as the detail read derives it
        (``lobby_state``), with its clock: a live or pre-game match's start, else a live draft's first pick clock --
        the bot prints it for ``live`` and ``draft_live`` only. No pick count: a pick emits no mix fact."""
        live_ids = [lobby.live_encounter_id for lobby in lobbies if lobby.live_encounter_id is not None]
        started = await self.lobbies.live_started_at(session, live_ids)
        pregame = await self.lobbies.pregame_ids(session, live_ids)
        drafts = await self.draft_lobbies(session, custom_game_id)
        first_picks = (
            await self.drafts.first_clock_starts(session, [entry[0] for entry in drafts.values()]) if drafts else {}
        )
        stages: list[dict[str, Any]] = []
        for lobby in sorted(lobbies, key=lambda row: row.lobby_index):
            draft = drafts.get(lobby.lobby_index)
            if lobby.live_encounter_id is not None:
                since = started.get(lobby.live_encounter_id)
            else:
                since = first_picks.get(draft[0]) if draft is not None else None
            stages.append(
                {
                    "lobby_index": lobby.lobby_index,
                    "state": lobby_state(
                        lobby.balance_result_json,
                        lobby.selected_variant_index,
                        lobby.live_encounter_id,
                        lobby.live_encounter_id in pregame,
                        draft[1] if draft is not None else None,
                    ),
                    "live_started_at": since.isoformat() if since is not None else None,
                }
            )
        return stages

    async def signup_post(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        self_signup: str,
        actor_user_id: int,
        actor_is_superuser: bool = False,
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
        so the channel never holds two cards at once. The claimed row carries no
        card: discord-service renders it from :meth:`discord_view`.
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

    async def roster_shape(self, session: AsyncSession, game: models.CustomGame) -> RosterShapeRead:
        """The slots of this mix's frozen team format."""
        team_format, source = await custom_game_format(session, game)
        return (
            await team_format_read(session, team_format, source=source, workspace_id=game.workspace_id)
        ).roster_shape

    async def host_points_per_win(self, session: AsyncSession, host_user_id: int | None) -> int:
        """How far a decided match moves this host's rank book; 0 means "not at all" (or the ranker moves it)."""
        return _points_per_win(await self._host_config(session, host_user_id))

    async def draft_rosters(
        self, session: AsyncSession, game: models.CustomGame, member_ids: Sequence[int]
    ) -> tuple[dict[int, PlayerRoster], frozenset[int]]:
        """The roles and ranks a mix draft reads for these members (spec §9.1), and which of them are away.

        Ranks are the numbers the mix balance reads (``_lineup_nodes``): the host's book above the workspace canon
        (``MIX_ORDER``), corrected by the hidden rating for a ranker host, on the roles the mix lets a member play --
        their explicit order, else every rated role. Lenient like a clone: a member who left the workspace does not
        resolve rather than failing the board. Away is reported, not filtered: a picked seat still renders.
        """
        ids = _uniq(member_ids)
        if not ids:
            return {}, frozenset()
        wanted = set(ids)
        rows = {
            row.workspace_member_id: row
            for row in await self.roster.list_for_game(session, game.id)
            if row.workspace_member_id in wanted
        }
        found = await self.load_roster(
            session,
            workspace_id=game.workspace_id,
            provider=DISCIPLINES[game.discipline].identity_provider,
            member_ids=ids,
        )
        rated = list(rated_role_codes(game.discipline))
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            discipline=game.discipline,
            members={member_id: member.player_id for member_id, member in found.items()},
            roles=rated,
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await self.grid(session, game),
        )
        if _uses_ranker(await self._host_config(session, game.host_user_id)):
            effective = await self.ranker.effective_ratings(
                session,
                workspace_id=game.workspace_id,
                discipline=game.discipline,
                open_ranks={key: rank.value for key, rank in resolved.items() if rank.value is not None},
            )
            resolved = {
                key: ResolvedRank(effective.get(key, rank.value), rank.source) for key, rank in resolved.items()
            }
        explicit = await self.player_roles.roles_for_players(
            session, [row.id for row in rows.values() if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT]
        )
        unranked = ResolvedRank(None, "none")
        out: dict[int, PlayerRoster] = {}
        for member_id, member in found.items():
            row = rows.get(member_id)
            order = (
                explicit.get(row.id, [])
                if row is not None and row.role_selection_mode == MixRoleSelectionMode.EXPLICIT
                else rated
            )
            out[member_id] = PlayerRoster(
                registration_id=None,
                identity=member.identity,
                display_name=member.display_name,
                player_id=member.player_id,
                auth_user_id=member.auth_user_id,
                workspace_member_id=member_id,
                roles=tuple(
                    RosterRole(
                        role=role,
                        rank=(rank := resolved.get((member_id, role), unranked)).value,
                        source=rank.source,
                        is_primary=priority == 1,
                        priority=priority,
                        subrole=None,
                    )
                    for priority, role in enumerate(order, start=1)
                ),
                is_full_flex=bool(row is not None and row.is_flex),
                player_name=member.player_name,
            )
        return out, frozenset(member_id for member_id, row in rows.items() if row.away)

    async def draft_lobbies(
        self, session: AsyncSession, custom_game_id: int
    ) -> dict[int, tuple[int, str, frozenset[int]]]:
        """Each drafting lobby of the mix: its session id, status and the members its draft holds -- the one
        membership the busy, detail and self reads share (``DraftSessionRepository.active_lobby_pools``)."""
        return await self.drafts.active_lobby_pools(session, custom_game_id)

    async def cancel_drafts(
        self, session: AsyncSession, game: models.CustomGame, lobby_indexes: Collection[int] | None
    ) -> None:
        """Cancel the running drafts of these lobbies (every lobby with ``None``): a lobby re-formed or a mix closed
        ends its draft (spec §9.5). Each board hears ``draft.cancelled``."""
        for draft in await self.drafts.active_for_custom_game(session, game.id):
            if lobby_indexes is not None and draft.lobby_index not in lobby_indexes:
                continue
            draft.status = DraftStatus.CANCELLED.value
            draft.blocked_reason = None
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.cancelled",
                payload={"session_id": draft.id, "status": draft.status},
            )
        await session.flush()

    async def draft_pools(
        self, session: AsyncSession, game: models.CustomGame, lobby_indexes: Sequence[int]
    ) -> dict[int, tuple[int, ...]]:
        """Who each of these lobbies' drafts seats (spec §9.2-9.3): the seated set the balancer would take -- present,
        non-benched players, must-play first, then rotation order (``seated_set``) -- split over the lobbies by
        strength when there are several, as ``balance(scope="all")`` splits them. One lobby leaves out whoever the
        others play, as ``balance(scope="lobby")`` does."""
        roster = list(await self.roster.list_for_game(session, game.id))
        lineup = [row for row in roster if row.participation != MixParticipation.BENCHED and not row.away]
        if len(lobby_indexes) == 1:
            lineup = await self._lobby_candidates(session, game, lineup, lobby_indexes[0])
        if not lineup:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
        host_config = await self._host_config(session, game.host_user_id)
        _nodes, candidates, _opens = await self._lineup_nodes(
            session, game=game, lineup=lineup, host_config=host_config
        )
        if len(lobby_indexes) == 1:
            # One lobby is what the solver seats, and it reads its players in uuid order
            # (``player_loader.load_players_from_dict``) before its overflow trim breaks a tie by that order: the
            # draft takes the same order, so a tie seats the same people. A pin onto this lobby already passed
            # ``_lobby_candidates``, and the splitter numbers lobbies from 0.
            candidates = sorted(
                (replace(candidate, pin=None) for candidate in candidates),
                key=lambda candidate: str(candidate.member_id),
            )
        mask = (await custom_game_slot_shape(session, game)).slots
        try:
            split = split_into_lobbies(candidates, mask=mask, lobby_count=len(lobby_indexes))
        except LobbySplitError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.code) from exc
        return dict(zip(lobby_indexes, split.lobbies, strict=True))

    async def write_draft_lineup(self, session: AsyncSession, draft_session: models.DraftSession) -> None:
        """A finished mix draft becomes its lobby's lineup (spec §9.4): one option, ``source: "draft"``, each team
        crowned by its current captain, scored by the same arithmetic as a hand-edited option
        (``_recompute_variant_stats``). A seat's rating is the rank its pick froze; a captain, who has no pick, sits on
        their seat role at its live rank. A ranker host's seats keep their open rank too, as a balanced lineup's do.

        Under the mix row's lock -- the last pick took it before touching the draft (``selection``) -- and only onto a
        mix still open and a lobby not playing (spec §5.1): a frozen lineup is never overwritten."""
        game = await self.games.get(session, draft_session.custom_game_id, for_update=True)
        if game.status in _TERMINAL:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Game is {game.status}")
        lobby = await self._lobby(session, game, draft_session.lobby_index)
        _refuse_live(lobby)
        teams = await DraftTeamRepository().list_by_session(session, draft_session.id)
        seated = [
            player
            for player in await DraftPlayerRepository().list_by_session(session, draft_session.id)
            if player.status == DraftPlayerStatus.PICKED.value
        ]
        picks = {
            pick.picked_player_id: pick for pick in await DraftPickRepository().list_resolved(session, draft_session.id)
        }
        rosters, _away = await self.draft_rosters(session, game, [player.workspace_member_id for player in seated])
        shape = await custom_game_slot_shape(session, game)
        players: dict[str, dict[str, Any]] = {}
        lineup_teams: list[dict[str, Any]] = []
        for team in teams:
            buckets: dict[str, list[str]] = {}
            for seat in (player for player in seated if player.drafted_by_team_id == team.id):
                roster = rosters.get(seat.workspace_member_id)
                pick = picks.get(seat.id)
                if not shape.has_role_slots:
                    role = None
                elif pick is not None:
                    role = pick.target_role
                else:
                    role = draft_ranks.seat_role(roster, seat.captain_role)
                bucket = role or FLEX_SLOT_CODE
                uuid = str(seat.workspace_member_id)
                ratings = dict(roster.role_ranks) if roster is not None else {}
                # The rank the pick froze, all-flex too: the host's book can change hands before the last pick, and a
                # pick made stands on what it was worth (``drafted_rank`` re-derives a flex pick's live maximum, as a
                # tournament's export does). A captain, who has no pick, sits on their live rank.
                frozen = pick.target_rank_value if pick is not None else None
                ratings[bucket] = (
                    frozen if frozen is not None else (draft_ranks.drafted_rank(roster, role, shape, frozen=None) or 0)
                )
                players[uuid] = {
                    "name": (roster.display_name or roster.handle if roster is not None else None) or f"player-{uuid}",
                    "is_captain": seat.workspace_member_id == team.captain_workspace_member_id,
                    "is_flex": bool(roster is not None and roster.is_full_flex),
                    "role_preferences": [entry.role for entry in roster.playable] if roster is not None else [],
                    "ratings": ratings,
                }
                buckets.setdefault(bucket, []).append(uuid)
            lineup_teams.append(
                {
                    "id": team.draft_position,
                    "average_mmr": None,
                    "total_rating": None,
                    "format_violations": [],
                    "format_advisories": [],
                    "roster": buckets,
                    "captain_member_id": team.captain_workspace_member_id,
                }
            )
        variant: dict[str, Any] = {"teams": lineup_teams, "statistics": {}, "benched": []}
        _recompute_variant_stats(variant, players)
        document = {"source": "draft", "players": players, "feasibility": None, "variants": [variant]}
        if _uses_ranker(await self._host_config(session, game.host_user_id)):
            resolved = await self.ranks.resolve(
                session,
                workspace_id=game.workspace_id,
                discipline=game.discipline,
                members={roster.workspace_member_id: roster.player_id for roster in rosters.values()},
                roles=list(rated_role_codes(game.discipline)),
                order=MIX_ORDER,
                author_user_id=game.host_user_id,
                grid=await self.grid(session, game),
            )
            opens: dict[int, dict[str, int]] = {}
            for (member_id, role), rank in resolved.items():
                if rank.value is not None:
                    opens.setdefault(member_id, {})[role] = rank.value
            _stamp_open_ratings(document, opens)
        lobby.balance_result_json = document
        lobby.selected_variant_index = 0
        lobby.balanced_at = datetime.now(UTC)
        game.status = MixStatus.BALANCED
        await session.flush()
        # The overview moves this lobby Draft -> Ready, whichever pick finished it: a captain's, the clock's or a host's.
        await emit_pickup_mix_changed(session, game.workspace_id, custom_game_id=game.id, change="draft")

    async def _lineup_nodes(
        self,
        session: AsyncSession,
        *,
        game: models.CustomGame,
        lineup: Sequence[models.CustomGamePlayer],
        host_config: Any,
    ) -> tuple[dict[str, Any], list[SplitCandidate], dict[int, dict[str, int]]]:
        """The solver's input for these roster rows plus the same facts for the splitter.

        One mix is solved lobby by lobby, each lobby feeding in its own set of
        rows and reading them the same way. One pass over one set of reads: the
        ranks, role order and rotation priority the solver wants are exactly
        what the two-lobby splitter weighs, so the two cannot drift apart (and
        ``member_rank`` is not read twice for one lineup).

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
        # otherwise discard any ordering placed on `lineup` itself. At every
        # player's default 0.0 (no map history yet) the trim keeps its own order.
        histories_by_member = {
            history.member_id: history for history in await self._rotation_histories(session, game, lineup)
        }
        members = await self.members(
            session, game.workspace_id, [row.workspace_member_id for row in lineup], discipline=game.discipline
        )
        resolved = await self.ranks.resolve(
            session,
            workspace_id=game.workspace_id,
            discipline=game.discipline,
            members={member_id: member.player_id for member_id, member in members.items()},
            roles=list(rated_role_codes(game.discipline)),
            # ``MIX_ORDER`` puts the host's own book above the workspace canon: a
            # mix balances on this host's read of these players, not the official one.
            order=MIX_ORDER,
            author_user_id=game.host_user_id,
            grid=await self.grid(session, game),
        )
        open_ranks = {
            key: ranked.value for key, ranked in resolved.items() if ranked is not None and ranked.value is not None
        }
        ranker = _uses_ranker(host_config)
        ranks = (
            await self.ranker.effective_ratings(
                session, workspace_id=game.workspace_id, discipline=game.discipline, open_ranks=open_ranks
            )
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
            role_order = explicit_roles.get(row.id, []) if explicit else rated_role_codes(game.discipline)
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
                    "name": member.display_name or member.handle or f"player-{member.member_id}",
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
        role_mask = (await custom_game_slot_shape(session, game)).slots
        team_format, _ = await custom_game_format(session, game)
        ontology = await CatalogRoleRepository().ontology(
            session, discipline=game.discipline, workspace_id=game.workspace_id
        )
        try:
            result = await self.run_balance(
                {"players": player_nodes, "format_context": serialize_format_context(team_format, ontology)},
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
        # Every option of a fresh run is captained by its strongest seats; a re-formed lobby starts over (§7.2).
        lobby.balance_result_json = with_captains(result)
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

        ``scope="lobby"``: the non-benched pool minus whoever the other lobbies
        are already playing goes to the solver and lands in this lobby's
        document. ``scope="all"`` exists
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
        if scope == "all":
            # A reshuffle re-forms every lobby, so one live match is enough to refuse it.
            targets = list(await self.lobbies.list_for_game(session, game.id))
        else:
            targets = [await self._lobby(session, game, lobby_index)]
        # Refused before the pool is read: a frozen lobby answers 409 match_live, never empty_lineup.
        for lobby in targets:
            _refuse_live(lobby)
        # Re-forming a lobby ends its running draft (spec §9.5).
        await self.cancel_drafts(session, game, [lobby.lobby_index for lobby in targets])
        roster = list(await self.roster.list_for_game(session, game.id))
        # An away player is in no lobby's seated set, must-play or not; the mark waits for their return (§7.4).
        lineup = [row for row in roster if row.participation != MixParticipation.BENCHED and not row.away]
        if not lineup:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
        if scope == "all":
            await self._balance_all(session, game, lineup)
        else:
            [lobby] = targets
            candidates = await self._lobby_candidates(session, game, lineup, lobby_index)
            if not candidates:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_lineup")
            await self._solve_lobby(session, game, lobby, candidates)
            # Benching the overflow is the one-lobby answer. With more lobbies the
            # players left out WAIT for the next one, and a
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
        role_mask = (await custom_game_slot_shape(session, game)).slots
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
        :meth:`start_match` fixes it on the match and :meth:`record_outcome` clears it.
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
        if map_id is not None and not await self.maps.exists(session, id=map_id, discipline=game.discipline):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")
        lobby = await self._lobby(session, game, lobby_index)
        _refuse_live(lobby)
        lobby.next_map_id = map_id
        await session.flush()
        return game

    async def set_lobby_code(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
        lobby_code: str | None,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """The in-game lobby's join code, or ``None`` (or blank) to clear it.

        Kept across matches until the host changes it, and writable while a match is live: a lobby re-created
        mid-match needs its new code out at once.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobby = await self._lobby(session, game, lobby_index)
        lobby.lobby_code = lobby_code or None
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
        _refuse_live(lobby)
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
        row = await self.workspace_configs.config_with_guild(session, workspace_id)
        if row is None:
            return None, None
        raw, guild_id = row
        return _mix_channel_id(raw), guild_id

    async def workspace_discord_channel_id(self, session: AsyncSession, workspace_id: int) -> int | None:
        """The workspace-wide mix channel: the ONLY channel a mix ever posts to.

        Kept in the workspace balancer config blob
        (``balancer.workspace_config.config_json``) next to the other
        workspace-scoped mix knobs.
        """
        config = await self.workspace_configs.get_by_workspace(session, workspace_id)
        return _mix_channel_id(config.config_json if config is not None else None)

    async def voice_config(self, session: AsyncSession, workspace_id: int) -> MixVoiceConfig:
        """The workspace's guild, voice category and general voices, in one read."""
        row = await self.workspace_configs.config_with_guild(session, workspace_id)
        return voice_config_from(row[0], row[1]) if row is not None else MixVoiceConfig(None, None, frozenset())

    async def set_voice_channels(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        general_voice_channel_id: int | None,
        lobbies: Sequence[tuple[int, int | None, int | None]],
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """The mix's own voices: the general one, and the two of every listed lobby."""
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        game.general_voice_channel_id = general_voice_channel_id
        for lobby_index, team1, team2 in lobbies:
            lobby = await self._lobby(session, game, lobby_index)
            lobby.team1_voice_channel_id = team1
            lobby.team2_voice_channel_id = team2
        await session.flush()
        return game

    async def voice_options(
        self,
        session: AsyncSession,
        *,
        discord: DiscordClient,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> dict[str, Any]:
        """The voices this mix may pick: the category's general and team voices, with the bot's gaps."""
        await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        voice = await self.voice_config(session, workspace_id)
        out: dict[str, Any] = {
            "category_id": voice.category_id,
            "category_missing_permissions": None,
            "general": [],
            "team": [],
            "error": None,
        }
        if voice.guild_id is None or voice.category_id is None:
            return out
        try:
            channels = await discord.guild_channels(voice.guild_id)
        except DiscordError as exc:
            return {**out, "error": str(exc)}
        category = next((c for c in channels if c["type"] == "category" and c["id"] == voice.category_id), None)
        if category is None:
            return {**out, "error": "category_not_found"}
        voices = [c for c in channels if c["type"] == "voice" and c.get("category_id") == voice.category_id]
        picked = [
            {"id": c["id"], "name": c["name"], "missing_permissions": c.get("missing_permissions")} for c in voices
        ]
        return {
            **out,
            "category_missing_permissions": category.get("missing_permissions"),
            "general": [c for c in picked if c["id"] in voice.general_ids],
            "team": [c for c in picked if c["id"] not in voice.general_ids],
        }

    async def discord_links(self, session: AsyncSession, member_ids: Sequence[int]) -> dict[int, str]:
        """The Discord id of every one of those workspace members who linked an account.

        One batched read rather than a lookup per seat. A member with no linked
        Discord simply does not ping; the lineup is not worth failing over
        somebody's unlinked account.
        """
        ids = _uniq(member_ids)
        if not ids:
            return {}
        rows = await self.workspace_members.discord_ids(session, ids)
        return {member_id: str(discord_id) for member_id, discord_id in rows if discord_id}

    async def discord_mentions(self, session: AsyncSession, member_ids: Sequence[int]) -> list[str]:
        """The Discord ids of those members who linked an account, in ``member_ids`` order."""
        links = await self.discord_links(session, member_ids)
        return [links[member_id] for member_id in _uniq(member_ids) if member_id in links]

    async def _voice_lobbies(
        self, session: AsyncSession, game: models.CustomGame, lobby_index: int | None
    ) -> list[models.CustomGameLobby]:
        if lobby_index is not None:
            return [await self._lobby(session, game, lobby_index)]
        return list(await self.lobbies.list_for_game(session, game.id))

    async def _voice_setup(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
        actor_is_superuser: bool,
    ) -> tuple[models.CustomGame, MixVoiceConfig]:
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        config = await self.voice_config(session, workspace_id)
        if config.guild_id is None or config.category_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="voice_not_configured")
        return game, config

    @staticmethod
    async def _ask_discord(
        discord: DiscordClient,
        config: MixVoiceConfig,
        *,
        moves: Sequence[Mapping[str, str]],
        drain: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        try:
            return await discord.voice_move(config.guild_id, category_id=config.category_id, moves=moves, drain=drain)
        except DiscordError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="discord_unavailable") from exc

    async def voice_move(
        self,
        session: AsyncSession,
        *,
        discord: DiscordClient,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int | None,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> dict[str, Any]:
        """Every seated player of the lobby (or of every lobby) into their team's voice."""
        game, config = await self._voice_setup(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobbies = await self._voice_lobbies(session, game, lobby_index)
        shaped = [
            LobbyVoice(
                lobby.lobby_index,
                seated_teams(lobby.balance_result_json, lobby.selected_variant_index),
                (snowflake(lobby.team1_voice_channel_id), snowflake(lobby.team2_voice_channel_id)),
            )
            for lobby in lobbies
        ]
        member_ids = [member for lobby in shaped for team in lobby.teams for member in team]
        plan = plan_move(config, shaped, await self.discord_links(session, member_ids))
        results = await self._ask_discord(discord, config, moves=plan.moves, drain=None) if plan.moves else []
        # The board's own names: every seat's uuid resolves in its document's player map.
        names = {
            int(uuid): str(player.get("name"))
            for lobby in lobbies
            for uuid, player in _lobby_players(as_lobby_document(lobby.balance_result_json)).items()
            if str(uuid).isdigit() and isinstance(player, Mapping) and player.get("name")
        }
        return report(plan, results, names)

    async def voice_return(
        self,
        session: AsyncSession,
        *,
        discord: DiscordClient,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int | None,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> dict[str, Any]:
        """Everyone in the lobby's team voices (players or not) back into the mix's general voice."""
        game, config = await self._voice_setup(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        general = snowflake(game.general_voice_channel_id)
        if general is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="general_voice_not_configured")
        if general not in config.general_ids:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="general_voice_outside_category")
        sources = [
            channel
            for lobby in await self._voice_lobbies(session, game, lobby_index)
            for channel in (snowflake(lobby.team1_voice_channel_id), snowflake(lobby.team2_voice_channel_id))
            if channel is not None and channel not in config.general_ids
        ]
        if not sources:
            return {"moved": 0, "results": []}
        results = await self._ask_discord(
            discord, config, moves=[], drain={"channel_ids": sources, "to_channel_id": general}
        )
        return report(VoicePlan(moves=[], rows=[], member_by_discord={}), results, {})

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
    ) -> tuple[int, list[DiscordCommandEvent]]:
        """The channel to post to plus the command that posts one lobby's lineup.

        The row it will become is claimed here (``slot='lineup:<lobby>:<match>'``),
        so the mix page can show the post and the host can take it down again;
        publishing is the RPC layer's job -- that is where the broker is -- so
        this returns the command. The row carries no card: discord-service
        renders the matchup from :meth:`discord_view` -- the lobby's shown option,
        which the pager keeps the same for everyone, so ``variant_index`` (the
        option on the host's screen) only has to exist -- and takes the voice
        buttons off the lobby's older cards itself.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
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
        # Per lobby: two lobbies keep two paces, so "game 5" in one is not
        # "game 5" in the other.
        activity = await self.mix_rounds.activity_for_lobbies(session, game.id)
        command = await discord_messages.send_command(
            session,
            subject=mix_subject(game.id),
            # One row per lineup the mix posts: the lobby it belongs to and the
            # match it announces, which is what the page labels the post with.
            slot=lineup_slot(lobby_index, activity.get(lobby_index, (0, None))[0] + 1),
            kind="mix.lineup",
            workspace_id=workspace_id,
            channel_id=channel_id,
        )
        return channel_id, [] if command is None else [command]

    async def _lineup_view(
        self,
        session: AsyncSession,
        game: models.CustomGame,
        lobby: models.CustomGameLobby | None,
        *,
        lobby_index: int,
        match_number: int,
        matches_recorded: int,
        points_per_win: int | None,
    ) -> dict[str, Any]:
        """One lineup card's facts: the lobby's shown option as it stands right now.

        ``current`` is false -- and the bot leaves that card as it is -- once the
        match it announces is recorded (the next shuffle belongs to the next
        post, not to the played card), when the lobby or its shown option is
        gone, and for a finished mix, which keeps its cards as they ended.
        """
        out: dict[str, Any] = {
            "lobby_index": lobby_index,
            "match_number": match_number,
            "current": False,
            "variant": None,
            "players": None,
            "team_names": None,
            "next_map": None,
            "map_image": None,
            "lobby_code": None,
            "points_per_win": None,
            "lobby_label": None,
            "mention_user_ids": [],
            "voice_target": f"{game.id}-{lobby_index}",
        }
        if game.status in _TERMINAL or lobby is None or match_number <= matches_recorded:
            return out
        result = as_lobby_document(lobby.balance_result_json)
        variants = result.get("variants") if isinstance(result, dict) else None
        index = lobby.selected_variant_index
        if (
            not isinstance(variants, list)
            or not (0 <= index < len(variants))
            or not isinstance(variants[index], Mapping)
        ):
            return out
        next_map: list[str | None] | None = None
        map_image: str | None = None
        if lobby.next_map_id is not None:
            # The card names the mode next to the map.
            row = await self.maps.get_map_with_mode(session, lobby.next_map_id, discipline=game.discipline)
            if row is not None:
                next_map = [row.name, row.parent.name if row.parent is not None else None]
                map_image = row.image_path or None
        team_names = await self._lobby_team_names(session, game.id, lobby_index)
        return {
            **out,
            "current": True,
            "variant": variants[index],
            "players": _lobby_players(result),
            "team_names": {str(team): name for team, name in team_names.items()},
            "next_map": next_map,
            "map_image": map_image,
            "lobby_code": lobby.lobby_code,
            "points_per_win": points_per_win,
            # Every lobby posts into the same channel, so a multi-lobby mix says
            # which one this lineup is; a one-lobby mix has nothing to qualify.
            "lobby_label": LOBBY_LETTERS[lobby_index] if game.lobby_count > 1 else None,
            # Everyone this matchup seats, so the lobby hears about it.
            "mention_user_ids": await self.discord_mentions(
                session, sorted(seated_member_ids(lobby.balance_result_json, index))
            ),
        }

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

        A swap that moves a team's captain re-captains both teams (``with_captains``).
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobby = await self._lobby(session, game, lobby_index)
        _refuse_live(lobby)
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

        captains = {str(teams[index].get("captain_member_id")) for index in (first_team, second_team)}
        first_bucket = teams[first_team]["roster"][first_role]
        second_bucket = teams[second_team]["roster"][second_role]
        first_bucket[first_pos], second_bucket[second_pos] = second_bucket[second_pos], first_bucket[first_pos]
        if captains & {first_uuid, second_uuid}:
            # A captain changed teams: both teams are captained afresh by their strongest seat (§7.2).
            for index in (first_team, second_team):
                teams[index]["captain_member_id"] = None
        with_captains(result)
        _recompute_variant_stats(variant, _lobby_players(result))

        lobby.balance_result_json = result
        await session.flush()
        return game

    async def set_captain(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
        workspace_member_id: int,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Make one seated player their team's captain in the option the lobby is showing ("Make captain").

        The shown option, not an index the caller names: the crown is read out with the matchup, and the pager
        that picks it is the lobby's own. 404 when that option does not seat the player.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobby = await self._lobby(session, game, lobby_index)
        _refuse_live(lobby)
        result = with_captains(copy.deepcopy(as_lobby_document(lobby.balance_result_json)))
        index = lobby.selected_variant_index
        team_index = next(
            (team for team, members in enumerate(seated_teams(result, index)) if workspace_member_id in members), None
        )
        if team_index is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not seated in this option")
        result["variants"][index]["teams"][team_index]["captain_member_id"] = workspace_member_id
        lobby.balance_result_json = result
        await session.flush()
        return game

    async def _shift_host_ranks(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        discipline: str,
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
            discipline=discipline,
            member_ids=[member_id for member_id, *_rest in shifts],
            author_user_id=host_user_id,
        )
        rated = set(rated_role_codes(discipline))
        for member_id, role, fallback, delta in shifts:
            if role not in rated:
                continue  # An open slot is no role: it moves no book.
            base = current.get((member_id, role), fallback)
            await self.ranks.set_ranks(
                session,
                workspace_id=workspace_id,
                discipline=discipline,
                workspace_member_id=member_id,
                ranks={role: base + delta},
                author_user_id=host_user_id,
            )

    async def _move_by_ranker(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        discipline: str,
        host_user_id: int,
        ranker: Ranker,
        winner: int | None,
        seats: Sequence[Sequence[tuple[int, str, int, RatedSeat]]],
    ) -> dict[int, int]:
        """Move each seat's open rank in the host's book by the ranker's formula; ``member -> applied delta``.

        ``seats`` per team: ``(member_id, role, open rank at balance time, hidden before/after)``. The base is
        the book's current value, like the points path; the applied delta is frozen on the round so undo gives
        back exactly it.
        """
        current = await self.ranks.list_layer(
            session,
            workspace_id=workspace_id,
            discipline=discipline,
            member_ids=[seat[0] for team in seats for seat in team],
            author_user_id=host_user_id,
        )
        deltas: dict[int, int] = {}
        rated = set(rated_role_codes(discipline))
        for team_index, team in enumerate(seats):
            outcome = 0 if winner is None else 1 if winner == team_index + 1 else -1
            for member_id, role, open_rank, (old, new) in team:
                if role not in rated:
                    continue  # An open slot is no role: it moves no book.
                base = current.get((member_id, role), open_rank)
                moved = round(base + ranker.open_delta(base, old, new, outcome))
                deltas[member_id] = moved - base
                if moved != base:
                    await self.ranks.set_ranks(
                        session,
                        workspace_id=workspace_id,
                        discipline=discipline,
                        workspace_member_id=member_id,
                        ranks={role: moved},
                        author_user_id=host_user_id,
                    )
        return deltas

    async def ban_opener(
        self, session: AsyncSession, game: models.CustomGame, lobby: models.CustomGameLobby
    ) -> int | None:
        """The lineup team (0/1) that bans first in this lobby's next match (spec §8.3); ``None`` without bans or a
        two-team lineup. Start and the detail read ask this one question, so the dialog shows what Start does."""
        if (
            game.hero_ban_preset is None
            or len(seated_teams(lobby.balance_result_json, lobby.selected_variant_index)) != 2
        ):
            return None
        result, teams = _two_team_lineup(lobby)
        _seats, players, _opens = _lineup_seats(result, teams)
        previous: list[tuple[frozenset[int], float]] | None = None
        last = await self.mix_rounds.newest_id_for_lobby(session, game.id, lobby.lobby_index)
        if last is not None:
            by_slot: dict[int, tuple[set[int], float]] = {}
            for row in await self.mix_rounds.seats(session, workspace_id=game.workspace_id, encounter_id=last):
                by_slot.setdefault(row.slot, (set(), float(row.own_score)))[0].add(row.workspace_member_id)
            if len(by_slot) == 2:
                previous = [(frozenset(by_slot[slot][0]), by_slot[slot][1]) for slot in sorted(by_slot)]
        return ban_opener([[(member, rating) for member, _code, rating in team] for team in players], previous)

    async def start_match(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
        flip_opener: bool = False,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Start the lobby's match on the option it is showing (spec §5.1).

        An open encounter of the mix with both teams' rosters -- the captains flagged, both seats ready -- and one game
        on the lobby's next map. From here the lineup is frozen (``_refuse_live``) until :meth:`record_outcome` or
        :meth:`cancel_match`. An away player still seated in the lineup plays: the board warns before Start, it does
        not block. The voices are the RPC layer's (it holds the Discord client).

        With a hero ban preset the opener (``ban_opener``, flipped by ``flip_opener``) sits in slot 1, the preset is
        frozen on the lobby (``live_ban_preset``: a header edit meanwhile does not change the room) and tournament-service
        is asked to open the room; without one the lineup order stands and the flip is ignored. Each captain also gets
        one DM linking the lobby's room (``mix.ban_room_opened``).
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobby = await self._lobby(session, game, lobby_index)
        _refuse_live(lobby)
        result, teams = _two_team_lineup(lobby)
        team_seats, _players, _opens = _lineup_seats(result, teams)
        names = await self._lobby_team_names(session, game.id, lobby_index)
        lineup_names = (names.get(0) or "Team 1", names.get(1) or "Team 2")
        opener = await self.ban_opener(session, game, lobby)
        first = 0 if opener is None else opener ^ int(flip_opener)
        order = (first, 1 - first)
        encounter = await self.open_match(
            session,
            MixMatchDraft(
                custom_game_id=game.id,
                workspace_id=game.workspace_id,
                discipline=game.discipline,
                scoring_rule_id=game.scoring_rule_id,
                map_id=lobby.next_map_id,
                names=(lineup_names[order[0]], lineup_names[order[1]]),
                seats=(tuple(team_seats[order[0]]), tuple(team_seats[order[1]])),
                bans=opener is not None,
            ),
        )
        lobby.live_encounter_id = encounter.id
        lobby.live_ban_preset = game.hero_ban_preset
        if opener is not None:
            # The room opens on this very start: each team's captain hears it once (spec §12.1 R3-3).
            captains = [team.get("captain_member_id") for team in teams if isinstance(team, dict)]
            members = [member for member in captains if isinstance(member, int)]
            accounts = await self.workspace_members.auth_user_ids(session, members)
            for member in members:
                await notify_mix_captain(
                    session,
                    kind="mix.ban_room_opened",
                    game=game,
                    lobby_index=lobby_index,
                    auth_user_id=accounts.get(member),
                    dedupe_key=f"mix_ban_room:{encounter.id}:{member}",
                )
        await session.flush()
        return game

    async def _drop_live_match(self, session: AsyncSession, lobby: models.CustomGameLobby) -> None:
        """Delete the lobby's live encounter (its game and rosters cascade) and release the lobby."""
        encounter_id, lobby.live_encounter_id, lobby.live_ban_preset = lobby.live_encounter_id, None, None
        await session.flush()
        await self.mix_rounds.delete_round(session, encounter_id)

    async def cancel_match(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Throw the lobby's live match away (spec §5.1): nothing is recorded, no rank, pin or map moves, and the
        lineup is Ready to start again. 409 ``no_live_match`` when nothing was started."""
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        lobby = await self._lobby(session, game, lobby_index)
        if lobby.live_encounter_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_live_match")
        await self._drop_live_match(session, lobby)
        await session.flush()
        return game

    async def record_outcome(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int = 0,
        winner: int | None,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Record the result of the lobby's live match (spec §5.1).

        Repeatable -- a mix records many matches before its host calls :meth:`close`, and the frozen snapshot is the
        only record of each. The seats are the lineup the match was started on (frozen since); the map was fixed at
        Start. The HOST's rating mode decides how both teams' host-authored ranks move: ``points_per_win`` (when set,
        and only for a decided match) or the mix ranker, seat by seat. The workspace's hidden ratings advance either
        way. Every seat that played redeems its ``MUST_PLAY`` pin back to ``POOL`` -- the pin promises one seat, not
        every seat forever. ``winner`` names the lineup team (1 or 2), whichever slot Start seated it in. The lobby's
        next map and frozen ban preset are cleared and the lobby is Ready again. 409 ``no_live_match`` when nothing was
        started.
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
        if lobby.live_encounter_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_live_match")
        result, teams = _two_team_lineup(lobby)
        _seats, team_players, open_ranks = _lineup_seats(result, teams)

        names = await self._lobby_team_names(session, game.id, lobby_index)
        # The host's knobs, not the mix's and not the recording co-host's -- the
        # book being moved is the host's own (see ``_shift_host_ranks``).
        host_config = await self._host_config(session, game.host_user_id)
        points_per_win = _points_per_win(host_config)
        roster = list(await self.roster.list_for_game(session, game.id))
        # Whoever was on the floor next door neither played this round nor sat it out.
        busy = await self._other_lobby_seated(session, game, lobby_index)
        # Away, they neither played nor sat out either: rotation skips the round for them like for a busy one (§7.4).
        busy |= {row.workspace_member_id for row in roster if row.away}

        participant_ids = {member_id for team in team_players for member_id, _, _ in team}
        for row in roster:
            if row.participation == MixParticipation.MUST_PLAY and row.workspace_member_id in participant_ids:
                row.participation = MixParticipation.POOL

        ranker, rated = await self.ranker.rate_match(
            session, workspace_id=workspace_id, discipline=game.discipline, teams=team_players, winner=winner
        )
        deltas: dict[int, int] = {}
        if game.host_user_id is not None and _uses_ranker(host_config):
            deltas = await self._move_by_ranker(
                session,
                workspace_id=workspace_id,
                discipline=game.discipline,
                host_user_id=game.host_user_id,
                ranker=ranker,
                winner=winner,
                seats=[
                    [
                        (member_id, role, open_rank, hidden)
                        for (member_id, role, _rating), open_rank, hidden in zip(
                            team_players[index], open_ranks[index], rated[index], strict=True
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
                discipline=game.discipline,
                host_user_id=game.host_user_id,
                shifts=[
                    (member_id, role, rating, points_per_win if index == winning_index else -points_per_win)
                    for index in range(2)
                    for member_id, role, rating in team_players[index]
                ],
            )

        await self.write_result(
            session,
            MixResultDraft(
                encounter_id=lobby.live_encounter_id,
                lobby_index=lobby_index,
                names=(names.get(0) or "Team 1", names.get(1) or "Team 2"),
                lineup_first_team=frozenset(member for member, _code, _rating in team_players[0]),
                winner=winner,
                # Frozen on the round so undo rolls back what was applied, not what the knob says by then.
                points_per_win_applied=points_per_win if (points_per_win and winner in (1, 2)) else None,
                rank_deltas=deltas,
                busy=busy,
                recorder_player_id=await self.players.get_id_by_auth_user_id(session, actor_user_id),
            ),
        )
        lobby.live_encounter_id = None
        lobby.live_ban_preset = None
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
        round_ = await self.mix_rounds.get_for_game(session, game.id, match_id)
        if round_ is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
        if await self.mix_rounds.newest_id_for_lobby(session, game.id, round_.lobby_index) != round_.encounter_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Only the most recent match of this lobby can be undone"
            )
        applied = round_.points_per_win_applied or 0
        shifts = [
            (
                seat.workspace_member_id,
                seat.role,
                seat.rank,
                (
                    (-applied if winner_slot(seat.slot, seat.own_score, seat.other_score) == seat.slot else applied)
                    if applied
                    else 0
                )
                - (seat.rank_delta_applied or 0),
            )
            for seat in await self.mix_rounds.seats(
                session, workspace_id=game.workspace_id, encounter_id=round_.encounter_id
            )
            # A seat balanced without a role has no book entry to move.
            if seat.role is not None
        ]
        if game.host_user_id is not None:
            await self._shift_host_ranks(
                session,
                workspace_id=workspace_id,
                discipline=game.discipline,
                host_user_id=game.host_user_id,
                shifts=shifts,
            )
        await self.mix_rounds.delete_round(session, round_.encounter_id)
        await session.flush()
        await self.ranker.rebuild(session, game.workspace_id)
        return game

    async def list_matches(
        self, session: AsyncSession, *, workspace_id: int, custom_game_id: int
    ) -> list[models.CustomGameRound]:
        """Every round recorded for this mix, newest first -- read is open to
        any workspace member, same as :meth:`get` (no host gate: watching the
        history is not writing it).
        """
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        return list(await self.mix_rounds.list_for_custom_game(session, game.id))

    async def round_map_info(self, session: AsyncSession, map_ids: Iterable[int]) -> dict[int, tuple[str, str | None]]:
        """``{map_id: (name, image_path)}`` for the match history, in one read; no ids, no query."""
        ids = set(map_ids)
        if not ids:
            return {}
        return {row.id: (row.name, row.image_path) for row in await self.maps.names_and_images(session, ids)}

    async def mix_stats(
        self, session: AsyncSession, *, workspace_id: int, discipline: str | None, since: datetime | None
    ) -> dict[str, Any]:
        """Per-member win/loss record across this workspace's mixes: one ``discipline``'s, or every game's.

        Workspace-wide on purpose: the scoreboard answers "how does this person
        do in our mixes", which no single mix can say. ``discipline=None`` keeps the
        cross-game tally (a member's identity then is their first handle in any game's
        provider, in installed-game order) and no per-role split -- role codes of different
        games are different roles; a code narrows seats, roles and identity to that game.
        Names come from the *current* roster, so a member who has since left keeps their
        record and loses only their label (and ``player_id``, the global player the
        client merges one person's rows across communities by).

        ``mixes``/``matches`` count the distinct mixes and rounds behind the same seats,
        so the totals always describe exactly the window the members were scored over.
        """
        rows = await self.mix_rounds.seats(session, workspace_id=workspace_id, discipline=discipline, since=since)
        seats = [
            SeatOutcome(
                member_id=row.workspace_member_id,
                role=row.role,
                match_id=row.encounter_id,
                played_at=row.created_at,
                recorded_at=row.recorded_at,
                outcome=outcome_for(row.own_score, row.other_score),
            )
            for row in rows
        ]
        stats = aggregate_mix_stats(seats)
        totals = {
            "mixes": len({row.custom_game_id for row in rows}),
            "matches": len({row.encounter_id for row in rows}),
        }
        if not stats:
            return {"members": [], **totals}

        providers = (
            [DISCIPLINES[discipline].identity_provider]
            if discipline is not None
            else list(dict.fromkeys(spec.identity_provider for spec in DISCIPLINES.values()))
        )
        members: dict[int, RosterMember] = {}
        for provider in providers:
            found = await self.load_roster(
                session,
                workspace_id=workspace_id,
                provider=provider,
                member_ids=[entry.member_id for entry in stats],
            )
            for member_id, member in found.items():
                known = members.get(member_id)
                if known is None or (known.identity is None and member.identity is not None):
                    members[member_id] = member
        dumped = [
            {
                "workspace_member_id": entry.member_id,
                "player_id": member.player_id if member is not None else None,
                "display_name": member.display_name if member is not None else None,
                "identity": member.identity.model_dump() if member is not None and member.identity else None,
                "games": entry.games,
                "wins": entry.wins,
                "losses": entry.losses,
                "draws": entry.draws,
                "win_rate": entry.win_rate,
                "streak": entry.streak,
                "last_played_at": entry.last_played_at.isoformat() if entry.last_played_at is not None else None,
                "by_role": (
                    None
                    if discipline is None
                    else {
                        role: {"games": tally.games, "wins": tally.wins, "losses": tally.losses, "draws": tally.draws}
                        for role, tally in entry.by_role.items()
                    }
                ),
                "form": [
                    {
                        "outcome": seat.outcome,
                        "match_id": seat.match_id,
                        "played_at": seat.played_at.isoformat(),
                        "recorded_at": seat.recorded_at.isoformat(),
                    }
                    for seat in entry.form
                ],
            }
            for entry, member in ((entry, members.get(entry.member_id)) for entry in stats)
        ]
        return {"members": dumped, **totals}

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
        one-lobby mix.
        """
        rounds = list(await self.mix_rounds.list_for_custom_game(session, game.id))
        rounds.reverse()  # newest-first -> chronological, oldest round first
        played = [{m.workspace_member_id for m in round_.members if not m.busy} for round_ in rounds]
        busy = [{m.workspace_member_id for m in round_.members if m.busy} for round_ in rounds]
        return [
            PlayerHistory(
                member_id=row.workspace_member_id,
                # Only maps recorded after this row joined the pool count --
                # a map played before they signed up is not one they sat out.
                played=tuple(
                    row.workspace_member_id in seated
                    for round_, seated, elsewhere in zip(rounds, played, busy, strict=True)
                    if (row.created_at is None or round_.encounter.created_at >= row.created_at)
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
        # Away players are outside the queue until they are back (§7.4).
        roster = [row for row in await self.roster.list_for_game(session, game.id) if not row.away]
        if not roster:
            return []

        candidates = await self._lobby_candidates(session, game, roster, lobby_index)
        if not candidates:
            return []

        histories = await self._rotation_histories(session, game, candidates)

        role_mask = (await custom_game_slot_shape(session, game)).slots
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
        ``record_outcome`` stay recorded; this only stops further writes. Every
        live match and every running draft is cancelled first.
        """
        game = await self._writable(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        # A mix that is over plays nothing: every live match is thrown away first (spec §5.1), and every running
        # draft is cancelled (spec §9.5).
        for lobby in await self.lobbies.list_for_game(session, game.id):
            if lobby.live_encounter_id is not None:
                await self._drop_live_match(session, lobby)
        await self.cancel_drafts(session, game, None)
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
        # A mix that is over plays nothing: every live match is thrown away first (spec §5.1), and every running
        # draft is cancelled (spec §9.5).
        for lobby in await self.lobbies.list_for_game(session, game.id):
            if lobby.live_encounter_id is not None:
                await self._drop_live_match(session, lobby)
        await self.cancel_drafts(session, game, None)
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
        ``custom_game_player`` and every round encounter cascade on the mix
        at the DB level, so deleting the game row is enough.

        Its Discord messages do not cascade -- ``discord_message`` is filed by
        subject, not by a foreign key -- and a mix that no longer exists has no
        business leaving cards in the channel, so they are all marked for
        deletion here. The caller publishes the returned commands after the
        commit that destroys the mix.

        The mix row is locked first (``FOR UPDATE``), like every host write in ``_writable`` -- mix, then its
        messages -- so a hard delete racing ``delete_discord_post`` waits for it instead of deadlocking. Not through
        ``_writable`` itself: a completed or cancelled mix is deleted too.
        """
        game = await self.games.get(session, custom_game_id, for_update=True)
        if game is None or game.workspace_id != workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        commands = await discord_messages.delete_commands(
            session, await discord_messages.repository.for_subject(session, mix_subject(custom_game_id))
        )
        rule = await self.scoring_rules.get(session, game.scoring_rule_id)
        await self.games.delete(session, game)
        # The rule is the mix's alone; its round encounters went with the mix.
        if rule is not None:
            await self.scoring_rules.delete(session, rule)
        return commands


custom_game_service = CustomGameService()
