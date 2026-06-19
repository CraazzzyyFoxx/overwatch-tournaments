"""Typed Pydantic models for RabbitMQ event messages.

These schemas provide type safety and validation for all inter-service messaging,
replacing untyped dict objects with validated Pydantic models.
"""

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Base class for all event messages."""

    event_type: str
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Idempotency key for this event")
    source_service: str | None = Field(default=None, description="Service that produced this event")
    schema_version: int = Field(default=1, description="Event schema version")
    timestamp: float = Field(default_factory=lambda: time.time(), description="UTC epoch timestamp")
    correlation_id: str | None = Field(default=None, description="Request correlation ID for tracing")


class DiscordCommandEvent(BaseEvent):
    """Event for triggering Discord bot commands.

    Published by: parser-service
    Consumed by: discord-service
    """

    event_type: str = Field(default="discord_command", frozen=True)
    action: str = Field(..., description="Action to perform: 'process_all' or 'process_message'")
    tournament_id: int = Field(..., description="Tournament ID to process")
    channel_id: int | None = Field(default=None, description="Discord channel ID (required for 'process_message')")
    message_id: int | None = Field(default=None, description="Discord message ID (required for 'process_message')")

    def model_post_init(self, __context) -> None:
        """Validate that required fields are present for specific actions."""
        if self.action == "process_message":
            if self.channel_id is None or self.message_id is None:
                raise ValueError("channel_id and message_id are required for action='process_message'")


class ProcessMatchLogEvent(BaseEvent):
    """Event for processing a single match log file.

    Published by: parser-service
    Consumed by: parser-service (background worker)
    """

    event_type: str = Field(default="process_match_log", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    filename: str = Field(..., description="Match log filename to process")


class UploadMatchLogEvent(BaseEvent):
    """Event carrying a raw match-log file to be stored + queued for processing.

    Published by: discord-service (bot upload, replacing the former direct
    ``POST http://parser:8002/logs/{id}/upload`` HTTP call).
    Consumed by: parser-service worker, which stores the log to S3, upserts the
    LogProcessingRecord, then publishes a ``ProcessMatchLogEvent``.

    The file bytes ride in ``content_b64`` (base64). Keep logs reasonably sized:
    the message must fit RabbitMQ's frame/size limits.
    """

    event_type: str = Field(default="upload_match_log", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    filename: str = Field(..., description="Match log filename")
    content_b64: str = Field(..., description="Base64-encoded raw log file bytes")
    content_type: str | None = Field(default=None, description="Original Content-Type, if known")
    uploader_discord_name: str | None = Field(
        default=None, description="Discord username of the uploader, resolved to a Player on ingest"
    )


class MatchLogProcessedEvent(BaseEvent):
    """Result of processing a single match log, sent back to the uploader.

    Published by: parser-service (worker, after process_match_log finishes)
    Consumed by: discord-service (resolves the pending upload future)

    Broadcast over a fanout exchange so every discord-service replica receives a
    copy; the replica holding the matching pending future resolves it and the
    rest no-op. Replaces the former pg LISTEN/NOTIFY 'log_processed' channel,
    which pgBouncer transaction pooling silently breaks.
    """

    event_type: str = Field(default="match_log_processed", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    filename: str = Field(..., description="Processed match log filename")
    status: Literal["done", "failed"] = Field(..., description="Processing outcome")


class ProcessTournamentLogsEvent(BaseEvent):
    """Event for processing all logs for a tournament.

    Published by: parser-service
    Consumed by: parser-service (background worker)
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


TournamentChangedReason = Literal["bracket_changed", "results_changed", "structure_changed"]


class TournamentChangedEvent(BaseEvent):
    """Event emitted when tournament bracket-related reads become stale.

    Published by: parser-service worker and tournament-service flows
    Consumed by: app-service and tournament-service APIs for cache invalidation
    and realtime fan-out
    """

    event_type: str = Field(default="tournament_changed", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID that was recalculated")
    reason: TournamentChangedReason = Field(
        ...,
        description="Why bracket-related tournament views should refresh",
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
    auth_user_id: int | None = Field(default=None, description="Auth user ID when linked")
    user_id: int | None = Field(default=None, description="Player user ID when linked")
    battle_tag: str | None = Field(default=None, description="Approved registration battle tag")


class RegistrationRejectedEvent(BaseEvent):
    """Domain event emitted when a tournament registration is rejected."""

    event_type: str = Field(default="registration_rejected", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    workspace_id: int = Field(..., description="Workspace ID")
    registration_id: int = Field(..., description="Registration ID")
    auth_user_id: int | None = Field(default=None, description="Auth user ID when linked")
    user_id: int | None = Field(default=None, description="Player user ID when linked")
    battle_tag: str | None = Field(default=None, description="Rejected registration battle tag")


class TournamentStateChangedEvent(BaseEvent):
    """Domain event emitted when tournament lifecycle state changes."""

    event_type: str = Field(default="tournament_state_changed", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    workspace_id: int | None = Field(default=None, description="Workspace ID")
    old_status: str | None = Field(default=None, description="Previous tournament status")
    new_status: str = Field(..., description="New tournament status")


class AnalyticsJobRequested(BaseEvent):
    """Unified analytics job dispatch — picked up by the analytics-worker.

    Replaces the v1 ``Recalculate`` + v2 ``Train ML`` + v2 ``Run inference``
    triggers. ``kind = 'compute'`` runs every selected v1 algorithm plus v2
    inference; ``kind = 'train_ml'`` (re)trains the v2 boosters and is
    superuser-only at the HTTP layer.
    """

    event_type: str = Field(default="analytics_job_requested", frozen=True)
    job_id: int = Field(..., description="analytics.job.id of the persisted request")


class AnalyticsTrainRequest(BaseEvent):
    """Request to (re)train v2 ML models up to a cutoff tournament.

    Published by: analytics-service HTTP (`POST /v2/train`).
    Consumed by: analytics-service worker (`serve.py`).
    """

    event_type: str = Field(default="analytics_train_request", frozen=True)
    cutoff_tournament_id: int = Field(..., description="Train on tournaments <= this id")
    model_kinds: list[str] | None = Field(
        default=None,
        description="Subset of model kinds to train (default: all active kinds)",
    )
    workspace_id: int | None = Field(
        default=None,
        description="Optional workspace scope filter",
    )
    workspace_ids: list[int] | None = Field(
        default=None,
        description="Optional multi-workspace training scope. None means all workspaces.",
    )


class AnalyticsInferRequest(BaseEvent):
    """Request to run v2 ML inference for a single tournament.

    Published by: analytics-service HTTP (`POST /v2/infer`).
    Consumed by: analytics-service worker (`serve.py`).
    """

    event_type: str = Field(default="analytics_infer_request", frozen=True)
    tournament_id: int = Field(..., description="Tournament to infer for")
    model_kinds: list[str] | None = Field(
        default=None,
        description="Subset of model kinds to run (default: all active kinds)",
    )
    workspace_id: int | None = Field(
        default=None,
        description="Optional workspace scope filter",
    )


class FetchRankEvent(BaseEvent):
    """Event to fetch one battle tag's competitive rank from OverFast.

    Published by: parser-service scheduler (``source="scheduled"``) and the
    registration hook (``source="registration"``, via the priority queue).
    Consumed by: parser-service worker.
    """

    event_type: str = Field(default="fetch_rank", frozen=True)
    battle_tag_id: int = Field(..., description="players.battle_tag.id to fetch")
    battle_tag: str = Field(..., description="Full battle tag 'Name#1234'")
    source: Literal["scheduled", "registration", "manual"] = Field(
        default="scheduled", description="What triggered this fetch"
    )
    registration_id: int | None = Field(default=None, description="Registration that triggered it")
    tournament_id: int | None = Field(default=None, description="Tournament context, when applicable")


class AchievementEvaluateEvent(BaseEvent):
    """Event for triggering achievement evaluation after parsing.

    Published by: parser-service (after match/tournament processing)
    Consumed by: parser-service (achievement engine)
    """

    event_type: str = Field(default="achievement_evaluate", frozen=True)
    workspace_id: int = Field(..., description="Workspace to evaluate achievements for")
    tournament_id: int = Field(..., description="Tournament that was just processed")
    changed_tables: list[str] = Field(
        ...,
        description="DB tables that changed (e.g. ['matches.statistics', 'tournament.encounter'])",
    )
