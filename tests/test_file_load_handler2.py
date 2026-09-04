"""file_load end-to-end against temp-dir fake storage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from tests.conftest import FakeStorageResolver

from galet_tools.tools.file_load_handler2 import FileLoadHandler2


def _make(tmp_path: Path, external_roots: Optional[Dict[str, str]] = None) -> Tuple[FileLoadHandler2, FakeStorageResolver]:
    resolver = FakeStorageResolver(str(tmp_path), external_roots=external_roots)
    return FileLoadHandler2(resolver), resolver


def _write(base: str, rel: str, content: str) -> str:
    full = os.path.join(base, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return full


class TestFileLoadEndToEnd:
    """Reads files from storage and named external locations."""

    def test_reads_file_from_storage(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        target = _write(resolver.storage_base_dir(), "notes/hello.txt", "hello storage")

        res = handler.execute({"location": "storage", "external_root": "", "path": "notes/hello.txt"})

        assert res["ok"] is True
        assert res["result"] == "hello storage"
        assert res["file_name"] == "hello.txt"
        assert res["resolved_path"] == target
        assert res["content_type"] == "text/plain"

    def test_reads_file_from_external_root(self, tmp_path: Path) -> None:
        ext_dir = str(tmp_path / "ext")
        handler, _ = _make(tmp_path, external_roots={"repo_lucy": ext_dir})
        target = _write(ext_dir, "notes/hello.md", "hello external")

        res = handler.execute({"location": "external", "external_root": "repo_lucy", "path": "notes/hello.md"})

        assert res["ok"] is True
        assert res["result"] == "hello external"
        assert res["resolved_path"] == target

    def test_relative_path_alias(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        _write(resolver.storage_base_dir(), "alias.txt", "aliased")

        res = handler.execute({"location": "storage", "external_root": "", "relative_path": "alias.txt"})

        assert res["ok"] is True
        assert res["result"] == "aliased"

    def test_missing_file_reports_error(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "storage", "external_root": "", "path": "missing.txt"})

        assert res["ok"] is False
        assert "File not found" in res["error"]

    def test_missing_path_is_rejected(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "storage", "external_root": ""})

        assert res["ok"] is False
        assert "path is required" in res["error"]

    def test_unknown_location_rejected(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "elsewhere", "external_root": "", "path": "a.txt"})

        assert res["ok"] is False
        assert "Unknown location" in res["error"]

    def test_external_location_requires_external_root(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "external", "external_root": "", "path": "a.txt"})

        assert res["ok"] is False
        assert "external_root is required" in res["error"]


class TestPathValidation:
    """Path rules stay inline: no absolute paths, no parent traversal."""

    def test_parent_traversal_rejected(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "storage", "external_root": "", "path": "../escape.txt"})

        assert res["ok"] is False
        assert ".." in res["error"]

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "storage", "external_root": "", "path": str(tmp_path / "abs.txt")})

        assert res["ok"] is False
        assert "absolute" in res["error"]

    def test_unknown_external_root_reports_resolver_error(self, tmp_path: Path) -> None:
        handler, _ = _make(tmp_path)

        res = handler.execute({"location": "external", "external_root": "nope", "path": "a.txt"})

        assert res["ok"] is False
        assert "external root not found" in res["error"]
