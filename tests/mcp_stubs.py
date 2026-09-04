from __future__ import annotations

from typing import Any, Dict, List

from galet_tools.framework.handler_v2 import HandlerV2


class RecordingHandler(HandlerV2):
    NAME = "mcp_rec_tool"
    SEEN: List[Dict[str, Any]] = []

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": cls.NAME,
                "description": cls.__name__,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto", **context: Any) -> Dict[str, Any]:
        self.SEEN.append({"args": args, "account_name": account_name})
        return {"ok": True, "tool": self.NAME, "echo": args}


class BoomHandler(RecordingHandler):
    NAME = "mcp_boom_tool"

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto", **context: Any) -> Dict[str, Any]:
        raise ValueError("boom")


class StringResultHandler(RecordingHandler):
    NAME = "mcp_str_tool"

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto", **context: Any) -> Any:
        return "not-a-dict"
