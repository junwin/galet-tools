from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class VideoGenerateHandler(HandlerV2):
    """Generate a short fashion reel from an image uploaded to host storage."""

    NAME = "video_generate"

    def __init__(
        self,
        storage_resolver: StorageLocationResolver,
        video_api: Optional[Any] = None,
    ) -> None:
        self._storage_resolver = storage_resolver
        self._video_api = video_api

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Generate a short portrait fashion reel from an image previously "
                "uploaded to the current account. The garment must remain unchanged."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_id": {
                        "type": "string",
                        "description": "Image ID returned by the host upload endpoint.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The subtle motion the model should perform.",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "enum": [4, 6, 8],
                        "description": "Generated reel duration. Prefer 4 seconds for garment fidelity.",
                    },
                },
                "required": ["image_id", "prompt", "duration_seconds"],
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
                "video_id": {"type": "string"},
                "path": {"type": "string"},
                "mime_type": {"type": "string"},
                "duration_seconds": {"type": "integer"},
                "model": {"type": "string"},
                "error": {"type": "string"},
            },
            "required": ["ok", "tool"],
            "additionalProperties": True,
        }

    def _get_video_api(self) -> Any:
        if self._video_api is None:
            try:
                from galet.gemini_videogen import GeminiVideoGenApi
            except ImportError as exc:
                raise RuntimeError(
                    "video_generate requires Galet with video support installed"
                ) from exc
            self._video_api = GeminiVideoGenApi()
        return self._video_api

    @staticmethod
    def _validate_account_name(account_name: str) -> str:
        value = (account_name or "").strip()
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or os.path.isabs(value)
        ):
            raise ValueError("invalid account name")
        return value

    @staticmethod
    def _validate_image_id(image_id: str) -> str:
        try:
            parsed = uuid.UUID(image_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("image_id must be a UUID") from exc
        return str(parsed)

    @staticmethod
    def _contained_path(base: Path, *parts: str) -> Path:
        base_resolved = base.resolve()
        candidate = base_resolved.joinpath(*parts).resolve()
        if os.path.commonpath([str(base_resolved), str(candidate)]) != str(base_resolved):
            raise ValueError("file path escapes storage root")
        return candidate

    def _resolve_image(
        self,
        *,
        account_name: str,
        image_id: str,
    ) -> Path:
        storage = Path(self._storage_resolver.storage_base_dir())
        image_dir = self._contained_path(storage, "images", account_name)
        metadata_path = self._contained_path(image_dir, f"{image_id}.json")
        if not metadata_path.is_file():
            raise FileNotFoundError("uploaded image metadata not found")

        with metadata_path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        if metadata.get("id") != image_id or metadata.get("account") != account_name:
            raise ValueError("uploaded image metadata does not match the request")

        mime_type = metadata.get("mime_type")
        extension = _IMAGE_EXTENSIONS.get(mime_type)
        if extension is None:
            raise ValueError(f"unsupported source image type: {mime_type}")

        image_path = self._contained_path(image_dir, f"{image_id}{extension}")
        if not image_path.is_file():
            raise FileNotFoundError("uploaded image file not found")
        return image_path

    def execute(
        self,
        args: Dict[str, Any],
        *,
        account_name: str = "auto",
        **context: Any,
    ) -> Dict[str, Any]:
        try:
            account = self._validate_account_name(account_name)
            image_id = self._validate_image_id(str(args.get("image_id", "")))
            prompt = str(args.get("prompt", "")).strip()
            duration = args.get("duration_seconds")
            if not prompt:
                raise ValueError("prompt is required")
            if isinstance(duration, bool) or duration not in {4, 6, 8}:
                raise ValueError("duration_seconds must be 4, 6, or 8")

            image_path = self._resolve_image(
                account_name=account,
                image_id=image_id,
            )
            storage = Path(self._storage_resolver.storage_base_dir())
            video_id = str(uuid.uuid4())
            output_dir = self._contained_path(storage, "videos", account)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self._contained_path(output_dir, f"{video_id}.mp4")

            api = self._get_video_api()
            model = "veo-3.1-fast-generate-preview"
            response = api.generate_video(
                model=model,
                prompt=prompt,
                image_path=str(image_path),
                aspect_ratio="9:16",
                duration_seconds=duration,
                resolution="720p",
                preserve_subject=True,
            )
            result = response.videos[0]
            api.download_video(result, str(output_path))
        except Exception as exc:
            logger.exception("video_generate failed")
            return {
                "ok": False,
                "tool": self.NAME,
                "error": str(exc),
            }

        return {
            "ok": True,
            "tool": self.NAME,
            "video_id": video_id,
            "path": f"videos/{account}/{video_id}.mp4",
            "mime_type": "video/mp4",
            "duration_seconds": duration,
            "model": model,
        }
