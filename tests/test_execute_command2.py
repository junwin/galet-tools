from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from tests.conftest import FakeSandboxResolver, FakeSecurityPolicy, FakeStorageResolver

from galet_tools.host.security import DefaultSecurityPolicy
from galet_tools.tools.execute_command2 import ExecuteCommand2


def make_handler(tmp_path: Path, policy=None) -> ExecuteCommand2:
    return ExecuteCommand2(
        FakeStorageResolver(str(tmp_path)),
        FakeSandboxResolver(str(tmp_path)),
        policy or DefaultSecurityPolicy(),
    )


def request(**changes):
    value = {
        "mode": "process",
        "executable": sys.executable,
        "arguments": ["-c", "print('hello')"],
        "script": "",
        "shell": "none",
        "location": "sandbox",
        "external_root": "",
        "working_directory": ".",
        "timeout_seconds": 10,
        "success_exit_codes": [0],
    }
    value.update(changes)
    return value


def test_process_arguments_are_not_shell_parsed(tmp_path: Path) -> None:
    handler = make_handler(tmp_path)
    values = ["space value", "", "a|b", 'quote"value', "unicode-£"]
    result = handler.execute(request(arguments=["-c", "import json,sys; print(json.dumps(sys.argv[1:]))", *values]))
    assert result["ok"] is True
    assert json.loads(result["stdout"]) == values


def test_stdin_is_disabled(tmp_path: Path) -> None:
    handler = make_handler(tmp_path)
    result = handler.execute(request(arguments=["-c", "import sys; print(sys.stdin.read())"]))
    assert result["ok"] is True
    assert result["stdout"] == "\n"


def test_timeout_is_structured(tmp_path: Path) -> None:
    handler = make_handler(tmp_path)
    result = handler.execute(request(arguments=["-c", "import time; time.sleep(5)"], timeout_seconds=1))
    assert result["ok"] is False
    assert result["error_code"] == "timeout"


def test_missing_executable_is_structured(tmp_path: Path) -> None:
    handler = make_handler(tmp_path)
    result = handler.execute(request(executable="galet-no-such-executable"))
    assert result["ok"] is False
    assert result["error_code"] == "executable_not_found"


@pytest.mark.parametrize("executable", ["bash", "sh", "pwsh", "powershell.exe", "cmd.exe"])
def test_embedded_shell_is_refused(tmp_path: Path, executable: str) -> None:
    handler = make_handler(tmp_path)
    result = handler.execute(request(executable=executable, arguments=["-c", "echo bad"]))
    assert result["ok"] is False
    assert result["error_code"] == "embedded_shell_refused"


def test_policy_receives_structured_request(tmp_path: Path) -> None:
    policy = FakeSecurityPolicy()
    handler = make_handler(tmp_path, policy)
    result = handler.execute(request())
    assert result["ok"] is True
    assert policy.execution_calls[0]["mode"] == "process"
    assert policy.execution_calls[0]["arguments"] == ["-c", "print('hello')"]


def test_path_containment_rejects_escape(tmp_path: Path) -> None:
    handler = make_handler(tmp_path)
    result = handler.execute(request(working_directory=".."))
    assert result["ok"] is False
    assert result["error_code"] == "invalid_working_directory"


def test_shell_schema_describes_current_host() -> None:
    definition = ExecuteCommand2.tool_def()
    description = definition["description"]
    assert ("Windows" in description) == (sys.platform == "win32")
    assert "bash -lc" in description
    assert "arguments array" in description


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_bash_pipeline(tmp_path: Path) -> None:
    handler = make_handler(tmp_path)
    result = handler.execute(request(mode="shell", executable="", arguments=[], script="printf hello | tr a-z A-Z", shell="bash"))
    assert result["ok"] is True
    assert result["stdout"] == "HELLO"


@pytest.mark.skipif(shutil.which("pwsh") is None and shutil.which("powershell.exe") is None, reason="PowerShell unavailable")
def test_powershell_pipeline_and_unicode(tmp_path: Path) -> None:
    handler = make_handler(tmp_path)
    result = handler.execute(request(mode="shell", executable="", arguments=[], script="'héllo' | ForEach-Object { $_.ToUpper() }", shell="powershell"))
    assert result["ok"] is True
    assert "HÉLLO" in result["stdout"]
