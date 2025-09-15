import asyncio
import os
import shutil
import tempfile
from typing import AsyncIterator, Dict, Optional, List
import re

from .config import settings


class CodexError(Exception):
    """Custom error for Codex failures."""


def _build_cmd_and_env(prompt: str, overrides: Optional[Dict] = None, images: Optional[List[str]] = None) -> list[str]:
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
    codex_exe = settings.codex_path
    if os.path.isabs(codex_exe):
        if not (os.path.isfile(codex_exe) and os.access(codex_exe, os.X_OK)):
            raise CodexError(
                f"CODEX_PATH '{codex_exe}' is not executable or not found"
            )
        exe = codex_exe
    else:
        exe = shutil.which(codex_exe)
        if not exe:
            raise CodexError(
                f"codex binary not found in PATH (CODEX_PATH='{codex_exe}'). Install Codex or set CODEX_PATH."
            )

    # Ensure workdir exists (create if missing)
    try:
        os.makedirs(settings.codex_workdir, exist_ok=True)
    except Exception as e:
        raise CodexError(
            f"Failed to create CODEX_WORKDIR '{settings.codex_workdir}': {e}"
        )

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
        else:
            cmd += ["--config", f"{key}={value}"]

    if settings.codex_model:
        cmd += ["--config", f"model=\"{settings.codex_model}\""]

    if overrides and overrides.get("sandbox") == "workspace-write":
        network = overrides.get("network_access")
        if network is not None:
            # Pass inline TOML table without extra quotes
            toml_bool = "true" if bool(network) else "false"
            cmd += ["--config", f"sandbox_workspace_write={{ network_access = {toml_bool} }}"]

    return cmd


async def run_codex(prompt: str, overrides: Optional[Dict] = None, images: Optional[List[str]] = None) -> AsyncIterator[str]:
    """Run codex CLI as async generator yielding filtered stdout lines suitable for SSE.

    Filters human-oriented headers and MCP warnings so only assistant text remains.
    """
    cmd = _build_cmd_and_env(prompt, overrides, images)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.codex_workdir,
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
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.decode().rstrip()

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
    """Filter human-oriented Codex CLI lines, returning cleaned text or None to drop.

    - Strips leading ISO timestamp in square brackets if present.
    - Drops known header/log prefixes (workdir/model/provider/etc.).
    - Drops MCP client startup errors (non-fatal noise).
    - Strips a leading 'codex' tag if present.
    """
    if not line:
        return None

    # Drop lines that are just timestamps
    if _LOOSE_TIMESTAMP_LINE.match(line):
        return None

    s = _TIMESTAMP_PREFIX.sub("", line).strip()

    # Known non-content noise lines
    lower = s.lower()
    if s.startswith("--------"):
        return None
    if s.startswith("ERROR: MCP client for ") or "mcp client for" in lower:
        return None
    for p in _DROP_PREFIXES:
        if s.startswith(p):
            return None

    # Drop user-echo lines, but keep assistant content if prefixed on same line
    if s.startswith("User:"):
        return None
    if s.startswith("Assistant:"):
        s = s[len("Assistant:"):].lstrip()

    # Remove leading 'codex' label if present (with or without separator)
    if lower.startswith("codex"):
        s = s[len("codex"):].lstrip(" :\t-")

    s = s.strip()
    return s or None


async def run_codex_last_message(prompt: str, overrides: Optional[Dict] = None, images: Optional[List[str]] = None) -> str:
    """Run codex and return only the final assistant message using --json and --output-last-message.

    This avoids human oriented headers and logs from the CLI.
    """
    cmd = _build_cmd_and_env(prompt, overrides, images)
    # Create temp file in workdir to ensure permissions
    os.makedirs(settings.codex_workdir, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="codex-last-", suffix=".txt", dir=settings.codex_workdir, delete=False) as tf:
        out_path = tf.name
    cmd = cmd + ["--json", "--output-last-message", out_path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.codex_workdir,
        )
        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=settings.timeout_seconds)
        if proc.returncode != 0:
            err = (stderr_data or b"").decode().strip() or "codex execution failed"
            raise CodexError(err)
        try:
            with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read().strip()
        except Exception:
            text = ""
        if not text:
            # Fallback to any stdout text, trimmed
            text = (stdout_data or b"").decode(errors="ignore").strip()
        return text
    except asyncio.TimeoutError:
        raise CodexError("codex execution timed out")
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass
