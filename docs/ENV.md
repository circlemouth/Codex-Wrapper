# Environment Configuration (.env and OS env)

This project loads configuration via environment variables. It supports a `.env` file (using `pydantic-settings`) and OS‑level environment variables. This document is the authoritative reference for how to configure the server. It is intentionally English‑only and should be linked from both English and Japanese READMEs.

## Files and Precedence

- Default file: `.env` at the repository root.
- Override file: set `CODEX_ENV_FILE` as an OS env var before starting the server to load a different file (e.g., `.env.local`). Do not set `CODEX_ENV_FILE` inside `.env`.
- OS env variables take precedence over values from the loaded file.

## Critical Variables

- `PROXY_API_KEY`: Bearer token required by this proxy (optional if you run without auth).
- `RATE_LIMIT_PER_MINUTE`: Requests per minute allowed per client. `0` disables limiting.
- `CODEX_PATH`: Path to `codex` binary (default: `codex`).
- `CODEX_WORKDIR`: Working directory for Codex runs (server enforces `cwd` to this path).
  - Codex はこのディレクトリ階層で `AGENTS.md` を探索します。ラッパー API 特有の指示を適用したい場合は、ここ（または配下のサブディレクトリ）に `AGENTS.md` を配置してください。
- `CODEX_CONFIG_DIR`: Optional directory to use as the Codex CLI home for this wrapper. When set, the server exports `CODEX_HOME` for subprocesses and guarantees the folder exists. Place your API-specific `config.toml` here.
  - API 専用の `config.toml` や MCP 設定を分離したい場合に利用します（CLI を直接使う環境と分けられます）。
- `CODEX_SANDBOX_MODE`: `read-only` | `workspace-write` | `danger-full-access`.
- `CODEX_REASONING_EFFORT`: `minimal` | `low` | `medium` | `high`.
- `CODEX_LOCAL_ONLY`: `0`/`1`. When `1`, the server rejects non‑local provider base URLs.
- `CODEX_ALLOW_DANGER_FULL_ACCESS`: `0`/`1`. When `1`, the API may request `x_codex.sandbox=danger-full-access`.
- `CODEX_TIMEOUT`: Server‑side timeout for Codex runs (seconds; default 120).
- `CODEX_ENV_FILE`: Name of the env file to load (set as an OS env var).

### Model Selection

- The server now discovers available models by invoking the Codex CLI (`codex models list`) during startup.
- Whatever names Codex reports are exposed through `GET /v1/models`, and clients must use those exact names in the `model` field when calling the API.
- Append ` minimal` / ` low` / ` medium` / ` high` to a model name to override the reasoning effort without using `x_codex.reasoning_effort`.
- The legacy `CODEX_MODEL` environment variable is ignored. If it is present the server logs a warning so you can remove it from your configuration.

## Codex CLI Credentials and Providers

- Codex auth is managed by the CLI itself with `codex login`.
- Credentials are stored at `$CODEX_HOME/auth.json` (default `~/.codex/auth.json`). To relocate, set the OS env var `CODEX_HOME`. Do not put `CODEX_HOME` inside `.env`.
- For OpenAI API‑key mode, Codex CLI reads `OPENAI_API_KEY` (this is consumed by Codex, not this proxy). OAuth mode does not require it.

## Local‑Only Enforcement

When `CODEX_LOCAL_ONLY=1`:
- The server inspects `$CODEX_HOME/config.toml` `model_providers` and the built‑in OpenAI provider `OPENAI_BASE_URL`.
- Any provider with a non‑local `base_url` (not localhost/127.0.0.1/[::1]/unix) is rejected with HTTP 400.

## Danger Mode

To allow full file/network access:
1. Set `CODEX_ALLOW_DANGER_FULL_ACCESS=1` before starting the server.
2. Send `x_codex.sandbox: "danger-full-access"` in the API request.

Both are required. If `CODEX_LOCAL_ONLY=1`, the provider `base_url` must also be local.

## Example `.env.example`

See the repository’s `.env.example` for a starter template. Copy it to `.env` and adjust as needed.
