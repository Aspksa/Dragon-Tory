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
