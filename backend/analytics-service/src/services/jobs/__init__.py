"""Unified analytics-job orchestration.

Replaces the v1 ``Recalculate`` + v2 ``Train ML`` + v2 ``Run inference``
triggers with one ``AnalyticsJob`` row + one RabbitMQ queue. The HTTP layer
creates and dispatches; the worker consumes, runs every requested stage,
and publishes progress to the realtime topic.
"""

from .service import (
    JOB_KIND_COMPUTE,
    JOB_KIND_TRAIN_ML,
    JOB_KINDS,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    ActiveJobConflict,
    create_job,
    get_active_job,
    get_job,
    list_jobs,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    update_progress,
)

__all__ = (
    "JOB_KIND_COMPUTE",
    "JOB_KIND_TRAIN_ML",
    "JOB_KINDS",
    "JOB_STATUS_FAILED",
    "JOB_STATUS_PENDING",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCEEDED",
    "ActiveJobConflict",
    "create_job",
    "get_active_job",
    "get_job",
    "list_jobs",
    "mark_job_failed",
    "mark_job_running",
    "mark_job_succeeded",
    "update_progress",
)
