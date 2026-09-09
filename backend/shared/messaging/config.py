"""RabbitMQ queue and exchange configurations with dead letter support."""

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

# ============================================================================
# Process Match Log Queue
# ============================================================================

PROCESS_MATCH_LOG_QUEUE = RabbitQueue(
    "process_match_log",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "process_match_log.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

PROCESS_MATCH_LOG_DLQ = RabbitQueue(
    "process_match_log.dlq",
    durable=True,
)

# ============================================================================
# Upload Match Log Queue (discord bot -> parser worker)
# ============================================================================
# Carries the raw log bytes (base64) so the bot no longer calls parser over HTTP.
# The worker stores the file + record, then publishes a ProcessMatchLogEvent.

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
# Match Log Result (parser worker -> discord)
# ============================================================================
# Fanout so every discord-service replica receives every result; the replica
# holding the pending upload future resolves it and the rest no-op. This mirrors
# the broadcast semantics of the pg LISTEN/NOTIFY channel it replaces, which
# pgBouncer transaction pooling breaks. Consumers bind their own exclusive,
# auto-deleted (server-named) queue to this exchange — no durable shared queue,
# which would round-robin results to the wrong replica.
MATCH_LOG_RESULT_EXCHANGE = RabbitExchange(
    "match_log.result",
    type=ExchangeType.FANOUT,
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
# Replaces the tournament.changed contour: the payload names the stale
# RESOURCES, so a consumer maps them onto its own keys instead of re-deriving
# intent from a shared "reason" enum.
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

CACHE_INVALIDATION_APP_QUEUE = RabbitQueue(
    "cache_invalidation_app_service",
    durable=True,
    routing_key="cache.invalidated.#",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "cache_invalidation_app_service.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

CACHE_INVALIDATION_APP_DLQ = RabbitQueue(
    "cache_invalidation_app_service.dlq",
    durable=True,
)

TOURNAMENT_CHANGED_EXCHANGE = RabbitExchange(
    "tournament.changed",
    type=ExchangeType.TOPIC,
    durable=True,
)

TOURNAMENT_CHANGED_TOURNAMENT_QUEUE = RabbitQueue(
    "tournament_changed_tournament_service",
    durable=True,
    routing_key="tournament.changed.*",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_changed_tournament_service.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

TOURNAMENT_CHANGED_TOURNAMENT_DLQ = RabbitQueue(
    "tournament_changed_tournament_service.dlq",
    durable=True,
)

TOURNAMENT_CHANGED_APP_QUEUE = RabbitQueue(
    "tournament_changed_app_service",
    durable=True,
    routing_key="tournament.changed.*",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_changed_app_service.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

TOURNAMENT_CHANGED_APP_DLQ = RabbitQueue(
    "tournament_changed_app_service.dlq",
    durable=True,
)

# Publishers provide an explicit topic routing key, so this queue argument is
# used only as the observable destination name by the shared publish helper.
TOURNAMENT_CHANGED_QUEUE = TOURNAMENT_CHANGED_TOURNAMENT_QUEUE
TOURNAMENT_CHANGED_DLQ = TOURNAMENT_CHANGED_TOURNAMENT_DLQ

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

TOURNAMENT_REGISTRATION_REJECTED_QUEUE = RabbitQueue(
    "tournament_registration_rejected",
    durable=True,
    routing_key="tournament.registration.rejected",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_registration_rejected.dlq",
        "x-message-ttl": 600000,  # 10 minutes
    },
)

TOURNAMENT_REGISTRATION_REJECTED_DLQ = RabbitQueue(
    "tournament_registration_rejected.dlq",
    durable=True,
)

TOURNAMENT_STATE_CHANGED_QUEUE = RabbitQueue(
    "tournament_state_changed",
    durable=True,
    routing_key="tournament.state.changed",
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


ANALYTICS_TRAIN_QUEUE = RabbitQueue(
    "analytics_train",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "analytics_train.dlq",
        # Training can take many minutes; bump TTL accordingly.
        "x-message-ttl": 3600000,  # 1 hour
    },
)

ANALYTICS_TRAIN_DLQ = RabbitQueue(
    "analytics_train.dlq",
    durable=True,
)

ANALYTICS_INFER_QUEUE = RabbitQueue(
    "analytics_infer",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "analytics_infer.dlq",
        "x-message-ttl": 1800000,  # 30 min
    },
)

ANALYTICS_INFER_DLQ = RabbitQueue(
    "analytics_infer.dlq",
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
