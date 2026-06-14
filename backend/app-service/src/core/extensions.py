from loguru import logger

from src.core import config
from shared.observability import setup_sentry


def configure_extensions() -> None:
    logger.info("Configuring extensions...")
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        environment=config.settings.environment,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        service_name="app-service",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
