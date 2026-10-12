from __future__ import annotations

from typing import Any, Dict

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver
from galet_tools.tools.repository_handler_support import resolve_repository_root
from galet_tools.tools.repository_index import RepositoryIndex


class RepoSearchHandler(HandlerV2):
    """Rank Python and other supported source files using structure and text."""

    NAME = "repo_search"

    def __init__(self, storage_resolver: StorageLocationResolver) -> None:
        self._storage_resolver = storage_resolver

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Find likely implementation files in a source repository using paths and file "
                "content; Python files also use classes, methods, functions, docstrings, and "
                "imports. Tests are excluded by default. Use repo_index after discovery to get "
                "Python AST ranges or matching text lines before file_load."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "external_root": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Exact configured root name. Names are arbitrary and case-sensitive; "
                            "no namespace or account is added automatically."
                        ),
                    },
                    "root": {"type": "string", "description": "Repository path relative to the selected root; usually '.'."},
                    "query": {"type": "string", "description": "Concept or behavior to locate."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "include_tests": {"type": "boolean"},
                },
                "required": [ "external_root", "root", "query", "limit", "include_tests"],
                "additionalProperties": False,
            },
            "strict": True,
        }

    @classmethod
    def result_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "properties": {"ok": {"type": "boolean"}, "tool": {"type": "string"}},
                "required": ["ok", "tool"], "additionalProperties": True}

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto", **context: Any) -> Dict[str, Any]:
        root, error = resolve_repository_root(self._storage_resolver, args)
        if error:
            return {"ok": False, "tool": self.NAME, **error}
        query = (args.get("query") or "").strip()
        limit = args.get("limit", 10)
        include_tests = args.get("include_tests", False)
        if not query:
            return {"ok": False, "tool": self.NAME, "error": "query is required"}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return {"ok": False, "tool": self.NAME, "error": "limit must be an integer between 1 and 50"}
        if not isinstance(include_tests, bool):
            return {"ok": False, "tool": self.NAME, "error": "include_tests must be a boolean"}
        results = RepositoryIndex(root).search(query, limit=limit, include_tests=include_tests)
        return {"ok": True, "tool": self.NAME, "query": query, "include_tests": include_tests,
                "count": len(results), "results": results}

