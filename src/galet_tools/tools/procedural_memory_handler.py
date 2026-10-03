"""Inspect and edit scoped contexts/skills through galet-memory."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from galet_tools.framework.handler_v2 import HandlerV2


class ProceduralMemoryHandler(HandlerV2):
    NAME = "procedural_memory"

    def __init__(self, memory: Any = None):
        self.memory = memory

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> dict[str, Any]:
        return {
            "type": "function", "name": cls.NAME,
            "description": (
                "Recall procedural context and skills; list/read/save/update named contexts and save skills. "
                "Recall resolves configured global/account/project scopes; writes use an explicit scope. "
                "Use context_name='none' plus skill_names to inspect named skills. "
                "save_context/save_skill replace the target file; update_context preserves unspecified fields."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": [
                        "recall", "list_contexts", "read_context", "save_context", "update_context", "save_skill",
                    ]},
                    "account_name": {"type": "string", "default": ""},
                    "context_name": {"type": "string", "default": ""},
                    "skill_name": {"type": "string", "default": ""},
                    "skill_names": {"type": "array", "items": {"type": "string"}},
                    "project_name": {"type": "string", "default": ""},
                    "scope": {"type": "string", "enum": ["effective", "global", "account", "project"],
                              "default": "effective"},
                    "text": {"anyOf": [{"type": "string"}, {"type": "null"}],
                             "description": "Body text. null/omitted preserves the body for update_context."},
                    "frontmatter": {"type": "object", "description": (
                        "Markdown frontmatter, e.g. imports, mandatory_tools, search_namespaces or tag. "
                        "update_context merges supplied fields; saves replace them."
                    )},
                    "inherit_existing": {"type": "boolean", "default": False},
                    "create_if_missing": {"type": "boolean", "default": False},
                },
                "required": ["action"], "additionalProperties": False,
            },
            "strict": False,
        }

    @classmethod
    def result_schema(cls) -> dict[str, Any]:
        return {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "tool": {"type": "string"},
            "action": {"type": "string"}, "memory": {"type": "object"},
            "context_names": {"type": "array", "items": {"type": "string"}},
            "text": {"type": "string"}, "frontmatter": {"type": "object"},
            "path": {"type": "string"}, "error": {"type": "string"},
        }, "required": ["ok", "tool", "action"], "additionalProperties": True}

    def execute(self, args: dict[str, Any], *, account_name: str = "auto", **context: Any) -> dict[str, Any]:
        action = str(args.get("action") or "").strip().lower()
        memory = context.get("procedural_memory") or self.memory
        if memory is None:
            return self._error(action, "procedural_memory not available")
        requested = str(args.get("account_name") or "").strip()
        account = requested or str(account_name or "").strip()
        if not account or account == "auto":
            return self._error(action, "account_name is required")
        if account_name not in ("", "auto", None) and account != account_name:
            return self._error(action, "account_name does not match the execution account")
        name = str(args.get("context_name") or "").strip()
        project = str(args.get("project_name") or "").strip()
        scope = str(args.get("scope") or "effective").strip()
        try:
            if scope not in ("effective", "global", "account", "project"):
                return self._error(action, "invalid procedural scope")
            if scope == "project" and not project:
                return self._error(action, "project_name is required for project scope")
            if action == "recall":
                if scope != "effective":
                    return self._error(action, "recall uses effective scope; read_context inspects a specific scope")
                from galet_memory import ProceduralMemoryRequest
                skills = args.get("skill_names") or []
                if not isinstance(skills, list) or any(not isinstance(item, str) or not item.strip() for item in skills):
                    return self._error(action, "skill_names must be an array of nonempty strings")
                if not name and not skills:
                    return self._error(action, "context_name or skill_names is required")
                result = memory.recall(ProceduralMemoryRequest(
                    account_name=account, context_name=name, project_name=project,
                    skill_names=tuple(skills), create_if_missing=bool(args.get("create_if_missing", False)),
                ))
                return self._ok(action, memory=asdict(result))

            repo = getattr(memory, "repository", None)
            if repo is None:
                return self._error(action, "configured procedural memory does not support context/skill management")
            if action == "list_contexts":
                names = (repo.list_resolved_context_names(account, project_name=project)
                         if scope == "effective" else
                         repo.list_context_names(account, project_name=project, scope=scope))
                return self._ok(action, context_names=names, count=len(names), scope=scope)
            if action == "read_context":
                if not name:
                    return self._error(action, "context_name is required")
                found = (repo.read_effective_context(account, name, project_name=project)
                         if scope == "effective" else
                         repo.read_context(account, name, project_name=project, scope=scope))
                if found is None:
                    return self._error(action, "context not found")
                fields, body = found
                return self._ok(action, context_name=name, scope=scope, frontmatter=fields, text=body)
            if action in ("save_context", "update_context", "save_skill"):
                if scope == "effective":
                    return self._error(action, "writes require scope: global, account or project")
                fields = args.get("frontmatter")
                if fields is not None and not isinstance(fields, dict):
                    return self._error(action, "frontmatter must be an object")
                text = args.get("text")
                if text is not None and not isinstance(text, str):
                    return self._error(action, "text must be a string or null")
                if action != "update_context" and text is None:
                    return self._error(action, "text is required for save actions (empty string is allowed)")
                kwargs = dict(account_name=account, project_name=project, scope=scope,
                              text=text, frontmatter=fields)
                if action == "save_skill":
                    skill = str(args.get("skill_name") or "").strip()
                    if not skill:
                        return self._error(action, "skill_name is required")
                    path = repo.save_skill(skill_name=skill, **kwargs)
                else:
                    if not name:
                        return self._error(action, "context_name is required")
                    if action == "update_context":
                        path = repo.update_context(context_name=name,
                            inherit_existing=bool(args.get("inherit_existing", False)), **kwargs)
                    else:
                        path = repo.save_context(context_name=name, **kwargs)
                return self._ok(action, path=str(path), scope=scope)
            return self._error(action, f"Unknown action: {action!r}")
        except Exception as exc:
            return self._error(action, f"{type(exc).__name__}: {exc}")

    @classmethod
    def _ok(cls, action: str, **data: Any) -> dict[str, Any]:
        return {"ok": True, "tool": cls.NAME, "action": action, **data}

    @classmethod
    def _error(cls, action: str, message: str) -> dict[str, Any]:
        return {"ok": False, "tool": cls.NAME, "action": action, "error": message}


__all__ = ["ProceduralMemoryHandler"]
