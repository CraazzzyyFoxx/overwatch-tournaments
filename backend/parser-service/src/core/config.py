from pydantic import RedisDsn

from shared.core.config import BaseServiceSettings


class AppConfig(BaseServiceSettings):
    project_name: str = "OWT"
    debug: bool = False
    project_url: str
    port: int = 8002

    # Match-log ingestion safety caps (defense-in-depth against oversized or
    # adversarial logs; see review MEDIUM: match-logs uploaded/parsed without a
    # size limit). Enforced before base64-decode and before building the parsing
    # DataFrame.
    max_match_log_bytes: int = 25 * 1024 * 1024
    max_match_log_lines: int = 500_000

    # Match-log stall recovery (src/services/match_logs/reaper.py). The
    # process_match_log queue TTLs messages after 5 minutes, so a record whose
    # event expired or whose worker died is only recoverable from the row.
    log_reaper_enabled: bool = True
    log_reaper_tick_seconds: int = 300
    # Must stay above the 5-minute queue TTL: inside that window a message can
    # still be waiting on a busy consumer, and requeueing would double-parse.
    log_reaper_pending_after_seconds: int = 900
    # A parse still running after this long has no live worker behind it.
    log_reaper_processing_after_seconds: int = 1800
    log_reaper_max_attempts: int = 5
    log_reaper_batch_size: int = 25

    redis_url: RedisDsn

    # OverFast API (self-hosted instance) — base URL for Overwatch stats/metadata.
    # Operational rank-collection params (interval, scope, rate limit, mapping)
    # live in the `Settings` table, not here.
    overfast_base_url: str = "https://overfast.craazzzyyfoxx.me"
    overfast_timeout: float = 15.0
    overfast_max_retries: int = 3
    # FastStream prefetch for the rank-fetch worker (keep low to protect OverFast).
    rank_fetch_worker_prefetch: int = 3

    # Subscription resolution credentials
    discord_token: str | None = None
    twitch_client_id: str | None = None

    # Challonge
    challonge_username: str
    challonge_api_key: str
    # RabbitMQ
    rabbitmq_url: str | None = None

    # RabbitMQ Management API (for queue depth monitoring)
    rabbitmq_management_url: str = "http://rabbitmq:15672"
    rabbitmq_management_user: str = "guest"
    rabbitmq_management_password: str = "guest"

    @property
    def broker_url(self):
        return self.rabbitmq_url


settings = AppConfig()
