from __future__ import annotations

from typing import Protocol


class StorageLocationResolver(Protocol):
    """Resolve arbitrary configured root names to absolute base directories.

    Named-root calls use external_root_dir only. Hosts supply their effective
    configuration, including any global/local overrides. A root name has no
    special meaning: callers append namespace/account segments when needed.
    storage_base_dir remains for legacy location='storage' calls and internal
    consumers that explicitly request a storage namespace.
    """

    def storage_base_dir(self) -> str:
        """Return the absolute storage base (storage_root_path joined with storage_namespace).

        Raises ValueError when the storage root path or the storage namespace is missing.
        """
        ...

    def external_root_dir(self, name: str) -> str:
        """Return the absolute directory for the named external root (external_roots[name]).

        Do not infer behavior from the name or append account/namespace paths.

        Raises ValueError when external_roots is not a map or the name is unknown.
        """
        ...

