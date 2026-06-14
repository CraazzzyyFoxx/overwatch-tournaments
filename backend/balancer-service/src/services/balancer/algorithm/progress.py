from __future__ import annotations

import typing
from collections.abc import Callable

ProgressPayload = dict[str, typing.Any]
ProgressCallback = Callable[[ProgressPayload], None]


def emit_progress(
    progress_callback: ProgressCallback | None,
    *,
    status: str,
    stage: str,
    message: str,
    level: str = "info",
    progress: dict[str, int | float] | None = None,
) -> None:
    """Emit progress/log updates to an optional callback."""
    if progress_callback is None:
        return

    payload: ProgressPayload = {
        "status": status,
        "stage": stage,
        "message": message,
        "level": level,
    }
    if progress is not None:
        payload["progress"] = progress

    progress_callback(payload)
