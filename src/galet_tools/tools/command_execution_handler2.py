from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.sandbox_root_resolver import SandboxRootResolver
from galet_tools.ports.security_policy import SecurityPolicy
from galet_tools.ports.storage_location_resolver import StorageLocationResolver


IS_WINDOWS = sys.platform == "win32"


class CommandExecutionHandler2(HandlerV2):
    """Run a command under a configured named root.

    Callers give an external_root and a relative working_directory; '.' means
    the configured root itself, without account scoping. Legacy location calls
    retain their original sandbox/external behavior. Shell operators require
    an explicit wrapper. The
    SecurityPolicy port makes the allow/deny decision and sets the output
    truncation limit; path rules stay inline below.
    """

    NAME = "execute_command"

    _BENIGN_COMMANDS = {"grep", "egrep", "fgrep", "find", "test", "[", "which", "command"}

    def __init__(
        self,
        storage_resolver: StorageLocationResolver,
        sandbox_resolver: SandboxRootResolver,
        security_policy: SecurityPolicy,
    ) -> None:
        self._storage_resolver = storage_resolver
        self._sandbox_resolver = sandbox_resolver
        self._security_policy = security_policy

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Run a command under a configured named root. Non-interactive only, "
                "executed with shell=False. For pipes/redirects/conditionals wrap in bash -lc (Linux) "
                "or powershell (Windows). Don't use this to read files (use file_load)."
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
                    "command": {
                        "type": "string",
                        "description": "Command to run (shell=False). Wrap in bash -lc/powershell for shell operators.",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Relative dir under the selected root; '.' for root.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Timeout in seconds.",
                        "default": 30,
                    },
                    "success_exit_codes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Exit codes treated as success (default [0]).",
                        "default": [0],
                    },
                    "wrapper": {
                        "type": "string",
                        "enum": ["none", "bash", "powershell"],
                        "description": "Shell wrapper: 'none', 'bash', or 'powershell'. Set bash/powershell to allow shell operators.",
                        "default": "none",
                    },
                },
                "required": [ "external_root", "command", "working_directory", "timeout_seconds", "success_exit_codes", "wrapper"],
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
                "command": {"type": "string"},
                "working_directory": {"type": "string"},
                "normalized_working_directory": {"type": "string"},
                "resolved_working_directory": {"type": "string"},
                "returncode": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "result": {"type": "string"},
                "error": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["ok", "tool"],
            "additionalProperties": True,
        }

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto") -> Dict[str, Any]:
        location = (args.get("location") or ("external" if args.get("external_root") else "sandbox")).strip().lower()
        external_root = (args.get("external_root") or "").strip()
        command = (args.get("command") or "").strip()
        working_directory_in = (args.get("working_directory") or "").strip()
        timeout_seconds = args.get("timeout_seconds", 30)
        wrapper = (args.get("wrapper") or "none").strip().lower()

        if not command or not working_directory_in:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "command and working_directory are required",
                "location": location,
                "external_root": external_root,
                "command": command,
                "working_directory": working_directory_in,
            }

        if wrapper == "bash" and IS_WINDOWS:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "bash is not available on Windows. Use wrapper='powershell'.",
                "location": location,
                "external_root": external_root,
                "command": command,
                "working_directory": working_directory_in,
            }
        if wrapper == "powershell" and not IS_WINDOWS:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "PowerShell wrapper requested but the platform is not Windows. If you have pwsh (PowerShell Core) installed, prefer that; otherwise run the command using wrapper='bash' or leave wrapper='none' and avoid shell operators.",
                "location": location,
                "external_root": external_root,
                "command": command,
                "working_directory": working_directory_in,
            }

        if not self._security_policy.is_command_allowed(command, wrapper=wrapper):
            return {
                "ok": False,
                "tool": self.NAME,
                "error": "Command refused by security policy",
                "location": location,
                "external_root": external_root,
                "command": command,
                "working_directory": working_directory_in,
            }

        norm_wd, err = self._validate_and_normalize_relative_path(working_directory_in)
        if err:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": err,
                "location": location,
                "external_root": external_root,
                "working_directory": working_directory_in,
            }

        try:
            if location == "sandbox":
                if external_root:
                    return {
                        "ok": False,
                        "tool": self.NAME,
                        "error": "external_root must be '' when location='sandbox'",
                        "location": location,
                        "external_root": external_root,
                        "working_directory": working_directory_in,
                    }
                base_dir = self._sandbox_resolver.sandbox_base_dir(account_name=account_name)
            elif location == "external":
                if not external_root:
                    return {
                        "ok": False,
                        "tool": self.NAME,
                        "error": "external_root is required when location='external'",
                        "location": location,
                        "external_root": external_root,
                        "working_directory": working_directory_in,
                    }
                base_dir = self._storage_resolver.external_root_dir(external_root)
            else:
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "error": f"Unknown location '{location}'",
                    "location": location,
                    "external_root": external_root,
                    "working_directory": working_directory_in,
                }
        except Exception as e:
            logging.exception("execute_command: failed to resolve base directory")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(e),
                "location": location,
                "external_root": external_root,
                "working_directory": working_directory_in,
            }

        try:
            resolved_dir = self._resolve_dir_safe(base_dir, norm_wd)
        except Exception as e:
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(e),
                "location": location,
                "external_root": external_root,
                "working_directory": working_directory_in,
                "normalized_working_directory": norm_wd,
                "base_dir": base_dir,
            }

        logging.info(
            "execute_command: account=%s location=%s external_root=%s working_directory=%s command=%s",
            account_name,
            location,
            external_root,
            working_directory_in,
            command,
        )

        success_exit_codes = args.get("success_exit_codes", [0])
        if not isinstance(success_exit_codes, list) or not all(isinstance(x, int) for x in success_exit_codes):
            success_exit_codes = [0]

        max_output_chars = self._security_policy.max_output_chars()

        try:
            rc, out_raw, err_raw = self._execute_script(command, resolved_dir, timeout=int(timeout_seconds), wrapper=wrapper)

            out = self._truncate(out_raw, limit=max_output_chars)
            err = self._truncate(err_raw, limit=max_output_chars)

        except Exception as e:
            logging.exception("execute_command failed")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(e),
                "location": location,
                "external_root": external_root,
                "command": command,
                "working_directory": working_directory_in,
                "normalized_working_directory": norm_wd,
                "resolved_working_directory": resolved_dir,
            }

        ok = rc in success_exit_codes

        if ok:
            if out.strip():
                result_str = out.strip()
            elif err.strip():
                result_str = err.strip()
            else:
                result_str = "success"
        else:
            result_str = f"error {rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}"

        result = {
            "ok": ok,
            "tool": self.NAME,
            "location": location,
            "external_root": external_root,
            "command": command,
            "working_directory": working_directory_in,
            "normalized_working_directory": norm_wd,
            "resolved_working_directory": resolved_dir,
            "returncode": rc,
            "stdout": out,
            "stderr": err,
            "result": result_str,
        }

        if not ok and self._is_benign_command(command):
            result["status"] = "warning"

        return result

    def execute_raw(self, arguments_raw: str, *, account_name: str = "auto", call_id: str = "", **context: Any) -> str:
        """Apply back-compat defaults for missing keys, then run execute."""
        try:
            args = json.loads(arguments_raw or "{}")
        except Exception:
            args = {}

        if isinstance(args, dict):
            if "location" not in args:
                args["location"] = "external" if args.get("external_root") else "sandbox"
            if "external_root" not in args:
                args["external_root"] = ""
            if "timeout_seconds" not in args:
                args["timeout_seconds"] = 30
            if "wrapper" not in args:
                args["wrapper"] = "none"

        result = self.execute(args if isinstance(args, dict) else {}, account_name=account_name)
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _has_drive_letter(path: str) -> bool:
        return len(path) >= 2 and path[1] == ":" and path[0].isalpha()

    def _validate_and_normalize_relative_path(self, path_in: str) -> Tuple[str, str]:
        if self._has_drive_letter(path_in):
            return "", "working_directory must be relative, not include drive letters"
        if os.path.isabs(path_in):
            return "", "working_directory must be relative, not absolute"

        norm_rel = os.path.normpath(path_in)

        if norm_rel in ("", ".."):
            return "", "working_directory must not be empty or point to parent directory"
        if norm_rel == ".":
            return ".", ""

        parts = [p for p in norm_rel.split(os.path.sep) if p]
        if os.path.altsep:
            parts = [p for seg in parts for p in seg.split(os.path.altsep) if p]
        if any(p == ".." for p in parts) or norm_rel.startswith(".."):
            return "", "working_directory must not contain '..' segments"

        return norm_rel, ""

    def _resolve_dir_safe(self, base_dir: str, rel_dir: str) -> str:
        """Resolve base_dir + rel_dir and enforce realpath containment."""
        base_abs = os.path.abspath(base_dir)
        full_path = os.path.normpath(os.path.join(base_abs, rel_dir))

        base_real = os.path.realpath(base_abs)
        full_real = os.path.realpath(full_path)

        if not (full_real == base_real or full_real.startswith(base_real + os.path.sep)):
            raise ValueError("Working directory outside allowed base path")

        if not os.path.isdir(full_real):
            raise ValueError(f"working dir does not exist: {full_real}")

        return full_real

    def _build_wrapper_argv(self, wrapper: str, command: str, cwd: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """Build argv for the chosen wrapper; returns (argv, cwd_to_pass)."""
        wrapper = (wrapper or "none").strip().lower()
        if wrapper == "none":
            return None, cwd

        if wrapper == "bash":
            return ["bash", "-lc", command], cwd

        if wrapper == "powershell":
            cwd_to_pass = cwd
            cmd = command
            if IS_WINDOWS and cwd and cwd.startswith("\\\\"):
                cmd = f"Set-Location -LiteralPath '{cwd}'; {command}"
                cwd_to_pass = None

            pwsh_path = shutil.which("pwsh")
            if pwsh_path:
                return [pwsh_path, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd], cwd_to_pass
            else:
                return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd], cwd_to_pass

        raise ValueError(f"Unknown wrapper: {wrapper}")

    def _execute_script(self, command: str, cwd: str, timeout: int = 30, wrapper: str = "none") -> tuple[int, str, str]:
        if wrapper and wrapper != "none":
            argv, cwd_to_pass = self._build_wrapper_argv(wrapper, command, cwd)
            completed = subprocess.run(
                argv,
                shell=False,
                cwd=cwd_to_pass,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return completed.returncode, completed.stdout or "", completed.stderr or ""

        argv = shlex.split(command, posix=(os.name != "nt"))

        completed = subprocess.run(
            argv,
            shell=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""

    def _truncate(self, text: str, limit: int) -> str:
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return (
            text[: limit // 2]
            + "\n\n[... output truncated ...]\n\n"
            + text[-limit // 2 :]
        )

    def _is_benign_command(self, command: str) -> bool:
        """Return whether a non-zero exit for command should be a warning.

        Benign commands: grep, egrep, fgrep, find, test, [, which, command,
        and diff with --brief/-q. Unwraps bash -c/-lc and PowerShell
        -Command to find the real program name.
        """
        try:
            parts = shlex.split(command, posix=(os.name != "nt"))
        except Exception:
            return False

        if not parts:
            return False

        relevant_parts = parts
        prog = parts[0]

        if os.path.basename(prog) == "bash":
            for i, p in enumerate(parts):
                if p in ("-c", "-lc") and i + 1 < len(parts):
                    try:
                        inner_parts = shlex.split(parts[i + 1], posix=(os.name != "nt"))
                    except Exception:
                        return False
                    if not inner_parts:
                        return False
                    relevant_parts = inner_parts
                    prog = inner_parts[0]
                    break

        base_prog = os.path.basename(prog).lower()
        if base_prog in ("powershell.exe", "pwsh"):
            for i, p in enumerate(parts):
                if p.lower() == "-command" and i + 1 < len(parts):
                    try:
                        inner_parts = shlex.split(parts[i + 1], posix=(os.name != "nt"))
                    except Exception:
                        return False
                    if not inner_parts:
                        return False
                    relevant_parts = inner_parts
                    prog = inner_parts[0]
                    break

        name = os.path.basename(prog)

        if name in self._BENIGN_COMMANDS:
            return True

        if name == "diff":
            if any(a in ("--brief", "-q") for a in relevant_parts):
                return True

        return False

