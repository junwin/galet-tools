from __future__ import annotations

from galet_tools.host.config import GaletConfig
from galet_tools.mcp.server import McpScope, dispatch_call, resolve_startup_scope
from tests.mcp_stubs import BoomHandler, RecordingHandler, StringResultHandler

ALL_REGISTERED = [
    "file_load",
    "file_save",
    "patch_apply",
    "execute_command",
    "generate_svg",
    "generate_image",
]


def _config(tmp_path, *, allowlist=None):
    return GaletConfig(
        account="tester",
        allowlist=ALL_REGISTERED if allowlist is None else allowlist,
        storage_root=str(tmp_path / "storage"),
        storage_namespace="test",
        external_roots={},
        sandbox_root=str(tmp_path / "sandbox"),
        host="127.0.0.1",
        port=8765,
        fonts=[],
    )


def _stub_scope(config):
    return McpScope(
        config=config,
        handlers={
            "mcp_boom_tool": BoomHandler(),
            "mcp_str_tool": StringResultHandler(),
            "mcp_rec_tool": RecordingHandler(),
        },
        tool_names=frozenset({"mcp_boom_tool", "mcp_rec_tool", "mcp_str_tool"}),
    )


def _text(result):
    return result["content"][0]["text"]


def test_dispatch_handler_raise_maps_to_error_result(tmp_path):
    scope = _stub_scope(_config(tmp_path))
    result = dispatch_call(scope, "mcp_boom_tool", {})
    assert result["isError"] is True
    assert _text(result) == "ValueError: boom"


def test_dispatch_non_dict_result_maps_to_error_result(tmp_path):
    scope = _stub_scope(_config(tmp_path))
    result = dispatch_call(scope, "mcp_str_tool", {})
    assert result["isError"] is True
    assert "expected a structured dict" in _text(result)


def test_dispatch_unknown_tool_lists_valid_tools(tmp_path):
    scope = _stub_scope(_config(tmp_path))
    result = dispatch_call(scope, "ghost_tool", {})
    text = _text(result)
    assert result["isError"] is True
    assert "Unknown tool 'ghost_tool'" in text
    assert "mcp_boom_tool" in text
    assert "mcp_rec_tool" in text
    assert "mcp_str_tool" in text


def test_dispatch_registered_but_not_advertised_tool_is_unknown(tmp_path):
    scope, _ = resolve_startup_scope(_config(tmp_path, allowlist=["file_load"]))
    assert "generate_svg" in scope.handlers
    assert "generate_svg" not in scope.tool_names
    result = dispatch_call(scope, "generate_svg", {})
    assert result["isError"] is True
    assert "Unknown tool" in _text(result)
