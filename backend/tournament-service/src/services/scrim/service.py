"""Provisioning for ad-hoc scrim rooms.

Everything a scrim room needs to run already exists — the pick-ban engine, the
readiness gate, the pre-game room UI, the captain-identity resolver. This module
does not extend any of them. It only assembles the rows they all expect: a
hidden container ``Tournament`` per workspace, one ``Stage`` per room to carry
that room's pool, two ``Team`` rows whose ``captain_id`` IS the room's authority
model, and one ``Encounter`` for the engine to hang a session off.

Two invariants this module owns, because nothing downstream can enforce them:

* **One person cannot captain both sides.** The engine trusts
  ``Team.captain_id`` completely (``encounter/captain.py``), so a single user
  holding both would let them ban for both halves of their own veto.
* **The creator's open-room count is capped** (``Settings["tournament.scrim"]``),
  because room creation writes six rows and is reachable by any workspace
  member.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from shared import models
from shared.core import http_status as status
from shared.core.enums import (
    EncounterStatus,
    MapVetoMode,
    PickBanKind,
    StageType,
    TournamentStatus,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_scoring import WINS_END_FORMULA
from shared.domain.pick_ban_config import has_pool
from shared.models.tournament.pick_ban import (
    PickBanConfig,
    PickBanConfigItem,
    PickBanConfigSlot,
    PickBanConfigSlotItem,
)
from shared.models.tournament.scrim import ScrimRoom
from shared.repository import (
    BracketEncounterRepository,
    EncounterRepository,
    PickBanConfigRepository,
    ScrimRoomRepository,
    StageRepository,
    TeamRepository,
    TournamentRepository,
    UserRepository,
    WorkspaceRepository,
)
from shared.services.encounter.participants import place_team, vacate_slot
from shared.services.ontology import assert_discipline_enabled
from shared.services.settings_provider import settings_provider
from shared.services.team_format import copy_for_tournament
from shared.services.tournament.visibility import ensure_tournament_viewable


def _pick_ban():
    """The pick-ban modules, imported on first use: only pool provisioning needs them, not ``claim_side``."""
    from src.services.encounter import pick_ban_config as pick_ban_config_service  # noqa: PLC0415
    from src.services.encounter.pick_ban_session import pick_ban_session_service  # noqa: PLC0415
    from src.services.encounter.veto_session import (  # noqa: PLC0415
        REASON_NOT_CONFIGURED,
        REASON_SLOT_COUNT_MISMATCH,
        REASON_SLOT_UNDERFILLED,
        SLOT_CANDIDATE_FLOOR,
    )

    return SimpleNamespace(
        config=pick_ban_config_service,
        sessions=pick_ban_session_service,
        bricking={REASON_NOT_CONFIGURED, REASON_SLOT_COUNT_MISMATCH, REASON_SLOT_UNDERFILLED},
        slot_count_mismatch=REASON_SLOT_COUNT_MISMATCH,
        slot_underfilled=REASON_SLOT_UNDERFILLED,
        candidate_floor=SLOT_CANDIDATE_FLOOR,
    )


#: Slot 1 is the creator's seat, slot 2 the one the share link gives away.
SLOTS = (1, 2)

# The container's name is cosmetic — rooms are found through ``ScrimRoom``, never
# by name — but it is what a workspace admin sees in the hidden-tournament list,
# so it stays a constant rather than a per-room string.
CONTAINER_NAME = "Scrims"

__all__ = (
    "CONTAINER_NAME",
    "require_workspace_member",
    "scrim_service",
)


# ── authorization ────────────────────────────────────────────────────────────


def require_workspace_member(user: models.AuthUser, workspace_id: int) -> None:
    """Membership, not a permission: creating a scrim is a player action.

    Deliberately NOT ``ensure_workspace_permission(... "match", "update")`` —
    that is the organizer gate, and requiring it would make scrims an admin
    feature. Superusers and workspace admins pass by virtue of membership.
    """
    if user.is_superuser or workspace_id in user.get_workspace_ids():
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not a member of this workspace",
    )


def is_workspace_staff(user: models.AuthUser | None, workspace_id: int) -> bool:
    """Who polices a workspace's scrims: whoever may enter a match result.

    The same grant the pre-game organizer controls run on (``match.result``), so a
    referee already trusted with a tournament's scoreline can also find and retire
    a room whose creator left the workspace. ``has_workspace_permission`` already
    answers True for a superuser, so that case needs no branch of its own.
    """
    return user is not None and user.has_workspace_permission(workspace_id, "match", "result")


def _may_close(room: ScrimRoom, user: models.AuthUser | None, viewer_slot: int | None) -> bool:
    """Creator, either captain, or workspace staff.

    One predicate for both the endpoint and the serialized ``can_close``, so the
    button a viewer sees and the rule the write enforces cannot drift.
    """
    if user is None:
        return False
    return (
        room.created_by_auth_user_id == user.id
        or viewer_slot is not None
        or user.is_superuser
        or is_workspace_staff(user, room.workspace_id)
    )


# ── pool ─────────────────────────────────────────────────────────────────────


def _clone_config(source: PickBanConfig, *, tournament_id: int, stage_id: int) -> PickBanConfig:
    """A stage-scoped copy of ``source`` for one room.

    A copy, not a reference: the room must keep playing the pool it opened with
    even if the organizer edits the tournament's config afterwards — the same
    "a running session is never silently rewritten" rule the engine already
    holds for tournament play. That includes the ruleset document, which is
    deep-copied rather than shared: two ORM rows pointing at one dict would let
    an edit to either rewrite both.
    """
    clone = PickBanConfig(
        tournament_id=tournament_id,
        kind=source.kind,
        stage_id=stage_id,
        round=None,
        mode=source.mode,
        first_pick_rule=source.first_pick_rule,
        first_ban_rotation=source.first_ban_rotation,
        ruleset_json=deepcopy(source.ruleset_json),
    )
    clone.items = [
        PickBanConfigItem(item_id=item.item_id, sort_order=item.sort_order)
        for item in sorted(source.items, key=lambda i: i.sort_order)
    ]
    clone.slots = [
        PickBanConfigSlot(
            position=slot.position,
            reserve_item_id=slot.reserve_item_id,
            items=[
                PickBanConfigSlotItem(item_id=item.item_id, sort_order=item.sort_order)
                for item in sorted(slot.items, key=lambda i: i.sort_order)
            ],
        )
        for slot in sorted(source.slots, key=lambda s: s.position)
    ]
    return clone


async def _config_from_input(
    session: AsyncSession, payload: dict[str, Any], *, tournament_id: int, stage_id: int
) -> PickBanConfig:
    """Build one room-scoped config from a custom-pool entry.

    Validated with the SAME validator the organizer's config editor uses, so a
    room cannot be provisioned into a shape the engine would later refuse to
    open a session for — which would strand the room in ``misconfigured`` with no
    way for its captains to fix it.
    """
    kind = PickBanKind(payload["kind"])
    mode = MapVetoMode(payload.get("mode") or MapVetoMode.POOL.value)
    slots = payload.get("slots") or []
    item_ids = payload.get("item_ids") or []
    ruleset = payload.get("ruleset") or {}

    pick_ban = _pick_ban()
    discipline = await pick_ban.config.tournament_discipline(session, tournament_id)
    await pick_ban.config.validate_config(
        session,
        kind=kind,
        mode=mode,
        ruleset=ruleset,
        item_ids=item_ids,
        slots=[(list(slot.get("candidates") or []), slot.get("reserve_item_id")) for slot in slots],
        stage_id=stage_id,
        round=None,
        discipline=discipline,
    )

    config = PickBanConfig(
        tournament_id=tournament_id,
        kind=kind,
        stage_id=stage_id,
        round=None,
        mode=mode,
        ruleset_json=pick_ban.config.normalized_ruleset(ruleset),
    )
    # Only assign what the caller actually sent: these columns carry server
    # defaults, and writing ``None`` over them would violate NOT NULL.
    for field in ("first_pick_rule", "first_ban_rotation"):
        value = payload.get(field)
        if value is not None:
            setattr(config, field, value)
    config.items = [PickBanConfigItem(item_id=item_id, sort_order=idx) for idx, item_id in enumerate(item_ids)]
    config.slots = [
        PickBanConfigSlot(
            position=idx,
            reserve_item_id=slot.get("reserve_item_id"),
            items=[
                PickBanConfigSlotItem(item_id=item_id, sort_order=order)
                for order, item_id in enumerate(slot.get("candidates") or [])
            ],
        )
        for idx, slot in enumerate(slots, start=1)
    ]
    return config


# ── reads ────────────────────────────────────────────────────────────────────

_ROOM_LOAD = (selectinload(ScrimRoom.encounter).selectinload(models.Encounter.teams),)


def _seat_at(encounter: models.Encounter, slot: int) -> models.EncounterTeam | None:
    """The participation holding ``slot``, live or retired.

    A retired slot-2 row is how a room remembers the team the creator named for
    an opponent before anyone claimed it: participations are append-only, so the
    reservation is recorded rather than stored in a column of its own.
    """
    candidates = [seat for seat in encounter.teams if seat.slot == slot]
    live = [seat for seat in candidates if seat.active]
    return live[0] if live else (candidates[-1] if candidates else None)


def _team_payload(slot: int, team: models.Team | None, seat: models.EncounterTeam | None) -> dict:
    """One team of the room. ``captain_claimed`` is what the share link gives
    away: a seat with no live participation is still open."""
    if team is None:
        return {"slot": slot, "id": None, "name": seat.name if seat is not None else "TBD", "captain_claimed": False}
    return {
        "slot": slot,
        "id": team.id,
        "name": team.name,
        "captain_claimed": team.captain_id is not None and seat is not None and seat.active,
    }


def _free_slot(encounter: models.Encounter) -> int | None:
    """The slot still open to the link's next taker, or None once both are held."""
    for slot in SLOTS:
        if not any(seat.slot == slot and seat.active for seat in encounter.teams):
            return slot
    return None


class ScrimService:
    def __init__(
        self,
        *,
        room_repo: ScrimRoomRepository = ScrimRoomRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        workspace_repo: WorkspaceRepository = WorkspaceRepository(),
        stage_repo: StageRepository = StageRepository(),
        team_repo: TeamRepository = TeamRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        bracket_encounter_repo: BracketEncounterRepository = BracketEncounterRepository(),
        pick_ban_config_repo: PickBanConfigRepository = PickBanConfigRepository(),
        user_repo: UserRepository = UserRepository(),
    ) -> None:
        self.room_repo = room_repo
        self.tournament_repo = tournament_repo
        self.workspace_repo = workspace_repo
        self.stage_repo = stage_repo
        self.team_repo = team_repo
        self.encounter_repo = encounter_repo
        self.bracket_encounter_repo = bracket_encounter_repo
        self.pick_ban_config_repo = pick_ban_config_repo
        self.user_repo = user_repo

    # ── authorization ────────────────────────────────────────────────────────

    async def _ensure_player(self, session: AsyncSession, user: models.AuthUser) -> models.User:
        """The ``players.user`` row a captain must have, created on demand.

        ``Team.captain_id`` points at the domain player, not the auth user, and a
        scrim captain may never have registered for anything.
        """
        return await self.user_repo.ensure_for_auth_user(
            session, auth_user_id=user.id, name_hint=user.username or user.email
        )

    # ── container ────────────────────────────────────────────────────────────

    async def _ensure_container(self, session: AsyncSession, workspace_id: int, discipline: str) -> models.Tournament:
        """The workspace's single hidden scrim container FOR ``discipline``, created on first use.

        One per workspace and game, never one per room: ``Tournament.id`` is read as an
        ordinal season timeline by the ML layer (see the ``ScrimRoom`` docstring), so
        a container per room would inject data-less rows into it. The game is part of
        the identity because the container is the room's owner tournament: its pool,
        maps and rosters are all read in the container's discipline.

        Serialized on an advisory lock — two members creating their first room at the
        same moment would otherwise each see "no container" and make one. A duplicate
        would be harmless (both hidden, each holding its own rooms) but permanent,
        and the lock costs one statement, so it is not worth tolerating.
        """
        await session.execute(
            sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(f"scrim:{workspace_id}:{discipline}")))
        )
        # ``order_by(id).limit(1)`` makes a duplicate container -- harmless but
        # permanent -- resolve to the same row every time.
        container = await session.scalar(
            self.tournament_repo.select()
            .where(
                models.Tournament.workspace_id == workspace_id,
                models.Tournament.discipline == discipline,
                models.Tournament.is_hidden.is_(True),
                models.Tournament.name == CONTAINER_NAME,
            )
            .order_by(models.Tournament.id)
            .limit(1)
        )
        if container is not None:
            return container
        workspace = await self.workspace_repo.get(session, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        assert_discipline_enabled(workspace, discipline)
        now = datetime.now(UTC)
        container = models.Tournament(
            workspace_id=workspace_id,
            discipline=discipline,
            name=CONTAINER_NAME,
            # Deterministic, not generated: one container per workspace and game, so
            # ``(workspace_id, discipline)`` already makes it unique, and a hidden row's
            # slug is never surfaced.
            slug=f"scrims-{workspace_id}-{discipline}",
            description="Container for ad-hoc scrim rooms. Not a real tournament.",
            is_hidden=True,
            status=TournamentStatus.LIVE,
            # Both dates set, though a container neither starts nor ends: ``TournamentRead``
            # declares them NOT NULL and its render sites read them unguarded. The
            # creation instant is the least misleading value available.
            start_date=now,
            end_date=now,
            # Nothing schedules or advances this row; leaving automation on would let
            # the tournament worker walk its status through a phase schedule it does
            # not have.
            auto_transitions_enabled=False,
        )
        container = await self.tournament_repo.create(session, container)
        await copy_for_tournament(session, container)
        return container

    # ── pool ────────────────────────────────────────────────────────────────

    async def _build_configs(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        pool: dict[str, Any],
        *,
        tournament_id: int,
        stage_id: int,
    ) -> list[PickBanConfig]:
        source = pool.get("source")
        if source == "copy":
            origin_id = pool.get("tournament_id")
            if not origin_id:
                raise HTTPException(status_code=422, detail="pool.tournament_id is required when source is copy")
            # The source tournament may be hidden or from another workspace; gate it
            # exactly as any other read would, or copying a pool becomes a way to
            # read a tournament the caller cannot see.
            await ensure_tournament_viewable(session, user, int(origin_id))
            # A pool is a list of one game's catalog ids: another game's tournament is not a
            # source for this room, whatever the caller may see of it.
            pick_ban = _pick_ban()
            origin_discipline = await pick_ban.config.tournament_discipline(session, int(origin_id))
            room_discipline = await pick_ban.config.tournament_discipline(session, tournament_id)
            if origin_discipline != room_discipline:
                raise HTTPException(
                    status_code=422,
                    detail=[
                        ApiExc(
                            code="pool_wrong_discipline",
                            msg=f"That tournament plays {origin_discipline!r}; this room plays {room_discipline!r}",
                        )
                    ],
                )
            configs: list[PickBanConfig] = []
            for kind in (PickBanKind.MAP, PickBanKind.HERO):
                resolved = await _pick_ban().sessions.resolve_config_at_level(
                    session,
                    tournament_id=int(origin_id),
                    kind=kind,
                    stage_id=pool.get("stage_id"),
                    round=pool.get("round"),
                )
                if resolved is not None:
                    configs.append(_clone_config(resolved, tournament_id=tournament_id, stage_id=stage_id))
            if not configs:
                raise HTTPException(
                    status_code=422,
                    detail="That tournament level has no pick-ban pool to copy",
                )
            return configs

        if source == "custom":
            entries = pool.get("configs") or []
            if not entries:
                raise HTTPException(status_code=422, detail="pool.configs must not be empty when source is custom")
            kinds = [entry.get("kind") for entry in entries]
            if len(set(kinds)) != len(kinds):
                raise HTTPException(status_code=422, detail="pool.configs must carry at most one entry per kind")
            return [
                await _config_from_input(session, entry, tournament_id=tournament_id, stage_id=stage_id)
                for entry in entries
            ]

        raise HTTPException(status_code=422, detail="pool.source must be 'copy' or 'custom'")

    # ── reads ───────────────────────────────────────────────────────────────

    async def _load_room(self, session: AsyncSession, token: str) -> ScrimRoom:
        room = await self.room_repo.get_by_token(session, token, options=_ROOM_LOAD)
        if room is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrim room not found")
        return room

    async def get_room_by_token(self, session: AsyncSession, user: models.AuthUser | None, token: str) -> dict:
        """One room, gated by the container's own visibility rules.

        ``ensure_tournament_viewable`` is what makes a room private: a stranger with
        the token still gets 404, because holding the link is not membership. The
        link only matters for the ONE action it unlocks — see ``claim_side``.
        """
        room = await self._load_room(session, token)
        await ensure_tournament_viewable(session, user, room.tournament_id)
        return await self.serialize_room(session, room, user)

    async def list_rooms_for_viewer(
        self, session: AsyncSession, user: models.AuthUser, workspace_id: int, *, scope: str = "mine"
    ) -> list[dict]:
        """The viewer's own rooms — created by them, or captained by them.

        ``scope="workspace"`` drops that gate and lists every room of the workspace
        instead, for staff who have to find a room they are in no way part of (a
        creator who left, an abandoned room still eating a cap slot). Same ordering
        and same serialization either way.

        Its own read rather than ``/encounters?scope=my_team``: that browse joins
        ``Player`` rows (a scrim team has none) and unconditionally excludes hidden
        tournaments, so it can never surface a scrim by construction.

        Deliberately NOT ``DISTINCT``. Every join below is to a primary key --
        ``ScrimRoom.encounter_id`` is unique, and each side resolves one ``Team`` row
        -- so the result is exactly one row per room and there is nothing to
        de-duplicate. A ``DISTINCT`` here is also outright invalid: Postgres requires
        every ORDER BY expression to appear in the select list under it, and the
        ordering below sorts on a computed ``closed_at IS NULL``, which raises
        ``InvalidColumnReferenceError``.
        """
        if scope not in ("mine", "workspace"):
            raise HTTPException(status_code=422, detail="scope must be 'mine' or 'workspace'")
        require_workspace_member(user, workspace_id)
        if scope == "workspace" and not is_workspace_staff(user, workspace_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied for workspace {workspace_id}: match.result required",
            )
        player_ids = sa.select(models.User.id).where(models.User.auth_user_id == user.id).scalar_subquery()
        seat = aliased(models.EncounterTeam)
        captain_team = aliased(models.Team)
        # "Captained by me": a team I captain holds one of this encounter's live seats.
        mine = sa.or_(
            ScrimRoom.created_by_auth_user_id == user.id,
            sa.exists()
            .where(seat.encounter_id == ScrimRoom.encounter_id)
            .where(seat.active.is_(True))
            .where(captain_team.id == seat.team_id)
            .where(captain_team.captain_id.in_(player_ids)),
        )
        rows = await session.execute(
            self.room_repo.select()
            .where(
                ScrimRoom.workspace_id == workspace_id,
                *([] if scope == "workspace" else [mine]),
            )
            .options(*_ROOM_LOAD)
            # Open rooms first, then newest closed: the list's job is "what am I in
            # right now", with history underneath it.
            .order_by(ScrimRoom.closed_at.is_(None).desc(), ScrimRoom.id.desc())
        )
        rooms = list(rows.scalars().all())
        player_id = await self.user_repo.get_id_by_auth_user_id(session, user.id) if user is not None else None
        teams = await self._room_teams(session, rooms)
        return [self._serialize_room(room, user, player_id, teams) for room in rooms]

    async def _room_teams(self, session: AsyncSession, rooms: Sequence[ScrimRoom]) -> dict[int, models.Team]:
        """Every source team seated (or reserved) in these rooms, by id."""
        team_ids = sorted({seat.team_id for room in rooms for seat in room.encounter.teams if seat.team_id is not None})
        if not team_ids:
            return {}
        return {team.id: team for team in await self.team_repo.bulk_get(session, team_ids)}

    def _viewer_slot_for_player(
        self, room: ScrimRoom, player_id: int | None, teams: dict[int, models.Team]
    ) -> int | None:
        if player_id is None:
            return None
        for slot in SLOTS:
            seat = _seat_at(room.encounter, slot)
            if seat is None or not seat.active or seat.team_id is None:
                continue
            team = teams.get(seat.team_id)
            if team is not None and team.captain_id == player_id:
                return slot
        return None

    async def _viewer_slot(self, session: AsyncSession, room: ScrimRoom, user: models.AuthUser | None) -> int | None:
        if user is None:
            return None
        player_id = await self.user_repo.get_id_by_auth_user_id(session, user.id)
        return self._viewer_slot_for_player(room, player_id, await self._room_teams(session, [room]))

    def _serialize_room(
        self,
        room: ScrimRoom,
        user: models.AuthUser | None,
        player_id: int | None,
        teams: dict[int, models.Team],
    ) -> dict:
        encounter = room.encounter
        viewer_slot = self._viewer_slot_for_player(room, player_id, teams)
        free_slot = _free_slot(encounter)
        can_claim = (
            viewer_slot is None
            and free_slot is not None
            and room.closed_at is None
            and user is not None
            and (user.is_superuser or room.workspace_id in user.get_workspace_ids())
        )
        seats = {slot: _seat_at(encounter, slot) for slot in SLOTS}
        return {
            "id": room.id,
            "token": room.token,
            "label": room.label,
            "workspace_id": room.workspace_id,
            "discipline": encounter.discipline,
            "tournament_id": room.tournament_id,
            "stage_id": room.stage_id,
            "encounter_id": room.encounter_id,
            "best_of": encounter.best_of,
            "teams": [
                _team_payload(slot, teams.get(seat.team_id) if seat is not None and seat.team_id else None, seat)
                for slot, seat in seats.items()
            ],
            "viewer_slot": viewer_slot,
            "can_claim": can_claim,
            "can_close": room.closed_at is None and _may_close(room, user, viewer_slot),
            "created_at": room.created_at,
            "closed_at": room.closed_at,
        }

    async def serialize_room(self, session: AsyncSession, room: ScrimRoom, user: models.AuthUser | None) -> dict:
        player_id = await self.user_repo.get_id_by_auth_user_id(session, user.id) if user is not None else None
        return self._serialize_room(room, user, player_id, await self._room_teams(session, [room]))

    # ── writes ──────────────────────────────────────────────────────────────

    async def _assert_under_cap(self, session: AsyncSession, user: models.AuthUser, limit: int) -> None:
        open_rooms = await session.scalar(
            sa.select(sa.func.count())
            .select_from(ScrimRoom)
            .where(
                ScrimRoom.created_by_auth_user_id == user.id,
                ScrimRoom.closed_at.is_(None),
            )
        )
        if int(open_rooms or 0) >= limit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"You already have {limit} open scrim room(s). Close one before opening another."
                    if limit == 1
                    else f"You already have {open_rooms} open scrim rooms (limit {limit}). Close one first."
                ),
            )

    async def _assert_playable(
        self,
        session: AsyncSession,
        encounter: models.Encounter,
        kinds: list[PickBanKind],
        *,
        stage_id: int,
        best_of: int,
    ) -> None:
        """Refuse a room the engine would not open a session for.

        Asked of the engine rather than re-derived here: ``unavailable_reason`` runs
        the same checks ``ensure_pick_ban_session`` does, against the rows just
        written, so the two cannot drift. Anything it reports about the room's
        *progress* -- nobody is ready yet, hero bans waiting on a map -- is the normal
        state of a fresh room and passes.

        A copied pool is checked only here: the custom branch validates its own
        payload, a copy does not, and borrowing a 3-slot round for a best-of-5 would
        otherwise open a room that can never play.
        """
        pick_ban = _pick_ban()
        for kind in kinds:
            reason = await pick_ban.sessions.unavailable_reason(session, encounter, kind)
            if reason not in pick_ban.bricking:
                continue
            config = await pick_ban.sessions.resolve_config_at_level(
                session,
                tournament_id=encounter.tournament_id,
                kind=kind,
                stage_id=stage_id,
                round=None,
            )
            slots = len(config.slots) if config is not None else 0
            if config is not None and not has_pool(config):
                # A rules template: rotation and timer authored for narrower
                # scopes to inherit, with no candidates of its own to play.
                detail = (
                    f"That {kind.value} pool has no candidates configured — it is a rules template. "
                    "Pick a different round, or author the pool at that scope."
                )
            elif reason == pick_ban.slot_count_mismatch:
                detail = (
                    f"That pool has {slots} map slot(s), so it plays a best-of-{slots} at most. "
                    f"Lower best_of to {slots} or copy a round with more slots."
                )
            elif reason == pick_ban.slot_underfilled:
                detail = (
                    f"One of that pool's first {best_of} slots offers fewer than {pick_ban.candidate_floor} "
                    "candidates, so there is nothing to ban. Copy a different round or author the pool here."
                )
            else:
                detail = f"The {kind.value} pool this room was given does not resolve for it."
            # 422, not 409: the request itself is unsatisfiable as sent, and the caller
            # fixes it by changing best_of or the source round.
            raise HTTPException(status_code=422, detail=detail)

    async def create_room(
        self,
        session: AsyncSession,
        user: models.AuthUser,
        *,
        workspace_id: int,
        discipline: str,
        label: str,
        best_of: int,
        team_names: Sequence[str],
        pool: dict[str, Any],
    ) -> dict:
        """Provision one room and return it. Commits.

        The creator takes slot 1 immediately; slot 2 stays unclaimed
        until someone opens the link. That asymmetry is the point of the token — the
        room is usable the moment it exists, and the opponent needs no invitation
        beyond the URL.
        """
        require_workspace_member(user, workspace_id)
        config = await settings_provider.get_scrim_config(session)
        await self._assert_under_cap(session, user, config.max_open_rooms_per_user)
        if best_of < 1 or best_of > config.max_best_of:
            raise HTTPException(status_code=422, detail=f"best_of must be between 1 and {config.max_best_of}")

        container = await self._ensure_container(session, workspace_id, discipline)

        # ``get_next_order`` answers 0 for a container with no stages yet, where a
        # room's stage starts at 1 -- which is what the ``or 1`` below preserves.
        next_order = await self.stage_repo.get_next_order(session, container.id)
        stage = models.Stage(
            tournament_id=container.id,
            # One rule row per room, the ``wins`` preset: a scrim is a Bo-N
            # series and nothing about it is configurable, but
            # ``stage.scoring_rule_id`` and ``encounter.scoring_rule_id`` are
            # both NOT NULL and the encounter layer scores every card by one.
            scoring_rule=models.ScoringRule(
                workspace_id=workspace_id,
                preset="wins",
                game_formula="win",
                end_formula=WINS_END_FORMULA,
            ),
            name=label,
            description="Scrim room",
            # The stage exists so this room's pool has a cascade level of its own
            # (``uq_pick_ban_config_level`` allows only one config per level). The type
            # is still read: ``_build_elimination_stage_standings`` would invent placings
            # for these two rosterless teams, which is why ``shared/services/scrim_scope.py``
            # skips the recalculation at the enqueue site.
            stage_type=StageType.SINGLE_ELIMINATION,
            max_rounds=1,
            order=int(next_order or 1),
            # A scrim room has no preview phase -- it is live the instant it is
            # created, so its stage must not read as an organizer's un-activated
            # bracket (``src.services.bracket.usability.is_encounter_live``).
            is_published=True,
        )
        # Seeded while transient: once flushed, the first touch of a collection
        # nothing loaded would lazy-SELECT (MissingGreenlet under async).
        stage.round_best_of = []
        await self.stage_repo.create(session, stage)

        configs = await self._build_configs(session, user, pool, tournament_id=container.id, stage_id=stage.id)
        # Items, slots and slot items are written by cascade off the config rows.
        await self.pick_ban_config_repo.create_many(session, configs)

        captain = await self._ensure_player(session, user)
        first = models.Team(tournament_id=container.id, name=team_names[0], balancer_name=team_names[0])
        first.captain_id = captain.id
        second = models.Team(tournament_id=container.id, name=team_names[1], balancer_name=team_names[1])
        await self.team_repo.create_many(session, [first, second])

        encounter = models.Encounter(
            name=label,
            workspace_id=container.workspace_id,
            discipline=container.discipline,
            tournament_id=container.id,
            scoring_rule_id=stage.scoring_rule_id,
            slot_count=2,
            best_of=best_of,
            status=EncounterStatus.OPEN,
        )
        await self.encounter_repo.create(session, encounter)
        await self.bracket_encounter_repo.create(
            session,
            models.BracketEncounter(
                encounter_id=encounter.id,
                tournament_id=container.id,
                stage_id=stage.id,
                stage_item_id=None,
                round=1,
            ),
        )
        # The creator takes slot 1 now; slot 2 is RESERVED, not seated -- the
        # retired participation is how the room remembers the team the creator
        # named for an opponent until ``claim_side`` seats it. That is also
        # what makes "is the link still open" a question about live seats alone.
        await place_team(session, encounter, slot=1, team_id=first.id, name=first.name, seed=None, members=())
        await place_team(session, encounter, slot=2, team_id=second.id, name=second.name, seed=None, members=())
        await vacate_slot(session, encounter, slot=2)

        await self._assert_playable(
            session, encounter, [config.kind for config in configs], stage_id=stage.id, best_of=best_of
        )

        room = ScrimRoom(
            token=secrets.token_urlsafe(12),
            label=label,
            workspace_id=workspace_id,
            tournament_id=container.id,
            stage_id=stage.id,
            encounter_id=encounter.id,
            created_by_auth_user_id=user.id,
        )
        await self.room_repo.create(session, room)
        await session.commit()

        return await self.get_room_by_token(session, user, room.token)

    async def claim_side(self, session: AsyncSession, user: models.AuthUser, token: str) -> dict:
        """Take the room's free side. Commits.

        The token is the only credential this needs beyond workspace membership —
        that is what makes a scrim room shareable. It is also the only write the
        token authorizes: everything afterwards runs on ``Team.captain_id`` through
        the engine's own resolver.
        """
        room = await self._load_room(session, token)
        require_workspace_member(user, room.workspace_id)
        if room.closed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This scrim room is closed")

        existing_slot = await self._viewer_slot(session, room, user)
        if existing_slot is not None:
            # Idempotent for the captain who already holds a side, and a refusal for
            # anyone trying to hold both: the engine reads authority straight off
            # ``captain_id``, so one user on both sides could ban for both.
            return await self.serialize_room(session, room, user)

        slot = _free_slot(room.encounter)
        if slot is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Both sides are already claimed")

        captain = await self._ensure_player(session, user)
        reserved = _seat_at(room.encounter, slot)
        if reserved is None or reserved.team_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That side has no team to claim")
        # Conditional UPDATE, not an assignment: two opponents opening the link
        # together would both read "unclaimed" and the later flush would silently
        # overwrite the earlier captain. Winning it is also what authorizes the
        # seat below, so the seat can never be written twice.
        if not await self.team_repo.claim_captain(session, reserved.team_id, captain.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That side was just claimed")
        await place_team(
            session,
            room.encounter,
            slot=slot,
            team_id=reserved.team_id,
            name=reserved.name,
            seed=None,
            members=(),
        )
        await session.commit()
        # The seats were loaded before this write; the read below serializes
        # from them, and a session that does not expire on commit would answer
        # with the room as it was BEFORE the claim.
        await session.refresh(room.encounter, ["teams"])
        return await self.get_room_by_token(session, user, token)

    async def close_room(self, session: AsyncSession, user: models.AuthUser, token: str) -> dict:
        """Close a room, freeing its creator's cap slot. Commits.

        Not a delete: the encounter, its pick-ban session and its reported maps are
        the scrim's history, and both captains keep reading them through the preview
        allowlist afterwards.
        """
        room = await self._load_room(session, token)
        viewer_slot = await self._viewer_slot(session, room, user)
        if not _may_close(room, user, viewer_slot):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the room's creator, a captain of either side, or workspace staff may close it",
            )
        if room.closed_at is None:
            room.closed_at = datetime.now(UTC)
            await session.commit()
        return await self.get_room_by_token(session, user, token)


scrim_service = ScrimService()
