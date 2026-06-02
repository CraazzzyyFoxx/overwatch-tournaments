from pydantic import RedisDsn

from shared.core.config import BaseServiceSettings


class AppConfig(BaseServiceSettings):
    project_name: str = "Anak Tournaments"
    debug: bool = False
    project_url: str
    battle_tag_regex: str = r"([\w0-9]{2,12}#[0-9]{4,})"
    port: int = 8002

    redis_url: RedisDsn

    # OverFast API (self-hosted instance) — base URL for Overwatch stats/metadata.
    # Operational rank-collection params (interval, scope, rate limit, mapping)
    # live in the `Settings` table, not here.
    overfast_base_url: str = "https://overfast.craazzzyyfoxx.me"
    overfast_timeout: float = 15.0
    overfast_max_retries: int = 3
    # FastStream prefetch for the rank-fetch worker (keep low to protect OverFast).
    rank_fetch_worker_prefetch: int = 3

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
