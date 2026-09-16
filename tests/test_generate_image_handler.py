"""generate_image end-to-end with a fake ConfigProvider."""

from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from PIL import ImageFont

import galet_tools.tools.generate_image_handler as image_handler_module
from galet_tools.tools.generate_image_handler import GenerateImageHandler
from tests.conftest import FakeConfigProvider

_DEJAVU_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


@pytest.fixture
def handler() -> GenerateImageHandler:
    return GenerateImageHandler(FakeConfigProvider())


class TestSuccessfulGeneration:
    """Handler renders PNG data URIs with defaults and custom parameters."""

    def test_generates_image_with_defaults(self, handler: GenerateImageHandler) -> None:
        result = handler.execute({"description": "Hello World"})
        assert result["ok"] is True
        assert result["image"]["url"].startswith("data:image/png;base64,")
        assert result["image"]["alt"] == "Hello World"

    def test_custom_dimensions_and_color(self, handler: GenerateImageHandler) -> None:
        result = handler.execute({
            "description": "Custom",
            "width": 600,
            "height": 300,
            "color": "#ff0000",
        })
        assert result["ok"] is True
        assert result["image"]["url"].startswith("data:image/png;base64,")
        assert result["image"]["alt"] == "Custom"

    def test_empty_description_defaults(self, handler: GenerateImageHandler) -> None:
        result = handler.execute({"description": "   "})
        assert result["ok"] is True
        assert result["image"]["alt"] == "Generated image"

    def test_result_is_valid_base64_png(self, handler: GenerateImageHandler) -> None:
        result = handler.execute({"description": "Test"})
        b64_data = result["image"]["url"].split(",", 1)[1]
        decoded = base64.b64decode(b64_data)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


class TestToolDefinition:
    """tool_def and result_schema expose the expected fields."""

    def test_tool_def_has_required_fields(self, handler: GenerateImageHandler) -> None:
        td = handler.tool_def()
        assert td["name"] == "generate_image"
        assert td["type"] == "function"
        assert "description" in td["parameters"]["properties"]
        assert "width" in td["parameters"]["properties"]
        assert "height" in td["parameters"]["properties"]
        assert "color" in td["parameters"]["properties"]

    def test_result_schema_has_image_field(self, handler: GenerateImageHandler) -> None:
        rs = handler.result_schema()
        assert "image" in rs["properties"]
        assert "ok" in rs["properties"]


class TestConfiguredFonts:
    """Font paths come from the ConfigProvider port; empty list falls back."""

    def test_empty_font_list_falls_back_to_default_font(self, handler: GenerateImageHandler) -> None:
        result = handler.execute({"description": "fallback"})
        assert result["ok"] is True
        assert result["image"]["url"].startswith("data:image/png;base64,")

    def test_configured_font_path_is_attempted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts: list[tuple[Any, int]] = []
        real_truetype = ImageFont.truetype
        font_file = tmp_path / "custom.ttf"

        def spy(font: Any, size: int, *args: Any, **kwargs: Any) -> object:
            attempts.append((font, size))
            return real_truetype(font, size=size, *args, **kwargs)

        monkeypatch.setattr(image_handler_module.ImageFont, "truetype", spy)
        custom_handler = GenerateImageHandler(FakeConfigProvider([str(font_file)]))

        result = custom_handler.execute({"description": "font attempt"})

        assert result["ok"] is True
        assert attempts[0] == (str(font_file), 20)

    @pytest.mark.skipif(not os.path.exists(_DEJAVU_FONT), reason="no system TrueType font available")
    def test_image_renders_with_real_configured_font(self, tmp_path: Path) -> None:
        font_file = tmp_path / "DejaVuSans.ttf"
        shutil.copy(_DEJAVU_FONT, font_file)
        custom_handler = GenerateImageHandler(FakeConfigProvider([str(font_file)]))

        result = custom_handler.execute({"description": "Real font", "width": 300, "height": 150})

        assert result["ok"] is True
        b64_data = result["image"]["url"].split(",", 1)[1]
        assert base64.b64decode(b64_data)[:8] == b"\x89PNG\r\n\x1a\n"
