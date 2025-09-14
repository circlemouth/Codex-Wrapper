# Codex-Wrapper

OpenAI 互換の最小 API で Codex CLI をラップする FastAPI サーバー。`/v1/chat/completions` と `/v1/models` を提供し、SSE ストリーミングをサポートします。

- 参考サブモジュール：`submodules/codex`（https://github.com/openai/codex.git）
- 実装計画：`docs/IMPLEMENTATION_PLAN.md`
- エージェント向けガイド：`docs/AGENTS.md`

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

3) 必要な環境変数を設定

```bash
export CODEX_WORKDIR="$PWD"              # Codex が操作できる作業ディレクトリ
export PROXY_API_KEY="your_api_key"      # 認証を有効にする場合
# 任意: export CODEX_MODEL="o3-mini"
# 任意: export RATE_LIMIT_PER_MINUTE=60
# 任意: export CODEX_TIMEOUT=120
```

4) サーバ起動

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

5) SDK から接続

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="YOUR_PROXY_API_KEY")
```

詳細は `docs/IMPLEMENTATION_PLAN.md` と `docs/AGENTS.md` を参照してください。

