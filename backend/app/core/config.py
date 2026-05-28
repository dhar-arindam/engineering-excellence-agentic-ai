"""Core application settings."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me"

    # API docs / OpenAPI
    enable_docs: bool = Field(
        default=True,
        description=(
            "Set to false in production to disable /docs, /redoc, and /openapi.json. "
            "Controlled via the ENABLE_DOCS environment variable."
        ),
    )

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description=(
            "Allowed CORS origins.  Use a JSON array string in the environment variable: "
            'CORS_ORIGINS=\'["https://app.example.com"]\''
        ),
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_multi_agent"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    openai_api_key: str = "sk-placeholder"
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3

    # GitHub
    github_token: str = ""

    # Review
    max_concurrent_agents: int = 5
    review_timeout_seconds: int = 300

    # Scan task queue (Arq / Redis)
    scan_max_concurrent: int = 3
    scan_timeout_seconds: int = 600
    scan_lock_ttl_seconds: int = 660
    scan_queue_name: str = "arq:scans"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
