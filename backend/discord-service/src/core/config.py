from shared.core.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    # Discord Bot
    discord_token: str

    # Parser Service
    parser_url: str

    # Service-to-service auth
    service_client_id: str
    service_client_secret: str
    service_token_skew_seconds: int = 30

    # RabbitMQ (optional)
    rabbitmq_url: str | None = None

    # Logging overrides
    logs_celery_root_path: str = ""

    @property
    def broker_url(self) -> str | None:
        return self.rabbitmq_url


settings = Settings()
