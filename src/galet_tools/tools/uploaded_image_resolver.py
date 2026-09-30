"""Shared account-fenced resolution of host-uploaded images."""
from __future__ import annotations
import json
import os
import uuid
from pathlib import Path
from galet_tools.ports.storage_location_resolver import StorageLocationResolver

_IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

class UploadedImageResolver:
    _storage_resolver: StorageLocationResolver

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

