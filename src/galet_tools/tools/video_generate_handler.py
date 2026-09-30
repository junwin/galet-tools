from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional
import uuid
from urllib.parse import quote

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver
from galet_tools.tools.uploaded_image_resolver import UploadedImageResolver

logger = logging.getLogger(__name__)



class VideoGenerateHandler(UploadedImageResolver, HandlerV2):
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
                "download_url": {"type": "string"},
                "video": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "mime_type": {"type": "string"},
                        "download_name": {"type": "string"},
                        "video_id": {"type": "string"},
                    },
                    "required": ["url", "mime_type", "download_name", "video_id"],
                    "additionalProperties": False,
                },
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

        download_url = (
            f"/download/video/{video_id}?accountName={quote(account, safe='')}"
        )
        return {
            "ok": True,
            "tool": self.NAME,
            "video_id": video_id,
            "path": f"videos/{account}/{video_id}.mp4",
            "download_url": download_url,
            "mime_type": "video/mp4",
            "duration_seconds": duration,
            "model": model,
            "video": {
                "url": download_url,
                "mime_type": "video/mp4",
                "download_name": f"fashion-reel-{video_id}.mp4",
                "video_id": video_id,
            },
        }

