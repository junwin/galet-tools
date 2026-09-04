from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Generic, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError


class ErrorCode(str, Enum):
    """Shared error codes for tool execution.

    Keep this small and stable; callers can key on this.
    """

    INVALID_ARGS = "invalid_args"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    RESULT_SERIALIZATION_FAILED = "result_serialization_failed"


class ResultEnvelope(BaseModel):
    """Base envelope for tool results.

    Tools should return an object that includes at least ok + tool.
    """

    ok: bool
    tool: str
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None


ArgsT = TypeVar("ArgsT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)


class SchemaHandlerV2(ABC, Generic[ArgsT, ResultT]):
    """Typed handler base with a raw JSON-string interface.

    - ArgsModel: Pydantic model used to validate/normalize tool arguments.
    - ResultModel: Pydantic model used to validate/normalize tool results.

    The processor will call execute_raw(arguments_raw, call_id=...).
    Handlers must return a JSON *object* string.
    """

    ArgsModel: Type[ArgsT]
    ResultModel: Type[ResultT]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__()

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
        """Return the ResultModel JSON schema when available."""
        try:
            return cls.ResultModel.model_json_schema()  # type: ignore[attr-defined]
        except Exception:
            return None

    def execute_raw(self, arguments_raw: str, *, account_name: str = "auto", call_id: str = "", **context: Any) -> str:
        """Execute a tool call with raw JSON arguments.

        Returns: JSON object string.
        """
        try:
            args_dict: Dict[str, Any]
            if not arguments_raw:
                args_dict = {}
            else:
                loaded = json.loads(arguments_raw)
                args_dict = loaded if isinstance(loaded, dict) else {}
        except Exception:
            logging.warning(
                "tool_args_invalid_json tool=%s call_id=%s args_preview=%r",
                self.name(),
                call_id,
                (arguments_raw or "")[:500],
            )
            return self._dump_result(
                ResultEnvelope(
                    ok=False,
                    tool=self.name(),
                    error="Tool arguments were not valid JSON.",
                    error_code=ErrorCode.INVALID_ARGS,
                ),
                call_id=call_id,
            )

        return self._execute_typed(args_dict, account_name=account_name, call_id=call_id)

    def _execute_typed(self, args: Dict[str, Any], *, account_name: str, call_id: str) -> str:
        try:
            typed_args = self.ArgsModel.model_validate(args)
        except ValidationError as e:
            logging.info(
                "tool_args_validation_failed tool=%s call_id=%s errors=%s",
                self.name(),
                call_id,
                e.errors(),
            )
            return self._dump_result(
                ResultEnvelope(
                    ok=False,
                    tool=self.name(),
                    error="Tool arguments failed validation.",
                    error_code=ErrorCode.INVALID_ARGS,
                ),
                call_id=call_id,
            )

        try:
            result = self.execute(typed_args, account_name=account_name, call_id=call_id)
        except Exception as e:
            logging.exception("tool_execute_failed tool=%s call_id=%s", self.name(), call_id)
            return self._dump_result(
                ResultEnvelope(
                    ok=False,
                    tool=self.name(),
                    error=f"{type(e).__name__}: {e}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED,
                ),
                call_id=call_id,
            )

        try:
            typed_result = self.ResultModel.model_validate(result)
        except ValidationError as e:
            logging.error(
                "tool_result_validation_failed tool=%s call_id=%s errors=%s",
                self.name(),
                call_id,
                e.errors(),
            )
            fallback = {
                "ok": False,
                "tool": self.name(),
                "error": "Tool returned invalid result shape.",
                "error_code": ErrorCode.RESULT_SERIALIZATION_FAILED,
                "raw_result": result,
            }
            return json.dumps(fallback, ensure_ascii=False)

        return self._dump_result(typed_result, call_id=call_id)

    @abstractmethod
    def execute(self, args: ArgsT, *, account_name: str = "auto", call_id: str = "") -> ResultT | Dict[str, Any]:
        ...

    def _dump_result(self, result_obj: BaseModel, *, call_id: str) -> str:
        try:
            payload = result_obj.model_dump()
            if not isinstance(payload, dict):
                payload = {"ok": False, "tool": self.name(), "error": "Tool result must be an object."}
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            logging.exception("tool_result_dump_failed tool=%s call_id=%s", self.name(), call_id)
            return json.dumps(
                {
                    "ok": False,
                    "tool": self.name(),
                    "error": f"Failed to serialize tool result: {type(e).__name__}: {e}",
                    "error_code": ErrorCode.RESULT_SERIALIZATION_FAILED,
                },
                ensure_ascii=False,
            )
