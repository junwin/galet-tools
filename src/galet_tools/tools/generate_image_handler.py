"""Generate_image tool: render simple images and return them as base64.

Creates an image (colored rectangle with the description rendered as text)
and returns it as a PNG data URI.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict

from PIL import Image, ImageDraw, ImageFont

from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.config_provider import ConfigProvider

logger = logging.getLogger(__name__)


class GenerateImageHandler(HandlerV2):
    """Handler that generates simple images and returns them as base64 data URIs."""

    NAME = "generate_image"

    def __init__(self, config: ConfigProvider) -> None:
        self._config = config

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Generate a simple image or diagram and return it as a base64-encoded "
                "PNG data URI. Use this to create visual illustrations, charts, or "
                "diagrams. The image is returned inline and displayed to the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What to draw or illustrate. This text is rendered on the image.",
                    },
                    "width": {
                        "type": "integer",
                        "description": "Image width in pixels (default 400).",
                        "default": 400,
                    },
                    "height": {
                        "type": "integer",
                        "description": "Image height in pixels (default 200).",
                        "default": 200,
                    },
                    "color": {
                        "type": "string",
                        "description": "Background color as a CSS color name or hex (default '#1e3a5f').",
                        "default": "#1e3a5f",
                    },
                },
                "required": ["description", "width", "height", "color"],
                "additionalProperties": False,
            },
            "strict": True,
        }

    @classmethod
    def result_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "alt": {"type": "string"},
                    },
                    "required": ["url", "alt"],
                    "additionalProperties": False,
                },
                "ok": {"type": "boolean"},
            },
            "required": ["image", "ok"],
            "additionalProperties": False,
        }

    def _render_image(self, description: str, width: int, height: int, bg_color: str) -> bytes:
        """Create a PNG image with the description rendered as text."""
        img = Image.new("RGB", (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)

        font = None
        font_paths = self._config.truetype_font_paths()
        for fp in font_paths:
            try:
                font = ImageFont.truetype(fp, size=20)
                break
            except (OSError, IOError):
                continue

        if font is None:
            logger.debug("generate_image: no TrueType font found, using default")
            font = ImageFont.load_default()

        max_chars_per_line = max(1, width // (font.getbbox("x")[2] if hasattr(font, "getbbox") else 10))
        lines = self._wrap_text(description, max_chars_per_line)

        line_height = 28
        total_text_height = len(lines) * line_height
        y = (height - total_text_height) // 2

        text_color = "#ffffff"
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (width - text_width) // 2
            draw.text((x, y), line, fill=text_color, font=font)
            y += line_height

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        """Split text into lines not exceeding max_chars."""
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            if current_line:
                candidate = current_line + " " + word
            else:
                candidate = word

            if len(candidate) <= max_chars:
                current_line = candidate
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word if len(word) <= max_chars else word[:max_chars]

        if current_line:
            lines.append(current_line)

        return lines if lines else [text[:max_chars]]

    def execute(self, args: Dict[str, Any], *, account_name: str = "auto", **context) -> Dict[str, Any]:
        description = str(args.get("description", "Generated image")).strip()
        if not description:
            description = "Generated image"

        width = max(100, min(1200, int(args.get("width", 400))))
        height = max(50, min(800, int(args.get("height", 200))))
        color_raw = str(args.get("color", "#1e3a5f")).strip()

        logger.info(
            "generate_image: description=%r width=%d height=%d color=%r",
            description[:80],
            width,
            height,
            color_raw,
        )

        try:
            png_bytes = self._render_image(description, width, height, color_raw)
        except Exception:
            logger.exception("generate_image: image rendering failed")
            return {
                "ok": False,
                "error": "Failed to generate image. Check the parameters.",
            }

        b64 = base64.b64encode(png_bytes).decode("ascii")

        return {
            "ok": True,
            "image": {
                "url": f"data:image/png;base64,{b64}",
                "alt": description,
            },
        }
