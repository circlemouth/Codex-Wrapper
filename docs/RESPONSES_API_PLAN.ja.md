# Responses API 対応計画（/v1/responses）

目的：OpenAI Responses API と互換のエンドポイント `/v1/responses` をこのラッパーに追加し、既存の SDK/サンプルが“そのまま”動く範囲を段階的に広げる。

## フェーズとスコープ

フェーズA（最小・非ストリーム）
- `POST /v1/responses`（非ストリーム）
- 入力: `input`（string またはシンプルな content 配列）/ `model` / 任意の軽微オプション。
- 出力: Responses 形式の `response` オブジェクト（`status=completed`、`output` に text を 1 メッセージとして格納）。
- 内部: 既存 `/v1/chat/completions` と同等の変換（`input` → `messages` → Codex 実行 → 文字列結合）。

フェーズB（SSE ストリーミング）【実装済み（最小）】
- `POST /v1/responses` with `stream=true` で SSE 返却。
- サポートする主要イベント（最低セット）:
  - `response.created`: 初期レスポンス（`status=in_progress`）。
  - `response.output_text.delta`: 出力テキストの差分（`delta`）。
  - `response.output_text.done`: テキスト完了（`text`）。
  - `response.completed`: 最終レスポンス（`status=completed`）。
  - 終了シグナル：`data: [DONE]`（利便性のため Chat Completions と同様に付与）。
- 互換性: SDK が型付きイベントを扱う前提に合わせ、`event:` ヘッダ＋`data:` JSON を送る。
- エラー時: `response.error` を送出し、その後 `[DONE]` を送る。

フェーズC（互換拡張）
- 入力 `input` のバリアント追加（chat-like 構造、`input_text` 配列、`input_image` パーツなど）。
- `reasoning.effort` → Codex の `model_reasoning_effort` にマップ。
- `temperature` / `max_output_tokens` は受けるが無視（現行どおり）。
- 未対応明示（将来検討）: ツール呼び出し、音声、structured output（JSON schema など）、並列スレッド。

## リクエスト変換（最小）

受け入れ（順に判定）
- Case 1: `input` が string → `messages=[{"role":"user","content": input}]`
 - Case 2: `input` が配列で、各要素が `{type:"input_text"|"input_image", ...}` → 1 ユーザーメッセージとして扱う（`input_text` は結合、`input_image` は画像として転送）
- Case 3: `input` が配列で、各要素が `{role, content}` を持つ（chat-like）→ そのまま `messages` として利用

オプション・マッピング
- `reasoning.effort`（`minimal|low|medium|high`）→ `x_codex.reasoning_effort`
- `stream: true/false` → SSE 出力の有無
- 以下は一旦未対応（受け取って無視／400 にしない）：`instructions`、`modalities`、`audio`、`tools`、`metadata`、`text.format`（Structured Output。Codex CLI が構造化オブジェクトを返さず文字列のみを出力するため伝搬経路がない）

## レスポンス構造（非ストリーム）

返却例（最小）：

```json
{
  "id": "resp_...",
  "object": "response",
  "created": 1736960000,
  "model": "codex-cli",
  "status": "completed",
  "output": [
    {
      "id": "msg_...",
      "type": "message",
      "role": "assistant",
      "content": [
        { "type": "output_text", "text": "...final text..." }
      ]
    }
  ],
  "usage": { "input_tokens": 0, "output_tokens": 0, "total_tokens": 0 }
}
```

注記
- `usage` は当面 0 を返す（既存仕様に合わせる）。将来、Codex セッションログから概算可能。
- `id` は `resp_`/`msg_` などの接頭辞＋UUID で生成。

## ストリーミング設計（SSE）

送出フォーマット（実装）

```
event: response.created
data: { "id":"resp_...", "status":"in_progress", ... }

event: response.output_text.delta
data: { "id":"resp_...", "delta":"partial..." }

event: response.output_text.delta
data: { "id":"resp_...", "delta":"...text..." }

event: response.output_text.done
data: { "id":"resp_...", "text":"...full text..." }

event: response.completed
data: { "id":"resp_...", "status":"completed", ...final object... }

data: [DONE]
```

Codex の出力行の扱い
- 既存と同様、1 行ずつ読み取り、JSON として解釈できれば `text|content` を優先、できなければテキスト連結。
- 連結した差分を `response.output_text.delta` で逐次送出し、最後に `.done` と `response.completed` を送る。

## エンドポイント仕様（暫定）

- `POST /v1/responses`
  - リクエスト: 上記の最小バリアントを受け付け
  - レスポンス: 非ストリームは JSON、ストリームは `text/event-stream`
- `GET /v1/models` は現状のまま（`codex-cli` を返す）。将来 `responses` との整合のため `id` と `model` の扱いを整理。

## 実装タスク

1. スキーマ追加（Pydantic）
   - Request: `ResponsesRequest`（`input` が `str|list` の Union。緩めの型で受け、内部で正規化）
   - Response: `ResponsesObject`（最小フィールドのみ。未知フィールドは無視）
   - SSE イベント：型は固定しつつ、`data` は辞書で柔軟に
2. ルータ追加
   - `@app.post("/v1/responses")`
   - 非ストリーム／ストリーム分岐は既存に準ずる
3. 正規化レイヤ
   - `input` を `messages` へ変換するユーティリティを新設
   - `reasoning.effort` のマッピング
4. 出力アダプタ
   - 非ストリーム: 最終テキスト → `ResponsesObject`
   - ストリーム: SSE イベントを順序通り送出
5. エラー
   - 400: バリデーション不能（`input` の型が不明等）
   - 500: Codex 実行失敗（既存例外を流用）
6. テスト
   - 非ストリーム／ストリームのサンプルで疎通
   - イベント順序の確認

## 互換性と制約（当面）

- 未対応: ツール呼び出し、画像・音声、Structured Output（`text.format`。Codex CLI が文字列のみを返す仕様のため非対応）、function/tool outputs、parallel responses。
- モデル/プロバイダ:
  - 既定は OpenAI（`OPENAI_API_KEY` がある場合）。`CODEX_LOCAL_ONLY=1` の場合はローカル以外の `base_url` を拒否。
- セキュリティ: 既存の `PROXY_API_KEY`、レート制限、サンドボックス方針に従う。

## クライアント例（計画）

Python（非ストリーム）
```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="YOUR_PROXY_API_KEY")
resp = client.responses.create(model="codex-cli", input="Say hello")
print(resp.output[0].content[0].text)
```

curl（SSE）
```bash
curl -N \
  -H "Authorization: Bearer $PROXY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "model":"codex-cli", "input":"Say hello", "stream":true }' \
  http://localhost:8000/v1/responses
```

---

更新履歴
- 2025-09-15: 初版（設計と段階計画）
