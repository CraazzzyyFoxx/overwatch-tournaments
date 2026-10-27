"""Read-side helpers: active-session lookup and the board snapshot."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NamedTuple
from uuid import uuid4

from cashews import cache
from loguru import logger
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from shared.models.draft import DraftSession
from shared.repository.draft import (
    DraftPickRepository,
    DraftSessionRepository,
    DraftTeamRepository,
)
from shared.repository.registration import RegistrationFormVersionRepository
from src import schemas
from src.services.draft import loaders
from src.services.draft import realtime as draft_rt
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service, single_flight

# Safety-net TTL for the public board cache: the event-id in the key already
# invalidates on every persisted draft event, so the TTL only bounds how long a
# role or rank edited elsewhere (read live, never evented on the board) stays
# stale, and expires dead keys.
_BOARD_CACHE_TTL_SECONDS = 5


def _board_cache_key(session_id: int, last_event_id: int | None) -> str:
    # The "backend:" prefix routes the key to the backend configured by
    # cache.setup() (cashews routes strictly by key prefix).
    return f"backend:balancer:draft_board:{session_id}:{last_event_id or 0}"


# Same safety net as the board, stretched over the gateway's 15s read deadline:
# a client that timed out and refetches the same board state gets the answer
# the first run produced instead of starting another.
_SHARED_READ_TTL = "15s"


def _shared_read_key(session_id: int, version: int, last_event_id: int | None, parts: tuple[Any, ...]) -> str:
    tail = ":".join(str(part) for part in parts)
    return f"backend:balancer:draft_read:{session_id}:{version}:{last_event_id or 0}:{tail}"


# Cross-replica single flight: the in-process map folds a replica's own burst,
# but every replica would still rebuild the same answer for a new board state.
# The TTL must outlive a realistic compute (p50 ~8s under load) yet stay under
# the gateway's 15s read deadline, so a dead leader's lock clears while its
# followers can still answer in time.
_LOCK_TTL_SECONDS = 10.0
_LOCK_POLL_SECONDS = 0.1


async def _cached(key: str) -> Any | None:
    try:
        return await cache.get(key)
    except Exception:  # noqa: BLE001 — cache is best-effort
        return None


async def _await_leader(key: str, lock_key: str) -> Any | None:
    """Poll for the leader's answer; give up as soon as its lock is gone without one."""
    deadline = time.monotonic() + _LOCK_TTL_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(_LOCK_POLL_SECONDS)
        result = await _cached(key)
        if result is not None:
            return result
        try:
            if not await cache.is_locked(lock_key):
                return None  # leader died, failed or was cancelled -- answer for ourselves
        except Exception:  # noqa: BLE001 — cache is best-effort
            return None
    return None


async def _compute_once[T](key: str, compute: Callable[[], Awaitable[T]], expire: str) -> T:
    """Compute ``key`` once across replicas; the others reuse the stored answer.

    Whoever wins the Redis ``SET NX PX`` lock computes, stores and releases;
    the rest poll for that answer. A leader's failure is never a follower's
    failure -- its lock disappears without a result and the follower computes
    for itself -- and Redis is best-effort end to end: no cache, or any cache
    error, just means everybody computes.
    """
    if not cache.is_setup():
        return await compute()
    lock_key = f"{key}:lock"
    token = uuid4().hex
    try:
        leader = await cache.set_lock(lock_key, token, expire=_LOCK_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — cache is best-effort
        return await compute()
    if not leader:
        shared = await _await_leader(key, lock_key)
        if shared is not None:
            return shared
    try:
        result = await compute()
        # Stored before the lock goes: a follower that sees the lock gone with
        # no answer would compute for itself.
        try:
            await cache.set(key, result, expire=expire)
        except Exception:  # noqa: BLE001 — cache is best-effort
            pass
    finally:
        if leader:
            try:
                await cache.unlock(lock_key, token)
            except Exception:  # noqa: BLE001 — cache is best-effort
                pass
    return result


class VisibleCustomField(NamedTuple):
    """One public registration custom field, projected onto the draft board."""

    key: str
    label: str
    type: str


def player_custom_fields(
    answers: Mapping[str, Any] | None,
    fields: list[VisibleCustomField],
) -> list[schemas.DraftPlayerCustomFieldRead]:
    """Answer + current label for each visible field this player actually filled.

    ``answers`` is the registration's own ``custom_fields_json``, read live --
    the draft keeps no copy, so which answers a spectator may see is decided by
    the CURRENT form schema (public visibility) against the CURRENT answers.
    Unanswered fields are dropped rather than rendered empty: the inspector is a
    pick aid, and a column of dashes is noise there (unlike the admin table).
    """
    if not answers:
        return []
    return [
        schemas.DraftPlayerCustomFieldRead(key=field.key, label=field.label, type=field.type, value=answers[field.key])
        for field in fields
        if answers.get(field.key) not in (None, "")
    ]


class DraftBoardService:
    def __init__(
        self,
        *,
        sessions_repo: DraftSessionRepository = DraftSessionRepository(),
        teams_repo: DraftTeamRepository = DraftTeamRepository(),
        picks_repo: DraftPickRepository = DraftPickRepository(),
        form_versions_repo: RegistrationFormVersionRepository = RegistrationFormVersionRepository(),
        feasibility: DraftFeasibilityService = feasibility_service,
    ) -> None:
        self.sessions_repo = sessions_repo
        self.teams_repo = teams_repo
        self.picks_repo = picks_repo
        self.form_versions_repo = form_versions_repo
        self.feasibility = feasibility

    async def get_active_session(self, session: AsyncSession, tournament_id: int) -> DraftSession | None:
        active = await self.sessions_repo.get_active_for_tournament(session, tournament_id)
        if active is not None:
            return active
        # Fall back to the most recent (e.g. COMPLETED) session for read-only views.
        return await self.sessions_repo.get_latest_for_tournament(session, tournament_id)

    async def visible_custom_fields(self, session: AsyncSession, tournament_id: int) -> list[VisibleCustomField]:
        """The tournament's PUBLIC custom questions, in schema order.

        Every custom field the organizer left public reaches the board: the form
        builder's visibility switch is the only gate, so an organizer adding a
        question sees it in the draft without a second opt-in.

        Resolved on every board build rather than frozen at seed time, so flipping a
        field's visibility (or renaming its label) shows up in a running draft. The
        schema is read as raw JSON -- balancer-service owns no copy of
        tournament-service's ``FormSchema`` -- so anything malformed is skipped
        instead of breaking the snapshot.

        Builtins are skipped because their answers are not in
        ``custom_fields_json`` at all (see ``registration.answers.custom_answers``);
        they reach the board through the player's own columns.
        """
        raw = await self.form_versions_repo.current_schema_json(session, tournament_id)
        fields: list[VisibleCustomField] = []
        for section in (raw or {}).get("sections") or []:
            if not isinstance(section, dict):
                continue
            for definition in section.get("fields") or []:
                if not isinstance(definition, dict):
                    continue
                kind = definition.get("kind")
                if kind == "builtin":
                    continue
                if definition.get("visibility") != "public":
                    continue
                key = definition.get("key")
                if not isinstance(key, str) or not key:
                    continue
                label = definition.get("label")
                fields.append(
                    VisibleCustomField(
                        key=key,
                        label=label if isinstance(label, str) and label else key,
                        type=kind if isinstance(kind, str) and kind else "text",
                    )
                )
        return fields

    async def session_read(self, session: AsyncSession, draft_session: DraftSession) -> schemas.DraftSessionRead:
        """The only way a draft session leaves the service.

        The roster shape is not a column on the row, so every reader resolves it
        through the one helper that knows which ids a draft resolves from. Both
        levels are cached, so this is free on the hot board path.
        """
        shape = await self.feasibility.resolve_shape(session, draft_session)
        return schemas.DraftSessionRead.from_session(draft_session, shape=shape, discipline=draft_session.discipline)

    async def list_sessions(self, session: AsyncSession, tournament_id: int) -> list[schemas.DraftSessionRead]:
        """Every session of a tournament, newest first."""
        rows = await self.sessions_repo.list_by_tournament(session, tournament_id)
        # The shape lookup behind session_read is cache-backed at both
        # levels, so one call per row costs a dict hit, not a query.
        return [await self.session_read(session, row) for row in rows]

    async def build_board(self, session: AsyncSession, draft_session: DraftSession) -> schemas.DraftBoardSnapshot:
        # The cheap max-event-id read runs on every request and doubles as the
        # cache key: every draft mutation persists a WorkspaceEvent in the same
        # transaction (services.draft.realtime), so new event -> new key -> fresh
        # board, and an unchanged id can safely serve the cached snapshot.
        # One topic: the session's board. Roles and ranks are read live, so an
        # edit made elsewhere shows once the 5 s TTL runs out.
        last_event_id = await draft_rt.last_event_id(session, draft_session.id)
        cache_key = _board_cache_key(draft_session.id, last_event_id)
        cached: schemas.DraftBoardSnapshot | None = await _cached(cache_key) if cache.is_setup() else None
        if cached is None:
            cached = await single_flight(
                cache_key,
                lambda: _compute_once(
                    cache_key,
                    lambda: self._load_board(session, draft_session, last_event_id),
                    f"{_BOARD_CACHE_TTL_SECONDS}s",
                ),
            )
        return cached

    async def _load_board(
        self, session: AsyncSession, draft_session: DraftSession, last_event_id: int | None
    ) -> schemas.DraftBoardSnapshot:
        """Build the public board snapshot (no board caching -- see ``build_board``; its seats ride the shared read
        snapshot -- see ``DraftFeasibilityService.board_snapshot``)."""
        teams = await self.teams_repo.list_by_session(session, draft_session.id, options=loaders.team_options())
        picks = await self.picks_repo.list_by_session(session, draft_session.id, options=loaders.pick_options())
        # Players and their ONE roster resolve (roles, ranks, sub-role, flex, notes, custom-field answers, live off
        # the registration) come off the read snapshot of this very state, shared with its fit and queue reads.
        snapshot = await self.feasibility.board_snapshot(
            session, draft_session, last_event_id, max_age=_BOARD_CACHE_TTL_SECONDS
        )
        players, rosters = snapshot.players, snapshot.rosters

        # Skipped entirely for a pool where nobody answered a custom field, so
        # those drafts pay nothing for the feature.
        custom_field_defs = (
            await self.visible_custom_fields(session, draft_session.tournament_id)
            if any((rosters[p.id].custom_fields if p.id in rosters else None) for p in players)
            else []
        )

        # The current pick always belongs to this session, so it is among `picks`
        # (loaded with pick_options above) — no extra fetch needed.
        current = (
            next((p for p in picks if p.id == draft_session.current_pick_id), None)
            if draft_session.current_pick_id
            else None
        )
        shape = await self.feasibility.resolve_shape(session, draft_session)
        dimension = await loaders.rated_dimension(session, draft_session)
        # The crown a seat shows is its team's current captain (a mix host may hand a team over mid-draft); a team
        # whose captain has no member falls back to the seed flag.
        crowns = {team.id: team.captain_workspace_member_id for team in teams}
        snapshot = schemas.DraftBoardSnapshot(
            session=await self.session_read(session, draft_session),
            teams=[schemas.DraftTeamRead.model_validate(t) for t in teams],
            picks=[schemas.DraftPickRead.from_pick(p, dimension=dimension) for p in picks],
            players=[
                schemas.DraftPlayerRead.from_seat(
                    p,
                    rosters.get(p.id),
                    shape=shape,
                    custom_fields=custom_field_defs,
                    dimension=dimension,
                    crowned=None
                    if crowns.get(p.drafted_by_team_id) is None
                    else p.workspace_member_id == crowns[p.drafted_by_team_id],
                )
                for p in players
            ],
            current_pick=schemas.DraftPickRead.from_pick(current, dimension=dimension) if current else None,
            last_event_id=last_event_id,
        )
        return snapshot

    async def shared_read[T](
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        parts: tuple[Any, ...],
        compute: Callable[[], Awaitable[T]],
    ) -> T:
        """One computation per board state for a derived read, shared by everyone asking.

        Fit and the pick queue each rebuild the whole draft snapshot, and every
        client refetches both on every draft event, so a room of viewers asking
        within the same second would saturate the worker. Keyed like the board --
        ``last_event_id`` -- plus the session's ``version``, so any persisted
        change is a new key; ``parts`` must carry whatever else the answer depends
        on that no event records (the team, its private queue). Read paths only: a
        write that resolves after mutating would read its own past. One replica
        leads the computation for the whole cluster (``_compute_once``); the
        in-flight map folds the burst that arrives on this one before that answer
        lands.
        """
        event_id = await draft_rt.last_event_id(session, draft_session.id)
        key = _shared_read_key(draft_session.id, draft_session.version, event_id, parts)
        if cache.is_setup():
            cached = await _cached(key)
            if cached is not None:
                return cached
        return await single_flight(key, lambda: _compute_once(key, compute, _SHARED_READ_TTL))


board_service = DraftBoardService()

# --- prewarm ------------------------------------------------------------------

_prewarm_session_factory: async_sessionmaker[AsyncSession] | None = None
_prewarms: set[asyncio.Task[None]] = set()


def configure_prewarm(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Build every committed board state before the room asks for it (``serve.py``); unset in tests and scripts."""
    global _prewarm_session_factory
    _prewarm_session_factory = session_factory


async def _prewarm(session_factory: async_sessionmaker[AsyncSession], draft_session_id: int) -> None:
    """Build the board of a just-committed state, and with it the read snapshot it shares, so the room's re-reads
    (a rollback's board herd, every pick's fit and queue) find both warm instead of all building them at once.
    Best-effort: a failure leaves the readers to build it themselves, as before."""
    try:
        async with session_factory() as session:
            draft = await board_service.sessions_repo.get(session, draft_session_id)
            if draft is not None:
                await board_service.build_board(session, draft)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("Draft board prewarm failed for session {}", draft_session_id)


@event.listens_for(Session, "after_commit")
def _prewarm_moved_boards(session: Session) -> None:
    if session.in_nested_transaction():
        return
    # A mark a rolled-back transaction left behind costs one spare build at most.
    moved: set[int] | None = session.info.pop(draft_rt.MOVED_BOARDS_KEY, None)
    if not moved or _prewarm_session_factory is None:
        return
    loop = asyncio.get_running_loop()
    for draft_session_id in moved:
        task = loop.create_task(_prewarm(_prewarm_session_factory, draft_session_id))
        _prewarms.add(task)
        task.add_done_callback(_prewarms.discard)
