"""Date-range resolution for rank-history reads.

Extracted verbatim from the former ``src/routes/rank_history.py`` HTTP route so the
typed-RPC handlers (``src/rpc/rank.py``) can reuse it after the FastAPI face was
removed. Behaviour is byte-identical: per-granularity defaults plus a max-range
guard for hourly/raw that raises ``HTTPException(422)``.

``HTTPException`` here is ``fastapi.HTTPException`` on purpose: the parser RPC
envelope (``src/rpc/_common.py``) maps ``fastapi.HTTPException`` status codes onto
the ``{ok,data,error}`` envelope, and a Starlette base-class instance would not be
caught by that ``except`` clause (it is a strict subclass), silently degrading the
422 into a generic 500. The rest of the ``src/services`` layer raises the same type.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from shared.core.errors import BaseAPIException as HTTPException

Granularity = Literal["raw", "daily", "hourly"]


def _resolve_date_range(
    granularity: Granularity,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime, datetime]:
    """Apply per-granularity defaults and enforce max range for hourly/raw."""
    now = datetime.now(tz=UTC)
    resolved_to = date_to or now
    default_days = 7 if granularity == "daily" else 3
    max_days = None if granularity == "daily" else 7
    resolved_from = date_from or (resolved_to - timedelta(days=default_days))
    if max_days is not None and (resolved_to - resolved_from).total_seconds() > max_days * 86400:
        raise HTTPException(
            status_code=422,
            detail=f"Date range for '{granularity}' granularity must not exceed {max_days} days.",
        )
    return resolved_from, resolved_to
