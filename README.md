# Codex-Wrapper

OpenAI 互換の最小 API で Codex CLI をラップする FastAPI サーバー。`/v1/chat/completions` と `/v1/models` を提供し、SSE ストリーミングをサポートします。

- 参考サブモジュール：`submodules/codex`（https://github.com/openai/codex.git）
- 実装計画：`docs/IMPLEMENTATION_PLAN.md`
- エージェント向けガイド：`docs/AGENTS.md`
 - Responses API 設計/進捗：`docs/RESPONSES_API_PLAN.md`

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

OpenAI の gpt-5 モデルを使うには、（APIキー運用時は）`OPENAI_API_KEY` を環境変数として設定し、
`.env` などで `CODEX_MODEL=gpt-5` を指定します。OAuth運用時は `OPENAI_API_KEY` は必須ではありません。

5) 環境変数の設定（.env 対応）

このリポジトリは `.env` から環境変数を自動で読み込みます（`pydantic-settings`）。

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

詳細は `docs/IMPLEMENTATION_PLAN.md` と `docs/AGENTS.md` を参照してください。
Responses API 互換は最小実装済み（非ストリーム/ストリーム）。詳細と今後の拡張は `docs/RESPONSES_API_PLAN.md` を参照。

## 環境変数（正確な仕様）

このサーバーは `.env` を読み込み、以下の環境変数で挙動を制御します。値の例や許容値は Codex サブモジュール（`submodules/codex`）の最新ドキュメントに基づきます。

- PROXY_API_KEY: API 認証トークン。未設定なら無認証で動作。
- RATE_LIMIT_PER_MINUTE: 1 分あたりの許容リクエスト数。0 で無効。
- CODEX_PATH: `codex` バイナリのパス。既定 `codex`。
- CODEX_WORKDIR: Codex 実行時の作業ディレクトリ（`cwd`）。既定 `/workspace`。
- CODEX_MODEL: Codex の `model` に渡す文字列。例: `o3`, `o4-mini`, `gpt-5`（`submodules/codex/docs/config.md` の「model」参照）。
  - 備考: 文字列自体は自由だが、選んだ `model_provider`（既定は OpenAI）側で利用可能なモデル名である必要があります。
- CODEX_SANDBOX_MODE: サンドボックス。許容値: `read-only` | `workspace-write` | `danger-full-access`。
  - `workspace-write` の場合、ラッパーは `--config sandbox_workspace_write='{ network_access = <true|false> }'` を必要に応じて付与します（API の `x_codex.network_access` が指定されたとき）。
- CODEX_REASONING_EFFORT: 推論強度。許容値: `minimal` | `low` | `medium` | `high`（既定 `medium`）。
- CODEX_LOCAL_ONLY: `0`/`1`。デフォルトは `0`（推奨）。
  - `1` の場合、モデルプロバイダの `base_url` がローカル（`localhost`/`127.0.0.1`/`[::1]`/`unix://`）以外なら 400 を返します。
  - 検査対象は `$CODEX_HOME/config.toml` の `model_providers` と、組み込み `openai` プロバイダの `OPENAI_BASE_URL` です。設定が見つからない/不明な場合も安全側で拒否します。
- CODEX_ALLOW_DANGER_FULL_ACCESS: `0`/`1`（既定 `0`）。`1` にすると、APIの `x_codex.sandbox: "danger-full-access"` を許可します。
  - 安全上の推奨: これを `1` にするのは隔離済みのコンテナ/VM環境に限ってください。
- CODEX_TIMEOUT: Codex 実行のサーバー側タイムアウト秒数（既定 120）。
- CODEX_ENV_FILE: 読み込む `.env` ファイルのパス。これは OS の環境変数としてサーバー起動前に設定してください（`.env` 内には書かない）。未設定時は `.env`。

認証関連の補足（重要）
- パターンA（OAuth/ChatGPT）とパターンB（APIキー）のいずれも Codex CLI 側で完結します。
  サーバープロセスと同じ OS ユーザーで `codex login` を実行してください。
- `auth.json` の場所は `$CODEX_HOME`（既定 `~/.codex`）。このパスを変える場合は、
  `.env` ではなく OS の環境変数 `CODEX_HOME` を設定してください。
- `PROXY_API_KEY` はこの API ラッパーの外部アクセス制御用で、Codex の OAuth 認証とは無関係です。
- ChatGPT ログイン方式では `OPENAI_API_KEY` は不要です。APIキー運用では必要に応じて設定してください。
- `CODEX_LOCAL_ONLY=1` のときは、OpenAI のようなリモート `base_url` は拒否されます（APIキー運用時は注意）。

補足（Codex 側の重要ポイント）
- model: Codex の既定は `gpt-5`。`o3` や `o4-mini` なども有効。
- sandbox_mode: `read-only`（既定）/`workspace-write`/`danger-full-access` をサポート。`workspace-write` では `sandbox_workspace_write.network_access`（既定 false）等の追加設定が可能。
- model_reasoning_effort: `minimal`/`low`/`medium`/`high` をサポート。

プロバイダ固有の環境変数について
- OpenAI プロバイダを「APIキー運用」で使う場合、Codex CLI は `OPENAI_API_KEY` を参照します。これは本ラッパーではなく Codex 側が読み取る変数です（OAuth運用では不要）。
- 独自プロバイダやローカル推論（例: `ollama`）を使う場合は `~/.codex/config.toml` の `model_providers` 設定で `base_url` 等を指定してください。

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
