from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Any, Dict, Optional
import uuid
from urllib.parse import quote

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver
from galet_tools.tools.uploaded_image_resolver import UploadedImageResolver

logger = logging.getLogger(__name__)



class VideoGenerateHandler(UploadedImageResolver, HandlerV2):
    """Generate an image-based video with caller-selected provider settings."""

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
                "Generate a short video from an image uploaded to the current account. "
                "Choose the source and model explicitly when requested. Defaults produce "
                "a silent portrait reel with the subject and garments preserved."
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
                    "source": {
                        "type": "string",
                        "enum": ["google"],
                        "default": "google",
                        "description": "Video provider. Currently only Google is supported.",
                    },
                    "model": {
                        "type": "string",
                        "minLength": 1,
                        "default": "veo-3.1-fast-generate-preview",
                        "description": "Provider model ID; defaults to veo-3.1-fast-generate-preview.",
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["9:16", "16:9"],
                        "default": "9:16",
                        "description": "Output aspect ratio; portrait 9:16 by default.",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["720p", "1080p", "4k"],
                        "default": "720p",
                        "description": "Output resolution. 1080p and 4k require 8 seconds.",
                    },
                    "preserve_subject": {
                        "type": "boolean",
                        "default": True,
                        "description": "Preserve identity and garments in the prompt; defaults to true.",
                    },
                    "add_sound": {
                        "type": "boolean",
                        "default": False,
                        "description": "Retain provider-generated audio if true; false removes audio from the MP4.",
                    },
                },
                "required": ["image_id", "prompt", "duration_seconds"],
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
                "source": {"type": "string"},
                "aspect_ratio": {"type": "string"},
                "resolution": {"type": "string"},
                "preserve_subject": {"type": "boolean"},
                "add_sound": {"type": "boolean"},
                "error": {"type": "string"},
            },
            "required": ["ok", "tool"],
            "additionalProperties": True,
        }

    def _get_video_api(self, source: str) -> Any:
        if source != "google":
            raise ValueError(f"unsupported video source: {source}; currently only google is supported")
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
    def _remove_audio(ffmpeg: str, source: Path, destination: Path) -> None:
        """Copy the video stream unchanged, excluding every audio track."""
        try:
            subprocess.run(
                [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(source),
                 "-map", "0:v:0", "-c:v", "copy", "-an", "-movflags", "+faststart",
                 str(destination)],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("FFmpeg failed to remove audio from the generated video") from exc

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
            if type(duration) is not int or duration not in {4, 6, 8}:
                raise ValueError("duration_seconds must be 4, 6, or 8")

            source = args.get("source", "google")
            model = args.get("model", "veo-3.1-fast-generate-preview")
            aspect_ratio = args.get("aspect_ratio", "9:16")
            resolution = args.get("resolution", "720p")
            preserve_subject = args.get("preserve_subject", True)
            add_sound = args.get("add_sound", False)
            if source != "google":
                raise ValueError("source must be google; no other video providers are supported yet")
            if not isinstance(model, str) or not model.strip():
                raise ValueError("model must be a non-empty provider model ID")
            model = model.strip()
            if aspect_ratio not in ("9:16", "16:9"):
                raise ValueError("aspect_ratio must be 9:16 or 16:9")
            if resolution not in ("720p", "1080p", "4k"):
                raise ValueError("resolution must be 720p, 1080p, or 4k")
            if resolution in ("1080p", "4k") and duration != 8:
                raise ValueError("1080p and 4k generation require an 8-second duration")
            if not isinstance(preserve_subject, bool) or not isinstance(add_sound, bool):
                raise ValueError("preserve_subject and add_sound must be booleans")

            image_path = self._resolve_image(
                account_name=account,
                image_id=image_id,
            )
            ffmpeg = None if add_sound else shutil.which("ffmpeg")
            if not add_sound and ffmpeg is None:
                raise RuntimeError("add_sound=false requires FFmpeg installed on the host and available on PATH")
            storage = Path(self._storage_resolver.storage_base_dir())
            video_id = str(uuid.uuid4())
            output_dir = self._contained_path(storage, "videos", account)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self._contained_path(output_dir, f"{video_id}.mp4")

            api = self._get_video_api(source)
            response = api.generate_video(
                model=model,
                prompt=prompt,
                image_path=str(image_path),
                aspect_ratio=aspect_ratio,
                duration_seconds=duration,
                resolution=resolution,
                preserve_subject=preserve_subject,
            )
            result = response.videos[0]
            with TemporaryDirectory(dir=output_dir) as temporary:
                downloaded = Path(temporary) / "provider.mp4"
                api.download_video(result, str(downloaded))
                if add_sound:
                    downloaded.replace(output_path)
                else:
                    silent = Path(temporary) / "silent.mp4"
                    self._remove_audio(ffmpeg, downloaded, silent)
                    silent.replace(output_path)
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
            "source": source,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "preserve_subject": preserve_subject,
            "add_sound": add_sound,
            "video": {
                "url": download_url,
                "mime_type": "video/mp4",
                "download_name": f"fashion-reel-{video_id}.mp4",
                "video_id": video_id,
            },
        }

