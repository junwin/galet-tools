from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.sandbox_root_resolver import SandboxRootResolver
from galet_tools.ports.security_policy import SecurityPolicy
from galet_tools.ports.storage_location_resolver import StorageLocationResolver


IS_WINDOWS = sys.platform == "win32"


class ExecuteCommand2(HandlerV2):
    """Cross-platform command execution with an explicit process/shell split."""

    NAME = "execute_command2"

    def __init__(
        self,
        storage_resolver: StorageLocationResolver,
        sandbox_resolver: SandboxRootResolver,
        security_policy: SecurityPolicy,
    ) -> None:
        self._storage_resolver = storage_resolver
        self._sandbox_resolver = sandbox_resolver
        self._security_policy = security_policy
        self._shell_executables = self._detect_shells()

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @staticmethod
    def _detect_shells() -> Dict[str, str]:
        shells: Dict[str, str] = {}
        bash = shutil.which("bash")
        pwsh = shutil.which("pwsh")
        windows_powershell = shutil.which("powershell.exe") if IS_WINDOWS else None
        if bash:
            shells["bash"] = bash
        if pwsh:
            shells["powershell"] = pwsh
        elif windows_powershell:
            shells["powershell"] = windows_powershell
        return shells

    @classmethod
    def available_shells(cls) -> List[str]:
        return sorted(cls._detect_shells())

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        shells = cls.available_shells()
        host = "Windows" if IS_WINDOWS else "Linux"
        native = "powershell" if IS_WINDOWS else "bash"
        available = ", ".join(shells) if shells else "none"
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                f"Run a non-interactive process or shell script on this {host} host. "
                "For mode='process', provide an executable and an arguments array; quoting is not interpreted. "
                f"For pipes, redirects, conditionals, expansion, or shell commands use mode='shell' "
                f"and shell='{native}' when available. Detected shells: {available}. "
                "Do not put bash -lc, pwsh -Command, powershell.exe -Command, or cmd.exe /c in executable or script. "
                "Use file_load to read files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["process", "shell"]},
                    "executable": {
                        "type": "string",
                        "description": "Executable for process mode; empty for shell mode.",
                    },
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact argument vector for process mode; [] for shell mode.",
                    },
                    "script": {
                        "type": "string",
                        "description": "Shell source for shell mode; empty for process mode.",
                    },
                    "shell": {
                        "type": "string",
                        "enum": ["none", "bash", "powershell"],
                        "description": f"Use 'none' for process mode. Available shell-mode values on this host: {available}.",
                    },
                    "location": {"type": "string", "enum": ["sandbox", "external"]},
                    "external_root": {"type": "string"},
                    "working_directory": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                    "success_exit_codes": {"type": "array", "items": {"type": "integer"}},
                },
                "required": [
                    "mode", "executable", "arguments", "script", "shell", "location",
                    "external_root", "working_directory", "timeout_seconds", "success_exit_codes",
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
                "status": {"type": "string"},
                "error_code": {"type": "string"},
                "error": {"type": "string"},
                "returncode": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "result": {"type": "string"},
            },
            "required": ["ok", "tool"],
            "additionalProperties": True,
        }

    def _failure(self, code: str, message: str, **details: Any) -> Dict[str, Any]:
        return {"ok": False, "tool": self.NAME, "status": "error", "error_code": code, "error": message, **details}

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto") -> Dict[str, Any]:
        mode = str(args.get("mode") or "").strip().lower()
        executable = str(args.get("executable") or "").strip()
        arguments = args.get("arguments")
        script = str(args.get("script") or "")
        shell = str(args.get("shell") or "none").strip().lower()
        location = str(args.get("location") or "sandbox").strip().lower()
        external_root = str(args.get("external_root") or "").strip()
        working_directory = str(args.get("working_directory") or "").strip()
        timeout = args.get("timeout_seconds", 30)
        success_codes = args.get("success_exit_codes", [0])

        if mode not in {"process", "shell"}:
            return self._failure("invalid_mode", "mode must be 'process' or 'shell'")
        if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
            return self._failure("invalid_arguments", "arguments must be an array of strings")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            return self._failure("invalid_timeout", "timeout_seconds must be an integer from 1 to 3600")
        if not isinstance(success_codes, list) or not success_codes or not all(type(value) is int for value in success_codes):
            return self._failure("invalid_success_exit_codes", "success_exit_codes must be a non-empty array of integers")

        if mode == "process":
            if not executable or script or shell != "none":
                return self._failure(
                    "invalid_process_request",
                    "process mode requires executable, shell='none', and an empty script",
                )
            if self._looks_like_shell(executable):
                return self._failure(
                    "embedded_shell_refused",
                    "Do not invoke a shell as a process. Use mode='shell', choose shell separately, and put only shell source in script.",
                )
        else:
            if executable or arguments or not script or shell == "none":
                return self._failure(
                    "invalid_shell_request",
                    "shell mode requires an empty executable, an empty arguments array, a non-empty script, and a named shell",
                )
            if shell not in self._shell_executables:
                return self._failure(
                    "shell_unavailable",
                    f"Shell '{shell}' is unavailable on this {sys.platform} host. Available shells: {sorted(self._shell_executables) or ['none']}.",
                )

        allowed = self._is_allowed(mode, executable, arguments, script, shell)
        if not allowed:
            return self._failure("policy_refused", "Execution refused by security policy")

        norm_wd, path_error = self._validate_relative_path(working_directory)
        if path_error:
            return self._failure("invalid_working_directory", path_error)
        try:
            base_dir = self._resolve_base(location, external_root, account_name)
            resolved_dir = self._resolve_dir_safe(base_dir, norm_wd)
        except ValueError as exc:
            return self._failure("invalid_working_directory", str(exc))
        except Exception as exc:
            logging.exception("execute_command2 failed to resolve its working directory")
            return self._failure("location_resolution_failed", str(exc))

        argv = self._build_argv(mode, executable, arguments, script, shell)
        logging.info("execute_command2 account=%s mode=%s cwd=%s argv0=%s", account_name, mode, resolved_dir, argv[0])
        try:
            rc, stdout_bytes, stderr_bytes = self._run(argv, resolved_dir, timeout)
        except FileNotFoundError:
            return self._failure("executable_not_found", f"Executable '{argv[0]}' was not found on this host.")
        except PermissionError:
            return self._failure("permission_denied", f"Permission denied while starting '{argv[0]}'.")
        except subprocess.TimeoutExpired:
            return self._failure("timeout", f"Execution exceeded {timeout} seconds and its process tree was terminated.")
        except OSError as exc:
            return self._failure("process_start_failed", str(exc))

        limit = self._security_policy.max_output_chars()
        stdout = self._truncate(self._decode(stdout_bytes), limit)
        stderr = self._truncate(self._decode(stderr_bytes), limit)
        ok = rc in success_codes
        result_text = (stdout.strip() or stderr.strip() or "success") if ok else f"error {rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        return {
            "ok": ok,
            "tool": self.NAME,
            "status": "success" if ok else "error",
            "mode": mode,
            "executable": executable,
            "arguments": arguments,
            "script": script,
            "shell": shell,
            "location": location,
            "external_root": external_root,
            "working_directory": working_directory,
            "normalized_working_directory": norm_wd,
            "resolved_working_directory": resolved_dir,
            "returncode": rc,
            "stdout": stdout,
            "stderr": stderr,
            "result": result_text,
        }

    def execute_raw(self, arguments_raw: str, *, account_name: str = "auto", call_id: str = "", **context: Any) -> str:
        try:
            args = json.loads(arguments_raw or "{}")
        except Exception:
            args = {}
        result = self.execute(args if isinstance(args, dict) else {}, account_name=account_name)
        return json.dumps(result, ensure_ascii=False)

    def _is_allowed(self, mode: str, executable: str, arguments: List[str], script: str, shell: str) -> bool:
        structured = getattr(self._security_policy, "is_execution_allowed", None)
        if callable(structured):
            return bool(structured(mode=mode, executable=executable, arguments=arguments, script=script, shell=shell))
        legacy_command = " ".join([executable, *arguments]) if mode == "process" else script
        return bool(self._security_policy.is_command_allowed(legacy_command, wrapper=shell))

    @staticmethod
    def _looks_like_shell(executable: str) -> bool:
        name = os.path.basename(executable).lower()
        if name.endswith(".exe"):
            name = name[:-4]
        return name in {"bash", "sh", "zsh", "pwsh", "powershell", "cmd"}

    def _resolve_base(self, location: str, external_root: str, account_name: str) -> str:
        if location == "sandbox":
            if external_root:
                raise ValueError("external_root must be empty when location='sandbox'")
            return self._sandbox_resolver.sandbox_base_dir(account_name=account_name)
        if location == "external":
            if not external_root:
                raise ValueError("external_root is required when location='external'")
            return self._storage_resolver.external_root_dir(external_root)
        raise ValueError(f"Unknown location '{location}'")

    @staticmethod
    def _has_drive_letter(path: str) -> bool:
        return len(path) >= 2 and path[1] == ":" and path[0].isalpha()

    def _validate_relative_path(self, path: str) -> Tuple[str, str]:
        if not path:
            return "", "working_directory is required"
        if self._has_drive_letter(path) or os.path.isabs(path):
            return "", "working_directory must be relative"
        normalized = os.path.normpath(path)
        if normalized == ".." or normalized.startswith(".." + os.path.sep):
            return "", "working_directory must remain under its configured root"
        return normalized, ""

    @staticmethod
    def _resolve_dir_safe(base_dir: str, relative_dir: str) -> str:
        base_real = os.path.realpath(os.path.abspath(base_dir))
        full_real = os.path.realpath(os.path.join(base_real, relative_dir))
        try:
            common = os.path.commonpath([os.path.normcase(base_real), os.path.normcase(full_real)])
        except ValueError as exc:
            raise ValueError("Working directory is on a different drive from the allowed root") from exc
        if common != os.path.normcase(base_real):
            raise ValueError("Working directory is outside the allowed root")
        if not os.path.isdir(full_real):
            raise ValueError(f"working directory does not exist: {full_real}")
        return full_real

    def _build_argv(self, mode: str, executable: str, arguments: List[str], script: str, shell: str) -> List[str]:
        if mode == "process":
            return [executable, *arguments]
        shell_executable = self._shell_executables[shell]
        if shell == "bash":
            return [shell_executable, "-lc", script]
        utf8_script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + script
        argv = [shell_executable, "-NoLogo", "-NoProfile", "-NonInteractive"]
        if IS_WINDOWS:
            argv.extend(["-ExecutionPolicy", "Bypass"])
        return [*argv, "-Command", utf8_script]

    @staticmethod
    def _run(argv: List[str], cwd: str, timeout: int) -> Tuple[int, bytes, bytes]:
        kwargs: Dict[str, Any] = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            argv,
            shell=False,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            ExecuteCommand2._terminate_tree(process)
            process.communicate()
            raise
        return process.returncode, stdout or b"", stderr or b""

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _decode(value: bytes) -> str:
        return value.decode("utf-8", errors="replace")

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: limit // 2] + "\n\n[... output truncated ...]\n\n" + value[-limit // 2 :]
