from typing import List, Dict, Any


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


def normalize_responses_input(inp: Any) -> List[Dict[str, str]]:
    """Normalize Responses API `input` into OpenAI chat `messages`.

    Supported variants (minimal):
    - str → single user message
    - list of {type: "input_text", text} → concatenate text parts to single user
    - list of {role, content} (chat-like) → pass through
    - list of str → concatenate
    """
    # Case 1: plain string
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]

    # Case 2/3/4: list variants
    if isinstance(inp, list):
        # list of dict with type == input_text
        if inp and isinstance(inp[0], dict) and inp[0].get("type") == "input_text":
            text = "".join([str(part.get("text", "")) for part in inp])
            return [{"role": "user", "content": text}]

        # list of dict with role/content (chat-like)
        if all(isinstance(x, dict) and "role" in x and "content" in x for x in inp):
            # best-effort cast to str
            msgs: List[Dict[str, str]] = []
            for x in inp:
                role = str(x.get("role"))
                content = str(x.get("content", ""))
                msgs.append({"role": role, "content": content})
            return msgs

        # list of str → concatenate
        if all(isinstance(x, str) for x in inp):
            return [{"role": "user", "content": "".join(inp)}]

    # Unsupported
    raise ValueError("Unsupported input format for Responses API")
