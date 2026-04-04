import asyncio
import json
import logging
import os
import re
import shutil
import threading
import tempfile
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore

from .config import settings


class CodexError(Exception):
    """Custom error for Codex failures."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


logger = logging.getLogger(__name__)

DEFAULT_CODEX_MODEL = "codex-cli"
_FALLBACK_MODELS = (DEFAULT_CODEX_MODEL, "gpt-5.1")
_SKIP_PRESET_PREFIXES = ("swiftfox",)
_DEFAULT_REASONING_EFFORTS = ("low", "medium", "high")
_ALLOWED_REASONING_EFFORTS = set((*_DEFAULT_REASONING_EFFORTS, "xhigh"))

_DEFAULT_PROFILE_DIR = (
    Path(__file__).resolve().parent.parent / "workspace" / "codex_profile"
)
_PROFILE_FILES = (
    ("AGENTS.md", "codex_agents.md", ("agent.md",)),
    ("config.toml", "codex_config.toml", ("config.toml",)),
)

_ASYNCIO_STREAM_LIMIT = 512 * 1024  # 512 KiB to tolerate large tool outputs

_WORKDIR_LOCK = threading.Lock()
_WORKDIR_PATH: Optional[Path] = None
_WORKDIR_NEEDS_SKIP_GIT_CHECK = False


class _CodexConcurrencyLimiter:
    """Limit how many Codex subprocesses run in parallel."""

    def __init__(self, max_parallel: int) -> None:
        self.configure(max_parallel)

    def configure(self, max_parallel: int) -> None:
        value = max(1, int(max_parallel or 1))
        self._max_parallel = value
        self._semaphore = asyncio.Semaphore(value)

    @property
    def max_parallel(self) -> int:
        return self._max_parallel

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()


_parallel_limiter = _CodexConcurrencyLimiter(settings.max_parallel_requests)


@dataclass(frozen=True)
class ModelPresetEntry:
    """Representation of a Codex CLI model preset."""

    model: str
    effort: Optional[str] = None


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
    "tool ",
)


class _CodexOutputFilter:
    """Drop CLI preamble/tool logs and surface only assistant text."""

    def __init__(self) -> None:
        self._saw_assistant = False
        self._emitted_any = False
        self._in_user_block = False
        self._skip_tool_output = False
        self._tool_output_depth = 0

    def process(self, raw_line: str) -> Optional[str]:
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if self._skip_tool_output:
            if not stripped:
                self._skip_tool_output = False
                return None
            if _TIMESTAMP_LINE.match(stripped):
                self._skip_tool_output = False
            else:
                self._tool_output_depth += _json_structure_delta(stripped)
                if self._tool_output_depth <= 0:
                    self._skip_tool_output = False
                return None
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

        if (
            (" success" in normalized or " failed" in normalized)
            and normalized.endswith(":")
            and " in " in normalized
            and "(" in normalized
            and ")" in normalized
        ):
            self._skip_tool_output = True
            self._tool_output_depth = 0
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


def _json_structure_delta(text: str) -> int:
    """Compute net change in JSON nesting depth for a given line."""

    delta = 0
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "[{":
            delta += 1
        elif ch in "]}":
            delta -= 1
    return delta


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
    """Ensure Codex working directory exists and is writable, falling back if needed."""

    global _WORKDIR_PATH, _WORKDIR_NEEDS_SKIP_GIT_CHECK
    if _WORKDIR_PATH is not None:
        return

    with _WORKDIR_LOCK:
        if _WORKDIR_PATH is not None:
            return

        requested_path = Path(settings.codex_workdir).expanduser()
        candidates: list[Path] = [requested_path]

        fallback_candidates = [
            Path(tempfile.gettempdir()) / "codex-workdir",
            Path.home() / ".cache" / "codex-wrapper",
        ]
        for fallback in fallback_candidates:
            if fallback not in candidates:
                candidates.append(fallback)

        errors: list[tuple[Path, Exception]] = []
        resolved: Optional[Path] = None

        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                _verify_directory_write_access(candidate)
            except Exception as exc:
                errors.append((candidate, exc))
                logger.warning(
                    "Unable to prepare Codex work directory '%s': %s", candidate, exc
                )
                continue

            resolved = candidate
            break

        if resolved is None:
            detail = "; ".join(f"{path}: {err}" for path, err in errors) or "no candidates"
            raise CodexError(f"Failed to prepare Codex work directory ({detail})")

        requested_resolved = requested_path
        with suppress(Exception):
            requested_resolved = requested_path.resolve()
        with suppress(Exception):
            resolved = resolved.resolve()
        if resolved != requested_resolved:
            logger.warning(
                "CODEX_WORKDIR '%s' is not writable; falling back to '%s'",
                requested_path,
                resolved,
            )

        resolved_str = str(resolved)
        settings.codex_workdir = resolved_str
        _WORKDIR_PATH = resolved
        _WORKDIR_NEEDS_SKIP_GIT_CHECK = not _is_git_repository(resolved)


def _is_git_repository(path: Path) -> bool:
    current = path
    with suppress(Exception):
        current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return True
        if candidate == candidate.parent:
            break
    return False


def _resolve_codex_home_dir() -> Path:
    """Return the directory Codex CLI uses as its home, ensuring it exists."""

    candidates: list[Path] = []
    errors: list[tuple[Path, Exception]] = []
    resolved: Optional[Path] = None

    if settings.codex_config_dir:
        candidates.append(Path(settings.codex_config_dir).expanduser())

    env_home = os.environ.get("CODEX_HOME")
    if env_home:
        env_path = Path(env_home).expanduser()
        if env_path not in candidates:
            candidates.append(env_path)

    default_home = Path.home() / ".codex"
    if default_home not in candidates:
        candidates.append(default_home)

    workspace_home = Path(settings.codex_workdir).expanduser() / ".codex"
    if workspace_home not in candidates:
        candidates.append(workspace_home)

    temp_home = Path(tempfile.gettempdir()) / "codex"
    if temp_home not in candidates:
        candidates.append(temp_home)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            _verify_directory_write_access(candidate)
        except Exception as exc:
            errors.append((candidate, exc))
            logger.warning(
                "Unable to prepare Codex home directory '%s': %s", candidate, exc
            )
            continue

        resolved = candidate
        break

    if resolved is None:
        detail = "; ".join(f"{path}: {err}" for path, err in errors) or "no candidates"
        raise CodexError(f"Failed to prepare Codex home directory ({detail})")

    if errors:
        joined = "; ".join(f"{path}: {err}" for path, err in errors)
        logger.warning(
            "Using Codex home directory '%s' after fallback (previous attempts: %s)",
            resolved,
            joined,
        )

    _configure_codex_home_environment(resolved, bool(errors))
    return resolved


def _verify_directory_write_access(directory: Path) -> None:
    test_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix="codex-perm-", delete=False
        ) as handle:
            handle.write(b"codex")
            handle.flush()
            test_path = Path(handle.name)
    except Exception as exc:  # pragma: no cover - startup failure path
        raise PermissionError(f"write test failed: {exc}") from exc
    finally:
        if test_path:
            with suppress(Exception):
                test_path.unlink()


def _configure_codex_home_environment(resolved: Path, had_errors: bool) -> None:
    resolved_str = str(resolved)
    previous_env = os.environ.get("CODEX_HOME")
    default_home = Path.home() / ".codex"

    if previous_env != resolved_str:
        if previous_env and previous_env != resolved_str:
            logger.warning(
                "Overriding unusable CODEX_HOME '%s' with '%s'.",
                previous_env,
                resolved_str,
            )
        elif had_errors:
            logger.warning("Setting CODEX_HOME to fallback directory '%s'.", resolved_str)
        elif resolved != default_home:
            logger.info("Setting CODEX_HOME to configured directory '%s'.", resolved_str)
        os.environ["CODEX_HOME"] = resolved_str

    try:
        if settings.codex_config_dir != resolved_str:
            settings.codex_config_dir = resolved_str
    except Exception:  # pragma: no cover - defensive best effort
        pass


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

    codex_home = _resolve_codex_home_dir()
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)

    config_dir = settings.codex_config_dir
    if config_dir:
        try:
            os.makedirs(config_dir, exist_ok=True)
        except Exception as exc:
            raise CodexError(
                f"Failed to prepare CODEX_CONFIG_DIR '{config_dir}': {exc}"
            )
        env["CODEX_HOME"] = config_dir

    # Ensure `node` is available for Codex CLI shims when running under nvm.
    if shutil.which("node", path=env.get("PATH", "")) is None:
        candidate_dirs: List[Path] = []
        codex_node_path = getattr(settings, "codex_node_path", None)
        if codex_node_path:
            candidate_dirs.append(Path(codex_node_path))
        nvm_versions = Path.home() / ".nvm" / "versions" / "node"
        if nvm_versions.is_dir():
            for child in sorted(nvm_versions.iterdir(), reverse=True):
                bin_dir = child / "bin"
                if bin_dir.is_dir():
                    candidate_dirs.append(bin_dir)
        if candidate_dirs:
            original_path = env.get("PATH", "")
            path_parts = original_path.split(os.pathsep) if original_path else []
            for candidate in candidate_dirs:
                candidate_str = str(candidate)
                if candidate_str not in path_parts:
                    path_parts.insert(0, candidate_str)
                if shutil.which("node", path=os.pathsep.join(path_parts)) is not None:
                    env["PATH"] = os.pathsep.join(path_parts)
                    break
    return env


def _build_cmd_and_env(
    prompt: str,
    overrides: Optional[Dict] = None,
    images: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> tuple[list[str], str]:
    """Build base `codex exec` command with configs and optional images.

    Returns (cmd, prompt_text).  The prompt is passed via stdin (using
    ``-`` as positional arg) to avoid OS "Argument list too long" errors.
    """
    cfg = {
        "sandbox_mode": settings.sandbox_mode,
        "hide_agent_reasoning": settings.hide_reasoning,
    }
    default_effort = (
        settings.reasoning_effort.strip().lower()
        if isinstance(settings.reasoning_effort, str)
        else None
    )
    if default_effort in _ALLOWED_REASONING_EFFORTS:
        cfg["model_reasoning_effort"] = default_effort

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
    cmd = [exe, "exec", "-", "--color", "never"]
    if _WORKDIR_NEEDS_SKIP_GIT_CHECK:
        cmd.append("--skip-git-repo-check")
    if images:
        for img in images:
            cmd += ["--image", img]

    if (
        model
        and model.startswith("gpt-5")
        and "model_reasoning_effort" in cfg
        and not (overrides and overrides.get("reasoning_effort"))
    ):
        # Respect explicit reasoning aliases only; base gpt-5 should default to CLI behaviour.
        cfg.pop("model_reasoning_effort", None)

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

    return cmd, prompt


@lru_cache(maxsize=1)
def load_builtin_model_presets() -> List[ModelPresetEntry]:
    """Load model presets defined in the Codex CLI submodule."""

    preset_path = (
        Path(__file__).resolve().parent.parent
        / "submodules"
        / "codex"
        / "codex-rs"
        / "core"
        / "src"
        / "openai_models"
        / "model_presets.rs"
    )

    try:
        raw = preset_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Codex model preset file not found: %s", preset_path)
        return []
    except Exception as exc:  # pragma: no cover - unexpected IO failure
        logger.warning("Failed to read Codex model presets from %s: %s", preset_path, exc)
        return []

    model_pattern = re.compile(r'model:\s*"([^"]+)"')
    effort_pattern = re.compile(
        r"effort:\s*(?:Some\()?\s*ReasoningEffort::([A-Za-z]+)\)?"
    )

    def _extract_preset_blocks(text: str) -> List[str]:
        blocks: List[str] = []
        idx = 0
        while True:
            start = text.find("ModelPreset", idx)
            if start == -1:
                break
            brace = text.find("{", start)
            if brace == -1:
                break
            depth = 0
            i = brace
            while i < len(text):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append(text[brace + 1 : i])
                        idx = i + 1
                        break
                i += 1
            else:
                break
        return blocks

    presets: List[ModelPresetEntry] = []
    for block in _extract_preset_blocks(raw):
        model_match = model_pattern.search(block)
        if not model_match:
            continue
        model = model_match.group(1).strip()
        if not model:
            continue
        if any(model.startswith(prefix) for prefix in _SKIP_PRESET_PREFIXES):
            continue
        effort_matches = [m.lower() for m in effort_pattern.findall(block)]
        if not effort_matches:
            presets.append(ModelPresetEntry(model=model, effort=None))
            continue
        for effort in effort_matches:
            presets.append(ModelPresetEntry(model=model, effort=effort))

    if not presets:
        logger.warning("Parsed zero Codex model presets from %s", preset_path)
    return presets


def builtin_reasoning_aliases() -> Dict[str, Tuple[str, ...]]:
    """Return reasoning effort aliases keyed by model slug."""

    aliases: Dict[str, List[str]] = {}
    for preset in load_builtin_model_presets():
        if not preset.effort:
            continue
        if preset.effort not in _ALLOWED_REASONING_EFFORTS:
            continue
        bucket = aliases.setdefault(preset.model, [])
        if preset.effort not in bucket:
            bucket.append(preset.effort)

    # Ensure codex-cli also exposes low/medium/high aliases for convenience.
    codex_bucket = aliases.setdefault(DEFAULT_CODEX_MODEL, [])
    for effort in _DEFAULT_REASONING_EFFORTS:
        if effort not in codex_bucket:
            codex_bucket.append(effort)

    return {model: tuple(values) for model, values in aliases.items()}


async def list_codex_models() -> List[str]:
    """Return available models without shelling out to the Codex CLI binary."""

    presets = load_builtin_model_presets()
    models: List[str] = []
    for preset in presets:
        if preset.model and preset.model not in models:
            models.append(preset.model)

    config_models = _models_from_config()
    for model in config_models:
        if model and model not in models:
            models.append(model)

    if models:
        if "gpt-5" not in models:
            models.append("gpt-5")
        for fallback in reversed(_FALLBACK_MODELS):
            if fallback not in models:
                models.insert(0, fallback)
        logger.debug(
            "Resolved Codex models from presets/config: %s",
            ", ".join(models),
        )
        return models

    raise CodexError(
        "Unable to list Codex models (no builtin presets or config entries found)"
    )


def _dedupe_preserving_order(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _parse_model_listing(raw: str) -> List[str]:
    """Parse `codex models list` output (JSON or plaintext) into model IDs."""

    models: List[str] = []
    if not raw:
        return models

    # Prefer JSON payloads first.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict) and isinstance(data.get("data"), list):
        for entry in data["data"]:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            model_id = model_id.strip()

            deployments = entry.get("deployments") or entry.get("deployment")
            if isinstance(deployments, str):
                deployments = [deployments]
            deployments = deployments if isinstance(deployments, list) else []

            variants = entry.get("variants") if isinstance(entry.get("variants"), list) else []

            is_codex = any(isinstance(d, str) and d.strip() == "codex" for d in deployments)
            models.append(model_id)
            if is_codex and not model_id.endswith("-codex"):
                models.append(f"{model_id}-codex")

            for variant in variants:
                if isinstance(variant, dict):
                    variant_id = variant.get("id")
                else:
                    variant_id = None
                if isinstance(variant_id, str) and variant_id.strip():
                    models.append(f"{model_id}-{variant_id.strip()}")

        return _dedupe_preserving_order(models)

    # Fallback: plaintext listing.
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("available models"):
            continue
        parts = stripped.split()
        base = parts[0]
        is_codex = any(p.lower() == "codex" for p in parts[1:])
        if is_codex and not base.endswith("-codex"):
            models.append(f"{base}-codex")
        else:
            models.append(base)

    return _dedupe_preserving_order(models)


def _models_from_config() -> List[str]:
    """Extract model names from Codex config files as a fallback."""

    candidates: List[Path] = []
    errors: List[str] = []

    def _add_candidate(base: Optional[str]) -> None:
        if not base:
            return
        resolved = Path(base).expanduser() / "config.toml"
        if resolved not in candidates:
            candidates.append(resolved)

    _add_candidate(settings.codex_config_dir)
    _add_candidate(os.environ.get("CODEX_HOME"))
    _add_candidate(str(Path.home() / ".codex"))

    for config_path in candidates:
        try:
            with open(config_path, "rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            errors.append(f"{config_path}: {exc}")
            logger.warning("Unable to read Codex config '%s': %s", config_path, exc)
            continue
        except Exception as exc:
            errors.append(f"{config_path}: {exc}")
            logger.warning("Failed to parse Codex config '%s': %s", config_path, exc)
            continue

        models = _models_from_config_data(data)
        if models:
            return models

    if errors:
        logger.debug("Skipped Codex config models because: %s", "; ".join(errors))
    return []


def _models_from_config_data(data: Dict[str, Any]) -> List[str]:
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


def _classify_codex_failure(stdout_text: str, stderr_text: str) -> Tuple[str, Optional[int]]:
    """Derive a human-readable error message and optional HTTP status code."""

    def _collect_lines(text: str) -> List[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    lines: List[str] = []
    if stderr_text:
        lines.extend(_collect_lines(stderr_text))
    if stdout_text:
        lines.extend(_collect_lines(stdout_text))

    message = None
    for line in reversed(lines):
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                error_obj = data.get("error")
                if isinstance(error_obj, dict):
                    error_message = error_obj.get("message")
                    if isinstance(error_message, str) and error_message.strip():
                        message = error_message.strip()
                        break
                msg = data.get("message")
                if isinstance(msg, str) and msg.strip():
                    message = msg.strip()
                    break
        lowered = line.lower()
        if lowered.startswith("error:") or "unauthorized" in lowered or "rate limit" in lowered:
            message = line
            break
    if message is None:
        message = lines[-1] if lines else "codex execution failed"

    lower_msg = message.lower()
    status_code = None
    if "401" in message or "unauthorized" in lower_msg:
        status_code = 401
    elif "429" in message or "rate limit" in lower_msg:
        status_code = 429
    elif "timeout" in lower_msg:
        status_code = 504

    return message, status_code


async def run_codex(
    prompt: str,
    overrides: Optional[Dict] = None,
    images: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> AsyncIterator[str]:
    """Run codex CLI as async generator yielding stdout lines suitable for SSE."""
    cmd, prompt_text = _build_cmd_and_env(prompt, overrides, images, model)
    codex_env = _build_codex_env()
    output_filter = _CodexOutputFilter()

    async with _parallel_limiter.slot():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=settings.codex_workdir,
                env=codex_env,
                limit=_ASYNCIO_STREAM_LIMIT,
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

        # Feed the prompt via stdin to avoid OS arg-length limits.
        proc.stdin.write(prompt_text.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        raw_lines: List[str] = []
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors="ignore")
                raw_lines.append(decoded)
                filtered = output_filter.process(decoded.rstrip("\n"))
                if filtered:
                    yield filtered
            await asyncio.wait_for(proc.wait(), timeout=settings.timeout_seconds)
            if proc.returncode != 0:
                stderr_text = (await proc.stderr.read()).decode(errors="ignore")
                stdout_text = "".join(raw_lines)
                message, status = _classify_codex_failure(stdout_text, stderr_text)
                raise CodexError(message, status_code=status)
        except asyncio.TimeoutError:
            proc.kill()
            raise CodexError("codex execution timed out", status_code=504)
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
    cmd, prompt_text = _build_cmd_and_env(prompt, overrides, images, model)
    # Create temp file in workdir to ensure permissions
    _ensure_workdir_exists()
    codex_env = _build_codex_env()
    with tempfile.NamedTemporaryFile(prefix="codex-last-", suffix=".txt", dir=settings.codex_workdir, delete=False) as tf:
        out_path = tf.name
    cmd = cmd + ["--json", "--output-last-message", out_path]
    try:
        async with _parallel_limiter.slot():
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=settings.codex_workdir,
                env=codex_env,
                limit=_ASYNCIO_STREAM_LIMIT,
            )
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(input=prompt_text.encode()), timeout=settings.timeout_seconds
            )
        if proc.returncode != 0:
            stdout_text = (stdout_data or b"").decode(errors="ignore")
            stderr_text = (stderr_data or b"").decode(errors="ignore")
            message, status = _classify_codex_failure(stdout_text, stderr_text)
            raise CodexError(message, status_code=status)
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
        raise CodexError("codex execution timed out", status_code=504)
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass
