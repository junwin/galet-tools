"""Registry build via register_generic_defaults."""

from __future__ import annotations

import pytest

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.register_generic_defaults import register_generic_defaults
from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2

EXPECTED_NAMES = [
    "execute_command",
    "execute_command2",
    "file_load",
    "file_save",
    "generate_image",
    "generate_svg",
    "patch_apply",
    "repo_index",
    "repo_search",
]

PROPERTY_KEYS = {
    "file_load": {
        "location",
        "external_root",
        "path",
        "start_line",
        "line_count",
        "include_line_numbers",
    },
    "file_save": {"location", "external_root", "path", "file_content", "overwrite"},
    "patch_apply": {
        "location",
        "external_root",
        "path",
        "patch_content",
        "check_only",
    },
    "execute_command2": {
        "mode",
        "executable",
        "arguments",
        "script",
        "shell",
        "location",
        "external_root",
        "working_directory",
        "timeout_seconds",
        "success_exit_codes",
    },
    "execute_command": {
        "location",
        "external_root",
        "command",
        "working_directory",
        "timeout_seconds",
        "success_exit_codes",
        "wrapper",
    },
    "generate_svg": {"svg_code", "description", "width", "height"},
    "generate_image": {"description", "width", "height", "color"},
}


def _registry() -> HandlerRegistry:
    reg = HandlerRegistry()
    register_generic_defaults(reg)
    return reg


class TestRegistryBuild:
    """register_generic_defaults registers the expected generic tools."""

    def test_registers_expected_generic_tools(self) -> None:
        reg = _registry()
        assert reg.tool_names() == sorted(EXPECTED_NAMES)
        for name in EXPECTED_NAMES:
            assert reg.has_tool(name)

    def test_tool_defs_carry_registered_names_and_function_shape(self) -> None:
        by_name = {fd["name"]: fd for fd in _registry().tools()}
        assert set(by_name) == set(EXPECTED_NAMES)
        for name, fd in by_name.items():
            assert fd["type"] == "function"
            assert fd["name"] == name
            assert fd["parameters"]["type"] == "object"

    def test_tool_def_parameters_expose_expected_arguments(self) -> None:
        by_name = {fd["name"]: fd for fd in _registry().tools()}
        for name, expected in PROPERTY_KEYS.items():
            assert set(by_name[name]["parameters"]["properties"]) == expected

    def test_result_schemas_registered_for_all_tools(self) -> None:
        reg = _registry()
        assert set(reg.all_result_schemas()) == set(EXPECTED_NAMES)
        for name in EXPECTED_NAMES:
            assert reg.result_schema(name) is not None

    def test_duplicate_registration_rejected(self) -> None:
        reg = HandlerRegistry()
        register_generic_defaults(reg)
        with pytest.raises(ValueError):
            reg.register(CommandExecutionHandler2)
