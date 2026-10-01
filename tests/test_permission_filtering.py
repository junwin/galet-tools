"""Permission filtering: registry ∩ agent.allowed_tools ∩ context list."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from galet_tools.framework.handler_registry import HandlerRegistry, filter_eligible_tool_defs
from galet_tools.register_generic_defaults import register_generic_defaults

DEFS: List[Dict[str, Any]] = [{"name": "t1"}, {"name": "t2"}, {"name": "t3"}]


def _agent(allowed_tools: Optional[List[str]] = None) -> SimpleNamespace:
    return SimpleNamespace(name="agent", allowed_tools=allowed_tools)


def _context(allowed_tools: Optional[List[str]] = None) -> SimpleNamespace:
    if allowed_tools is None:
        return SimpleNamespace(extra={})
    return SimpleNamespace(extra={"allowed_tools": allowed_tools})


def _names(fds: List[Dict[str, Any]]) -> List[str]:
    return [fd["name"] for fd in fds]


class TestAgentCeiling:
    """agent.allowed_tools is the ceiling; missing or empty allows nothing."""

    def test_missing_allowed_tools_allows_none(self) -> None:
        assert filter_eligible_tool_defs(DEFS, _agent(None)) == []

    def test_empty_allowed_tools_allows_none(self) -> None:
        assert filter_eligible_tool_defs(DEFS, _agent([])) == []

    def test_agent_without_allowed_tools_attribute_allows_none(self) -> None:
        assert filter_eligible_tool_defs(DEFS, SimpleNamespace(name="bare")) == []

    def test_subset_preserves_registry_order(self) -> None:
        result = filter_eligible_tool_defs(DEFS, _agent(["t3", "t1"]))
        assert _names(result) == ["t1", "t3"]

    def test_unknown_names_ignored_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        result = filter_eligible_tool_defs(DEFS, _agent(["t2", "nope"]))
        assert _names(result) == ["t2"]
        assert any("unknown allowed_tools entries" in r.getMessage() for r in caplog.records)


class TestContextNarrowing:
    """A non-empty context tool list narrows; it can never grant tools."""

    def test_no_context_uses_agent_tools(self) -> None:
        result = filter_eligible_tool_defs(DEFS, _agent(["t1", "t3"]), None)
        assert _names(result) == ["t1", "t3"]

    def test_context_without_tool_list_uses_agent_tools(self) -> None:
        result = filter_eligible_tool_defs(DEFS, _agent(["t1", "t3"]), _context())
        assert _names(result) == ["t1", "t3"]

    def test_context_empty_list_does_not_restrict(self) -> None:
        result = filter_eligible_tool_defs(DEFS, _agent(["t1", "t2"]), _context([]))
        assert _names(result) == ["t1", "t2"]

    def test_context_list_narrows_agent_tools_registry_order_wins(self) -> None:
        result = filter_eligible_tool_defs(DEFS, _agent(["t1", "t2", "t3"]), _context(["t3", "t1"]))
        assert _names(result) == ["t1", "t3"]

    def test_context_exceeding_agent_permissions_clamped_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        result = filter_eligible_tool_defs(DEFS, _agent(["t1"]), _context(["t1", "t2", "t3"]))
        assert _names(result) == ["t1"]
        assert any("exceeds agent" in r.getMessage() and "clamped" in r.getMessage() for r in caplog.records)

    def test_context_cannot_grant_when_agent_has_no_tools(self) -> None:
        result = filter_eligible_tool_defs(DEFS, _agent(None), _context(["t1"]))
        assert result == []

    def test_context_unknown_entries_ignored_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        result = filter_eligible_tool_defs(DEFS, _agent(["t1", "t2", "t3"]), _context(["t1", "bogus"]))
        assert _names(result) == ["t1"]
        assert any("unknown entries" in r.getMessage() for r in caplog.records)


class TestRegistryEligible:
    """Registry-level eligibility helpers apply the same filtering."""

    def test_registry_eligible_tool_defs_intersects_agent(self) -> None:
        reg = HandlerRegistry()
        register_generic_defaults(reg)
        result = reg.eligible_tool_defs(_agent(["file_save", "generate_svg"]))
        assert _names(result) == ["file_save", "generate_svg"]

    def test_registry_eligible_tool_names_preserve_registry_order(self) -> None:
        reg = HandlerRegistry()
        register_generic_defaults(reg)
        result = reg.eligible_tool_names(_agent(["generate_svg", "execute_command"]))
        assert result == ["execute_command", "generate_svg"]
