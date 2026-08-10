
import os
import types
import dataclasses
import typing
import requests
from pathlib import Path
from typing import Any, Optional, List, Dict

from pyt.core.llm.chatlog import AttrDict, chatEntry, load_chatlog

def _sanitize_messages(messages):
    """Return a copy of *messages* enforcing strict OpenAI tool-message ordering
    (some providers, e.g. Moonshot, 400 on violations). Repairs, without mutating
    the caller's list: unanswered ``tool_call_id``s get a synthetic tool result,
    and orphan tool messages (id never requested) are folded into system messages
    so no information is lost. Well-formed payloads pass through unchanged.
    """
    out = []
    pending = []  # unanswered tool_call_ids from the most recent assistant

    def flush():
        for cid in pending:
            out.append({"role": "tool", "tool_call_id": cid,
                        "content": "(no tool result was delivered for this "
                                   "call; inserted to keep the request valid)"})
        pending.clear()

    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            flush()
            for call in msg["tool_calls"]:
                cid = call.get("id")
                if isinstance(cid, str) and cid:
                    pending.append(cid)
            out.append(msg)
        elif role == "tool":
            cid = msg.get("tool_call_id")
            if cid in pending:
                pending.remove(cid)
                out.append(msg)
            else:
                out.append({"role": "system",
                            "content": f"[orphan tool result] {msg.get('content', '')}"})
        else:
            flush()
            out.append(msg)
    flush()
    return out

def toolprop_enum(options: list[str], **etc) -> dict:
    return {**etc, "type": "string", "enum": options}

def toolprop_string(**etc) -> dict:
    return {**etc, "type": "string"}

def toolprop_number(**etc) -> dict:
    return {**etc, "type": "number"}

def toolprop_bool(**etc) -> dict:
    return {**etc, "type": "boolean"}

def toolprop_object(properties: dict, required: list[str], **etc) -> dict:
    return {
        **etc,
        "properties": properties,
        "required": required,
        "type": "object",
        "additionalProperties": False,
    }

_type_map = {
    int: toolprop_number,
    float: toolprop_number,
    str: toolprop_string,
    bool: toolprop_bool,
}

tp = AttrDict({
    "enum":   toolprop_enum,
    "string": toolprop_string,
    "number": toolprop_number,
    "object": toolprop_object,
    "bool":   toolprop_bool,
})

def toolprop(default=dataclasses.MISSING,
             default_factory=dataclasses.MISSING,
             **kwargs):
    kw = {}
    if default is not dataclasses.MISSING:
        kw["default"] = default
    if default_factory is not dataclasses.MISSING:
        kw["default_factory"] = default_factory
    if "desc" in kwargs:
        kwargs["description"] = kwargs["desc"]
        del kwargs["desc"]
    return dataclasses.field(metadata={"toolprop_args": kwargs}, **kw)

def _map_type(_type, toolprop_args: dict) -> dict:
    """Recursive helper to map a python type to a JSON schema tool property."""
    origin = typing.get_origin(_type)
    type_args = typing.get_args(_type)

    if origin is typing.Literal:
        return toolprop_enum([*type_args], **toolprop_args)
    elif origin in (list, typing.List):
        inner_type = type_args[0] if type_args else str
        inner_schema = _map_type(inner_type, {})
        return {"type": "array", "items": inner_schema, **toolprop_args}
    elif _type in _type_map:
        return _type_map[_type](**toolprop_args)
    else:
        raise TypeError(f"No tool property mapping for type {_type}")

def dataclass_to_toolprops(dc) -> tuple[dict, list[str]]:
    hints = typing.get_type_hints(dc)
    props: dict = {}
    required: list[str] = []
    for field in dataclasses.fields(dc):
        _type = hints[field.name]
        origin = typing.get_origin(_type)
        type_args = typing.get_args(_type)
        toolprop_args = field.metadata.get("toolprop_args", {})
        is_required = True

        is_union = origin is typing.Union or origin is types.UnionType

        if is_union:
            non_none_args = [a for a in type_args if a is not type(None)]
            if len(non_none_args) == 1:
                is_required = False
                props[field.name] = _map_type(non_none_args[0], toolprop_args)
            else:
                raise TypeError("General unions not supported as tool properties")
        else:
            props[field.name] = _map_type(_type, toolprop_args)

        if is_required:
            required.append(field.name)
    return props, required

def dataclass_to_tool(dc) -> dict:
    props, required = dataclass_to_toolprops(dc)
    return {
        "type": "function",
        "function": {
            "name": dc.__name__,
            "description": dc.__doc__ or "",
            "parameters": toolprop_object(props, required),
        },
    }

def tool(c=None, *, desc=None):
    def decorator(c):
        dc = dataclasses.dataclass(c)
        if desc:
            dc.__doc__ = desc
        dc.tool = dataclass_to_tool(dc)
        return dc
    return decorator(c) if c is not None else decorator

def _tool(name: str, description: str, properties: Dict) -> Dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": toolprop_object(properties, []),
        },
    }

_cached_openrouter_key: Optional[str] = None

def _get_openrouter_key() -> str:
    global _cached_openrouter_key
    if _cached_openrouter_key is not None:
        return _cached_openrouter_key

    key_file = Path("/home/ponder/ponder/openrouter")
    if key_file.exists():
        _cached_openrouter_key = key_file.read_text().strip()
    else:
        _cached_openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

    return _cached_openrouter_key

def tool_call(api, model, messages: List[Dict], tools: List[Dict],
              forced=False, jinja_args={}, request_timeout=None, **etc) -> Dict:
    api_key = _get_openrouter_key()
    try:
        response = requests.post(
            f"{api}/v1/chat/completions",
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer":  "https://ponder.ooo",
                "X-Title":       "snakepyt",
            },
            json={
                "model": model,
                "messages": _sanitize_messages(messages),
                "tools": tools,
                "chat_template_kwargs": {
                    "enable_thinking": False,
                    **jinja_args,
                },
                "tool_choice": "required" if forced else "auto",
                **etc,
            },
            timeout=request_timeout,
        )
    except Exception as e:
        # request-level failure (network, timeout, ...): structured so callers
        # can classify; no "code" means retryable at the caller's discretion.
        return {"error": {"message": f"api call failed: {e}"}}
    try:
        return response.json()
    except Exception:
        # non-JSON body (e.g. a proxy/gateway HTML error page): keep the HTTP
        # status so callers can classify instead of guessing.
        return {"error": {"message": f"HTTP {response.status_code}: non-JSON "
                                     f"response: {response.text[:300]}",
                          "code": response.status_code}}

