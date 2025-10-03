# Docker Deployment

This repository now ships a `Dockerfile` that bundles the FastAPI wrapper together with the Codex CLI. The image installs the published Codex binary during build time and copies the repository (including the `submodules/codex` checkout) so you can inspect upstream documentation from inside the container.

> **Prerequisite:** Make sure the Codex submodule is populated before building.
>
> ```bash
> git submodule update --init --recursive
> ```

## Building the image

```bash
docker build -t codex-wrapper .
```

The build uses `TARGETOS`/`TARGETARCH` arguments supplied by Docker BuildKit to download the correct Codex binary. Linux `amd64` and `arm64` are supported. You can override the Codex release by passing `--build-arg CODEX_VERSION=vX.Y.Z`; the default `latest` tracks the newest GitHub release.

## Runtime layout

- Default working directory for Codex runs: `/workspace` (configurable via `CODEX_WORKDIR`).
- Codex CLI home: `/home/appuser/.codex`. Mount this path to persist `auth.json`, `config.toml`, and MCP settings.
- The API listens on port `8000` with `uvicorn app.main:app`.

To retain credentials and give Codex a writable sandbox, mount volumes when you start the container:

```bash
docker run \
  --rm \
  -p 8000:8000 \
  -v "$PWD/workspace-data:/workspace" \
  -v "$HOME/.codex:/home/appuser/.codex" \
  --env-file ./.env \
  codex-wrapper
```

Environment variables follow the definitions in [`docs/ENV.md`](./ENV.md). For example, set `PROXY_API_KEY`, `CODEX_LOCAL_ONLY`, or `CODEX_ALLOW_DANGER_FULL_ACCESS` as needed. You may also export `CODEX_HOME` if you prefer a different location for Codex state.

## Verifying Codex inside the container

After launching the container you can open a shell and confirm the CLI works:

```bash
docker exec -it <container-id> codex --help
```

This prints the Codex CLI usage banner from the downloaded release.

## Updating the image

- Rebuild the image whenever the upstream Codex CLI changes or when you pull new wrapper updates.
- If you maintain your own fork, keep the `submodules/codex` directory updated so developers can read the bundled upstream documentation even when offline.
