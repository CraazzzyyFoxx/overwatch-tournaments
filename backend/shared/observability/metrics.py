"""Thin wrapper over Sentry's experimental trace-metrics API.

Operational metrics (request counts, latencies, queue depth) are collected via
Prometheus. These helpers are for *business/domain* metrics that benefit from
being correlated with Sentry traces — e.g. balancer job sizes, parser log
volumes, inference durations.

The underlying :mod:`sentry_sdk.metrics` API is flagged experimental and may
change between SDK versions, so all call sites should go through this module:
a future migration then touches one file instead of many.

Metrics are only emitted when Sentry was initialized with ``enable_metrics``
(the default in :func:`shared.observability.sentry.setup_sentry`); otherwise
the SDK treats these as cheap no-ops.
"""

from __future__ import annotations

from typing import Any

from sentry_sdk import metrics as _metrics


def count(
    name: str,
    value: float = 1.0,
    *,
    unit: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Increment a counter metric (e.g. number of jobs processed)."""
    _metrics.count(name, value, unit=unit, attributes=attributes)


def gauge(
    name: str,
    value: float,
    *,
    unit: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Record a point-in-time value (e.g. current queue depth)."""
    _metrics.gauge(name, value, unit=unit, attributes=attributes)


def distribution(
    name: str,
    value: float,
    *,
    unit: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Record a value whose distribution matters (e.g. job duration)."""
    _metrics.distribution(name, value, unit=unit, attributes=attributes)
