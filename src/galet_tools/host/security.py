"""Default SecurityPolicy porting Lucy's execute_command inline guards."""

from __future__ import annotations

import os
import re
import shlex
import sys

IS_WINDOWS = sys.platform == "win32"

_SHELL_PATTERN_PIECES = [
    r"\|\|",
    r"&&",
    r"\|",
    r">>",
    r">",
    r"<<",
    r"<",
    r"\$\(",
    r"`",
    r"2>",
    r"2>>",
]


class DefaultSecurityPolicy:
    """Command allow/deny decision and output limit for execute_command.

    Ports the interactive-shell refusal, shell-syntax wrapper enforcement,
    and the 10_000-character output limit that Lucy kept inline in
    execute_command.
    """

    INTERACTIVE_BARE = frozenset(
        {"python", "python3", "bash", "sh", "zsh", "powershell.exe", "pwsh", "cmd.exe"}
    )
    SUPPORTED_WRAPPERS = frozenset({"none", "bash", "powershell"})
    DEFAULT_MAX_OUTPUT_CHARS = 10_000

    def __init__(self, *, max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> None:
        self._max_output_chars = max_output_chars
        patterns = list(_SHELL_PATTERN_PIECES)
        if not IS_WINDOWS:
            patterns.insert(3, r";")
        self._shell_syntax_re = re.compile("|".join(f"({p})" for p in patterns))

    def is_command_allowed(self, command: str, *, wrapper: str = "none") -> bool:
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

    def _is_bare_interactive(self, command: str) -> bool:
        try:
            parts = shlex.split(command or "", posix=(os.name != "nt"))
        except Exception:
            return True

        if not parts:
            return True

        prog = parts[0]

        if prog in self.INTERACTIVE_BARE and len(parts) == 1:
            return True

        if prog == "bash" and not any(p in ("-c", "-lc") for p in parts[1:]):
            return True

        if os.path.basename(prog).lower() in ("powershell.exe", "pwsh") and not any(
            p.lower() == "-command" for p in parts[1:]
        ):
            return True

        if os.path.basename(prog).lower() == "cmd.exe" and not any(
            p.lower() == "/c" for p in parts[1:]
        ):
            return True

        return False

    def _contains_shell_syntax(self, command: str) -> bool:
        try:
            parts = shlex.split(command or "", posix=(os.name != "nt"))
        except Exception:
            return True

        if parts:
            prog = os.path.basename(parts[0])
            if prog == "bash":
                for p in parts[1:3]:
                    if p in ("-c", "-lc"):
                        return False

        return self._shell_syntax_re.search(command or "") is not None
