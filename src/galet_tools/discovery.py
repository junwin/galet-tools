from __future__ import annotations

from importlib.metadata import entry_points
from typing import Iterable

from galet_tools.framework.handler_registry import HandlerRegistry

ENTRY_POINT_GROUP = "galet_tools.handlers"


class HandlerPluginError(RuntimeError):
    """Raised when an installed handler plugin cannot be registered."""


def _handler_entry_points(group: str) -> Iterable[object]:
    """Return handler entry points in deterministic order.

    The fallback supports the mapping-style object returned by older
    importlib-metadata releases, even though galet-tools itself requires
    Python 3.11 or newer.
    """
    discovered = entry_points()
    if hasattr(discovered, "select"):
        selected = discovered.select(group=group)
    else:  # pragma: no cover - compatibility with old importlib-metadata
        selected = discovered.get(group, ())
    return sorted(selected, key=lambda ep: (ep.name, ep.value))


def register_installed_handlers(
    registry: HandlerRegistry,
    *,
    group: str = ENTRY_POINT_GROUP,
) -> list[str]:
    """Load installed handler registrars and apply them to ``registry``.

    Packages contribute a callable through the ``galet_tools.handlers``
    entry-point group. The callable receives the registry and registers one
    or more HandlerV2 classes. Broken plugins fail startup with the entry-point
    name included, rather than silently removing tools from the host.

    Returns the entry-point names in the order they were invoked.
    """
    loaded: list[str] = []
    for entry_point in _handler_entry_points(group):
        try:
            registrar = entry_point.load()
        except Exception as exc:
            raise HandlerPluginError(
                f"Could not load handler plugin {entry_point.name!r} "
                f"({entry_point.value})"
            ) from exc

        if not callable(registrar):
            raise HandlerPluginError(
                f"Handler plugin {entry_point.name!r} ({entry_point.value}) "
                "must resolve to a callable registrar"
            )

        try:
            registrar(registry)
        except Exception as exc:
            raise HandlerPluginError(
                f"Handler plugin {entry_point.name!r} ({entry_point.value}) "
                "failed during registration"
            ) from exc
        loaded.append(entry_point.name)

    return loaded
