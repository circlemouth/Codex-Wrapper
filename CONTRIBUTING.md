# Contributing

Thanks for contributing to Codex-Wrapper! This repository maintains bilingual user docs (English and Japanese) and an English‑only agents guide. Please follow these rules to keep documentation consistent.

## Doc Language Policy

- User docs are maintained in two languages with mirrored content, except noted below:
  - English files end with `.en.md` (except the root `README.md`)
  - Japanese files end with `.ja.md`
- The agents guide is English‑only: `docs/AGENTS.md`.
- Environment configuration docs are English‑only: `docs/ENV.md`.
- Implementation Plan and Responses API Plan are Japanese‑only: `docs/IMPLEMENTATION_PLAN.ja.md`, `docs/RESPONSES_API_PLAN.ja.md`.

## Content Parity Rules

- Update both English and Japanese documents in the same PR whenever the content changes (except the two Japanese‑only docs listed above).
- Cross‑link the pair (e.g., add links between `README.md` and `README.ja.md`, or between `*.en.md` and `*.ja.md`).
- If you add a new doc, create both `*.en.md` and `*.ja.md` siblings under `docs/` (unless you are extending one of the Japanese‑only docs).
- Keep titles, section order, and examples aligned across languages. If an example is locale‑specific, note it explicitly in both versions.
- Small wording fixes in one language still require parity (make an equivalent adjustment in the other language or open a follow‑up issue tagged `docs:parity`).

## Recommended Workflow

1) Author changes in English first, get technical approval.
2) Port to Japanese in the same PR.
3) Verify cross‑links and file names.
4) Run a quick diff on sections to ensure order and coverage match.

## PR Checklist (copy into your PR description)

- [ ] Updated English doc(s)
- [ ] Updated Japanese doc(s)
- [ ] Cross‑links between language versions (`README.md`/`README.ja.md` or `*.en.md`/`*.ja.md`)
- [ ] Agents guide unaffected or updated (`docs/AGENTS.md` is English‑only)
- [ ] ENV doc referenced where appropriate (`docs/ENV.md`)
- [ ] Local build/run sanity checked if instructions changed

## Style

- Keep headings and code fences consistent.
- Use backticks for commands, file paths, env vars, and code identifiers.
- Prefer concise, actionable steps over long prose.

## Development

- Python: use a virtual environment (`venv`) and install from `requirements.txt`.
- Start the server: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Submodule updates: `git submodule update --init --recursive` and `git submodule update --remote submodules/codex` as needed.

## Reporting Issues

- Use GitHub Issues with clear repro steps, expected vs actual behavior, and logs if relevant.
- Tag documentation issues that need translation with `docs:parity`.
