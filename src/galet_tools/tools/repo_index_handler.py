from __future__ import annotations

from typing import Any, Dict

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver
from galet_tools.tools.repository_handler_support import resolve_repository_root
from galet_tools.tools.repository_index import RepositoryIndex


class RepoIndexHandler(HandlerV2):
    """Inspect source repository structure and searchable file metadata."""

    NAME = "repo_index"

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
                "Inspect a source repository. For Python, operation='symbol' locates classes, "
                "functions, methods, and qualified Class.method names with AST line ranges. For "
                "other supported languages it returns matching text lines. operation='lookup' "
                "returns Python structure or basic metadata for a file/directory; operation='map' "
                "lists supported source files. Prefer this before broad file reads."
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
                    "operation": {"type": "string", "enum": ["symbol", "lookup", "map"]},
                    "query": {"type": "string", "description": "Symbol or path for symbol/lookup; use '' for map."},
                    "include_tests": {"type": "boolean", "description": "Include tests in symbol/map results."},
                },
                "required": [ "external_root", "root", "operation", "query", "include_tests"],
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
        operation = (args.get("operation") or "").strip().lower()
        query = (args.get("query") or "").strip()
        include_tests = args.get("include_tests", False)
        if not isinstance(include_tests, bool):
            return {"ok": False, "tool": self.NAME, "error": "include_tests must be a boolean"}
        if operation in {"symbol", "lookup"} and not query:
            return {"ok": False, "tool": self.NAME, "error": "query is required for symbol and lookup"}

        index = RepositoryIndex(root)
        if operation == "symbol":
            results = index.find_symbol(query, include_tests=include_tests)
        elif operation == "lookup":
            results = index.lookup(query)
        elif operation == "map":
            results = index.map(include_tests=include_tests)
        else:
            return {"ok": False, "tool": self.NAME, "error": f"Unknown operation '{operation}'"}
        return {"ok": True, "tool": self.NAME, "operation": operation, "query": query,
                "include_tests": include_tests, "count": len(results), "results": results}

