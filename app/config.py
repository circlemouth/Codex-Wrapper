from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    proxy_api_key: Optional[str] = Field(default=None, alias="PROXY_API_KEY")
    codex_workdir: str = Field(default="/workspace", alias="CODEX_WORKDIR")
    codex_model: Optional[str] = Field(default=None, alias="CODEX_MODEL")
    codex_path: str = Field(default="codex", alias="CODEX_PATH")
    approval_policy: str = Field(default="on-request", alias="CODEX_APPROVAL_POLICY")
    sandbox_mode: str = Field(default="read-only", alias="CODEX_SANDBOX_MODE")
    reasoning_effort: str = Field(default="medium", alias="CODEX_REASONING_EFFORT")
    local_only: bool = Field(default=False, alias="CODEX_LOCAL_ONLY")
    timeout_seconds: int = Field(default=120, alias="CODEX_TIMEOUT")
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")

    model_config = SettingsConfigDict(case_sensitive=False, env_file=".env")


settings = Settings()
