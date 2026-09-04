from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class HandlerV2(ABC):
    """End-state handler interface.

    - tool_def(): OpenAI tool definition (type=function, function={...})
    - execute(args, ...): returns a structured python dict (tool result)
    - result_schema(): optional JSON schema for the returned dict

    Subclasses may accept additional **context kwargs in execute() for
    runtime execution context (e.g. conversation_id, primary_agent, etc.).
    """

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        ...

    @classmethod
    @abstractmethod
    def tool_def(cls) -> Dict[str, Any]:
        ...

    @classmethod
    def result_schema(cls) -> Optional[Dict[str, Any]]:
        return None

    @abstractmethod
    def execute(self, args: Dict[str, Any], *, account_name: str = "auto", **context) -> Dict[str, Any]:
        ...
