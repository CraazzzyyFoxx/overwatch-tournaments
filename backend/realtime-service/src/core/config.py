from pydantic import RedisDsn
from shared.core.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    project_name: str = "Anak Realtime Service"
    port: int = 8005
    api_root_path: str = ""

    redis_url: RedisDsn
    ws_ping_interval: int = 25
    ws_idle_timeout: int = 60
    ws_replay_limit: int = 500

    @property
    def api_cache_url(self) -> str:
        return f"{self.redis_url}/7"


settings = Settings()
