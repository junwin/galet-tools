"""AI image generation/editing through Galet's provider-neutral image API."""
from __future__ import annotations
import logging
import base64
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import urlopen
from PIL import Image
from typing import Any
from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.storage_location_resolver import StorageLocationResolver
from galet_tools.tools.uploaded_image_resolver import UploadedImageResolver

logger = logging.getLogger(__name__)

class ImageGenerateHandler(UploadedImageResolver, HandlerV2):
    NAME = "image_generate"

    def __init__(self, storage_resolver: StorageLocationResolver, image_api: Any = None) -> None:
        self._storage_resolver = storage_resolver
        self._image_api = image_api

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> dict:
        properties = {
            "prompt": {"type": "string", "description": "Final instruction to the image model."},
            "model": {"type": "string", "description": "Galet image model, e.g. gpt-image-1 or gemini-2.5-flash-image."},
            "size": {"type": "string", "description": "Output size, e.g. 1024x1024."},
            "quality": {"type": "string", "enum": ["standard", "hd", "low", "medium", "high", "auto"]},
            "image_ids": {"type": "array", "items": {"type": "string"}, "description": "Reference upload UUIDs in the current account; [] for text-only generation."},
            "messages": {"type": "array", "description": "Explicit earlier image turns; [] for a single request. Do not include unrelated tool/chat events.", "items": {
                "type": "object", "properties": {
                    "role": {"type": "string", "enum": ["user", "assistant"]},
                    "text": {"type": "string"},
                    "image_ids": {"type": "array", "items": {"type": "string"}},
                }, "required": ["role", "text", "image_ids"], "additionalProperties": False}},
        }
        return {"type": "function", "name": cls.NAME,
                "description": "Generate or edit an AI image using Galet. Reference images are sent as image data. Saves a PNG and returns its image UUID, path, and display URL. Use the UUID for later edits.",
                "parameters": {"type": "object", "properties": properties,
                               "required": list(properties), "additionalProperties": False}, "strict": True}

    @classmethod
    def result_schema(cls) -> dict:
        return {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "tool": {"type": "string"},
            "model": {"type": "string"}, "error": {"type": "string"},
            "image_id": {"type": "string"}, "path": {"type": "string"},
            "download_url": {"type": "string"}, "mime_type": {"type": "string"},
            "image": {"type": "object", "properties": {
                "url": {"type": "string"}, "alt": {"type": "string"}},
                "required": ["url", "alt"], "additionalProperties": False}},
            "required": ["ok", "tool"], "additionalProperties": False}

    def _get_image_api(self) -> Any:
        if self._image_api is None:
            from galet.imagegen_router import ImageGenRouter
            self._image_api = ImageGenRouter()
        return self._image_api

    def _persist_image(self, result: Any, account: str, prompt: str) -> tuple[str, str]:
        """Persist provider bytes as PNG using the host upload metadata contract."""
        max_bytes = 50 * 1024 * 1024
        if result.b64_json:
            if len(result.b64_json) > (max_bytes * 4 // 3 + 4):
                raise ValueError("generated image exceeds storage size limit")
            raw = base64.b64decode(result.b64_json, validate=True)
        elif result.url:
            if urlparse(result.url).scheme != "https":
                raise ValueError("provider image download requires an HTTPS URL")
            with urlopen(result.url, timeout=30) as download:
                raw = download.read(max_bytes + 1)
        else:
            raise ValueError("image model returned an empty image")
        if len(raw) > max_bytes:
            raise ValueError("generated image exceeds storage size limit")
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            image = source.convert("RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
        png = output.getvalue()
        image_id = str(uuid.uuid4())
        storage = Path(self._storage_resolver.storage_base_dir())
        directory = self._contained_path(storage, "images", account)
        directory.mkdir(parents=True, exist_ok=True)
        path = self._contained_path(directory, f"{image_id}.png")
        metadata_path = self._contained_path(directory, f"{image_id}.json")
        metadata = {"id": image_id, "account": account,
                    "original_filename": f"generated-{image_id}.png",
                    "mime_type": "image/png", "size_bytes": len(png),
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "source": "image_generate", "prompt": prompt}
        try:
            with path.open("xb") as handle:
                handle.write(png)
            with metadata_path.open("x", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False)
        except Exception:
            path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            raise
        logger.info("image_generate: saved image_id=%s account=%s size_bytes=%d", image_id, account, len(png))
        return image_id, f"images/{account}/{image_id}.png"

    def execute(self, args: dict, *, account_name: str = "auto", **context: Any) -> dict:
        try:
            from galet.imagegen_dto import ImageInput, ImageMessage
            account = self._validate_account_name(account_name)
            prompt = args.get("prompt", "")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("prompt is required")
            model = args.get("model", "")
            if not isinstance(model, str) or not model.strip():
                raise ValueError("model is required")

            def load_images(ids: Any) -> tuple:
                if not isinstance(ids, list):
                    raise ValueError("image_ids must be a list")
                if len(ids) > 16:
                    raise ValueError("at most 16 reference images per turn")
                result = []
                for raw_id in ids:
                    image_id = self._validate_image_id(raw_id)
                    path = self._resolve_image(account_name=account, image_id=image_id)
                    mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[path.suffix]
                    result.append(ImageInput(data=path.read_bytes(), mime_type=mime))
                return tuple(result)

            raw_messages = args.get("messages", [])
            if not isinstance(raw_messages, list) or len(raw_messages) > 20:
                raise ValueError("messages must be a list of at most 20 turns")
            messages = [ImageMessage(role=m["role"], text=m["text"],
                                     images=load_images(m.get("image_ids", []))) for m in raw_messages]
            references = load_images(args.get("image_ids", []))
            if references:
                messages.append(ImageMessage(role="user", images=references))
            extra = {"messages": messages} if messages else {}
            response = self._get_image_api().generate_image(
                model=model.strip(), prompt=prompt, size=args.get("size", "1024x1024"),
                quality=args.get("quality", "standard"), n=1, **extra)
            if not response.images:
                raise ValueError("image model returned no images")
            result = response.images[0]
            image_id, path = self._persist_image(result, account, prompt)
            download_url = f"/download/image/{image_id}?accountName={quote(account, safe='')}"
            return {"ok": True, "tool": self.NAME, "model": response.model or model,
                    "image_id": image_id, "path": path, "mime_type": "image/png",
                    "download_url": download_url,
                    "image": {"url": download_url, "alt": prompt}}
        except Exception as exc:
            logger.exception("image_generate failed")
            return {"ok": False, "tool": self.NAME, "error": str(exc)}
