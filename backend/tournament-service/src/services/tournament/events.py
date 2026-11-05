from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared import models
from shared.core.enums import FlowNodeKind
from shared.disciplines import discipline as discipline_spec
from shared.messaging.config import (
    ACHIEVEMENT_EVALUATE_QUEUE,
    FLOW_NODE_STATE_CHANGED_ROUTING_KEY,
    PLAYER_EVENTS_EXCHANGE,
    PLAYER_REFRESH_REQUESTED_ROUTING_KEY,
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_STATE_CHANGED_ROUTING_KEY,
    TOURNAMENT_VOICE_SYNC_ROUTING_KEY,
)
from shared.messaging.outbox import enqueue_outbox_event
from shared.schemas.events import (
    AchievementEvaluateEvent,
    FlowNodeStateChangedEvent,
    PlayerRefreshRequestedEvent,
    TournamentStateChangedEvent,
    TournamentVoiceSyncRequestedEvent,
)
from shared.schemas.identity import PlayerIdentityRead
from shared.services.notifications import PersonalNotification, notify_users
from shared.services.realtime import Resource, Scope, emit, enqueue_invalidation_outbox
from shared.services.scrim_scope import is_scrim_container
from src.services.computation.jobs import jobs_service

#: Tournaments whose standings this transaction already asked for. A result
#: write that completes its encounter reaches ``enqueue_tournament_recalculation``
#: twice -- once from the settlement, once from the caller's own unconditional
#: request (a lobby game, an accepted log, a game correction) -- and a second
#: request bumps the generation past the job the first one created, so that job
#: would be followed by a second full recompute over the very data it just ranked.
_STANDINGS_REQUESTED_KEY = "standings_recalculation_requested"

#: Resources that a write to the tournament's shape (stages, teams, the
#: tournament row itself) stales. ``tournament.structure`` covers the overview,
#: teams, stages, encounters and standings at once, so a page whose set of
#: sections moved repairs itself by refetching those reads.
STRUCTURE_RESOURCES: tuple[Resource, ...] = (Resource.TOURNAMENT_STRUCTURE,)

#: Resources a recomputed or hand-edited result stales: the standings, the
#: encounters feeding their embedded ``matches_history``, and the tournament
#: read that carries the placement summary.
RESULT_RESOURCES: tuple[Resource, ...] = (
    Resource.TOURNAMENT_STANDINGS,
    Resource.TOURNAMENT_DETAIL,
    Resource.TOURNAMENT_ENCOUNTERS,
)


async def publish_tournament_invalidation(
    session: AsyncSession,
    tournament_id: int,
    resources: Sequence[Resource],
) -> None:
    """Stale ``resources`` for this tournament, locally and cross-service.

    The two halves live in one helper because omitting the second is silent:
    the page repairs itself while app-service keeps serving its own cached
    aggregate until its TTL. Writes whose resources no other service caches
    (an image swap, a preview-access grant) call ``emit`` directly rather than
    pay for an outbox row nobody reads.
    """
    scope = Scope.tournament(tournament_id)
    await emit(session, scope=scope, invalidates=resources)
    await enqueue_invalidation_outbox(session, scope=scope, resources=resources)


def _session_info(session: AsyncSession) -> dict[Any, Any] | None:
    """The underlying ``Session.info``, the per-transaction scratch space the
    ``after_commit``/``after_rollback`` listeners below drain."""
    return getattr(getattr(session, "sync_session", None) or session, "info", None)


@event.listens_for(Session, "after_commit")
def _drop_transaction_scratch_after_commit(session: Session) -> None:
    # Per-transaction scratch; a session outlives its transactions. A released
    # savepoint fires this too, but its work is still the outer transaction's.
    if session.in_nested_transaction():
        return
    session.info.pop(_STANDINGS_REQUESTED_KEY, None)


@event.listens_for(Session, "after_rollback")
def _drop_transaction_scratch_after_rollback(session: Session) -> None:
    # Fires for a rolled-back savepoint too: forgetting a request it undid costs at most one spare job.
    session.info.pop(_STANDINGS_REQUESTED_KEY, None)


async def enqueue_tournament_recalculation(
    session: AsyncSession,
    tournament_id: int,
) -> None:
    # A scrim container has nothing to recalculate: every one of its stages is a
    # single ad-hoc room with no stage items, no seeds and no rosters.
    # Recalculating it does not merely waste a job — the elimination branch of
    # the standings builder derives participants from encounters when seeds are
    # absent, so it invents a "1st place" Standing row for every room's two
    # rosterless teams and flips their Stage.is_completed, for EVERY room in the
    # workspace on every captain report of any one of them.
    #
    # Skipped here, at the only automatic door into the standings queue, rather
    # than no-opped in the worker: a job that is created, delivered and then
    # discarded is a permanent per-report cost that looks like health.
    info = _session_info(session)
    requested: set[int] = info.setdefault(_STANDINGS_REQUESTED_KEY, set()) if info is not None else set()
    if tournament_id not in requested and not await is_scrim_container(session, tournament_id):
        await jobs_service.request_standings_recalculation(session, tournament_id)
    requested.add(tournament_id)
    # The realtime invalidation still goes out: it is a cache notification, not a
    # computation, and a room's participants are legitimate viewers of the
    # container.
    await emit(
        session,
        scope=Scope.tournament(tournament_id),
        invalidates=[Resource.TOURNAMENT_ENCOUNTERS],
    )


async def _event_snapshot(
    session: AsyncSession,
    registrations: Sequence[models.Registration],
) -> tuple[Any, list[tuple[int | None, int | None]]]:
    """What the registration events snapshot for ``registrations`` of ONE tournament: the tournament
    (``workspace_id``, ``discipline``, ``name``) and each registrant's ``(player_id, auth_user_id)``.

    At most two reads whatever the batch size, and none for what the caller already holds: the admin
    review paths pass a registration from ``get_registration_by_id``, whose options eager-load
    ``tournament`` and ``workspace_member.player``. Those are read off the instance dict rather than the
    attribute: touching an unloaded relationship on an async session raises instead of lazy-loading,
    which is why ``lifecycle._workspace_id_for`` does the same.

    Registration has no denormalized workspace_id column, and ``workspace_member_id`` is its only
    identity anchor: a registration without a member has no player, and a shadow player (no site
    account behind its ``players.user`` row) no ``auth_user_id``.
    """
    first = registrations[0]
    assert all(r.tournament_id == first.tournament_id for r in registrations), "one tournament per batch"
    tournament = first.__dict__.get("tournament")
    if tournament is None:
        tournament = (
            await session.execute(
                sa.select(models.Tournament.workspace_id, models.Tournament.discipline, models.Tournament.name).where(
                    models.Tournament.id == first.tournament_id
                )
            )
        ).one()
    players = [
        member.__dict__.get("player") if (member := r.__dict__.get("workspace_member")) is not None else None
        for r in registrations
    ]
    member_ids = {
        r.workspace_member_id
        for r, player in zip(registrations, players, strict=True)
        if player is None and r.workspace_member_id is not None
    }
    members: dict[int, Any] = {}
    if member_ids:
        rows = await session.execute(
            sa.select(models.WorkspaceMember.id, models.WorkspaceMember.player_id, models.User.auth_user_id)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(models.WorkspaceMember.id.in_(member_ids))
        )
        members = {row.id: row for row in rows}
    registrants: list[tuple[int | None, int | None]] = []
    for registration, player in zip(registrations, players, strict=True):
        if player is not None:
            registrants.append((player.id, player.auth_user_id))
        elif (row := members.get(registration.workspace_member_id)) is not None:
            registrants.append((row.player_id, row.auth_user_id))
        else:
            registrants.append((None, None))
    return tournament, registrants


def _identity(registration: models.Registration, discipline: str) -> PlayerIdentityRead | None:
    """The registration's primary handle for its tournament's identity provider, as the events carry it.

    Never another provider's handle: a tournament whose discipline declares no provider has no identity.
    """
    provider = discipline_spec(discipline).identity_provider
    if provider is None:
        return None
    primary = registration.primary_game_identity(provider=provider)
    return PlayerIdentityRead.of(provider, primary.handle if primary is not None else None)


async def registration_node_label(session: AsyncSession, tournament_id: int, node_id: int) -> str | None:
    """The registration node's name for a notification, only when the tournament has several intakes.

    A single-node tournament carries the default node name ("Registration", English data), which must not
    be printed as "(Registration)" to a Russian-speaking player.
    """
    rows = (
        await session.execute(
            sa.select(models.FlowNode.id, models.FlowNode.name).where(
                models.FlowNode.tournament_id == tournament_id,
                models.FlowNode.kind == FlowNodeKind.REGISTRATION,
            )
        )
    ).all()
    return next((row.name for row in rows if row.id == node_id), None) if len(rows) > 1 else None


async def _notify_registration_decision(
    session: AsyncSession,
    registrations: Sequence[models.Registration],
    registrants: Sequence[tuple[int | None, int | None]],
    tournament: Any,
    *,
    kind: str,
    registration_node_id: int,
) -> None:
    """Tell each registrant their entry was decided; ``registrants`` is ``_event_snapshot``'s, row for row.

    A shadow player -- a real competitor with no site account behind their
    ``players.user`` row -- has no inbox, so there is simply no row. That is not
    an error: the decision itself is about the registration, not the account.

    ``ponytail:`` no de-duplication. A status toggled approved -> rejected ->
    approved notifies three times, because the write is unconditional. The
    upgrade path is a suppression window inside ``notify_users()`` (skip a repeat of
    the same recipient/kind/entity within N minutes), not a unique index, which
    would also block the legitimate repeat.
    """
    recipients = [
        (registration, recipient)
        for registration, (_player_id, recipient) in zip(registrations, registrants, strict=True)
        if recipient is not None
    ]
    if not recipients:
        return
    node_name = await registration_node_label(session, registrations[0].tournament_id, registration_node_id)
    await notify_users(
        session,
        kind=kind,
        notifications=[
            PersonalNotification(
                recipient_auth_user_id=int(recipient),
                payload={
                    "tournament_id": registration.tournament_id,
                    "tournament_name": tournament.name,
                    "registration_id": registration.id,
                    "registration_node_id": registration_node_id,
                    "node_name": node_name,
                },
                # The organizer that owns the tournament, so their operators can find
                # (and retire) the decision rows their own review produced.
                source_workspace_id=tournament.workspace_id,
            )
            for registration, recipient in recipients
        ],
    )


async def _enqueue_player_refresh(
    session: AsyncSession,
    registration: models.Registration,
    tournament: Any,
    player_id: int | None,
    *,
    source: Literal["tournament_registration", "tournament_recheck"],
    flush: bool = True,
) -> None:
    """Ask the tournament's rank collector (and identity) to re-read the registrant's accounts.

    A registration without a player has no accounts to read: no event.
    """
    if player_id is None:
        return
    await enqueue_outbox_event(
        session,
        PlayerRefreshRequestedEvent(
            user_id=player_id,
            discipline=tournament.discipline,
            workspace_id=tournament.workspace_id,
            source=source,
            registration_id=registration.id,
            identity=_identity(registration, tournament.discipline),
            source_service="tournament-service",
        ),
        exchange=PLAYER_EVENTS_EXCHANGE,
        routing_key=PLAYER_REFRESH_REQUESTED_ROUTING_KEY,
        flush=flush,
    )


async def enqueue_registration_approved(
    session: AsyncSession,
    registration: models.Registration,
    *,
    registration_node_id: int,
) -> None:
    await enqueue_registrations_approved(session, [registration], registration_node_id=registration_node_id)


async def enqueue_registrations_approved(
    session: AsyncSession,
    registrations: Sequence[models.Registration],
    *,
    registration_node_id: int,
) -> None:
    """Per registration of ONE tournament: the player refresh, the registrant's inbox row and the page
    invalidation, in a constant number of statements -- ``bulk_approve_registrations`` approves up to 500 at
    once. The refresh rows ride the inbox rows' flush (or the caller's commit when nobody has an inbox)."""
    if not registrations:
        return
    tournament, registrants = await _event_snapshot(session, registrations)
    for registration, (player_id, _recipient) in zip(registrations, registrants, strict=True):
        await _enqueue_player_refresh(
            session, registration, tournament, player_id, source="tournament_registration", flush=False
        )
        await emit(
            session,
            scope=Scope.tournament(registration.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
            # A row created in this same transaction has no id until it flushes;
            # entity_ids is optional precision, so no id just means no narrowing.
            entity_ids={"registration_ids": [registration.id]} if registration.id is not None else None,
        )
    await _notify_registration_decision(
        session,
        registrations,
        registrants,
        tournament,
        kind="registration.approved",
        registration_node_id=registration_node_id,
    )


async def notify_registration_rejected(
    session: AsyncSession,
    registration: models.Registration,
    *,
    registration_node_id: int,
) -> None:
    """Tell the registrant and the open pages; no domain event, nothing consumes a rejection."""
    tournament, registrants = await _event_snapshot(session, [registration])
    await _notify_registration_decision(
        session,
        [registration],
        registrants,
        tournament,
        kind="registration.rejected",
        registration_node_id=registration_node_id,
    )
    await emit(
        session,
        scope=Scope.tournament(registration.tournament_id),
        invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        # A row created in this same transaction has no id until it flushes;
        # entity_ids is optional precision, so no id just means no narrowing.
        entity_ids={"registration_ids": [registration.id]} if registration.id is not None else None,
    )


async def enqueue_registration_rank_check(
    session: AsyncSession,
    registration: models.Registration,
) -> None:
    """Ask the discipline's rank collector to re-fetch the registrant's accounts (the profile check)."""
    tournament, [(player_id, _recipient)] = await _event_snapshot(session, [registration])
    await _enqueue_player_refresh(session, registration, tournament, player_id, source="tournament_recheck")


async def enqueue_tournament_state_changed(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    old_status: str | None,
    new_status: str,
) -> None:
    await enqueue_outbox_event(
        session,
        TournamentStateChangedEvent(
            tournament_id=tournament.id,
            workspace_id=tournament.workspace_id,
            old_status=old_status,
            new_status=new_status,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key=TOURNAMENT_STATE_CHANGED_ROUTING_KEY,
    )


async def enqueue_flow_node_state_changed(
    session: AsyncSession,
    node: models.FlowNode,
    *,
    workspace_id: int,
    old_status: str,
) -> None:
    await enqueue_outbox_event(
        session,
        FlowNodeStateChangedEvent(
            tournament_id=node.tournament_id,
            workspace_id=workspace_id,
            node_id=node.id,
            kind=node.kind,
            old_status=old_status,
            new_status=node.status,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key=FLOW_NODE_STATE_CHANGED_ROUTING_KEY,
    )


async def enqueue_achievement_evaluation(
    session: AsyncSession,
    tournament: models.Tournament,
    changed_tables: Sequence[str],
) -> None:
    if await is_scrim_container(session, tournament.id):
        return
    await enqueue_outbox_event(
        session,
        AchievementEvaluateEvent(
            workspace_id=tournament.workspace_id,
            tournament_id=tournament.id,
            changed_tables=list(changed_tables),
        ),
        # Default exchange: the routing key IS the queue name.
        exchange=None,
        routing_key=ACHIEVEMENT_EVALUATE_QUEUE.name,
    )


async def enqueue_tournament_voice_sync(session: AsyncSession, tournament: models.Tournament) -> None:
    """Ask discord-service to reconcile this tournament's voice channels (settings saved, "sync" pressed)."""
    await enqueue_outbox_event(
        session,
        TournamentVoiceSyncRequestedEvent(
            tournament_id=tournament.id,
            workspace_id=tournament.workspace_id,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key=TOURNAMENT_VOICE_SYNC_ROUTING_KEY,
    )
