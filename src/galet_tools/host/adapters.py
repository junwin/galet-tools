"""Concrete config-backed port adapters for galet-tools hosts."""

from __future__ import annotations

import os

from galet_tools.host.config import GaletConfig


class ConfigStorageLocationResolver:
    """StorageLocationResolver backed by a GaletConfig."""

    def __init__(self, config: GaletConfig) -> None:
        self._config = config

    def storage_base_dir(self) -> str:
        root = self._config.storage_root
        namespace = self._config.storage_namespace
        if not root or not namespace:
            raise ValueError("storage_root and storage_namespace are required")
        base = os.path.join(root, namespace)
        os.makedirs(base, exist_ok=True)
        return os.path.abspath(base)

    def external_root_dir(self, name: str) -> str:
        if name not in self._config.external_roots:
            raise ValueError(f"external root not found: {name}")
        return self._config.external_roots[name]


class ConfigSandboxRootResolver:
    """SandboxRootResolver that fences the sandbox base per account."""

    def __init__(self, config: GaletConfig) -> None:
        self._config = config

    def sandbox_base_dir(self, *, account_name: str) -> str:
        root = self._config.sandbox_root
        if not root:
            raise ValueError("sandbox_root is required")
        account = (account_name or "").strip()
        if not account or account in (".", ".."):
            raise ValueError("account_name is required for sandbox fencing")
        if os.path.sep in account or (os.path.altsep and os.path.altsep in account):
            raise ValueError("account_name must be a single path segment")
        base = os.path.join(root, account)
        os.makedirs(base, exist_ok=True)
        return os.path.abspath(base)


class GaletConfigProvider:
    """ConfigProvider backed by the configured font path list."""

    def __init__(self, config: GaletConfig) -> None:
        self._config = config

    def truetype_font_paths(self) -> list[str]:
        return list(self._config.fonts)
