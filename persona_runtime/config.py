"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent

# Used only when INTERNAL_API_TOKEN is unset (local dev). Both processes read the same .env.
DEV_INTERNAL_TOKEN = "dev-internal-token-change-me"


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
    proactive_max_per_hour: int = Field(2, alias="PROACTIVE_MAX_PER_HOUR")
    proactive_max_per_day: int = Field(8, alias="PROACTIVE_MAX_PER_DAY")
    proactive_max_per_week: int = Field(28, alias="PROACTIVE_MAX_PER_WEEK")
    proactive_min_gap_minutes: float = Field(5.0, alias="PROACTIVE_MIN_GAP_MINUTES")
    proactive_min_gap_hours: float = Field(20.0, alias="PROACTIVE_MIN_GAP_HOURS")
    proactive_quiet_start: str = Field("22:00", alias="PROACTIVE_QUIET_START")
    proactive_quiet_end: str = Field("08:00", alias="PROACTIVE_QUIET_END")
    proactive_scan_minutes: float = Field(2.0, alias="PROACTIVE_SCAN_MINUTES")
    proactive_interval_jitter_ratio: float = Field(0.15, alias="PROACTIVE_INTERVAL_JITTER_RATIO")
    proactive_unanswered_cooldown_hours: float = Field(6.0, alias="PROACTIVE_UNANSWERED_COOLDOWN_HOURS")
    proactive_max_consecutive_initiations: int = Field(3, alias="PROACTIVE_MAX_CONSECUTIVE_INITIATIONS")
    proactive_analyze_recent_messages: int = Field(10, alias="PROACTIVE_ANALYZE_RECENT_MESSAGES")
    proactive_max_bubbles: int = Field(3, alias="PROACTIVE_MAX_BUBBLES")
    proactive_job_ttl_hours: float = Field(6.0, alias="PROACTIVE_JOB_TTL_HOURS")
    proactive_delivery: str = Field("in_app", alias="PROACTIVE_DELIVERY")
    # Turns Sarah keeps leading after the user answers an outbound/opening message
    sarah_led_turns: int = Field(4, alias="SARAH_LED_TURNS")

    # Simulated reply timing for normal replies (life simulator). Proactive never delays.
    realistic_reply_delays: bool = Field(True, alias="REALISTIC_REPLY_DELAYS")

    # Shared secret between the Django proxy and FastAPI. FastAPI rejects calls without it.
    internal_api_token: str = Field("", alias="INTERNAL_API_TOKEN")
    max_users_per_browser: int = Field(25, alias="MAX_USERS_PER_BROWSER")

    @property
    def effective_internal_token(self) -> str:
        return self.internal_api_token or DEV_INTERNAL_TOKEN

    @property
    def openai_model_name(self) -> str:
        """Return the configured model name without hard-coding."""
        return self.openai_model


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    get_settings.cache_clear()
