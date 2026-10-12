"""Named roots are host-defined aliases, without implicit account/namespace joins."""

import json
import shlex
import sys

import pytest

from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2
from galet_tools.tools.execute_command2 import ExecuteCommand2
from galet_tools.tools.file_load_handler2 import FileLoadHandler2
from galet_tools.tools.file_save_handler import FileSaveHandler2
from galet_tools.tools.patch_apply_handler import PatchApplyHandler2
from galet_tools.tools.repo_index_handler import RepoIndexHandler
from galet_tools.tools.repo_search_handler import RepoSearchHandler
from tests.conftest import FakeSecurityPolicy


class NamedOnlyResolver:
    def __init__(self, name, base):
        self.name, self.base = name, str(base)
        self.calls = []

    def external_root_dir(self, name):
        self.calls.append(name)
        if name != self.name:
            raise ValueError(f"Unknown configured root: {name}")
        return self.base

    def storage_base_dir(self):
        raise AssertionError("Named roots must not select legacy storage")

    def sandbox_base_dir(self, *, account_name):
        raise AssertionError("Named roots must not select the account sandbox")


HANDLERS = [FileLoadHandler2, FileSaveHandler2, PatchApplyHandler2,
            RepoIndexHandler, RepoSearchHandler, CommandExecutionHandler2, ExecuteCommand2]


def _make(cls, resolver):
    if cls in (CommandExecutionHandler2, ExecuteCommand2):
        return cls(resolver, resolver, FakeSecurityPolicy())
    return cls(resolver)


def _args(cls, name):
    args = {"external_root": name}
    if cls is FileLoadHandler2:
        args.update(path="namespace/alice/file.txt", start_line=None,
                    line_count=None, include_line_numbers=False)
    elif cls is FileSaveHandler2:
        args.update(path="namespace/alice/saved.txt", file_content="saved", overwrite=False)
    elif cls is PatchApplyHandler2:
        args.update(path="namespace/alice/file.txt", check_only=False,
                    patch_content="--- namespace/alice/file.txt\n+++ namespace/alice/file.txt\n@@ -1 +1 @@\n-old\n+new\n")
    elif cls is RepoIndexHandler:
        args.update(root="namespace/alice", operation="map", query="", include_tests=False)
    elif cls is RepoSearchHandler:
        args.update(root="namespace/alice", query="hello", limit=10, include_tests=False)
    elif cls is ExecuteCommand2:
        args.update(mode="process", executable=sys.executable,
                    arguments=["-c", "import os; print(os.getcwd())"], script="", shell="none",
                    working_directory="namespace/alice", timeout_seconds=10, success_exit_codes=[0])
    else:
        args.update(command=f'{shlex.quote(sys.executable)} -c "import os; print(os.getcwd())"',
                    working_directory="namespace/alice", timeout_seconds=10,
                    success_exit_codes=[0], wrapper="none")
    return args


@pytest.mark.parametrize("cls", HANDLERS)
@pytest.mark.parametrize("name", ["Pishare", "sandbox", "storage", "lucy_data_files", "My Root"])
@pytest.mark.parametrize("raw", [False, True])
def test_root_only_call_uses_exact_alias_and_explicit_subdirectories(tmp_path, cls, name, raw):
    directory = tmp_path / "namespace/alice"
    directory.mkdir(parents=True)
    (directory / "file.txt").write_text("old\n")
    (directory / "hello.py").write_text("def hello():\n    pass\n")
    resolver = NamedOnlyResolver(name, tmp_path)
    handler = _make(cls, resolver)
    args = _args(cls, name)
    result = (json.loads(handler.execute_raw(json.dumps(args), account_name="different-account"))
              if raw and hasattr(handler, "execute_raw")
              else handler.execute(args, account_name="different-account"))
    assert result["ok"] is True, result
    assert resolver.calls == [name]
    if cls in (CommandExecutionHandler2, ExecuteCommand2):
        assert result["stdout"].strip() == str(directory)
    if cls is PatchApplyHandler2:
        assert (directory / "file.txt").read_text() == "new\n"
    if cls is FileSaveHandler2:
        assert (directory / "saved.txt").read_text() == "saved"
    if cls in (RepoIndexHandler, RepoSearchHandler):
        assert result["count"] > 0


@pytest.mark.parametrize("cls", HANDLERS)
def test_model_schema_requires_named_root_without_location(cls):
    definition = cls.tool_def()
    parameters = definition["parameters"]
    assert "location" not in parameters["properties"]
    assert "location" not in parameters["required"]
    assert "external_root" in parameters["required"]
    assert parameters["properties"]["external_root"]["minLength"] == 1
    assert "enum" not in parameters["properties"]["external_root"]
    assert set(parameters["required"]) == set(parameters["properties"])
    assert parameters["additionalProperties"] is False


@pytest.mark.parametrize("cls", HANDLERS)
def test_unknown_root_fails_without_legacy_fallback(tmp_path, cls):
    resolver = NamedOnlyResolver("Pishare", tmp_path)
    result = _make(cls, resolver).execute(_args(cls, "pishare"))
    assert result["ok"] is False
    assert "Unknown configured root" in result["error"]


@pytest.mark.parametrize("shell_mode", [False, True])
def test_command_arguments_and_script_may_contain_absolute_paths(tmp_path, shell_mode):
    base = tmp_path / "root"
    base.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("absolute argument works")
    handler = _make(ExecuteCommand2, NamedOnlyResolver("arbitrary", base))
    args = {"external_root": "arbitrary", "working_directory": ".",
            "timeout_seconds": 10, "success_exit_codes": [0]}
    code = "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())"
    if shell_mode:
        if "bash" not in handler.available_shells():
            pytest.skip("bash unavailable")
        script = shlex.join([sys.executable, "-c", code, str(outside)])
        args.update(mode="shell", executable="", arguments=[], shell="bash", script=script)
    else:
        args.update(mode="process", executable=sys.executable, arguments=["-c", code, str(outside)],
                    script="", shell="none")
    result = handler.execute(args)
    assert result["ok"] is True, result
    assert result["stdout"].strip() == "absolute argument works"
    assert result["arguments"] == args["arguments"]
    assert result["script"] == args["script"]


@pytest.mark.parametrize("cls", HANDLERS)
def test_named_root_handler_paths_cannot_escape(tmp_path, cls):
    resolver = NamedOnlyResolver("root", tmp_path)
    args = _args(cls, "root")
    field = "working_directory" if cls in (CommandExecutionHandler2, ExecuteCommand2) else (
        "root" if cls in (RepoIndexHandler, RepoSearchHandler) else "path")
    args[field] = "../outside"
    result = _make(cls, resolver).execute(args)
    assert result["ok"] is False


def test_mcp_advertises_and_dispatches_named_root_calls(tmp_path):
    from galet_tools.host.config import GaletConfig
    from galet_tools.mcp.server import dispatch_call, resolve_startup_scope

    directory = tmp_path / "configured"
    directory.mkdir()
    config = GaletConfig(account="alice", allowlist=["file_save", "file_load", "execute_command2"],
                         storage_root=str(tmp_path / "legacy-storage"), storage_namespace="legacy-ns",
                         external_roots={"arbitrary": str(directory)}, sandbox_root=str(tmp_path / "legacy-sandbox"),
                         host="127.0.0.1", port=8765, fonts=[])
    scope, tools = resolve_startup_scope(config)
    assert all("location" not in tool["inputSchema"]["properties"] for tool in tools)
    saved = dispatch_call(scope, "file_save", {"external_root": "arbitrary", "path": "note.txt",
                                              "file_content": "named root", "overwrite": False})
    assert json.loads(saved["content"][0]["text"])["ok"] is True
    loaded = dispatch_call(scope, "file_load", {"external_root": "arbitrary", "path": "note.txt"})
    assert json.loads(loaded["content"][0]["text"])["result"] == "named root"
    assert (directory / "note.txt").read_text() == "named root"
    assert not (directory / "alice").exists()
    assert not (directory / "legacy-ns").exists()

