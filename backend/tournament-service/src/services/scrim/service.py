"""Provisioning for ad-hoc scrim rooms.

Design: ``docs/plans/2026-08-12-scrim-rooms.md``.

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
from datetime import UTC, datetime
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from shared.core import http_status as status
from shared.core.enums import (
    EncounterStatus,
    MapVetoMode,
    PickBanKind,
    StageType,
    TournamentStatus,
)
from shared.core.errors import BaseAPIException as HTTPException

# Direct imports rather than through ``src.models``: that package re-exports only
# part of the tournament domain, and these four modules are not in it. Same as
# ``services/encounter/pick_ban_session.py`` and ``services/admin/preview_access.py``.
from shared.models.tournament.pick_ban import (
    PickBanConfig,
    PickBanConfigItem,
    PickBanConfigSlot,
    PickBanConfigSlotItem,
)
from shared.models.tournament.scrim import ScrimRoom
from shared.repository import (
    EncounterRepository,
    ScrimRoomRepository,
    StageRepository,
    TeamRepository,
    TournamentRepository,
    UserRepository,
)
from shared.services.settings_provider import settings_provider
from shared.services.tournament.visibility import assert_tournament_viewable
from src import models
from src.services.encounter.pick_ban_session import (
    pick_ban_session_service,
    validate_pick_ban_config,
    validate_pick_ban_slot_config,
)
from src.services.encounter.veto_session import (
    REASON_NOT_CONFIGURED,
    REASON_SLOT_COUNT_MISMATCH,
    REASON_SLOT_UNDERFILLED,
    SLOT_CANDIDATE_FLOOR,
)

Side = Literal["home", "away"]

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


# ── pool ─────────────────────────────────────────────────────────────────────


def _clone_config(source: PickBanConfig, *, tournament_id: int, stage_id: int) -> PickBanConfig:
    """A stage-scoped copy of ``source`` for one room.

    A copy, not a reference: the room must keep playing the pool it opened with
    even if the organizer edits the tournament's config afterwards — the same
    "a running session is never silently rewritten" rule the engine already
    holds for tournament play.
    """
    clone = PickBanConfig(
        tournament_id=tournament_id,
        kind=source.kind,
        stage_id=stage_id,
        round=None,
        mode=source.mode,
        first_pick_rule=source.first_pick_rule,
        first_ban_rotation=source.first_ban_rotation,
        turn_timer_seconds=source.turn_timer_seconds,
        preset=source.preset,
        sequence_json=list(source.sequence_json),
        no_repeat_scope=source.no_repeat_scope,
        unique_attribute_per_side_per_round=source.unique_attribute_per_side_per_round,
        allow_protect=source.allow_protect,
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


def _config_from_input(payload: dict[str, Any], *, tournament_id: int, stage_id: int) -> PickBanConfig:
    """Build one room-scoped config from a custom-pool entry.

    Validated with the SAME validators the organizer's config editor uses, so a
    room cannot be provisioned into a shape the engine would later refuse to
    open a session for — which would strand the room in ``misconfigured`` with no
    way for its captains to fix it.
    """
    kind = PickBanKind(payload["kind"])
    mode = MapVetoMode(payload.get("mode") or MapVetoMode.POOL.value)
    slots = payload.get("slots") or []
    item_ids = payload.get("item_ids") or []
    sequence = payload.get("sequence") or []

    if mode == MapVetoMode.SLOTS:
        if item_ids or sequence:
            raise HTTPException(status_code=422, detail="item_ids/sequence must be empty in slots mode")
        validate_pick_ban_slot_config(
            [list(slot.get("candidates") or []) for slot in slots],
            reserves=[slot.get("reserve_item_id") for slot in slots],
        )
    else:
        if slots:
            raise HTTPException(status_code=422, detail="slots must be empty in pool mode")
        validate_pick_ban_config(list(sequence), list(item_ids), kind=kind)

    config = PickBanConfig(
        tournament_id=tournament_id,
        kind=kind,
        stage_id=stage_id,
        round=None,
        mode=mode,
        turn_timer_seconds=payload.get("turn_timer_seconds"),
        preset=payload.get("preset"),
        sequence_json=list(sequence),
        unique_attribute_per_side_per_round=payload.get("unique_attribute_per_side_per_round"),
        allow_protect=bool(payload.get("allow_protect", False)),
    )
    # Only assign what the caller actually sent: these columns carry server
    # defaults, and writing ``None`` over them would violate NOT NULL.
    for field in ("first_pick_rule", "first_ban_rotation", "no_repeat_scope"):
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

_ROOM_LOAD = (
    selectinload(ScrimRoom.encounter).selectinload(models.Encounter.home_team),
    selectinload(ScrimRoom.encounter).selectinload(models.Encounter.away_team),
)


def _team_payload(team: models.Team) -> dict:
    """Never optional: both sides are written when the room is provisioned, and
    ``Encounter.home_team_id``/``away_team_id`` cascade on delete, so a ``Team``
    cannot outlive the room that names it (nor the room the team)."""
    return {"id": team.id, "name": team.name, "captain_claimed": team.captain_id is not None}


def _free_side(encounter: models.Encounter) -> Side | None:
    """The side still open to the link's next taker, or None once both are held."""
    if encounter.home_team.captain_id is None:
        return "home"
    if encounter.away_team.captain_id is None:
        return "away"
    return None


#: Reasons ``unavailable_reason`` gives that describe the POOL, not the room's
#: progress. Each one is permanent: it is answered by editing a config, which a
#: scrim has no organizer to do -- so a room in any of these states is bricked and
#: its only recovery is to close it and make another.
_BRICKING_REASONS = frozenset({REASON_NOT_CONFIGURED, REASON_SLOT_COUNT_MISMATCH, REASON_SLOT_UNDERFILLED})


class ScrimService:
    def __init__(
        self,
        *,
        room_repo: ScrimRoomRepository = ScrimRoomRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        stage_repo: StageRepository = StageRepository(),
        team_repo: TeamRepository = TeamRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        user_repo: UserRepository = UserRepository(),
    ) -> None:
        self.room_repo = room_repo
        self.tournament_repo = tournament_repo
        self.stage_repo = stage_repo
        self.team_repo = team_repo
        self.encounter_repo = encounter_repo
        self.user_repo = user_repo

    # ── authorization ────────────────────────────────────────────────────────

    async def _ensure_player(self, session: AsyncSession, user: models.AuthUser) -> models.User:
        """The ``players.user`` row a captain must have, created on demand.

        Same provisioning the registration flow already does
        (``services/registration/service.py``): ``Team.captain_id`` points at the
        domain player, not the auth user, and a scrim captain may never have
        registered for anything.

        Deliberately not ``UserRepository.ensure_for_auth_user``: that one falls
        back to a ``user-<id>`` name and suffixes it on collision, which writes a
        different row than this has always written.
        """
        player = await self.user_repo.get_by_auth_user_id(session, user.id)
        if player is not None:
            return player
        return await self.user_repo.create(session, models.User(name=user.username or user.email, auth_user_id=user.id))

    # ── container ────────────────────────────────────────────────────────────

    async def _ensure_container(self, session: AsyncSession, workspace_id: int) -> models.Tournament:
        """The workspace's single hidden scrim container, created on first use.

        One per workspace, never one per room: ``Tournament.id`` is read as an
        ordinal season timeline by the ML layer (see the ``ScrimRoom`` docstring), so
        a container per room would inject data-less rows into it.

        Serialized on an advisory lock — two members creating their first room at the
        same moment would otherwise each see "no container" and make one. A duplicate
        would be harmless (both hidden, each holding its own rooms) but permanent,
        and the lock costs one statement, so it is not worth tolerating. Same pattern
        as ``shared/services/tournament/computation.py``.
        """
        await session.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(f"scrim:{workspace_id}"))))
        # Stays in the service: no repository read filters a hidden tournament by
        # name, and the ``order_by(id).limit(1)`` is what makes a duplicate
        # container -- harmless but permanent -- resolve to the same row every time.
        container = await session.scalar(
            self.tournament_repo.select()
            .where(
                models.Tournament.workspace_id == workspace_id,
                models.Tournament.is_hidden.is_(True),
                models.Tournament.name == CONTAINER_NAME,
            )
            .order_by(models.Tournament.id)
            .limit(1)
        )
        if container is not None:
            return container
        now = datetime.now(UTC)
        container = models.Tournament(
            workspace_id=workspace_id,
            name=CONTAINER_NAME,
            # Deterministic, not generated: one container per workspace (see the
            # lookup above), so workspace_id alone already guarantees uniqueness
            # without the collision-checking path real tournaments go through.
            # Never surfaced (is_hidden, not a real tournament), so a stable
            # internal value is all the public-URL slug column needs here.
            slug=f"scrims-{workspace_id}",
            description="Container for ad-hoc scrim rooms. Not a real tournament.",
            is_hidden=True,
            status=TournamentStatus.LIVE,
            # Both dates set, even though a container neither starts nor ends. The
            # columns are nullable and purely informational, but ``TournamentRead``
            # declares them NOT NULL and every one of ~15 render sites (public and
            # admin) reads them unguarded -- a contract that held because the admin
            # create form requires both. A container with NULL dates was the single
            # violator and 500'd the admin tournament list, which is the one list that
            # shows hidden rows. Its creation instant is the least misleading value
            # available: the row did come into existence then.
            start_date=now,
            end_date=now,
            # Nothing schedules or advances this row; leaving automation on would let
            # the tournament worker walk its status through a phase schedule it does
            # not have.
            auto_transitions_enabled=False,
        )
        return await self.tournament_repo.create(session, container)

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
            await assert_tournament_viewable(session, user, int(origin_id))
            configs: list[PickBanConfig] = []
            for kind in (PickBanKind.MAP, PickBanKind.HERO):
                resolved = await pick_ban_session_service.resolve_config_at_level(
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
            return [_config_from_input(entry, tournament_id=tournament_id, stage_id=stage_id) for entry in entries]

        raise HTTPException(status_code=422, detail="pool.source must be 'copy' or 'custom'")

    # ── reads ───────────────────────────────────────────────────────────────

    async def _load_room(self, session: AsyncSession, token: str) -> ScrimRoom:
        room = await self.room_repo.get_by_token(session, token, options=_ROOM_LOAD)
        if room is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrim room not found")
        return room

    async def get_room_by_token(self, session: AsyncSession, user: models.AuthUser | None, token: str) -> dict:
        """One room, gated by the container's own visibility rules.

        ``assert_tournament_viewable`` is what makes a room private: a stranger with
        the token still gets 404, because holding the link is not membership. The
        link only matters for the ONE action it unlocks — see ``claim_side``.
        """
        room = await self._load_room(session, token)
        await assert_tournament_viewable(session, user, room.tournament_id)
        return await self.serialize_room(session, room, user)

    async def list_rooms_for_viewer(
        self, session: AsyncSession, user: models.AuthUser, workspace_id: int
    ) -> list[dict]:
        """The viewer's own rooms — created by them, or captained by them.

        Its own read rather than ``/encounters?scope=my_team``: that browse joins
        ``Player`` rows (a scrim team has none) and unconditionally excludes hidden
        tournaments, so it can never surface a scrim by construction.

        Deliberately NOT ``DISTINCT``. Every join below is to a primary key --
        ``ScrimRoom.encounter_id`` is unique, and each side resolves one ``Team`` row
        -- so the result is exactly one row per room and there is nothing to
        de-duplicate. A ``DISTINCT`` here is also outright invalid: Postgres requires
        every ORDER BY expression to appear in the select list under it, and the
        ordering below sorts on a computed ``closed_at IS NULL``, which raises
        ``InvalidColumnReferenceError``. It shipped with one and 500'd the list.
        """
        require_workspace_member(user, workspace_id)
        player_ids = sa.select(models.User.id).where(models.User.auth_user_id == user.id).scalar_subquery()
        home = aliased(models.Team)
        away = aliased(models.Team)
        # Stays in the service rather than ``ScrimRoomRepository.list_for_workspace``:
        # that read filters on workspace/closed/tournament only, while this one is a
        # three-join projection gated on "created by me OR captained by me" and
        # ordered open-first. Built from the repository's select() all the same.
        rows = await session.execute(
            self.room_repo.select()
            .join(models.Encounter, models.Encounter.id == ScrimRoom.encounter_id)
            .join(home, home.id == models.Encounter.home_team_id, isouter=True)
            .join(away, away.id == models.Encounter.away_team_id, isouter=True)
            .where(
                ScrimRoom.workspace_id == workspace_id,
                sa.or_(
                    ScrimRoom.created_by_auth_user_id == user.id,
                    home.captain_id.in_(player_ids),
                    away.captain_id.in_(player_ids),
                ),
            )
            .options(*_ROOM_LOAD)
            # Open rooms first, then newest closed: the list's job is "what am I in
            # right now", with history underneath it.
            .order_by(ScrimRoom.closed_at.is_(None).desc(), ScrimRoom.id.desc())
        )
        rooms = list(rows.scalars().all())
        player_id = await self.user_repo.get_id_by_auth_user_id(session, user.id) if user is not None else None
        return [self._serialize_room(room, user, player_id) for room in rooms]

    def _viewer_side_for_player(self, room: ScrimRoom, player_id: int | None) -> Side | None:
        if player_id is None:
            return None
        encounter = room.encounter
        if encounter.home_team.captain_id == player_id:
            return "home"
        if encounter.away_team.captain_id == player_id:
            return "away"
        return None

    async def _viewer_side(self, session: AsyncSession, room: ScrimRoom, user: models.AuthUser | None) -> Side | None:
        if user is None:
            return None
        player_id = await self.user_repo.get_id_by_auth_user_id(session, user.id)
        return self._viewer_side_for_player(room, player_id)

    def _serialize_room(self, room: ScrimRoom, user: models.AuthUser | None, player_id: int | None) -> dict:
        encounter = room.encounter
        side = self._viewer_side_for_player(room, player_id)
        free_side = _free_side(encounter)
        can_claim = (
            side is None
            and free_side is not None
            and room.closed_at is None
            and user is not None
            and (user.is_superuser or room.workspace_id in user.get_workspace_ids())
        )
        return {
            "id": room.id,
            "token": room.token,
            "label": room.label,
            "workspace_id": room.workspace_id,
            "tournament_id": room.tournament_id,
            "stage_id": room.stage_id,
            "encounter_id": room.encounter_id,
            "best_of": encounter.best_of,
            "home_team": _team_payload(encounter.home_team),
            "away_team": _team_payload(encounter.away_team),
            "viewer_side": side,
            "can_claim": can_claim,
            "created_at": room.created_at,
            "closed_at": room.closed_at,
        }

    async def serialize_room(self, session: AsyncSession, room: ScrimRoom, user: models.AuthUser | None) -> dict:
        player_id = await self.user_repo.get_id_by_auth_user_id(session, user.id) if user is not None else None
        return self._serialize_room(room, user, player_id)

    # ── writes ──────────────────────────────────────────────────────────────

    async def _assert_under_cap(self, session: AsyncSession, user: models.AuthUser, limit: int) -> None:
        # A bare aggregate, so it stays here rather than in the repository (the
        # ``count(*)`` also has to answer ``None`` as zero, see the guard below).
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
        best_of: int,
    ) -> None:
        """Refuse a room the engine would not open a session for.

        Asked of the engine rather than re-derived here: ``unavailable_reason`` runs
        the same checks ``ensure_pick_ban_session`` does, against the rows just
        written, so the two cannot drift. Anything it reports about the room's
        *progress* -- nobody is ready yet, hero bans waiting on a map -- is the normal
        state of a fresh room and passes.

        This closes the gap that let ``pool.source = "copy"`` brick a room: the custom
        branch validates its own payload, but a copied config was trusted, so
        borrowing a 3-slot round for a best-of-5 produced a room whose only screen
        read "The pool does not cover this series -- the organizer has to add the
        missing slots", naming a person a scrim does not have.
        """
        for kind in kinds:
            reason = await pick_ban_session_service.unavailable_reason(session, encounter, kind)
            if reason not in _BRICKING_REASONS:
                continue
            config = await pick_ban_session_service.resolve_config_at_level(
                session,
                tournament_id=encounter.tournament_id,
                kind=kind,
                stage_id=encounter.stage_id,
                round=None,
            )
            slots = len(config.slots) if config is not None else 0
            if config is not None and not pick_ban_session_service.has_pool(config):
                # A rules template: rotation and timer authored for narrower
                # scopes to inherit, with no candidates of its own to play.
                detail = (
                    f"That {kind.value} pool has no candidates configured — it is a rules template. "
                    "Pick a different round, or author the pool at that scope."
                )
            elif reason == REASON_SLOT_COUNT_MISMATCH:
                detail = (
                    f"That pool has {slots} map slot(s), so it plays a best-of-{slots} at most. "
                    f"Lower best_of to {slots} or copy a round with more slots."
                )
            elif reason == REASON_SLOT_UNDERFILLED:
                detail = (
                    f"One of that pool's first {best_of} slots offers fewer than {SLOT_CANDIDATE_FLOOR} "
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
        label: str,
        best_of: int,
        home_team_name: str,
        away_team_name: str,
        pool: dict[str, Any],
    ) -> dict:
        """Provision one room and return it. Commits.

        The creator takes the home side immediately; the away side stays unclaimed
        until someone opens the link. That asymmetry is the point of the token — the
        room is usable the moment it exists, and the opponent needs no invitation
        beyond the URL.
        """
        require_workspace_member(user, workspace_id)
        config = await settings_provider.get_scrim_config(session)
        await self._assert_under_cap(session, user, config.max_open_rooms_per_user)
        if best_of < 1 or best_of > config.max_best_of:
            raise HTTPException(status_code=422, detail=f"best_of must be between 1 and {config.max_best_of}")

        container = await self._ensure_container(session, workspace_id)

        # ``get_next_order`` answers 0 for a container with no stages yet, where a
        # room's stage starts at 1 -- which is what the ``or 1`` below preserves.
        next_order = await self.stage_repo.get_next_order(session, container.id)
        stage = models.Stage(
            tournament_id=container.id,
            name=label,
            description="Scrim room",
            # The stage exists so this room's pool has a cascade level of its own
            # (``uq_pick_ban_config_level`` allows only one config per level). The type
            # is otherwise arbitrary — but it is NOT unread, as this comment used to
            # claim: ``standings/service.py:_build_elimination_stage_standings`` treats
            # an elimination stage with no seeds as "derive the bracket from its
            # encounters", and will invent placings for these two rosterless teams if
            # it is ever handed the container. That is why the recalculation is skipped
            # at the enqueue site (``shared/services/scrim_scope.py``,
            # docs/plans/2026-08-12-scrim-rooms.md §5) instead of relying on the shape
            # of a room being inert.
            stage_type=StageType.SINGLE_ELIMINATION,
            max_rounds=1,
            order=int(next_order or 1),
            # A scrim room has no preview phase -- it is live the instant it is
            # created, so its stage must not read as an organizer's un-activated
            # bracket (``shared.services.bracket.usability.is_encounter_live``).
            is_published=True,
        )
        # Seeded while transient: once flushed, the first touch of a collection
        # nothing loaded would lazy-SELECT (MissingGreenlet under async).
        stage.round_best_of = []
        await self.stage_repo.create(session, stage)

        configs = await self._build_configs(session, user, pool, tournament_id=container.id, stage_id=stage.id)
        for pick_ban_config in configs:
            # No repository for ``PickBanConfig``: the graph below it (items, slots,
            # slot items) is written by cascade off this one ``add``.
            session.add(pick_ban_config)

        captain = await self._ensure_player(session, user)
        home = models.Team(tournament_id=container.id, name=home_team_name, balancer_name=home_team_name)
        home.captain_id = captain.id
        away = models.Team(tournament_id=container.id, name=away_team_name, balancer_name=away_team_name)
        await self.team_repo.create_many(session, [home, away])

        encounter = models.Encounter(
            name=label,
            tournament_id=container.id,
            stage_id=stage.id,
            home_team_id=home.id,
            away_team_id=away.id,
            home_score=0,
            away_score=0,
            round=1,
            best_of=best_of,
            status=EncounterStatus.OPEN,
        )
        await self.encounter_repo.create(session, encounter)

        await self._assert_playable(session, encounter, [config.kind for config in configs], best_of=best_of)

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

        existing_side = await self._viewer_side(session, room, user)
        if existing_side is not None:
            # Idempotent for the captain who already holds a side, and a refusal for
            # anyone trying to hold both: the engine reads authority straight off
            # ``captain_id``, so one user on both sides could ban for both.
            return await self.serialize_room(session, room, user)

        side = _free_side(room.encounter)
        if side is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Both sides are already claimed")

        captain = await self._ensure_player(session, user)
        team = room.encounter.home_team if side == "home" else room.encounter.away_team
        # Conditional UPDATE, not an assignment: two opponents opening the link
        # together would both read "unclaimed" and the later flush would silently
        # overwrite the earlier captain.
        claimed = await session.execute(
            sa.update(models.Team)
            .where(models.Team.id == team.id, models.Team.captain_id.is_(None))
            .values(captain_id=captain.id)
        )
        if claimed.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That side was just claimed")
        await session.commit()
        await session.refresh(room.encounter)
        return await self.get_room_by_token(session, user, token)

    async def close_room(self, session: AsyncSession, user: models.AuthUser, token: str) -> dict:
        """Close a room, freeing its creator's cap slot. Commits.

        Not a delete: the encounter, its pick-ban session and its reported maps are
        the scrim's history, and both captains keep reading them through the preview
        allowlist afterwards.
        """
        room = await self._load_room(session, token)
        side = await self._viewer_side(session, room, user)
        if room.created_by_auth_user_id != user.id and side is None and not user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the room's creator or a captain may close it",
            )
        if room.closed_at is None:
            room.closed_at = datetime.now(UTC)
            await session.commit()
        return await self.get_room_by_token(session, user, token)


scrim_service = ScrimService()
