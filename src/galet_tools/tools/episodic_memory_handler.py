"""Tool for inspecting and managing episodic sessions through galet-memory."""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from galet_memory import EpisodicEvent, EpisodicMemoryManager
from galet_tools.framework.handler_v2 import HandlerV2


class EpisodicMemoryHandler(HandlerV2):
    """Expose episodic memory operations through a handler interface."""

    NAME = "episodic_memory"

    def __init__(self, memory: Optional[EpisodicMemoryManager] = None):
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
                "Recall and inspect episodic chat memory through the CoALA memory layer. "
                "Supports session reads/writes and invalidate_events by correlation_id, hiding the request and linked responses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "recall", "get_session", "list_sessions", "append_event",
                            "create_session", "update_session", "reset_session", "delete_session", "delete_sessions",
                            "invalidate_events",
                        ],
                    },
                    "session_id": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                    "account_name": {"type": "string", "default": ""},
                    "agent_name": {"type": "string", "default": ""},
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 20},
                    "max_events": {"type": "integer", "default": 6},
                    "include_events": {"type": "boolean", "default": True},
                    "event_scope": {"type": "string", "enum": ["active", "all", "archived"], "default": "active"},
                    "correlation_id": {"type": "string", "default": "",
                                       "description": "Required for invalidate_events: correlation of the request and its linked responses."},
                    "expected_last_event_id": {"anyOf": [{"type": "string"}, {"type": "null"}],
                                               "default": None, "description": "Optional guard using session.last_event_id; null means no guard."},
                    "role": {"type": "string", "default": "user"},
                    "kind": {"type": "string", "default": ""},
                    "content": {"type": "string", "default": ""},
                },
                "required": [
                    "action", "session_id", "account_name", "agent_name", "query",
                    "limit", "max_events", "include_events", "role", "kind", "content",
                    "event_scope", "correlation_id", "expected_last_event_id"
                ],
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
                "action": {"type": "string"},
                "session": {"type": "object"},
                "sessions": {"type": "array", "items": {"type": "object"}},
                "events": {"type": "array", "items": {"type": "object"}},
                "status": {"type": "string"},
                "event_ids": {"type": "array", "items": {"type": "string"}},
                "event_count": {"type": "integer"},
                "invalidated_digest_ids": {"type": "array", "items": {"type": "string"}},
                "error": {"type": "string"},
            },
            "required": ["ok", "tool", "action"],
            "additionalProperties": True,
        }

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto", **context: Any) -> Dict[str, Any]:
        action = str(args.get("action") or "").strip().lower()
        memory = context.get("episodic_store") or self.memory
        if memory is None:
            return self._error(action, "episodic_store not available")
        requested_account = str(args.get("account_name") or "").strip()
        resolved_account = requested_account or str(account_name or "").strip()
        raw_session_id = args.get("session_id")
        session_id = raw_session_id.strip() if isinstance(raw_session_id, str) else ""

        try:
            from galet_memory import EpisodicEvent, EpisodicMemoryRequest, EpisodicSessionQuery

            if not resolved_account or resolved_account == "auto":
                return self._error(action, "account_name is required")
            if account_name not in ("", "auto", None) and resolved_account != account_name:
                return self._error(action, "account_name does not match the execution account")
            # The tool does not expose another account's session or mutate it.
            if session_id and action not in ("create_session", "list_sessions"):
                owned = memory.get_session(session_id, include_events=False)
                if owned is None or owned.account_name != resolved_account:
                    return self._error(action, "Session not found for account")

            if action == "invalidate_events":
                if not session_id:
                    return self._error(action, "session_id is required")
                correlation_id = str(args.get("correlation_id") or "").strip()
                if not correlation_id:
                    return self._error(action, "correlation_id is required")
                expected_tail = args.get("expected_last_event_id")
                if expected_tail is not None and not isinstance(expected_tail, str):
                    return self._error(action, "expected_last_event_id must be a string or null")
                result = memory.invalidate_events(
                    account_name=resolved_account, session_id=session_id,
                    correlation_id=correlation_id,
                    expected_last_event_id=expected_tail or None,
                )
                return {
                    "ok": True, "tool": self.NAME, "action": action,
                    "session_id": result.session_id, "correlation_id": result.correlation_id,
                    "status": result.status, "event_ids": list(result.event_ids),
                    "event_count": result.event_count,
                    "invalidated_digest_ids": list(result.invalidated_digest_ids),
                    "marker_event_id": result.marker_event_id,
                    "unprovenanced_digests_invalidated": result.unprovenanced_digests_invalidated,
                }

            if action == "recall":
                if not session_id:
                    return self._error(action, "session_id is required")
                result = memory.recall(
                    EpisodicMemoryRequest(
                        account_name=resolved_account,
                        agent_name=str(args.get("agent_name") or "").strip(),
                        conversation_id=session_id,
                        query=str(args.get("query") or "").strip(),
                        max_events=max(0, int(args.get("max_events", 6))),
                        include_archived_digests=False,
                    )
                )
                return {
                    "ok": True,
                    "tool": self.NAME,
                    "action": action,
                    "session_id": result.session_id or session_id,
                    "session": {
                        "account_name": result.session_account_name,
                        "agent_name": result.session_agent_name,
                        "context_name": result.session_context_name,
                        "friendly_name": result.session_friendly_name,
                        "session_type": result.session_type,
                        "participants": list(result.session_participants),
                        "tags": list(result.session_tags),
                        "updated_at": result.session_updated_at.isoformat() if result.session_updated_at else None,
                    },
                    "events": [self._event_dict(event) for event in result.events],
                    "event_count": len(result.events),
                    "dropped_event_count": result.dropped_event_count,
                    "metadata": dict(result.metadata),
                }

            if action == "get_session":
                if not session_id:
                    return self._error(action, "session_id is required")
                event_scope = str(args.get("event_scope") or "active")
                if event_scope not in ("active", "all", "archived"):
                    return self._error(action, "event_scope must be active, all or archived")
                session = memory.get_session(
                    session_id,
                    include_events=bool(args.get("include_events", True)),
                    event_scope=event_scope,
                )
                if session is None:
                    return self._error(action, f"Session not found: {session_id}")
                return {"ok": True, "tool": self.NAME, "action": action, "session": self._session_dict(session)}

            if action == "list_sessions":
                if not resolved_account or resolved_account == "auto":
                    return self._error(action, "account_name is required")
                sessions = memory.list_sessions(
                    EpisodicSessionQuery(
                        account_name=resolved_account,
                        agent_name=str(args.get("agent_name") or "").strip(),
                        query=str(args.get("query") or "").strip(),
                        limit=max(1, int(args.get("limit", 20))),
                    )
                )
                return {
                    "ok": True,
                    "tool": self.NAME,
                    "action": action,
                    "sessions": [self._session_dict(session) for session in sessions],
                    "count": len(sessions),
                }

            if action == "append_event":
                if not session_id:
                    return self._error(action, "session_id is required")
                content = str(args.get("content") or "")
                if not content:
                    return self._error(action, "content is required")
                role = str(args.get("role") or "user").strip()
                stored = memory.append_event(
                    session_id,
                    EpisodicEvent(
                        role=role,
                        actor=role,
                        kind=str(args.get("kind") or "").strip(),
                        content=content,
                    ),
                )
                return {"ok": True, "tool": self.NAME, "action": action, "event": self._event_dict(stored)}

            if action == "create_session":
                agent_name = str(args.get("agent_name") or "").strip()
                if not agent_name:
                    return self._error(action, "agent_name is required")
                kwargs: Dict[str, Any] = {}
                if str(args.get("session_id") or "").strip():
                    kwargs["session_id"] = str(args.get("session_id") or "").strip()
                if str(args.get("user_id") or "").strip():
                    kwargs["user_id"] = str(args.get("user_id") or "").strip()
                if str(args.get("friendly_name") or "").strip():
                    kwargs["friendly_name"] = str(args.get("friendly_name") or "").strip()
                if str(args.get("context_name") or "").strip():
                    kwargs["context_name"] = str(args.get("context_name") or "").strip()
                if str(args.get("session_type") or "").strip():
                    kwargs["session_type"] = str(args.get("session_type") or "").strip()
                if args.get("tags"):
                    kwargs["tags"] = list(args.get("tags"))
                if args.get("participants"):
                    kwargs["participants"] = list(args.get("participants"))
                if args.get("links"):
                    raw_links = dict(args.get("links") or {})
                    allowed = {"user_session_id", "internal_session_id"}
                    filtered = {k: v for k, v in raw_links.items() if k in allowed}
                    if filtered:
                        kwargs["links"] = filtered
                if args.get("metadata"):
                    kwargs["metadata"] = dict(args.get("metadata") or {})

                created = memory.create_session(
                    account_name=resolved_account,
                    agent_name=agent_name,
                    **kwargs,
                )
                return {"ok": True, "tool": self.NAME, "action": action, "session": self._session_dict(created)}

            if action == "update_session":
                if not session_id:
                    return self._error(action, "session_id is required")
                patch: Dict[str, Any] = {}
                for key in ("friendly_name", "context_name", "session_type"):
                    v = args.get(key)
                    if v is not None and (not isinstance(v, str) or str(v).strip() != ""):
                        patch[key] = v
                for key in ("tags", "participants", "metadata"):
                    if args.get(key) is not None:
                        patch[key] = args.get(key)
                if args.get("links") is not None:
                    raw_links = dict(args.get("links") or {})
                    allowed = {"user_session_id", "internal_session_id"}
                    filtered = {k: v for k, v in raw_links.items() if k in allowed}
                    if filtered:
                        patch["links"] = filtered

                updated = memory.update_session(session_id, patch)
                return {"ok": True, "tool": self.NAME, "action": action, "session": self._session_dict(updated)}

            if action == "reset_session":
                if not session_id:
                    return self._error(action, "session_id is required")
                memory.reset_session(session_id)
                return {"ok": True, "tool": self.NAME, "action": action, "session_id": session_id}

            if action == "delete_sessions":
                ids = raw_session_id
                if not isinstance(ids, list) or not ids or any(
                    not isinstance(sid, str) or not sid.strip() for sid in ids
                ):
                    return self._error(action, "session_id must be a nonempty array of session IDs for delete_sessions")
                if len(ids) > 100:
                    return self._error(action, "at most 100 session IDs per request")
                selected = list(dict.fromkeys(sid.strip() for sid in ids))
                for sid in selected:
                    owned = memory.get_session(sid, include_events=False)
                    if owned is not None and owned.account_name != resolved_account:
                        return self._error(action, "Session not found for account")
                deleted = memory.delete_sessions(selected)
                return {
                    "ok": True, "tool": self.NAME, "action": action,
                    "session_ids": deleted, "count": len(deleted),
                }

            if action == "delete_session":
                if not session_id:
                    return self._error(action, "session_id is required")
                memory.delete_session(session_id)
                return {"ok": True, "tool": self.NAME, "action": action, "session_id": session_id}

            return self._error(action, f"Unknown action: {action!r}")
        except Exception as exc:
            return self._error(action, f"{type(exc).__name__}: {exc}")

    @classmethod
    def _session_dict(cls, session: Any) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "account_name": session.account_name,
            "agent_name": session.agent_name,
            "friendly_name": session.friendly_name,
            "context_name": session.context_name,
            "session_type": session.session_type,
            "participants": list(session.participants),
            "links": dict(session.links),
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "tags": list(session.tags),
            "metadata": dict(session.metadata),
            "last_event_id": session.last_event_id,
            "events": [cls._event_dict(event) for event in session.events],
        }

    @staticmethod
    def _event_dict(event: EpisodicEvent) -> Dict[str, Any]:
        return {
            "event_id": event.event_id,
            "role": event.role,
            "actor": event.actor,
            "kind": event.kind,
            "content": event.content,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "metadata": dict(event.metadata),
        }

    @classmethod
    def _error(cls, action: str, message: str) -> Dict[str, Any]:
        return {"ok": False, "tool": cls.NAME, "action": action, "error": message}


__all__ = ["EpisodicMemoryHandler"]
