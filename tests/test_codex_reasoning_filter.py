from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import codex


SAMPLE_LINES = [
    "[2025-09-15T06:53:40] thinking\n",
    "\n",
    "First reasoning step\n",
    "Second reasoning step\n",
    "[2025-09-15T06:53:42] codex\n",
    "\n",
    "Final answer line\n",
]


def _collect_output(lines, expose_reasoning):
    suppressor = codex._ReasoningSuppressor(expose_reasoning)
    emitted: list[str] = []
    for raw in lines:
        if suppressor.should_skip(raw):
            continue
        cleaned = codex.filter_codex_stdout_line(raw)
        if cleaned:
            emitted.append(cleaned)
    return emitted


def test_reasoning_visible_when_enabled():
    output = _collect_output(SAMPLE_LINES, expose_reasoning=True)
    assert output == [
        "thinking\n",
        "\n",
        "First reasoning step\n",
        "Second reasoning step\n",
        "\n",
        "\n",
        "Final answer line\n",
    ]


def test_reasoning_hidden_when_disabled():
    output = _collect_output(SAMPLE_LINES, expose_reasoning=False)
    assert output == ["\n", "Final answer line\n"]


def test_words_starting_with_thinking_are_preserved():
    lines = [
        "[2025-09-15T06:53:42] codex\n",
        "\n",
        "thinking about the result\n",
    ]
    output = _collect_output(lines, expose_reasoning=False)
    assert output == ["\n", "\n", "thinking about the result\n"]
