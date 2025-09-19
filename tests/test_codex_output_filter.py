from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import codex


SAMPLE_OUTPUT = """[2025-09-18T23:14:43] OpenAI Codex v0.36.0 (research preview)
workdir: /home/user/codex-workspace
model: gpt-5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, ] (network access enabled)
reasoning effort: high
reasoning summaries: detailed
[2025-09-18T23:14:43] User instructions:
Tell me the current weather.
Assistant:
 [2025-09-18T23:14:51] 🌐 Searched: weather: Kobe, Hyogo, Japan
[2025-09-18T23:15:14] codex

Current weather is cloudy, 24 C.

Let me know if you need hourly data.
[2025-09-18T23:15:15] tokens used: 12345
"""


EXPECTED_TEXT = "Current weather is cloudy, 24 C.\n\nLet me know if you need hourly data."


def test_sanitize_codex_text_removes_metadata():
    cleaned = codex._sanitize_codex_text(SAMPLE_OUTPUT)
    assert cleaned == EXPECTED_TEXT


def test_codex_output_filter_streaming():
    filt = codex._CodexOutputFilter()
    collected: list[str] = []
    for raw_line in SAMPLE_OUTPUT.splitlines(keepends=True):
        processed = filt.process(raw_line)
        if processed:
            collected.append(processed)
    assert "".join(collected).rstrip("\n") == EXPECTED_TEXT


def test_user_block_is_removed():
    filt = codex._CodexOutputFilter()
    lines = [
        "[2025-09-18T23:14:43] User instructions:\n",
        "今日の神戸の天気は？\n",
        "[2025-09-18T23:14:51] codex\n",
        "\n",
        "神戸の天気は快晴です。\n",
    ]
    out = [filt.process(line) for line in lines]
    rendered = "".join(part for part in out if part)
    assert rendered.strip() == "神戸の天気は快晴です。"
