import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from typing import AsyncIterator, Dict, List, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore

from .config import settings


class CodexError(Exception):
    """Custom error for Codex failures."""


logger = logging.getLogger(__name__)


class _ReasoningSuppressor:
    """Track whether Codex human-oriented output is currently streaming reasoning text."""

    def __init__(self, expose_reasoning: bool):
        self._expose_reasoning = expose_reasoning
        self._suppress = False

    def should_skip(self, raw_line: str) -> bool:
        """Return True when the given stdout line belongs to a reasoning block we should hide."""

        if self._expose_reasoning:
            return False

        normalized = _TIMESTAMP_PREFIX.sub("", raw_line)
        stripped = normalized.strip()
        has_timestamp = bool(_TIMESTAMP_PREFIX.match(raw_line))
        lowered = stripped.lower()

        if has_timestamp and lowered.startswith("thinking"):
            self._suppress = True
            return True

        if self._suppress:
            if has_timestamp and lowered.startswith("codex"):
                self._suppress = False
                return True
            if not stripped:
                return True
            if not has_timestamp:
                return True
            return True

        return False


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
                if isinstance(item, str):
                    parsed.append(item)
                    continue
                if isinstance(item, dict):
                    for key in ("id", "name", "model"):
                        value = item.get(key)
                        if isinstance(value, str):
                            parsed.append(value)
                            break
            return _dedupe_preserving_order(parsed)

    parsed_lines: List[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("available models"):
            continue
        token = stripped.split()[0]
        lowered_token = token.lower()
        if lowered_token in {"model", "name", "id"}:
            continue
        parsed_lines.append(token)

    return _dedupe_preserving_order(parsed_lines)


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
    """Run codex CLI as async generator yielding filtered stdout lines suitable for SSE.

    Filters human-oriented headers and MCP warnings so only assistant text remains.
    """
    cmd = _build_cmd_and_env(prompt, overrides, images, model)
    codex_env = _build_codex_env()
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
        # Stateful filtering: suppress the CLI prompt echo that follows "User instructions:" lines
        suppress_instructions_block = False
        reasoning_filter = _ReasoningSuppressor(settings.expose_reasoning)
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.decode()

            # Drop the echoed prompt lines the CLI prints under "User instructions:".
            if suppress_instructions_block:
                # A new timestamped line indicates the CLI has moved on to real events.
                if _TIMESTAMP_PREFIX.match(raw):
                    suppress_instructions_block = False
                else:
                    continue

            # Detect the start of the instructions block (prompt echo) and skip it entirely.
            chk = _TIMESTAMP_PREFIX.sub("", raw).strip()
            if chk.startswith("User instructions:"):
                suppress_instructions_block = True
                continue

            if reasoning_filter.should_skip(raw):
                continue

            cleaned = filter_codex_stdout_line(raw)
            if cleaned:
                yield cleaned
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


_TIMESTAMP_PREFIX = re.compile(r"^\[[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\]]+\]\s*")
# Loose timestamp-only line, e.g. "2025/09/15 06:53:40" or "2025-09-15 06:53:40"
_LOOSE_TIMESTAMP_LINE = re.compile(r"^\s*\d{4}[-\/]\d{2}[-\/]\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*$")

_DROP_PREFIXES = (
    "OpenAI Codex v",
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning effort:",
    "reasoning summaries:",
    "User instructions:",
    "tokens used:",
)

def filter_codex_stdout_line(line: str) -> Optional[str]:
    """Filter human-oriented Codex CLI lines, returning cleaned text (with original newlines).

    Preserves assistant-authored whitespace while removing timestamps, headers, and prompt echoes.
    """
    if not line:
        return None

    # Normalize newline handling but keep track so we can restore it.
    newline = ""
    if line.endswith("\r\n"):
        newline = "\n"
        body = line[:-2]
    elif line.endswith("\n"):
        newline = "\n"
        body = line[:-1]
    else:
        body = line

    stripped_for_check = body.strip()
    if _LOOSE_TIMESTAMP_LINE.match(stripped_for_check):
        return None

    s = _TIMESTAMP_PREFIX.sub("", body)
    compare = s.lstrip()
    lower_compare = compare.lower()

    if compare.startswith("--------"):
        return None
    if compare.startswith("ERROR: MCP client for ") or "mcp client for" in lower_compare:
        return None
    for p in _DROP_PREFIXES:
        if compare.startswith(p):
            return None

    if compare.startswith("User:"):
        return None

    if compare.startswith("Assistant:"):
        lead_len = len(s) - len(compare)
        s = s[lead_len + len("Assistant:") :]
        s = s.lstrip()
        if not s:
            return None
        compare = s.lstrip()
        lower_compare = compare.lower()

    if lower_compare.startswith("codex"):
        lead_len = len(s) - len(compare)
        s = s[lead_len:]
        lower = s.lower()
        if lower.startswith("codex"):
            s = s[len("codex") :]
            s = s.lstrip(" :\t-")

    if not s:
        return newline or None

    return f"{s}{newline}" if newline else s


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

        return text
    except asyncio.TimeoutError:
        raise CodexError("codex execution timed out")
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass
