from typing import List, Dict, Any, Tuple


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
                # Ignore non-text parts (images, tool calls, etc.)
            elif isinstance(p, str):
                parts.append(p)
        if parts:
            return "".join(parts)
    # Fallback: stringify
    try:
        return str(content)
    except Exception:
        return ""


def _extract_images(content: Any) -> List[str]:
    """Extract image URLs from a message `content` structure."""
    images: List[str] = []
    if isinstance(content, list):
        for p in content:
            if isinstance(p, dict):
                t = p.get("type")
                if t in ("image_url", "input_image", "image"):
                    url_obj = p.get("image_url") or p.get("url")
                    if isinstance(url_obj, dict):
                        url = url_obj.get("url")
                    else:
                        url = url_obj
                    if isinstance(url, str):
                        images.append(url)
    return images


def build_prompt_and_images(messages: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """Convert chat messages into a prompt string and collect image URLs."""
    system_parts: List[str] = []
    convo: List[Dict[str, Any]] = []
    images: List[str] = []

    for m in messages:
        role = (m.get("role") or "").strip().lower()
        # Treat 'developer' as 'system' for compatibility
        normalized_role = "system" if role == "developer" else role
        content = m.get("content")
        images.extend(_extract_images(content))
        text = _content_to_text(content)
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
    return "\n".join(lines), images


def normalize_responses_input(inp: Any) -> List[Dict[str, Any]]:
    """Normalize Responses API `input` into OpenAI chat `messages`.

    Supported variants (minimal):
    - str → single user message
    - list of content parts (`input_text`/`input_image`/...) → single user message
    - list of {role, content} (chat-like) → pass through
    - list of str → concatenate
    """
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]

    if isinstance(inp, list):
        # list of dict with type field (content parts)
        if inp and isinstance(inp[0], dict) and "type" in inp[0] and "role" not in inp[0]:
            return [{"role": "user", "content": inp}]

        # list of dict with role/content (chat-like)
        if all(isinstance(x, dict) and "role" in x and "content" in x for x in inp):
            msgs: List[Dict[str, Any]] = []
            for x in inp:
                msgs.append({"role": str(x.get("role")), "content": x.get("content")})
            return msgs

        # list of str → concatenate
        if all(isinstance(x, str) for x in inp):
            return [{"role": "user", "content": "".join(inp)}]

    raise ValueError("Unsupported input format for Responses API")
