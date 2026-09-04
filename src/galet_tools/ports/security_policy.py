from __future__ import annotations

from typing import Protocol


class SecurityPolicy(Protocol):
    """Command allow/deny decision and output limits for execute_command."""

    def is_command_allowed(self, command: str, *, wrapper: str = "none") -> bool:
        """Return whether the command may be executed with the given wrapper.

        Covers the interactive-shell and shell-syntax refusal rules inline in
        execute_command today, plus any host deny rules.
        """
        ...

    def max_output_chars(self) -> int:
        """Return the output truncation limit in characters."""
        ...
