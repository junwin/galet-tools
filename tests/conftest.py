"""Shared fake port adapters for hermetic galet-tools tests."""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple


class FakeStorageResolver:
    def __init__(self, root: str, external_roots: Optional[Dict[str, str]] = None) -> None:
        self._storage_dir = os.path.join(root, "storage")
        os.makedirs(self._storage_dir, exist_ok=True)
        self._external_roots: Dict[str, str] = {}
        for name, path in (external_roots or {}).items():
            os.makedirs(path, exist_ok=True)
            self._external_roots[name] = path

    def storage_base_dir(self) -> str:
        return self._storage_dir

    def external_root_dir(self, name: str) -> str:
        if name not in self._external_roots:
            raise ValueError(f"external root not found: {name}")
        return self._external_roots[name]


class FakeSandboxResolver:
    def __init__(self, root: str) -> None:
        self._root = root

    def sandbox_base_dir(self, *, account_name: str) -> str:
        path = os.path.join(self._root, "sandbox", account_name)
        os.makedirs(path, exist_ok=True)
        return path


class FakeSecurityPolicy:
    def __init__(self, *, allowed: bool = True, max_chars: int = 10000, denied: Optional[List[str]] = None) -> None:
        self._allowed = allowed
        self._max_chars = max_chars
        self._denied = set(denied or [])
        self.calls: List[Tuple[str, str]] = []
        self.execution_calls: List[dict] = []

    def is_command_allowed(self, command: str, *, wrapper: str = "none") -> bool:
        self.calls.append((command, wrapper))
        return self._allowed and command not in self._denied

    def is_execution_allowed(self, *, mode: str, executable: str, arguments: Sequence[str], script: str, shell: str) -> bool:
        self.execution_calls.append({
            "mode": mode,
            "executable": executable,
            "arguments": list(arguments),
            "script": script,
            "shell": shell,
        })
        candidate = " ".join([executable, *arguments]) if mode == "process" else script
        return self._allowed and candidate not in self._denied

    def max_output_chars(self) -> int:
        return self._max_chars


class FakeConfigProvider:
    def __init__(self, font_paths: Optional[List[str]] = None) -> None:
        self._font_paths = list(font_paths or [])

    def truetype_font_paths(self) -> list[str]:
        return list(self._font_paths)
