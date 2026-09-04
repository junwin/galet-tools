from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Tuple

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver


class FileLoadHandler2(HandlerV2):
    """Load a file from a named storage or external location.

    Callers never pass absolute paths: they give a location ('storage', or
    'external' with a named external_root) plus a path relative to that
    root. Accepts 'relative_path' as a back-compat alias for 'path'.
    """

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
                "Read a text file's contents and return them. Use this tool to read, open, view, or "
                "inspect any file whose path is known or specified. Prefer this over execute_command "
                "with cat, sed, tail, head, or less. "
                "Paths are always relative and resolved under a named location. "
                "location='storage' uses Lucy storage; location='external' uses external_root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "enum": ["storage", "external"],
                        "description": "Where to load from.",
                    },
                    "external_root": {
                        "type": "string",
                        "description": "Named external root key when location='external'. Use '' otherwise.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative path under the chosen location (no leading /, no ..).",
                    },
                },
                "required": ["location", "external_root", "path"],
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
                "result": {"type": "string"},
                "error": {"type": "string"},
            },
            "required": ["ok", "tool"],
            "additionalProperties": True,
        }

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto") -> Dict[str, Any]:
        path_in = (args.get("path") or args.get("relative_path") or "").strip()
        location = (args.get("location") or "storage").strip().lower()
        external_root = (args.get("external_root") or "").strip()

        if not path_in:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "path is required",
                "args": {"path": path_in, "location": location, "external_root": external_root},
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
        except Exception as e:
            logging.exception("file_load: failed to resolve base directory")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(e),
                "location": location,
                "external_root": external_root,
                "path": path_in,
            }

        logging.info(
            "file_load: account=%s location=%s external_root=%s path=%s",
            account_name,
            location,
            external_root or "",
            path_in,
        )

        try:
            content, full_path = self._read_file_safe(base_dir, norm_rel)
        except Exception as e:
            logging.exception("file_load failed")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(e),
                "location": location,
                "external_root": external_root,
                "path": path_in,
                "normalized_path": norm_rel,
                "base_dir": base_dir,
            }

        file_name = os.path.basename(norm_rel)

        return {
            "ok": True,
            "tool": self.NAME,
            "location": location,
            "external_root": external_root,
            "path": path_in,
            "normalized_path": norm_rel,
            "file_name": file_name,
            "resolved_path": full_path,
            "content_type": "text/plain",
            "encoding": "utf-8",
            "result": content,
        }

    def execute_raw(self, arguments_raw: str, *, account_name: str = "auto", call_id: str = "", **context: Any) -> str:
        """Run execute against a JSON arguments string."""
        try:
            args = json.loads(arguments_raw or "{}")
        except Exception:
            args = {}
        result = self.execute(args if isinstance(args, dict) else {}, account_name=account_name)
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _has_drive_letter(path: str) -> bool:
        return len(path) >= 2 and path[1] == ":" and path[0].isalpha()

    def _validate_and_normalize_relative_path(self, path_in: str) -> Tuple[str, str]:
        """Return (normalized_path, error_message_or_empty)."""
        if self._has_drive_letter(path_in):
            return "", "path must be relative, not include drive letters"
        if os.path.isabs(path_in):
            return "", "path must be relative, not absolute"

        norm_rel = os.path.normpath(path_in)

        if norm_rel in ("", ".", ".."):
            return "", "path must not be empty or point to current/parent directory"

        parts = [p for p in norm_rel.split(os.path.sep) if p]
        if os.path.altsep:
            parts = [p for seg in parts for p in seg.split(os.path.altsep) if p]
        if any(p == ".." for p in parts) or norm_rel.startswith(".."):
            return "", "path must not contain '..' segments"

        return norm_rel, ""

    def _read_file_safe(self, base_dir: str, rel_path: str) -> Tuple[str, str]:
        """Resolve base_dir + rel_path and enforce realpath containment."""
        base_abs = os.path.abspath(base_dir)
        full_path = os.path.normpath(os.path.join(base_abs, rel_path))

        base_real = os.path.realpath(base_abs)
        full_real = os.path.realpath(full_path)

        if not (full_real == base_real or full_real.startswith(base_real + os.path.sep)):
            raise ValueError("File access outside allowed base path")

        if not os.path.isfile(full_real):
            raise FileNotFoundError(f"File not found: {full_real}")

        with open(full_real, "r", encoding="utf-8") as f:
            return f.read(), full_real
