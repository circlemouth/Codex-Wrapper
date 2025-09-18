import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.codex import ReasoningStreamFilter, strip_reasoning_text


def test_reasoning_stream_filter_passthrough():
    filt = ReasoningStreamFilter(include_reasoning=True)
    assert filt.process("Hello world\n") == "Hello world\n"


def test_reasoning_stream_filter_think_blocks_removed():
    filt = ReasoningStreamFilter(include_reasoning=False)
    assert filt.process("<think>internal step\n") is None
    assert filt.process("more thinking</think>\n") is None
    assert filt.process("Final answer\n") == "Final answer\n"


def test_reasoning_stream_filter_json_reasoning_removed():
    filt = ReasoningStreamFilter(include_reasoning=False)
    reasoning_json = '{"type": "reasoning", "text": "internal"}\n'
    assert filt.process(reasoning_json) is None


def test_reasoning_stream_filter_json_final_text():
    filt = ReasoningStreamFilter(include_reasoning=False)
    final_json = '{"type": "message", "text": "Final"}\n'
    assert filt.process(final_json) == "Final\n"


def test_strip_reasoning_text_think_block_removed():
    text = "<think>internal</think>\nAnswer"
    assert strip_reasoning_text(text, include_reasoning=False) == "Answer"


def test_strip_reasoning_text_json_removed():
    json_text = (
        '{"role":"assistant","content":['
        '{"type":"reasoning","text":"internal"},'
        '{"type":"output_text","text":"Answer"}'
        "]}"
    )
    assert strip_reasoning_text(json_text, include_reasoning=False) == "Answer"


def test_strip_reasoning_text_passthrough_when_enabled():
    text = "<think>internal</think>\nAnswer"
    assert strip_reasoning_text(text, include_reasoning=True) == text
