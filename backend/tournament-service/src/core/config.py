from pydantic import RedisDsn

from shared.core.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    project_name: str = "Anak Tournament Service"
    port: int = 8004
    api_v1_str: str = "/api/v1"

    redis_url: RedisDsn
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672"
    challonge_username: str = ""
    challonge_api_key: str = ""
    challonge_auto_sync_enabled: bool = True
    challonge_auto_sync_interval_minutes: int = 5

    tournaments_cache_ttl: int = 60 * 5
    teams_cache_ttl: int = 60 * 5
    encounters_cache_ttl: int = 60 * 5
    # Match detail pages can change mid-series (live score edits), so they rely
    # on a short TTL instead of targeted invalidation (the key has no
    # tournament_id for the invalidation patterns to match on).
    match_cache_ttl: int = 30
    realtime_pubsub_channel: str = "tournament.changed"

    @property
    def api_cache_url(self) -> str:
        return f"{self.redis_url}/5"

    @property
    def backend_cache_url(self) -> str:
        return f"{self.redis_url}/6"


settings = Settings()
