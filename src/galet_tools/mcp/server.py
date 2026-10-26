from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.host.adapters import (
    ConfigSandboxRootResolver,
    ConfigStorageLocationResolver,
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
from galet_tools.tools.image_generate_handler import ImageGenerateHandler
from galet_tools.tools.video_generate_handler import VideoGenerateHandler
from galet_tools.tools.generate_svg_handler import GenerateSvgHandler
from galet_tools.tools.patch_apply_handler import PatchApplyHandler2
from galet_tools.tools.text_replace_handler import TextReplaceHandler

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

    def close(self) -> None:
        semantic = self.handlers.get("semantic_memory")
        if semantic is not None:
            semantic.close()
        handler = self.handlers.get("episodic_memory")
        if handler is not None:
            handler.memory.close()


def build_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_generic_defaults(registry)
    return registry


def _build_handlers(config: GaletConfig) -> Dict[str, Any]:
    storage = ConfigStorageLocationResolver(config)
    sandbox = ConfigSandboxRootResolver(config)
    security = DefaultSecurityPolicy()
    handlers = {
        "file_load": FileLoadHandler2(storage),
        "file_save": FileSaveHandler2(storage),
        "patch_apply": PatchApplyHandler2(storage),
        "text_replace": TextReplaceHandler(storage),
        "execute_command": CommandExecutionHandler2(storage, sandbox, security),
        "execute_command2": ExecuteCommand2(storage, sandbox, security),
        "generate_svg": GenerateSvgHandler(),
        "image_generate": ImageGenerateHandler(storage),
        "video_generate": VideoGenerateHandler(storage),
    }
    memory_tools = set(config.allowlist) & {"procedural_memory", "episodic_memory"}
    if memory_tools:
        try:
            from galet_memory import FileProceduralMemory, ProceduralLayout, SqliteEpisodicMemory
        except ImportError as exc:
            raise GaletMcpError("memory tools require galet-tools[memory] with the explicit episodic interfaces") from exc
        base = Path(storage.storage_base_dir())
        if "procedural_memory" in memory_tools:
            from galet_tools.tools.procedural_memory_handler import ProceduralMemoryHandler
            options = config.procedural_memory
            layout = {
                "global_contexts": "contexts", "account_contexts": "contexts/{account}",
                "project_contexts": None,
                "global_skills": "skills", "account_skills": "skills/{account}",
                "project_skills": None,
                **options.get("layout", {}),
            }
            handlers["procedural_memory"] = ProceduralMemoryHandler(FileProceduralMemory(
                options.get("root") or base, ProceduralLayout(**layout),
                context_resolution=options.get("context_resolution", "most_specific"),
            ))
        if "episodic_memory" in memory_tools:
            from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler
            if not callable(getattr(SqliteEpisodicMemory, "invalidate_exchange", None)):
                raise GaletMcpError("episodic_memory requires galet-memory PR #33 explicit interfaces; install the pinned memory extra")
            path = Path(config.episodic_memory_db_path or base / "chat2.sqlite")
            path.parent.mkdir(parents=True, exist_ok=True)
            handlers["episodic_memory"] = EpisodicMemoryHandler(SqliteEpisodicMemory(
                path, digests_root=base / "digests",
            ))
    if "semantic_memory" in config.allowlist:
        from galet_tools.mcp.semantic import build_semantic_handler
        try:
            handlers["semantic_memory"] = build_semantic_handler(config.memory_config_path)
        except Exception as exc:
            if "episodic_memory" in handlers:
                handlers["episodic_memory"].memory.close()
            raise GaletMcpError(f"cannot configure semantic memory: {exc}") from exc
    return handlers


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
    if name in ("procedural_memory", "episodic_memory", "semantic_memory"):
        requested_account = (arguments or {}).get("account_name")
        if requested_account and str(requested_account).strip() != scope.config.account:
            return error_result("account_name does not match the fixed MCP account")
    call_id = uuid.uuid4().hex
    started = time.monotonic()
    logger.info("mcp_call_start call_id=%s tool=%s account=%s",
                call_id, name, scope.config.account)
    try:
        result = handler.execute(
            arguments or {}, account_name=scope.config.account
        )
    except Exception as exc:
        logger.exception("mcp_call_failed call_id=%s tool=%s duration_ms=%.1f",
                         call_id, name, (time.monotonic() - started) * 1000)
        return error_result(f"{type(exc).__name__}: {exc}")
    if not isinstance(result, dict):
        return error_result(
            f"Tool '{name}' produced a {type(result).__name__} result; "
            "expected a structured dict."
        )
    metadata = result.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    backend, reason = metadata.get("backend"), metadata.get("reason")
    log = logger.warning if result.get("ok") is False or backend == "keyword" else logger.info
    log("mcp_call_done call_id=%s tool=%s account=%s duration_ms=%.1f "
        "ok=%s backend=%s reason=%s count=%s",
        call_id, name, scope.config.account, (time.monotonic() - started) * 1000,
        result.get("ok"), backend, reason, result.get("count"))
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
        scope.close()
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
    try:
        uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    finally:
        scope.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="galet-mcp",
        description="galet-tools MCP streamable-HTTP server (loopback only).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="path to the galet-mcp.json config file (default: ./galet-mcp.json)",
    )
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"),
                        default="INFO", help="application log level (default: INFO)")
    parser.add_argument("--log-file", help="append application logs to this file as well as stderr")
    args = parser.parse_args(argv)
    try:
        handlers = [logging.StreamHandler()]
        if args.log_file:
            handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    except OSError as exc:
        print(f"galet-mcp: cannot open log file: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=getattr(logging, args.log_level), handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("mcp_process_start config=%s", args.config or "galet-mcp.json")
    try:
        serve(config_path=args.config)
    except (GaletConfigError, GaletMcpError) as exc:
        logger.error("mcp_start_failed: %s", exc)
        print(f"galet-mcp: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
