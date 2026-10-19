"""Exact, single-match edits without model-authored diff coordinates."""
from __future__ import annotations

import difflib
import os
import stat
import tempfile
from pathlib import Path

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.tools.patch_apply_handler import PatchApplyHandler2

_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_TEXT_BYTES = 1024 * 1024
_MAX_DIFF_CHARS = 4000


class TextReplaceHandler(HandlerV2):
    NAME = "text_replace"

    def __init__(self, storage_resolver):
        self._storage_resolver = storage_resolver

    @classmethod
    def name(cls):
        return cls.NAME

    @classmethod
    def tool_def(cls):
        return {"type": "function", "name": cls.NAME, "strict": True,
                "description": "Prefer for small exact edits to an existing UTF-8 file. Replace old_text only if it matches exactly once. No regex, diff headers or line counts. Read the current text first; if absent/ambiguous, reread a narrow region and provide enough unique context. check_only validates and previews without writing.",
                "parameters": {"type": "object", "properties": {
                    "external_root": {"type": "string", "minLength": 1, "description": "Exact configured root name; no account or namespace is added."},
                    "path": {"type": "string", "description": "Root-relative POSIX path."},
                    "old_text": {"type": "string", "minLength": 1},
                    "new_text": {"type": "string"},
                    "check_only": {"type": "boolean"}},
                    "required": ["external_root", "path", "old_text", "new_text", "check_only"],
                    "additionalProperties": False}}

    @classmethod
    def result_schema(cls):
        return {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "tool": {"type": "string"}, "applied": {"type": "boolean"},
            "error": {"type": "string"}, "error_code": {"type": "string"},
            "match_count": {"type": "integer"}, "diff": {"type": "string"},
            "diff_truncated": {"type": "boolean"}},
            "required": ["ok", "tool", "applied"], "additionalProperties": True}

    def execute(self, args, *, account_name="auto", **context):
        result = {"ok": False, "tool": self.NAME, "applied": False}

        def fail(code, message, **extra):
            return {**result, "error_code": code, "error": message, **extra}

        if not isinstance(args, dict):
            return fail("invalid_arguments", "arguments must be an object")
        path, error = PatchApplyHandler2._validate_relative_path(args.get("path"))
        if error:
            return fail("invalid_path", error)
        root, old, new, check = (args.get(k) for k in ("external_root", "old_text", "new_text", "check_only"))
        result.update(path=path, external_root=root)
        if not isinstance(root, str) or not root.strip():
            return fail("invalid_root", "external_root is required")
        if not isinstance(old, str) or not old or not isinstance(new, str) or not isinstance(check, bool):
            return fail("invalid_arguments", "old_text must be non-empty, new_text a string, check_only a boolean")
        try:
            text_bytes = max(len(old.encode('utf-8')), len(new.encode('utf-8')))
        except UnicodeError:
            return fail("invalid_encoding", "Replacement text must be valid UTF-8")
        if text_bytes > _MAX_TEXT_BYTES:
            return fail("text_too_large", "Each edit text must be at most 1 MiB")
        if old == new:
            return fail("no_change", "old_text and new_text are identical")
        temporary = None
        try:
            base = Path(self._storage_resolver.external_root_dir(root)).resolve()
            target = base / path
            if not base.is_dir() or not target.resolve().is_relative_to(base):
                return fail("invalid_path", "path escapes the configured root or root is unavailable")
            if target.is_symlink() or not target.is_file():
                return fail("invalid_file", "Target must be an existing regular file, not a symbolic link")
            if target.stat().st_size > _MAX_FILE_BYTES:
                return fail("file_too_large", "Target must be at most 4 MiB")
            original = target.read_bytes()
            if len(original) > _MAX_FILE_BYTES:
                return fail("file_too_large", "Target must be at most 4 MiB")
            if b'\0' in original:
                return fail("invalid_encoding", "Target must be UTF-8 text, not binary")
            text = original.decode('utf-8')  # No newline normalization.
            matches, position = 0, text.find(old)
            while position != -1:
                matches += 1
                position = text.find(old, position + 1)
            if matches != 1:
                return fail("match_not_unique", "old_text must match exactly once; reread the target and supply unique exact context", match_count=matches)
            changed = text.replace(old, new, 1)
            encoded = changed.encode('utf-8')
            if len(encoded) > _MAX_FILE_BYTES:
                return fail("file_too_large", "Result must be at most 4 MiB")
            preview = ''
            truncated = False
            for line in difflib.unified_diff(text.splitlines(keepends=True), changed.splitlines(keepends=True),
                                             fromfile='a/'+path, tofile='b/'+path, n=2):
                if len(preview) + len(line) > _MAX_DIFF_CHARS:
                    preview += line[:_MAX_DIFF_CHARS-len(preview)]
                    truncated = True
                    break
                preview += line
            result.update(match_count=1, diff=preview, diff_truncated=truncated)
            if check:
                return {**result, "ok": True}
            mode = stat.S_IMODE(target.stat().st_mode)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = stream.name
                stream.write(encoded)
                stream.flush()
            os.chmod(temporary, mode)
            # Fail closed if the source changed during preparation.
            if target.is_symlink() or not target.resolve().is_relative_to(base) or target.read_bytes() != original:
                return fail("source_changed", "File changed during edit; reread and retry")
            os.replace(temporary, target)
            temporary = None
            return {**result, "ok": True, "applied": True}
        except UnicodeError:
            return fail("invalid_encoding", "Target and replacement text must be valid UTF-8")
        except (OSError, ValueError, TypeError) as exc:
            return fail("file_error", str(exc))
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
