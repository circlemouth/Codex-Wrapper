"""Utility helpers for discovering and caching Codex models."""

import logging
import os
from typing import List, Optional, Tuple

from .codex import CodexError, apply_codex_profile_overrides, list_codex_models

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "codex-cli"
_AVAILABLE_MODELS: List[str] = [DEFAULT_MODEL]
_LAST_ERROR: Optional[str] = None
_WARNED_LEGACY_ENV = False

REASONING_EFFORT_SUFFIXES = ("minimal", "low", "medium", "high")


def _augment_models(models: List[str]) -> List[str]:
    """Add known aliases (e.g., strip -codex) and remove duplicates."""

    augmented: list[str] = []
    seen = set()
    for model in models:
        if model and model not in seen:
            augmented.append(model)
            seen.add(model)
        if model.endswith('-codex'):
            base = model[:-6]
            if base and base not in seen:
                augmented.append(base)
                seen.add(base)
    return augmented


async def initialize_model_registry() -> List[str]:
    """Populate the available model list by querying the Codex CLI."""

    global _AVAILABLE_MODELS, _LAST_ERROR

    _warn_if_legacy_env_present()
    apply_codex_profile_overrides()

    try:
        models = await list_codex_models()
        if not models:
            raise CodexError("Codex CLI returned an empty model list")
        _AVAILABLE_MODELS = _augment_models(models)
        _LAST_ERROR = None
        logger.info("Loaded %d Codex model(s): %s", len(models), ", ".join(models))
    except Exception as exc:  # pragma: no cover - startup failure path
        _LAST_ERROR = str(exc)
        logger.warning(
            "Falling back to default model list because Codex model discovery failed: %s",
            exc,
        )
        _AVAILABLE_MODELS = _augment_models([DEFAULT_MODEL])
    return list(_AVAILABLE_MODELS)


def get_available_models(include_reasoning_aliases: bool = False) -> List[str]:
    """Return a copy of the currently cached model list."""

    models = list(_AVAILABLE_MODELS)
    if include_reasoning_aliases and _AVAILABLE_MODELS:
        alias: List[str] = []
        for base in _AVAILABLE_MODELS:
            alias.extend(f"{base} {suffix}" for suffix in REASONING_EFFORT_SUFFIXES)
        models.extend(alias)
    return models


def get_default_model() -> str:
    """Return the default model name used when clients omit `model`."""

    return _AVAILABLE_MODELS[0] if _AVAILABLE_MODELS else DEFAULT_MODEL


def choose_model(requested: Optional[str]) -> Tuple[str, Optional[str]]:
    """Validate the requested model name and return the model plus optional reasoning effort."""

    if requested:
        base_model, effort = _split_model_and_effort(requested)
        if base_model in _AVAILABLE_MODELS:
            return base_model, effort
        available = ", ".join(get_available_models(include_reasoning_aliases=True))
        raise ValueError(
            f"Model '{requested}' is not available. Choose one of: {available or 'none'}"
        )
    return get_default_model(), None


def get_last_error() -> Optional[str]:
    """Return the most recent discovery error message (if any)."""

    return _LAST_ERROR


def _split_model_and_effort(raw: str) -> Tuple[str, Optional[str]]:
    normalized = " ".join(raw.split()) if raw else ""
    if not normalized:
        return normalized, None
    if " " in normalized:
        base, suffix = normalized.rsplit(" ", 1)
        if base and suffix.lower() in REASONING_EFFORT_SUFFIXES:
            return base, suffix.lower()
    return normalized, None


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
