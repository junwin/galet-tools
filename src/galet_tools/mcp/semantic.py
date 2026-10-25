"""MCP semantic memory assembled from the shared galet-memory configuration."""
from dataclasses import replace

from galet_tools.tools.semantic_memory_handler import SemanticMemoryHandler


class ConfiguredSemanticHandler(SemanticMemoryHandler):
    def __init__(self, runtime):
        self.runtime = runtime
        settings = runtime.config
        profile = settings.embedding_profiles[settings.semantic.embedding_profile]
        super().__init__(runtime.semantic, embedding_model=profile.model)

    def close(self):
        self.runtime.close()


def build_semantic_handler(path):
    from galet_memory import build_memory, load_memory_config

    if not path:
        raise ValueError("semantic_memory requires memory_config_path")
    settings = load_memory_config(path=path)
    if settings.semantic is None:
        raise ValueError("memory config must enable semantic memory")
    # Other components are configured separately by MCP. Opening this tool must
    # not create or open the application's episodic, working or procedural stores.
    settings = replace(settings, episodic=None, procedural=None, working=None)
    return ConfiguredSemanticHandler(build_memory(settings))
