"""Typed Pydantic models for RabbitMQ event messages.

These schemas provide type safety and validation for all inter-service messaging.
"""

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.schemas.identity import PlayerIdentityRead
from shared.schemas.role import RoleRef


class BaseEvent(BaseModel):
    """Base class for all event messages."""

    event_type: str
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Idempotency key for this event")
    source_service: str | None = Field(default=None, description="Service that produced this event")
    schema_version: int = Field(default=1, description="Event schema version")
    timestamp: float = Field(default_factory=lambda: time.time(), description="UTC epoch timestamp")
    correlation_id: str | None = Field(default=None, description="Request correlation ID for tracing")


class DiscordCommandEvent(BaseEvent):
    """A command for discord-service about one ``discord_message`` row.

    Published by: everything that sends, through
    ``shared.services.discord_messages`` (the outbox, in the transaction that
    claims the row). Consumed by: discord-service.

    The command carries nothing but the row id: the row names the destination
    (``channel``/``target``), the subject the bot renders the message from
    (``kind``/``subject``/``slot``/``payload_json``) and the state the bot
    writes back. ``send`` posts the row's message (a channel post or a DM, by
    ``channel``); ``delete`` removes it. Edits are not commands at all: the bot
    re-renders a live message when the fact it shows changes
    (``pickup_mix.changed``).
    """

    event_type: str = Field(default="discord_command", frozen=True)
    action: Literal["send", "delete"]
    #: ``discord_message.id`` -- the platform's own handle on the message.
    message_ref: int = Field(..., description="discord_message row this command is about")


class NotificationCreatedEvent(BaseEvent):
    """A personal notification row was written; deliver it outside the app.

    Published by: ``shared.services.notifications.notify`` (outbox, same transaction)
    Consumed by: app-service notification delivery
    """

    event_type: str = Field(default="notification.created", frozen=True)
    notification_id: int = Field(..., description="notification.id of the personal row")


class NotificationBroadcastEvent(BaseEvent):
    """Post one event to the workspace's notification channel.

    Carries the payload itself: a broadcast writes no notification row.

    Published by: ``shared.services.notifications.broadcast`` (outbox, same transaction)
    Consumed by: app-service notification delivery
    """

    event_type: str = Field(default="notification.broadcast", frozen=True)
    workspace_id: int = Field(..., description="Workspace whose channel receives the post")
    kind: str = Field(..., description="Notification kind, one of BROADCASTABLE_KINDS")
    payload: dict[str, Any] = Field(..., description="Validated snapshot, same schema as the kind's inbox payload")
    dedupe_key: str = Field(..., description="Producer identity of the event, the ledger key")


class PickupMixChangedEvent(BaseEvent):
    """Something about a workspace's pickup mixes changed; re-project what shows it.

    A fact, not a command: it carries no state, only where to look. Consumers
    read the current state and render from it, so a redelivered, late or
    out-of-order event is harmless. ``custom_game_id`` is ``None`` for a change
    that is not about one mix (a player renamed, a rank corrected), which
    concerns every mix of the workspace.

    Published by: ``shared.services.pickup_mix_realtime.emit_pickup_mix_changed`` (outbox, same transaction), from
    balancer-service's mix writes and tournament-service's mix hero room crossing Pre-game <-> Live
    Consumed by: discord-service's mix projector, which re-renders the mix's live cards
    """

    event_type: str = Field(default="pickup_mix.changed", frozen=True)
    workspace_id: int = Field(..., description="Workspace whose mixes changed")
    custom_game_id: int | None = Field(default=None, description="The mix, or None for workspace-wide")
    change: str = Field(..., description="What changed (roster, member, rank, close...), diagnostic only")


class ProcessIngestJobEvent(BaseEvent):
    """Event for processing one ingest job.

    Published by: stats-service (outbox, reaper, retry, tournament fanout) onto ``stats.ingest.<discipline>``
    Consumed by: stats-service worker selecting that discipline, which refuses a job of another discipline.
    """

    event_type: str = Field(default="process_ingest_job", frozen=True)
    ingest_job_id: int = Field(..., gt=0, description="Authorized stats.ingest_job ID")
    reparse_expected_revision: int | None = Field(
        default=None,
        ge=1,
        description="Set for a revision-fenced replay of a done job: the observation revision seen when it was selected",
    )
    # A Discord upload's message, threaded from ``UploadMatchLogEvent`` to the job's ``MatchLogProcessedEvent``.
    channel_id: int | None = Field(default=None, description="Discord channel of the upload, echoed on the result")
    message_id: int | None = Field(default=None, description="Discord message of the upload, echoed on the result")


class UploadMatchLogEvent(BaseEvent):
    """Event carrying a raw match-log file to be stored + queued for processing.

    Published by: discord-service (bot upload).
    Consumed by: stats-service worker, which stores the log to S3, creates or
    reuses its native ingest job, then enqueues a ``ProcessIngestJobEvent``.

    The file bytes ride in ``content_b64`` (base64). Keep logs reasonably sized:
    the message must fit RabbitMQ's frame/size limits.

    ``channel_id``/``message_id`` name the Discord message the file came from;
    stats echoes them back on ``MatchLogProcessedEvent`` so whichever bot
    replica consumes the result can react on that message. The bot keeps no
    in-memory waiter.
    """

    event_type: str = Field(default="upload_match_log", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    filename: str = Field(..., description="Match log filename")
    content_b64: str = Field(..., description="Base64-encoded raw log file bytes")
    content_type: str | None = Field(default=None, description="Original Content-Type, if known")
    uploader_discord_name: str | None = Field(
        default=None, description="Discord username of the uploader, resolved to a Player on ingest"
    )
    channel_id: int | None = Field(default=None, description="Discord channel the attachment was posted in")
    message_id: int | None = Field(default=None, description="Discord message carrying the attachment")


class MatchLogProcessedEvent(BaseEvent):
    """Result of processing a single match log, sent back to the uploader.

    Published by: stats-service (worker, after the ingest job finishes)
    Consumed by: discord-service ``match_log_result`` (one durable work queue,
    competing replicas): it reacts on the originating message named by
    ``channel_id``/``message_id``. Reactions and a per-file reply are
    idempotent, so a redelivery repeats nothing visible.
    """

    event_type: str = Field(default="match_log_processed", frozen=True)
    tournament_id: int | None = Field(..., description="Tournament hint, nullable if its owner was deleted")
    filename: str = Field(..., description="Processed match log filename")
    status: Literal["done", "failed", "awaiting_link"] = Field(..., description="Persisted processing outcome")
    ingest_job_id: int | None = Field(
        default=None, gt=0, description="Absent only if upload failed before job creation"
    )
    error_message: str | None = None
    channel_id: int | None = Field(default=None, description="Echoed from the upload event")
    message_id: int | None = Field(default=None, description="Echoed from the upload event")

    @model_validator(mode="after")
    def require_completed_job(self):
        if self.ingest_job_id is None and self.status != "failed":
            raise ValueError("A completed or awaiting-link result requires an ingest job")
        return self


class ProcessTournamentLogsEvent(BaseEvent):
    """Event for processing all logs for a tournament.

    Published by: stats-service
    Consumed by: stats-service (background worker)
    """

    event_type: str = Field(default="process_tournament_logs", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID to process logs for")


class BalancerJobEvent(BaseEvent):
    """Event for scheduling a balancer job.

    Published by: balancer-service API
    Consumed by: balancer-service worker
    """

    event_type: str = Field(default="balancer_job", frozen=True)
    job_id: str = Field(..., description="Balancer job identifier")


class TournamentComputationJobEvent(BaseModel):
    """Dispatch one persisted tournament computation job."""

    job_id: int = Field(..., description="tournament.computation_job.id")


class TournamentStandingsInvalidatedEvent(BaseEvent):
    """Domain event requesting a durable standings generation increment."""

    event_type: str = Field(default="tournament_standings_invalidated", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID whose results changed")
    reason: str = Field(default="results_changed", description="Source/reason for observability")


class MatchIngestPlacement(BaseModel):
    """One bound encounter team's canonical placement; ``None`` = the document carries none for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    encounter_team_id: int = Field(..., gt=0)
    placement: int | None = Field(default=None, ge=1)


class MatchIngestExtraParticipant(BaseModel):
    """A participant the observation shows on a team whose roster lacks them (never a stats row id)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    encounter_team_id: int = Field(..., gt=0)
    workspace_member_id: int = Field(..., gt=0)
    handle_snapshot: str = Field(..., min_length=1, max_length=128)
    observed_role: RoleRef | None = None


class MatchIngestedEvent(BaseEvent):
    """One observation revision a stats document bound to an encounter game.

    Published by: stats-service (transactional outbox), event id ``match.ingested:{evidence_id}:{revision}``.
    Consumed by: the tournament match layer, which alone decides whether it is official. Carries no raw document,
    S3 reference or interpreted score facts: only opaque evidence identity, the game-result basis it was captured
    against, canonical placements, the extra participants the roster lacks and the observed map and mode (an accepted
    result fills a game that named neither).
    """

    event_type: str = Field(default="match_ingested", frozen=True)
    workspace_id: int = Field(..., gt=0)
    discipline: str = Field(..., min_length=1, max_length=32)
    encounter_id: int = Field(..., gt=0)
    encounter_game_id: int = Field(..., gt=0)
    evidence_id: int = Field(..., gt=0, description="stats.match.id, opaque to the match layer")
    revision: int = Field(..., ge=1, description="Observation revision of that match")
    ingest_job_id: int = Field(..., gt=0)
    basis_game_result_version: int = Field(..., ge=0, description="game.result_version the binding was made against")
    placements: list[MatchIngestPlacement] = Field(default_factory=list)
    extra_participants: list[MatchIngestExtraParticipant] = Field(default_factory=list)
    map_id: int | None = Field(default=None, gt=0, description="catalog map the observation was played on")
    mode_id: int | None = Field(default=None, gt=0, description="catalog mode of the observation, when it has one")


class CacheInvalidatedEvent(BaseEvent):
    """Cross-service half of a realtime invalidation.

    Published by: whichever service owns the write, through
    ``shared.services.realtime.enqueue_invalidation_outbox`` (transactional
    outbox — Redis pub/sub is at-most-once, and another service's cashews
    entries have no TTL-plus-replay safety net the way clients do).
    Consumed by: every service that caches reads the resources describe.

    ``resources`` are manifest entries (shared/realtime/resources.json), i.e.
    WHAT went stale. There is deliberately no "reason" field: the consumer maps
    resources onto its own cache keys and does not re-derive intent.
    """

    event_type: str = Field(default="cache_invalidated", frozen=True)
    scope_kind: str = Field(..., description="tournament | workspace | user")
    scope_id: int = Field(..., description="Id of the scoped subject")
    resources: list[str] = Field(..., description="Manifest resource names that went stale")
    entity_ids: dict[str, list[int]] = Field(
        default_factory=dict,
        description="Optional narrowing (e.g. {'registration_ids': [77]}); consumers may ignore it",
    )


class EncounterCompletedEvent(BaseEvent):
    """Domain event emitted after an encounter result is finalized."""

    event_type: str = Field(default="encounter_completed", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    encounter_id: int = Field(..., description="Encounter ID")
    home_team_id: int | None = Field(default=None, description="Home team ID")
    away_team_id: int | None = Field(default=None, description="Away team ID")
    winner_team_id: int | None = Field(default=None, description="Winner team ID if determinable")


class RegistrationApprovedEvent(BaseEvent):
    """Domain event emitted when a tournament registration is approved."""

    event_type: str = Field(default="registration_approved", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    workspace_id: int = Field(..., description="Workspace ID")
    registration_id: int = Field(..., description="Registration ID")
    user_id: int | None = Field(default=None, description="Player user ID when linked")
    identity: PlayerIdentityRead | None = Field(
        default=None,
        description="Approved registration's primary handle for its tournament's identity provider",
    )


class RegistrationRankCheckRequestedEvent(RegistrationApprovedEvent):
    """The registrant asked to re-check their profile from their own card.

    Same payload as the approval event, so stats-service runs the same rank check
    for it; a distinct type and routing key so it is never read as an approval.
    """

    event_type: str = Field(default="registration_rank_check_requested", frozen=True)


class TournamentStateChangedEvent(BaseEvent):
    """Domain event emitted when tournament lifecycle state changes.

    Published by: tournament-service (``transition_status``, manual and automatic).
    Consumed by: analytics-worker (``tournament_state_changed``: a ``completed``
    tournament gets its compute job created without anyone clicking), and the
    discord bot's channel registry (per-replica exclusive queue: a finished
    tournament leaves the watched set).
    """

    event_type: str = Field(default="tournament_state_changed", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    workspace_id: int | None = Field(default=None, description="Workspace ID")
    old_status: str | None = Field(default=None, description="Previous tournament status")
    new_status: str = Field(..., description="New tournament status")


class ChallongePushRequestedEvent(BaseEvent):
    """A confirmed result of a Challonge-linked encounter is to be pushed to Challonge.

    Published by: tournament-service, in the transaction that confirmed the
    result (every confirm path: captain reports, organizer result, agreed claim,
    lobby game, accepted log evidence).
    Consumed by: tournament-service ``tournament_challonge_push``, which pushes
    only if the encounter's ``result_version`` still matches -- a reopened and
    re-confirmed encounter supersedes an older, not-yet-pushed request.

    ``event_id`` is deterministic (``challonge_push:<encounter>:<version>``):
    one request per result version, however many times the drain redelivers.
    """

    event_type: str = Field(default="challonge_push_requested", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    encounter_id: int = Field(..., description="Encounter whose result was confirmed")
    result_version: int = Field(..., ge=0, description="encounter.result_version the push carries")

    @model_validator(mode="after")
    def _deterministic_id(self):
        self.event_id = f"challonge_push:{self.encounter_id}:{self.result_version}"
        return self


class PickBanRoomOpenRequestedEvent(BaseEvent):
    """A mix match started with hero bans: its encounter's pick-ban room is to be opened.

    Published by: balancer-service ``start_mix_match``, in the transaction that started the match.
    Consumed by: tournament-service ``tournament_pick_ban_room_open``, which runs the room healer on the encounter.

    ``event_id`` is deterministic (``pick_ban_room_open:<encounter>``): one request per started match.
    """

    event_type: str = Field(default="pick_ban_room_open_requested", frozen=True)
    encounter_id: int = Field(..., description="The started mix encounter")

    @model_validator(mode="after")
    def _deterministic_id(self):
        self.event_id = f"pick_ban_room_open:{self.encounter_id}"
        return self


class WorkspaceMemberChangedEvent(BaseEvent):
    """Workspace membership or workspace roles changed for some auth users.

    Published by: app-service (member add/update/remove, owner transfer,
    workspace create/delete, player delete, profile merge) and by the shared
    RBAC writers every service runs (``shared.rbac.bootstrap.stage_rbac_change``:
    member admission, role grant, bulk role autofill, system-role permission
    reconciliation), in the same transaction as the write.
    Consumed by: identity-service ``workspace_member_changed``, which drops the
    cached RBAC payload of every listed user. Dropping a key is idempotent, so
    a redelivery is harmless and the event needs no deterministic id.
    """

    event_type: str = Field(default="workspace_member_changed", frozen=True)
    workspace_id: int | None = Field(default=None, description="Workspace ID; None when not workspace-scoped")
    auth_user_ids: list[int] = Field(..., min_length=1, description="Auth users whose RBAC must be reloaded")
    change: str = Field(
        ...,
        description="added | roles_changed | removed | owner_transferred | merged | role_permissions_changed"
        " | workspace_deleted | player_deleted",
    )


class SteamAccountChangedEvent(BaseEvent):
    """A Steam ``social_account`` was created or its account id changed.

    Published by: ``shared.services.social_identity`` (every social-account
    writer) in the same transaction as the write, unless the writer already
    supplied the display name. Consumed by: identity-service
    ``steam_account_changed``, which fetches the persona name into
    ``social_account.display_name``. Re-fetching is idempotent, so a redelivery
    is harmless.
    """

    event_type: str = Field(default="steam_account_changed", frozen=True)
    social_account_id: int = Field(..., description="players.social_account id")


class DiscordMemberChangedEvent(BaseEvent):
    """A Discord guild member joined, left, or had their roles changed.

    Published by: discord-service straight from the gateway event (no DB
    transaction to join, so no outbox).
    Consumed by: stats-worker ``discord_member_changed``, which re-resolves the
    linked account's Boosty entitlement in every workspace bound to the guild.
    """

    event_type: str = Field(default="discord_member_changed", frozen=True)
    guild_id: str = Field(..., description="Discord guild id")
    discord_user_id: str = Field(..., description="Discord user id")
    reason: str = Field(..., description="role_update | member_join | member_remove")


class AnalyticsJobRequested(BaseEvent):
    """Unified analytics job dispatch — picked up by the analytics-worker.

    ``kind = 'compute'`` runs every selected v1 algorithm plus v2
    inference; ``kind = 'train_ml'`` (re)trains the v2 boosters and is
    superuser-only at the HTTP layer.
    """

    event_type: str = Field(default="analytics_job_requested", frozen=True)
    job_id: int = Field(..., description="analytics.job.id of the persisted request")


class FetchRankEvent(BaseEvent):
    """Event to fetch one battle tag's competitive rank from OverFast.

    Published by: stats-service scheduler (``source="scheduled"``) and the
    registration hook (``source="registration"``, via the priority queue).
    Consumed by: stats-service worker.
    """

    event_type: str = Field(default="fetch_rank", frozen=True)
    social_account_id: int = Field(..., description="players.social_account.id (battlenet) to fetch")
    battle_tag: str = Field(..., description="Full battle tag 'Name#1234'")
    source: Literal["scheduled", "registration", "manual"] = Field(
        default="scheduled", description="What triggered this fetch"
    )
    registration_id: int | None = Field(default=None, description="Registration that triggered it")
    tournament_id: int | None = Field(default=None, description="Tournament context, when applicable")


class AchievementEvaluateEvent(BaseEvent):
    """Event for triggering achievement evaluation after parsing.

    Published by: stats-service (after match/tournament processing, and when a
    manual/rule_version_bump run for an unverified workspace is deferred)
    Consumed by: stats-service (achievement engine)
    """

    event_type: str = Field(default="achievement_evaluate", frozen=True)
    workspace_id: int = Field(..., description="Workspace to evaluate achievements for")
    tournament_id: int | None = Field(
        default=None,
        description="Tournament that was just processed; None for a workspace-wide deferred run",
    )
    changed_tables: list[str] = Field(
        ...,
        description="DB tables that changed (e.g. ['stats.fact', 'encounter.encounter'])",
    )
    # Deferred-queue only: the run row already exists (status ``queued``), so the
    # consumer resumes it instead of opening a second audit row, and the slice
    # the caller asked for has to survive the round trip.
    run_id: str | None = Field(default=None, description="Existing queued EvaluationRun to resume")
    match_id: int | None = Field(default=None, description="Restrict evaluation to this match")
    rule_ids: list[int] | None = Field(default=None, description="Restrict evaluation to these rule ids")
