import json
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .codex import CodexError, run_codex
from .config import settings
from .deps import rate_limiter, verify_api_key
from .prompt import build_prompt
from .schemas import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageResponse,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/v1/models", dependencies=[Depends(rate_limiter), Depends(verify_api_key)])
async def list_models():
    """Return available model list."""
    return {"data": [{"id": "codex-cli"}]}


@app.post("/v1/chat/completions", dependencies=[Depends(rate_limiter), Depends(verify_api_key)])
async def chat_completions(req: ChatCompletionRequest):
    prompt = build_prompt([m.dict() for m in req.messages])
    overrides = req.x_codex.dict(exclude_none=True) if req.x_codex else None

    if settings.local_only and overrides and overrides.get("sandbox") == "danger-full-access":
        raise HTTPException(status_code=400, detail="danger-full-access is disabled")

    try:
        if req.stream:
            async def event_gen() -> AsyncIterator[bytes]:
                async for line in run_codex(prompt, overrides):
                    try:
                        obj = json.loads(line)
                        text = obj.get("text") or obj.get("content")
                    except json.JSONDecodeError:
                        text = line
                    if text:
                        chunk = {
                            "choices": [
                                {"delta": {"content": text}, "index": 0, "finish_reason": None}
                            ]
                        }
                        yield f"data: {json.dumps(chunk)}\n\n".encode()
                yield b"data: [DONE]\n\n"

            return StreamingResponse(event_gen(), media_type="text/event-stream")
        else:
            pieces = []
            async for line in run_codex(prompt, overrides):
                try:
                    obj = json.loads(line)
                    text = obj.get("text") or obj.get("content")
                    if text is not None:
                        pieces.append(text)
                except json.JSONDecodeError:
                    pieces.append(line)
            final = "".join(pieces)
            resp = ChatCompletionResponse(
                choices=[ChatChoice(message=ChatMessageResponse(content=final))]
            )
            return resp
    except CodexError as e:
        raise HTTPException(
            status_code=500,
            detail={"message": str(e), "type": "server_error", "code": None},
        )
