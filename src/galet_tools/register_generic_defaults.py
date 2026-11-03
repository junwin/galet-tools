"""Backward-compatible strict registration of generic defaults."""
from __future__ import annotations

from galet_tools.composition import ServiceProvider, register_builtin_handlers
from galet_tools.framework.handler_registry import HandlerRegistry


def register_generic_defaults(
    reg: HandlerRegistry, *, services: ServiceProvider | None = None,
) -> None:
    """Register built-ins, rejecting duplicates as before.

    Hosts composing their own adapters should use register_builtin_handlers,
    whose default collision policy preserves existing host registrations.
    """
    register_builtin_handlers(reg, services=services, collision="error")
