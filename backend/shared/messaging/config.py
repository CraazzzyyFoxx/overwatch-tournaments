"""RabbitMQ queue and exchange configurations with dead letter support."""

from functools import cache

from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue

# Dead Letter Exchange (DLX)
# All failed messages from any queue will be routed here
DLX_EXCHANGE = RabbitExchange(
    "dlx",
    type=ExchangeType.DIRECT,
    durable=True,
)

# ============================================================================
# Discord Commands Queue
# ============================================================================

DISCORD_COMMANDS_QUEUE = RabbitQueue(
    "discord_commands",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "discord_commands.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

DISCORD_COMMANDS_DLQ = RabbitQueue(
    "discord_commands.dlq",
    durable=True,
)

# ============================================================================
# Discord Member Roles Queue (RPC)
# ============================================================================

DISCORD_MEMBER_ROLES_QUEUE = RabbitQueue(
    "discord_member_roles",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "discord_member_roles.dlq",
        "x-message-ttl": 60000,  # 1 minute
    },
)

DISCORD_MEMBER_ROLES_DLQ = RabbitQueue(
    "discord_member_roles.dlq",
    durable=True,
)
# ============================================================================
# Discord Guild Entities Queues (RPC)
# ============================================================================

DISCORD_GUILD_ROLES_QUEUE = RabbitQueue(
    "discord_guild_roles",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "discord_guild_roles.dlq",
        "x-message-ttl": 60000,  # 1 minute
    },
)

DISCORD_GUILD_ROLES_DLQ = RabbitQueue(
    "discord_guild_roles.dlq",
    durable=True,
)

DISCORD_GUILD_CHANNELS_QUEUE = RabbitQueue(
    "discord_guild_channels",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "discord_guild_channels.dlq",
        "x-message-ttl": 60000,  # 1 minute
    },
)

DISCORD_GUILD_CHANNELS_DLQ = RabbitQueue(
    "discord_guild_channels.dlq",
    durable=True,
)

DISCORD_GUILD_INFO_QUEUE = RabbitQueue(
    "discord_guild_info",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "discord_guild_info.dlq",
        "x-message-ttl": 60000,  # 1 minute
    },
)

DISCORD_GUILD_INFO_DLQ = RabbitQueue(
    "discord_guild_info.dlq",
    durable=True,
)

DISCORD_VOICE_MOVE_QUEUE = RabbitQueue(
    "discord_voice_move",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "discord_voice_move.dlq",
        "x-message-ttl": 60000,  # 1 minute
    },
)

DISCORD_VOICE_MOVE_DLQ = RabbitQueue(
    "discord_voice_move.dlq",
    durable=True,
)

# ============================================================================
# Ingest queues (one per discipline)
# ============================================================================
# `stats.ingest.<discipline code>` carries ProcessIngestJobEvent for that discipline's jobs; a stats worker consumes
# only the disciplines it selected (STATS_DISCIPLINES). Every producer (outbox, reaper, retry, tournament fanout) names
# the queue through ingest_queue(job.discipline).

INGEST_QUEUE_PREFIX = "stats.ingest."


@cache
def ingest_queue(discipline: str) -> RabbitQueue:
    return RabbitQueue(
        f"{INGEST_QUEUE_PREFIX}{discipline}",
        durable=True,
        arguments={
            "x-dead-letter-exchange": "dlx",
            "x-dead-letter-routing-key": f"{INGEST_QUEUE_PREFIX}{discipline}.dlq",
            "x-message-ttl": 300000,  # 5 minutes
        },
    )


@cache
def ingest_dlq(discipline: str) -> RabbitQueue:
    return RabbitQueue(f"{INGEST_QUEUE_PREFIX}{discipline}.dlq", durable=True)


# Replay requests (a tournament-wide reparse of DONE jobs, carrying the revision seen at selection) get their own queue
# WITHOUT a message TTL: a DONE job is not recoverable by the stall reaper, so an expiring request would silently drop
# the reparse. Only a worker selecting the discipline declares and consumes it; refused/poison deliveries go to its DLQ.
@cache
def ingest_replay_queue(discipline: str) -> RabbitQueue:
    return RabbitQueue(
        f"{INGEST_QUEUE_PREFIX}{discipline}.replay",
        durable=True,
        arguments={
            "x-dead-letter-exchange": "dlx",
            "x-dead-letter-routing-key": f"{INGEST_QUEUE_PREFIX}{discipline}.replay.dlq",
        },
    )


@cache
def ingest_replay_dlq(discipline: str) -> RabbitQueue:
    return RabbitQueue(f"{INGEST_QUEUE_PREFIX}{discipline}.replay.dlq", durable=True)


# ============================================================================
# Upload Match Log Queue (discord bot -> stats worker)
# ============================================================================
# Carries the raw log bytes (base64) so the bot never calls stats-service over HTTP.
# The worker stores the file + record, then publishes a ProcessIngestJobEvent.

UPLOAD_MATCH_LOG_QUEUE = RabbitQueue(
    "upload_match_log",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "upload_match_log.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

UPLOAD_MATCH_LOG_DLQ = RabbitQueue(
    "upload_match_log.dlq",
    durable=True,
)

# ============================================================================
# Match Log Result (stats worker -> discord)
# ============================================================================
# One durable work queue: the result names the Discord message it answers
# (``channel_id``/``message_id``), so any replica can react on it -- there is no
# in-process waiter to find.

MATCH_LOG_RESULT_QUEUE = RabbitQueue(
    "match_log_result",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "match_log_result.dlq",
        "x-message-ttl": 300000,  # 5 minutes: past that the uploader has moved on
    },
)

MATCH_LOG_RESULT_DLQ = RabbitQueue(
    "match_log_result.dlq",
    durable=True,
)

# ============================================================================
# Process Tournament Logs Queue
# ============================================================================

PROCESS_TOURNAMENT_LOGS_QUEUE = RabbitQueue(
    "process_tournament_logs",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "process_tournament_logs.dlq",
        "x-message-ttl": 600000,  # 10 minutes (longer for bulk processing)
    },
)

PROCESS_TOURNAMENT_LOGS_DLQ = RabbitQueue(
    "process_tournament_logs.dlq",
    durable=True,
)

# ============================================================================
# Balancer Jobs Queue
# ============================================================================

BALANCER_JOBS_QUEUE = RabbitQueue(
    "balancer_jobs",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "balancer_jobs.dlq",
        "x-message-ttl": 900000,  # 15 minutes
    },
)

BALANCER_JOBS_DLQ = RabbitQueue(
    "balancer_jobs.dlq",
    durable=True,
)

# ============================================================================
# Tournament computation jobs
# ============================================================================

TOURNAMENT_COMPUTE_EXCHANGE = RabbitExchange(
    "tournament.compute",
    type=ExchangeType.TOPIC,
    durable=True,
)

TOURNAMENT_BRACKET_JOBS_QUEUE = RabbitQueue(
    "tournament_bracket_jobs",
    durable=True,
    routing_key="tournament.compute.bracket",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_bracket_jobs.dlq",
    },
)

TOURNAMENT_BRACKET_JOBS_DLQ = RabbitQueue(
    "tournament_bracket_jobs.dlq",
    durable=True,
)

TOURNAMENT_STANDINGS_JOBS_QUEUE = RabbitQueue(
    "tournament_standings_jobs",
    durable=True,
    routing_key="tournament.compute.standings",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_standings_jobs.dlq",
    },
)

TOURNAMENT_STANDINGS_JOBS_DLQ = RabbitQueue(
    "tournament_standings_jobs.dlq",
    durable=True,
)

DIVISION_GRID_IMPORT_JOBS_QUEUE = RabbitQueue(
    "division_grid_import_jobs",
    durable=True,
    routing_key="tournament.compute.division-grid-import",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "division_grid_import_jobs.dlq",
    },
)

DIVISION_GRID_IMPORT_JOBS_DLQ = RabbitQueue(
    "division_grid_import_jobs.dlq",
    durable=True,
)

# Cache invalidation, cross-service. One topic exchange, one queue per service
# that owns a cache, routing key `cache.invalidated.<scope_kind>.<scope_id>`.
# The payload names the stale RESOURCES, so a consumer maps them onto its own
# keys instead of re-deriving intent from a shared "reason" enum.
CACHE_INVALIDATION_EXCHANGE = RabbitExchange(
    "cache.invalidation",
    type=ExchangeType.TOPIC,
    durable=True,
)

CACHE_INVALIDATION_TOURNAMENT_QUEUE = RabbitQueue(
    "cache_invalidation_tournament_service",
    durable=True,
    routing_key="cache.invalidated.#",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "cache_invalidation_tournament_service.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

CACHE_INVALIDATION_TOURNAMENT_DLQ = RabbitQueue(
    "cache_invalidation_tournament_service.dlq",
    durable=True,
)

# stats-service owns the public read caches (statistics, /users/*, achievements) and the hero-stats materialized view.
CACHE_INVALIDATION_STATS_QUEUE = RabbitQueue(
    "cache_invalidation_stats_service",
    durable=True,
    routing_key="cache.invalidated.#",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "cache_invalidation_stats_service.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

CACHE_INVALIDATION_STATS_DLQ = RabbitQueue(
    "cache_invalidation_stats_service.dlq",
    durable=True,
)

TOURNAMENT_EVENTS_EXCHANGE = RabbitExchange(
    "tournament.events",
    type=ExchangeType.TOPIC,
    durable=True,
)

TOURNAMENT_ENCOUNTER_COMPLETED_QUEUE = RabbitQueue(
    "tournament_encounter_completed",
    durable=True,
    routing_key="tournament.encounter.completed",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_encounter_completed.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

TOURNAMENT_ENCOUNTER_COMPLETED_DLQ = RabbitQueue(
    "tournament_encounter_completed.dlq",
    durable=True,
)

TOURNAMENT_REGISTRATION_APPROVED_QUEUE = RabbitQueue(
    "tournament_registration_approved",
    durable=True,
    routing_key="tournament.registration.approved",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_registration_approved.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

TOURNAMENT_REGISTRATION_APPROVED_DLQ = RabbitQueue(
    "tournament_registration_approved.dlq",
    durable=True,
)

TOURNAMENT_REGISTRATION_RANK_CHECK_QUEUE = RabbitQueue(
    "tournament_registration_rank_check",
    durable=True,
    routing_key="tournament.registration.rank_check_requested",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_registration_rank_check.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

TOURNAMENT_REGISTRATION_RANK_CHECK_DLQ = RabbitQueue(
    "tournament_registration_rank_check.dlq",
    durable=True,
)

# Routing key on ``tournament.events`` that more than one binding names (the
# bot's per-replica channel-registry queue binds it too); the rest are spelled
# at their single producer/consumer pair.
TOURNAMENT_STATE_CHANGED_ROUTING_KEY = "tournament.state.changed"

# Owner: analytics-worker. A ``completed`` tournament gets its compute job
# created from here instead of waiting for someone to press "recalculate".
TOURNAMENT_STATE_CHANGED_QUEUE = RabbitQueue(
    "tournament_state_changed",
    durable=True,
    routing_key=TOURNAMENT_STATE_CHANGED_ROUTING_KEY,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_state_changed.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

TOURNAMENT_STATE_CHANGED_DLQ = RabbitQueue(
    "tournament_state_changed.dlq",
    durable=True,
)

TOURNAMENT_STANDINGS_INVALIDATED_QUEUE = RabbitQueue(
    "tournament_standings_invalidated",
    durable=True,
    routing_key="tournament.standings.invalidated",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_standings_invalidated.dlq",
    },
)

TOURNAMENT_STANDINGS_INVALIDATED_DLQ = RabbitQueue(
    "tournament_standings_invalidated.dlq",
    durable=True,
)

# Owner: tournament-service. The confirmed-result push to Challonge, taken out
# of the confirming request: the request commits the result and this row, the
# consumer talks to Challonge with the queue's retry instead of a swallowed
# ``logger.error``.
TOURNAMENT_CHALLONGE_PUSH_QUEUE = RabbitQueue(
    "tournament_challonge_push",
    durable=True,
    routing_key="tournament.encounter.challonge_push_requested",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_challonge_push.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

TOURNAMENT_CHALLONGE_PUSH_DLQ = RabbitQueue(
    "tournament_challonge_push.dlq",
    durable=True,
)

# Owner: tournament-service. A mix match started with hero bans (balancer-service's Start match): its encounter's
# pick-ban room is opened by the room healer (``reconcile_encounter``), which is idempotent -- a redelivery opens
# nothing twice.
TOURNAMENT_PICK_BAN_ROOM_OPEN_QUEUE = RabbitQueue(
    "tournament_pick_ban_room_open",
    durable=True,
    routing_key="tournament.encounter.pick_ban_room_open_requested",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_pick_ban_room_open.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

TOURNAMENT_PICK_BAN_ROOM_OPEN_DLQ = RabbitQueue(
    "tournament_pick_ban_room_open.dlq",
    durable=True,
)

# ============================================================================
# Workspace membership changes (app-service -> identity-service)
# ============================================================================
# ``WorkspaceMemberChangedEvent`` through the outbox, straight onto the queue:
# identity drops the cached RBAC payload of the listed users.

WORKSPACE_MEMBER_CHANGED_QUEUE = RabbitQueue(
    "workspace_member_changed",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "workspace_member_changed.dlq",
        "x-message-ttl": 120000,  # 2 min; a drop that expires unread is covered by identity's startup RBAC flush
    },
)

WORKSPACE_MEMBER_CHANGED_DLQ = RabbitQueue(
    "workspace_member_changed.dlq",
    durable=True,
)

# ============================================================================
# Steam account created / re-pointed (any social-account writer -> identity-service)
# ============================================================================
# ``SteamAccountChangedEvent`` through the outbox, straight onto the queue:
# identity fetches the account's persona name into ``social_account.display_name``.
# Best effort: the daily refresh is the reconciliation for a lost message.

STEAM_ACCOUNT_CHANGED_QUEUE = RabbitQueue(
    "steam_account_changed",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "steam_account_changed.dlq",
        "x-message-ttl": 3600000,  # 1 hour
    },
)

STEAM_ACCOUNT_CHANGED_DLQ = RabbitQueue(
    "steam_account_changed.dlq",
    durable=True,
)

# ============================================================================
# Discord guild member changes (discord-service -> stats-worker)
# ============================================================================
# ``DiscordMemberChangedEvent``, published straight from the gateway event (the
# bot has no transaction to join). stats re-resolves the member's Boosty
# entitlement; the scheduled sweep stays as the slow reconciliation.

DISCORD_MEMBER_CHANGED_QUEUE = RabbitQueue(
    "discord_member_changed",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "discord_member_changed.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

DISCORD_MEMBER_CHANGED_DLQ = RabbitQueue(
    "discord_member_changed.dlq",
    durable=True,
)

# ============================================================================
# Match ingested (stats-service -> tournament match layer)
# ============================================================================
# One opaque evidence id/revision/placements payload per accepted observation
# revision. The tournament consumer decides whether it is official; the
# stats side never writes ``encounter.*``.

MATCH_INGESTED_EXCHANGE = RabbitExchange(
    "match.ingested",
    type=ExchangeType.TOPIC,
    durable=True,
)

MATCH_INGESTED_TOURNAMENT_QUEUE = RabbitQueue(
    "match.ingested.tournament",
    durable=True,
    routing_key="match.ingested",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "match.ingested.tournament.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

MATCH_INGESTED_TOURNAMENT_DLQ = RabbitQueue(
    "match.ingested.tournament.dlq",
    durable=True,
)

# ============================================================================
# Notification delivery (notify()/broadcast() outbox -> app-service)
# ============================================================================
# One queue, one owner: app-service's delivery consumer.

#: One personal row (DM).
NOTIFICATION_CREATED_ROUTING_KEY = "notification.created"
#: One workspace channel post.
NOTIFICATION_BROADCAST_ROUTING_KEY = "notification.broadcast"

NOTIFICATIONS_EXCHANGE = RabbitExchange(
    "notifications",
    type=ExchangeType.TOPIC,
    durable=True,
)

NOTIFICATION_DELIVERY_QUEUE = RabbitQueue(
    "notification_delivery",
    durable=True,
    routing_key="notification.*",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "notification_delivery.dlq",
    },
)

NOTIFICATION_DELIVERY_DLQ = RabbitQueue(
    "notification_delivery.dlq",
    durable=True,
)

# ============================================================================
# Pickup mix changes (balancer-service, tournament-service -> discord-service)
# ============================================================================
# ``PickupMixChangedEvent`` through the outbox, straight onto the queue (default
# exchange): the one consumer, the bot's mix projector, re-renders the mix's
# live Discord cards. No exchange until a second consumer needs the fact.

PICKUP_MIX_CHANGED_QUEUE = RabbitQueue(
    "pickup_mix_changed",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "pickup_mix_changed.dlq",
    },
)

PICKUP_MIX_CHANGED_DLQ = RabbitQueue(
    "pickup_mix_changed.dlq",
    durable=True,
)

# ============================================================================
# Analytics v2 ML Queues
# ============================================================================

ANALYTICS_JOB_QUEUE = RabbitQueue(
    "analytics_job",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "analytics_job.dlq",
        # Compute + training can both fit comfortably in 1 hour.
        "x-message-ttl": 3600000,
    },
)

ANALYTICS_JOB_DLQ = RabbitQueue(
    "analytics_job.dlq",
    durable=True,
)


# ============================================================================
# Achievement Evaluate Queue
# ============================================================================

ACHIEVEMENT_EVALUATE_QUEUE = RabbitQueue(
    "achievement_evaluate",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "achievement_evaluate.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

ACHIEVEMENT_EVALUATE_DLQ = RabbitQueue(
    "achievement_evaluate.dlq",
    durable=True,
)

# Recompute for an unverified workspace: same payload, its own queue so one
# low-prefetch consumer drains it without competing with parse-driven runs.
ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE = RabbitQueue(
    "achievement_evaluate.deferred",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "achievement_evaluate.deferred.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

ACHIEVEMENT_EVALUATE_DEFERRED_DLQ = RabbitQueue(
    "achievement_evaluate.deferred.dlq",
    durable=True,
)

# ============================================================================
# OverFast Rank Fetch Queues
# ============================================================================
# Two queues give registration-driven checks priority over the bulk sweep
# (RabbitMQ has no in-queue priority used elsewhere in this codebase). Both feed
# the same handler; the priority queue is consumed with higher prefetch.

RANK_FETCH_QUEUE = RabbitQueue(
    "rank_fetch",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "rank_fetch.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

RANK_FETCH_DLQ = RabbitQueue(
    "rank_fetch.dlq",
    durable=True,
)

RANK_FETCH_PRIORITY_QUEUE = RabbitQueue(
    "rank_fetch_priority",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "rank_fetch_priority.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

RANK_FETCH_PRIORITY_DLQ = RabbitQueue(
    "rank_fetch_priority.dlq",
    durable=True,
)

# ============================================================================
# Every exchange the outbox relay may publish to, by name
# ============================================================================
# The drain declares an exchange before its first publish to it. A publish to an
# exchange the broker does not know (``NOT_FOUND``) closes the channel and
# fails the rest of the batch, and any producing service (app-svc onto
# ``tournament.events``, say) can be the first process to publish on a fresh
# broker, before the consumer that declares the exchange has started.

EXCHANGES_BY_NAME: dict[str, RabbitExchange] = {
    exchange.name: exchange
    for exchange in (
        TOURNAMENT_COMPUTE_EXCHANGE,
        CACHE_INVALIDATION_EXCHANGE,
        TOURNAMENT_EVENTS_EXCHANGE,
        MATCH_INGESTED_EXCHANGE,
        NOTIFICATIONS_EXCHANGE,
    )
}
