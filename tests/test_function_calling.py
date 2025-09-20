import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main
from app import prompt
from app.schemas import ChatCompletionRequest, ChatMessage, FunctionDefinition


@pytest.mark.asyncio
async def test_chat_completion_returns_function_call(monkeypatch):
    monkeypatch.setattr(main, "choose_model", lambda model: (model or "test", None))
    monkeypatch.setattr(main.settings, "local_only", False)

    async def fake_run_codex_last_message(*_, **__):
        return '{"function_call": {"name": "lookup_weather", "arguments": {"city": "Osaka"}}}'

    monkeypatch.setattr(main, "run_codex_last_message", fake_run_codex_last_message)

    req = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="天気教えて")],
        functions=[
            FunctionDefinition(
                name="lookup_weather",
                description="現在の天気を取得する",
                parameters={"type": "object", "properties": {"city": {"type": "string"}}},
            )
        ],
    )

    response = await main.chat_completions(req)
    choice = response.choices[0]

    assert choice.finish_reason == "function_call"
    assert choice.message.function_call is not None
    assert choice.message.function_call.name == "lookup_weather"
    assert choice.message.function_call.arguments == '{"city": "Osaka"}'


@pytest.mark.asyncio
async def test_chat_completion_function_call_forbidden_returns_text(monkeypatch):
    monkeypatch.setattr(main, "choose_model", lambda model: (model or "test", None))
    monkeypatch.setattr(main.settings, "local_only", False)

    async def fake_run_codex_last_message(*_, **__):
        return '{"function_call": {"name": "lookup_weather", "arguments": {"city": "Kyoto"}}}'

    monkeypatch.setattr(main, "run_codex_last_message", fake_run_codex_last_message)

    req = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="京都の天気")],
        functions=[
            FunctionDefinition(
                name="lookup_weather",
                description="現在の天気を取得する",
                parameters={"type": "object", "properties": {"city": {"type": "string"}}},
            )
        ],
        function_call="none",
    )

    response = await main.chat_completions(req)
    choice = response.choices[0]

    assert choice.finish_reason == "stop"
    assert choice.message.function_call is None
    assert '{"function_call"' in choice.message.content


def test_extract_function_call_payload_from_code_fence():
    text = """```json\n{"function_call": {"name": "lookup_weather", "arguments": {"city": "Tokyo"}}}\n```"""
    data, remainder = prompt.extract_function_call_payload(text)

    assert data == {"name": "lookup_weather", "arguments": '{"city": "Tokyo"}'}
    assert remainder == ""
