from __future__ import annotations

from typing import Protocol


class SandboxRootResolver(Protocol):
    """Resolves the sandbox base directory that commands run under."""

    def sandbox_base_dir(self, *, account_name: str) -> str:
        """Return the absolute sandbox base directory for the account.

        Built from the code sandbox path fenced per account. Raises
        ValueError when the code sandbox path is missing or unset.
        """
        ...
