from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver

_MAX_LINE_COUNT = 2000


class FileLoadHandler2(HandlerV2):
    """Load all or a selected range of a UTF-8 text file."""

    NAME = "file_load"

    def __init__(self, storage_resolver: StorageLocationResolver) -> None:
        self._storage_resolver = storage_resolver

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Read all or part of a text file. Paths are relative to the "
                "configured root selected by external_root. Use start_line and line_count for "
                "targeted reads; use null for both to read the whole file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "external_root": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Exact configured root name. Names are arbitrary and case-sensitive; "
                            "no namespace or account is added automatically."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative path under the selected root (no leading /, no ..).",
                    },
                    "start_line": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "description": "One-based first line, or null to start at line 1.",
                    },
                    "line_count": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": _MAX_LINE_COUNT,
                        "description": (
                            "Maximum number of lines to return, or null to read through "
                            "the end of the file."
                        ),
                    },
                    "include_line_numbers": {
                        "type": "boolean",
                        "description": "Prefix returned lines with their one-based line numbers.",
                    },
                },
                "required": [
                    "external_root",
                    "path",
                    "start_line",
                    "line_count",
                    "include_line_numbers",
                ],
                "additionalProperties": False,
            },
            "strict": True,
        }

    @classmethod
    def result_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "tool": {"type": "string"},
                "location": {"type": "string"},
                "external_root": {"type": "string"},
                "path": {"type": "string"},
                "normalized_path": {"type": "string"},
                "file_name": {"type": "string"},
                "resolved_path": {"type": "string"},
                "content_type": {"type": "string"},
                "encoding": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "total_lines": {"type": "integer"},
                "has_more": {"type": "boolean"},
                "result": {"type": "string"},
                "error": {"type": "string"},
            },
            "required": ["ok", "tool"],
            "additionalProperties": True,
        }

    def execute(
        self,
        args: Dict[str, Any],
        *,
        account_name: str = "auto",
        **context: Any,
    ) -> Dict[str, Any]:
        path_in = (args.get("path") or args.get("relative_path") or "").strip()
        location = (args.get("location") or ("external" if args.get("external_root") else "storage")).strip().lower()
        external_root = (args.get("external_root") or "").strip()
        start_line = args.get("start_line")
        line_count = args.get("line_count")
        include_line_numbers = args.get("include_line_numbers", False)

        range_error = self._validate_range(
            start_line=start_line,
            line_count=line_count,
            include_line_numbers=include_line_numbers,
        )
        if range_error:
            return {"ok": False, "tool": self.NAME, "error": range_error}

        if not path_in:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "path is required",
                "args": {
                    "path": path_in,
                    "location": location,
                    "external_root": external_root,
                },
            }

        norm_rel, err = self._validate_and_normalize_relative_path(path_in)
        if err:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": err,
                "path": path_in,
            }

        try:
            if location == "storage":
                if external_root:
                    return {
                        "ok": False,
                        "tool": self.NAME,
                        "error": "external_root must be '' when location='storage'",
                        "location": location,
                        "external_root": external_root,
                        "path": path_in,
                    }
                base_dir = self._storage_resolver.storage_base_dir()
            elif location == "external":
                if not external_root:
                    return {
                        "ok": False,
                        "tool": self.NAME,
                        "error": "external_root is required when location='external'",
                        "location": location,
                        "path": path_in,
                    }
                base_dir = self._storage_resolver.external_root_dir(external_root)
            else:
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "error": f"Unknown location '{location}'",
                    "location": location,
                    "path": path_in,
                }
        except Exception as exc:
            logging.exception("file_load: failed to resolve base directory")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(exc),
                "location": location,
                "external_root": external_root,
                "path": path_in,
            }

        logging.info(
            "file_load: account=%s location=%s external_root=%s path=%s start_line=%s line_count=%s",
            account_name,
            location,
            external_root,
            path_in,
            start_line,
            line_count,
        )

        try:
            content, full_path, first, last, total, has_more = self._read_file_safe(
                base_dir,
                norm_rel,
                start_line=start_line,
                line_count=line_count,
                include_line_numbers=include_line_numbers,
            )
        except Exception as exc:
            logging.exception("file_load failed")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(exc),
                "location": location,
                "external_root": external_root,
                "path": path_in,
                "normalized_path": norm_rel,
                "base_dir": base_dir,
            }

        return {
            "ok": True,
            "tool": self.NAME,
            "location": location,
            "external_root": external_root,
            "path": path_in,
            "normalized_path": norm_rel,
            "file_name": os.path.basename(norm_rel),
            "resolved_path": full_path,
            "content_type": "text/plain",
            "encoding": "utf-8",
            "start_line": first,
            "end_line": last,
            "total_lines": total,
            "has_more": has_more,
            "result": content,
        }

    def execute_raw(
        self,
        arguments_raw: str,
        *,
        account_name: str = "auto",
        call_id: str = "",
        **context: Any,
    ) -> str:
        """Map legacy arguments and defaults before executing."""
        try:
            args = json.loads(arguments_raw or "{}")
        except json.JSONDecodeError:
            args = {}

        if isinstance(args, dict):
            if not args.get("path") and args.get("relative_path"):
                args["path"] = args.get("relative_path")
            args.setdefault("location", "external" if args.get("external_root") else "storage")
            args.setdefault("external_root", "")
            args.setdefault("start_line", None)
            args.setdefault("line_count", None)
            args.setdefault("include_line_numbers", False)

        result = self.execute(
            args if isinstance(args, dict) else {},
            account_name=account_name,
            **context,
        )
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _validate_range(
        *,
        start_line: object,
        line_count: object,
        include_line_numbers: object,
    ) -> str:
        if start_line is not None and (
            isinstance(start_line, bool)
            or not isinstance(start_line, int)
            or start_line < 1
        ):
            return "start_line must be null or an integer greater than or equal to 1"
        if line_count is not None and (
            isinstance(line_count, bool)
            or not isinstance(line_count, int)
            or line_count < 1
            or line_count > _MAX_LINE_COUNT
        ):
            return (
                f"line_count must be null or an integer between 1 and "
                f"{_MAX_LINE_COUNT}"
            )
        if not isinstance(include_line_numbers, bool):
            return "include_line_numbers must be a boolean"
        return ""

    @staticmethod
    def _has_drive_letter(path: str) -> bool:
        return len(path) >= 2 and path[1] == ":" and path[0].isalpha()

    def _validate_and_normalize_relative_path(
        self,
        path_in: str,
    ) -> Tuple[str, str]:
        """Return (normalized_path, error_message_or_empty)."""
        if self._has_drive_letter(path_in):
            return "", "path must be relative, not include drive letters"
        if os.path.isabs(path_in):
            return "", "path must be relative, not absolute"

        norm_rel = os.path.normpath(path_in)
        if norm_rel in ("", ".", ".."):
            return "", "path must not be empty or point to current/parent directory"

        parts = [part for part in norm_rel.split(os.path.sep) if part]
        if os.path.altsep:
            parts = [
                part
                for segment in parts
                for part in segment.split(os.path.altsep)
                if part
            ]
        if any(part == ".." for part in parts) or norm_rel.startswith(".."):
            return "", "path must not contain '..' segments"

        return norm_rel, ""

    def _read_file_safe(
        self,
        base_dir: str,
        rel_path: str,
        *,
        start_line: Optional[int],
        line_count: Optional[int],
        include_line_numbers: bool,
    ) -> Tuple[str, str, int, int, int, bool]:
        """Read a selected line range while enforcing realpath containment."""
        base_abs = os.path.abspath(base_dir)
        full_path = os.path.normpath(os.path.join(base_abs, rel_path))
        base_real = os.path.realpath(base_abs)
        full_real = os.path.realpath(full_path)

        try:
            contained = os.path.commonpath([base_real, full_real]) == base_real
        except ValueError:
            contained = False
        if not contained:
            raise ValueError("File access outside allowed base path")
        if not os.path.isfile(full_real):
            raise FileNotFoundError(f"File not found: {full_real}")

        with open(full_real, "r", encoding="utf-8") as handle:
            whole_content = handle.read()

        lines = whole_content.splitlines(keepends=True)
        total_lines = len(lines)
        first_line = start_line or 1
        start_index = first_line - 1
        if start_index > total_lines:
            raise ValueError(
                f"start_line {first_line} exceeds file length {total_lines}"
            )

        end_index = (
            total_lines
            if line_count is None
            else min(total_lines, start_index + line_count)
        )
        selected = lines[start_index:end_index]

        if include_line_numbers:
            content = "".join(
                f"{line_number}: {line}"
                for line_number, line in enumerate(selected, start=first_line)
            )
        else:
            content = "".join(selected)

        end_line = start_index + len(selected)
        return (
            content,
            full_real,
            first_line,
            end_line,
            total_lines,
            end_index < total_lines,
        )

