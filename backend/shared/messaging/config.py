"""RabbitMQ queue and exchange configurations with dead letter support.

All queues are configured with:
- Dead letter exchange for failed messages
- 5-minute message TTL
- Durable persistence
"""

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
# Tournament Recalculation Events
# ============================================================================

TOURNAMENT_RECALC_EXCHANGE = RabbitExchange(
    "tournament.recalc",
    type=ExchangeType.TOPIC,
    durable=True,
)

TOURNAMENT_RECALC_QUEUE = RabbitQueue(
    "tournament_recalc",
    durable=True,
    routing_key="tournament.recalc.*",
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "tournament_recalc.dlq",
        "x-message-ttl": 900000,  # 15 minutes
    },
)

TOURNAMENT_RECALC_DLQ = RabbitQueue(
    "tournament_recalc.dlq",
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

# ============================================================================
# Swiss Next Round Queue
# ============================================================================

SWISS_NEXT_ROUND_QUEUE = RabbitQueue(
    "swiss_next_round",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "dlx",
        "x-dead-letter-routing-key": "swiss_next_round.dlq",
        "x-message-ttl": 300000,  # 5 minutes
    },
)

SWISS_NEXT_ROUND_DLQ = RabbitQueue(
    "swiss_next_round.dlq",
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
