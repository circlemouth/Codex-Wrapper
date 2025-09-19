# 実装計画書（CLI実行方式）

本リポジトリは、OpenAI 互換エンドポイント（最小セット）で Codex CLI の入出力を FastAPI でラップするプロキシです。以下は初期リリースに向けた実装計画です。

## 1. スコープと完成条件

最初は「最低限の互換」を作り、あとで広げます。

提供するもの

1. HTTP API：`/v1/chat/completions` と `/v1/models`（一覧のみ）。
2. ストリーミング：少しずつテキストを返す仕組み → サーバー送信イベント（Server-Sent Events/SSE）。
3. Codex 実行：`codex exec` をサブプロセスとして呼ぶ。静かな出力（`-q`）を優先的に使い、行単位で読み取る。
4. Codex の思考モード（`model_reasoning_effort`）とエージェント権限（`sandbox_mode`）をサーバー起動時の既定値で制御し、リクエスト側では任意で上書きできる。

完成の判断

- OpenAI Python SDK から base_url 差し替えだけでチャット補完が通る（非ストリーム／ストリーム両方）。
- Codex の作業ディレクトリを限定し、承認モードを安全側で動かせる。
- 失敗時は OpenAI 互換のエラー JSON を返す。

## 2. 仕様（OpenAI 互換の最小セット）

エンドポイント

- `/v1/chat/completions`：チャット形式の補完を返す。
- `/v1/models`：`codex-cli` のみを返す「見せ札」。

入力（主要フィールド）

- `model`：既定は `"codex-cli"`（実体は CLI）。
- `messages`：`system` / `user` / `assistant` を受ける。まとめて 1 本の指示に変換する。
- `stream`：`true` なら SSE で逐次返す。
- `temperature`, `max_tokens`：受けるが、CLI 実行では無視（将来拡張の余地として保持）。
- `x_codex`（任意）：`sandbox`/`reasoning_effort` などを指定。未指定時はサーバー起動時の既定値を用いる。

出力（非ストリーム）

- `choices[0].message.content` に最終テキスト。
- `usage` は一旦 0 固定（将来、Codex セッションログから概算）。

出力（ストリーム / SSE）

- 行ごとに `data: {chunk}` を返し、最後に `data: [DONE]`。
- 行の内容は、Codex の静かな出力から JSON とテキストを両方受けられるようにする（JSON として読めなければテキスト連結でフォールバック）。

未対応（初期リリース）

- ツール呼び出し／関数呼び出し、画像・音声の互換、レスポンス形式の厳密なトークン数。
- これらは Codex 側の機能と CLI 出力の安定度に合わせて段階拡張。

並列実行: API リクエストは `CODEX_MAX_PARALLEL_REQUESTS` で指定した件数まで同時に Codex プロセスを起動できる（既定 2。1 を指定すると従来どおり逐次実行）。

## 3. アーキテクチャ（簡潔）

- FastAPI：HTTP の受け口。SSE にも対応。
- CodexRunner：`codex exec` を非同期サブプロセスで走らせ、行単位で stdout を流す。失敗時は stderr も吸い上げて整形。
- PromptBuilder：`messages` を 1 本の指示文にまとめる（`system` を先頭へ）。
- Config：環境変数で最小制御（例：`CODEX_WORKDIR`、`CODEX_SANDBOX_MODE`、`PROXY_API_KEY`）。
- Logger：アプリ側ログ＋Codex セッション JSONL のパスを記録（必要なら後で読み込み）。

## 4. Codex 呼び出しの取り決め

基本コマンド

- 非対話実行：`codex exec "<指示>"`。
- 静かな出力：`-q` / `--quiet` を付ける。
- モデル指定：必要なら `--model o4-mini` 等（任意）。
- サンドボックス：`--config sandbox_mode=...` を環境変数から切替（初期は安全側）。
- 思考モード：`--config model_reasoning_effort=...` を環境変数から切替（`medium` が既定）。

作業ディレクトリ

- `CODEX_WORKDIR` を明示し、その配下に限定。サーバー実行ユーザーは非 root にする。

ログ

- Codex の JSONL セッションは `$CODEX_HOME/sessions/.../*.jsonl` に残る前提（解析は後日機能）。

## 5. 失敗と例外の扱い（方針）

- Codex 側が失敗：終了コード ≠ 0 なら、OpenAI 互換のエラー JSON で 500。stderr を message に要約。
- パースできない出力：JSON として読めない行はテキストとしてバッファし、最後に返す。
- タイムアウト：実行時間の上限（例：60–120 秒）を持つ。長すぎる場合は中断し、内容を添えて 504。
- ストリーミング切断：クライアント切断を検出したらサブプロセスも終了。

## 6. セキュリティ（最初に守ること）

- 実行権限を絞る：非 root、専用ユーザー、専用ディレクトリ。
- 承認モードを安全側：最初は「読むだけ／書き込みに承認が要る」状態。
- HTTP 側の鍵：`PROXY_API_KEY`（Bearer）で守る。必要なら IP 制限＋TLS をリバースプロキシで。
- レート制限：1 IP あたりの毎分リクエスト数を制限。
- 監査：Codex の JSONL ログの保存先を明示しておく。

## 7. 設定（環境変数）

- `PROXY_API_KEY`：API 認証用。
- `CODEX_WORKDIR`：Codex 実行カレント。
- `CODEX_SANDBOX_MODE`：`read-only` / `workspace-write` / `danger-full-access`（既定は安全側）。
- `CODEX_REASONING_EFFORT`：`minimal` / `low` / `medium` / `high`（既定は `medium`）。
- `CODEX_LOCAL_ONLY`：`1` でローカル固定（プロバイダの `base_url` がローカル以外なら 400）。
- `CODEX_MODEL`：廃止。サーバー起動時に `codex models list` を実行して利用可能なモデルを自動検出する。
- `CODEX_PATH`：`codex` 実行ファイルへのパスを上書きしたい場合に使用。
- `CODEX_TIMEOUT`：Codex 実行のタイムアウト秒数（既定 120）。
- `RATE_LIMIT_PER_MINUTE`：1 分あたりの許可リクエスト数（既定 60）。

これらでサーバー起動時の既定値を定め、リクエスト側は `x_codex` を使うことで任意に上書きできる（OpenAI 互換のまま）。

## 8. 実装タスク（Codex に投げる用の粒度）

フェーズA：土台

- A1 リポジトリ初期化
  - 受け入れ：FastAPI と uvicorn の依存が入り、`app/` 構成ができる。起動して 200 が返る。
- A2 設定読み込み
  - 受け入れ：環境変数を Pydantic で読み、欠落時の既定値が効く。
- A3 `/v1/models`
  - 受け入れ：`{"data":[{"id":"codex-cli"}]}` を返す。

フェーズB：Codex 実行レイヤ

- B1 PromptBuilder
  - 受け入れ：messages を「system 文 → 会話 → assistant: で締める」文字列にできる。
- B2 CodexRunner（非同期）
  - 受け入れ：`codex exec` を `-q` 付きで実行し、行ごとに stdout を async iterator で受け取れる。失敗時は stderr を拾う。
- B3 タイムアウトと中断
  - 受け入れ：指定秒数で打ち切り。クライアント切断を検知してプロセスを殺せる。

フェーズC：API 実装

- C1 `/v1/chat/completions` 非ストリーム
  - 受け入れ：最終行の JSON から `text`/`content` を選ぶ。なければプレーンテキスト結合で返す。
- C2 `/v1/chat/completions` ストリーム（SSE）
  - 受け入れ：`text/event-stream` で `data: {chunk}` を逐次送信し、最後に `[DONE]`。
- C3 エラー整形
  - 受け入れ：OpenAI 互換のエラー JSON に統一。

フェーズD：運用と安全

- D1 認証（Bearer）
  - 受け入れ：`Authorization: Bearer xxx` が必須（未設定なら無認証でも起動可）。
- D2 レート制限 & CORS
  - 受け入れ：1 分あたりの回数を制限。必要なオリジンのみ許可。
- D3 監査ログの鉤
  - 受け入れ：Codex の JSONL ログパス（`$CODEX_HOME/sessions/...`）をアプリ側ログに記録。

フェーズE：テストとデプロイ

- E1 SDK 経由の動作確認
  - 受け入れ：OpenAI Python SDK で `base_url=http://localhost:8000/v1`、`stream=True/False` が通る。
- E2 並行実行テスト
  - 受け入れ：同時 5–10 リクエストで相互干渉しない。
- E3 Docker 化（任意）
  - 受け入れ：非 root で動作し、`CODEX_WORKDIR` をボリュームで与えられる。

## 9. 実装メモ（Codex への具体指示例）

依存導入

```bash
pip install fastapi "uvicorn[standard]" pydantic
```

ファイル構成（例）

- `app/main.py`（FastAPI 起動）
- `app/schemas.py`（入出力モデル）
- `app/prompt.py`（PromptBuilder）
- `app/codex.py`（CodexRunner：`asyncio.create_subprocess_exec`）
- `app/deps.py`（認証・設定）

CodexRunner のコマンド

- `[
  "codex", "exec", prompt,
  "-q",
  "--config", f"sandbox_mode='{os.getenv('CODEX_SANDBOX_MODE','read-only')}'",
  "--config", f"model_reasoning_effort='{os.getenv('CODEX_REASONING_EFFORT','medium')}'",
  # 任意: ローカル provider 固定（例: ollama）
  # "--config", "model_provider='ollama'",
  # "--config", "model_providers.ollama='{ name = \"Ollama\", base_url = \"http://localhost:11434/v1\" }'",
  # 旧仕様：環境変数 `CODEX_MODEL` を `--config model` に渡していたが、現在は自動検出されたモデルを使う。
]` のように組み立て、空値は落とす。
- `cwd=CODEX_WORKDIR` を必ず指定。
- `CODEX_LOCAL_ONLY=1` の場合、`$CODEX_HOME/config.toml` の `model_providers` と `OPENAI_BASE_URL` を検査し、ローカル以外の `base_url` なら実行前に 400 で拒否。

API 入力の拡張（任意）

- リクエスト JSON のベンダー拡張 `x_codex` を受け付け、以下を `--config` にマップ：
  - `x_codex.sandbox` → `sandbox_mode`
  - `x_codex.reasoning_effort` → `model_reasoning_effort`
  - `x_codex.network_access`（true/false）→ `sandbox_workspace_write.network_access`（`workspace-write` のときのみ）

SSE の返し方

- 1 行受けるたびに：
  - JSON なら `obj.get("text") or obj.get("content")` を `delta.content` にして chunk 化。
  - 失敗したら一旦バッファに貯め、最後にまとめて 1 回流す。

エラー JSON の形

```json
{"error": {"message": "...", "type": "server_error", "code": null}}
```

## 10. リスクと回避策

- CLI 出力仕様の変化：`--quiet` の JSON 行やフィールド名は将来変わることがある → JSON/テキスト両対応のフォールバックを実装。
- 安全性：Codex の自動実行が思わぬ変更を起こす可能性 → 承認モードを安全側、ディレクトリを限定、バージョン管理で監査。
- ログ肥大：JSONL セッションが蓄積 → ログ保存期間とサイズを定め、定期ローテーションを運用に入れる。

## 11. 受け入れテスト項目（抜粋）

- 非ストリーム：単発の指示で応答が返る。
- ストリーム：SSE で逐次文字列が届く。
- 失敗時：Codex のエラーを 500 で JSON 化して返す。
- 認証：鍵なし拒否／鍵あり成功。
- 承認モード：`manual` と `readonly` 切替で挙動が変わる（少なくとも無害である）。

## 12. 運用の始め方

Codex の導入

- `npm i -g @openai/codex` または `brew install codex`（OS に応じて）。
- 非対話の動作確認：`codex exec "echo hello"`、静かな出力：`codex -q "echo hello"`。

サーバー起動

- `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- OpenAI SDK から `base_url="http://localhost:8000/v1"` で疎通。
