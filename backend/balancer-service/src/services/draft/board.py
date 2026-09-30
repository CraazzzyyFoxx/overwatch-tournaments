"""Read-side helpers: active-session lookup and the board snapshot."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, NamedTuple

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.balancer.draft import DraftSession
from shared.models.platform.realtime import WorkspaceEvent
from shared.models.registration.registration import BalancerRegistrationForm, BalancerRegistrationFormVersion
from shared.repository.draft import (
    DraftPickRepository,
    DraftPlayerRepository,
    DraftSessionRepository,
    DraftTeamRepository,
)
from shared.services.realtime import Scope
from src import schemas
from src.services.draft import loaders
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.rosters import DraftRosterService, draft_rosters

# Safety-net TTL for the public board cache: the event-id in the key already
# invalidates on every persisted draft/registration event, so the TTL only
# bounds staleness for hypothetical writes that bypass the event log and
# expires dead keys.
_BOARD_CACHE_TTL = "5s"


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


_inflight: dict[str, asyncio.Future[Any]] = {}


async def _single_flight[T](key: str, compute: Callable[[], Awaitable[T]]) -> T:
    """Run ``compute`` once per ``key`` at a time in this process; concurrent callers await that run.

    A waiter never inherits the leader's failure: if the leader raises (or its
    request is cancelled), the waiter computes for itself, so one caller's error
    or disconnect cannot fail everybody else's request.
    """
    pending = _inflight.get(key)
    if pending is not None:
        try:
            return await asyncio.shield(pending)
        except Exception:  # noqa: BLE001 — the leader failed; answer for ourselves
            return await compute()
    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    _inflight[key] = future
    try:
        result = await compute()
    except BaseException as exc:
        future.set_exception(exc if isinstance(exc, Exception) else RuntimeError("shared read abandoned"))
        future.exception()  # retrieved: waiters recover on their own, nothing left to log
        raise
    else:
        future.set_result(result)
        return result
    finally:
        del _inflight[key]


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
    the draft no longer keeps a copy, so which answers a spectator may see is
    decided by the CURRENT form schema (public visibility) against the CURRENT
    answers.
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
        players_repo: DraftPlayerRepository = DraftPlayerRepository(),
        picks_repo: DraftPickRepository = DraftPickRepository(),
        feasibility: DraftFeasibilityService = feasibility_service,
        rosters: DraftRosterService = draft_rosters,
    ) -> None:
        self.sessions_repo = sessions_repo
        self.teams_repo = teams_repo
        self.players_repo = players_repo
        self.picks_repo = picks_repo
        self.feasibility = feasibility
        self.rosters = rosters

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
        raw = await session.scalar(
            sa.select(BalancerRegistrationFormVersion.schema_json)
            .join(
                BalancerRegistrationForm,
                BalancerRegistrationForm.current_version_id == BalancerRegistrationFormVersion.id,
            )
            .where(BalancerRegistrationForm.tournament_id == tournament_id)
        )
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

        The roster shape is no longer a column on the row, so every reader resolves
        it through the one helper that knows which ids a draft resolves from. Both
        levels are cached, so this is free on the hot board path.
        """
        shape = await self.feasibility.resolve_shape(session, draft_session)
        return schemas.DraftSessionRead.from_session(draft_session, shape=shape)

    async def build_board(self, session: AsyncSession, draft_session: DraftSession) -> schemas.DraftBoardSnapshot:
        # The cheap max-event-id read runs on every request and doubles as the
        # cache key: every draft mutation persists a WorkspaceEvent in the same
        # transaction (services.draft.realtime), so new event -> new key -> fresh
        # board, and an unchanged id can safely serve the cached snapshot.
        # Two topics, because roles and ranks are no longer copied into the draft:
        # a rank typed in the balancer changes what this board shows, and a
        # registration edit lands on the tournament's INVALIDATION topic
        # (tournament-service, resource ``tournament.registrations``). Keying on
        # the draft topic alone would serve the pre-edit ranks until the TTL
        # expired.
        last_event_id = await self.last_event_id(session, draft_session)
        cache_key = _board_cache_key(draft_session.id, last_event_id)
        if cache.is_setup():
            try:
                cached = await cache.get(cache_key)
            except Exception:  # noqa: BLE001 — cache is best-effort
                cached = None
            if cached is not None:
                # server_time drives client clock sync; never serve a stale one.
                return cached.model_copy(update={"server_time": datetime.now(UTC)})

        teams = await self.teams_repo.list_by_session(session, draft_session.id, options=loaders.team_options())
        picks = await self.picks_repo.list_by_session(session, draft_session.id, options=loaders.pick_options())
        players = await self.players_repo.list_by_session(session, draft_session.id, options=loaders.player_options())
        # ONE resolve for the whole board: roles, ranks, sub-role, flex, notes and
        # custom-field answers all come from here, live off the registration.
        rosters = await self.rosters.load(session, draft_session, players)

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
        snapshot = schemas.DraftBoardSnapshot(
            session=await self.session_read(session, draft_session),
            teams=[schemas.DraftTeamRead.model_validate(t) for t in teams],
            picks=[schemas.DraftPickRead.model_validate(p) for p in picks],
            players=[
                schemas.DraftPlayerRead.from_seat(
                    p,
                    rosters.get(p.id),
                    shape=shape,
                    custom_fields=custom_field_defs,
                )
                for p in players
            ],
            current_pick=schemas.DraftPickRead.model_validate(current) if current else None,
            server_time=datetime.now(UTC),
            last_event_id=last_event_id,
        )
        if cache.is_setup():
            try:
                await cache.set(cache_key, snapshot, expire=_BOARD_CACHE_TTL)
            except Exception:  # noqa: BLE001 — cache is best-effort
                pass
        return snapshot

    async def last_event_id(self, session: AsyncSession, draft_session: DraftSession) -> int | None:
        """Newest event on the draft topic or the tournament's invalidation topic (see ``build_board``)."""
        scope = Scope.tournament(draft_session.tournament_id)
        topics = (scope.domain_topic("draft"), scope.invalidation_topic)
        return await session.scalar(sa.select(sa.func.max(WorkspaceEvent.id)).where(WorkspaceEvent.topic.in_(topics)))

    async def shared_read[T](
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        parts: tuple[Any, ...],
        compute: Callable[[], Awaitable[T]],
    ) -> T:
        """One computation per board state for a derived read, shared by everyone asking.

        Fit and the pick queue each rebuild the whole draft snapshot, and every
        client refetches both on every draft event: 25 viewers asking within the
        same second saturated the worker (2026-09-30, 8s p50, 504s past 15s).
        Keyed like the board -- ``last_event_id`` -- plus the session's
        ``version``, so any persisted change is a new key; ``parts`` must carry
        whatever else the answer depends on that no event records (the team, its
        private queue). Redis shares the answer across replicas; the in-flight map
        folds the burst that arrives before the first answer lands. Read paths
        only: a write that resolves after mutating would read its own past.
        """
        event_id = await self.last_event_id(session, draft_session)
        key = _shared_read_key(draft_session.id, draft_session.version, event_id, parts)
        if cache.is_setup():
            try:
                cached = await cache.get(key)
            except Exception:  # noqa: BLE001 — cache is best-effort
                cached = None
            if cached is not None:
                return cached

        async def compute_and_store() -> T:
            result = await compute()
            if cache.is_setup():
                try:
                    await cache.set(key, result, expire=_SHARED_READ_TTL)
                except Exception:  # noqa: BLE001 — cache is best-effort
                    pass
            return result

        return await _single_flight(key, compute_and_store)


board_service = DraftBoardService()
