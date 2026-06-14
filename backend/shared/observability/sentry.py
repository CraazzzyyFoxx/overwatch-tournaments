"""Shared Sentry initialization helpers."""

from __future__ import annotations

import logging
from typing import Any

import sentry_sdk
from loguru import logger
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration


def _resolve_level(level: str | int) -> int:
    """Map a level name (e.g. ``"INFO"``) to its numeric logging level."""
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


def setup_sentry(
    *,
    dsn: str | None,
    environment: str,
    traces_sample_rate: float,
    profiles_sample_rate: float,
    service_name: str | None = None,
    release: str | None = None,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
    proxy_headers: dict[str, str] | None = None,
    enable_logs: bool = True,
    logs_level: str | int = "INFO",
    enable_metrics: bool = True,
) -> bool:
    """Initialize Sentry with tracing, structured logs, and metrics.

    When ``service_name`` is provided, a ``service`` tag is set on the global
    scope so that every event from this process is attributed to the service
    even though all backend processes share a single DSN.

    Observability surfaces wired here:

    - **Tracing** — ``traces_sample_rate`` plus the auto-enabled
      FastAPI/SQLAlchemy/Redis integrations. ``AsyncioIntegration`` is added
      explicitly so spans and errors from tasks spawned in the FastStream
      workers keep their context (it does not auto-enable).
    - **Logs** — when ``enable_logs`` is set, loguru records are forwarded to
      Sentry Logs at ``logs_level`` via :class:`LoguruIntegration`. Errors
      still become events (ERROR) and INFO records still become breadcrumbs.
    - **Metrics** — ``enable_metrics`` powers the experimental trace-metrics
      API exposed through :mod:`shared.observability.metrics`.
    """
    if not dsn:
        return False

    init_kwargs: dict[str, Any] = {
        "dsn": dsn,
        "environment": environment,
        "traces_sample_rate": traces_sample_rate,
        "profiles_sample_rate": profiles_sample_rate,
        "enable_logs": enable_logs,
        "enable_metrics": enable_metrics,
        # FastAPI/Starlette/SQLAlchemy/Redis auto-enable; Asyncio does not, and
        # the explicit Loguru integration lets us control the Sentry-logs level.
        "integrations": [
            AsyncioIntegration(),
            LoguruIntegration(sentry_logs_level=_resolve_level(logs_level)),
        ],
    }
    if release:
        init_kwargs["release"] = release
    if http_proxy:
        init_kwargs["http_proxy"] = http_proxy
    if https_proxy:
        init_kwargs["https_proxy"] = https_proxy
    if proxy_headers:
        init_kwargs["proxy_headers"] = proxy_headers

    sentry_sdk.init(**init_kwargs)

    if service_name:
        # Global scope tags apply to all events, including those raised in
        # background tasks/workers that run outside a request scope.
        sentry_sdk.get_global_scope().set_tag("service", service_name)

    logger.info(
        f"Sentry initialized (service={service_name}, sampling={traces_sample_rate}, "
        f"logs={enable_logs}, metrics={enable_metrics}, "
        f"http_proxy={http_proxy}, https_proxy={https_proxy})"
    )
    return True
