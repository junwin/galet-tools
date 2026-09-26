"""Tool adapter for galet-memory's non-destructive curation service."""

from __future__ import annotations

from typing import Any, Dict, Protocol

from galet_tools.framework.handler_v2 import HandlerV2


class CurationPort(Protocol):
    def produce_digest(self, *, account_name: str, session_id: str, max_chars: int = 32000) -> Any: ...
    def archive(
        self, *, account_name: str, session_id: str, max_chars: int = 32000,
        idempotency_key: str | None = None,
    ) -> Any: ...


class CurateChatHandler(HandlerV2):
    """Preview a digest or append an archive boundary to an episodic session.

    The host supplies a galet_memory.curation.CurationService. The account comes
    from the trusted execution context, never from model-provided arguments.
    """

    NAME = "curate_chat"

    def __init__(self, curation: CurationPort) -> None:
        self.curation = curation

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Generate a digest of an episodic session, or archive it by "
                "appending a non-destructive digest boundary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session UUID."},
                    "mode": {
                        "type": "string", "enum": ["digest", "archive"],
                        "description": "Digest leaves the session unchanged; archive appends a boundary.",
                    },
                    "max_chars": {
                        "type": "integer", "description": "Maximum input characters for the digest.",
                    },
                    "idempotency_key": {
                        "type": "string",
                        "description": "Stable operation key for retrying archive; empty for a new operation.",
                    },
                },
                "required": ["session_id", "mode", "max_chars", "idempotency_key"],
                "additionalProperties": False,
            },
            "strict": True,
        }

    @classmethod
    def result_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "tool": {"type": "string"},
                "status": {"type": "string"},
                "session_id": {"type": "string"},
                "digest": {"type": "string"},
                "boundary_event_id": {"type": ["string", "null"]},
                "error": {"type": "string"},
            },
            "required": ["ok", "tool"],
            "additionalProperties": True,
        }

    def execute(
        self, args: Dict[str, Any], *, account_name: str = "auto", **context: Any
    ) -> Dict[str, Any]:
        def error(message: str) -> Dict[str, Any]:
            return {"ok": False, "tool": self.NAME, "status": "error", "error": message}

        session_id = args.get("session_id")
        mode = args.get("mode")
        max_chars = args.get("max_chars", 32000)
        key = args.get("idempotency_key") or None
        if not isinstance(session_id, str) or not session_id.strip():
            return error("session_id is required")
        if mode not in ("digest", "archive"):
            return error("mode must be digest or archive")
        if type(max_chars) is not int or max_chars <= 0:
            return error("max_chars must be a positive integer")
        if not isinstance(account_name, str) or not account_name.strip() or account_name == "auto":
            return error("account_name is required from the execution context")
        if key is not None and (not isinstance(key, str) or not key.strip()):
            return error("idempotency_key must be a non-empty string")
        if mode == "digest" and key is not None:
            return error("idempotency_key applies only to archive")

        try:
            if mode == "digest":
                result = self.curation.produce_digest(
                    account_name=account_name, session_id=session_id.strip(),
                    max_chars=max_chars,
                )
            else:
                result = self.curation.archive(
                    account_name=account_name, session_id=session_id.strip(),
                    max_chars=max_chars, idempotency_key=key,
                )
        except Exception as exc:
            # The curation package defines its own typed errors; keep this
            # adapter import-free so other hosts can implement the port.
            return error(f"{type(exc).__name__}: {exc}")
        boundary = getattr(result, "boundary_event", None)
        return {
            "ok": True,
            "tool": self.NAME,
            "status": "archived" if mode == "archive" else "preview",
            "session_id": result.session_id,
            "digest": result.digest,
            "boundary_event_id": getattr(boundary, "event_id", None),
        }
