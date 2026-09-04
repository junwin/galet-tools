"""CommandExecutionHandler2 relative-path validation and end-to-end runs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from tests.conftest import FakeSandboxResolver, FakeSecurityPolicy, FakeStorageResolver

from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2


def _make(
    tmp_path: Path,
    *,
    external_roots: Optional[Dict[str, str]] = None,
    allowed: bool = True,
    max_chars: int = 10000,
) -> Tuple[CommandExecutionHandler2, FakeSecurityPolicy]:
    policy = FakeSecurityPolicy(allowed=allowed, max_chars=max_chars)
    handler = CommandExecutionHandler2(
        FakeStorageResolver(str(tmp_path), external_roots=external_roots),
        FakeSandboxResolver(str(tmp_path)),
        policy,
    )
    return handler, policy


def _args(command: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "location": "sandbox",
        "external_root": "",
        "command": command,
        "working_directory": ".",
        "timeout_seconds": 10,
        "success_exit_codes": [0],
        "wrapper": "none",
    }
    base.update(overrides)
    return base


class TestRelativePathValidation:
    """Working-directory validation keeps dot and blocks parent escapes."""

    def test_allows_dot(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        norm, err = handler._validate_and_normalize_relative_path(".")

        assert err == ""
        assert norm == "."

    def test_empty_normalizes_to_dot(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        norm, err = handler._validate_and_normalize_relative_path("")

        assert err == ""
        assert norm == "."

    def test_blocks_parent(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        norm, err = handler._validate_and_normalize_relative_path("..")

        assert norm == ""
        assert "parent" in err or ".." in err

    def test_allows_internal_dotdot_normalization(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        norm, err = handler._validate_and_normalize_relative_path("a/../b")

        assert err == ""
        assert norm == "b"


class TestEndToEnd:
    """Commands run under a permissive policy and are refused under a denying one."""

    def test_runs_trivial_command_in_sandbox(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute(_args("echo hi"))

        assert res["ok"] is True
        assert res["returncode"] == 0
        assert res["stdout"].strip() == "hi"
        assert res["location"] == "sandbox"

    def test_runs_command_on_external_root(self, tmp_path: Path) -> None:
        ext_dir = str(tmp_path / "repo_lucy")
        handler, _ = _make(tmp_path, external_roots={"repo_lucy": ext_dir})

        res = handler.execute(_args("pwd", location="external", external_root="repo_lucy"))

        assert res["ok"] is True
        assert res["stdout"].strip() == os.path.realpath(ext_dir)

    def test_denying_policy_refuses_command(self, tmp_path: Path) -> None:
        handler, policy = _make(tmp_path, allowed=False)

        res = handler.execute(_args("echo hi"))

        assert res["ok"] is False
        assert "refused" in res["error"].lower()
        assert res["command"] == "echo hi"
        assert policy.calls == [("echo hi", "none")]

    def test_wrapper_choice_reaches_policy(self, tmp_path: Path) -> None:
        handler, policy = _make(tmp_path)

        res = handler.execute(_args("echo hi", wrapper="bash"))

        assert res["ok"] is True
        assert policy.calls == [("echo hi", "bash")]

    def test_output_truncated_at_policy_limit(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path, max_chars=20)

        res = handler.execute(_args("python3 -c \"print('x' * 200)\""))

        assert res["ok"] is True
        assert "[... output truncated ...]" in res["stdout"]
        assert len(res["stdout"]) < 200

    def test_nonzero_exit_is_not_ok(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute(_args("python3 -c \"import sys; sys.exit(3)\""))

        assert res["ok"] is False
        assert res["returncode"] == 3
        assert "error 3" in res["result"]

    def test_benign_command_nonzero_reports_warning(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute(_args("grep -q missing-pattern missing-file"))

        assert res["ok"] is False
        assert res.get("status") == "warning"
