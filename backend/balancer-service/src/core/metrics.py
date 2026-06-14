from __future__ import annotations

from prometheus_client import Counter, Histogram

BALANCER_JOB_QUEUE_WAIT_SECONDS = Histogram(
    "balancer_job_queue_wait_seconds",
    "Time a balancer job waits in queue before worker execution starts.",
    ("algorithm",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

BALANCER_JOB_TOTAL_SECONDS = Histogram(
    "balancer_job_total_seconds",
    "End-to-end balancer job execution time inside the worker.",
    ("algorithm", "status"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

BALANCER_SOLVER_SECONDS = Histogram(
    "balancer_solver_seconds",
    "Time spent inside the selected balancer solver.",
    ("algorithm",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

BALANCER_JOB_REDIS_WRITES_TOTAL = Counter(
    "balancer_job_redis_writes_total",
    "Total number of Redis write commands executed by the balancer job store.",
    ("operation",),
)


def record_balancer_redis_writes(operation: str, count: int) -> None:
    if count <= 0:
        return
    BALANCER_JOB_REDIS_WRITES_TOTAL.labels(operation=operation).inc(count)
