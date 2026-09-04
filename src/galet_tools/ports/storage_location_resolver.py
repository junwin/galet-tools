from __future__ import annotations

from typing import Protocol


class StorageLocationResolver(Protocol):
    """Resolves named file locations to absolute base directories.

    The surface covers only what the file tools read: the storage base formed
    from the storage root path plus the storage namespace, and named external
    roots from the external_roots map.
    """

    def storage_base_dir(self) -> str:
        """Return the absolute storage base (storage_root_path joined with storage_namespace).

        Raises ValueError when the storage root path or the storage namespace is missing.
        """
        ...

    def external_root_dir(self, name: str) -> str:
        """Return the absolute directory for the named external root (external_roots[name]).

        Raises ValueError when external_roots is not a map or the name is unknown.
        """
        ...
