from __future__ import annotations

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.tools.command_execution_handler2 import CommandExecutionHandler2
from galet_tools.tools.execute_command2 import ExecuteCommand2
from galet_tools.tools.file_load_handler2 import FileLoadHandler2
from galet_tools.tools.file_save_handler import FileSaveHandler2
from galet_tools.tools.image_generate_handler import ImageGenerateHandler
from galet_tools.tools.generate_svg_handler import GenerateSvgHandler
from galet_tools.tools.patch_apply_handler import PatchApplyHandler2
from galet_tools.tools.text_replace_handler import TextReplaceHandler
from galet_tools.tools.repo_index_handler import RepoIndexHandler
from galet_tools.tools.repo_search_handler import RepoSearchHandler
from galet_tools.tools.video_generate_handler import VideoGenerateHandler
from galet_tools.tools.semantic_memory_handler import SemanticMemoryHandler
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler
from galet_tools.tools.procedural_memory_handler import ProceduralMemoryHandler


def register_generic_defaults(reg: HandlerRegistry) -> None:
    """Register the generic tool handlers on `reg`."""
    reg.register(FileLoadHandler2)
    reg.register(FileSaveHandler2)
    reg.register(PatchApplyHandler2)
    reg.register(TextReplaceHandler)
    reg.register(CommandExecutionHandler2)
    reg.register(ExecuteCommand2)
    reg.register(RepoSearchHandler)
    reg.register(RepoIndexHandler)
    reg.register(GenerateSvgHandler)
    reg.register(ImageGenerateHandler)
    reg.register(VideoGenerateHandler)
    # Memory backends are supplied by execute context or an explicit host factory.
    reg.register(SemanticMemoryHandler, factory=lambda config: SemanticMemoryHandler())
    reg.register(EpisodicMemoryHandler, factory=lambda config: EpisodicMemoryHandler())
    reg.register(ProceduralMemoryHandler, factory=lambda config: ProceduralMemoryHandler())
