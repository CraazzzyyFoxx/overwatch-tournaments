"""Read-side helpers: active-session lookup and the board snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, NamedTuple

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.balancer.draft import DraftSession
from shared.models.platform.realtime import WorkspaceEvent
from shared.models.registration.registration import BalancerRegistrationForm
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


class VisibleCustomField(NamedTuple):
    """One registration custom field the organizer opted into the draft."""

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
    decided by the CURRENT form (``show_in_draft``) against the CURRENT answers.
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
        """The tournament's ``show_in_draft`` custom-field definitions, in form order.

        Resolved on every board build rather than frozen at seed time, so flipping a
        field's visibility (or renaming its label) shows up in a running draft. The
        definitions are read as raw JSON — balancer-service owns no copy of
        tournament-service's ``CustomFieldDefinition`` — so anything malformed is
        skipped instead of breaking the snapshot.
        """
        raw = await session.scalar(
            sa.select(BalancerRegistrationForm.custom_fields_json).where(
                BalancerRegistrationForm.tournament_id == tournament_id
            )
        )
        fields: list[VisibleCustomField] = []
        for definition in raw or []:
            if not isinstance(definition, dict) or definition.get("show_in_draft") is not True:
                continue
            key = definition.get("key")
            if not isinstance(key, str) or not key:
                continue
            label = definition.get("label")
            field_type = definition.get("type")
            fields.append(
                VisibleCustomField(
                    key=key,
                    label=label if isinstance(label, str) and label else key,
                    type=field_type if isinstance(field_type, str) and field_type else "text",
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
        scope = Scope.tournament(draft_session.tournament_id)
        topics = (scope.domain_topic("draft"), scope.invalidation_topic)
        last_event_id = await session.scalar(
            sa.select(sa.func.max(WorkspaceEvent.id)).where(WorkspaceEvent.topic.in_(topics))
        )
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


board_service = DraftBoardService()
