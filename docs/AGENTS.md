# Agents Guide (Codex-Wrapper)

This server wraps the Codex CLI with FastAPI and exposes a minimal OpenAI‑compatible API. You can use existing OpenAI clients (Python/JS, etc.) by switching `base_url`.

Important: Always install Python libraries inside a virtual environment (venv).

## Basics

- Base URL: `http://<host>:8000/v1`
- Auth: `Authorization: Bearer <PROXY_API_KEY>` (you may run without it if configured that way)
- Model IDs: discovered at startup by running `codex models list`. Call `GET /v1/models` to inspect the exact names your Codex CLI reports.
  - When the CLI only exposes deployments/variants (e.g. `{"id": "gpt-5", "deployment": "codex"}`), the wrapper expands them into aliases such as `gpt-5-codex` so existing clients continue to work.
  - You can append ` minimal` / ` low` / ` medium` / ` high` to those model IDs to set the reasoning effort (for example: `gpt-5-codex high`).
- Submodule: Codex reference lives in `submodules/codex`
- Supported APIs: `/v1/chat/completions` and minimal `/v1/responses` (see `docs/RESPONSES_API_PLAN.ja.md` – Japanese)

## Codex Authentication (OAuth or API key)

- Pattern A: OAuth (ChatGPT sign‑in)
  - Run: `codex login` as the same OS user as the server process
  - Result: credentials saved to `$CODEX_HOME/auth.json` (default `~/.codex/auth.json`)
  - Headless: SSH port‑forward (`ssh -L 1455:localhost:1455 <user>@<host>`) then open the printed URL locally, or copy `auth.json` from a local login to the server
  - `OPENAI_API_KEY`: not required

- Pattern B: API key (metered alternative)
  - Run: `codex login --api-key "<YOUR_OPENAI_API_KEY>"`
  - Requires: an OpenAI API key with Responses API access
  - Note: With `CODEX_LOCAL_ONLY=1`, remote provider `base_url`s (e.g., OpenAI) are rejected; typically keep `CODEX_LOCAL_ONLY=0` for API‑key usage.

Notes
- Set `CODEX_HOME` as an OS env var (not in `.env`). This wrapper consumes the `auth.json` stored by Codex CLI.
- `PROXY_API_KEY` controls access to THIS wrapper API and is independent of Codex login.

## Supported APIs

- `GET /v1/models`
  - Example: `{ "data": [{ "id": "o4-mini" }, { "id": "gpt-4.1" }] }`
- `POST /v1/chat/completions`
  - Input (subset)
    - `model`: optional; defaults to the first model reported by Codex at startup
  - `messages`: OpenAI format (`system`/`user`/`assistant`). User messages may include `input_image` parts.
    - `stream`: `true` for SSE streaming
    - `temperature`, `max_tokens`: accepted but ignored for the initial version
  - Output (non‑stream)
    - `choices[0].message.content` holds the final text
    - `usage` is 0 for now
  - Output (stream / SSE)
    - `Content-Type: text/event-stream`
    - Lines as `data: {chunk}`, end with `data: [DONE]`
    - JSON lines are preferred; we emit their `text`/`content` as `choices[0].delta.content`. Non‑JSON lines are concatenated as text fallback.

## Examples (Python / OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY",  # if required
)

# Non-stream (replace with a name from GET /v1/models, e.g. "o4-mini")
resp = client.chat.completions.create(
    model="o4-mini",
    messages=[
        {"role": "system", "content": "You are a helpful coding agent."},
        {"role": "user", "content": "Say hello and exit."},
    ],
)
print(resp.choices[0].message.content)

# Image input
resp = client.chat.completions.create(
    model="o4-mini",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Describe this image"},
                {"type": "input_image", "image_url": {"url": "https://example.com/cat.png"}},
            ],
        }
    ],
)
print(resp.choices[0].message.content)

# Stream (SSE)
with client.chat.completions.create(
    model="o4-mini",
    messages=[{"role": "user", "content": "Write 'hello'"}],
    stream=True,
) as stream:
    for event in stream:
        if event.type == "chunk":
            delta = event.data.choices[0].delta
            if delta and delta.content:
                print(delta.content, end="", flush=True)
```

## Examples (Responses API)

Non‑stream
```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="YOUR_PROXY_API_KEY")
resp = client.responses.create(model="o4-mini", input="Say hello")
print(resp.output[0].content[0].text)
```

Stream (SSE)
```bash
curl -N \
  -H "Authorization: Bearer $PROXY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"o4-mini","input":"Say hello","stream":true}' \
  http://localhost:8000/v1/responses
```

Minimal SSE events
- `response.created` → initial state (`status=in_progress`)
- `response.output_text.delta` → incremental text `{ "delta": "..." }`
- `response.output_text.done` → final text `{ "text": "..." }`
- `response.completed` → final object
- On error: `response.error`, then `[DONE]`

## Example (curl / SSE)

```bash
curl -N \
  -H "Authorization: Bearer $PROXY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "model":"codex-cli",
        "stream":true,
        "messages":[{"role":"user","content":"Say hello"}]
      }' \
  http://localhost:8000/v1/chat/completions
```

## Error format

- Standard FastAPI JSON: `{ "detail": { ... } }`

```json
{"detail": {"message": "...", "type": "server_error", "code": null}}
```

- Timeouts result in HTTP 500.

## Execution and safety

- Codex invocation: `codex exec <PROMPT> -q [--model <...>]`
- CWD is restricted to `CODEX_WORKDIR` (run the server as a non‑root user)
- Rate limiting/CORS are handled at the API layer (configurable)

## Settings (Environment Variables)

- `PROXY_API_KEY`: auth for this proxy (optional)
- `CODEX_WORKDIR`: working directory for Codex runs
- `CODEX_MODEL`: **deprecated**. Startup now queries available models automatically; setting this variable has no effect other than a warning.
- `CODEX_PATH`: override path to `codex` binary
- `CODEX_SANDBOX_MODE`: `read-only` / `workspace-write` / `danger-full-access`
- `CODEX_REASONING_EFFORT`: `minimal` / `low` / `medium` / `high`
- `CODEX_LOCAL_ONLY`: `0/1` (default 0). If 1, reject non‑local base URLs
- `CODEX_ALLOW_DANGER_FULL_ACCESS`: allow `sandbox=danger-full-access` when `1`
- `CODEX_TIMEOUT`: timeout seconds for Codex (default 120)
- `RATE_LIMIT_PER_MINUTE`: allowed requests per minute (default 60)
- `CODEX_ENV_FILE`: path to `.env` to load (set as OS env var before start)

Server defaults may be overridden per‑request via the `x_codex` vendor extension; omitted fields fall back to server defaults.

## Modes (Local‑first design)

We assume a local‑only posture by default. Codex sandbox/approval and reasoning effort are mapped as follows:

- Local‑only means model provider `base_url` should be local (e.g., `http://localhost:11434/v1`). External cloud base URLs are disallowed when `CODEX_LOCAL_ONLY=1`.
- Network access for command execution is blocked by default (even in `workspace-write`). Allow only when explicitly configured.

### Agent privileges (sandbox)

- Safe (default): `sandbox=read-only`
  - Read‑only; writes and network are blocked.
- Edit allowed (recommended): `sandbox=workspace-write` (network `false`)
  - Enables workspace edits and command execution; network remains blocked.
- Full access (explicitly allowed only): `sandbox=danger-full-access`
  - Full file/network access. Disabled by default; set `CODEX_ALLOW_DANGER_FULL_ACCESS=1` to allow.

CLI equivalents

```bash
# Safe (default)
codex exec "..." -q \
  --config sandbox_mode='read-only'

# Edit allowed
codex exec "..." -q \
  --config sandbox_mode='workspace-write' \
  --config sandbox_workspace_write='{ network_access = false }'

# Danger mode (explicit)
codex exec "..." -q \
  --config sandbox_mode='danger-full-access'
```

### Reasoning Effort

Control Codex `model_reasoning_effort` (`minimal`/`low`/`medium`/`high`).

- Default: `medium`
- Guide:
  - `high`: big refactors, multi‑file consistency, ambiguous requirements
  - `medium`: routine implementation and fixes
  - `low/minimal`: small mechanical edits, command‑centric tasks

CLI example

```bash
codex exec "..." -q --config model_reasoning_effort='high'
```

### Server enforcement (Local‑Only)

- With `CODEX_LOCAL_ONLY=1`, non‑local provider base URLs are rejected (anything other than localhost/127.0.0.1/[::1]/unix).
  - The server inspects `$CODEX_HOME/config.toml` `model_providers` and the built‑in `openai` `OPENAI_BASE_URL`.
- Default is `CODEX_LOCAL_ONLY=0` (recommended for OpenAI default provider usage).
- Keep cloud keys like `OPENAI_API_KEY` unset unless needed; with `CODEX_LOCAL_ONLY=1` they are unused anyway.
- For local providers (e.g., `ollama`) you can pass configs with `--config`.

Example (force local Ollama)

```bash
codex exec "..." -q \
  --config model_provider='ollama' \
  --config model='llama3.1' \
  --config model_providers.ollama='{ name = "Ollama", base_url = "http://localhost:11434/v1" }' \
  --config sandbox_mode='workspace-write' \
  --config sandbox_workspace_write='{ network_access = false }' \
  --config model_reasoning_effort='medium'
```

### Vendor extension from API (`x_codex`)

To remain OpenAI‑compatible, we accept an optional `x_codex` field. Omitted fields fall back to server defaults.

```json
{
  "model": "codex-cli",
  "messages": [ { "role": "user", "content": "..." } ],
  "x_codex": {
    "sandbox": "workspace-write",           
    "reasoning_effort": "high",             
    "network_access": false                  
  }
}
```

The server maps these to Codex CLI `--config`. With `CODEX_LOCAL_ONLY=1`, non‑local base URLs are rejected; `danger-full-access` is allowed only when `CODEX_ALLOW_DANGER_FULL_ACCESS=1`.

## Submodule workflow

- Location: `submodules/codex` (https://github.com/openai/codex.git)
- First checkout: `git submodule update --init --recursive`
- Update to latest:

```bash
git submodule update --remote submodules/codex
# Commit as needed in the parent repo
```

## Limitations (initial)

 - No tool/function calling; no audio
- No strict token accounting; parallelism is capped by `CODEX_MAX_PARALLEL_REQUESTS` (default 2)
- CLI output format can evolve; we parse both JSON and text to remain resilient

## Troubleshooting

- 401: check `PROXY_API_KEY` and request headers
- 500 (incl. timeout): Codex run took too long; simplify prompt or raise timeout
- 429: rate limit reached; adjust `RATE_LIMIT_PER_MINUTE`
- Extra CLI banner or `MCP client for ... failed to start` in output:
  - Non‑stream uses `codex exec --json --output-last-message` to keep output clean.
  - Stream now forwards Codex CLI output verbatim; expect banners/warnings unless you trim them in your Codex profile or CLI config.
  - Root fix: remove/comment `mcp_servers` in `~/.codex/config.toml` to avoid timeouts from unconfigured servers.

## Codex TOML config

- Location: `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`)
- Example: copy `docs/examples/codex-config.example.toml`

```bash
mkdir -p ~/.codex
cp docs/examples/codex-config.example.toml ~/.codex/config.toml
```

- For OpenAI in API‑key mode set `OPENAI_API_KEY` (OAuth mode does not need it).
- Enable web search via `tools.web_search = true` in `config.toml`.
- Define MCP servers under `mcp_servers.<id>` (stdio).
- API 専用の設定を分離したい場合は `.env` に `CODEX_CONFIG_DIR` を設定します。Codex ランタイムはこの値を `CODEX_HOME` として扱い、`config.toml` や MCP 定義をラッパー専用にできます。

## AGENTS templates

- Example: copy `docs/examples/AGENTS.example.md` to the desired location for Codex (global or repository).

```bash
# Global defaults
cp docs/examples/AGENTS.example.md ~/.codex/AGENTS.md

# Repository-specific guidance
cp docs/examples/AGENTS.example.md AGENTS.md
```

Update the copied file with your project-specific notes. Codex reads AGENTS.md files at the root of the working directory tree when executing requests from this API.

## Wrapper bootstrap directory (agent/config overrides)

- The repository ships a managed profile directory: `workspace/codex_profile/`.
  - `codex_agents.sample.md` / `codex_config.sample.toml` act as templates. Rename or copy them to `codex_agents.md` / `codex_config.toml` to activate overrides.
  - During server startup the wrapper copies those files (if present) into the Codex home (`AGENTS.md` / `config.toml`).
  - 片方だけ配置した場合は存在するファイルのみがコピーされます。
- Legacy filenames (`agent.md`, `config.toml`) continue to work but trigger a startup warning so you can migrate at your own pace.
- Set `CODEX_WRAPPER_PROFILE_DIR` if you want to store these overrides elsewhere. The path should contain the new filenames (`codex_agents.md`, `codex_config.toml`).
