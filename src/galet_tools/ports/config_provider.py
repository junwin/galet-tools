from __future__ import annotations

from typing import Protocol


class ConfigProvider(Protocol):
    """Provides the host configuration generate_image needs to render text.

    generate_image keeps no config reads today; its only host dependency is
    the hardcoded Linux TrueType font path list in _render_image. The port
    exists so that list becomes host-provided when the handler moves.
    """

    def truetype_font_paths(self) -> list[str]:
        """Return candidate TrueType font file paths in preference order.

        The handler tries each path with ImageFont.truetype and falls back to
        Pillow's default font when none load, so an empty list is safe.
        """
        ...
