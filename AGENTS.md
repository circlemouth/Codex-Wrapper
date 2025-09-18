# Repository Guidelines

## Language
- 以降、このリポジトリでのアシスタントからの返答は日本語で行うこと。

## Project Structure & Module Organization
- `app/` holds the FastAPI service: `main.py` exposes `/v1/chat/completions` and `/v1/responses`, `codex.py` shells out to the Codex CLI, and sibling modules handle config, schemas, and security gates.
- `docs/` contains bilingual product docs plus English-only references such as `ENV.md` and API plans; keep translations in sync per `CONTRIBUTING.md`.
- `submodules/codex` tracks the upstream Codex CLI; run `git submodule update --init --recursive` after cloning.
- `workspace/` is a scratch area for manual experiments (e.g., `test_filter.py`); treat anything promoted from here as real tests before merging.

## Build, Test, and Development Commands
- `python3 -m venv .venv && source .venv/bin/activate` ensures isolation for Python deps.
- `pip install -r requirements.txt` installs FastAPI, uvicorn, and supporting libraries.
- `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` runs the wrapper locally with auto-reload.
- `pytest` executes unit tests; add targeted suites under `tests/` (preferred) or migrate scripts from `workspace/`.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and snake_case for functions, PascalCase for Pydantic models.
- Keep async boundaries explicit—prefer async FastAPI endpoints delegating to helpers in `app.codex`.
- Add type hints and short docstrings where behavior is security-sensitive (e.g., sandbox enforcement).
- Use `black` or an equivalent formatter before committing; avoid mixing style-only changes with feature work.

## Testing Guidelines
- Write pytest cases that cover both streaming and non-streaming flows in `app.main`; mock Codex CLI responses to avoid external calls.
- Name tests `test_<feature>.py` and fixtures `<scope>_<name>` for clarity.
- Include regression tests when altering request parsing, prompt assembly, or sandbox validation—these areas gate user safety.

## Commit & Pull Request Guidelines
- Use concise, imperative commit messages; history favors prefixes like `feat:`, `docs:`, and maintenance notes.
- Update English and Japanese docs together unless editing an explicitly single-language file; copy the PR checklist from `CONTRIBUTING.md`.
- PRs should describe the scenario, local testing (include `pytest` / manual uvicorn runs), and note configuration impacts (e.g., `CODEX_ALLOW_DANGER_FULL_ACCESS`).

## Security & Configuration Tips
- Keep `.env` secrets out of version control and document new variables in `docs/ENV.md`.
- If changes touch sandboxing (`CODEX_ALLOW_DANGER_FULL_ACCESS`, `CODEX_LOCAL_ONLY`), call out risks and default behaviors in the PR description.
- When extending Codex CLI integration, verify `~/.codex/config.toml` compatibility and add migration notes if defaults shift.
