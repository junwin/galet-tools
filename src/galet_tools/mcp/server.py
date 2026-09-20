from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.host.adapters import (
    ConfigSandboxRootResolver,
    ConfigStorageLocationResolver,
    GaletConfigProvider,
)
from galet_tools.host.config import GaletConfig, GaletConfigError, load_config
from galet_tools.host.security import DefaultSecurityPolicy
from galet_tools.mcp.tool_adapter import (
    error_result,
    handler_tool_def_to_mcp,
    success_result,
)
from galet_tools.register_generic_defaults import register_generic_defaults
from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2
from galet_tools.tools.execute_command2 import ExecuteCommand2
from galet_tools.tools.file_load_handler2 import FileLoadHandler2
from galet_tools.tools.file_save_handler import FileSaveHandler2
from galet_tools.tools.generate_image_handler import GenerateImageHandler
from galet_tools.tools.generate_svg_handler import GenerateSvgHandler
from galet_tools.tools.patch_apply_handler import PatchApplyHandler2

logger = logging.getLogger(__name__)

SERVER_NAME = "galet-tools"
SERVER_VERSION = "0.1.0"


class GaletMcpError(Exception):
    pass


@dataclass(frozen=True)
class McpScope:
    config: GaletConfig
    handlers: Dict[str, Any]
    tool_names: frozenset


def build_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_generic_defaults(registry)
    return registry


def _build_handlers(config: GaletConfig) -> Dict[str, Any]:
    storage = ConfigStorageLocationResolver(config)
    sandbox = ConfigSandboxRootResolver(config)
    security = DefaultSecurityPolicy()
    fonts = GaletConfigProvider(config)
    return {
        "file_load": FileLoadHandler2(storage),
        "file_save": FileSaveHandler2(storage),
        "patch_apply": PatchApplyHandler2(storage),
        "execute_command": CommandExecutionHandler2(storage, sandbox, security),
        "execute_command2": ExecuteCommand2(storage, sandbox, security),
        "generate_svg": GenerateSvgHandler(),
        "generate_image": GenerateImageHandler(fonts),
    }


def exposed_tools(
    registry: HandlerRegistry, allowlist: List[str]
) -> List[Dict[str, Any]]:
    allowed = set(allowlist)
    tool_defs = [
        tool_def
        for tool_def in registry.tools()
        if tool_def.get("name") in allowed
    ]
    return [handler_tool_def_to_mcp(tool_def) for tool_def in tool_defs]


def resolve_startup_scope(config: GaletConfig) -> Tuple[McpScope, List[Dict[str, Any]]]:
    registry = build_registry()
    mcp_tools = exposed_tools(registry, config.allowlist)
    if not mcp_tools:
        raise GaletMcpError(
            f"refusing to start: allowlist {config.allowlist!r} exposes no tools "
            f"from the registered handlers {registry.tool_names()!r} "
            "(nothing exposed => nothing to serve)"
        )
    scope = McpScope(
        config=config,
        handlers=_build_handlers(config),
        tool_names=frozenset(tool["name"] for tool in mcp_tools),
    )
    return scope, mcp_tools


def dispatch_call(
    scope: McpScope, name: str, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    if name not in scope.tool_names:
        valid = ", ".join(sorted(scope.tool_names))
        logger.error("mcp_call_rejected tool=%r valid_tools=%s", name, valid)
        return error_result(f"Unknown tool '{name}'. Valid tools: {valid}")
    handler = scope.handlers.get(name)
    if handler is None:
        return error_result(
            f"Tool '{name}' is advertised but not available in this server process."
        )
    try:
        result = handler.execute(
            arguments or {}, account_name=scope.config.account
        )
    except Exception as exc:
        logger.exception("mcp_call_failed tool=%s", name)
        return error_result(f"{type(exc).__name__}: {exc}")
    if not isinstance(result, dict):
        return error_result(
            f"Tool '{name}' produced a {type(result).__name__} result; "
            "expected a structured dict."
        )
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        text = str(result)
    return success_result(text)


def serve(config_path: Optional[str] = None) -> None:
    config = load_config(config_path)
    scope, mcp_tools = resolve_startup_scope(config)

    try:
        from mcp.server.lowlevel import Server

        import mcp.types as mcp_types

        import uvicorn
    except ImportError as exc:
        raise GaletMcpError(
            "the official MCP Python SDK (mcp 2.x with its HTTP extras) and "
            "uvicorn are not installed. Install the pinned mcp dependency "
            "before starting the galet-mcp server."
        ) from exc

    logger.info(
        "galet_mcp_start account=%s host=%s port=%d tools=%d",
        config.account,
        config.host,
        config.port,
        len(scope.tool_names),
    )
    for tool in sorted(mcp_tools, key=lambda t: t["name"]):
        logger.info("galet_mcp_tool name=%s", tool["name"])

    async def _handle_list_tools(ctx: Any, params: Any) -> Any:
        return mcp_types.ListToolsResult(
            tools=[
                mcp_types.Tool(
                    name=tool["name"],
                    description=tool["description"],
                    inputSchema=tool["inputSchema"],
                )
                for tool in mcp_tools
            ]
        )

    async def _handle_call_tool(ctx: Any, params: Any) -> Any:
        result = await asyncio.to_thread(
            dispatch_call,
            scope,
            params.name,
            dict(params.arguments or {}),
        )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(text=result["content"][0]["text"])],
            isError=result["isError"],
        )

    sdk_server = Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        instructions=(
            "galet-tools MCP facade: exposes the configured allowlist of "
            "generic HandlerRegistry tools. Scope is fixed at startup "
            "(account and exposed set); loopback binding only."
        ),
        on_list_tools=_handle_list_tools,
        on_call_tool=_handle_call_tool,
    )
    app = sdk_server.streamable_http_app()

    logger.info(
        "galet_mcp_serving url=http://%s:%d/mcp account=%s",
        config.host,
        config.port,
        config.account,
    )
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="galet-mcp",
        description="galet-tools MCP streamable-HTTP server (loopback only).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="path to the galet-mcp.json config file (default: ./galet-mcp.json)",
    )
    args = parser.parse_args(argv)
    try:
        serve(config_path=args.config)
    except (GaletConfigError, GaletMcpError) as exc:
        print(f"galet-mcp: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
