from __future__ import annotations

import json
import time
import uuid
from typing import Any, Literal

import redis.asyncio as redis

from src.core.config import config
from src.core.metrics import record_balancer_redis_writes

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class BalancerJobStore:
    """Redis-backed storage for balancer jobs, events, and results."""

    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _meta_key(job_id: str) -> str:
        return f"balancer:job:{job_id}:meta"

    @staticmethod
    def _payload_key(job_id: str) -> str:
        return f"balancer:job:{job_id}:payload"

    @staticmethod
    def _result_key(job_id: str) -> str:
        return f"balancer:job:{job_id}:result"

    @staticmethod
    def _events_key(job_id: str) -> str:
        return f"balancer:job:{job_id}:events"

    @staticmethod
    def _event_sequence_key(job_id: str) -> str:
        return f"balancer:job:{job_id}:event_seq"

    @staticmethod
    def _api_key_active_jobs_key(api_key_id: int) -> str:
        return f"balancer:api_key:{api_key_id}:active_jobs"

    @staticmethod
    def _session_active_jobs_key(user_id: int) -> str:
        return f"balancer:user:{user_id}:active_jobs"

    async def _refresh_ttl(self, job_id: str) -> None:
        pipe = self._redis.pipeline()
        for key in (
            self._meta_key(job_id),
            self._payload_key(job_id),
            self._result_key(job_id),
            self._events_key(job_id),
            self._event_sequence_key(job_id),
        ):
            pipe.expire(key, self._ttl_seconds)
        await pipe.execute()
        record_balancer_redis_writes("refresh_ttl", 5)

    async def _save_meta(self, job_id: str, meta: dict[str, Any]) -> None:
        await self._redis.set(self._meta_key(job_id), json.dumps(meta), ex=self._ttl_seconds)
        record_balancer_redis_writes("save_meta", 1)

    async def _persist_event_and_meta(
        self,
        job_id: str,
        *,
        event: dict[str, Any],
        meta: dict[str, Any],
        result: dict[str, Any] | None = None,
        refresh_payload_ttl: bool = False,
    ) -> None:
        pipe = self._redis.pipeline()
        operation_count = 0

        pipe.rpush(self._events_key(job_id), json.dumps(event))
        operation_count += 1

        pipe.set(self._meta_key(job_id), json.dumps(meta), ex=self._ttl_seconds)
        operation_count += 1

        if result is not None:
            pipe.set(self._result_key(job_id), json.dumps(result), ex=self._ttl_seconds)
            operation_count += 1

        if refresh_payload_ttl:
            pipe.expire(self._payload_key(job_id), self._ttl_seconds)
            operation_count += 1

        pipe.expire(self._events_key(job_id), self._ttl_seconds)
        pipe.expire(self._event_sequence_key(job_id), self._ttl_seconds)
        operation_count += 2

        await pipe.execute()
        record_balancer_redis_writes("persist_event", operation_count)

    async def create_job(
        self,
        input_data: dict[str, Any],
        config_overrides: dict[str, Any] | None,
        *,
        job_id: str | None = None,
        workspace_id: int | None = None,
        tournament_id: int | None = None,
        created_by: int | None = None,
        credential_type: str = "access_token",
        api_key_id: int | None = None,
    ) -> str:
        job_id = job_id or uuid.uuid4().hex
        now = time.time()

        meta = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "progress": None,
            "error": None,
            "workspace_id": workspace_id,
            "tournament_id": tournament_id,
            "created_by": created_by,
            "credential_type": credential_type,
            "api_key_id": api_key_id,
            "events_count": 0,
        }
        payload = {
            "player_data": input_data,
            "config_overrides": config_overrides,
        }

        pipe = self._redis.pipeline()
        pipe.set(self._meta_key(job_id), json.dumps(meta), ex=self._ttl_seconds)
        pipe.set(self._payload_key(job_id), json.dumps(payload), ex=self._ttl_seconds)
        pipe.set(self._event_sequence_key(job_id), 0, ex=self._ttl_seconds)
        await pipe.execute()
        record_balancer_redis_writes("create_job", 3)

        await self.append_event(
            job_id,
            status="queued",
            stage="queued",
            level="info",
            message="Balancer job accepted and queued",
            update_meta=False,
            meta=meta,
        )
        return job_id

    async def get_job_meta(self, job_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._meta_key(job_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def get_job_payload(self, job_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._payload_key(job_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def get_job_result(self, job_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._result_key(job_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def append_event(
        self,
        job_id: str,
        *,
        status: JobStatus,
        stage: str,
        message: str,
        level: str = "info",
        progress: dict[str, Any] | None = None,
        update_meta: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta_snapshot = meta
        if meta_snapshot is None:
            meta_snapshot = await self.get_job_meta(job_id)
        if meta_snapshot is None:
            raise KeyError(job_id)

        event_id = await self._redis.incr(self._event_sequence_key(job_id))
        record_balancer_redis_writes("next_event_id", 1)
        event = {
            "event_id": event_id,
            "timestamp": time.time(),
            "level": level,
            "status": status,
            "stage": stage,
            "message": message,
            "progress": progress,
        }

        meta_snapshot["events_count"] = int(meta_snapshot.get("events_count", 0)) + 1

        if update_meta:
            meta_snapshot["status"] = status
            meta_snapshot["stage"] = stage
            if progress is not None:
                meta_snapshot["progress"] = progress
            if status == "running" and meta_snapshot.get("started_at") is None:
                meta_snapshot["started_at"] = time.time()
            if status in {"failed", "succeeded"}:
                meta_snapshot["finished_at"] = time.time()

        await self._persist_event_and_meta(job_id, event=event, meta=meta_snapshot)
        return event

    async def mark_running(self, job_id: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        meta_snapshot = meta
        if meta_snapshot is None:
            meta_snapshot = await self.get_job_meta(job_id)
        if meta_snapshot is None:
            raise KeyError(job_id)

        meta_snapshot["status"] = "running"
        meta_snapshot["stage"] = "running"
        meta_snapshot["started_at"] = time.time()
        meta_snapshot["error"] = None

        await self.append_event(
            job_id,
            status="running",
            stage="running",
            level="info",
            message="Balancer job started",
            update_meta=False,
            meta=meta_snapshot,
        )
        return meta_snapshot

    async def update_runtime_state(
        self,
        job_id: str,
        *,
        stage: str,
        status: JobStatus = "running",
        progress: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        meta_snapshot = meta
        if meta_snapshot is None:
            meta_snapshot = await self.get_job_meta(job_id)
        if meta_snapshot is None:
            raise KeyError(job_id)

        meta_snapshot["status"] = status
        meta_snapshot["stage"] = stage
        if progress is not None:
            meta_snapshot["progress"] = progress
        await self._save_meta(job_id, meta_snapshot)

    async def mark_succeeded(
        self,
        job_id: str,
        result: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta_snapshot = meta
        if meta_snapshot is None:
            meta_snapshot = await self.get_job_meta(job_id)
        if meta_snapshot is None:
            raise KeyError(job_id)

        meta_snapshot["status"] = "succeeded"
        meta_snapshot["stage"] = "completed"
        meta_snapshot["finished_at"] = time.time()
        meta_snapshot["error"] = None
        meta_snapshot["events_count"] = int(meta_snapshot.get("events_count", 0)) + 1

        event_id = await self._redis.incr(self._event_sequence_key(job_id))
        record_balancer_redis_writes("next_event_id", 1)
        event = {
            "event_id": event_id,
            "timestamp": time.time(),
            "level": "success",
            "status": "succeeded",
            "stage": "completed",
            "message": "Balancer job completed successfully",
            "progress": None,
        }

        await self._persist_event_and_meta(
            job_id,
            event=event,
            meta=meta_snapshot,
            result=result,
        )
        await self._release_active_job(job_id, meta_snapshot)
        return meta_snapshot

    async def mark_failed(
        self,
        job_id: str,
        error_message: str,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta_snapshot = meta
        if meta_snapshot is None:
            meta_snapshot = await self.get_job_meta(job_id)
        if meta_snapshot is None:
            raise KeyError(job_id)

        meta_snapshot["status"] = "failed"
        meta_snapshot["stage"] = "failed"
        meta_snapshot["finished_at"] = time.time()
        meta_snapshot["error"] = error_message
        meta_snapshot["events_count"] = int(meta_snapshot.get("events_count", 0)) + 1

        event_id = await self._redis.incr(self._event_sequence_key(job_id))
        record_balancer_redis_writes("next_event_id", 1)
        event = {
            "event_id": event_id,
            "timestamp": time.time(),
            "level": "error",
            "status": "failed",
            "stage": "failed",
            "message": error_message,
            "progress": None,
        }

        await self._persist_event_and_meta(
            job_id,
            event=event,
            meta=meta_snapshot,
        )
        await self._release_active_job(job_id, meta_snapshot)
        return meta_snapshot

    async def _release_active_job(self, job_id: str, meta: dict[str, Any]) -> None:
        """Release the concurrency slot reserved at creation for either principal
        kind (review H5): API-key jobs by their key id, session jobs by the
        creating user id. Mirrors ``ApiKeyUsageLimiter.active_jobs_key``."""
        if meta.get("credential_type") == "api_key":
            raw_id = meta.get("api_key_id")
            key_builder = self._api_key_active_jobs_key
        else:
            raw_id = meta.get("created_by")
            key_builder = self._session_active_jobs_key
        try:
            principal_id = int(raw_id)
        except (TypeError, ValueError):
            return
        await self._redis.srem(key_builder(principal_id), job_id)
        record_balancer_redis_writes("release_active_job", 1)

    async def get_events_since(self, job_id: str, after_event_id: int = 0) -> list[dict[str, Any]]:
        start_index = max(after_event_id, 0)
        raw_events = await self._redis.lrange(self._events_key(job_id), start_index, -1)
        return [json.loads(item) for item in raw_events]

    async def close(self) -> None:
        await self._redis.aclose()


_job_store: BalancerJobStore | None = None


def get_job_store() -> BalancerJobStore:
    global _job_store
    if _job_store is None:
        _job_store = BalancerJobStore(config.redis_url, config.balancer_job_ttl_seconds)
    return _job_store


async def close_job_store() -> None:
    global _job_store
    if _job_store is None:
        return
    await _job_store.close()
    _job_store = None
