from enum import StrEnum

# Re-export shared enums (LogStatsName, etc.) for convenience.
from shared.core.enums import *  # noqa: F401,F403


class RouteTag(StrEnum):
    """Tags used to classify API routes in this service."""

    ANALYTICS = " Analytics"
    HEALTH = " Health"
