from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from galet_tools.tools.video_generate_handler import VideoGenerateHandler


class _Resolver:
    def __init__(self, base: Path) -> None:
        self._base = base

    def storage_base_dir(self) -> str:
        return str(self._base)

    def external_root_dir(self, name: str) -> str:
        raise ValueError(name)


class _VideoApi:
    def __init__(self) -> None:
        self.generate_kwargs = None
        self.download_destination = None

    def generate_video(self, **kwargs):
        self.generate_kwargs = kwargs
        return SimpleNamespace(
            videos=[SimpleNamespace(raw=object(), url="authenticated://video")]
        )

    def download_video(self, result, destination: str) -> None:
        self.download_destination = destination
        Path(destination).write_bytes(b"video-data")


def _uploaded_image(base: Path, account: str = "arla") -> str:
    image_id = str(uuid.uuid4())
    directory = base / "images" / account
    directory.mkdir(parents=True)
    (directory / f"{image_id}.png").write_bytes(b"png-data")
    (directory / f"{image_id}.json").write_text(
        json.dumps(
            {
                "id": image_id,
                "account": account,
                "mime_type": "image/png",
            }
        ),
        encoding="utf-8",
    )
    return image_id


def test_generates_video_from_uploaded_account_image(tmp_path) -> None:
    image_id = _uploaded_image(tmp_path)
    api = _VideoApi()
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=api)

    result = handler.execute(
        {
            "image_id": image_id,
            "prompt": "The model turns slightly toward the camera.",
            "duration_seconds": 4,
        },
        account_name="arla",
    )

    assert result["ok"] is True
    assert result["tool"] == "video_generate"
    assert result["duration_seconds"] == 4
    assert result["model"] == "veo-3.1-fast-generate-preview"
    assert result["path"] == f"videos/arla/{result['video_id']}.mp4"
    assert (tmp_path / result["path"]).read_bytes() == b"video-data"

    assert api.generate_kwargs["image_path"].endswith(f"{image_id}.png")
    assert api.generate_kwargs["aspect_ratio"] == "9:16"
    assert api.generate_kwargs["resolution"] == "720p"
    assert api.generate_kwargs["preserve_subject"] is True


def test_cannot_use_another_accounts_uploaded_image(tmp_path) -> None:
    image_id = _uploaded_image(tmp_path, account="john")
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=_VideoApi())

    result = handler.execute(
        {
            "image_id": image_id,
            "prompt": "Turn",
            "duration_seconds": 4,
        },
        account_name="arla",
    )

    assert result["ok"] is False
    assert "metadata not found" in result["error"]


def test_rejects_invalid_duration_before_generation(tmp_path) -> None:
    image_id = _uploaded_image(tmp_path)
    api = _VideoApi()
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=api)

    result = handler.execute(
        {
            "image_id": image_id,
            "prompt": "Turn",
            "duration_seconds": 5,
        },
        account_name="arla",
    )

    assert result["ok"] is False
    assert "4, 6, or 8" in result["error"]
    assert api.generate_kwargs is None


def test_tool_schema_prefers_uploaded_image_id() -> None:
    tool_def = VideoGenerateHandler.tool_def()

    assert tool_def["name"] == "video_generate"
    assert tool_def["parameters"]["required"] == [
        "image_id",
        "prompt",
        "duration_seconds",
    ]
