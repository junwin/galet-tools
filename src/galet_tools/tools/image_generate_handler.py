"""AI image generation/editing through Galet's provider-neutral image API."""
from __future__ import annotations
import logging
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
                "description": "Generate or edit an AI image using Galet. Reference images are sent as image data. Returns an inline image for display.",
                "parameters": {"type": "object", "properties": properties,
                               "required": list(properties), "additionalProperties": False}, "strict": True}

    @classmethod
    def result_schema(cls) -> dict:
        return {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "tool": {"type": "string"},
            "model": {"type": "string"}, "error": {"type": "string"},
            "image": {"type": "object", "properties": {
                "url": {"type": "string"}, "alt": {"type": "string"}},
                "required": ["url", "alt"], "additionalProperties": False}},
            "required": ["ok", "tool"], "additionalProperties": False}

    def _get_image_api(self) -> Any:
        if self._image_api is None:
            from galet.imagegen_router import ImageGenRouter
            self._image_api = ImageGenRouter()
        return self._image_api

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
            url = result.url
            if result.b64_json:
                url = f"data:{result.mime_type};base64,{result.b64_json}"
            if not url:
                raise ValueError("image model returned an empty image")
            return {"ok": True, "tool": self.NAME, "model": response.model or model,
                    "image": {"url": url, "alt": prompt}}
        except Exception as exc:
            logger.exception("image_generate failed")
            return {"ok": False, "tool": self.NAME, "error": str(exc)}
