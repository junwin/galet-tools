from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Tuple

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver


class FileSaveHandler2(HandlerV2):
    """Save text content to a file under a named storage or external location.

    Mirrors FileLoadHandler2's location scheme. The strict tool_def exposes
    no legacy alias keys; execute_raw maps relative_path for back-compat.
    """

    NAME = "file_save"

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
                "Save code or text into a file under a named location. "
                "Paths are always relative. "
                "location='storage' uses Lucy storage; location='external' uses external_root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "enum": ["storage", "external"],
                        "description": "Where to save to.",
                    },
                    "external_root": {
                        "type": "string",
                        "description": "Named external root key when location='external'. Use '' otherwise.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative path under the chosen location (no leading /, no ..).",
                    },
                    "file_content": {
                        "type": "string",
                        "description": "Content to write to the file",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "If false, fail when the target file already exists",
                        "default": True,
                    },
                },
                "required": ["location", "external_root", "path", "file_content", "overwrite"],
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
        location = (args.get("location") or "storage").strip().lower()
        external_root = (args.get("external_root") or "").strip()
        path_in = (args.get("path") or "").strip()
        file_content = args.get("file_content")
        overwrite = args.get("overwrite", True)

        if not path_in or file_content is None:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "path and file_content are required",
                "location": location,
                "external_root": external_root,
                "path": path_in,
            }

        if not isinstance(file_content, str):
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "file_content must be a string",
                "location": location,
                "external_root": external_root,
                "path": path_in,
            }

        norm_rel, err = self._validate_and_normalize_relative_path(path_in)
        if err:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": err,
                "location": location,
                "external_root": external_root,
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
                        "external_root": external_root,
                        "path": path_in,
                    }
                base_dir = self._storage_resolver.external_root_dir(external_root)
            else:
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "error": f"Unknown location '{location}'",
                    "location": location,
                    "external_root": external_root,
                    "path": path_in,
                }
        except Exception as e:
            logging.exception("file_save: failed to resolve base directory")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(e),
                "location": location,
                "external_root": external_root,
                "path": path_in,
            }

        logging.info(
            "file_save: account=%s location=%s external_root=%s path=%s overwrite=%s",
            account_name,
            location,
            external_root,
            path_in,
            bool(overwrite),
        )

        try:
            full_path = self._write_file_safe(base_dir, norm_rel, file_content, overwrite=bool(overwrite))
        except Exception as e:
            logging.exception("file_save failed")
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
            "result": f"success file saved at {full_path}",
        }

    def execute_raw(self, arguments_raw: str, *, account_name: str = "auto", call_id: str = "", **context: Any) -> str:
        """Map legacy relative_path and missing-key defaults before executing."""
        try:
            args = json.loads(arguments_raw or "{}")
        except Exception:
            args = {}

        if isinstance(args, dict):
            if (not args.get("path")) and args.get("relative_path"):
                args["path"] = args.get("relative_path")

            if "location" not in args:
                args["location"] = "storage"
            if "external_root" not in args:
                args["external_root"] = ""
            if "overwrite" not in args:
                args["overwrite"] = True

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

    def _write_file_safe(self, base_dir: str, rel_path: str, content: str, overwrite: bool = True) -> str:
        """Resolve base_dir + rel_path, enforce realpath containment, and write.

        Creates parent directories as needed inside base_dir.
        """
        base_abs = os.path.abspath(base_dir)
        full_path = os.path.normpath(os.path.join(base_abs, rel_path))

        base_real = os.path.realpath(base_abs)
        full_real = os.path.realpath(full_path)

        if not (full_real == base_real or full_real.startswith(base_real + os.path.sep)):
            raise ValueError("File access outside allowed base path")

        parent = os.path.dirname(full_real)
        os.makedirs(parent, exist_ok=True)

        if not overwrite and os.path.exists(full_real):
            raise FileExistsError("Target file already exists and overwrite=false")

        with open(full_real, "w", encoding="utf-8") as f:
            f.write(content)

        return full_real
