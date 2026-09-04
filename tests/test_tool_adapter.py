"""Translation conformance tests for ``galet_tools.mcp.tool_adapter``.

Pure/offline: no MCP SDK, no network, no server process. Registry coverage
runs against the real generic registry (``register_generic_defaults``) so any
future handler whose ``tool_def()`` stops translating losslessly to an MCP
tool fails CI. Mirrors Lucy's ``tests/test_tool_adapter.py`` on the
galet-tools adapter.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.mcp.tool_adapter import (
    error_result,
    handler_tool_def_to_mcp,
    success_result,
    text_content,
)
from galet_tools.register_generic_defaults import register_generic_defaults

_MCP_TOOL_KEYS = frozenset({"name", "description", "inputSchema"})

_SOURCE_FIELDS = ("name", "description", "parameters")

_FLAT_TOOL_DEF: Dict[str, Any] = {
    "type": "function",
    "name": "alpha_tool",
    "description": "alpha handler",
    "parameters": {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    },
    "strict": True,
}


@pytest.fixture(scope="module")
def real_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_generic_defaults(registry)
    return registry


def _source_def(tool_def: Dict[str, Any]) -> Dict[str, Any]:
    function = tool_def.get("function")
    return function if isinstance(function, dict) else tool_def


class _StubToolHandler(HandlerV2):
    """Stub handler whose name() collides in the duplicate-name tests."""

    NAME = "stub_dup_tool"

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": "stub handler for duplicate-name tests",
            "parameters": {"type": "object", "properties": {}},
        }

    def execute(
        self, args: Dict[str, Any], *, account_name: str = "auto", **context
    ) -> Dict[str, Any]:
        return {"ok": True}


class _StubToolHandlerLookalike(_StubToolHandler):
    """Second handler class that deliberately collides on ``name()``."""


class TestRegistryConformance:
    """Every registered handler translates losslessly; duplicates cannot surface."""

    def test_all_registered_tool_defs_translate_losslessly(self, real_registry: HandlerRegistry) -> None:
        tool_defs = real_registry.tools()
        assert tool_defs, "conformance over an empty registry would be vacuous"

        mcp_names = []
        for tool_def in tool_defs:
            source = _source_def(tool_def)

            missing = [k for k in _SOURCE_FIELDS if k not in source]
            assert not missing, (
                f"registered tool_def {source.get('name')!r} missing source "
                f"field(s) {missing}; translation would not be lossless"
            )

            mcp_tool = handler_tool_def_to_mcp(tool_def)

            assert set(mcp_tool) == _MCP_TOOL_KEYS
            assert isinstance(mcp_tool["name"], str) and mcp_tool["name"]
            assert isinstance(mcp_tool["description"], str)
            assert isinstance(mcp_tool["inputSchema"], dict)

            assert mcp_tool["name"] == source["name"]
            assert mcp_tool["description"] == source["description"]
            assert mcp_tool["inputSchema"] == source["parameters"]
            assert mcp_tool["inputSchema"] is not source["parameters"]

            mcp_names.append(mcp_tool["name"])

        assert len(mcp_names) == len(tool_defs)
        assert sorted(mcp_names) == real_registry.tool_names()

    def test_duplicate_defs_rejected_and_translation_idempotent(self, real_registry: HandlerRegistry) -> None:
        registry = HandlerRegistry()
        registry.register(_StubToolHandler)
        with pytest.raises(ValueError, match="Duplicate handler name registered"):
            registry.register(_StubToolHandler)
        with pytest.raises(ValueError, match="Duplicate handler name registered"):
            registry.register(_StubToolHandlerLookalike)
        assert registry.tool_names() == [_StubToolHandler.NAME]

        tool_defs = real_registry.tools()
        assert tool_defs

        translated_once = [handler_tool_def_to_mcp(d) for d in tool_defs]
        translated_twice = [handler_tool_def_to_mcp(d) for d in real_registry.tools()]
        assert translated_once == translated_twice

        mcp_names = [tool["name"] for tool in translated_once]
        assert len(mcp_names) == len(set(mcp_names)) == len(real_registry.tool_names())
        assert sorted(mcp_names) == real_registry.tool_names()

        first = handler_tool_def_to_mcp(tool_defs[0])
        second = handler_tool_def_to_mcp(tool_defs[0])
        assert first == second
        first["inputSchema"]["_probe"] = True
        assert handler_tool_def_to_mcp(tool_defs[0]) == second


class TestLayoutRules:
    """Flat and nested ``function`` tool_def layouts translate; defaults apply."""

    def test_flat_tool_def_layout_translates(self) -> None:
        mcp_tool = handler_tool_def_to_mcp(_FLAT_TOOL_DEF)
        assert set(mcp_tool) == _MCP_TOOL_KEYS
        assert mcp_tool["name"] == "alpha_tool"
        assert mcp_tool["description"] == "alpha handler"
        assert mcp_tool["inputSchema"] == _FLAT_TOOL_DEF["parameters"]
        assert mcp_tool["inputSchema"] is not _FLAT_TOOL_DEF["parameters"]

    def test_nested_function_layout_wins_when_present(self) -> None:
        tool_def = {
            "type": "function",
            "name": "outer_name",
            "description": "outer description",
            "parameters": {"type": "object", "properties": {"outer": {"type": "string"}}},
            "function": {
                "name": "inner_name",
                "description": "inner description",
                "parameters": {"type": "object", "properties": {"inner": {"type": "integer"}}},
            },
        }
        mcp_tool = handler_tool_def_to_mcp(tool_def)
        assert mcp_tool == {
            "name": "inner_name",
            "description": "inner description",
            "inputSchema": {"type": "object", "properties": {"inner": {"type": "integer"}}},
        }

    def test_missing_description_defaults_to_empty_string(self) -> None:
        mcp_tool = handler_tool_def_to_mcp({"name": "bare_tool", "parameters": {}})
        assert mcp_tool["description"] == ""

    def test_missing_parameters_defaults_to_empty_schema(self) -> None:
        mcp_tool = handler_tool_def_to_mcp({"name": "bare_tool", "description": "d"})
        assert mcp_tool["inputSchema"] == {}

    def test_input_schema_is_a_deep_copy(self) -> None:
        tool_def = {
            "name": "copy_tool",
            "description": "d",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string", "description": "query"}},
            },
        }
        first = handler_tool_def_to_mcp(tool_def)
        second = handler_tool_def_to_mcp(tool_def)

        first["inputSchema"]["properties"]["q"]["description"] = "mutated"
        first["inputSchema"]["properties"]["extra"] = {"type": "string"}

        assert second == handler_tool_def_to_mcp(tool_def)
        assert tool_def["parameters"]["properties"]["q"]["description"] == "query"
        assert "extra" not in tool_def["parameters"]["properties"]


class TestTranslationErrors:
    """Defs that cannot translate losslessly raise ValueError with a clear message."""

    def test_non_dict_tool_def_rejected(self) -> None:
        with pytest.raises(ValueError, match="tool_def must be a dict"):
            handler_tool_def_to_mcp("not-a-dict")
        with pytest.raises(ValueError, match="tool_def must be a dict"):
            handler_tool_def_to_mcp(["name"])

    def test_missing_or_blank_name_rejected(self) -> None:
        for bad in (None, "", "   "):
            with pytest.raises(ValueError, match="non-empty string"):
                handler_tool_def_to_mcp({"name": bad})
        with pytest.raises(ValueError, match="non-empty string"):
            handler_tool_def_to_mcp({})

    def test_non_string_description_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            handler_tool_def_to_mcp({"name": "alpha_tool", "description": 42})

    def test_non_dict_parameters_rejected(self) -> None:
        with pytest.raises(ValueError, match="JSON Schema dict"):
            handler_tool_def_to_mcp(
                {"name": "alpha_tool", "description": "d", "parameters": "not-a-schema"}
            )


class TestResultErrorMapping:
    """text_content / success_result / error_result MCP result shapes."""

    def test_text_content_requires_string(self) -> None:
        assert text_content("hi") == {"type": "text", "text": "hi"}
        for bad in (None, 42, ["hi"]):
            with pytest.raises(ValueError, match="MCP text content must be a string"):
                text_content(bad)

    def test_success_result_shape(self) -> None:
        assert success_result("ok") == {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
        }

    def test_error_result_shape(self) -> None:
        assert error_result("boom") == {
            "content": [{"type": "text", "text": "boom"}],
            "isError": True,
        }
