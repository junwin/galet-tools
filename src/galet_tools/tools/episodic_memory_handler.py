"""Explicit account-scoped session, event and digest tools for galet-memory."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Protocol, TYPE_CHECKING

from galet_tools.framework.handler_v2 import HandlerV2

if TYPE_CHECKING:
    from galet_memory import SessionStore, EventStore, DigestStore

    class EpisodicStore(SessionStore, EventStore, DigestStore, Protocol):
        pass


class EpisodicMemoryHandler(HandlerV2):
    NAME = "episodic_memory"
    ACTIONS = (
        "create_session", "get_session", "list_sessions", "update_session",
        "clear_session_events", "delete_session", "delete_sessions",
        "append_event", "append_events", "get_event", "get_recent_events",
        "get_events_by_period", "get_exchange", "invalidate_exchange",
        "get_digest", "list_digests", "search_digests",
    )

    def __init__(self, memory: EpisodicStore | None = None):
        self.memory = memory

    @classmethod
    def name(cls):
        return cls.NAME

    @classmethod
    def tool_def(cls):
        strings = {"type": "array", "items": {"type": "string"}}
        nullable = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        event = {
            "type": "object", "properties": {
                "role": {"type": "string"}, "actor": {"type": "string"},
                "kind": {"type": "string"}, "content": {},
                "created_at": {"type": "string", "format": "date-time"},
                "metadata": {"type": "object"}, "correlation_ids": strings,
            }, "required": ["role", "actor", "content"], "additionalProperties": False,
        }
        changes = {
            "type": "object", "properties": {
                "friendly_name": nullable, "context_name": nullable,
                "tags": strings, "metadata": {"type": "object"},
            }, "additionalProperties": False,
        }
        return {
            "type": "function", "name": cls.NAME,
            "description": (
                "Manage account-owned sessions and read complete episodic events and digests. "
                "get_session returns metadata only. Use get_recent_events with event_kinds "
                "['user_message'] for the last N user messages; filters apply before count. "
                "Use get_exchange/invalidate_exchange for a request and linked responses. "
                "Period reads use timezone-aware [start,end). Pass returned pagination fields "
                "to continue. Updates use changes: omit unchanged fields, null clears nullable fields. "
                "clear_session_events permanently removes events; use reset_session to reset context."
            ),
            "parameters": {
                "type": "object", "properties": {
                    "action": {"type": "string", "enum": list(cls.ACTIONS)},
                    "account_name": {"type": "string", "description": "Defaults to the trusted execution account."},
                    "session_id": {"type": "string"}, "session_ids": strings,
                    "count": {"type": "integer", "minimum": 0, "default": 20,
                              "description": "Maximum records; zero returns none. Omit for the operation default."},
                    "cursor": {"type": "string"}, "before_event_id": {"type": "string"},
                    "event_id": {"type": "string"}, "digest_id": {"type": "string"},
                    "correlation_id": {"type": "string"}, "query": {"type": "string"},
                    "event_kinds": strings, "actors": strings,
                    "start": {"type": "string", "format": "date-time"},
                    "end": {"type": "string", "format": "date-time"},
                    "expected_last_event_id": {**nullable, "description": "Omit/null: no guard; empty string: guard an empty stream; otherwise the expected tail ID."},
                    "event": event, "events": {"type": "array", "items": event, "minItems": 1},
                    "friendly_name": nullable, "context_name": nullable,
                    "tags": strings, "metadata": {"type": "object"}, "changes": changes,
                }, "required": ["action"], "additionalProperties": False,
            },
            # Optional action-specific fields and arbitrary JSON payloads require non-strict mode.
            "strict": False,
        }

    @classmethod
    def result_schema(cls):
        return {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "tool": {"type": "string"},
            "action": {"type": "string"}, "error": {"type": "string"},
        }, "required": ["ok", "tool", "action"], "additionalProperties": True}

    def execute(self, args: dict[str, Any], *, account_name: str = "auto", **context: Any):
        action = str(args.get("action") or "").strip().lower()
        memory = context.get("episodic_store") or self.memory
        if memory is None:
            return self._error(action, "episodic_store not available")
        try:
            from galet_memory import EMPTY_TAIL, NewEvent, SessionChanges

            if action not in self.ACTIONS:
                raise ValueError(f"Unknown action: {action!r}; use an explicit session/event/digest action")
            unknown = set(args) - set(self.tool_def()["parameters"]["properties"])
            if unknown:
                raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}")
            resolved = self._text(args.get("account_name") or account_name, "account_name")
            if resolved == "auto":
                raise ValueError("account_name is required")
            if account_name not in ("", "auto", None) and resolved != account_name:
                raise ValueError("account_name does not match the execution account")
            kw = {"account_name": resolved}
            if action not in ("create_session", "list_sessions", "delete_sessions", "search_digests"):
                kw["session_id"] = self._text(args.get("session_id"), "session_id")
            tail = args.get("expected_last_event_id")
            if tail is not None and not isinstance(tail, str):
                raise ValueError("expected_last_event_id must be a string or null")
            guard = EMPTY_TAIL if tail == "" else tail
            if action in ("append_event", "append_events", "clear_session_events", "invalidate_exchange"):
                kw["expected_last_event_id"] = guard
            if action in ("list_sessions", "get_recent_events", "get_events_by_period", "list_digests", "search_digests"):
                default = {"get_recent_events": 10, "get_events_by_period": 100, "search_digests": 3}.get(action, 20)
                count = args.get("count", default)
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError("count must be a nonnegative integer")
                kw["count"] = count
            if action in ("list_sessions", "get_events_by_period", "list_digests"):
                kw["cursor"] = self._optional_text(args.get("cursor"), "cursor")
            if action in ("get_recent_events", "get_events_by_period"):
                for key in ("event_kinds", "actors"):
                    kw[key] = self._strings(args[key], key) if key in args else None
            if action == "get_recent_events":
                kw["before_event_id"] = self._optional_text(args.get("before_event_id"), "before_event_id")
            elif action == "get_events_by_period":
                kw.update(start=self._timestamp(args.get("start")), end=self._timestamp(args.get("end")))
            elif action in ("get_exchange", "invalidate_exchange"):
                kw["correlation_id"] = self._text(args.get("correlation_id"), "correlation_id")
            elif action in ("get_event", "get_digest"):
                key = "event_id" if action == "get_event" else "digest_id"
                kw[key] = self._text(args.get(key), key)
            elif action == "create_session":
                if args.get("session_id"):
                    kw["session_id"] = self._text(args["session_id"], "session_id")
                for key in ("friendly_name", "context_name"):
                    if key in args:
                        kw[key] = self._nullable_text(args[key], key)
                if "tags" in args:
                    kw["tags"] = self._strings(args["tags"], "tags")
                if "metadata" in args:
                    kw["metadata"] = self._object(args["metadata"], "metadata")
            elif action == "update_session":
                changes = dict(self._object(args.get("changes"), "changes"))
                if set(changes) - {"friendly_name", "context_name", "tags", "metadata"}:
                    raise ValueError("Unknown SessionChanges fields")
                for key in ("friendly_name", "context_name"):
                    if key in changes:
                        changes[key] = self._nullable_text(changes[key], key)
                if "tags" in changes:
                    changes["tags"] = tuple(self._strings(changes["tags"], "tags"))
                if "metadata" in changes:
                    self._object(changes["metadata"], "metadata")
                kw["changes"] = SessionChanges(**changes)
            elif action == "delete_sessions":
                ids = self._strings(args.get("session_ids"), "session_ids")
                if not ids or len(ids) > 100:
                    raise ValueError("session_ids requires 1 to 100 session IDs")
                kw["session_ids"] = list(dict.fromkeys(ids))
            elif action in ("append_event", "append_events"):
                def new_event(raw):
                    raw = dict(self._object(raw, "event"))
                    if set(raw) - {"role", "content", "actor", "kind", "created_at", "metadata", "correlation_ids"}:
                        raise ValueError("Unknown NewEvent fields")
                    for key in ("role", "actor"):
                        raw[key] = self._text(raw.get(key), key)
                    if "content" not in raw:
                        raise ValueError("content is required")
                    if "created_at" in raw:
                        raw["created_at"] = self._timestamp(raw["created_at"])
                    if "correlation_ids" in raw:
                        raw["correlation_ids"] = tuple(self._strings(raw["correlation_ids"], "correlation_ids"))
                    if "metadata" in raw:
                        self._object(raw["metadata"], "metadata")
                    if "kind" in raw and not isinstance(raw["kind"], str):
                        raise ValueError("kind must be a string")
                    return NewEvent(**raw)
                if action == "append_event":
                    kw["event"] = new_event(args.get("event"))
                else:
                    raw = args.get("events")
                    if not isinstance(raw, list) or not raw:
                        raise ValueError("events must be a nonempty array")
                    kw["events"] = [new_event(item) for item in raw]
            elif action == "search_digests":
                kw["query"] = self._text(args.get("query"), "query")
                kw["session_id"] = self._optional_text(args.get("session_id"), "session_id")

            result = getattr(memory, action)(**kw)
            output = {"ok": True, "tool": self.NAME, "action": action, "account_name": resolved}
            if action in ("create_session", "get_session", "update_session"):
                if result is None:
                    raise ValueError("Session not found for account")
                output["session"] = self._serialize(result)
            elif action in ("list_sessions", "list_digests"):
                key = "sessions" if action == "list_sessions" else "digests"
                output.update({key: self._serialize(result.items), "count": len(result.items), "next_cursor": result.next_cursor})
                if action == "list_sessions":
                    output["metadata"] = {"requested_count": kw["count"]}
                    path = getattr(memory, "db_path", None)
                    if path is not None:
                        output["metadata"]["database_path"] = str(path)
                    if kw["count"] == 0:
                        output["metadata"]["reason"] = "count_zero"

            elif action in ("get_recent_events", "get_events_by_period"):
                output.update(self._serialize(result))
                output["event_count"] = len(result.events)
            elif action == "invalidate_exchange":
                output.update(self._serialize(result))
                output["event_count"] = result.event_count
            elif action in ("get_event", "append_event", "get_digest", "get_exchange"):
                key = {"get_digest": "digest", "get_exchange": "exchange"}.get(action, "event")
                output[key] = self._serialize(result)
            elif action in ("append_events", "search_digests", "delete_sessions"):
                key = {"append_events": "events", "search_digests": "matches", "delete_sessions": "session_ids"}[action]
                output.update({key: self._serialize(result), "count": len(result)})
            elif action == "clear_session_events":
                output.update(self._serialize(result))
            elif action == "delete_session":
                output.update(session_id=kw["session_id"], deleted=result)
            return output
        except Exception as exc:
            return self._error(action, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _text(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

    @staticmethod
    def _nullable_text(value, name):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be a string or null")
        return value

    @classmethod
    def _optional_text(cls, value, name):
        return None if value is None or (isinstance(value, str) and not value.strip()) else cls._text(value, name)

    @classmethod
    def _strings(cls, value, name):
        if not isinstance(value, list):
            raise ValueError(f"{name} must be an array of strings")
        return [cls._text(item, name) for item in value]

    @staticmethod
    def _object(value, name):
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")
        return value

    @staticmethod
    def _timestamp(value):
        if not isinstance(value, str):
            raise ValueError("timestamp must be a timezone-aware ISO string")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return parsed

    @classmethod
    def _serialize(cls, value):
        if is_dataclass(value):
            return cls._serialize(asdict(value))
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: cls._serialize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._serialize(item) for item in value]
        return value

    @classmethod
    def _error(cls, action, message):
        return {"ok": False, "tool": cls.NAME, "action": action, "error": message}


__all__ = ["EpisodicMemoryHandler"]
