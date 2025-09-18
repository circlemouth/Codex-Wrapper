# Codex AGENTS example

This template shows how to share project guidance with the Codex CLI. Copy it to one of the supported locations and edit the bullets to match your workflow.

## Copy targets
- `~/.codex/AGENTS.md` for global defaults (recommended)
- `<repo>/AGENTS.md` for repository-wide guidance
- `<repo>/<subdir>/AGENTS.md` for folder-specific rules

## Sample guidance
- Summaries go first. Start replies with a terse overview before details.
- Prefer tests in `tests/` and name them `test_<feature>.py`.
- Never commit secrets. Use `.env` and document new variables in `docs/ENV.md`.
- When unsure about requirements, ask for clarification before coding.

## Housekeeping
- Keep instructions short and scoped. Delete sections that do not apply.
- Update this document whenever workflow expectations change.
