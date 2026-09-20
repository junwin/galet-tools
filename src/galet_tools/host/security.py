"""Default execution security policy used by both command APIs."""

from __future__ import annotations

import os
import re
import shlex
import sys
from typing import Sequence

IS_WINDOWS = sys.platform == "win32"

_SHELL_PATTERN_PIECES = [r"\|\|", r"&&", r"\|", r">>", r">", r"<<", r"<", r"\$\(", r"`", r"2>", r"2>>"]


class DefaultSecurityPolicy:
    """Fail-closed checks and output limits for command execution."""

    INTERACTIVE_BARE = frozenset(
        {"python", "python3", "bash", "sh", "zsh", "powershell", "pwsh", "cmd"}
    )
    SHELL_EXECUTABLES = frozenset({"bash", "sh", "zsh", "powershell", "pwsh", "cmd"})
    SUPPORTED_WRAPPERS = frozenset({"none", "bash", "powershell"})
    DEFAULT_MAX_OUTPUT_CHARS = 10_000

    def __init__(self, *, max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> None:
        self._max_output_chars = max_output_chars
        patterns = list(_SHELL_PATTERN_PIECES)
        if not IS_WINDOWS:
            patterns.insert(3, r";")
        self._shell_syntax_re = re.compile("|".join(f"({piece})" for piece in patterns))

    def is_execution_allowed(
        self,
        *,
        mode: str,
        executable: str,
        arguments: Sequence[str],
        script: str,
        shell: str,
    ) -> bool:
        """Evaluate an unambiguous process or shell execution request."""
        if mode == "process":
            if not executable or script or shell != "none":
                return False
            normalized = self._normalized_executable(executable)
            if normalized in self.SHELL_EXECUTABLES:
                return False
            return not (normalized in self.INTERACTIVE_BARE and not arguments)
        if mode == "shell":
            return (
                not executable
                and not arguments
                and bool(script.strip())
                and shell in {"bash", "powershell"}
            )
        return False

    def is_command_allowed(self, command: str, *, wrapper: str = "none") -> bool:
        """Retain the legacy string-command policy for execute_command."""
        wrapper = (wrapper or "none").strip().lower()
        if wrapper not in self.SUPPORTED_WRAPPERS:
            return False
        if self._is_bare_interactive(command):
            return False
        if wrapper == "none" and self._contains_shell_syntax(command):
            return False
        return True

    def max_output_chars(self) -> int:
        return self._max_output_chars

    @staticmethod
    def _normalized_executable(executable: str) -> str:
        name = os.path.basename(executable).lower()
        return name[:-4] if name.endswith(".exe") else name

    def _is_bare_interactive(self, command: str) -> bool:
        try:
            parts = shlex.split(command or "", posix=(os.name != "nt"))
        except Exception:
            return True
        if not parts:
            return True
        program = self._normalized_executable(parts[0])
        if program in self.INTERACTIVE_BARE and len(parts) == 1:
            return True
        if program in {"bash", "sh", "zsh"} and not any(part in ("-c", "-lc") for part in parts[1:]):
            return True
        if program in {"powershell", "pwsh"} and not any(part.lower() == "-command" for part in parts[1:]):
            return True
        if program == "cmd" and not any(part.lower() == "/c" for part in parts[1:]):
            return True
        return False

    def _contains_shell_syntax(self, command: str) -> bool:
        try:
            parts = shlex.split(command or "", posix=(os.name != "nt"))
        except Exception:
            return True
        if parts and self._normalized_executable(parts[0]) in {"bash", "sh", "zsh"}:
            if any(part in ("-c", "-lc") for part in parts[1:3]):
                return False
        return self._shell_syntax_re.search(command or "") is not None
