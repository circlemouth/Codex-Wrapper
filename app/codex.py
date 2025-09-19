import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore

from .config import settings


class CodexError(Exception):
    """Custom error for Codex failures."""


logger = logging.getLogger(__name__)

_DEFAULT_PROFILE_DIR = (
    Path(__file__).resolve().parent.parent / "workspace" / "codex_profile"
)
_PROFILE_FILES = (
    ("AGENTS.md", "codex_agents.md", ("agent.md",)),
    ("config.toml", "codex_config.toml", ("config.toml",)),
)


_TIMESTAMP_LINE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}]")
_KNOWN_METADATA_PREFIXES = (
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning effort:",
    "reasoning summaries:",
    "tokens used:",
    "user instructions:",
    "user:",
    "searched:",
    "searching:",
    "retrying ",
    "error:",
)


class _CodexOutputFilter:
    """Drop CLI preamble/tool logs and surface only assistant text."""

    def __init__(self) -> None:
        self._saw_assistant = False
        self._emitted_any = False
        self._in_user_block = False

    def process(self, raw_line: str) -> Optional[str]:
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        lowered = stripped.lower()
        match = _TIMESTAMP_LINE.match(stripped)
        if match:
            remainder = stripped[match.end() :].strip().lower()
            normalized = _strip_leading_symbols(remainder)
        else:
            normalized = _strip_leading_symbols(lowered)

        if normalized.startswith("user instructions:") or normalized.startswith("user:"):
            self._in_user_block = True
            return None

        if normalized.startswith("assistant:"):
            self._in_user_block = False
            self._saw_assistant = True
            return None

        if not stripped:
            if self._in_user_block:
                return None
            if self._emitted_any:
                return "\n"
            return None

        if self._in_user_block:
            if _looks_like_codex_marker(stripped):
                self._in_user_block = False
                return None
            return None

        if _is_metadata_line(stripped):
            return None

        if not self._saw_assistant:
            self._saw_assistant = True


        self._emitted_any = True
        return f"{line}\n"


def _is_metadata_line(text: str) -> bool:
    if _TIMESTAMP_LINE.match(text):
        return True
    lower = text.lower()
    normal = _strip_leading_symbols(lower)
    return any(normal.startswith(prefix) for prefix in _KNOWN_METADATA_PREFIXES)


def _strip_leading_symbols(value: str) -> str:
    idx = 0
    length = len(value)
    while idx < length and not value[idx].isalnum():
        idx += 1
    if idx == 0:
        return value
    return value[idx:]


def _looks_like_codex_marker(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith("assistant"):
        return True
    if _TIMESTAMP_LINE.match(text) and " codex" in lowered:
        return True
    return False


def _sanitize_codex_text(raw: str) -> str:
    """Filter Codex CLI output down to assistant-visible text."""

    filt = _CodexOutputFilter()
    parts: list[str] = []
    for line in raw.splitlines():
        processed = filt.process(f"{line}\n")
        if processed:
            parts.append(processed)

    cleaned = "".join(parts).rstrip("\n")
    return cleaned


def _resolve_codex_executable() -> str:
    """Return the resolved Codex CLI executable path or raise CodexError."""

    codex_exe = settings.codex_path
    if os.path.isabs(codex_exe):
        if not (os.path.isfile(codex_exe) and os.access(codex_exe, os.X_OK)):
            raise CodexError(
                f"CODEX_PATH '{codex_exe}' is not executable or not found"
            )
        return codex_exe

    exe = shutil.which(codex_exe)
    if not exe:
        raise CodexError(
            f"codex binary not found in PATH (CODEX_PATH='{codex_exe}'). Install Codex or set CODEX_PATH."
        )
    return exe


def _ensure_workdir_exists() -> None:
    """Ensure Codex working directory exists."""

    try:
        os.makedirs(settings.codex_workdir, exist_ok=True)
    except Exception as e:
        raise CodexError(
            f"Failed to create CODEX_WORKDIR '{settings.codex_workdir}': {e}"
        )


def _resolve_codex_home_dir() -> Path:
    """Return the directory Codex CLI uses as its home, ensuring it exists."""

    if settings.codex_config_dir:
        target = Path(settings.codex_config_dir).expanduser()
    else:
        env_home = os.environ.get("CODEX_HOME")
        if env_home:
            target = Path(env_home).expanduser()
        else:
            target = Path.home() / ".codex"

    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise CodexError(f"Failed to prepare Codex home directory '{target}': {exc}")
    return target


def apply_codex_profile_overrides() -> None:
    """Copy opt-in profile files into the Codex home directory before startup."""

    configured_dir = settings.codex_profile_dir
    source_dir = (
        Path(configured_dir).expanduser()
        if configured_dir
        else _DEFAULT_PROFILE_DIR
    )
    if not source_dir.is_dir():
        return

    pending: list[tuple[Path, str, Optional[str], str]] = []
    for dest_name, primary_name, legacy_names in _PROFILE_FILES:
        selected_path: Optional[Path] = None
        legacy_match: Optional[str] = None
        for candidate in (primary_name, *legacy_names):
            candidate_path = source_dir / candidate
            if candidate_path.is_file():
                selected_path = candidate_path
                if candidate != primary_name:
                    legacy_match = candidate
                break
        if selected_path:
            pending.append((selected_path, dest_name, legacy_match, primary_name))

    if not pending:
        return

    codex_home = _resolve_codex_home_dir()
    for src_path, dest_name, legacy_name, primary_name in pending:
        dest_path = codex_home / dest_name
        try:
            shutil.copyfile(src_path, dest_path)
        except Exception as exc:
            raise CodexError(
                f"Failed to copy '{src_path}' to '{dest_path}': {exc}"
            ) from exc
        if legacy_name:
            logger.warning(
                "Codex profile override using legacy filename '%s'; rename to '%s' for future compatibility.",
                legacy_name,
                primary_name,
            )
        logger.info("Applied Codex profile override: %s -> %s", src_path, dest_path)


def _build_codex_env() -> Dict[str, str]:
    """Prepare environment variables for Codex subprocesses."""

    env = os.environ.copy()
    config_dir = settings.codex_config_dir
    if config_dir:
        try:
            os.makedirs(config_dir, exist_ok=True)
        except Exception as exc:
            raise CodexError(
                f"Failed to prepare CODEX_CONFIG_DIR '{config_dir}': {exc}"
            )
        env["CODEX_HOME"] = config_dir
    return env


def _build_cmd_and_env(
    prompt: str,
    overrides: Optional[Dict] = None,
    images: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> list[str]:
    """Build base `codex exec` command with configs and optional images."""
    cfg = {
        "sandbox_mode": settings.sandbox_mode,
        "model_reasoning_effort": settings.reasoning_effort,
        "hide_agent_reasoning": settings.hide_reasoning,
    }
    # Map API overrides (x_codex) to Codex config keys
    if overrides:
        mapped: Dict[str, object] = {}
        for k, v in overrides.items():
            if v is None:
                continue
            if k == "sandbox":
                mapped["sandbox_mode"] = v
            elif k == "reasoning_effort":
                mapped["model_reasoning_effort"] = v
            elif k == "hide_reasoning":
                mapped["hide_agent_reasoning"] = bool(v)
            elif k == "expose_reasoning":
                mapped["hide_agent_reasoning"] = not bool(v)
            else:
                mapped[k] = v
        cfg.update(mapped)

    # Resolve codex executable
    exe = _resolve_codex_executable()

    # Ensure workdir exists (create if missing)
    _ensure_workdir_exists()

    # Note: Rust CLI does not support `-q`. Use human output or JSON mode selectively.
    cmd = [exe, "exec", prompt, "--color", "never"]
    if images:
        for img in images:
            cmd += ["--image", img]
    for key, value in cfg.items():
        if key == "network_access":
            # handled separately when sandbox_mode is workspace-write
            continue
        # Use TOML-style quoting for strings
        if isinstance(value, str):
            cmd += ["--config", f"{key}=\"{value}\""]
        elif isinstance(value, bool):
            bool_value = "true" if value else "false"
            cmd += ["--config", f"{key}={bool_value}"]
        else:
            cmd += ["--config", f"{key}={value}"]

    if model:
        cmd += ["--config", f"model=\"{model}\""]

    override_network = overrides.get("network_access") if overrides else None

    effective_sandbox = cfg.get("sandbox_mode", settings.sandbox_mode)
    if effective_sandbox == "workspace-write":
        allow_network = (
            bool(override_network)
            if override_network is not None
            else settings.workspace_network_access
        )
        if override_network is not None or settings.workspace_network_access:
            toml_bool = "true" if allow_network else "false"
            cmd += ["--config", f"sandbox_workspace_write={{ network_access = {toml_bool} }}"]

    return cmd


async def list_codex_models() -> List[str]:
    """Query the Codex CLI for available models."""

    exe = _resolve_codex_executable()
    _ensure_workdir_exists()
    codex_env = _build_codex_env()

    attempts = [
        [exe, "models", "list", "--json"],
        [exe, "models", "--json"],
        [exe, "models", "list"],
        [exe, "models"],
    ]
    errors: List[str] = []

    for cmd in attempts:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=settings.codex_workdir,
                env=codex_env,
            )
        except FileNotFoundError as e:
            raise CodexError(
                f"Failed to launch codex: {e}. Check CODEX_PATH and PATH."
            )
        except PermissionError as e:
            raise CodexError(
                f"Permission error launching codex: {e}. Ensure the binary is executable."
            )
        except Exception as e:  # pragma: no cover - unexpected failure
            errors.append(f"{' '.join(cmd)} -> {e}")
            continue

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=settings.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            errors.append(f"{' '.join(cmd)} -> timed out")
            continue

        if proc.returncode != 0:
            err_text = (stderr_data or b"").decode().strip() or f"exit code {proc.returncode}"
            errors.append(f"{' '.join(cmd)} -> {err_text}")
            continue

        models = _parse_model_listing((stdout_data or b"").decode())
        if models:
            logger.debug("Resolved Codex models via '%s': %s", " ".join(cmd), models)
            return models

        errors.append(f"{' '.join(cmd)} -> no models returned")

    try:
        proto_models = await _probe_models_via_proto(exe)
    except Exception as exc:  # pragma: no cover - network/process failure path
        errors.append(f"{exe} proto -> {exc}")
    else:
        if proto_models:
            logger.debug("Resolved Codex models via 'proto': %s", proto_models)
            return proto_models
        errors.append(f"{exe} proto -> no models returned")

    try:
        config_models = _models_from_config()
    except Exception as exc:  # pragma: no cover - file parsing failure
        errors.append(f"config.toml -> {exc}")
    else:
        if config_models:
            logger.debug("Resolved Codex models via config: %s", config_models)
            return config_models
        errors.append("config.toml -> no models returned")

    detail = "; ".join(errors) if errors else "no output"
    logger.warning("Unable to list Codex models (%s)", detail)
    raise CodexError(f"Unable to list Codex models ({detail})")


def _parse_model_listing(raw: str) -> List[str]:
    """Parse Codex CLI model listings from JSON or plaintext."""

    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        pass
    else:
        items = None
        if isinstance(data, dict):
            for key in ("data", "models", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    items = value
                    break
            else:
                if isinstance(data.get("id"), str):
                    items = [data]
        elif isinstance(data, list):
            items = data

        if items is not None:
            parsed: List[str] = []
            for item in items:
                parsed.extend(_extract_model_identifiers(item))
            return _dedupe_preserving_order(parsed)

    parsed_lines: List[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("available models"):
            continue
        parts = stripped.split()
        if not parts:
            continue
        token = parts[0]
        lowered_token = token.lower()
        if lowered_token in {"model", "name", "id"}:
            continue
        parsed_lines.append(token)
        if len(parts) > 1:
            for variant in parts[1:]:
                alias = _compose_codex_variant_name(token, variant)
                if alias:
                    parsed_lines.append(alias)

    return _dedupe_preserving_order(parsed_lines)


def _extract_model_identifiers(item: Any) -> List[str]:
    if isinstance(item, str):
        cleaned = item.strip()
        return [cleaned] if cleaned else []
    if isinstance(item, dict):
        return _extract_model_identifiers_from_dict(item)
    return []


def _extract_model_identifiers_from_dict(data: Dict[str, Any]) -> List[str]:
    results: List[str] = []
    base = _first_non_empty_string(data, ("id", "model", "name", "slug"))
    if base:
        results.append(base)

    for key in ("deployment", "variant"):
        results.extend(_collect_codex_aliases(base, data.get(key)))

    for key in ("deployments", "variants"):
        results.extend(_collect_codex_aliases(base, data.get(key)))

    return results


def _first_non_empty_string(data: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _collect_codex_aliases(base: Optional[str], raw_value: Any) -> List[str]:
    aliases: List[str] = []
    for variant in _iter_variant_strings(raw_value):
        alias = _compose_codex_variant_name(base, variant)
        if alias:
            aliases.append(alias)
    return aliases


def _iter_variant_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for entry in value:
            yield from _iter_variant_strings(entry)
    elif isinstance(value, dict):
        for key in ("id", "name", "variant", "deployment"):
            maybe = value.get(key)
            if isinstance(maybe, str):
                yield maybe


def _compose_codex_variant_name(base: Optional[str], variant: str) -> Optional[str]:
    if not variant:
        return None
    normalized_variant = re.sub(r"[^0-9a-zA-Z._-]+", "-", variant.strip().lower())
    normalized_variant = re.sub(r"-+", "-", normalized_variant).strip("-")
    if not normalized_variant or "codex" not in normalized_variant:
        return None

    base_name = base.strip() if isinstance(base, str) else ""
    if base_name:
        if base_name.lower().endswith(f"-{normalized_variant}"):
            return None
        return f"{base_name}-{normalized_variant}"
    return normalized_variant


async def _probe_models_via_proto(exe: str) -> List[str]:
    """Use `codex proto` to discover the current default model."""

    codex_env = _build_codex_env()

    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "proto",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.codex_workdir,
            env=codex_env,
        )
    except FileNotFoundError as exc:
        raise CodexError(f"Failed to launch codex proto: {exc}")

    discovered: Optional[str] = None
    try:
        assert proc.stdout is not None
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=settings.timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise CodexError("codex proto did not emit session_configured in time") from exc
            if not line:
                break
            try:
                payload = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            msg = payload.get("msg") if isinstance(payload, dict) else None
            if isinstance(msg, dict) and msg.get("type") == "session_configured":
                model = msg.get("model")
                if isinstance(model, str) and model:
                    discovered = model
                break
    finally:
        shutdown_payload = json.dumps({"id": "wrapper_shutdown", "op": {"type": "shutdown"}}) + "\n"
        if proc.stdin is not None:
            try:
                proc.stdin.write(shutdown_payload.encode())
                await proc.stdin.drain()
            except Exception:
                pass
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    if discovered:
        return [discovered]
    return []


def _dedupe_preserving_order(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _models_from_config() -> List[str]:
    """Extract model names from ~/.codex/config.toml as a fallback."""

    codex_home = (
        settings.codex_config_dir
        or os.environ.get("CODEX_HOME")
        or os.path.expanduser("~/.codex")
    )
    config_path = os.path.join(codex_home, "config.toml")
    if not os.path.isfile(config_path):
        return []

    with open(config_path, "rb") as fh:
        data = tomllib.load(fh)

    models: List[str] = []

    def _add(value: Optional[str]) -> None:
        if isinstance(value, str) and value:
            models.append(value)

    _add(data.get("model"))
    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if isinstance(profile, dict):
                _add(profile.get("model"))

    augmented = list(models)
    for model in list(models):
        if isinstance(model, str) and model.endswith('-codex'):
            base = model[:-6]
            if base:
                augmented.append(base)
    return _dedupe_preserving_order(augmented)


async def run_codex(
    prompt: str,
    overrides: Optional[Dict] = None,
    images: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> AsyncIterator[str]:
    """Run codex CLI as async generator yielding stdout lines suitable for SSE."""
    cmd = _build_cmd_and_env(prompt, overrides, images, model)
    codex_env = _build_codex_env()
    output_filter = _CodexOutputFilter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.codex_workdir,
            env=codex_env,
        )
    except FileNotFoundError as e:
        raise CodexError(
            f"Failed to launch codex: {e}. Check CODEX_PATH and PATH."
        )
    except PermissionError as e:
        raise CodexError(
            f"Permission error launching codex: {e}. Ensure the binary is executable."
        )
    except Exception as e:
        raise CodexError(f"Unable to start codex process: {e}")

    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            filtered = output_filter.process(line.decode(errors="ignore"))
            if filtered:
                yield filtered
        await asyncio.wait_for(proc.wait(), timeout=settings.timeout_seconds)
        if proc.returncode != 0:
            err = (await proc.stderr.read()).decode().strip()
            raise CodexError(err or "codex execution failed")
    except asyncio.TimeoutError:
        proc.kill()
        raise CodexError("codex execution timed out")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()



async def run_codex_last_message(
    prompt: str,
    overrides: Optional[Dict] = None,
    images: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> str:
    """Run codex and return only the final assistant message using --json and --output-last-message.

    This avoids human oriented headers and logs from the CLI.
    """
    cmd = _build_cmd_and_env(prompt, overrides, images, model)
    # Create temp file in workdir to ensure permissions
    _ensure_workdir_exists()
    codex_env = _build_codex_env()
    with tempfile.NamedTemporaryFile(prefix="codex-last-", suffix=".txt", dir=settings.codex_workdir, delete=False) as tf:
        out_path = tf.name
    cmd = cmd + ["--json", "--output-last-message", out_path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.codex_workdir,
            env=codex_env,
        )
        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=settings.timeout_seconds)
        if proc.returncode != 0:
            err = (stderr_data or b"").decode().strip() or "codex execution failed"
            raise CodexError(err)
        try:
            with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            text = ""

        if not text:
            # Fallback to any stdout text when the file is empty or missing.
            text = (stdout_data or b"").decode(errors="ignore")
        sanitized = _sanitize_codex_text(text)
        if sanitized:
            return sanitized
        return text.strip()
    except asyncio.TimeoutError:
        raise CodexError("codex execution timed out")
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass
