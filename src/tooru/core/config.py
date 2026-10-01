from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from tooru.version import APP_VERSION


class Settings(BaseSettings):
    app_name: str = "Dragon Tory"
    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = Path("./data")

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://foundation-models.api.cloud.ru/v1"
    deepseek_model: str = "deepseek-ai/DeepSeek-V4-Flash"
    claude_api_key: str | None = None

    update_repository: str = "Aspksa/Dragon-Tory"
    update_branch: str = "main"

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

    # Memory Intelligence Layer. Providers are registered in AIRouter later.
    memory_intelligence_primary_provider: str = "deepseek"
    memory_intelligence_reviewer_provider: str = "claude"
    memory_intelligence_reviewer_threshold: float = 0.85
    memory_intelligence_context_limit: int = 12

    memory_guardian_enabled: bool = True
    memory_guardian_medium_importance: float = 0.65
    memory_guardian_high_importance: float = 0.85
    memory_guardian_min_confidence: float = 0.60
    memory_guardian_automation_enabled: bool = True
    memory_guardian_interval_seconds: int = 900
    memory_guardian_retry_batch_size: int = 20
    memory_guardian_max_attempts: int = 5
    memory_guardian_retry_delay_seconds: int = 1800

    model_config = SettingsConfigDict(
        env_prefix="TOORU_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def version(self) -> str:
        return APP_VERSION

    @property
    def memory_db_path(self) -> Path:
        return self.data_dir / "memory" / "tooru_memory.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
