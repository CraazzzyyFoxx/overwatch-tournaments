from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.enums import (
    CasualTeamSide,
    HeroClass,
    MixParticipation,
    MixRoleSelectionMode,
    MixStatus,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.domain.roster_shape import resolve_roster_shape
from shared.repository import (
    CasualMatchRepository,
    CasualPlayerRepository,
    CasualTeamRepository,
    CustomGameCoHostRepository,
    CustomGamePlayerRepository,
    CustomGamePlayerRoleRepository,
    CustomGameRepository,
    CustomGameRoleSlotRepository,
    CustomGameTeamNameRepository,
)
from shared.schemas.roster_slots import RosterShapeRead, normalize_roster_slots
from shared.services.division_grid.access import get_effective_division_grid
from shared.services.member_rank import MIX_ORDER, MemberRankService, member_rank_service
from shared.services.roster_shape_access import get_workspace_roster_slots
from shared.services.workspace_roster import (
    RosterMember,
    hosts_by_user_id,
    list_roster,
    workspace_member_user_ids,
)
from src.domain.mix_rotation import PlayerHistory, RotationRecommendation, recommend_rotation, rotation_priority
from src.services.balancer.config.public_contract import normalize_config_overrides
from src.services.balancer.role_naming import role_slot_code
from src.services.balancer.solver import run_mix_balance as _run_balance

__all__ = ("CustomGameService", "custom_game_service")

_TERMINAL = frozenset({MixStatus.COMPLETED, MixStatus.CANCELLED})
#: Plenty for any pickup mix (2-3 teams in practice); guards against a
#: malformed payload turning into an unbounded dict.
_MAX_TEAMS = 8
#: Plenty for any pickup mix; guards a malformed payload from growing the
#: co-host list without bound.
_MAX_CO_HOSTS = 16
_MAX_TEAM_NAME_LEN = 60
#: Upper bound on the host's configurable rank-adjustment-per-win. Generous
#: for any plausible rank scale, guards against a fat-fingered config wrecking
#: the rank book in one recorded match.
_MAX_POINTS_PER_WIN = 1000
#: A roster row owns only its lineup state. A rank correction goes into the
#: host's own layer of ``member_rank``, so it outlives the game it was made in.
_PLAYER_PATCH_FIELDS = frozenset({"participation", "roles", "is_flex"})


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
    payload = result
    if isinstance(result, dict):
        variants = result.get("variants")
        if isinstance(variants, list) and variants:
            payload = variants[0]
    if not isinstance(payload, dict):
        return

    by_uuid = {str(row.workspace_member_id): row for row in roster}
    benched = payload.get("benched_players")
    if not isinstance(benched, list):
        return
    for player in benched:
        if not isinstance(player, dict):
            continue
        uuid = player.get("uuid")
        row = by_uuid.get(str(uuid)) if uuid is not None else None
        if row is not None:
            row.participation = MixParticipation.BENCHED


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
                if isinstance(entry, Mapping) and str(entry.get("uuid")) == uuid:
                    return team_index, role, position
    return None


def _recompute_variant_stats(variant: dict[str, Any]) -> None:
    """Re-derive the read-only verdict from a manually edited roster.

    Mirrors the solver's own arithmetic for the three metrics that are pure
    functions of the roster (``calculate_team_stats`` / ``calculate_objective_breakdown``
    in ``tournament_balancer``): a team's average is the mean of its seats' ratings, the
    spread is the gap between the strongest and weakest team's *total* rating,
    and the standard deviation is the sample stdev of the teams' averages.

    ``composite_score`` is deliberately NOT one of these: it is a knee-score
    normalised against the whole Pareto archive the solver searched for that
    run, meaningless for a single hand-edited arrangement with no archive to
    normalise against -- so it is cleared rather than faked.
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
                for entry in entries:
                    if not isinstance(entry, Mapping):
                        continue
                    rating = entry.get("assigned_rating")
                    if isinstance(rating, int | float):
                        ratings.append(float(rating))
                    preferences = entry.get("role_preferences") or []
                    is_flex = entry.get("is_flex") is True
                    if not is_flex and preferences and preferences[0] != role:
                        off_role_count += 1
        total = sum(ratings)
        team["average_mmr"] = (total / len(ratings)) if ratings else None
        team_totals.append(total)
        if ratings:
            team_means.append(total / len(ratings))

    statistics = dict(variant.get("statistics") or {})
    statistics["composite_score"] = None
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
        player_roles: CustomGamePlayerRoleRepository = CustomGamePlayerRoleRepository(),
        team_names: CustomGameTeamNameRepository = CustomGameTeamNameRepository(),
        role_slots: CustomGameRoleSlotRepository = CustomGameRoleSlotRepository(),
        casual_matches: CasualMatchRepository = CasualMatchRepository(),
        casual_teams: CasualTeamRepository = CasualTeamRepository(),
        casual_players: CasualPlayerRepository = CasualPlayerRepository(),
        ranks: MemberRankService | None = None,
        load_roster=list_roster,
        load_hosts=hosts_by_user_id,
        load_member_user_ids=workspace_member_user_ids,
        run_balance=_run_balance,
    ) -> None:
        self.games = games
        self.roster = roster
        self.co_hosts = co_hosts
        self.player_roles = player_roles
        self.team_names = team_names
        self.role_slots = role_slots
        self.casual_matches = casual_matches
        self.casual_teams = casual_teams
        self.casual_players = casual_players
        self.ranks = ranks if ranks is not None else member_rank_service
        self.load_roster = load_roster
        self.load_hosts = load_hosts
        self.load_member_user_ids = load_member_user_ids
        self.run_balance = run_balance

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

    async def get(self, session: AsyncSession, *, workspace_id: int, custom_game_id: int) -> models.CustomGame:
        game = await self.games.get(session, custom_game_id)
        if game is None or game.workspace_id != workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game not found")
        return game

    async def list(self, session: AsyncSession, *, workspace_id: int) -> list[models.CustomGame]:
        return list(await self.games.list_for_workspace(session, workspace_id))

    async def _writable(
        self, session: AsyncSession, *, workspace_id: int, custom_game_id: int, actor_user_id: int
    ) -> models.CustomGame:
        game = await self.get(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
        if actor_user_id != game.host_user_id:
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
        balancer_config: Mapping[str, Any] | None = None,
    ) -> models.CustomGame:
        _require_host(actor_user_id, host_user_id)
        trimmed = name.strip() if isinstance(name, str) else ""
        if not trimmed:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name is required")
        ids = _uniq(member_ids)
        members = await self.members(session, workspace_id, ids)
        game = models.CustomGame(
            workspace_id=workspace_id,
            host_user_id=host_user_id,
            name=trimmed,
            status=MixStatus.DRAFT,
            balancer_config_json=(normalize_config_overrides(balancer_config) if balancer_config else None),
        )
        await self.games.create(session, game)
        rows = [_new_roster_row(game.id, item, index) for index, item in enumerate(ids)]
        if rows:
            await self.roster.create_many(session, rows)
        await self._seed_host_ranks(session, game, members)
        return game

    async def update_roster(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        member_ids: Sequence[int],
        actor_user_id: int,
    ) -> models.CustomGame:
        """Set pool membership, keeping every surviving row's lineup state.

        Adding or dropping one player must not reset the bench switches and role
        orders the host already tuned for everybody else, so rows are matched by
        ``workspace_member_id`` instead of rebuilt from scratch.
        """
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
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
    ) -> models.CustomGame:
        """Patch one roster row's participation, role selection and flex mode."""
        unknown = sorted(set(patch) - _PLAYER_PATCH_FIELDS)
        if unknown:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown fields {unknown}")
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        roster = list(await self.roster.list_for_game(session, game.id))
        row = next((item for item in roster if item.workspace_member_id == workspace_member_id), None)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game player not found")
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
        await session.flush()
        return game

    async def set_participation(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        participation: Mapping[int, MixParticipation],
        actor_user_id: int,
    ) -> models.CustomGame:
        """Move several roster rows between lineup states atomically.

        The rotation hint applies a whole verdict at once. One transaction, one
        snapshot: applying it row by row raced on whose response the client
        saw last, and left the lineup mid-verdict if one call failed.
        """
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        rows = {row.workspace_member_id: row for row in await self.roster.list_for_game(session, game.id)}
        if not set(participation) <= set(rows):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom game player not found")
        for member_id, state in participation.items():
            rows[member_id].participation = state
        await session.flush()
        return game

    async def roster_shape(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
    ) -> RosterShapeRead:
        """Resolve the mix override, workspace default, then built-in shape."""
        role_mask = await self.role_slots.mapping_for_game(session, custom_game_id)
        workspace_slots = await get_workspace_roster_slots(session, workspace_id)
        shape = resolve_roster_shape(role_mask or None, workspace_slots)
        source = "tournament" if role_mask else "workspace" if workspace_slots else "default"
        return RosterShapeRead.from_shape(shape, source=source)

    async def balance(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        actor_user_id: int,
    ) -> models.CustomGame:
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
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
        role_mask = (
            await self.roster_shape(
                session,
                workspace_id=workspace_id,
                custom_game_id=game.id,
            )
        ).slots
        try:
            result = await self.run_balance(
                {"players": player_nodes},
                game.balancer_config_json,
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
        game.balance_result_json = result
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
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        patch = _normalize_team_names(team_names)
        for index, value in patch.items():
            await self.team_names.set(session, game.id, int(index), value)
        await session.flush()
        return game

    async def set_role_mask(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        role_mask: Mapping[str, int] | None,
        actor_user_id: int,
    ) -> models.CustomGame:
        """Patch the mix's own roster-shape override, or clear it back to inheriting.

        Mirrors ``Tournament.roster_slots_json``: ``None`` clears the override, and
        ``balance``/``roster_shape`` then fall back through ``resolve_roster_shape``
        to the workspace default, then the built-in Overwatch 5v5 shape.
        """
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        try:
            normalized = normalize_roster_slots(role_mask)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        await self.role_slots.replace(session, game.id, normalized)
        return game

    async def set_points_per_win(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        points_per_win: int | None,
        actor_user_id: int,
    ) -> models.CustomGame:
        """Patch the host's rank-adjustment-per-win knob. ``None``/``0`` disables it.

        Recording an outcome then bumps the host's own rank book (the layer a
        mix already resolves against, see ``MIX_ORDER``) by this many points
        for the winning team and down by the same for the losing team, per
        player and role -- see :meth:`record_outcome`. A draw never adjusts
        anything, win or lose.
        """
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        if points_per_win is not None:
            if not isinstance(points_per_win, int) or isinstance(points_per_win, bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="points_per_win must be an integer"
                )
            if not (0 <= points_per_win <= _MAX_POINTS_PER_WIN):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"points_per_win must be between 0 and {_MAX_POINTS_PER_WIN}",
                )
        game.points_per_win = points_per_win or None
        await session.flush()
        return game

    async def set_balancer_config(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        balancer_config: Mapping[str, Any] | None,
        actor_user_id: int,
    ) -> models.CustomGame:
        """Replace the mix's validated solver overrides."""
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        normalized = normalize_config_overrides(balancer_config) if balancer_config else {}
        game.balancer_config_json = normalized or None
        await session.flush()
        return game

    async def transfer_host(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        new_host_user_id: int,
        actor_user_id: int,
    ) -> models.CustomGame:
        """Transfer primary ownership to a signed-in member of this workspace."""
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
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
    ) -> models.CustomGame:
        """Grant a signed-in workspace member co-host write access."""
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
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
    ) -> models.CustomGame:
        """Revoke co-host access, including a co-host removing themselves."""
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
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
    ) -> models.CustomGame:
        """Swap two seated players between teams, same role only.

        A same-role swap can never break a team's role quota (1 tank / 2 dps /
        2 support stays exactly that on both sides), so it needs no eligibility
        check beyond "both seats exist and share a role" -- unlike a free move,
        which would need to know every role a player is *ranked* for, not just
        the one this balance happened to seat them in.

        Edits whichever balance option is on screen (``variant_index``), not
        only the first: a host who paged to option 2 and likes it otherwise is
        adjusting that one, not silently rewriting option 1.
        """
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        result = copy.deepcopy(game.balance_result_json) if isinstance(game.balance_result_json, dict) else None
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
        _recompute_variant_stats(variant)

        game.balance_result_json = result
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
    ) -> models.CustomGame:
        """Freeze one played match into ``casual.match`` and its two scored sides.

        Repeatable -- a mix records many matches before its host calls
        :meth:`close`, and the frozen snapshot is the only record of each: the
        mix itself keeps no mutable copy of "the last result".

        ``points_per_win`` (when set, and only for a decided match) moves both
        teams' host-authored ranks, and every seat that actually played redeems
        its ``MUST_PLAY`` pin back to ``POOL`` -- the pin promises one
        guaranteed seat, not every seat forever.
        """
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
        )
        if winner not in (1, 2, None):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="winner must be 1, 2 or null")
        if map_id is not None and await session.get(models.Map, map_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

        result = game.balance_result_json if isinstance(game.balance_result_json, dict) else {}
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
        match = models.CasualMatch(custom_game_id=game.id, map_id=map_id, recorded_by=actor_user_id)
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
        for team_index, (team, casual_team) in enumerate(zip(teams, casual_teams, strict=True)):
            roster = team.get("roster") if isinstance(team, dict) else None
            if not isinstance(roster, dict):
                continue
            for bucket_name, seats in roster.items():
                if not isinstance(seats, list):
                    continue
                slot_code = role_slot_code(bucket_name)
                role = HeroClass.from_slot_code(slot_code)
                for seat in seats:
                    if not isinstance(seat, dict) or seat.get("uuid") is None:
                        continue
                    member_id = int(seat["uuid"])
                    rating = int(seat["assigned_rating"])
                    await self.casual_players.create(
                        session,
                        models.CasualPlayer(
                            team_id=casual_team.id,
                            workspace_member_id=member_id,
                            # The name as it stood when the match was played --
                            # a later rename or a member leaving the workspace
                            # must not rewrite history.
                            display_name_snapshot=str(seat.get("name") or f"#{member_id}"),
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

        points_per_win = game.points_per_win or 0
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

        await session.flush()
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

        role_mask = (await self.roster_shape(session, workspace_id=workspace_id, custom_game_id=game.id)).slots
        players_per_team = sum(role_mask.values())
        usable_count = len(roster) if players_per_team <= 0 else (len(roster) // players_per_team) * players_per_team
        return recommend_rotation(histories, usable_count=usable_count)

    async def close(
        self, session: AsyncSession, *, workspace_id: int, custom_game_id: int, actor_user_id: int
    ) -> models.CustomGame:
        """Ends the mix. No result of its own -- matches already recorded via
        ``record_outcome`` stay recorded; this only stops further writes.
        """
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
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
    ) -> models.CustomGame:
        game = await self._writable(
            session, workspace_id=workspace_id, custom_game_id=custom_game_id, actor_user_id=actor_user_id
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
