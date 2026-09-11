import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

DEFAULT_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_TIMEOUT = 30.0

_EXIT_OK = 0
_EXIT_TOOL_ERROR = 1
_EXIT_USAGE = 2
_EXIT_CONNECT = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="galet-tools-smoke",
        description="Smoke-test a galet-tools MCP server over streamable HTTP.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="MCP endpoint URL (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="read timeout in seconds (default: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    list_parser = subparsers.add_parser("list", help="list the tools the server exposes")
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="print the tools as a JSON array instead of plain text",
    )
    call_parser = subparsers.add_parser("call", help="call one tool and print its text output")
    call_parser.add_argument("tool", help="name of the tool to call")
    call_parser.add_argument(
        "args_json",
        nargs="?",
        default="{}",
        metavar="ARGS_JSON",
        help="JSON object of tool arguments (default: {})",
    )
    return parser


def _friendly(exc: BaseException) -> str:
    while isinstance(exc, BaseExceptionGroup):
        if not exc.exceptions:
            break
        exc = exc.exceptions[0]
    message = str(exc)
    return message if message else type(exc).__name__


def _parse_arguments(raw: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"arguments are not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise ValueError("arguments must be a JSON object")
    return value


async def _fetch_tools(url: str, timeout: float) -> List[Any]:
    async with streamable_http_client(url) as (read_stream, write_stream):
        async with ClientSession(
            read_stream, write_stream, read_timeout_seconds=timeout
        ) as session:
            await session.initialize()
            result = await session.list_tools()
            return list(result.tools)


async def _call_tool(
    url: str, timeout: float, name: str, arguments: Dict[str, Any]
) -> Any:
    async with streamable_http_client(url) as (read_stream, write_stream):
        async with ClientSession(
            read_stream, write_stream, read_timeout_seconds=timeout
        ) as session:
            await session.initialize()
            return await session.call_tool(
                name, arguments, read_timeout_seconds=timeout
            )


def _run_list(url: str, timeout: float, as_json: bool) -> int:
    try:
        tools = asyncio.run(_fetch_tools(url, timeout))
    except Exception as exc:
        print(
            f"galet-tools-smoke: could not list tools from {url}: {_friendly(exc)}",
            file=sys.stderr,
        )
        return _EXIT_CONNECT
    tools.sort(key=lambda tool: tool.name)
    if as_json:
        payload = [tool.model_dump(mode="json") for tool in tools]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{len(tools)} tools")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")
    return _EXIT_OK


def _run_call(url: str, timeout: float, name: str, arguments: Dict[str, Any]) -> int:
    try:
        result = asyncio.run(_call_tool(url, timeout, name, arguments))
    except Exception as exc:
        print(
            f"galet-tools-smoke: could not call tool '{name}' at {url}: {_friendly(exc)}",
            file=sys.stderr,
        )
        return _EXIT_CONNECT
    text_parts = [part.text for part in result.content if part.type == "text"]
    print("".join(text_parts).strip())
    return _EXIT_TOOL_ERROR if result.isError else _EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "list":
        return _run_list(args.url, args.timeout, args.json)
    try:
        arguments = _parse_arguments(args.args_json)
    except ValueError as exc:
        print(f"galet-tools-smoke: {exc}", file=sys.stderr)
        return _EXIT_USAGE
    return _run_call(args.url, args.timeout, args.tool, arguments)


if __name__ == "__main__":
    raise SystemExit(main())
