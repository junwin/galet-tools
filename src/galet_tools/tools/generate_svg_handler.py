"""Generate_svg tool: validate and sanitize SVG markup from the LLM.

Parses the markup with xml.etree, strips disallowed elements, attributes
and event handlers, and returns clean markup plus a base64 data URI.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Set
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from galet_tools.framework.handler_v2 import HandlerV2

logger = logging.getLogger(__name__)

SVG_NAMESPACE = "http://www.w3.org/2000/svg"

ALLOWED_ELEMENTS: Set[str] = {
    "svg",
    "g",
    "circle",
    "ellipse",
    "rect",
    "line",
    "polyline",
    "polygon",
    "path",
    "text",
    "defs",
    "linearGradient",
    "radialGradient",
    "stop",
    "use",
    "clipPath",
    "mask",
    "pattern",
    "filter",
    "feColorMatrix",
}

ALLOWED_ATTRIBUTES: Set[str] = {
    "id",
    "class",
    "fill",
    "stroke",
    "stroke-width",
    "opacity",
    "transform",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "x",
    "y",
    "width",
    "height",
    "d",
    "points",
    "viewBox",
    "font-family",
    "font-size",
    "text-anchor",
    "dominant-baseline",
    "style",
    "xmlns",
    "version",
}

FORBIDDEN_ATTR_PREFIXES: tuple[str, ...] = ("on",)

MAX_SVG_CHARS = 50000


class GenerateSvgInput(BaseModel):
    """Validated input for the generate_svg tool."""

    svg_code: str = Field(
        ...,
        description="Complete SVG markup to validate and sanitize.",
    )
    description: str = Field(
        default="",
        description="What the SVG depicts. Used as alt text.",
    )
    width: int = Field(
        default=400,
        ge=50,
        le=1200,
        description="Canvas width in pixels.",
    )
    height: int = Field(
        default=200,
        ge=50,
        le=1200,
        description="Canvas height in pixels.",
    )


class SvgSanitizer:
    """Walk an XML tree and strip disallowed elements and attributes."""

    def __init__(self) -> None:
        self._stripped_elements: int = 0
        self._stripped_attrs: int = 0

    def sanitize(self, raw_svg: str) -> str:
        """Parse, sanitize, and return a clean SVG string.

        Raises ValueError when the input is not well-formed XML.
        """
        self._stripped_elements = 0
        self._stripped_attrs = 0

        ET.register_namespace("", SVG_NAMESPACE)

        root = ET.fromstring(raw_svg.strip())

        tag = self._local_name(root.tag)
        if tag != "svg":
            raise ValueError(f"Root element must be <svg>, got <{tag}>")

        self._sanitize_element(root)

        if self._stripped_elements:
            logger.info(
                "generate_svg: stripped %d disallowed element(s)",
                self._stripped_elements,
            )
        if self._stripped_attrs:
            logger.info(
                "generate_svg: stripped %d disallowed attribute(s)",
                self._stripped_attrs,
            )

        return self._to_string(root)

    def _sanitize_element(self, elem: ET.Element) -> None:
        """Recursively sanitize an element and its children."""
        self._sanitize_attrs(elem)

        to_remove: List[ET.Element] = []
        for child in elem:
            child_tag = self._local_name(child.tag)
            if child_tag not in ALLOWED_ELEMENTS:
                to_remove.append(child)
            else:
                self._sanitize_element(child)

        for child in to_remove:
            self._stripped_elements += 1
            elem.remove(child)

    def _sanitize_attrs(self, elem: ET.Element) -> None:
        """Remove disallowed attributes from an element."""
        attrs_to_remove: List[str] = []
        for attr_name in elem.attrib:
            if not self._attr_allowed(attr_name):
                attrs_to_remove.append(attr_name)

        for name in attrs_to_remove:
            self._stripped_attrs += 1
            del elem.attrib[name]

    def _attr_allowed(self, name: str) -> bool:
        """Return True when the attribute is permitted."""
        local = name.split("}")[-1] if "}" in name else name
        local = local.split(":")[-1] if ":" in local else local

        if local.startswith(FORBIDDEN_ATTR_PREFIXES):
            return False

        if local in ALLOWED_ATTRIBUTES:
            return True

        return False

    @staticmethod
    def _local_name(tag: str) -> str:
        """Extract the local name from a namespaced tag."""
        tag = tag.split("}")[-1] if "}" in tag else tag
        tag = tag.split(":")[-1] if ":" in tag else tag
        return tag

    @staticmethod
    def _to_string(root: ET.Element) -> str:
        return ET.tostring(root, encoding="unicode", xml_declaration=False)


class GenerateSvgHandler(HandlerV2):
    """Handler that validates and sanitizes SVG markup from the LLM."""

    NAME = "generate_svg"

    def __init__(self) -> None:
        self._sanitizer = SvgSanitizer()

    @classmethod
    def name(cls) -> str:
        return cls.NAME

    @classmethod
    def tool_def(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": cls.NAME,
            "description": (
                "Generate an SVG image and return clean, sanitized SVG markup. "
                "You must provide the full SVG markup as the svg_code argument. "
                "Use the description to explain what the image depicts. "
                "The SVG will be validated and sanitized — scripts, event handlers, "
                "and foreign objects are stripped automatically. "
                "The returned SVG can be rendered safely in the browser."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "svg_code": {
                        "type": "string",
                        "description": (
                            "Complete SVG markup as a string. Must be valid XML "
                            "with an <svg> root element. Include xmlns and viewBox attributes."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "What the SVG depicts. Used as alt text in the UI.",
                    },
                    "width": {
                        "type": "integer",
                        "description": "Canvas width in pixels (default 400).",
                        "default": 400,
                    },
                    "height": {
                        "type": "integer",
                        "description": "Canvas height in pixels (default 200).",
                        "default": 200,
                    },
                },
                "required": ["svg_code", "description", "width", "height"],
                "additionalProperties": False,
            },
            "strict": True,
        }

    @classmethod
    def result_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "svg": {
                    "type": "object",
                    "properties": {
                        "markup": {"type": "string"},
                        "alt": {"type": "string"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["markup", "alt", "width", "height"],
                    "additionalProperties": False,
                },
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
            "required": ["svg", "ok"],
            "additionalProperties": False,
        }

    def execute(
        self,
        args: Dict[str, Any],
        *,
        account_name: str = "auto",
        **context,
    ) -> Dict[str, Any]:
        try:
            validated = GenerateSvgInput.model_validate(args)
        except Exception as e:
            logger.warning("generate_svg: input validation failed: %s", e)
            return {
                "ok": False,
                "error": f"Invalid input: {e}",
            }

        svg_code = validated.svg_code.strip()
        if not svg_code:
            return {
                "ok": False,
                "error": "svg_code must not be empty.",
            }

        if len(svg_code) > MAX_SVG_CHARS:
            return {
                "ok": False,
                "error": (
                    f"SVG code too large: {len(svg_code)} chars "
                    f"(limit {MAX_SVG_CHARS})."
                ),
            }

        try:
            clean = self._sanitizer.sanitize(svg_code)
        except ET.ParseError as e:
            logger.warning("generate_svg: XML parse error: %s", e)
            return {
                "ok": False,
                "error": f"Invalid SVG — not well-formed XML: {e}",
            }
        except ValueError as e:
            logger.warning("generate_svg: sanitization error: %s", e)
            return {
                "ok": False,
                "error": str(e),
            }

        description = validated.description or "SVG image"

        b64 = base64.b64encode(clean.encode("utf-8")).decode("ascii")
        data_uri = f"data:image/svg+xml;base64,{b64}"

        logger.info(
            "generate_svg: ok input_len=%d output_len=%d desc=%r",
            len(svg_code),
            len(clean),
            description[:80],
        )

        return {
            "ok": True,
            "svg": {
                "markup": clean,
                "alt": description,
                "width": validated.width,
                "height": validated.height,
            },
            "image": {
                "url": data_uri,
                "alt": description,
            },
        }
