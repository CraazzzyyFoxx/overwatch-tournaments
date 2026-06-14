"""Shared Sentry initialization helpers."""

from __future__ import annotations

from typing import Any

import sentry_sdk
from loguru import logger


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
) -> bool:
    """Initialize Sentry with optional proxy support.

    When ``service_name`` is provided, a ``service`` tag is set on the global
    scope so that every event from this process is attributed to the service
    even though all services share a single DSN.
    """
    if not dsn:
        return False

    init_kwargs: dict[str, Any] = {
        "dsn": dsn,
        "environment": environment,
        "traces_sample_rate": traces_sample_rate,
        "profiles_sample_rate": profiles_sample_rate,
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
        f"http_proxy={http_proxy}, https_proxy={https_proxy})"
    )
    return True
