from __future__ import annotations

import time
from typing import Any

TERMINAL_STATUSES = {"succeeded", "failed"}
ACTIVE_JOB_STATUSES = TERMINAL_STATUSES | {"queued", "running"}
PROGRESS_EVENT_INTERVAL_SECONDS = 0.5
PROGRESS_PERCENT_STEP = 5.0


def extract_progress_percent(progress: Any) -> float | None:
    if not isinstance(progress, dict):
        return None
    percent = progress.get("percent")
    if percent is not None:
        try:
            return float(percent)
        except (TypeError, ValueError):
            return None
    current = progress.get("current")
    total = progress.get("total")
    if current is None or total in (None, 0):
        return None
    try:
        return (float(current) / float(total)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class ProgressEventThrottler:
    def __init__(
        self,
        *,
        job_store,
        job_id: str,
        meta: dict[str, Any],
        clock=None,
    ) -> None:
        self._job_store = job_store
        self._job_id = job_id
        self._meta = meta
        self._clock = clock or time.monotonic
        self._last_emitted_stage: str | None = None
        self._last_emitted_percent: float | None = None
        self._last_emitted_at: float | None = None
        self._pending_update: dict[str, Any] | None = None
        self.emitted_count = 0

    async def handle(self, update: dict[str, Any]) -> None:
        now = self._clock()
        if self._should_emit(update, now):
            await self._emit(update, now)
            return
        self._pending_update = update

    async def flush_pending(self) -> None:
        if self._pending_update is None:
            return
        pending_update = self._pending_update
        self._pending_update = None
        await self._emit(pending_update, self._clock())

    def _should_emit(self, update: dict[str, Any], now: float) -> bool:
        status_value = str(update.get("status", "running"))
        stage_value = str(update.get("stage", "running"))
        percent = extract_progress_percent(update.get("progress"))

        if status_value in TERMINAL_STATUSES:
            return True
        if self._last_emitted_at is None:
            return True
        if stage_value != self._last_emitted_stage:
            return True
        if (
            percent is not None
            and self._last_emitted_percent is not None
            and percent - self._last_emitted_percent >= PROGRESS_PERCENT_STEP
        ):
            return True
        return now - self._last_emitted_at >= PROGRESS_EVENT_INTERVAL_SECONDS

    async def _emit(self, update: dict[str, Any], now: float) -> None:
        status_value = str(update.get("status", "running"))
        status_name = status_value if status_value in ACTIVE_JOB_STATUSES else "running"
        stage_value = str(update.get("stage", "running"))
        progress = update.get("progress")

        await self._job_store.append_event(
            self._job_id,
            status=status_name,
            stage=stage_value,
            message=str(update.get("message", "")),
            level=str(update.get("level", "info")),
            progress=progress if isinstance(progress, dict) else None,
            update_meta=True,
            meta=self._meta,
        )

        self.emitted_count += 1
        self._last_emitted_at = now
        self._last_emitted_stage = stage_value
        self._last_emitted_percent = extract_progress_percent(progress)
