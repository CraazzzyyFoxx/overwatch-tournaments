import typing
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ("BaseServiceSettings",)


class BaseServiceSettings(BaseSettings):
    """Common settings shared across all microservices.

    Services extend this class and add their own specific fields::

        class Settings(BaseServiceSettings):
            redis_url: RedisDsn
            my_custom_field: str = "default"
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.prod"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Proxy (optional — supports http, socks5, shadowsocks via proxy sidecar)
    proxy_type: typing.Literal["http", "socks5", "shadowsocks"] | None = None
    proxy_ip: str | None = None
    proxy_port: int | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    # shadowsocks: proxy sidecar exposes a local SOCKS5 port
    proxy_ss_local_host: str = "proxy"
    proxy_ss_local_port: int = 1080
    proxy_http_host: str = "proxy"
    proxy_http_port: int = 8080

    # Application
    project_name: str = "Anak Service"
    version: str = "0.0.1"
    environment: typing.Literal["development", "production", "staging"] = "development"
    host: str = "localhost"
    port: int = 8000

    # Postgres
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str
    postgres_port: str | int

    # Auth/identity: services validate tokens through the gateway, which routes
    # to the headless identity-svc over RPC. (auth-service is decommissioned.)
    auth_service_url: str = "http://gateway:8080/api/auth"
    auth_service_timeout: float = 5.0
    auth_service_max_retries: int = 2

    # Database pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True
    db_pool_use_lifo: bool = True
    db_connect_timeout: float = 10.0
    db_statement_timeout: int = 30000  # milliseconds
    # Connect through pgBouncer (transaction pooling): disables asyncpg
    # prepared-statement caching, uses NullPool, and applies statement_timeout
    # per-transaction via SET LOCAL.
    db_pgbouncer: bool = False

    # Circuit Breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 30.0

    # CORS
    cors_origins: list[str] = []

    # Logging
    log_level: str = "info"
    logs_root_path: str = "/logs" if Path("/logs").exists() else str(Path.cwd() / "logs")
    json_logging: bool = True

    # S3 / MinIO (optional – only needed by services that use storage)
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_endpoint_url: str | None = None
    s3_bucket_name: str = "aqt"
    s3_public_url: str | None = None  # e.g. "https://minio.craazzzyyfoxx.me/aqt"

    # Observability
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.1
    sentry_http_proxy: str | None = None
    sentry_https_proxy: str | None = None
    sentry_enable_logs: bool = True
    sentry_logs_level: str = "INFO"
    sentry_enable_metrics: bool = True
    otlp_endpoint: str | None = None
    tracing_enabled: bool = False
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = 0.1
    worker_metrics_port: int | None = None

    @property
    def db_url_asyncpg(self) -> str:
        url = (
            f"{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return f"postgresql+asyncpg://{url}"

    @property
    def db_url(self) -> str:
        url = (
            f"{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return f"postgresql+psycopg://{url}"

    @property
    def proxy_url(self) -> str | None:
        """Build proxy URL based on proxy_type.

        - ``http``: ``http://user:pass@host:port``
        - ``socks5``: ``socks5://user:pass@host:port``
        - ``shadowsocks``: ``socks5://ss-local-host:ss-local-port``
          (shadowsocks client sidecar exposes a plain SOCKS5 interface)
        """
        if self.proxy_type is None:
            # Backwards compat: if legacy proxy_ip is set without proxy_type, assume http
            if self.proxy_ip:
                auth = ""
                if self.proxy_username and self.proxy_password:
                    auth = f"{self.proxy_username}:{self.proxy_password}@"
                return f"http://{auth}{self.proxy_ip}:{self.proxy_port}"
            return None

        if self.proxy_type == "shadowsocks":
            return f"socks5://{self.proxy_ss_local_host}:{self.proxy_ss_local_port}"

        # http or socks5
        if not self.proxy_ip:
            return None
        scheme = self.proxy_type  # "http" or "socks5"
        auth = ""
        if self.proxy_username and self.proxy_password:
            auth = f"{self.proxy_username}:{self.proxy_password}@"
        return f"{scheme}://{auth}{self.proxy_ip}:{self.proxy_port}"

    @property
    def proxy_http_url(self) -> str:
        return f"http://{self.proxy_http_host}:{self.proxy_http_port}"

    @property
    def sentry_http_proxy_url(self) -> str | None:
        if self.sentry_http_proxy:
            return self.sentry_http_proxy
        if self.proxy_type == "shadowsocks":
            return self.proxy_http_url
        return None

    @property
    def sentry_https_proxy_url(self) -> str | None:
        if self.sentry_https_proxy:
            return self.sentry_https_proxy
        return self.sentry_http_proxy_url
