"""Configuration module for balancer service."""

from __future__ import annotations

from pydantic import Field, field_validator

from shared.core.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    # Balancer-specific fields
    project_name: str = "OWT"
    description: str = "Tournament team balancing service"
    debug: bool = False
    port: int = 8005

    # Infrastructure
    redis_url: str = "redis://redis:6379"
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672"
    # Floor must stay above jobs.py::_SOLVER_WATCHDOG_SECONDS (660s): the
    # active-jobs Redis set's TTL is only re-armed on new reservations, so a
    # value below the true max job duration lets Redis expire the whole set
    # out from under a still-running job, silently resetting concurrent_jobs.
    balancer_job_ttl_seconds: int = Field(default=86400, ge=900, le=604800)

    # CORS extras
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"])

    # Logging extras
    log_format: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> "
        "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )

    # Access token
    access_token_service: str = ""

    # Absolute base of the public site, used to build the board link a mix's
    # Discord signup card carries (``PUBLIC_SITE_URL``, the same value
    # app-service and discord-service read). Platform zone only: a workspace's
    # own subdomain or custom domain is out of scope for this link.
    public_site_url: str = "http://localhost:3000"

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed_levels:
            raise ValueError(f"log_level must be one of {allowed_levels}")
        return v_upper

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


# Global configuration instance
config = Settings()
