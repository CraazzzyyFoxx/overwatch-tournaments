"""Unified structured logging for all microservices.

Uses Loguru for structured JSON logging in production and human-readable output in development.
"""

import logging
import sys
from pathlib import Path

from loguru import logger
from opentelemetry import trace

from .correlation import get_correlation_id


def _inject_observability_context(record: dict) -> None:
    span = trace.get_current_span()
    span_context = span.get_span_context()
    is_sampled = bool(span_context.is_valid and span_context.trace_flags.sampled)

    record["extra"].update(
        correlation_id=get_correlation_id(),
        trace_id=f"{span_context.trace_id:032x}" if span_context.is_valid else None,
        span_id=f"{span_context.span_id:016x}" if span_context.is_valid else None,
        trace_sampled=is_sampled,
    )


class InterceptHandler(logging.Handler):
    """Intercept standard logging and redirect to Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the logged message originated
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(
    service_name: str,
    log_level: str = "info",
    logs_root_path: str = "/logs",
    json_output: bool = True,
    rotation: str = "1 day",
    retention: str = "30 days",
    compression: str = "gz",
):
    """Setup Loguru with structured JSON or human-readable output.

    Args:
        service_name: Name of the service (included in all log records)
        log_level: Minimum log level (debug, info, warning, error, critical)
        logs_root_path: Directory for log files
        json_output: If True, output JSON for production; if False, colorized for dev
        rotation: Log rotation interval (e.g., "1 day", "500 MB")
        retention: How long to keep old logs (e.g., "30 days", "10")
        compression: Compression format for rotated logs ("gz", "zip", "bz2", "xz")

    Returns:
        Configured logger instance
    """
    # Remove default handler
    logger.remove()

    level = log_level.upper()
    level_no = logger.level(level).no
    # ``diagnose`` renders local variable values (identity payloads, tokens, URLs) into tracebacks: debug only.
    diagnose = level_no <= logging.DEBUG

    # Create logs directory if needed
    logs_dir = Path(logs_root_path)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Format for development (human-readable with colors)
    dev_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level> | "
        "{extra}"
    )

    # Add stderr handler (always human-readable for console)
    logger.add(
        sys.stderr,
        level=level,
        format=dev_format,
        colorize=True,
        backtrace=True,
        diagnose=diagnose,
    )

    # Add file handler
    log_file = logs_dir / f"{service_name}.log"
    if json_output:
        logger.add(
            log_file,
            level=level,
            serialize=True,  # Built-in Loguru JSON serialization writes record["extra"] fields
            rotation=rotation,
            retention=retention,
            compression=compression,
            backtrace=True,
            diagnose=diagnose,
        )
    else:
        logger.add(
            log_file,
            level=level,
            format=dev_format,
            rotation=rotation,
            retention=retention,
            compression=compression,
            backtrace=True,
            diagnose=diagnose,
        )

    # Bind service name to all logs and inject correlation_id on every record via patcher.
    # Loguru's serialize=True writes record["extra"] into the JSON output, so patching
    # extra["correlation_id"] here is the correct way to get it into every file log line.
    logger.configure(
        extra={"service": service_name, "correlation_id": None},
        patcher=_inject_observability_context,
    )

    # Intercept standard library logging at the configured level: level 0 made every library (aiormq per
    # AMQP frame) build and format DEBUG records only for the sinks to discard them.
    logging.basicConfig(handlers=[InterceptHandler()], level=level_no, force=True)
    # APScheduler logs "Running job"/"executed successfully" at INFO for every tick; its skips are WARNINGs.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # Intercept common libraries
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "sqlalchemy"]:
        logging.getLogger(logger_name).handlers = [InterceptHandler()]

    logger.info(f"✅ Logging initialized for {service_name} (level={level}, json={json_output})")

    return logger


def get_logger():
    """Get the Loguru logger instance."""
    return logger
