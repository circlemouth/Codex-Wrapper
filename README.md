# Codex-Wrapper

OpenAI 互換の最小 API で Codex CLI をラップする FastAPI サーバー。`/v1/chat/completions` と `/v1/models` を提供し、SSE ストリーミングをサポートします。

- 参考サブモジュール：`submodules/codex`（https://github.com/openai/codex.git）
- 実装計画：`docs/IMPLEMENTATION_PLAN.md`
- エージェント向けガイド：`docs/AGENTS.md`

## クイックスタート（計画に準拠）

1) 依存

```bash
pip install fastapi "uvicorn[standard]" pydantic
```

2) Codex の導入（いずれか）

```bash
npm i -g @openai/codex
# または
brew install codex
```

3) サーバ起動（実装後）

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4) SDK から接続

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="YOUR_PROXY_API_KEY")
```

詳細は `docs/IMPLEMENTATION_PLAN.md` と `docs/AGENTS.md` を参照してください。

