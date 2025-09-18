# Codex-Wrapper

FastAPI server that wraps Codex CLI behind a minimal OpenAI‑compatible API. It exposes `/v1/chat/completions` and `/v1/models` and supports SSE streaming.

For Japanese instructions, see [README.ja.md](./README.ja.md).

- Reference submodule: `submodules/codex` (https://github.com/openai/codex.git)
- Implementation plan: `docs/IMPLEMENTATION_PLAN.ja.md` (Japanese)
- Agent guide: `docs/AGENTS.md` (English)
- Responses API plan/progress: `docs/RESPONSES_API_PLAN.ja.md` (Japanese)
- Environment configuration: `docs/ENV.md` (English)

> Documentation languages: English and Japanese. Exceptions: Implementation Plan and Responses API Plan are maintained in Japanese only. See `CONTRIBUTING.md` for the doc sync policy.

## Quick Start

1) Dependencies

```bash
pip install -r requirements.txt
```

2) Install Codex CLI (pick one)

```bash
npm i -g @openai/codex
# or
brew install codex
```

3) Sign in to Codex (OAuth or API key)

Authentication happens in the Codex CLI, not in this API wrapper.

Pattern A: OAuth (ChatGPT sign‑in)

```bash
# Run as the same OS user that runs this API server
codex login
```

- After browser sign‑in, credentials are saved to `$CODEX_HOME/auth.json` (default `~/.codex/auth.json`).
- Headless/remote notes:
  - SSH port‑forward: `ssh -L 1455:localhost:1455 <user>@<host>` → run `codex login` on the remote → open the printed URL in your local browser.
  - Or log in locally and copy `auth.json` to the server: `scp ~/.codex/auth.json user@host:~/.codex/auth.json`.

Pattern B: API key (metered, alternative)

```bash
codex login --api-key "<YOUR_OPENAI_API_KEY>"
```

- Use an OpenAI API key that has access to the Responses API.
- If the server runs with `CODEX_LOCAL_ONLY=1`, the built‑in OpenAI provider’s remote `base_url` will be rejected (400). For API‑key usage, keep `CODEX_LOCAL_ONLY=0` in most cases.

Common notes
- You can relocate `auth.json` by setting the OS environment variable `CODEX_HOME` (for example: `/opt/codex`). Configure this as an OS env var, not inside `.env`.
- If you switch auth modes, consider recreating `~/.codex/auth.json` by running `codex login` again.

4) Configure Codex (example using OpenAI gpt‑5)

```bash
mkdir -p ~/.codex
cp docs/examples/codex-config.example.toml ~/.codex/config.toml
```

To use OpenAI’s gpt‑5 model (when using API‑key mode), configure the Codex CLI with the appropriate provider credentials. This wrapper now queries the CLI for available models at startup, so call `GET /v1/models` to discover the names you can use. For OAuth, `OPENAI_API_KEY` is not required.

4b) Optional: Repository guidance for Codex

```bash
# Copy the AGENTS template for repository-wide instructions
cp docs/examples/AGENTS.example.md AGENTS.md

# Or set wrapper-specific guidance inside the Codex workdir
cp docs/examples/AGENTS.example.md $CODEX_WORKDIR/AGENTS.md
```

With `CODEX_WORKDIR` set (default `/workspace`), Codex merges any `AGENTS.md` files under that directory hierarchy when the wrapper executes requests.

5) Environment Variables (.env supported)

This server automatically loads `.env` using `pydantic-settings`. See `docs/ENV.md` for complete details.

```bash
cp .env.example .env
# Edit .env with your favorite editor
```

If you want to override values ad‑hoc in the shell, you can still use `export`.

Advanced: if you prefer a file other than `.env`, set `CODEX_ENV_FILE` as an OS environment variable before starting the server (set it in the shell, not inside `.env`).

```bash
export CODEX_ENV_FILE=.env.local
```

6) Run the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

7) Connect from an SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="YOUR_PROXY_API_KEY")
```

See `docs/IMPLEMENTATION_PLAN.ja.md` (Japanese) and `docs/AGENTS.md` for details. Minimal Responses API compatibility (non‑stream/stream) is implemented; see `docs/RESPONSES_API_PLAN.ja.md` (Japanese) for details and future work.

## Environment Variables (Authoritative)

This server reads `.env` and uses the following variables. Example values and constraints follow the current Codex submodule docs (`submodules/codex`).

- PROXY_API_KEY: API token for this wrapper. If unset, the server can run without auth.
- RATE_LIMIT_PER_MINUTE: Allowed requests per minute. 0 disables limiting.
- CODEX_PATH: Path to the `codex` binary. Default `codex`.
- CODEX_WORKDIR: Working directory for Codex executions (`cwd`). Default `/workspace`.
  - Ensure this directory is writable by the server user; otherwise Codex fails with `Failed to create CODEX_WORKDIR ... Read-only file system`.
  - Codex merges any `AGENTS.md` files under this directory tree when the wrapper runs requests; copy `docs/examples/AGENTS.example.md` here (or deeper) to provide project instructions.
- CODEX_CONFIG_DIR: Optional directory treated as `CODEX_HOME` for this wrapper. When set, the server creates it if missing and runs Codex CLI with that directory as its config root; place wrapper-specific `config.toml`, `auth.json`, or MCP settings here.
- CODEX_MODEL: **Deprecated.** Model selection is automatic; setting this variable has no effect (a warning is logged if present).
  - Note: The string is free‑form, but it must be a model name supported by the selected `model_provider` (OpenAI by default).
- CODEX_SANDBOX_MODE: Sandbox mode. One of: `read-only` | `workspace-write` | `danger-full-access`.
  - For `workspace-write`, the wrapper adds `--config sandbox_workspace_write='{ network_access = <true|false> }'` when the API request specifies `x_codex.network_access`.
- CODEX_REASONING_EFFORT: Reasoning effort. One of: `minimal` | `low` | `medium` | `high` (default `medium`).
- CODEX_LOCAL_ONLY: `0`/`1`. Default `0` (recommended).
  - If `1`, any non‑local model provider `base_url` (not localhost/127.0.0.1/[::1]/unix) is rejected with 400.
  - The server checks `$CODEX_HOME/config.toml` `model_providers` and the built‑in `openai` provider’s `OPENAI_BASE_URL`. Unknown/missing settings are rejected conservatively.
- CODEX_ALLOW_DANGER_FULL_ACCESS: `0`/`1` (default `0`). When `1`, the API may request `x_codex.sandbox: "danger-full-access"`.
  - Safety note: Only set `1` inside isolated containers/VMs.
- CODEX_TIMEOUT: Server‑side timeout (seconds) for Codex runs (default 120).
- CODEX_ENV_FILE: Path to the `.env` file to load. Must be set as an OS env var before the server starts (do not place this inside `.env`). Defaults to `.env`.

Auth notes
- Both OAuth (ChatGPT) and API‑key modes are handled by Codex CLI. Run `codex login` as the same OS user as the server process.
- `auth.json` location is `$CODEX_HOME` (default `~/.codex`). If you move it, set `CODEX_HOME` as an OS env var (not in `.env`).
- `PROXY_API_KEY` controls access to this wrapper; it is unrelated to Codex OAuth.
- ChatGPT login does not require `OPENAI_API_KEY`; API‑key usage does.
- With `CODEX_LOCAL_ONLY=1`, remote `base_url`s (like OpenAI) are rejected; be mindful when using API‑key mode.

Codex highlights
- model: The Codex CLI currently surfaces `gpt-5` and `gpt-5-codex` for this account (verified 2025-09-17 via `GET /v1/models`). Append ` minimal` / ` low` / ` medium` / ` high` to request a specific reasoning effort (e.g. `gpt-5-codex high`).
- sandbox_mode: Supports `read-only` (default) / `workspace-write` / `danger-full-access`. For `workspace-write`, `sandbox_workspace_write.network_access` (default false) can be tuned.
- model_reasoning_effort: `minimal`/`low`/`medium`/`high`.

Provider‑specific env vars
- With the OpenAI provider in API‑key mode, Codex CLI reads `OPENAI_API_KEY`. This belongs to Codex, not this wrapper (OAuth mode does not require it).
- For custom providers or local inference (e.g., `ollama`), edit `~/.codex/config.toml` `model_providers` to set `base_url`, etc.

See `.env.example` for a template.

### Danger Mode and Local‑Only

1) Set `CODEX_ALLOW_DANGER_FULL_ACCESS=1` and start the server.
2) In a request, set `x_codex.sandbox: "danger-full-access"`.

Both must hold to allow danger mode:
- Server has `CODEX_ALLOW_DANGER_FULL_ACCESS=1`.
- Additionally, if `CODEX_LOCAL_ONLY=1` then provider `base_url` must be local.

If either condition fails, the server responds 400.

## Codex TOML Config (`config.toml`)

- Location: `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`).
- Example file: `docs/examples/codex-config.example.toml`.

```bash
mkdir -p ~/.codex
cp docs/examples/codex-config.example.toml ~/.codex/config.toml
```

- For OpenAI default provider with API‑key mode, set `OPENAI_API_KEY` (read by Codex CLI, not this wrapper).
- To enable web search, set `tools.web_search = true` in `config.toml` (disabled by default).
- Configure MCP servers under `mcp_servers` (stdio transport). See the example file.

### Multiple Codex Configs

You can run several wrapper instances, each backed by a different Codex configuration. Launch one process per backend, set a unique `CODEX_HOME` (this must be an OS env var, not inside `.env`), and keep ports/env files separate with `CODEX_ENV_FILE` when you need different `.env` content.

```bash
# Instance A (production)
CODEX_HOME=/opt/codex-prod CODEX_ENV_FILE=.env.prod uvicorn app.main:app --port 8000

# Instance B (staging)
CODEX_HOME=/opt/codex-stage CODEX_ENV_FILE=.env.stage uvicorn app.main:app --port 8001
```

Each directory specified by `CODEX_HOME` (e.g., `/opt/codex-prod`) should contain its own `config.toml` and optional `auth.json`, letting you serve multiple Codex backends side by side.

## Notes and Policy

- Do not share your personal ChatGPT/Codex account or resell access. This may violate OpenAI’s terms.
- To use safely:
  - Keep the server private for your own use.
  - For team usage, switch to a proper API setup and give each user their own key.
  - Use rate limiting, avoid key sharing, and manage logs responsibly.

## Caution

- This repository is an experimental project that was created quickly via “vibe coding.”
- Beyond the rough architecture, the author may not have full awareness of all implementation details.
- Before any production use or third‑party access, independently review the code, configuration, dependencies, and security posture.

## Language and Sync Policy

- All user‑facing docs are maintained in English and Japanese with equivalent content.
- AGENT documentation is English‑only by design (`docs/AGENTS.md`).
- The Environment Variables section is provided in English in both READMEs by policy.
- See `CONTRIBUTING.md` for required steps to keep both languages in sync.
