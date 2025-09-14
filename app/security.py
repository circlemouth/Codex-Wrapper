import os
import pathlib
import re
from typing import Optional, Tuple

try:
    import tomllib  # Py>=3.11
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _is_local_url(url: str) -> bool:
    """Return True if URL clearly points to localhost.

    Accepts http(s) to localhost/127.0.0.1/[::1] and unix schemes.
    Conservative default: if parse fails or host is unknown, return False.
    """
    if not url:
        return False
    u = url.strip()
    if u.startswith("unix://") or u.startswith("http+unix://"):
        return True
    m = re.match(r"^(?P<scheme>https?)://(?P<host>\[[^\]]+\]|[^/:]+)(?::\d+)?(/|$)", u, re.IGNORECASE)
    if not m:
        return False
    host = m.group("host").lower()
    return host in LOCAL_HOSTS


def _load_config_toml() -> dict:
    """Read $CODEX_HOME/config.toml (if any). Returns {} on error/missing."""
    home = os.getenv("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    path = pathlib.Path(home) / "config.toml"
    if not path.exists():
        return {}
    if tomllib is None:
        # Best-effort: treat as absent if tomllib is unavailable
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return {}


def _resolve_provider(config: dict) -> str:
    """Determine model_provider id based on config + profile selection.

    Defaults to 'openai' if unspecified.
    """
    provider: Optional[str] = None
    profile = config.get("profile")
    profiles = config.get("profiles") or {}
    if isinstance(profile, str) and isinstance(profiles, dict):
        prof = profiles.get(profile) or {}
        if isinstance(prof, dict):
            provider = prof.get("model_provider")
    if not provider:
        provider = config.get("model_provider")
    return provider or "openai"


def _provider_base_url(config: dict, provider_id: str) -> Optional[str]:
    """Resolve base_url for provider id.

    - If provider exists in config.model_providers, use its base_url.
    - For built-in 'openai', allow override via OPENAI_BASE_URL; default is remote.
    - Otherwise, return None (unknown), which callers should treat as non-local.
    """
    mps = config.get("model_providers") or {}
    if isinstance(mps, dict) and provider_id in mps:
        cfg = mps.get(provider_id) or {}
        if isinstance(cfg, dict):
            return cfg.get("base_url")
    if provider_id in {"openai", "openai-chat-completions"}:
        return os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    return None


def assert_local_only_or_raise() -> None:
    """Raise ValueError if the effective model provider is not localhost-only.

    Conservative behavior: missing/unknown config is treated as non-local.
    """
    cfg = _load_config_toml()
    provider_id = _resolve_provider(cfg)
    base_url = _provider_base_url(cfg, provider_id)
    if not base_url or not _is_local_url(base_url):
        raise ValueError(
            f"Non-local model provider detected: provider='{provider_id}', base_url='{base_url or 'DEFAULT/UNKNOWN'}'"
        )

