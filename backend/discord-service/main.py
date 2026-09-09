"""Discord log-collection worker: process entrypoint.

See ``src/bot.py`` for the bot itself and ``README.md`` for the service's
responsibilities.
"""

from shared.observability import setup_logging, setup_tracing, start_worker_metrics_server
from shared.services.realtime import configure_realtime
from src.bot import LogCollectorBot
from src.core.config import settings
from src.core.db import async_engine

logger = setup_logging(
    service_name="discord-worker",
    log_level=settings.log_level,
    logs_root_path=settings.logs_root_path,
    json_output=settings.json_logging,
)


def main() -> None:
    try:
        logger.info("🚀 Starting Discord Log Collection Bot...")
        setup_tracing(
            service_name="discord-worker",
            otlp_endpoint=settings.otlp_endpoint,
            enabled=settings.tracing_enabled,
            sampler_name=settings.otel_traces_sampler,
            sampler_arg=settings.otel_traces_sampler_arg,
            environment=settings.environment,
            release=settings.sentry_release,
            engine=async_engine,
        )
        start_worker_metrics_server(settings.worker_metrics_port)
        # The Boosty re-sync resolves entitlements, which stages a
        # workspace.subscriptions invalidation; shared/services/realtime has no
        # settings of its own to find Redis with.
        configure_realtime(redis_url=str(settings.redis_url))

        bot = LogCollectorBot(settings)
        # `log_handler=None`: logging is already configured via `setup_logging`
        # above; discord.py's own default handler would double-configure the
        # root logger. Cleanup (RabbitMQ listener, gateway connection) runs
        # through `LogCollectorBot.close`, invoked automatically by `run()`.
        bot.run(settings.discord_token, log_handler=None)
    except KeyboardInterrupt:
        logger.info("⏸️ Shutting down bot...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        logger.info("👋 Bot stopped")


if __name__ == "__main__":
    main()
