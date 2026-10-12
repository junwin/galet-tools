"""Apply a constrained single-file unified diff using git apply."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import PurePosixPath
from typing import Any, Dict, List, Tuple

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver

logger = logging.getLogger(__name__)

_MAX_PATCH_BYTES = 1024 * 1024
_GIT_TIMEOUT_SECONDS = 30
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class PatchApplyHandler2(HandlerV2):
    """Validate and apply a patch that affects exactly one requested file."""

    NAME = "patch_apply"

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
                "Validate or apply a unified-diff patch to exactly one file. "
                "Keep path relative to the selected root, including any repository directory. "
                "Use numbered unified-diff hunks and either a/path + b/path headers "
                "or prefix-free path headers. Do not use *** Begin Patch syntax. "
                "Example for path='repo/file.txt': "
                "--- a/repo/file.txt\n+++ b/repo/file.txt\n@@ -1 +1 @@\n-old\n+new\n"
                "Use check_only=true to validate before applying."
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
                        "description": "POSIX-style relative path to the single file being patched.",
                    },
                    "patch_content": {"type": "string"},
                    "check_only": {
                        "type": "boolean",
                        "description": "Validate without changing the file.",
                    },
                },
                "required": [
                    "external_root",
                    "path",
                    "patch_content",
                    "check_only",
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
                "applied": {"type": "boolean"},
                "location": {"type": "string"},
                "external_root": {"type": "string"},
                "path": {"type": "string"},
                "affected_paths": {"type": "array", "items": {"type": "string"}},
                "strip_components": {"type": "integer"},
                "path_attempts": {"type": "array", "items": {"type": "object"}},
                "error": {"type": "string"},
                "details": {"type": "string"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
            },
            "required": ["ok", "tool", "applied"],
            "additionalProperties": True,
        }

    def _result(
        self,
        *,
        ok: bool,
        applied: bool,
        location: str = "",
        external_root: str = "",
        path: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "ok": ok,
            "tool": self.NAME,
            "applied": applied,
            "location": location,
            "external_root": external_root,
            "path": path,
        }
        result.update(extra)
        return result

    def _invalid(
        self,
        message: str,
        *,
        location: str = "",
        external_root: str = "",
        path: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        return self._result(
            ok=False,
            applied=False,
            location=location,
            external_root=external_root,
            path=path,
            error=message,
            **extra,
        )

    @staticmethod
    def _validate_relative_path(path: object) -> Tuple[str, str]:
        if not isinstance(path, str):
            return "", "path must be a string"

        candidate = path.strip()
        if not candidate:
            return "", "path is required"
        if "\x00" in candidate or "\n" in candidate or "\r" in candidate:
            return "", "path contains an invalid character"
        if "\\" in candidate:
            return "", "path must use POSIX '/' separators"
        if _WINDOWS_DRIVE_RE.match(candidate):
            return "", "path must not contain a Windows drive prefix"

        parsed = PurePosixPath(candidate)
        if parsed.is_absolute() or any(part == ".." for part in parsed.parts):
            return "", "path must be relative and must not contain '..'"
        if parsed == PurePosixPath("."):
            return "", "path must identify a file"

        normalized = parsed.as_posix()
        if normalized.startswith("../") or normalized == "..":
            return "", "path escapes the configured root"
        return normalized, ""

    @staticmethod
    def _decode_git_output(value: bytes) -> str:
        return value.decode("utf-8", errors="replace")

    @classmethod
    def _paths_from_numstat(cls, stdout: bytes) -> Tuple[List[str], str]:
        """Parse git apply --numstat -z output and reject rename/copy records."""
        records = stdout.split(b"\x00")
        if records and records[-1] == b"":
            records.pop()

        paths: List[str] = []
        for record in records:
            fields = record.split(b"\t", 2)
            if len(fields) != 3:
                return [], "Could not parse the patch's affected paths"
            raw_path = fields[2]
            if not raw_path:
                return [], "Rename and copy patches are not supported"
            paths.append(raw_path.decode("utf-8", errors="surrogateescape"))
        return paths, ""

    def execute(
        self,
        args: Dict[str, Any],
        *,
        account_name: str = "auto",
        **context: Any,
    ) -> Dict[str, Any]:
        if not isinstance(args, dict):
            return self._invalid("arguments must be an object")

        location_value = args.get("location", "external")
        external_root_value = args.get("external_root")
        raw_path = args.get("path")
        patch_content = args.get("patch_content")
        check_only = args.get("check_only")

        if not isinstance(location_value, str):
            return self._invalid("location must be a string")
        location = location_value.strip()

        if not isinstance(external_root_value, str):
            return self._invalid("external_root must be a string", location=location)
        external_root = external_root_value.strip()

        if location not in ("storage", "external"):
            return self._invalid(
                "location must be 'storage' or 'external'",
                location=location,
                external_root=external_root,
            )
        if location == "storage" and external_root:
            return self._invalid(
                "external_root must be empty for location='storage'",
                location=location,
                external_root=external_root,
            )
        if location == "external" and not external_root:
            return self._invalid(
                "external_root is required for location='external'",
                location=location,
            )

        normalized_path, path_error = self._validate_relative_path(raw_path)
        if path_error:
            return self._invalid(
                path_error,
                location=location,
                external_root=external_root,
                path=raw_path if isinstance(raw_path, str) else "",
            )

        if not isinstance(patch_content, str) or not patch_content:
            return self._invalid(
                "patch_content must be a non-empty string",
                location=location,
                external_root=external_root,
                path=normalized_path,
            )
        if len(patch_content.encode("utf-8")) > _MAX_PATCH_BYTES:
            return self._invalid(
                f"patch_content exceeds the {_MAX_PATCH_BYTES}-byte limit",
                location=location,
                external_root=external_root,
                path=normalized_path,
            )
        if not isinstance(check_only, bool):
            return self._invalid(
                "check_only must be a boolean",
                location=location,
                external_root=external_root,
                path=normalized_path,
            )

        if patch_content.lstrip().startswith("*** Begin Patch"):
            return self._invalid(
                "unsupported patch format: use a unified diff, not *** Begin Patch",
                location=location,
                external_root=external_root,
                path=normalized_path,
                details="Use --- a/<path>, +++ b/<path> (or prefix-free headers) "
                "and numbered @@ -old,count +new,count @@ hunks.",
            )

        forbidden_markers = (
            "GIT binary patch",
            "new file mode 120000",
            "new mode 120000",
            "old mode 120000",
        )
        if any(marker in patch_content for marker in forbidden_markers):
            return self._invalid(
                "binary patches and symbolic-link mode changes are not supported",
                location=location,
                external_root=external_root,
                path=normalized_path,
            )

        try:
            if location == "storage":
                resolved_base = self._storage_resolver.storage_base_dir()
            else:
                resolved_base = self._storage_resolver.external_root_dir(external_root)
        except (TypeError, ValueError) as exc:
            return self._invalid(
                str(exc),
                location=location,
                external_root=external_root,
                path=normalized_path,
            )

        base_dir = os.path.realpath(os.path.abspath(resolved_base))
        if not os.path.isdir(base_dir):
            return self._invalid(
                "configured root is not an existing directory",
                location=location,
                external_root=external_root,
                path=normalized_path,
                details=base_dir,
            )

        target_path = os.path.realpath(os.path.join(base_dir, normalized_path))
        try:
            contained = os.path.commonpath([base_dir, target_path]) == base_dir
        except ValueError:
            contained = False
        if not contained:
            return self._invalid(
                "path escapes the configured root",
                location=location,
                external_root=external_root,
                path=normalized_path,
            )

        git_executable = shutil.which("git")
        if git_executable is None:
            return self._invalid(
                "git was not found on PATH",
                location=location,
                external_root=external_root,
                path=normalized_path,
            )

        patch_file = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".patch",
                delete=False,
                encoding="utf-8",
            ) as handle:
                handle.write(patch_content)
                patch_file = handle.name

            # Match the caller's exact root-relative target before selecting a
            # strip setting. Never guess by shortening the requested path, and
            # never change the setting after a failed content check.
            path_attempts = []
            strip_components = None
            for candidate in (1, 0):
                numstat = subprocess.run(
                    [git_executable, "apply", f"-p{candidate}", "--numstat", "-z", patch_file],
                    cwd=base_dir,
                    capture_output=True,
                    timeout=_GIT_TIMEOUT_SECONDS,
                )
                affected_paths, parse_error = (self._paths_from_numstat(numstat.stdout)
                    if numstat.returncode == 0 else ([], "could not inspect patch paths"))
                path_attempts.append({
                    "strip_components": candidate,
                    "affected_paths": affected_paths,
                    "error": parse_error,
                    "stdout": self._decode_git_output(numstat.stdout),
                    "stderr": self._decode_git_output(numstat.stderr),
                })
                if not parse_error and affected_paths == [normalized_path]:
                    strip_components = candidate
                    break

            if strip_components is None:
                inspected = next((attempt for attempt in path_attempts if not attempt["error"]), None)
                diagnostic = inspected or path_attempts[0]
                return self._invalid(
                    "patch must affect exactly the requested path" if inspected else diagnostic["error"],
                    location=location,
                    external_root=external_root,
                    path=normalized_path,
                    affected_paths=diagnostic["affected_paths"],
                    path_attempts=path_attempts,
                    stdout=diagnostic["stdout"],
                    stderr=diagnostic["stderr"],
                    details="Keep path relative to the selected root. Diff headers must name that "
                    "same file, either with a/ and b/ prefixes or without prefixes. "
                    "For malformed hunks, correct the numbered hunk counts; do not shorten path.",
                )

            checked = subprocess.run(
                [git_executable, "apply", f"-p{strip_components}", "--check", patch_file],
                cwd=base_dir,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            if checked.returncode != 0:
                return self._invalid(
                    "git apply --check failed",
                    location=location,
                    external_root=external_root,
                    path=normalized_path,
                    affected_paths=affected_paths,
                    strip_components=strip_components,
                    stdout=checked.stdout,
                    stderr=checked.stderr,
                )

            if check_only:
                return self._result(
                    ok=True,
                    applied=False,
                    location=location,
                    external_root=external_root,
                    path=normalized_path,
                    affected_paths=affected_paths,
                    strip_components=strip_components,
                    stdout=checked.stdout,
                    stderr=checked.stderr,
                )

            applied = subprocess.run(
                [git_executable, "apply", f"-p{strip_components}", patch_file],
                cwd=base_dir,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            if applied.returncode != 0:
                return self._invalid(
                    "git apply failed",
                    location=location,
                    external_root=external_root,
                    path=normalized_path,
                    affected_paths=affected_paths,
                    strip_components=strip_components,
                    stdout=applied.stdout,
                    stderr=applied.stderr,
                )

            return self._result(
                ok=True,
                applied=True,
                location=location,
                external_root=external_root,
                path=normalized_path,
                affected_paths=affected_paths,
                strip_components=strip_components,
                stdout=applied.stdout,
                stderr=applied.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return self._invalid(
                "git apply timed out",
                location=location,
                external_root=external_root,
                path=normalized_path,
                details=str(exc),
            )
        except OSError as exc:
            logger.exception("patch_apply operating-system failure")
            return self._invalid(
                "operating-system error while applying patch",
                location=location,
                external_root=external_root,
                path=normalized_path,
                details=str(exc),
            )
        finally:
            if patch_file:
                try:
                    os.remove(patch_file)
                except OSError:
                    logger.warning(
                        "Could not remove temporary patch file %s",
                        patch_file,
                        exc_info=True,
                    )

    def execute_raw(
        self,
        arguments_raw: str,
        *,
        account_name: str = "auto",
        call_id: str = "",
        **context: Any,
    ) -> str:
        try:
            args = json.loads(arguments_raw)
        except (TypeError, json.JSONDecodeError) as exc:
            return json.dumps(
                self._invalid("arguments_raw is not valid JSON", details=str(exc)),
                ensure_ascii=False,
            )

        if not isinstance(args, dict):
            return json.dumps(
                self._invalid("arguments_raw must decode to an object"),
                ensure_ascii=False,
            )

        return json.dumps(
            self.execute(args, account_name=account_name, **context),
            ensure_ascii=False,
        )


__all__ = ["PatchApplyHandler2"]

