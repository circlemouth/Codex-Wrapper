import os
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    proxy_api_key: Optional[str] = Field(default=None, alias="PROXY_API_KEY")
    codex_workdir: str = Field(default="/workspace", alias="CODEX_WORKDIR")
    codex_config_dir: Optional[str] = Field(default=None, alias="CODEX_CONFIG_DIR")
    codex_path: str = Field(default="codex", alias="CODEX_PATH")
    sandbox_mode: str = Field(default="read-only", alias="CODEX_SANDBOX_MODE")
    workspace_network_access: bool = Field(
        default=False, alias="CODEX_WORKSPACE_NETWORK_ACCESS"
    )
    reasoning_effort: str = Field(default="medium", alias="CODEX_REASONING_EFFORT")
    local_only: bool = Field(default=False, alias="CODEX_LOCAL_ONLY")
    timeout_seconds: int = Field(default=120, alias="CODEX_TIMEOUT")
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")
    # Allow server to honor x_codex.sandbox == "danger-full-access" requests.
    # When false, such requests are blocked if received (unless CODEX_LOCAL_ONLY is also false
    # in older behavior). Prefer enabling this explicitly for safety.
    allow_danger_full_access: bool = Field(default=False, alias="CODEX_ALLOW_DANGER_FULL_ACCESS")
    # Deprecated: ignored, but kept to avoid startup failures when legacy env remains.
    codex_model: Optional[str] = Field(default=None, alias="CODEX_MODEL")

    # Default to loading from ".env". You can override the path by
    # passing `_env_file` when instantiating `Settings` (see bottom).
    model_config = SettingsConfigDict(case_sensitive=False, env_file=".env")

# Allow overriding env file path via process env `CODEX_ENV_FILE`.
# Note: this variable must be set in the OS/process environment (not inside .env),
# because it controls which .env file to read.
_ENV_FILE = os.getenv("CODEX_ENV_FILE") or ".env"

# Instantiate settings, optionally pointing to a custom env file.
settings = Settings(_env_file=_ENV_FILE)
