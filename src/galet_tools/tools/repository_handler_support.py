from __future__ import annotations

import os
from typing import Any

from galet_tools.ports.storage_location_resolver import StorageLocationResolver


def resolve_repository_root(
    resolver: StorageLocationResolver,
    args: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    location = (args.get("location") or "storage").strip().lower()
    external_root = (args.get("external_root") or "").strip()
    relative_root = (args.get("root") or ".").strip()

    if os.path.isabs(relative_root) or relative_root == ".." or relative_root.startswith("../"):
        return None, {"error": "root must be relative and remain within the configured location"}

    try:
        if location == "storage":
            if external_root:
                return None, {"error": "external_root must be '' when location='storage'"}
            base = resolver.storage_base_dir()
        elif location == "external":
            if not external_root:
                return None, {"error": "external_root is required when location='external'"}
            base = resolver.external_root_dir(external_root)
        else:
            return None, {"error": f"Unknown location '{location}'"}
    except Exception as exc:
        return None, {"error": str(exc)}

    base_real = os.path.realpath(base)
    root_real = os.path.realpath(os.path.join(base_real, relative_root))
    try:
        if os.path.commonpath([base_real, root_real]) != base_real:
            return None, {"error": "root resolves outside the configured location"}
    except ValueError:
        return None, {"error": "root resolves outside the configured location"}
    if not os.path.isdir(root_real):
        return None, {"error": f"repository root is not a directory: {relative_root}"}
    return root_real, None
