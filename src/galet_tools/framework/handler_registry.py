from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Type

from galet_tools.framework.handler_v2 import HandlerV2

logger = logging.getLogger(__name__)

HandlerFactory = Callable[[Any], HandlerV2]


def _context_tool_list(context_state: Any) -> Optional[List[str]]:
    """Extract the optional tool list from a Context-like object.

    allowed_tools is not a typed Context field, so legacy contexts still
    carrying it expose it through the catch-all extra dict (or an old data
    dict). Returns None when no tool list should be applied: no active
    context, missing extra/data dict, no 'allowed_tools' key, a non-list
    value, or an empty list (empty => no context restriction). A non-empty
    list is returned as-is so callers can intersect it with the agent's
    allowed_tools ceiling.
    """
    if context_state is None:
        return None
    extra = getattr(context_state, "extra", None)
    data = getattr(context_state, "data", None)
    raw = None
    if isinstance(extra, dict):
        raw = extra.get("allowed_tools")
    if raw is None and isinstance(data, dict):
        raw = data.get("allowed_tools")
    if raw is None:
        return None
    if isinstance(raw, (str, bytes)):
        return None
    try:
        lst = list(raw)
    except Exception:
        return None
    if not lst:
        return None
    return lst


def filter_eligible_tool_defs(
    tool_defs: List[Dict[str, Any]],
    agent: Any = None,
    context_state: Any = None,
) -> List[Dict[str, Any]]:
    """Resolve eligible tool definitions via registry ∩ agent ∩ context.

    Eligible = registry ∩ agent.allowed_tools, narrowed only when the active
    context carries an explicit non-empty tool list. Agent rules:
    agent.allowed_tools missing/None => no tools ([]); empty list => no
    tools ([]); otherwise only tools whose name appears in
    agent.allowed_tools, preserving registry order. Unknown names are
    logged and ignored. Context tool list (deterministic, no LLM call):
    no context, or no 'allowed_tools' key, or an empty list => the agent's
    allowed_tools apply unchanged. A non-empty list => effective = agent
    allowed_tools & context list, with the agent's list as the hard
    ceiling; context entries outside the agent's list or unknown to the
    registry are logged and ignored.
    """
    function_defs = tool_defs or []

    allowed = getattr(agent, "allowed_tools", None)
    if not allowed:
        return []

    try:
        allowed_list = list(allowed)
    except Exception:
        allowed_list = []

    available_names = [fd.get("name") for fd in function_defs]
    unknown = [n for n in allowed_list if n not in available_names]
    if unknown:
        logger.warning(
            "unknown allowed_tools entries for agent '%s': %s; ignoring",
            getattr(agent, "name", "<unknown>"),
            unknown,
        )

    allowed_set = set(n for n in allowed_list if n in available_names)

    context_tools = _context_tool_list(context_state)
    if context_tools is not None:
        context_known = [n for n in context_tools if n in available_names]
        context_unknown = [n for n in context_tools if n not in available_names]
        if context_unknown:
            logger.warning(
                "context tool list contains unknown entries: %s; ignoring",
                context_unknown,
            )
        clamped = [n for n in context_known if n not in allowed_set]
        if clamped:
            logger.warning(
                "context tool list exceeds agent '%s' allowed_tools; clamped: %s",
                getattr(agent, "name", "<unknown>"),
                clamped,
            )
        allowed_set = allowed_set & set(context_known)

    return [fd for fd in function_defs if fd.get("name") in allowed_set]


class HandlerRegistry:
    def __init__(self) -> None:
        self._by_name: Dict[str, Type[HandlerV2]] = {}
        self._factories: Dict[str, HandlerFactory] = {}
        self._result_schemas: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        handler_cls: Type[HandlerV2],
        *,
        factory: Optional[HandlerFactory] = None,
    ) -> None:
        """Register a handler class and optional host-provided factory."""
        name = handler_cls.name()
        if not name:
            raise ValueError("HandlerV2.name() must be non-empty")
        if name in self._by_name:
            raise ValueError(f"Duplicate handler name registered: {name}")

        self._by_name[name] = handler_cls
        if factory is not None:
            self._factories[name] = factory

        try:
            sch = handler_cls.result_schema()
            if sch is not None:
                self._result_schemas[name] = sch
        except Exception:
            pass

    def has_tool(self, name: str) -> bool:
        """Return True when a handler with `name` is registered."""
        return name in self._by_name

    def create(self, name: str, *, config: Any) -> HandlerV2:
        cls = self._by_name.get(name)
        if cls is None:
            raise KeyError(
                f"Unknown handler: {name!r}. Valid handlers: {self.tool_names()}"
            )
        factory = self._factories.get(name)
        if factory is not None:
            return factory(config)
        return cls(config)  # type: ignore[call-arg]

    def tools(self) -> List[Dict[str, Any]]:
        return [cls.tool_def() for cls in self._by_name.values()]

    def tool_names(self) -> List[str]:
        return sorted(self._by_name.keys())

    def eligible_tool_defs(
        self, agent: Any = None, context_state: Any = None
    ) -> List[Dict[str, Any]]:
        """Return the tool definitions `agent` is allowed to use.

        The permission ceiling is:

            registry ∩ agent.allowed_tools
                ∩ context.extra['allowed_tools']  (only when non-empty)

        An empty or missing context tool list does not restrict the agent's
        allowed tools. Equivalent to
        ``filter_eligible_tool_defs(self.tools(), agent, context_state)``.
        See that helper for the full filtering rules.
        """
        return filter_eligible_tool_defs(self.tools(), agent, context_state)

    def eligible_tool_names(
        self, agent: Any = None, context_state: Any = None
    ) -> List[str]:
        """Return the names of eligible tool defs (registry order preserved)."""
        return [
            fd.get("name")
            for fd in self.eligible_tool_defs(agent, context_state)
            if fd.get("name")
        ]

    def result_schema(self, name: str) -> Optional[Dict[str, Any]]:
        if name in self._result_schemas:
            return self._result_schemas[name]
        cls = self._by_name.get(name)
        if cls is None:
            return None
        return cls.result_schema()

    def all_result_schemas(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._result_schemas)
