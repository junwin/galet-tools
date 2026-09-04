"""execute_command fail-fast: policy refusal precedes any subprocess run."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Tuple

from tests.conftest import FakeSandboxResolver, FakeSecurityPolicy, FakeStorageResolver

from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2


def _make(tmp_path: Path, *, allowed: bool = True) -> Tuple[CommandExecutionHandler2, FakeSecurityPolicy]:
    policy = FakeSecurityPolicy(allowed=allowed)
    handler = CommandExecutionHandler2(
        FakeStorageResolver(str(tmp_path)),
        FakeSandboxResolver(str(tmp_path)),
        policy,
    )
    return handler, policy


def _base_args(command: str, timeout_seconds: int) -> dict:
    return {
        "location": "sandbox",
        "external_root": "",
        "command": command,
        "working_directory": ".",
        "timeout_seconds": timeout_seconds,
        "success_exit_codes": [0],
    }


def test_denied_heredoc_returns_without_running(tmp_path: Path) -> None:
    handler, policy = _make(tmp_path, allowed=False)
    cmd = "python3 - << 'PY'\nprint('hello')\nPY"

    res = handler.execute(_base_args(cmd, 2))

    assert res["ok"] is False
    assert "refused" in res["error"].lower()
    assert res.get("command") == cmd
    assert policy.calls == [(cmd, "none")]


def test_refusal_precedes_working_directory_validation(tmp_path: Path) -> None:
    handler, _ = _make(tmp_path, allowed=False)
    args = _base_args("echo hi", 2)
    args["working_directory"] = ".."

    res = handler.execute(args)

    assert res["ok"] is False
    assert "refused" in res["error"].lower()


def test_heredoc_allowed_when_wrapped_in_bash_lc(tmp_path: Path) -> None:
    handler, _ = _make(tmp_path, allowed=True)
    inner = "python3 - <<'PY'\nprint('hello-from-heredoc')\nPY"
    cmd = "bash -lc " + shlex.quote(inner)

    res = handler.execute(_base_args(cmd, 5))

    assert res["ok"] is True
    assert "hello-from-heredoc" in (res.get("stdout") or "")
    assert res.get("command") == cmd


def test_deny_list_blocks_specific_command_only(tmp_path: Path) -> None:
    policy = FakeSecurityPolicy(allowed=True, denied=["rm -rf /"])
    handler = CommandExecutionHandler2(
        FakeStorageResolver(str(tmp_path)),
        FakeSandboxResolver(str(tmp_path)),
        policy,
    )

    denied = handler.execute(_base_args("rm -rf /", 2))
    allowed = handler.execute(_base_args("echo ok", 2))

    assert denied["ok"] is False
    assert "refused" in denied["error"].lower()
    assert allowed["ok"] is True
    assert allowed["stdout"].strip() == "ok"
