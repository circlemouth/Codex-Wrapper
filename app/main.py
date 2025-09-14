import json
import time
import uuid
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .codex import CodexError, run_codex, run_codex_last_message
from .config import settings
from .deps import rate_limiter, verify_api_key
from .security import assert_local_only_or_raise
from .prompt import build_prompt, normalize_responses_input
from .schemas import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageResponse,
    ResponsesRequest,
    ResponsesObject,
    ResponsesMessage,
    ResponsesOutputText,
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

    # Safety gate: only allow danger-full-access when explicitly enabled
    if overrides and overrides.get("sandbox") == "danger-full-access":
        if not settings.allow_danger_full_access:
            raise HTTPException(status_code=400, detail="danger-full-access is disabled by server policy")

    # Enforce local-only model provider when enabled
    if settings.local_only:
        try:
            assert_local_only_or_raise()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        if req.stream:
            async def event_gen() -> AsyncIterator[bytes]:
                async for text in run_codex(prompt, overrides):
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
            final = await run_codex_last_message(prompt, overrides)
            resp = ChatCompletionResponse(
                choices=[ChatChoice(message=ChatMessageResponse(content=final))]
            )
            return resp
    except CodexError as e:
        raise HTTPException(
            status_code=500,
            detail={"message": str(e), "type": "server_error", "code": None},
        )


@app.post("/v1/responses", dependencies=[Depends(rate_limiter), Depends(verify_api_key)])
async def responses_endpoint(req: ResponsesRequest):
    # Normalize input → messages
    try:
        messages = normalize_responses_input(req.input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Map reasoning.effort → x_codex.reasoning_effort
    overrides = {}
    if req.reasoning and req.reasoning.effort:
        overrides["reasoning_effort"] = req.reasoning.effort

    # Enforce local-only model provider when enabled
    if settings.local_only:
        try:
            assert_local_only_or_raise()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    prompt = build_prompt(messages)

    resp_id = f"resp_{uuid.uuid4().hex}"
    msg_id = f"msg_{uuid.uuid4().hex}"
    created = int(time.time())
    model = req.model or "codex-cli"

    try:
        if req.stream:
            async def event_gen() -> AsyncIterator[bytes]:
                try:
                    # response.created
                    created_evt = {
                        "id": resp_id,
                        "object": "response",
                        "created": created,
                        "model": model,
                        "status": "in_progress",
                    }
                    yield f"event: response.created\ndata: {json.dumps(created_evt)}\n\n".encode()

                    buf: list[str] = []
                    async for text in run_codex(prompt, overrides):
                        if text:
                            buf.append(text)
                            delta_evt = {"id": resp_id, "delta": text}
                            yield f"event: response.output_text.delta\ndata: {json.dumps(delta_evt)}\n\n".encode()

                    final_text = "".join(buf)
                    # output_text.done
                    done_evt = {"id": resp_id, "text": final_text}
                    yield f"event: response.output_text.done\ndata: {json.dumps(done_evt)}\n\n".encode()

                    # response.completed
                    final_obj = ResponsesObject(
                        id=resp_id,
                        created=created,
                        model=model,
                        status="completed",
                        output=[
                            ResponsesMessage(
                                id=msg_id,
                                content=[ResponsesOutputText(text=final_text)],
                            )
                        ],
                    ).model_dump()
                    yield f"event: response.completed\ndata: {json.dumps(final_obj)}\n\n".encode()
                except CodexError as e:
                    err_evt = {"id": resp_id, "error": {"message": str(e)}}
                    yield f"event: response.error\ndata: {json.dumps(err_evt)}\n\n".encode()
                finally:
                    yield b"data: [DONE]\n\n"

            headers = {
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            }
            return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)
        else:
            final = await run_codex_last_message(prompt, overrides)
            resp = ResponsesObject(
                id=resp_id,
                created=created,
                model=model,
                status="completed",
                output=[
                    ResponsesMessage(
                        id=msg_id,
                        content=[ResponsesOutputText(text=final)],
                    )
                ],
            )
            return resp
    except CodexError as e:
        raise HTTPException(
            status_code=500,
            detail={"message": str(e), "type": "server_error", "code": None},
        )
