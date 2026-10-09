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
    "mix.join",
    "mix.leave",
    "mix.roles",
    "mix.setup",
    "mix.seat_set",
    "voice.move",
    "voice.return",
    "voice.move_confirm",
    "voice.return_confirm",
]

#: An emoji by name, as ``shared.domain.discord_ui.EMOJI`` spells it (``tank``,
#: ``div_gold_3``); discord-service resolves it to the uploaded application emoji.
_EMOJI_NAME = r"^[a-z0-9_]{1,28}$"


class DiscordLinkButton(BaseModel):
    """A link button: Discord opens ``url`` itself, so the bot handles no interaction."""

    type: Literal["link"] = "link"
    label: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=512, pattern=r"^https?://")
    emoji: str | None = Field(default=None, pattern=_EMOJI_NAME)


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
    emoji: str | None = Field(default=None, pattern=_EMOJI_NAME)
    #: Shown greyed out: the card says the action exists but is not open now.
    disabled: bool = False


DiscordButton = Annotated[DiscordLinkButton | DiscordActionButton, Field(discriminator="type")]


class DiscordCard(BaseModel):
    """One Components V2 message: an accent-coloured container the bot lays out as

    ``text`` (with ``thumbnail_url`` beside it), a divider, ``details``,
    ``image_url`` as a full-width picture and the ``answers`` row, with one
    action row per entry of ``rows`` under the container rather than in it.
    ``answers`` holds the card's one-click answers, ``rows`` where to read more
    and how to stop hearing it.
    Both texts are Discord markdown, already escaped by the publisher, and may
    carry ``:owt_<name>:`` emoji shortcodes (``shared.domain.discord_ui``).
    The layout lives in discord-service; this is only what fills it.
    """

    accent_color: int | None = Field(default=None, ge=0, le=0xFFFFFF)
    text: str = Field(min_length=1)
    details: str | None = None
    thumbnail_url: str | None = Field(default=None, max_length=2048, pattern=r"^https?://")
    #: A picture the card is *about* (an encounter's OpenGraph image), not its
    #: icon: Discord shows it full width, fetching the URL itself.
    #: ``attachment://<image_filename>`` shows the PNG the command carries.
    image_url: str | None = Field(default=None, max_length=2048, pattern=r"^(https?|attachment)://")
    answers: list[DiscordButton] = Field(default_factory=list, max_length=5)
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

    @property
    def attachment_name(self) -> str | None:
        """The file the card shows from its own message, ``None`` for a URL or no picture."""
        prefix = "attachment://"
        return self.image_url[len(prefix) :] if self.image_url and self.image_url.startswith(prefix) else None


class DiscordCommandEvent(BaseEvent):
    """Event for triggering Discord bot commands.

    Published by: parser-service (``process_all``), balancer-service and
    app-service notification delivery (everything that sends, through
    ``shared.services.discord_messages``)
    Consumed by: discord-service

    Actions:
    - ``process_all``: re-scan every registered channel of a tournament.
    - ``process_message``: re-process one known message.
    - ``post_message``: post one card to a channel, with the PNG it shows when
      ``card.image_url`` is ``attachment://<image_filename>``.
    - ``send_dm``: send one card to one Discord user.
    - ``edit_message``: show the card the ``discord_message`` row now holds
      (``card_json``); the command carries no card of its own, and may carry
      the PNG the row's card now shows. Edits of one message arriving close
      together collapse into one read of the row.
    - ``delete_message``: delete a message the bot sent.

    Every message the platform sends is a ``discord_message`` row, and the four
    message actions name it by ``message_ref`` (its id): the bot records the
    Discord ids there once the message exists, and an edit or a delete is
    resolved from that row -- a publisher never handles a Discord message id.
    """

    event_type: str = Field(default="discord_command", frozen=True)
    action: Literal["process_all", "process_message", "post_message", "send_dm", "edit_message", "delete_message"]
    tournament_id: int | None = Field(default=None, description="Tournament ID to process (for 'process_all')")
    channel_id: int | None = Field(default=None, description="Discord channel ID (process_message, post_message)")
    message_id: int | None = Field(default=None, description="Discord message ID (process_message)")
    discord_user_id: int | None = Field(default=None, description="Discord user ID (required for 'send_dm')")
    #: ``discord_message.id`` -- the platform's own handle on the message.
    message_ref: int | None = Field(default=None, description="discord_message row (post/send/edit/delete)")
    image_b64: str | None = Field(default=None, description="Base64 PNG the card shows (post_message, edit_message)")
    image_filename: str = Field(default="lineup.png", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    card: DiscordCard | None = Field(default=None, description="Components V2 card (post_message, send_dm)")
    #: Who may be pinged. ``False`` pings nobody (notifications carry
    #: user-written names). ``True`` pings the users the card mentions -- never
    #: ``@everyone`` or a role, whatever the text says.
    allow_mentions: bool = Field(default=False, description="True = the card's user mentions ping")

    def model_post_init(self, __context) -> None:
        """Validate that required fields are present for specific actions."""
        if self.action == "process_all":
            if self.tournament_id is None:
                raise ValueError("tournament_id is required for action='process_all'")
        elif self.action == "process_message":
            if self.channel_id is None or self.message_id is None:
                raise ValueError("channel_id and message_id are required for action='process_message'")
        elif self.action == "post_message":
            if self.channel_id is None or self.card is None or self.message_ref is None:
                raise ValueError("channel_id, card and message_ref are required for action='post_message'")
        elif self.action == "send_dm":
            if self.discord_user_id is None or self.card is None or self.message_ref is None:
                raise ValueError("discord_user_id, card and message_ref are required for action='send_dm'")
        elif self.action == "edit_message":
            # The card is the row's: one carried here would be a second,
            # possibly older, copy that the bot would have to pick between.
            if self.message_ref is None or self.card is not None:
                raise ValueError("edit_message takes message_ref and no card")
        elif self.action == "delete_message":
            if self.message_ref is None:
                raise ValueError("message_ref is required for action='delete_message'")
        # The PNG and the card that shows it travel together or not at all:
        # Discord renders neither a gallery pointing at a missing file nor a
        # stray attachment beside a Components V2 layout.
        shown = self.card.attachment_name if self.card is not None else None
        if self.image_b64 is not None:
            if self.action not in ("post_message", "edit_message"):
                raise ValueError("image_b64 is only sent with action='post_message' or 'edit_message'")
            # An edit carries no card (it is the row's); the bot checks the
            # name against the row's card when it applies the edit.
            if self.action == "post_message" and shown != self.image_filename:
                raise ValueError("image_b64 needs a card whose image_url is attachment://<image_filename>")
        elif shown is not None:
            raise ValueError("card.image_url names an attachment the command does not carry")


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

    Published by: balancer-service ``emit_pickup_mix_changed`` (outbox, same transaction)
    Consumed by: balancer-service signup-card projector
    """

    event_type: str = Field(default="pickup_mix.changed", frozen=True)
    workspace_id: int = Field(..., description="Workspace whose mixes changed")
    custom_game_id: int | None = Field(default=None, description="The mix, or None for workspace-wide")
    change: str = Field(..., description="What changed (roster, member, rank, close...), diagnostic only")


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


class RegistrationRankCheckRequestedEvent(RegistrationApprovedEvent):
    """The registrant asked to re-check their profile from their own card.

    Same payload as the approval event, so parser-service runs the same rank check
    for it; a distinct type and routing key so it is never read as an approval.
    """

    event_type: str = Field(default="registration_rank_check_requested", frozen=True)


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
