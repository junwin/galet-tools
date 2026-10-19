"""Registry build via register_generic_defaults."""

from __future__ import annotations

import pytest

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.register_generic_defaults import register_generic_defaults
from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2

EXPECTED_NAMES = [
    "episodic_memory",
    "procedural_memory",
    "execute_command",
    "execute_command2",
    "file_load",
    "file_save",
    "image_generate",
    "generate_svg",
    "patch_apply",
    "text_replace",
    "repo_index",
    "repo_search",
    "video_generate",
]

PROPERTY_KEYS = {
    "file_load": {
        "external_root",
        "path",
        "start_line",
        "line_count",
        "include_line_numbers",
    },
    "file_save": {"external_root", "path", "file_content", "overwrite"},
    "text_replace": {"external_root", "path", "old_text", "new_text", "check_only"},
    "patch_apply": {
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
        "external_root",
        "working_directory",
        "timeout_seconds",
        "success_exit_codes",
    },
    "execute_command": {
        "external_root",
        "command",
        "working_directory",
        "timeout_seconds",
        "success_exit_codes",
        "wrapper",
    },
    "generate_svg": {"svg_code", "description", "width", "height"},
    "video_generate": {"image_id", "prompt", "duration_seconds", "source", "model",
                       "aspect_ratio", "resolution", "preserve_subject", "add_sound"},
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

