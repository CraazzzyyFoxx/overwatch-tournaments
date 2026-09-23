"""Typed Pydantic models for RabbitMQ event messages.

These schemas provide type safety and validation for all inter-service messaging,
replacing untyped dict objects with validated Pydantic models.
"""

import time
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class BaseEvent(BaseModel):
    """Base class for all event messages."""

    event_type: str
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Idempotency key for this event")
    source_service: str | None = Field(default=None, description="Service that produced this event")
    schema_version: int = Field(default=1, description="Event schema version")
    timestamp: float = Field(default_factory=lambda: time.time(), description="UTC epoch timestamp")
    correlation_id: str | None = Field(default=None, description="Request correlation ID for tracing")


#: Discord's cap on the text of every TextDisplay in one Components V2 message.
DISCORD_CARD_TEXT_LIMIT = 4000


#: The actions discord-service answers itself (``src/interactions/actions.py``
#: says what each one calls). A literal rather than a string so a producer
#: cannot put a button on a card that the bot could only answer "unknown".
DiscordAction = Literal[
    "invite.accept",
    "invite.decline",
    "check_in",
    "registration.view",
    "notifications.menu",
    "notifications.mute",
]


class DiscordLinkButton(BaseModel):
    """A link button: Discord opens ``url`` itself, so the bot handles no interaction."""

    type: Literal["link"] = "link"
    label: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=512, pattern=r"^https?://")


class DiscordActionButton(BaseModel):
    """A button the bot answers itself, acting as whoever clicked it.

    It names *what* and *on which object*, never *who*: the clicker comes from
    the interaction Discord signs, and the bot acts only for an account that
    linked that Discord user. The target RPC then authorizes as it does for the
    site, so a button can never do more than its clicker could there.
    """

    type: Literal["action"] = "action"
    label: str = Field(min_length=1, max_length=80)
    action: DiscordAction
    #: The object acted on: an invite id, a tournament id, a preference group.
    target: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    style: Literal["primary", "secondary", "success", "danger"] = "secondary"


DiscordButton = Annotated[DiscordLinkButton | DiscordActionButton, Field(discriminator="type")]


class DiscordCard(BaseModel):
    """One Components V2 message: an accent-coloured container the bot lays out as

    ``text`` (with ``thumbnail_url`` beside it), a divider and ``details``, then
    one action row per entry of ``rows``. Both texts are Discord markdown,
    already escaped by the publisher. The layout lives in discord-service; this
    is only what fills it.
    """

    accent_color: int | None = Field(default=None, ge=0, le=0xFFFFFF)
    text: str = Field(min_length=1)
    details: str | None = None
    thumbnail_url: str | None = Field(default=None, max_length=2048, pattern=r"^https?://")
    # Discord's own caps: five buttons to a row, five rows to a message.
    rows: list[Annotated[list[DiscordButton], Field(min_length=1, max_length=5)]] = Field(
        default_factory=list, max_length=5
    )

    @model_validator(mode="after")
    def _fits_one_message(self) -> DiscordCard:
        # Discord answers 400 past this, which is a DLQ entry rather than a message.
        if len(self.text) + len(self.details or "") > DISCORD_CARD_TEXT_LIMIT:
            raise ValueError(f"card text exceeds Discord's {DISCORD_CARD_TEXT_LIMIT}-character limit")
        return self


class DiscordCommandEvent(BaseEvent):
    """Event for triggering Discord bot commands.

    Published by: parser-service (``process_all``), balancer-service (``post_message``),
    app-service notification delivery (``post_message``, ``send_dm``)
    Consumed by: discord-service

    Actions:
    - ``process_all``: re-scan every registered channel of a tournament.
    - ``process_message``: re-process one known message.
    - ``post_message``: send a message (content, embed and/or PNG attachment, or one card) to a channel.
    - ``send_dm``: send a direct message (content and/or embed, or one card) to one Discord user.
    """

    event_type: str = Field(default="discord_command", frozen=True)
    action: str = Field(
        ..., description="Action to perform: 'process_all', 'process_message', 'post_message' or 'send_dm'"
    )
    tournament_id: int | None = Field(default=None, description="Tournament ID to process (for 'process_all')")
    channel_id: int | None = Field(
        default=None, description="Discord channel ID (required for 'process_message' and 'post_message')"
    )
    message_id: int | None = Field(default=None, description="Discord message ID (required for 'process_message')")
    discord_user_id: int | None = Field(default=None, description="Discord user ID (required for 'send_dm')")
    content: str | None = Field(default=None, description="Plain message text (for 'post_message' and 'send_dm')")
    embed: dict[str, Any] | None = Field(
        default=None,
        description="Discord embed object, as accepted by discord.Embed.from_dict (for 'post_message' and 'send_dm')",
    )
    image_b64: str | None = Field(default=None, description="Base64 PNG sent as an attachment (for 'post_message')")
    image_filename: str = Field(default="lineup.png", description="Filename for ``image_b64``")
    card: DiscordCard | None = Field(
        default=None,
        description="Components V2 card (for 'post_message' and 'send_dm'); excludes content, embed and image_b64",
    )
    # Defaults to True so the balancer's existing mix posts keep their behaviour;
    # notifications carry user-written team/tournament names and pass False, so
    # an ``@everyone`` in a team name pings nobody.
    allow_mentions: bool = Field(default=True, description="False = the bot sends with AllowedMentions.none()")

    def model_post_init(self, __context) -> None:
        """Validate that required fields are present for specific actions."""
        if self.action == "process_all":
            if self.tournament_id is None:
                raise ValueError("tournament_id is required for action='process_all'")
        elif self.action == "process_message":
            if self.channel_id is None or self.message_id is None:
                raise ValueError("channel_id and message_id are required for action='process_message'")
        elif self.action == "post_message":
            if self.channel_id is None:
                raise ValueError("channel_id is required for action='post_message'")
            if self.content is None and self.embed is None and self.image_b64 is None and self.card is None:
                raise ValueError("content, embed, image_b64 or card is required for action='post_message'")
        elif self.action == "send_dm":
            if self.discord_user_id is None:
                raise ValueError("discord_user_id is required for action='send_dm'")
            if self.content is None and self.embed is None and self.card is None:
                raise ValueError("content, embed or card is required for action='send_dm'")
        # A Components V2 message carries no content or embeds: Discord refuses the mix.
        if self.card is not None and (self.content is not None or self.embed is not None or self.image_b64 is not None):
            raise ValueError("card cannot be combined with content, embed or image_b64")


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
    battle_tag: str | None = Field(default=None, description="Approved registration battle tag")


class RegistrationRejectedEvent(BaseEvent):
    """Domain event emitted when a tournament registration is rejected."""

    event_type: str = Field(default="registration_rejected", frozen=True)
    tournament_id: int = Field(..., description="Tournament ID")
    workspace_id: int = Field(..., description="Workspace ID")
    registration_id: int = Field(..., description="Registration ID")
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
    social_account_id: int = Field(..., description="players.social_account.id (battlenet) to fetch")
    battle_tag: str = Field(..., description="Full battle tag 'Name#1234'")
    source: Literal["scheduled", "registration", "manual"] = Field(
        default="scheduled", description="What triggered this fetch"
    )
    registration_id: int | None = Field(default=None, description="Registration that triggered it")
    tournament_id: int | None = Field(default=None, description="Tournament context, when applicable")


class AchievementEvaluateEvent(BaseEvent):
    """Event for triggering achievement evaluation after parsing.

    Published by: parser-service (after match/tournament processing, and when a
    manual/rule_version_bump run for an unverified workspace is deferred)
    Consumed by: parser-service (achievement engine)
    """

    event_type: str = Field(default="achievement_evaluate", frozen=True)
    workspace_id: int = Field(..., description="Workspace to evaluate achievements for")
    tournament_id: int | None = Field(
        default=None,
        description="Tournament that was just processed; None for a workspace-wide deferred run",
    )
    changed_tables: list[str] = Field(
        ...,
        description="DB tables that changed (e.g. ['matches.statistics', 'tournament.encounter'])",
    )
    # Deferred-queue only: the run row already exists (status ``queued``), so the
    # consumer resumes it instead of opening a second audit row, and the slice
    # the caller asked for has to survive the round trip.
    run_id: str | None = Field(default=None, description="Existing queued EvaluationRun to resume")
    match_id: int | None = Field(default=None, description="Restrict evaluation to this match")
    rule_ids: list[int] | None = Field(default=None, description="Restrict evaluation to these rule ids")
