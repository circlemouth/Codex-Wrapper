# Codex-Wrapper

OpenAI 互換の最小 API で Codex CLI をラップする FastAPI サーバー。`/v1/chat/completions` と `/v1/models` を提供し、SSE ストリーミングをサポートします。

- 参考サブモジュール：`submodules/codex`（https://github.com/openai/codex.git）
- 実装計画：`docs/IMPLEMENTATION_PLAN.ja.md`（日本語のみ）
- エージェント向けガイド：`docs/AGENTS.md`（英語）
- Responses API 設計/進捗：`docs/RESPONSES_API_PLAN.ja.md`（日本語のみ）
- 環境設定: `docs/ENV.md`（英語）

> 言語ポリシー：ユーザー向けドキュメントは原則として英日両対応ですが、実装計画と Responses API 計画は日本語のみで管理します。運用ルールは `CONTRIBUTING.md` を参照してください。

[English](./README.en.md) | 日本語

## クイックスタート

1) 依存

```bash
pip install -r requirements.txt
```

2) Codex の導入（いずれか）

```bash
npm i -g @openai/codex
# または
brew install codex
```

3) Codex のログイン（選択: OAuth または API キー）

Codex CLI の認証は CLI 側で行います。API ラッパー側に特別な設定は不要です。

パターンA: OAuth（ChatGPT サインイン）

```bash
# サーバー（このAPIを起動するマシン）と同じOSユーザーで実行
codex login
```

- ブラウザでサインイン完了後、資格情報が `$CODEX_HOME/auth.json`（既定 `~/.codex/auth.json`）に保存されます。
- ヘッドレス/リモートの場合: 
  - SSHポートフォワード: `ssh -L 1455:localhost:1455 <user>@<host>` → リモートで `codex login` → 表示URLをローカルブラウザで開く。
  - ローカルでログインして `auth.json` をサーバーへコピー（`scp ~/.codex/auth.json user@host:~/.codex/auth.json`）。

パターンB: API キー（従量課金・代替手段）

```bash
codex login --api-key "<YOUR_OPENAI_API_KEY>"
```

- Responses API に書き込み権限のある OpenAI API キーを使用します。
- サーバーで `CODEX_LOCAL_ONLY=1` を有効にしている場合、組み込み OpenAI プロバイダのリモート `base_url` がブロックされ 400 になります。APIキー運用時は通常 `CODEX_LOCAL_ONLY=false` のままにしてください。

共通の注意:
- `auth.json` の位置は OS 環境変数 `CODEX_HOME` で変更可能（例: `/opt/codex`）。これは `.env` ではなく「OS環境変数」として設定します。
- 以前の認証方式から切り替える場合は `~/.codex/auth.json` の再作成（`codex login` 実行）を検討してください。

4) Codex の設定（OpenAI gpt-5 を使う例）

```bash
mkdir -p ~/.codex
cp docs/examples/codex-config.example.toml ~/.codex/config.toml
```

OpenAI の gpt-5 モデルを使うには、（APIキー運用時は）`OPENAI_API_KEY` を環境変数として設定し、`.env` などで `CODEX_MODEL=gpt-5` を指定します。OAuth運用時は `OPENAI_API_KEY` は必須ではありません。

5) 環境変数の設定（.env 対応）

このリポジトリは `.env` から環境変数を自動で読み込みます（`pydantic-settings`）。詳細は `docs/ENV.md` を参照してください（英語）。

```bash
cp .env.example .env
# 好みのエディタで .env を編集
```

ワンショットで上書きしたい場合は通常の `export` も併用できます。

高度な使い方: `.env` ではなく任意のファイルを使いたい場合は、サーバ起動前に
`CODEX_ENV_FILE` を OS の環境変数として設定してください（.env の中ではなく、
シェルで設定する必要があります）。

```bash
export CODEX_ENV_FILE=.env.local
```

6) サーバ起動

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

7) SDK から接続

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="YOUR_PROXY_API_KEY")
```

詳細は `docs/IMPLEMENTATION_PLAN.ja.md` と `docs/AGENTS.md`（英語）を参照してください。
Responses API 互換は最小実装済み（非ストリーム/ストリーム）。詳細と今後の拡張は `docs/RESPONSES_API_PLAN.ja.md` を参照。

## 環境変数（Authoritative / English）

以下のセクションは英語で記載します（英語版 README と同一内容）。

This server reads `.env` and uses the following variables. Example values and constraints follow the current Codex submodule docs (`submodules/codex`).

- PROXY_API_KEY: API token for this wrapper. If unset, the server can run without auth.
- RATE_LIMIT_PER_MINUTE: Allowed requests per minute. 0 disables limiting.
- CODEX_PATH: Path to the `codex` binary. Default `codex`.
- CODEX_WORKDIR: Working directory for Codex executions (`cwd`). Default `/workspace`.
- CODEX_MODEL: String passed as Codex `model`, e.g., `o3`, `o4-mini`, `gpt-5` (see `submodules/codex/docs/config.md`, “model”).
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
- model: Default is `gpt-5`. Others like `o3` and `o4-mini` work.
- sandbox_mode: Supports `read-only` (default) / `workspace-write` / `danger-full-access`. For `workspace-write`, `sandbox_workspace_write.network_access` (default false) can be tuned.
- model_reasoning_effort: `minimal`/`low`/`medium`/`high`.

Provider‑specific env vars
- With the OpenAI provider in API‑key mode, Codex CLI reads `OPENAI_API_KEY`. This belongs to Codex, not this wrapper (OAuth mode does not require it).
- For custom providers or local inference (e.g., `ollama`), edit `~/.codex/config.toml` `model_providers` to set `base_url`, etc.

`.env` の雛形は `.env.example` を参照してください。

### 危険モードの明示許可と Local Only の関係

1) サーバ側で `CODEX_ALLOW_DANGER_FULL_ACCESS=1` を設定し、起動する。
2) リクエストで `x_codex.sandbox: "danger-full-access"` を指定する。

危険モードを許可するには以下の両方が必要です。
- サーバ側で `CODEX_ALLOW_DANGER_FULL_ACCESS=1`
- （任意）`CODEX_LOCAL_ONLY=1` の場合は、プロバイダの `base_url` がローカルであること

どちらかを満たさない場合は 400 を返します。

## Codex の TOML 設定（config.toml）

- 場所: `$CODEX_HOME/config.toml`（未設定時は `~/.codex/config.toml`）。
- 例ファイル: `docs/examples/codex-config.example.toml` をコピーして利用できます。

```bash
mkdir -p ~/.codex
cp docs/examples/codex-config.example.toml ~/.codex/config.toml
```

- OpenAI のデフォルトモデルを使う場合は、環境変数 `OPENAI_API_KEY` を設定してください（本ラッパーではなく Codex CLI が参照します）。
- Web 検索を有効化するには `tools.web_search = true` を `config.toml` に記載します（デフォルトは無効）。
- MCP サーバーは `mcp_servers` セクションで定義します（stdio トランスポート）。サンプルは上記例ファイルを参照。

## 注意事項

- 本ラッパーを他人に使わせたり、自分の ChatGPT/Codex アカウント経由で第三者の利用を中継すると、OpenAI の規約に抵触する可能性があります。
- API キーやアカウントの共有、CLI を使った再販・第三者向け提供は禁止されています。
- 安全に利用するために:
  - 自分専用で使い、外部公開は避ける。
  - 複数人で利用する場合は API ベースに切り替え、各ユーザーに固有の API キーを発行する。
  - レート制限の遵守・キーの非共有・ログ管理を徹底する。

## 追加の注意事項（実験性について）

- このリポジトリはバイブコーディング」によって短時間で作成した実験的なプロジェクトです。
- おおまかな仕組み以外は作者自身も完全には把握していない可能性があります。
- 本番利用・第三者提供の前に、コードと設定、依存関係、セキュリティ方針を必ず各自で精査してください。

## 言語と同期ポリシー

注意事項
- このリポジトリはバイブコーディングによって短時間で作成した実験的なプロジェクトです。
- おおまかな仕組み以外は作者自身も完全には把握していません。
- 本番利用・第三者提供の前に、コードと設定、依存関係、セキュリティ方針を必ず各自で精査してください。

