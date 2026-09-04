"""generate_svg input validation, sanitization, and handler execution."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from galet_tools.tools.generate_svg_handler import (
    ALLOWED_ELEMENTS,
    MAX_SVG_CHARS,
    GenerateSvgHandler,
    GenerateSvgInput,
    SvgSanitizer,
)


@pytest.fixture
def handler() -> GenerateSvgHandler:
    return GenerateSvgHandler()


@pytest.fixture
def sanitizer() -> SvgSanitizer:
    return SvgSanitizer()


class TestInputValidation:
    """GenerateSvgInput bounds and required fields."""

    def test_valid_minimal_input(self) -> None:
        inp = GenerateSvgInput.model_validate({
            "svg_code": "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        })
        assert inp.svg_code == "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
        assert inp.width == 400
        assert inp.height == 200

    def test_missing_svg_code_rejected(self) -> None:
        with pytest.raises(Exception):
            GenerateSvgInput.model_validate({})

    def test_width_below_min_rejected(self) -> None:
        with pytest.raises(Exception):
            GenerateSvgInput.model_validate({"svg_code": "<svg></svg>", "width": 10})

    def test_width_above_max_rejected(self) -> None:
        with pytest.raises(Exception):
            GenerateSvgInput.model_validate({"svg_code": "<svg></svg>", "width": 2000})

    def test_height_below_min_rejected(self) -> None:
        with pytest.raises(Exception):
            GenerateSvgInput.model_validate({"svg_code": "<svg></svg>", "height": 10})

    def test_height_above_max_rejected(self) -> None:
        with pytest.raises(Exception):
            GenerateSvgInput.model_validate({"svg_code": "<svg></svg>", "height": 2000})


class TestSanitization:
    """Sanitizer strips disallowed elements, attributes, and handlers."""

    def test_valid_svg_passes_through(self, sanitizer: SvgSanitizer) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="40" fill="red"/>
</svg>"""
        result = sanitizer.sanitize(svg)
        assert "circle" in result
        assert 'fill="red"' in result

    def test_script_element_stripped(self, sanitizer: SvgSanitizer) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg">
  <script>alert('xss')</script>
  <rect x="0" y="0" width="10" height="10"/>
</svg>"""
        result = sanitizer.sanitize(svg)
        assert "script" not in result
        assert "alert" not in result
        assert "rect" in result

    def test_onclick_handler_stripped(self, sanitizer: SvgSanitizer) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="40" onclick="evil()" fill="blue"/>
</svg>"""
        result = sanitizer.sanitize(svg)
        assert "onclick" not in result
        assert "fill" in result

    def test_foreign_object_stripped(self, sanitizer: SvgSanitizer) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg">
  <foreignObject><body>bad</body></foreignObject>
  <rect x="0" y="0" width="10" height="10"/>
</svg>"""
        result = sanitizer.sanitize(svg)
        assert "foreignObject" not in result
        assert "bad" not in result
        assert "rect" in result

    def test_onerror_stripped(self, sanitizer: SvgSanitizer) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg">
  <image href="x" onerror="alert(1)"/>
</svg>"""
        result = sanitizer.sanitize(svg)
        assert "onerror" not in result

    def test_namespace_preserved(self, sanitizer: SvgSanitizer) -> None:
        svg = """<svg viewBox="0 0 100 100">
  <rect width="100" height="100"/>
</svg>"""
        result = sanitizer.sanitize(svg)
        assert "svg" in result
        assert "rect" in result

    def test_all_whitelisted_elements_preserved(self, sanitizer: SvgSanitizer) -> None:
        for elem in sorted(ALLOWED_ELEMENTS):
            if elem == "svg":
                continue
            svg = f'<svg xmlns="http://www.w3.org/2000/svg"><{elem}/></svg>'
            result = sanitizer.sanitize(svg)
            assert elem in result

    def test_disallowed_elements_stripped(self, sanitizer: SvgSanitizer) -> None:
        disallowed = ["script", "foreignObject", "iframe", "embed", "object"]
        for elem in disallowed:
            svg = f'<svg xmlns="http://www.w3.org/2000/svg"><{elem}>bad</{elem}><rect/></svg>'
            result = sanitizer.sanitize(svg)
            assert elem not in result


class TestParseErrors:
    """Malformed XML and non-svg roots are rejected."""

    def test_malformed_xml_rejected(self) -> None:
        with pytest.raises(ET.ParseError):
            ET.fromstring("not xml <<<")

    def test_non_svg_root_rejected(self, sanitizer: SvgSanitizer) -> None:
        with pytest.raises(ValueError, match="Root element must be <svg>"):
            sanitizer.sanitize("<html><body>not svg</body></html>")


class TestHandlerExecute:
    """Handler.execute validates, sanitizes, and returns clean SVG."""

    def test_successful_generation(self, handler: GenerateSvgHandler) -> None:
        result = handler.execute({
            "svg_code": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="40" fill="red"/>
</svg>""",
            "description": "A red circle",
            "width": 400,
            "height": 200,
        })
        assert result["ok"] is True
        assert "svg" in result
        assert result["svg"]["markup"]
        assert result["svg"]["alt"] == "A red circle"
        assert result["svg"]["width"] == 400
        assert result["svg"]["height"] == 200
        assert "image" in result
        assert result["image"]["url"].startswith("data:image/svg+xml;base64,")

    def test_empty_svg_code_rejected(self, handler: GenerateSvgHandler) -> None:
        result = handler.execute({"svg_code": "   "})
        assert result["ok"] is False
        assert "empty" in result["error"].lower()

    def test_oversized_svg_rejected(self, handler: GenerateSvgHandler) -> None:
        huge = "<svg>" + (" " * (MAX_SVG_CHARS + 10)) + "</svg>"
        result = handler.execute({"svg_code": huge})
        assert result["ok"] is False
        assert "too large" in result["error"].lower()

    def test_invalid_svg_xml_rejected(self, handler: GenerateSvgHandler) -> None:
        result = handler.execute({"svg_code": "not xml <<<"})
        assert result["ok"] is False
        assert "Invalid SVG" in result["error"] or "well-formed" in result["error"].lower()

    def test_xss_sanitized_in_handler(self, handler: GenerateSvgHandler) -> None:
        result = handler.execute({
            "svg_code": """<svg xmlns="http://www.w3.org/2000/svg">
  <script>alert('xss')</script>
  <circle cx="50" cy="50" r="40" fill="green"/>
</svg>""",
        })
        assert result["ok"] is True
        assert "script" not in result["svg"]["markup"]
        assert "alert" not in result["svg"]["markup"]
        assert "circle" in result["svg"]["markup"]

    def test_result_is_valid_json(self, handler: GenerateSvgHandler) -> None:
        result = handler.execute({"svg_code": "<svg xmlns='http://www.w3.org/2000/svg'></svg>"})
        parsed = json.loads(json.dumps(result))
        assert parsed["ok"] is True
