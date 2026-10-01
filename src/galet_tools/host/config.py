"""Host configuration for the galet MCP server (galet-mcp.json)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

DEFAULT_CONFIG_FILE = "galet-mcp.json"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

REGISTERED_TOOL_NAMES = (
    "file_load",
    "file_save",
    "patch_apply",
    "execute_command",
    "execute_command2",
    "generate_svg",
    "repo_index",
    "repo_search",
    "image_generate",
    "video_generate",
)

DEFAULT_ALLOWLIST = list(REGISTERED_TOOL_NAMES)


class GaletConfigError(Exception):
    """Raised when the config file is missing, invalid, or fails validation."""


@dataclass(frozen=True)
class GaletConfig:
    """Validated server configuration loaded from the JSON config file."""

    account: str
    allowlist: list[str]
    storage_root: str
    storage_namespace: str
    external_roots: dict[str, str]
    sandbox_root: str
    host: str
    port: int
    fonts: list[str]


def load_config(path: Optional[Union[str, os.PathLike]] = None) -> GaletConfig:
    """Load and validate the JSON config file; any schema error raises GaletConfigError."""
    config_path = Path(path) if path is not None else Path(DEFAULT_CONFIG_FILE)
    if not config_path.is_file():
        raise GaletConfigError(
            f"config file not found: {config_path} (default '{DEFAULT_CONFIG_FILE}' at the "
            "repo root; override with --config <path>)"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GaletConfigError(
            f"config file {config_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise GaletConfigError(
            f"config file {config_path} must contain a JSON object, got {type(raw).__name__}"
        )
    return _validate(raw, source=str(config_path))


def _validate(raw: Dict[str, Any], *, source: str) -> GaletConfig:
    def fail(message: str) -> None:
        raise GaletConfigError(f"invalid config {source}: {message}")

    def abs_path(value: Any, key: str) -> str:
        if not isinstance(value, str) or not value.strip():
            fail(f"key '{key}' must be a non-empty string path")
        expanded = os.path.expanduser(value.strip())
        if not os.path.isabs(expanded):
            fail(f"key '{key}' must be an absolute path, got {value!r}")
        return os.path.normpath(expanded)

    account_raw = raw.get("account")
    if not isinstance(account_raw, str) or not account_raw.strip():
        fail("key 'account' must be a non-empty string")
    account = account_raw.strip()

    allowlist_raw = raw.get("allowlist")
    if allowlist_raw is None:
        allowlist = list(DEFAULT_ALLOWLIST)
    else:
        if not isinstance(allowlist_raw, list) or not all(
            isinstance(x, str) for x in allowlist_raw
        ):
            fail("key 'allowlist' must be a list of tool name strings")
        allowlist = [x.strip() for x in allowlist_raw if x.strip()]
        unknown = [name for name in allowlist if name not in REGISTERED_TOOL_NAMES]
        if unknown:
            fail(
                "key 'allowlist' contains unknown tool names: "
                f"{sorted(set(unknown))}; registered tools: {sorted(REGISTERED_TOOL_NAMES)}"
            )
    if not allowlist:
        fail("key 'allowlist' must not be empty (fail closed: nothing to expose)")

    storage_root = abs_path(raw.get("storage_root"), "storage_root")

    namespace_raw = raw.get("storage_namespace")
    if not isinstance(namespace_raw, str) or not namespace_raw.strip():
        fail("key 'storage_namespace' must be a non-empty string")
    storage_namespace = namespace_raw.strip()

    roots_raw = raw.get("external_roots")
    if roots_raw is None:
        roots_raw = {}
    if not isinstance(roots_raw, dict):
        fail("key 'external_roots' must be an object mapping root names to absolute paths")
    external_roots: dict[str, str] = {}
    for name, value in roots_raw.items():
        if not isinstance(name, str) or not name.strip():
            fail("key 'external_roots' must use non-empty string names")
        external_roots[name.strip()] = abs_path(value, f"external_roots['{name}']")

    sandbox_root = abs_path(raw.get("sandbox_root"), "sandbox_root")

    host_raw = raw.get("host")
    if host_raw is None:
        host_raw = DEFAULT_HOST
    if not isinstance(host_raw, str) or not host_raw.strip():
        fail("key 'host' must be a string")
    host = host_raw.strip().lower()
    if host not in _ALLOWED_HOSTS:
        fail(
            f"key 'host' must be loopback only ({sorted(_ALLOWED_HOSTS)}), got {host!r}; "
            "remote access needs a separate reverse-proxy design"
        )

    port_raw = raw.get("port")
    if port_raw is None:
        port_raw = DEFAULT_PORT
    if isinstance(port_raw, bool):
        fail(f"key 'port' must be an integer, got {port_raw!r}")
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        fail(f"key 'port' must be an integer, got {port_raw!r}")
    if not 1 <= port <= 65535:
        fail(f"key 'port' must be in 1..65535, got {port}")

    fonts_raw = raw.get("fonts")
    if fonts_raw is None:
        fonts_raw = []
    if not isinstance(fonts_raw, list) or not all(isinstance(x, str) for x in fonts_raw):
        fail("key 'fonts' must be a list of font file path strings")
    fonts = [os.path.expanduser(x.strip()) for x in fonts_raw if x.strip()]

    return GaletConfig(
        account=account,
        allowlist=allowlist,
        storage_root=storage_root,
        storage_namespace=storage_namespace,
        external_roots=external_roots,
        sandbox_root=sandbox_root,
        host=host,
        port=port,
        fonts=fonts,
    )
