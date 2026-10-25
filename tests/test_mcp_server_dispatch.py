from __future__ import annotations

import json
import os
from pathlib import Path

from galet_tools.host.config import REGISTERED_TOOL_NAMES, GaletConfig
from galet_tools.mcp.server import McpScope, dispatch_call, resolve_startup_scope
from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2
from galet_tools.tools.file_load_handler2 import FileLoadHandler2
from tests.conftest import FakeSandboxResolver, FakeSecurityPolicy, FakeStorageResolver
from tests.mcp_stubs import RecordingHandler


def _config(tmp_path: Path) -> GaletConfig:
    root = Path(tmp_path)
    return GaletConfig(
        account="junwin",
        allowlist=[n for n in REGISTERED_TOOL_NAMES if n != "semantic_memory"],
        storage_root=str(root / "storage"),
        storage_namespace="galet",
        external_roots={},
        sandbox_root=str(root / "sandbox"),
        host="127.0.0.1",
        port=8765,
        fonts=[],
    )


def test_dispatch_recording_stub_success(tmp_path: Path) -> None:
    config = _config(tmp_path)
    RecordingHandler.SEEN.clear()
    handler = RecordingHandler()
    scope = McpScope(
        config=config,
        handlers={RecordingHandler.name(): handler},
        tool_names=frozenset([RecordingHandler.name()]),
    )
    args = {"key": "value", "n": 7}
    result = dispatch_call(scope, RecordingHandler.name(), args)
    assert result["isError"] is False
    assert RecordingHandler.SEEN == [{"args": args, "account_name": config.account}]
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["echo"] == args


def test_dispatch_file_load_over_fake_storage(tmp_path: Path) -> None:
    config = _config(tmp_path)
    resolver = FakeStorageResolver(str(tmp_path))
    handler = FileLoadHandler2(resolver)
    scope = McpScope(
        config=config,
        handlers={FileLoadHandler2.name(): handler},
        tool_names=frozenset([FileLoadHandler2.name()]),
    )
    rel_path = "notes/hello.txt"
    target = Path(resolver.storage_base_dir()) / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello from storage", encoding="utf-8")
    result = dispatch_call(
        scope,
        FileLoadHandler2.name(),
        {"location": "storage", "external_root": "", "path": rel_path},
    )
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["result"] == "hello from storage"
    assert payload["resolved_path"] == os.path.realpath(str(target))


def test_dispatch_execute_command_in_sandbox(tmp_path: Path) -> None:
    config = _config(tmp_path)
    storage = FakeStorageResolver(str(tmp_path))
    sandbox = FakeSandboxResolver(str(tmp_path))
    policy = FakeSecurityPolicy()
    handler = CommandExecutionHandler2(storage, sandbox, policy)
    scope = McpScope(
        config=config,
        handlers={CommandExecutionHandler2.name(): handler},
        tool_names=frozenset([CommandExecutionHandler2.name()]),
    )
    result = dispatch_call(
        scope,
        CommandExecutionHandler2.name(),
        {
            "location": "sandbox",
            "external_root": "",
            "command": "pwd",
            "working_directory": ".",
            "timeout_seconds": 30,
            "success_exit_codes": [0],
            "wrapper": "none",
        },
    )
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["returncode"] == 0
    expected_dir = os.path.realpath(str(Path(tmp_path) / "sandbox" / config.account))
    assert payload["resolved_working_directory"] == expected_dir
    assert payload["resolved_working_directory"].startswith(
        os.path.realpath(str(Path(tmp_path) / "sandbox"))
    )
    assert payload["result"] == payload["resolved_working_directory"]
    assert policy.calls == [("pwd", "none")]


def test_resolve_startup_scope_default_allowlist_round_trip(tmp_path: Path) -> None:
    config = _config(tmp_path)
    scope, mcp_tools = resolve_startup_scope(config)
    assert scope.tool_names == frozenset(n for n in REGISTERED_TOOL_NAMES if n != "semantic_memory")
    advertised_names = {tool["name"] for tool in mcp_tools}
    assert advertised_names == set(n for n in REGISTERED_TOOL_NAMES if n != "semantic_memory")
    save_result = dispatch_call(
        scope,
        "file_save",
        {
            "location": "storage",
            "external_root": "",
            "path": "roundtrip/demo.txt",
            "file_content": "round trip payload",
            "overwrite": True,
        },
    )
    assert save_result["isError"] is False
    save_payload = json.loads(save_result["content"][0]["text"])
    assert save_payload["ok"] is True
    load_result = dispatch_call(
        scope,
        "file_load",
        {"location": "storage", "external_root": "", "path": "roundtrip/demo.txt"},
    )
    assert load_result["isError"] is False
    load_payload = json.loads(load_result["content"][0]["text"])
    assert load_payload["ok"] is True
    assert load_payload["result"] == "round trip payload"
    assert load_payload["resolved_path"] == save_payload["resolved_path"]
