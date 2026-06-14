from pydantic import BaseModel, Field

__all__ = (
    "HealthCheckResponse",
    "DependencyHealth",
)


class DependencyHealth(BaseModel):
    """Health status of a service dependency."""

    name: str
    status: str  # "ok" | "degraded" | "down"
    latency_ms: float | None = None
    details: str | None = None


class HealthCheckResponse(BaseModel):
    timestamp: int
    status: str
    service: str
    version: str
    dependencies: list[DependencyHealth] = Field(default_factory=list)
