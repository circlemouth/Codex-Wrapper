from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class XCodexOptions(BaseModel):
    sandbox: Optional[str] = None
    approval_policy: Optional[str] = None
    reasoning_effort: Optional[str] = None
    network_access: Optional[bool] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(default="codex-cli")
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
