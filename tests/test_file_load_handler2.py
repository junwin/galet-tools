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


class TestRangedReads:
    """Targeted reads preserve exact text and report useful paging metadata."""

    def test_reads_requested_line_range(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        _write(
            resolver.storage_base_dir(),
            "sample.txt",
            "one\ntwo\nthree\nfour\nfive\n",
        )

        res = handler.execute(
            {
                "location": "storage",
                "external_root": "",
                "path": "sample.txt",
                "start_line": 2,
                "line_count": 2,
                "include_line_numbers": False,
            }
        )

        assert res["ok"] is True
        assert res["result"] == "two\nthree\n"
        assert res["start_line"] == 2
        assert res["end_line"] == 3
        assert res["total_lines"] == 5
        assert res["has_more"] is True

    def test_line_numbers_are_optional(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        _write(resolver.storage_base_dir(), "sample.txt", "one\ntwo\nthree")

        res = handler.execute(
            {
                "location": "storage",
                "external_root": "",
                "path": "sample.txt",
                "start_line": 2,
                "line_count": None,
                "include_line_numbers": True,
            }
        )

        assert res["ok"] is True
        assert res["result"] == "2: two\n3: three"
        assert res["end_line"] == 3
        assert res["has_more"] is False

    def test_null_range_preserves_whole_file_behavior(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        content = "one\n\nthree\n"
        _write(resolver.storage_base_dir(), "sample.txt", content)

        res = handler.execute(
            {
                "location": "storage",
                "external_root": "",
                "path": "sample.txt",
                "start_line": None,
                "line_count": None,
                "include_line_numbers": False,
            }
        )

        assert res["ok"] is True
        assert res["result"] == content
        assert res["start_line"] == 1
        assert res["end_line"] == 3
        assert res["total_lines"] == 3
        assert res["has_more"] is False

    def test_start_line_at_end_returns_empty_page(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        _write(resolver.storage_base_dir(), "sample.txt", "one\ntwo\n")

        res = handler.execute(
            {
                "location": "storage",
                "external_root": "",
                "path": "sample.txt",
                "start_line": 3,
                "line_count": 10,
                "include_line_numbers": False,
            }
        )

        assert res["ok"] is True
        assert res["result"] == ""
        assert res["end_line"] == 2
        assert res["total_lines"] == 2
        assert res["has_more"] is False

    @staticmethod
    def _range_args(**overrides):
        args = {
            "location": "storage",
            "external_root": "",
            "path": "sample.txt",
            "start_line": 1,
            "line_count": 10,
            "include_line_numbers": False,
        }
        args.update(overrides)
        return args

    def test_invalid_range_values_are_rejected(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        _write(resolver.storage_base_dir(), "sample.txt", "one\n")

        for overrides in (
            {"start_line": 0},
            {"start_line": True},
            {"line_count": 0},
            {"line_count": 2001},
            {"line_count": True},
            {"include_line_numbers": "yes"},
        ):
            res = handler.execute(self._range_args(**overrides))
            assert res["ok"] is False

    def test_start_beyond_end_is_rejected(self, tmp_path: Path) -> None:
        handler, resolver = _make(tmp_path)
        _write(resolver.storage_base_dir(), "sample.txt", "one\n")

        res = handler.execute(self._range_args(start_line=3))

        assert res["ok"] is False
        assert "exceeds file length" in res["error"]

    def test_execute_raw_supplies_legacy_range_defaults(self, tmp_path: Path) -> None:
        import json

        handler, resolver = _make(tmp_path)
        _write(resolver.storage_base_dir(), "sample.txt", "one\ntwo\n")

        res = json.loads(
            handler.execute_raw(
                '{"location":"storage","external_root":"","path":"sample.txt"}'
            )
        )

        assert res["ok"] is True
        assert res["result"] == "one\ntwo\n"

    def test_strict_schema_requires_all_properties(self) -> None:
        parameters = FileLoadHandler2.tool_def()["parameters"]

        assert set(parameters["required"]) == set(parameters["properties"])
        assert parameters["additionalProperties"] is False
