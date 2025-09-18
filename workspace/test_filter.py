"""Manual harness retained for historical comparison.

Filtering logic was removed from the wrapper; the samples below now pass
through unchanged. Run this script to sanity-check how Codex CLI lines are
delivered when debugging streaming output.
"""

samples = [
    "2025/09/15 06:53:40",
    "User instructions:",
    "You are Obsidian Copilot, a helpful assistant...",
    "User: 君の名前は？",
    "Assistant:",
    "Assistant: 私は Obsidian Copilot です。よろしくお願いします。",
    "tokens used: 123",
]

for s in samples:
    print(s, "=>", repr(s))
