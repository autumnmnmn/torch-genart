
import json
import re
import requests
import dataclasses
import typing
import os
from pathlib import Path
from typing import Any, Optional

from pyt.core.llm.chatlog import AttrDict, chatEntry, load_chatlog


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
        "additionalProperties": False
    }

_type_map = {
    int: toolprop_number,
    float: toolprop_number,
    str: toolprop_string,
    bool: toolprop_bool,
}

tp = AttrDict({
    "enum": toolprop_enum,
    "string": toolprop_string,
    "number": toolprop_number,
    "object": toolprop_object,
    "bool": toolprop_bool
})

def toolprop(default=dataclasses.MISSING, default_factory=dataclasses.MISSING, **kwargs):
    kw = {}
    if default is not dataclasses.MISSING: kw["default"] = default
    if default_factory is not dataclasses.MISSING: kw["default_factory"] = default_factory
    if "desc" in kwargs:
        kwargs["description"] = kwargs["desc"]
        del kwargs["desc"]
    return dataclasses.field(metadata={"toolprop_args": kwargs}, **kw)

def dataclass_to_toolprops(dc) -> tuple[dict, list[str]]:
    hints = typing.get_type_hints(dc)
    props = {}
    required = []
    for field in dataclasses.fields(dc):
        _type = hints[field.name]
        origin = typing.get_origin(_type)
        type_args = typing.get_args(_type)
        toolprop_args = field.metadata.get("toolprop_args", {})
        is_required = True

        if origin is typing.Literal:
            props[field.name] = toolprop_enum([*type_args], **toolprop_args)
        elif origin is typing.Union:
            non_none_args = [a for a in type_args if a is not type(None)]
            if len(non_none_args) == 1:
                is_required = False
                arg = non_none_args[0]
                origin = typing.get_origin(arg)
                if origin is typing.Literal:
                    type_args = typing.get_args(arg)
                    props[field.name] = toolprop_enum([*type_args], **toolprop_args)
                elif arg in _type_map:
                    props[field.name] = _type_map[arg](**toolprop_args)
                else:
                    raise TypeError(f"No tool property mapping for type {_type}")
            else:
                raise TypeError("General unions not supported as tool properties")
        elif _type in _type_map:
            props[field.name] = _type_map[_type](**toolprop_args)
        else:
            raise TypeError(f"No tool property mapping for type {_type}")
        if is_required:
            required.append(field.name)
    return props, required

def dataclass_to_tool(dc) -> dict:
    props, required = dataclass_to_toolprops(dc)
    return {
        "type": "function",
        "function": {
            "name": dc.__name__,#.replace('_', ' '),
            "description": dc.__doc__ or "",
            "parameters": toolprop_object(props, required)
        }
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
            "parameters": toolprop_object(properties)
        }
    }

_cached_openrouter_key = None
def _get_openrouter_key():
    global _cached_openrouter_key
    if _cached_openrouter_key is not None:
        return _cached_openrouter_key

    key_file = Path("/home/ponder/ponder/openrouter")
    if key_file.exists():
        _cached_openrouter_key = key_file.read_text().strip()
    else:
        # Fallback just in case!
        _cached_openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

    return _cached_openrouter_key


def tool_call(api, model, messages: List[Dict], tools: List[Dict], forced=False, jinja_args={}, **etc) -> Dict:
    api_key = _get_openrouter_key()
    try:
        response = requests.post(
            f"{api}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://ponder.ooo",
                "X-Title": "snakepyt"
            },
            json={
                "model": model,
                "messages": messages,
                "tools": tools,
                "chat_template_kwargs": { "enable_thinking": False, **jinja_args },
                "tool_choice": "required" if forced else "auto",
                **etc
            }
        )
        return response.json()
    except Exception as e:
        return {
            "error": "api call failed",
            "response": str(e)
        }

