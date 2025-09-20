import json
import os
import time
import uuid
from typing import AsyncIterator, List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .codex import CodexError, run_codex, run_codex_last_message
from .config import settings
from .deps import rate_limiter, verify_api_key
from .model_registry import (
    choose_model,
    get_available_models,
    initialize_model_registry,
)
from .security import assert_local_only_or_raise
from .prompt import (
    build_prompt_and_images,
    normalize_responses_input,
    extract_function_call_payload,
)
from .images import save_image_to_temp
from .schemas import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessageResponse,
    FunctionCallPayload,
    FunctionCallRequest,
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


@app.on_event("startup")
async def startup_event() -> None:
    await initialize_model_registry()


@app.get("/v1/models", dependencies=[Depends(rate_limiter), Depends(verify_api_key)])
async def list_models():
    """Return available model list."""
    return {"data": [{"id": model} for model in get_available_models(include_reasoning_aliases=True)]}


@app.post("/v1/chat/completions", dependencies=[Depends(rate_limiter), Depends(verify_api_key)])
async def chat_completions(req: ChatCompletionRequest):
    try:
        model_name, alias_effort = choose_model(req.model)
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "message": str(e),
                "type": "invalid_request_error",
                "code": "model_not_found",
            },
        )

    function_defs = [f.model_dump() for f in req.functions] if req.functions else None
    forced_function_call: Optional[str] = None
    function_call_disabled = False
    if isinstance(req.function_call, FunctionCallRequest):
        forced_function_call = req.function_call.name
    elif req.function_call == "none":
        function_call_disabled = True

    prompt, image_urls = build_prompt_and_images(
        [m.model_dump() for m in req.messages],
        functions=function_defs,
        forced_function_call=forced_function_call,
        function_call_disabled=function_call_disabled,
    )
    x_overrides = req.x_codex.dict(exclude_none=True) if req.x_codex else {}
    if alias_effort and "reasoning_effort" not in x_overrides:
        x_overrides["reasoning_effort"] = alias_effort
    overrides = x_overrides or None

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

    image_paths: List[str] = []
    try:
        for u in image_urls:
            image_paths.append(save_image_to_temp(u))
    except ValueError as e:
        for p in image_paths:
            try:
                os.remove(p)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))

    try:
        function_call_supported = bool(function_defs)

        if req.stream:
            async def event_gen() -> AsyncIterator[bytes]:
                buffered: List[str] = []
                async for text in run_codex(prompt, overrides, image_paths, model=model_name):
                    if not text:
                        continue
                    if function_call_supported:
                        buffered.append(text)
                        continue

                    chunk = {
                        "choices": [
                            {"delta": {"content": text}, "index": 0, "finish_reason": None}
                        ]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n".encode()

                if function_call_supported:
                    combined = "".join(buffered)
                    function_call_dict, cleaned_text = extract_function_call_payload(combined)

                    if function_call_dict and not function_call_disabled:
                        payload = FunctionCallPayload(**function_call_dict)
                        delta_chunk = {
                            "choices": [
                                {"delta": {"function_call": payload.dict()}, "index": 0}
                            ]
                        }
                        yield f"data: {json.dumps(delta_chunk)}\n\n".encode()
                        finish_reason = "function_call"
                    else:
                        content_to_emit = cleaned_text if function_call_dict is None else combined
                        if content_to_emit:
                            chunk = {
                                "choices": [
                                    {"delta": {"content": content_to_emit}, "index": 0}
                                ]
                            }
                            yield f"data: {json.dumps(chunk)}\n\n".encode()
                        finish_reason = "stop"

                    final_chunk = {
                        "choices": [
                            {"delta": {}, "index": 0, "finish_reason": finish_reason}
                        ]
                    }
                    yield f"data: {json.dumps(final_chunk)}\n\n".encode()

                yield b"data: [DONE]\n\n"

            return StreamingResponse(event_gen(), media_type="text/event-stream")
        else:
            final = await run_codex_last_message(prompt, overrides, image_paths, model=model_name)
            function_call_dict = None
            cleaned_text = final
            if function_call_supported:
                function_call_dict, cleaned_text = extract_function_call_payload(final)

            if function_call_dict and not function_call_disabled:
                payload = FunctionCallPayload(**function_call_dict)
                message = ChatMessageResponse(content=None, function_call=payload)
                finish_reason = "function_call"
            else:
                message_content = cleaned_text if function_call_dict is None else final
                message = ChatMessageResponse(content=message_content)
                finish_reason = "stop"

            resp = ChatCompletionResponse(
                choices=[ChatChoice(message=message, finish_reason=finish_reason)]
            )
            return resp
    except CodexError as e:
        raise HTTPException(
            status_code=500,
            detail={"message": str(e), "type": "server_error", "code": None},
        )
    finally:
        for p in image_paths:
            try:
                os.remove(p)
            except Exception:
                pass


@app.post("/v1/responses", dependencies=[Depends(rate_limiter), Depends(verify_api_key)])
async def responses_endpoint(req: ResponsesRequest):
    try:
        model, alias_effort = choose_model(req.model)
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "message": str(e),
                "type": "invalid_request_error",
                "code": "model_not_found",
            },
        )

    # Normalize input → messages
    try:
        messages = normalize_responses_input(req.input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    overrides = {}
    if alias_effort:
        overrides["reasoning_effort"] = alias_effort
    if req.reasoning and req.reasoning.effort:
        overrides["reasoning_effort"] = req.reasoning.effort

    # Enforce local-only model provider when enabled
    if settings.local_only:
        try:
            assert_local_only_or_raise()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    prompt, image_urls = build_prompt_and_images(messages)

    resp_id = f"resp_{uuid.uuid4().hex}"
    msg_id = f"msg_{uuid.uuid4().hex}"
    created = int(time.time())
    response_model = req.model or model
    codex_overrides = overrides or None

    image_paths: List[str] = []
    try:
        for u in image_urls:
            image_paths.append(save_image_to_temp(u))
    except ValueError as e:
        for p in image_paths:
            try:
                os.remove(p)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))

    try:
        if req.stream:
            async def event_gen() -> AsyncIterator[bytes]:
                try:
                    created_evt = {
                        "id": resp_id,
                        "object": "response",
                        "created": created,
                        "model": response_model,
                        "status": "in_progress",
                    }
                    yield f"event: response.created\ndata: {json.dumps(created_evt)}\n\n".encode()

                    buf: list[str] = []
                    async for text in run_codex(prompt, codex_overrides, image_paths, model=model):
                        if text:
                            buf.append(text)
                            delta_evt = {"id": resp_id, "delta": text}
                            yield f"event: response.output_text.delta\ndata: {json.dumps(delta_evt)}\n\n".encode()

                    final_text = "".join(buf)
                    done_evt = {"id": resp_id, "text": final_text}
                    yield f"event: response.output_text.done\ndata: {json.dumps(done_evt)}\n\n".encode()

                    final_obj = ResponsesObject(
                        id=resp_id,
                        created=created,
                        model=response_model,
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
            final = await run_codex_last_message(prompt, codex_overrides, image_paths, model=model)
            resp = ResponsesObject(
                id=resp_id,
                created=created,
                model=response_model,
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
    finally:
        for p in image_paths:
            try:
                os.remove(p)
            except Exception:
                pass
