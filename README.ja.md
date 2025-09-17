# Codex-Wrapper

OpenAI 互換の最小 API で Codex CLI をラップする FastAPI サーバー。`/v1/chat/completions` と `/v1/models` を提供し、SSE ストリーミングをサポートします。

- 参考サブモジュール：`submodules/codex`（https://github.com/openai/codex.git）
- 実装計画：`docs/IMPLEMENTATION_PLAN.ja.md`（日本語のみ）
- エージェント向けガイド：`docs/AGENTS.md`（英語）
- Responses API 設計/進捗：`docs/RESPONSES_API_PLAN.ja.md`（日本語のみ）
- 環境設定: `docs/ENV.md`（英語）

> 言語ポリシー：ユーザー向けドキュメントは原則として英日両対応ですが、実装計画と Responses API 計画は日本語のみで管理します。運用ルールは `CONTRIBUTING.md` を参照してください。

[English](./README.md) | 日本語

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

OpenAI の gpt-5 モデルを使うには、（APIキー運用時は）Codex CLI 側で該当プロバイダーの資格情報を設定してください。このラッパーは起動時に `codex models list` を実行して利用可能なモデル名を自動検出します。利用可能なモデル名は `GET /v1/models` で確認できます。OAuth運用時は `OPENAI_API_KEY` は必須ではありません。

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

## 環境変数


このサーバーは `.env` を読み込み、以下の環境変数を使用します。例や制約は Codex サブモジュール（`submodules/codex`）の最新ドキュメントに準拠しています。

- PROXY_API_KEY: ラッパー用の API トークン。未設定の場合は認証なしで起動します。
- RATE_LIMIT_PER_MINUTE: 1 分あたりのリクエスト許容量。0 を指定するとレート制限を無効化します。
- CODEX_PATH: `codex` バイナリのパス。既定値は `codex`。
- CODEX_WORKDIR: Codex 実行時の作業ディレクトリ (`cwd`)。既定値は `/workspace`。
  - サーバープロセスから書き込み可能なパスを指定してください。読み取り専用パスの場合は `Failed to create CODEX_WORKDIR ... Read-only file system` エラーになります。
- CODEX_MODEL: **廃止**。モデル選択は自動化されており、この変数を設定しても無視され（起動時に警告が出力されます）。
- CODEX_SANDBOX_MODE: サンドボックスモード。`read-only` / `workspace-write` / `danger-full-access` のいずれか。
  - `workspace-write` の場合、API リクエストで `x_codex.network_access` が指定されると `--config sandbox_workspace_write='{ network_access = <true|false> }'` を付与します。
- CODEX_REASONING_EFFORT: 推論強度。`minimal` / `low` / `medium` / `high`（既定は `medium`）。
- CODEX_LOCAL_ONLY: `0` または `1`。既定は `0`（推奨）。
  - `1` にするとローカル以外の `base_url`（localhost/127.0.0.1/[::1]/UNIX ソケット以外）のモデルプロバイダを 400 で拒否します。
  - サーバーは `$CODEX_HOME/config.toml` の `model_providers` と組み込み `openai` プロバイダの `OPENAI_BASE_URL` を検証し、不明な設定は安全側で拒否します。
- CODEX_ALLOW_DANGER_FULL_ACCESS: `0` または `1`（既定 `0`）。`1` にすると API から `x_codex.sandbox: "danger-full-access"` を要求できます。隔離環境以外では有効化しないでください。
- CODEX_TIMEOUT: Codex 実行のサーバー側タイムアウト秒数（既定 120 秒）。
- CODEX_ENV_FILE: 読み込む `.env` ファイルのパス。サーバー起動前に OS 環境変数として設定する必要があり、`.env` 内からは指定できません（既定 `.env`）。

認証関連の補足
- OAuth（ChatGPT）と API キーの両モードとも Codex CLI 側で処理します。サーバープロセスと同じ OS ユーザーで `codex login` を実行してください。
- `auth.json` の場所は `$CODEX_HOME`（既定 `~/.codex`）。移動する場合は `.env` ではなく OS 環境変数で `CODEX_HOME` を設定します。
- `PROXY_API_KEY` はこのラッパーへのアクセス制御用であり、Codex の OAuth とは無関係です。
- ChatGPT ログイン（OAuth）では `OPENAI_API_KEY` は不要ですが、API キー運用では必須です。
- `CODEX_LOCAL_ONLY=1` の場合、OpenAI などリモートの `base_url` は拒否されるため API キー運用時は設定に注意してください。

Codex の主な設定
- model: 既定は `gpt-5`。`o3` や `o4-mini` など他のモデルも利用可能です。
- sandbox_mode: `read-only`（既定）/`workspace-write`/`danger-full-access` をサポート。`workspace-write` の場合は `sandbox_workspace_write.network_access`（既定 false）を調整できます。
- model_reasoning_effort: `minimal`/`low`/`medium`/`high`。

プロバイダ固有の環境変数
- OpenAI プロバイダを API キーで使う場合、Codex CLI は `OPENAI_API_KEY` を参照します（ラッパー側ではなく Codex 側の設定）。OAuth モードでは不要です。
- 独自プロバイダやローカル推論（例: `ollama`）を使うときは、`~/.codex/config.toml` の `model_providers` で `base_url` などを設定してください。

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

### 複数の Codex 設定を並行運用する

Codex の設定ごとにラッパーを別プロセスで起動し、起動前に `CODEX_HOME` を設定すると、それぞれ異なる `config.toml` を参照できます（`.env` ではなく OS 環境変数として設定してください）。ポートや `.env` の内容を分けたい場合は `CODEX_ENV_FILE` も併用します。

```bash
# インスタンスA（本番）
CODEX_HOME=/opt/codex-prod CODEX_ENV_FILE=.env.prod uvicorn app.main:app --port 8000

# インスタンスB（ステージング）
CODEX_HOME=/opt/codex-stage CODEX_ENV_FILE=.env.stage uvicorn app.main:app --port 8001
```

`CODEX_HOME` で指定した各ディレクトリ（例: `/opt/codex-prod`）に専用の `config.toml` や必要なら `auth.json` を配置すれば、複数の Codex バックエンドを並行して提供できます。

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
