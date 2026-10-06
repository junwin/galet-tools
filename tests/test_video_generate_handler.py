from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import uuid

import pytest

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


def test_generates_video_from_uploaded_account_image(tmp_path, monkeypatch) -> None:
    image_id = _uploaded_image(tmp_path)
    api = _VideoApi()
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=api)
    monkeypatch.setattr("galet_tools.tools.video_generate_handler.shutil.which", lambda _: "ffmpeg")
    mute_calls = []

    def mute(ffmpeg, source, destination):
        mute_calls.append((ffmpeg, source.name, destination.name))
        shutil.copyfile(source, destination)

    monkeypatch.setattr(handler, "_remove_audio", mute)

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
    assert result["source"] == "google"
    assert result["add_sound"] is False
    assert mute_calls == [("ffmpeg", "provider.mp4", "silent.mp4")]
    assert result["path"] == f"videos/arla/{result['video_id']}.mp4"
    assert result["download_url"] == (
        f"/download/video/{result['video_id']}?accountName=arla"
    )
    assert result["video"] == {
        "url": result["download_url"],
        "mime_type": "video/mp4",
        "download_name": f"fashion-reel-{result['video_id']}.mp4",
        "video_id": result["video_id"],
    }
    assert (tmp_path / result["path"]).read_bytes() == b"video-data"

    assert api.generate_kwargs["image_path"].endswith(f"{image_id}.png")
    assert api.generate_kwargs["aspect_ratio"] == "9:16"
    assert api.generate_kwargs["resolution"] == "720p"
    assert api.generate_kwargs["preserve_subject"] is True
    assert "add_sound" not in api.generate_kwargs  # Unsupported by Gemini API.


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
    assert tool_def["strict"] is False  # Defaults can be omitted.
    properties = tool_def["parameters"]["properties"]
    assert properties["source"]["default"] == "google"
    assert properties["model"]["default"] == "veo-3.1-fast-generate-preview"
    assert properties["aspect_ratio"]["default"] == "9:16"
    assert properties["resolution"]["default"] == "720p"
    assert properties["preserve_subject"]["default"] is True
    assert properties["add_sound"]["default"] is False


def test_forwards_explicit_settings_and_retains_audio(tmp_path, monkeypatch) -> None:
    image_id = _uploaded_image(tmp_path)
    api = _VideoApi()
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=api)
    monkeypatch.setattr("galet_tools.tools.video_generate_handler.shutil.which", lambda _: None)
    result = handler.execute({
        "image_id": image_id, "prompt": "Turn", "duration_seconds": 8,
        "source": "google", "model": "veo-3.1-generate-preview",
        "aspect_ratio": "16:9", "resolution": "1080p",
        "preserve_subject": False, "add_sound": True,
    }, account_name="arla")
    assert result["ok"] is True
    assert api.generate_kwargs["model"] == "veo-3.1-generate-preview"
    assert api.generate_kwargs["aspect_ratio"] == "16:9"
    assert api.generate_kwargs["resolution"] == "1080p"
    assert api.generate_kwargs["preserve_subject"] is False
    assert result["add_sound"] is True
    assert (tmp_path / result["path"]).read_bytes() == b"video-data"


@pytest.mark.parametrize("settings, error", [
    ({"source": "openai"}, "source must be google"),
    ({"source": None}, "source must be google"),
    ({"model": " "}, "model must be"),
    ({"model": None}, "model must be"),
    ({"aspect_ratio": "1:1"}, "aspect_ratio must be"),
    ({"resolution": "480p"}, "resolution must be"),
    ({"resolution": "1080p"}, "8-second duration"),
    ({"resolution": "4k"}, "8-second duration"),
    ({"preserve_subject": "false"}, "must be booleans"),
    ({"add_sound": "false"}, "must be booleans"),
    ({"duration_seconds": True}, "duration_seconds"),
    ({"duration_seconds": 4.0}, "duration_seconds"),
])
def test_invalid_settings_fail_before_generation(tmp_path, settings, error) -> None:
    image_id = _uploaded_image(tmp_path)
    api = _VideoApi()
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=api)
    result = handler.execute({"image_id": image_id, "prompt": "Turn",
                              "duration_seconds": 4, **settings}, account_name="arla")
    assert result["ok"] is False
    assert error in result["error"]
    assert api.generate_kwargs is None


def test_silent_default_requires_ffmpeg_before_generation(tmp_path, monkeypatch) -> None:
    image_id = _uploaded_image(tmp_path)
    api = _VideoApi()
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=api)
    monkeypatch.setattr("galet_tools.tools.video_generate_handler.shutil.which", lambda _: None)
    result = handler.execute({"image_id": image_id, "prompt": "Turn",
                              "duration_seconds": 4}, account_name="arla")
    assert result["ok"] is False
    assert "requires FFmpeg" in result["error"]
    assert api.generate_kwargs is None


def test_mute_failure_does_not_publish_video(tmp_path, monkeypatch) -> None:
    image_id = _uploaded_image(tmp_path)
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=_VideoApi())
    monkeypatch.setattr("galet_tools.tools.video_generate_handler.shutil.which", lambda _: "ffmpeg")

    def fail(ffmpeg, source, destination):
        destination.write_bytes(b"partial-output")
        raise RuntimeError("audio removal failed")

    monkeypatch.setattr(handler, "_remove_audio", fail)
    result = handler.execute({"image_id": image_id, "prompt": "Turn",
                              "duration_seconds": 4}, account_name="arla")
    assert result["ok"] is False
    assert not list((tmp_path / "videos" / "arla").iterdir())


@pytest.mark.parametrize("add_sound", [False, True])
def test_real_mp4_audio_policy(tmp_path, add_sound) -> None:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe required for MP4 integration test")
    original = tmp_path / "original.mp4"
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=32x32:r=5:d=1", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", "-c:v", "mpeg4", "-c:a",
                    "aac", "-shortest", str(original)], check=True, timeout=30)

    class RealVideoApi(_VideoApi):
        def download_video(self, result, destination):
            shutil.copyfile(original, destination)

    image_id = _uploaded_image(tmp_path)
    handler = VideoGenerateHandler(_Resolver(tmp_path), video_api=RealVideoApi())
    result = handler.execute({"image_id": image_id, "prompt": "Turn",
                              "duration_seconds": 4, "add_sound": add_sound}, account_name="arla")
    assert result["ok"] is True
    output = tmp_path / result["path"]
    probe = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json",
                            str(output)], check=True, capture_output=True, text=True, timeout=30)
    streams = json.loads(probe.stdout)["streams"]
    assert any(s["codec_type"] == "video" for s in streams)
    assert any(s["codec_type"] == "audio" for s in streams) is add_sound

    def video_hash(path):
        return subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0",
                               "-c:v", "copy", "-f", "hash", "-hash", "sha256", "-"],
                              check=True, capture_output=True, timeout=30).stdout

    assert video_hash(output) == video_hash(original)
