from __future__ import annotations

import json

import pytest

from galet_tools.host.config import (
    REGISTERED_TOOL_NAMES,
    GaletConfig,
    GaletConfigError,
)
from galet_tools.mcp.server import (
    GaletMcpError,
    build_registry,
    exposed_tools,
    main,
    resolve_startup_scope,
    serve,
)


def _config(tmp_path, **overrides):
    values = {
        "account": "junwin",
        "allowlist": list(REGISTERED_TOOL_NAMES),
        "storage_root": str(tmp_path / "storage"),
        "storage_namespace": "galet",
        "external_roots": {},
        "sandbox_root": str(tmp_path / "sandbox"),
        "host": "127.0.0.1",
        "port": 8765,
        "fonts": [],
    }
    values.update(overrides)
    return GaletConfig(**values)


def _write_config(tmp_path, **overrides):
    data = {
        "account": "junwin",
        "storage_root": str(tmp_path / "storage"),
        "storage_namespace": "galet",
        "sandbox_root": str(tmp_path / "sandbox"),
        "allowlist": list(REGISTERED_TOOL_NAMES),
    }
    data.update(overrides)
    path = tmp_path / "galet-mcp.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _registered_names(registry):
    return {tool["name"] for tool in registry.tools()}


def test_exposed_tools_returns_only_allowlist_intersection():
    registry = build_registry()
    registered = _registered_names(registry)
    allowlist = ["file_load", "file_save"]
    exposed = exposed_tools(registry, allowlist)
    assert [tool["name"] for tool in exposed] == [
        name for name in allowlist if name in registered
    ]


def test_registered_but_not_allowed_tools_are_excluded():
    registry = build_registry()
    registered = sorted(_registered_names(registry))
    allowlist = [registered[0]]
    exposed_names = {tool["name"] for tool in exposed_tools(registry, allowlist)}
    assert exposed_names == {registered[0]}
    assert set(registered) - exposed_names == set(registered[1:])


def test_unknown_allowlist_names_are_dropped():
    registry = build_registry()
    registered = _registered_names(registry)
    exposed = exposed_tools(registry, list(registered) + ["ghost_tool"])
    assert {tool["name"] for tool in exposed} == registered


def test_empty_allowlist_exposes_nothing():
    registry = build_registry()
    assert exposed_tools(registry, []) == []


@pytest.mark.parametrize("allowlist", [[], ["ghost_tool"]])
def test_resolve_startup_scope_refuses_when_nothing_exposed(tmp_path, allowlist):
    with pytest.raises(GaletMcpError, match="refusing to start"):
        resolve_startup_scope(_config(tmp_path, allowlist=allowlist))


def test_scope_tool_names_match_advertised_tools(tmp_path):
    scope, mcp_tools = resolve_startup_scope(_config(tmp_path))
    assert mcp_tools
    assert set(scope.tool_names) == {tool["name"] for tool in mcp_tools}
    assert set(scope.handlers) == set(REGISTERED_TOOL_NAMES)
    assert "execute_command2" in scope.tool_names
    assert "execute_command" not in scope.tool_names
    for tool in mcp_tools:
        assert set(tool) == {"name", "description", "inputSchema"}


def test_serve_missing_config_raises_before_sdk_import(tmp_path):
    with pytest.raises(GaletConfigError, match="config file not found"):
        serve(str(tmp_path / "missing.json"))


@pytest.mark.parametrize("allowlist", [[], ["ghost_tool"]])
def test_serve_invalid_allowlist_raises_before_sdk_import(tmp_path, allowlist):
    with pytest.raises(GaletConfigError, match="allowlist"):
        serve(_write_config(tmp_path, allowlist=allowlist))


def test_main_missing_config_returns_2_and_prints_stderr(tmp_path, capsys):
    rc = main(["--config", str(tmp_path / "missing.json")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "galet-mcp:" in captured.err
