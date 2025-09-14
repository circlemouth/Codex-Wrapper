from typing import List, Dict


def build_prompt(messages: List[Dict[str, str]]) -> str:
    """Convert chat messages into a single prompt string."""
    system_parts = [m["content"].strip() for m in messages if m["role"] == "system"]
    convo = [m for m in messages if m["role"] != "system"]

    lines = []
    if system_parts:
        lines.append("\n".join(system_parts))
        lines.append("")

    for msg in convo:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content'].strip()}")

    lines.append("Assistant:")
    return "\n".join(lines)
