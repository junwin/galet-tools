from __future__ import annotations

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2
from galet_tools.tools.file_load_handler2 import FileLoadHandler2
from galet_tools.tools.file_save_handler import FileSaveHandler2
from galet_tools.tools.generate_image_handler import GenerateImageHandler
from galet_tools.tools.generate_svg_handler import GenerateSvgHandler


def register_generic_defaults(reg: HandlerRegistry) -> None:
    """Register the generic tool handlers on `reg`."""
    reg.register(FileLoadHandler2)
    reg.register(FileSaveHandler2)
    reg.register(CommandExecutionHandler2)
    reg.register(GenerateSvgHandler)
    reg.register(GenerateImageHandler)
