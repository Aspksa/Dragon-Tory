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
