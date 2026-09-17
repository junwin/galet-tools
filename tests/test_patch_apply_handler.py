"""Safety and behavior tests for PatchApplyHandler2."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from galet_tools.tools.patch_apply_handler import PatchApplyHandler2
from tests.conftest import FakeStorageResolver


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def _handler_for(base: Path, root_name: str = "repo") -> PatchApplyHandler2:
    resolver = FakeStorageResolver(
        str(base / "resolver"),
        external_roots={root_name: str(base)},
    )
    return PatchApplyHandler2(resolver)


def _replace_patch(path: str, old: str = "old", new: str = "new") -> str:
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def _args(path: str, patch_content: str, **overrides):
    values = {
        "location": "external",
        "external_root": "repo",
        "path": path,
        "patch_content": patch_content,
        "check_only": False,
    }
    values.update(overrides)
    return values


def test_applies_exact_requested_path(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("old\n", encoding="utf-8")
    handler = _handler_for(tmp_path)

    result = handler.execute(_args("hello.txt", _replace_patch("hello.txt")))

    assert result["ok"] is True
    assert result["applied"] is True
    assert result["path"] == "hello.txt"
    assert result["affected_paths"] == ["hello.txt"]
    assert target.read_text(encoding="utf-8") == "new\n"


def test_check_only_does_not_modify_file(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("old\n", encoding="utf-8")
    handler = _handler_for(tmp_path)

    result = handler.execute(
        _args("hello.txt", _replace_patch("hello.txt"), check_only=True)
    )

    assert result["ok"] is True
    assert result["applied"] is False
    assert result["affected_paths"] == ["hello.txt"]
    assert target.read_text(encoding="utf-8") == "old\n"


def test_invalid_patch_fails_without_modifying_file(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("old\n", encoding="utf-8")
    handler = _handler_for(tmp_path)

    result = handler.execute(
        _args("hello.txt", _replace_patch("hello.txt", old="not-present"))
    )

    assert result["ok"] is False
    assert result["applied"] is False
    assert "check failed" in result["error"]
    assert target.read_text(encoding="utf-8") == "old\n"


@pytest.mark.parametrize(
    "path",
    [
        "../hello.txt",
        "/tmp/hello.txt",
        "nested/../../hello.txt",
        r"C:\\temp\\hello.txt",
        r"nested\\hello.txt",
    ],
)
def test_unsafe_paths_are_rejected(tmp_path: Path, path: str) -> None:
    handler = _handler_for(tmp_path)

    result = handler.execute(_args(path, _replace_patch("hello.txt")))

    assert result["ok"] is False
    assert result["applied"] is False


def test_location_and_external_root_must_agree(tmp_path: Path) -> None:
    handler = _handler_for(tmp_path)
    patch = _replace_patch("hello.txt")

    missing = handler.execute(_args("hello.txt", patch, external_root=""))
    storage_with_root = handler.execute(
        _args("hello.txt", patch, location="storage")
    )

    assert missing["error"] == "external_root is required for location='external'"
    assert (
        storage_with_root["error"]
        == "external_root must be empty for location='storage'"
    )


def test_unknown_external_root_is_rejected(tmp_path: Path) -> None:
    handler = _handler_for(tmp_path)

    result = handler.execute(
        _args(
            "hello.txt",
            _replace_patch("hello.txt"),
            external_root="unknown",
        )
    )

    assert result["ok"] is False
    assert "external root not found" in result["error"]


def test_patch_targeting_different_file_is_rejected(tmp_path: Path) -> None:
    requested = tmp_path / "requested.txt"
    other = tmp_path / "other.txt"
    requested.write_text("old\n", encoding="utf-8")
    other.write_text("old\n", encoding="utf-8")
    handler = _handler_for(tmp_path)

    result = handler.execute(
        _args("requested.txt", _replace_patch("other.txt"))
    )

    assert result["ok"] is False
    assert result["error"] == "patch must affect exactly the requested path"
    assert result["affected_paths"] == ["other.txt"]
    assert requested.read_text(encoding="utf-8") == "old\n"
    assert other.read_text(encoding="utf-8") == "old\n"


def test_multi_file_patch_is_rejected_atomically(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old\n", encoding="utf-8")
    second.write_text("old\n", encoding="utf-8")
    handler = _handler_for(tmp_path)
    patch = _replace_patch("first.txt") + _replace_patch("second.txt")

    result = handler.execute(_args("first.txt", patch))

    assert result["ok"] is False
    assert result["affected_paths"] == ["first.txt", "second.txt"]
    assert first.read_text(encoding="utf-8") == "old\n"
    assert second.read_text(encoding="utf-8") == "old\n"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    (outside / "hello.txt").write_text("old\n", encoding="utf-8")
    os.symlink(outside, base / "escape")
    handler = _handler_for(base)

    result = handler.execute(
        _args("escape/hello.txt", _replace_patch("escape/hello.txt"))
    )

    assert result["ok"] is False
    assert result["error"] == "path escapes the configured root"
    assert (outside / "hello.txt").read_text(encoding="utf-8") == "old\n"


def test_invalid_json_returns_explicit_error(tmp_path: Path) -> None:
    handler = _handler_for(tmp_path)

    result = json.loads(handler.execute_raw("{not-json"))

    assert result["ok"] is False
    assert result["applied"] is False
    assert result["error"] == "arguments_raw is not valid JSON"


def test_binary_patch_is_rejected(tmp_path: Path) -> None:
    handler = _handler_for(tmp_path)

    result = handler.execute(
        _args("hello.bin", "GIT binary patch\nliteral 0\n")
    )

    assert result["ok"] is False
    assert "binary patches" in result["error"]


def test_strict_schema_requires_every_property() -> None:
    parameters = PatchApplyHandler2.tool_def()["parameters"]

    assert set(parameters["required"]) == set(parameters["properties"])
    assert parameters["additionalProperties"] is False
