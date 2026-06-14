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
        service_name="balancer-service",
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
