"""Reset the current episodic session and signal the host to clear its view."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Protocol

from galet_tools.framework.handler_v2 import HandlerV2

logger = logging.getLogger(__name__)


class ResettableEpisodicStore(Protocol):
    def reset_context(self, *, account_name: str, session_id: str) -> Any: ...


class ResetSessionHandler(HandlerV2):
    """Reset active context using the host's current conversation ID.

    The action result is retained for Lucy's streaming client notification.
    """

    NAME = "reset_session"

    def __init__(self, memory: ResettableEpisodicStore | None = None) -> None:
        self.memory = memory

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Reset the current chat session. Use this when the user asks to "
                "start fresh, clear history, or begin a new session."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        }

    @classmethod
    def result_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "ok": {"type": "boolean"},
                "error": {"type": "string"},
            },
            "required": ["action", "ok"],
            "additionalProperties": False,
        }

    def execute(
        self, args: Dict[str, Any], *, account_name: str = "auto", **context: Any
    ) -> Dict[str, Any]:
        conversation_id = context.get("conversation_id")
        store = context.get("curation_service") or self.memory
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            return {"action": self.NAME, "ok": False, "error": "No session ID available"}
        if store is None:
            return {"action": self.NAME, "ok": False, "error": "curation_service not available"}
        try:
            if account_name in ("", "auto", None):
                raise ValueError("account_name is required")
            store.reset_context(account_name=account_name, session_id=conversation_id)
        except Exception as exc:
            logger.exception("reset_session: failed for session=%s", conversation_id)
            return {"action": self.NAME, "ok": False, "error": str(exc)}
        logger.info("reset_session: reset context for session=%s account=%s", conversation_id, account_name)
        return {"action": self.NAME, "ok": True}

    def execute_raw(
        self, arguments_raw: str, *, account_name: str = "auto",
        call_id: str = "", **context: Any,
    ) -> str:
        return json.dumps(self.execute({}, account_name=account_name, **context), ensure_ascii=False)
