"""Tool adapter for galet-memory semantic recall and embedding utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from galet_memory.semantic import SemanticMemory
from galet_tools.framework.handler_v2 import HandlerV2

logger = logging.getLogger(__name__)


def _models_to_list(resp: Any) -> List[Any]:
    if isinstance(resp, list):
        return resp
    if not isinstance(resp, dict):
        return []
    embedded = resp.get("models")
    if isinstance(embedded, list):
        return embedded
    records: List[Any] = []
    for value in resp.values():
        if isinstance(value, dict):
            records.append(value)
        elif hasattr(value, "name"):
            records.append(
                {
                    "name": value.name,
                    "provider": getattr(value, "provider", ""),
                    "dimensions": getattr(value, "dimensions", None),
                    "description": getattr(value, "description", ""),
                }
            )
    return records


class SemanticMemoryHandler(HandlerV2):
    """Recall semantic memory through an injected galet-memory implementation."""

    NAME = "semantic_memory"

    def __init__(self, memory: SemanticMemory | None = None, *, embedding_facade: Any = None,
                 embedding_model: str = "text-embedding-3-small") -> None:
        self.embedding_model = embedding_model
        self.memory = memory
        self.embedding_facade = (
            embedding_facade if embedding_facade is not None
            else getattr(memory, "embedding_facade", None)
        )

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Recall durable semantic memory relevant to a query using the "
                "configured embedding store. Returns matching documents/snippets "
                "with similarity scores and retrieval metadata. Utility actions "
                "allow direct embedding operations and metadata lookup "
                "(embed, compare, rank, models, namespaces)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "recall",
                            "embed",
                            "compare",
                            "rank",
                            "models",
                            "namespaces",
                        ],
                        "description": "Operation to perform.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural-language query to recall relevant semantic memory.",
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Account whose semantic memory should be searched. Empty uses the caller account.",
                        "default": "",
                    },
                    "namespaces": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Namespaces to search; empty searches all namespaces for the account.",
                        "default": [],
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of vector matches to consider.",
                        "default": 3,
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters loaded from each matching source document.",
                        "default": 9000,
                    },
                    "score_threshold": {
                        "type": "number",
                        "description": "Minimum similarity score required for inclusion.",
                        "default": 0.25,
                    },
                    "embedding_model": {
                        "type": "string",
                        "description": "Query embedding model; omit to use the configured profile.",
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Optional source_type filter, e.g. 'obsidian_note'.",
                        "default": "",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            "strict": False,
        }

    @classmethod
    def result_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "tool": {"type": "string"},
                "action": {"type": "string"},
                "query": {"type": "string"},
                "account_name": {"type": "string"},
                "documents": {"type": "array", "items": {"type": "object"}},
                "metadata": {"type": "object"},
                "models": {"type": "array"},
                "namespaces": {"type": "array", "items": {"type": "string"}},
                "error": {"type": "string"},
            },
            "required": ["ok", "tool", "action"],
            "additionalProperties": True,
        }

    def execute(
        self,
        args: Dict[str, Any],
        *,
        account_name: str = "auto",
        **context: Any,
    ) -> Dict[str, Any]:
        memory = context.get("semantic_memory", self.memory)
        action = str(args.get("action") or "").strip().lower()

        allowed = ["recall", "embed", "compare", "rank", "models", "namespaces"]

        if action not in allowed:
            return {
                "ok": False,
                "tool": self.NAME,
                "action": action,
                "error": f"Unknown action: {action!r}. Use {', '.join(allowed)}.",
            }

        # --- recall ----------------------------------------------------------------
        if action == "recall":
            query = str(args.get("query") or "").strip()
            if not query:
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "action": action,
                    "error": "query is required",
                }

            requested_account = str(args.get("account_name") or "").strip()
            resolved_account = requested_account or str(account_name or "").strip()
            if not resolved_account or resolved_account == "auto":
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "action": action,
                    "error": "account_name is required",
                }

            from galet_memory.semantic import SemanticMemoryRequest

            namespaces_raw = args.get("namespaces") or []
            namespaces: List[str] = [
                str(value).strip() for value in namespaces_raw if str(value).strip()
            ]

            if not namespaces and hasattr(memory, "list_namespaces"):
                namespaces = list(memory.list_namespaces(resolved_account))

            request = SemanticMemoryRequest(
                account_name=resolved_account,
                query=query,
                use_embeddings=True,
                namespaces=namespaces,
                top_k=max(1, int(args.get("top_k", 3))),
                max_chars=max(1, int(args.get("max_chars", 9000))),
                score_threshold=float(args.get("score_threshold", 0.25)),
                embedding_model=str(
                    args.get("embedding_model") or self.embedding_model
                ).strip(),
                source_type=(str(args.get("source_type") or "").strip() or None),
            )

            try:
                result = memory.recall(request)
            except Exception as exc:
                logger.exception("semantic_memory recall failed")
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "action": action,
                    "query": query,
                    "account_name": resolved_account,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            documents = [
                {
                    "source_id": doc.source_id,
                    "source_type": doc.source_type,
                    "title": doc.title,
                    "snippet": doc.snippet,
                    "tags": list(doc.tags),
                    "score": doc.score,
                    "truncated": doc.truncated,
                    "path": doc.path,
                    "metadata": dict(doc.metadata),
                }
                for doc in result.documents
            ]

            return {
                "ok": True,
                "tool": self.NAME,
                "action": action,
                "query": query,
                "account_name": resolved_account,
                "documents": documents,
                "count": len(documents),
                "metadata": dict(result.metadata),
            }

        # --- embed -----------------------------------------------------------------
        if action == "embed":
            query = str(args.get("query") or "").strip()
            model = str(args.get("embedding_model") or self.embedding_model).strip()
            texts = [query] if query else []

            if not texts:
                return {"ok": False, "tool": self.NAME, "action": "embed", "error": "No texts provided"}

            try:
                if hasattr(memory, "embed"):
                    resp = memory.embed(texts, model=model)
                elif self.embedding_facade is not None:
                    resp = self.embedding_facade.embed(texts, model=model)
                else:
                    raise RuntimeError("no embedding facade available")
            except Exception as exc:
                logger.exception("semantic_memory embed failed")
                return {"ok": False, "tool": self.NAME, "action": "embed", "error": f"{type(exc).__name__}: {exc}"}

            return {"ok": True, "tool": self.NAME, "action": "embed", "model": getattr(resp, "model", ""), "embeddings": getattr(resp, "embeddings", [])}

        # --- compare ---------------------------------------------------------------
        if action == "compare":
            a = args.get("vector_a", [])
            b = args.get("vector_b", [])
            model = str(args.get("embedding_model") or "").strip() or None

            try:
                if hasattr(memory, "compare"):
                    resp = memory.compare(a, b, model=model)
                elif self.embedding_facade is not None:
                    resp = self.embedding_facade.compare(a, b, model=model)
                else:
                    raise RuntimeError("no compare capability available")
            except Exception as exc:
                logger.exception("semantic_memory compare failed")
                return {"ok": False, "tool": self.NAME, "action": "compare", "error": f"{type(exc).__name__}: {exc}"}

            return {"ok": True, "tool": self.NAME, "action": "compare", **(resp if isinstance(resp, dict) else {"score": getattr(resp, "score", None)})}

        # --- rank ------------------------------------------------------------------
        if action == "rank":
            items = args.get("candidates", [])
            # If no candidates, attempt to use query as single item
            if not items:
                q = str(args.get("query") or "").strip()
                items = [q] if q else []

            model = str(args.get("embedding_model") or "").strip() or None

            try:
                if hasattr(memory, "rank"):
                    resp = memory.rank(items, model=model)
                elif self.embedding_facade is not None:
                    resp = self.embedding_facade.rank(items, model=model)
                else:
                    raise RuntimeError("no rank capability available")
            except Exception as exc:
                logger.exception("semantic_memory rank failed")
                return {"ok": False, "tool": self.NAME, "action": "rank", "error": f"{type(exc).__name__}: {exc}"}

            return {"ok": True, "tool": self.NAME, "action": "rank", **(resp if isinstance(resp, dict) else {})}

        # --- models ---------------------------------------------------------------
        if action == "models":
            try:
                if hasattr(memory, "models"):
                    resp = memory.models()
                elif self.embedding_facade is not None and hasattr(
                    self.embedding_facade, "models"
                ):
                    resp = self.embedding_facade.models()
                else:
                    resp = None
            except Exception as exc:
                logger.exception("semantic_memory models failed")
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "action": action,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            if resp is None:
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "action": action,
                    "error": "no models capability available",
                }

            models_list = _models_to_list(resp)
            return {
                "ok": True,
                "tool": self.NAME,
                "action": action,
                "models": models_list,
                "count": len(models_list),
            }

        # --- namespaces ------------------------------------------------------------
        if action == "namespaces":
            requested_account = str(args.get("account_name") or "").strip()
            resolved_account = requested_account or str(account_name or "").strip()
            if not resolved_account or resolved_account == "auto":
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "action": action,
                    "error": "account_name is required",
                }

            try:
                if hasattr(memory, "list_namespaces"):
                    namespaces = list(memory.list_namespaces(resolved_account))
                elif hasattr(memory, "embedding_store") and hasattr(
                    memory.embedding_store, "list_embedding_namespaces"
                ):
                    namespaces = list(
                        memory.embedding_store.list_embedding_namespaces(
                            resolved_account
                        )
                    )
                elif hasattr(memory, "index"):
                    namespaces = list(memory.index.list_namespaces(resolved_account))
                else:
                    return {
                        "ok": False,
                        "tool": self.NAME,
                        "action": action,
                        "error": "no namespaces capability available",
                    }
            except Exception as exc:
                logger.exception("semantic_memory namespaces failed")
                return {
                    "ok": False,
                    "tool": self.NAME,
                    "action": action,
                    "account_name": resolved_account,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            return {
                "ok": True,
                "tool": self.NAME,
                "action": action,
                "account_name": resolved_account,
                "namespaces": namespaces,
                "count": len(namespaces),
            }


__all__ = ["SemanticMemoryHandler"]
