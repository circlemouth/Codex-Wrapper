from app.codex import filter_codex_stdout_line

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
    print(s, '=>', repr(filter_codex_stdout_line(s)))
