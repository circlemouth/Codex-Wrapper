import json
from typing import List, Dict, Any, Tuple, Optional


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


def _render_function_catalog(
    functions: List[Dict[str, Any]],
    forced_function_call: Optional[str] = None,
    function_call_disabled: bool = False,
) -> str:
    lines: List[str] = []
    lines.append(
        "You have access to the following callable functions. When you call one, "
        "respond ONLY with JSON of the form {\"function_call\": {\"name\": \"<name>\", "
        "\"arguments\": <JSON object>}} with arguments as valid JSON."
    )
    if function_call_disabled:
        lines.append("Do not call any function; return a natural-language answer instead.")
    elif forced_function_call:
        lines.append(f"You must call the function '{forced_function_call}' in your next reply.")
    for func in functions:
        name = func.get("name", "unknown")
        desc = func.get("description")
        params = func.get("parameters") or {}
        lines.append(f"Function: {name}")
        if desc:
            lines.append(f"  Description: {desc}")
        params_text = json.dumps(params, ensure_ascii=False, indent=2)
        lines.append("  Parameters JSON Schema:")
        for line in params_text.splitlines():
            lines.append(f"    {line}")
    return "\n".join(lines)


def _format_function_call_line(call: Dict[str, Any]) -> str:
    arguments = call.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            pass
    payload = {
        "name": call.get("name"),
        "arguments": arguments,
    }
    return json.dumps({"function_call": payload}, ensure_ascii=False)


def _format_tool_result_line(name: Optional[str], content: str) -> str:
    label = name or "tool"
    return f"Tool {label} result: {content.strip()}"


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_function_call_payload(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Detect function_call JSON payload in model output.

    Returns (function_call, remaining_text).
    """

    original_text = text
    stripped = original_text.strip()
    if not stripped:
        return None, original_text

    candidate_strings = [stripped, _strip_code_fence(stripped)]

    for candidate in candidate_strings:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        function_call: Optional[Dict[str, Any]] = None
        if isinstance(parsed, dict):
            if "function_call" in parsed and isinstance(parsed["function_call"], dict):
                function_call = parsed["function_call"].copy()
            elif "name" in parsed and "arguments" in parsed:
                function_call = {"name": parsed.get("name"), "arguments": parsed.get("arguments")}

        if function_call and function_call.get("name"):
            arguments = function_call.get("arguments", {})
            if not isinstance(arguments, str):
                try:
                    function_call["arguments"] = json.dumps(arguments, ensure_ascii=False)
                except (TypeError, ValueError):
                    function_call["arguments"] = str(arguments)
            return function_call, ""

    return None, original_text


def build_prompt_and_images(
    messages: List[Dict[str, Any]],
    functions: Optional[List[Dict[str, Any]]] = None,
    forced_function_call: Optional[str] = None,
    function_call_disabled: bool = False,
) -> Tuple[str, List[str]]:
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
            continue

        if normalized_role in ("tool", "function"):
            convo.append(
                {
                    "role": "tool",
                    "name": m.get("name"),
                    "content": text,
                }
            )
            continue

        function_call = m.get("function_call")
        if normalized_role == "assistant" and function_call:
            convo.append(
                {
                    "role": "assistant_function_call",
                    "name": function_call.get("name"),
                    "arguments": function_call.get("arguments"),
                }
            )
        else:
            convo.append({"role": normalized_role or "user", "content": text})

    lines: List[str] = []
    if system_parts:
        lines.append("\n".join(system_parts))
        lines.append("")

    if functions:
        lines.append(
            _render_function_catalog(
                functions,
                forced_function_call=forced_function_call,
                function_call_disabled=function_call_disabled,
            )
        )
        lines.append("")

    for msg in convo:
        role = msg["role"]
        if role == "assistant_function_call":
            lines.append(f"Assistant (function call): {_format_function_call_line(msg)}")
        elif role == "tool":
            lines.append(_format_tool_result_line(msg.get("name"), msg.get("content", "")))
        else:
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {msg['content'].strip()}")

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
