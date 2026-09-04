"""file_save end-to-end against temp-dir fake storage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from tests.conftest import FakeStorageResolver

from galet_tools.tools.file_save_handler import FileSaveHandler2


def _make(tmp_path: Path, external_roots: Optional[Dict[str, str]] = None) -> Tuple[FileSaveHandler2, FakeStorageResolver]:
    resolver = FakeStorageResolver(str(tmp_path), external_roots=external_roots)
    return FileSaveHandler2(resolver), resolver


class TestFileSaveEndToEnd:
    """Writes files under storage and named external locations."""

    def test_writes_file_to_storage(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)

        res = handler.execute(
            {"location": "storage", "external_root": "", "path": "sub/dir/note.txt", "file_content": "hello", "overwrite": True}
        )

        assert res["ok"] is True
        assert res["resolved_path"] == os.path.join(resolver.storage_base_dir(), "sub", "dir", "note.txt")
        with open(res["resolved_path"], encoding="utf-8") as f:
            assert f.read() == "hello"

    def test_writes_file_to_external_root(self, tmp_path: Path) -> None:
        ext_dir = str(tmp_path / "ext")
        handler, _ = _make(tmp_path, external_roots={"repo_lucy": ext_dir})

        res = handler.execute(
            {"location": "external", "external_root": "repo_lucy", "path": "note.txt", "file_content": "external", "overwrite": True}
        )

        assert res["ok"] is True
        with open(os.path.join(ext_dir, "note.txt"), encoding="utf-8") as f:
            assert f.read() == "external"

    def test_overwrite_allows_rewrite_by_default(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)

        first = handler.execute(
            {"location": "storage", "external_root": "", "path": "f.txt", "file_content": "one", "overwrite": True}
        )
        second = handler.execute(
            {"location": "storage", "external_root": "", "path": "f.txt", "file_content": "two", "overwrite": True}
        )

        assert first["ok"] is True
        assert second["ok"] is True
        with open(os.path.join(resolver.storage_base_dir(), "f.txt"), encoding="utf-8") as f:
            assert f.read() == "two"

    def test_overwrite_false_rejects_existing_file(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        ok_res = handler.execute(
            {"location": "storage", "external_root": "", "path": "f.txt", "file_content": "one", "overwrite": True}
        )
        reject = handler.execute(
            {"location": "storage", "external_root": "", "path": "f.txt", "file_content": "two", "overwrite": False}
        )

        assert ok_res["ok"] is True
        assert reject["ok"] is False
        assert "already exists" in reject["error"]

    def test_storage_location_rejects_external_root(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute(
            {"location": "storage", "external_root": "repo_lucy", "path": "f.txt", "file_content": "x", "overwrite": True}
        )

        assert res["ok"] is False
        assert "external_root must be ''" in res["error"]

    def test_external_location_requires_external_root(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute(
            {"location": "external", "external_root": "", "path": "f.txt", "file_content": "x", "overwrite": True}
        )

        assert res["ok"] is False
        assert "external_root is required" in res["error"]

    def test_missing_path_or_content_rejected(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "storage", "external_root": "", "path": "", "file_content": "x", "overwrite": True})

        assert res["ok"] is False
        assert "required" in res["error"]

    def test_non_string_content_rejected(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "storage", "external_root": "", "path": "f.txt", "file_content": 123, "overwrite": True})

        assert res["ok"] is False
        assert "file_content must be a string" in res["error"]

    def test_parent_traversal_rejected(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute(
            {"location": "storage", "external_root": "", "path": "../escape.txt", "file_content": "x", "overwrite": True}
        )

        assert res["ok"] is False
        assert ".." in res["error"]


class TestExecuteRaw:
    """execute_raw back-compat: relative_path alias and missing-key defaults."""

    def test_execute_raw_maps_relative_path_and_defaults(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)

        raw = json.dumps({"relative_path": "alias.txt", "file_content": "via-alias"})
        result = json.loads(handler.execute_raw(raw))

        assert result["ok"] is True
        with open(os.path.join(resolver.storage_base_dir(), "alias.txt"), encoding="utf-8") as f:
            assert f.read() == "via-alias"

    def test_execute_raw_defaults_location_storage(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)

        raw = json.dumps({"path": "plain.txt", "file_content": "plain"})
        result = json.loads(handler.execute_raw(raw))

        assert result["ok"] is True
        assert os.path.exists(os.path.join(resolver.storage_base_dir(), "plain.txt"))
