"""Utility helpers for discovering and caching Codex models."""

import logging
import os
from typing import List, Optional

from .codex import CodexError, list_codex_models

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "codex-cli"
_AVAILABLE_MODELS: List[str] = [DEFAULT_MODEL]
_LAST_ERROR: Optional[str] = None
_WARNED_LEGACY_ENV = False


async def initialize_model_registry() -> List[str]:
    """Populate the available model list by querying the Codex CLI."""

    global _AVAILABLE_MODELS, _LAST_ERROR

    _warn_if_legacy_env_present()

    try:
        models = await list_codex_models()
        if not models:
            raise CodexError("Codex CLI returned an empty model list")
        _AVAILABLE_MODELS = models
        _LAST_ERROR = None
        logger.info("Loaded %d Codex model(s): %s", len(models), ", ".join(models))
    except Exception as exc:  # pragma: no cover - startup failure path
        _LAST_ERROR = str(exc)
        logger.warning(
            "Falling back to default model list because Codex model discovery failed: %s",
            exc,
        )
        _AVAILABLE_MODELS = [DEFAULT_MODEL]
    return list(_AVAILABLE_MODELS)


def get_available_models() -> List[str]:
    """Return a copy of the currently cached model list."""

    return list(_AVAILABLE_MODELS)


def get_default_model() -> str:
    """Return the default model name used when clients omit `model`."""

    return _AVAILABLE_MODELS[0] if _AVAILABLE_MODELS else DEFAULT_MODEL


def choose_model(requested: Optional[str]) -> str:
    """Validate the requested model name and return the selected value."""

    if requested:
        if requested in _AVAILABLE_MODELS:
            return requested
        available = ", ".join(_AVAILABLE_MODELS)
        raise ValueError(
            f"Model '{requested}' is not available. Choose one of: {available or 'none'}"
        )
    return get_default_model()


def get_last_error() -> Optional[str]:
    """Return the most recent discovery error message (if any)."""

    return _LAST_ERROR


def _warn_if_legacy_env_present() -> None:
    global _WARNED_LEGACY_ENV
    if _WARNED_LEGACY_ENV:
        return

    legacy_value = os.getenv("CODEX_MODEL")
    if legacy_value:
        logger.warning(
            "Environment variable CODEX_MODEL is deprecated and ignored. Detected value: %s",
            legacy_value,
        )
    _WARNED_LEGACY_ENV = True
