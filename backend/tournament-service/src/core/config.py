from pydantic import RedisDsn

from shared.core.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    project_name: str = "OWT Tournament Service"
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
    standings_cache_ttl: int = 60 * 5
    encounters_cache_ttl: int = 60 * 5
    # Match detail pages can change mid-series (live score edits), so they rely
    # on a short TTL instead of targeted invalidation (the key has no
    # tournament_id for the invalidation patterns to match on).
    match_cache_ttl: int = 30

    # Subscription-entitlement providers. Both optional: without them the
    # resolver still answers, reporting `unknown` (fail open) with a reason, so a
    # missing credential degrades the gate to "not enforced" rather than
    # refusing every patron.
    #
    # `discord_token` is the SAME bot token discord-service already uses; the bot
    # is already present in organizers' guilds. Reading one member's roles needs
    # no privileged intent (see the design doc's fact table).
    discord_token: str | None = None
    twitch_client_id: str | None = None

    @property
    def api_cache_url(self) -> str:
        return f"{self.redis_url}/5"

    @property
    def backend_cache_url(self) -> str:
        return f"{self.redis_url}/6"


settings = Settings()
