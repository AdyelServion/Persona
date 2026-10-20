"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Required runtime settings. Missing values fail loudly at startup."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_uri: str = Field(..., alias="MONGODB_URI")
    db_name: str = Field(..., alias="DB_NAME")
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field(..., alias="OPENAI_MODEL")
    ngrok_key: str = Field("", alias="NGROK_KEY")

    default_persona_id: str = Field("sarah_taylor_001", alias="DEFAULT_PERSONA_ID")
    default_user_id: str = Field("local-user", alias="DEFAULT_USER_ID")
    fastapi_base_url: str = Field("http://127.0.0.1:8001", alias="FASTAPI_BASE_URL")
    django_port: int = Field(8000, alias="DJANGO_PORT")
    fastapi_port: int = Field(8001, alias="FASTAPI_PORT")
    persona_source_dir: Path = Field(default_factory=lambda: ROOT_DIR)
    timezone: str = Field("Europe/London", alias="PERSONA_TIMEZONE")
    context_char_budget: int = Field(12000, alias="CONTEXT_CHAR_BUDGET")
    memory_importance_threshold: float = Field(0.45, alias="MEMORY_IMPORTANCE_THRESHOLD")
    memory_jaccard_dup_threshold: float = Field(0.75, alias="MEMORY_JACCARD_DUP_THRESHOLD")
    max_retrieved_memories: int = Field(8, alias="MAX_RETRIEVED_MEMORIES")
    recent_message_limit: int = Field(12, alias="RECENT_MESSAGE_LIMIT")

    # Async response / life simulation
    response_worker_enabled: bool = Field(True, alias="RESPONSE_WORKER_ENABLED")
    response_worker_poll_seconds: float = Field(1.5, alias="RESPONSE_WORKER_POLL_SECONDS")
    batch_window_min_seconds: float = Field(15.0, alias="BATCH_WINDOW_MIN_SECONDS")
    batch_window_max_seconds: float = Field(120.0, alias="BATCH_WINDOW_MAX_SECONDS")
    life_time_scale: float = Field(1.0, alias="LIFE_TIME_SCALE")

    # Proactive / resume outbound (default off — no idle messaging loop)
    proactive_outbound_enabled: bool = Field(False, alias="PROACTIVE_OUTBOUND_ENABLED")
    proactive_min_interval_hours: float = Field(12.0, alias="PROACTIVE_MIN_INTERVAL_HOURS")
    proactive_max_per_day: int = Field(1, alias="PROACTIVE_MAX_PER_DAY")

    @property
    def openai_model_name(self) -> str:
        """Return the configured model name without hard-coding."""
        return self.openai_model


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    get_settings.cache_clear()
