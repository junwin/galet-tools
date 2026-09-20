from __future__ import annotations

from typing import Protocol, Sequence


class SecurityPolicy(Protocol):
    """Allow/deny decisions and output limits for both command APIs."""

    def is_command_allowed(self, command: str, *, wrapper: str = "none") -> bool:
        """Evaluate a legacy string command."""
        ...

    def is_execution_allowed(
        self,
        *,
        mode: str,
        executable: str,
        arguments: Sequence[str],
        script: str,
        shell: str,
    ) -> bool:
        """Evaluate a structured process or shell request."""
        ...

    def max_output_chars(self) -> int:
        """Return the output truncation limit in characters."""
        ...
