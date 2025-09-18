from typing import Any, Dict, List, Optional, Literal, Union
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    # Accept both legacy string content and the newer array-of-parts format
    # seen in modern OpenAI-compatible clients (e.g., [{type:"text", text:"..."}]).
    # Keep this permissive to avoid 422 for clients sending mixed shapes.
    content: Any


class XCodexOptions(BaseModel):
    sandbox: Optional[str] = None
    reasoning_effort: Optional[str] = None
    network_access: Optional[bool] = None
    hide_reasoning: Optional[bool] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(default=None)
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    x_codex: Optional[XCodexOptions] = None


class ChatMessageResponse(BaseModel):
    role: str = "assistant"
    content: str


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessageResponse
    finish_reason: Optional[str] = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = "codex-cli"
    object: str = "chat.completion"
    choices: List[ChatChoice]
    usage: Usage = Usage()


# --- Responses API (minimal compatibility) ---

class ResponsesReasoning(BaseModel):
    effort: Optional[str] = None  # minimal | low | medium | high


class ResponsesRequest(BaseModel):
    model: Optional[str] = Field(default=None)
    input: Any
    stream: Optional[bool] = False
    reasoning: Optional[ResponsesReasoning] = None


class ResponsesOutputText(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str


class ResponsesMessage(BaseModel):
    id: str
    type: Literal["message"] = "message"
    role: str = "assistant"
    content: List[ResponsesOutputText]


class ResponsesUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ResponsesObject(BaseModel):
    id: str
    object: Literal["response"] = "response"
    created: int
    model: str = "codex-cli"
    status: Literal["in_progress", "completed", "failed"] = "completed"
    output: List[ResponsesMessage]
    usage: ResponsesUsage = ResponsesUsage()
