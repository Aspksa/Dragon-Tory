from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Dragon Tory"
    version: str = "00.00.02"
    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = Path("./data")

    deepseek_api_key: str | None = None
    claude_api_key: str | None = None

    memory_embedding_provider: str = "hash"
    memory_embedding_url: str | None = None
    memory_embedding_api_key: str | None = None
    memory_embedding_model: str | None = None
    memory_embedding_dimensions: int = 384
    memory_related_threshold: float = 0.82

    memory_automation_enabled: bool = True
    memory_maintenance_interval_seconds: int = 1800
    memory_archive_after_days: int = 180
    memory_archive_max_importance: float = 0.30
    memory_archive_max_access_count: int = 1
    memory_auto_consolidate_threshold: int = 40
    memory_consolidate_cooldown_hours: int = 24

    model_config = SettingsConfigDict(
        env_prefix="TOORU_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def memory_db_path(self) -> Path:
        return self.data_dir / "memory" / "tooru_memory.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
