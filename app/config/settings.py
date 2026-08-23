from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "Saksham"
    app_env: str = "development"
    debug: bool = True

    database_url: str = "sqlite+aiosqlite:///./saksham.db"

    llm_api_key: str = ""
    llm_model: str = "meta-llama/llama-3.1-8b-instruct"
    llm_base_url: str = "https://openrouter.ai/api/v1"

    low_confidence_threshold: float = 0.6
    high_risk_threshold: float = 0.8
    max_tool_retries: int = 3

    escalation_webhook_url: str = ""

    required_application_fields: list[str] = [
        "applicant_name",
        "business_name",
        "pan_number",
        "phone",
    ]

    pan_pattern: str = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
    gst_pattern: str = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"

    upload_dir: str = "./data/uploads"
    max_file_size: int = 10 * 1024 * 1024  # 10 MB
    max_pdf_pages: int = 5
    allowed_mime_types: list[str] = [
        "image/jpeg",
        "image/png",
        "application/pdf",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
