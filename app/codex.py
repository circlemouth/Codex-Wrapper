import asyncio
from typing import AsyncIterator, Dict, Optional

from .config import settings


class CodexError(Exception):
    """Custom error for Codex failures."""


async def run_codex(prompt: str, overrides: Optional[Dict] = None) -> AsyncIterator[str]:
    """Run codex CLI as async generator yielding stdout lines."""
    cfg = {
        "sandbox_mode": settings.sandbox_mode,
        "approval_policy": settings.approval_policy,
        "model_reasoning_effort": settings.reasoning_effort,
    }
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})

    cmd = [settings.codex_path, "exec", prompt, "-q"]
    for key, value in cfg.items():
        if key == "network_access":
            # handled separately when sandbox_mode is workspace-write
            continue
        cmd += ["--config", f"{key}='{value}'"]

    if settings.codex_model:
        cmd += ["--config", f"model='{settings.codex_model}'"]

    if overrides and overrides.get("sandbox") == "workspace-write":
        network = overrides.get("network_access")
        if network is not None:
            cmd += ["--config", f"sandbox_workspace_write='{{ network_access = {str(network).lower()} }}'"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=settings.codex_workdir,
    )

    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield line.decode().rstrip()
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
