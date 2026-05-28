"""Runtime settings and small config helpers."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


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
    openai_proxy: str | None = Field(default=None)
    anysearch_api_key: str | None = Field(default=None)
    anysearch_mcp_url: str = "https://api.anysearch.com/mcp"
    anysearch_proxy: str | None = Field(default=None)

    dify_base_url: str = "https://api.dify.ai/v1"
    dify_dataset_id: str | None = Field(default=None)
    dify_api_key: str | None = Field(default=None)
    dify_proxy: str | None = Field(default=None)
    dify_skip_check_for_dry_run: bool = False

    admin_username: str = "admin"
    admin_password: str | None = Field(default=None)
    jwt_secret: str | None = Field(default=None)
    jwt_cookie_name: str = "meme_collector_auth"
    jwt_ttl_minutes: int = 480
    csrf_cookie_name: str = "meme_collector_csrf"


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


def parse_bool(value: bool | str | None, *, default: bool = False) -> bool:
    """Parse persisted/env boolean values without relying on string truthiness."""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default
