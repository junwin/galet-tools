"""Shared memory assembly for MCP and application hosts such as Lucy.

Galet-memory owns config loading, storage assembly and credential delegation.
The host owns the returned runtime and closes it once on shutdown.
"""
from dataclasses import replace
import logging

MEMORY_TOOLS = frozenset({'semantic_memory', 'episodic_memory', 'procedural_memory'})
logger = logging.getLogger(__name__)


def build_configured_memory(path, tool_names, *, embedding_provider_factory=None):
    from galet_memory import build_memory, load_memory_config

    selected = set(tool_names) & MEMORY_TOOLS
    settings = load_memory_config(path=path)
    for tool in sorted(selected):
        kind = tool.removesuffix('_memory')
        if getattr(settings, kind) is None:
            raise ValueError(f'{tool} is allowed but memory config does not enable {kind}')
    # Tools cannot open stores outside the allowlist. Working state is internal
    # host infrastructure, enabled explicitly by the shared memory config.
    settings = replace(settings, **{
        kind: getattr(settings, kind) if kind + '_memory' in selected else None
        for kind in ('semantic', 'episodic', 'procedural')
    })
    runtime = build_memory(settings, embedding_provider_factory=embedding_provider_factory)
    logger.info('configured_memory_ready config=%s components=%s', path,
                ','.join(kind for kind in ('semantic', 'episodic', 'procedural', 'working')
                         if getattr(runtime, kind) is not None))
    if settings.semantic:
        profile = settings.embedding_profiles[settings.semantic.embedding_profile]
        logger.info('mcp_semantic_ready config=%s metadata_version=%s provider=%s model=%s dimensions=%s',
                    path, settings.semantic.metadata_version, profile.provider, profile.model, profile.dimensions)
    return runtime


def memory_handlers(runtime, tool_names):
    """Bind tools to one already-built runtime; ownership remains with the host."""
    from galet_tools.tools.semantic_memory_handler import SemanticMemoryHandler
    from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler
    from galet_tools.tools.procedural_memory_handler import ProceduralMemoryHandler

    selected = set(tool_names) & MEMORY_TOOLS
    handlers = {}
    for tool in sorted(selected):
        kind = tool.removesuffix('_memory')
        backend = getattr(runtime, kind)
        if backend is None:
            raise ValueError(f'{tool} requires an enabled {kind} backend')
        if tool == 'semantic_memory':
            profile = runtime.config.embedding_profiles[runtime.config.semantic.embedding_profile]
            handler = SemanticMemoryHandler(backend, embedding_model=profile.model)
        else:
            cls = EpisodicMemoryHandler if tool == 'episodic_memory' else ProceduralMemoryHandler
            handler = cls(backend)
        handlers[tool] = handler
    return handlers
