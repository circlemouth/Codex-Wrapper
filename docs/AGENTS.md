# エージェント向けガイド（Codex-Wrapper）

このサーバーは Codex CLI を FastAPI でラップし、OpenAI 互換の最低限 API を提供します。既存の OpenAI クライアント（Python/JS など）で `base_url` を差し替えるだけで利用できます。

## 基本

- ベース URL：`http://<host>:8000/v1`
- 認証：`Authorization: Bearer <PROXY_API_KEY>`（未設定時は無認証で動作可能にする構成も可）
- 提供モデル：`codex-cli`（見かけ上のモデル名）
- サブモジュール：`submodules/codex` に Codex 本体（参考実装）

## サポート API

- `GET /v1/models`
  - 返却例：`{"data":[{"id":"codex-cli"}]}`
- `POST /v1/chat/completions`
  - 入力（抜粋）
    - `model`: 任意。省略時 `codex-cli`
    - `messages`: OpenAI 形式（`system`/`user`/`assistant`）
    - `stream`: `true` で SSE ストリーミング
    - `temperature`, `max_tokens`: 受けるが初期版では無視
  - 出力（非ストリーム）
    - `choices[0].message.content` に最終テキスト
    - `usage` は暫定で 0 固定
  - 出力（ストリーム/SSE）
    - `Content-Type: text/event-stream`
    - 行ごとに `data: {chunk}`、終了は `data: [DONE]`
    - JSON 行を優先解釈し、`text` または `content` を `choices[0].delta.content` として送出。非 JSON 行はテキスト連結フォールバック

## サンプル（Python / OpenAI SDK）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY",  # 必須にしている場合
)

# 非ストリーム
resp = client.chat.completions.create(
    model="codex-cli",
    messages=[
        {"role": "system", "content": "You are a helpful coding agent."},
        {"role": "user", "content": "Say hello and exit."},
    ],
)
print(resp.choices[0].message.content)

# ストリーム（SSE）
with client.chat.completions.create(
    model="codex-cli",
    messages=[{"role": "user", "content": "Write 'hello'"}],
    stream=True,
) as stream:
    for event in stream:
        if event.type == "chunk":
            delta = event.data.choices[0].delta
            if delta and delta.content:
                print(delta.content, end="", flush=True)
```

## サンプル（curl / SSE）

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

## エラー形式（互換）

- 失敗時は以下の形で返します：

```json
{"error": {"message": "...", "type": "server_error", "code": null}}
```

- タイムアウトが発生した場合は 504 を想定（実装計画に準拠）

## 実行と安全性

- Codex 呼び出し：`codex exec <PROMPT> -q [--model <...>] [--approval-mode <...>]`
- CWD：`CODEX_WORKDIR` に制限（サーバープロセスは非 root を推奨）
- 承認モード：`manual`/`readonly`/`full-auto` を環境変数で指定（初期は安全側）
- レート制限/CORS：API 層で制御（設定により有効化）

## 設定（環境変数）

- `PROXY_API_KEY`：API 認証用（未設定なら無認証でも起動可にする構成も可能）
- `CODEX_WORKDIR`：Codex 実行時の作業ディレクトリ
- `CODEX_MODEL`：`o3-mini` など任意指定
- `CODEX_PATH`：`codex` 実行ファイルパスの上書き
- `CODEX_APPROVAL_POLICY`：`never` / `on-request` / `on-failure` / `untrusted`
- `CODEX_SANDBOX_MODE`：`read-only` / `workspace-write` / `danger-full-access`
- `CODEX_REASONING_EFFORT`：`minimal` / `low` / `medium` / `high`
- `CODEX_LOCAL_ONLY`：`1` でローカル以外のベースURLを拒否

## モード設計（ローカル固定）

本ラッパーは「ローカルで固定（クラウドには送信しない）」を前提に設計します。Codex CLI 側のサンドボックス／承認、および思考モード（reasoning effort）を以下の方針でラップします。

- ローカル固定の意味：モデル推論の HTTP 送信先はローカル（例：`http://localhost:11434/v1` など）に限定。外部クラウドの API ベースURLは禁止。
- コマンド実行のネットワーク：原則ブロック（`workspace-write` でも network_access=false）。必要な場合のみ明示的に許可（将来オプション）。

### エージェント権限（フルアクセスか否か）

Codex CLI のドキュメントに準拠して、`sandbox_mode` と `approval_policy` を組み合わせます。

- 安全（既定）: `sandbox=read-only`, `approval=on-request`
  - 読み取りのみ。編集・実行・ネットワークは原則拒否、必要時にエスカレーション要求。
- 編集許可（推奨）: `sandbox=workspace-write`, `approval=on-request`（ネットワークは `false`）
  - ワークスペース内の編集とコマンド実行は自動可。外部アクセスやリポ外は承認が必要。ネットワークは遮断。
- フルアクセス（原則無効）: `sandbox=danger-full-access`, `approval=never`
  - ファイル・ネットワーク全面許可。ローカル固定の安全方針に反するため、デフォルトではサーバー側で拒否します（CI/コンテナ等で明示的にのみ有効化）。

CLI フラグ相当（参考）

```bash
# 安全（既定）
codex exec "..." -q \
  --config sandbox_mode='read-only' \
  --config approval_policy='on-request'

# 編集許可（推奨）
codex exec "..." -q \
  --config sandbox_mode='workspace-write' \
  --config approval_policy='on-request' \
  --config sandbox_workspace_write='{ network_access = false }'
```

### 思考モード（Reasoning Effort）

`model_reasoning_effort` を Codex CLI に渡して制御します（`minimal`/`low`/`medium`/`high`）。

- 既定: `medium`（バランス重視）
- 推奨ガイド:
  - `high`: 大規模改修、複数ファイルの整合性が絡む作業、要件曖昧で探索が必要なとき
  - `medium`: 通常の実装・修正
  - `low/minimal`: 単発の小改修、機械的な変換、コマンド実行中心

CLI フラグ相当（参考）

```bash
codex exec "..." -q --config model_reasoning_effort='high'
```

### サーバー側の固定と検証（ローカル限定）

サーバー（ラッパー）は以下を強制します。

- `CODEX_LOCAL_ONLY=1` のとき、Codex のモデル送信先がローカル以外（`http(s)://localhost`/`127.0.0.1`/Unix ソケット以外）なら 400/403 を返して拒否。
- `OPENAI_API_KEY` など外部クラウド用のキーは未設定を推奨（設定されていても `CODEX_LOCAL_ONLY=1` のときは不使用）。
- Codex CLI には `--config model_provider=ollama` などローカル向けを明示、`--config model_providers.ollama.base_url='http://localhost:11434/v1'` を付与。

例（ローカル Ollama に固定して実行）

```bash
codex exec "..." -q \
  --config model_provider='ollama' \
  --config model='llama3.1' \
  --config model_providers.ollama='{ name = "Ollama", base_url = "http://localhost:11434/v1" }' \
  --config sandbox_mode='workspace-write' \
  --config sandbox_workspace_write='{ network_access = false }' \
  --config approval_policy='on-request' \
  --config model_reasoning_effort='medium'
```

### API からの指定（拡張フィールド）

OpenAI 互換のまま利用できるよう、任意でベンダー拡張 `x_codex` を受け付けます（未指定時はサーバー既定を適用）。

```json
{
  "model": "codex-cli",
  "messages": [ { "role": "user", "content": "..." } ],
  "x_codex": {
    "sandbox": "workspace-write",           // read-only | workspace-write | danger-full-access
    "approval_policy": "on-request",        // never | on-request | on-failure | untrusted
    "reasoning_effort": "high",             // minimal | low | medium | high
    "network_access": false                  // workspace-write のときのみ有効
  }
}
```

サーバーは上記を Codex CLI の `--config` 引数にマッピングします。`CODEX_LOCAL_ONLY=1` の場合、`danger-full-access` や外部ベースURLは拒否されます。

## サブモジュール運用

- 参照先：`submodules/codex`（https://github.com/openai/codex.git）
- 初回取得：`git submodule update --init --recursive`
- 更新反映：

```bash
git submodule update --remote submodules/codex
# 必要に応じて commit し、上位リポジトリに反映
```

## 制約と非対応（初期）

- ツール/関数呼び出し・画像/音声は非対応
- 厳密なトークン制御・マルチスレッドは非対応
- CLI 出力仕様の変化に備え、JSON/テキスト両対応でパース（将来変更に追随）

## トラブルシュート

- 403/401：`PROXY_API_KEY` とヘッダを確認
- 504：Codex 実行が長すぎる可能性。プロンプトを簡潔に、またはタイムアウト設定を調整
- 500：Codex 側のエラーが stderr に出力。サーバーログで要約を確認
