# src/mcp/tool_adapter.py
"""Pure translation between Lucy handler tool defs and MCP tool schemas.

This module is deliberately I/O-free: it contains mapping rules only (design
doc ``docs/design/mcp-handlerregistry.md``, Decision 2 and the result/error
mapping). No registry, no config, no handler execution, no network.

Mapping (OpenAI/Responses ``tool_def()`` -> MCP tool)::

    tool_def field            MCP tool field
    ------------------------  -----------------
    name                      name
    description               description
    parameters (JSON Schema)  inputSchema

The parameters block is already JSON Schema, so the translation is structural,
not semantic: ``inputSchema`` is the handler's ``parameters`` verbatim. Any
extra ``tool_def()`` keys (``type``, ``strict``, ...) are not part of an MCP
tool and are dropped.

Two ``tool_def()`` layouts are accepted, because both have existed in Lucy's
handler family:

- flat Responses style (current code reality, all ~23 handlers):
  ``{"type": "function", "name": ..., "description": ..., "parameters": ...}``
- Chat-Completions style wrapper (HandlerV2 docstring / design table):
  ``{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}``

When the nested ``function`` dict is present it wins; otherwise the top level
is read directly.

Result/error mapping (MCP ``CallToolResult`` with text content)::

    handler result text        -> {"content": [{"type": "text", "text": ...}],
                                   "isError": False}
    handler error message      -> {"content": [{"type": "text", "text": ...}],
                                   "isError": True}

``isError`` follows the FCP semantics: a handler that runs and returns a
structured dict -- including a dict such as ``{"ok": False, "error": ...}`` --
is a *result* (plain text content). ``isError=True`` is reserved for execution
failures (handler exceptions / executor errors), which must surface to the MCP
client as an error result rather than a transport failure.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

# MCP tool schema field name for the translated JSON-Schema parameters block.
_MCP_INPUT_SCHEMA_KEY = "inputSchema"

# MCP text content discriminator.
_TEXT_CONTENT_TYPE = "text"

# Keys consumed from a flat tool_def / nested function dict.
_NAME_KEY = "name"
_DESCRIPTION_KEY = "description"
_PARAMETERS_KEY = "parameters"


def handler_tool_def_to_mcp(tool_def: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a Lucy ``HandlerV2.tool_def()`` into an MCP tool definition.

    The result is ``{"name", "description", "inputSchema"}`` with
    ``inputSchema`` being a deep copy of the handler's ``parameters`` block, so
    later MCP-side mutation can never alias back into registry-owned defs.

    Raises ``ValueError`` with a clear message when the def cannot be
    translated losslessly (missing/invalid name, non-string description,
    non-dict parameters).
    """
    if not isinstance(tool_def, dict):
        raise ValueError(
            f"tool_def must be a dict, got {type(tool_def).__name__}"
        )

    source = tool_def.get("function")
    if not isinstance(source, dict):
        source = tool_def

    name = source.get(_NAME_KEY)
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            f"MCP tool name must be a non-empty string, got {name!r} "
            f"(tool_def keys: {sorted(tool_def.keys())})"
        )

    if _DESCRIPTION_KEY in source:
        description = source.get(_DESCRIPTION_KEY)
        if not isinstance(description, str):
            raise ValueError(
                f"description for tool {name!r} must be a string, "
                f"got {type(description).__name__}"
            )
    else:
        # Same default as the MCP pseudo-code on #157: absent description
        # maps to an empty string rather than failing the translation.
        description = ""

    if _PARAMETERS_KEY in source:
        parameters = source.get(_PARAMETERS_KEY)
        if not isinstance(parameters, dict):
            raise ValueError(
                f"parameters for tool {name!r} must be a JSON Schema dict, "
                f"got {type(parameters).__name__}"
            )
    else:
        # Empty object schema: accepts any arguments (JSON Schema default).
        parameters = {}

    return {
        _NAME_KEY: name,
        _DESCRIPTION_KEY: description,
        _MCP_INPUT_SCHEMA_KEY: copy.deepcopy(parameters),
    }


def text_content(text: str) -> Dict[str, Any]:
    """Build an MCP ``TextContent`` block from a string."""
    if not isinstance(text, str):
        raise ValueError(
            f"MCP text content must be a string, got {type(text).__name__}"
        )
    return {"type": _TEXT_CONTENT_TYPE, "text": text}


def success_result(text: str) -> Dict[str, Any]:
    """Map a handler result (as text) to an MCP ``CallToolResult``.

    The handler executed and produced a result, so ``isError`` is ``False``.
    """
    return {"content": [text_content(text)], "isError": False}


def error_result(message: str) -> Dict[str, Any]:
    """Map a handler/executor failure to an MCP ``CallToolResult``.

    The failure is reported as MCP text content with ``isError=True`` so the
    client sees a tool error result instead of a transport-level failure.
    """
    return {"content": [text_content(message)], "isError": True}
