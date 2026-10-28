from pydantic import RedisDsn

from shared.core.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    redis_url: RedisDsn
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672"
    challonge_username: str = ""
    challonge_api_key: str = ""
    challonge_auto_sync_enabled: bool = True
    challonge_auto_sync_interval_minutes: int = 5

    tournaments_cache_ttl: int = 60 * 5
    teams_cache_ttl: int = 60 * 5
    standings_cache_ttl: int = 60 * 5
    encounters_cache_ttl: int = 60 * 5
    # Match detail pages can change mid-series (live score edits), so they rely
    # on a short TTL instead of targeted invalidation (the key has no
    # tournament_id to name a tournament's cache generations by).
    match_cache_ttl: int = 30
    # A pick-ban write invalidates no tournament cache (realtime_commit.py), so the tournament's pick-ban outcomes
    # stay fresh during a live tournament by TTL alone.
    pick_ban_outcomes_cache_ttl: int = 30

    # Subscription-entitlement provider credentials. Optional: without it Twitch
    # still answers `unknown` (fail open) with a reason, so a missing credential
    # degrades the gate to "not enforced" rather than refusing every patron.
    # Boosty (Discord roles) asks discord-service over the broker; no bot token here.
    twitch_client_id: str | None = None

    @property
    def api_cache_url(self) -> str:
        return f"{self.redis_url}/5"

    @property
    def backend_cache_url(self) -> str:
        return f"{self.redis_url}/6"


settings = Settings()
