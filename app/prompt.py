from typing import List, Dict, Any


def _content_to_text(content: Any) -> str:
    """Best-effort conversion of message `content` into plain text.

    Supported variants:
    - str → as-is
    - list of {type:"text"|"input_text", text} → join text fields
    - list of str → join
    - any other → stringified
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Typed parts (OpenAI-style content parts)
        parts: List[str] = []
        for p in content:
            if isinstance(p, dict):
                t = p.get("type")
                if t in ("text", "input_text") and isinstance(p.get("text"), str):
                    parts.append(p["text"])
                # Ignore non-text parts for now (images, tool calls, etc.)
            elif isinstance(p, str):
                parts.append(p)
        if parts:
            return "".join(parts)
    # Fallback: stringify
    try:
        return str(content)
    except Exception:
        return ""


def build_prompt(messages: List[Dict[str, Any]]) -> str:
    """Convert chat messages into a single prompt string (robust to content variants)."""
    system_parts: List[str] = []
    convo: List[Dict[str, Any]] = []

    for m in messages:
        role = (m.get("role") or "").strip().lower()
        # Treat 'developer' as 'system' for compatibility
        normalized_role = "system" if role == "developer" else role
        text = _content_to_text(m.get("content"))
        if normalized_role == "system":
            if text:
                system_parts.append(text.strip())
        else:
            convo.append({"role": normalized_role or "user", "content": text})

    lines: List[str] = []
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
