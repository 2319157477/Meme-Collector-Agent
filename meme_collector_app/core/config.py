"""Runtime settings and small config helpers."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and optional .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_path: Path = Path("data/meme_collector.sqlite3")

    openai_api_key: str | None = Field(default=None)
    openai_model: str = "gpt-5.4"
    openai_base_url: str | None = Field(default=None)
    anysearch_api_key: str | None = Field(default=None)

    dify_base_url: str = "https://api.dify.ai/v1"
    dify_dataset_id: str | None = Field(default=None)
    dify_api_key: str | None = Field(default=None)
    dify_proxy: str | None = Field(default=None)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def mask_secret(value: str | None) -> str:
    """Return a display-safe version of a secret."""

    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
