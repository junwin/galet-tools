"""Host-neutral composition of the package's supported built-in handlers."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
import logging
from typing import Any, Callable, Literal

from galet_tools.framework.handler_registry import HandlerRegistry
from galet_tools.framework.handler_v2 import HandlerV2
from galet_tools.ports.sandbox_root_resolver import SandboxRootResolver
from galet_tools.ports.security_policy import SecurityPolicy
from galet_tools.ports.storage_location_resolver import StorageLocationResolver

logger = logging.getLogger(__name__)


class MissingHandlerServiceError(RuntimeError):
    """A host tried to construct a tool without its required service ports."""


@dataclass(frozen=True)
class HandlerServices:
    """Host-owned ports and backends; composition never creates or closes them.

    Memory services may instead be supplied per call using execution_context().
    No account, permissions, configuration files or credentials are inferred.
    """

    storage_resolver: StorageLocationResolver | None = None
    sandbox_resolver: SandboxRootResolver | None = None
    security_policy: SecurityPolicy | None = None
    semantic_memory: Any = None
    episodic_store: Any = None
    procedural_memory: Any = None
    image_api: Any = None
    video_api: Any = None

    def execution_context(self) -> dict[str, Any]:
        """Return the memory keys consumed by handlers' execute(**context)."""
        return {key: value for key, value in (
            ("semantic_memory", self.semantic_memory),
            ("episodic_store", self.episodic_store),
            ("procedural_memory", self.procedural_memory),
        ) if value is not None}


@dataclass(frozen=True)
class BuiltinHandler:
    """A lazy class reference and explicit constructor-to-service bindings.

    Required ports fail clearly at creation. Optional services (notably memory)
    can arrive through the trusted execution context instead of the constructor.
    """

    reference: str
    required: tuple[str, ...] = ()
    bindings: tuple[tuple[str, str], ...] = ()
    optional_modules: tuple[str, ...] = ()

    def load(self) -> type[HandlerV2]:
        module, name = self.reference.split(":", 1)
        cls = getattr(import_module(module), name)
        if not isinstance(cls, type) or not issubclass(cls, HandlerV2):
            raise TypeError(f"Built-in {self.reference!r} must be a HandlerV2 class")
        return cls

    def create(self, cls: type[HandlerV2], services: HandlerServices) -> HandlerV2:
        missing = [key for key in self.required if getattr(services, key) is None]
        if missing:
            raise MissingHandlerServiceError(
                f"Cannot create handler {cls.name()!r}: missing host services: "
                + ", ".join(missing)
            )
        kwargs = {parameter: getattr(services, service)
                  for parameter, service in self.bindings}
        return cls(**kwargs)


def builtin_handlers() -> tuple[BuiltinHandler, ...]:
    """The package owns this manifest; hosts never enumerate individual tools."""
    prefix = "galet_tools.tools."
    storage = (("storage_resolver", "storage_resolver"),)
    command = storage + (("sandbox_resolver", "sandbox_resolver"),
                         ("security_policy", "security_policy"))
    specs = [
        BuiltinHandler(prefix + ref, ("storage_resolver",), storage)
        for ref in (
            "file_load_handler2:FileLoadHandler2", "file_save_handler:FileSaveHandler2",
            "patch_apply_handler:PatchApplyHandler2", "text_replace_handler:TextReplaceHandler",
            "repo_search_handler:RepoSearchHandler", "repo_index_handler:RepoIndexHandler",
        )
    ]
    specs.extend(BuiltinHandler(prefix + ref,
                               ("storage_resolver", "sandbox_resolver", "security_policy"), command)
                 for ref in ("command_execution_handler2:CommandExecutionHandler2",
                             "execute_command2:ExecuteCommand2"))
    specs.append(BuiltinHandler(prefix + "generate_svg_handler:GenerateSvgHandler"))
    for kind in ("image", "video"):
        specs.append(BuiltinHandler(
            prefix + f"{kind}_generate_handler:{kind.capitalize()}GenerateHandler",
            ("storage_resolver",), storage + ((f"{kind}_api", f"{kind}_api"),),
            optional_modules=("galet",),
        ))
    for kind, service in (("semantic", "semantic_memory"), ("episodic", "episodic_store"),
                          ("procedural", "procedural_memory")):
        specs.append(BuiltinHandler(
            prefix + f"{kind}_memory_handler:{kind.capitalize()}MemoryHandler",
            bindings=(("memory", service),), optional_modules=("galet_memory",),
        ))
    # This module only depends on the lightweight handler ABI, not galet-memory.
    from galet_tools.tools.episodic_operations import EPISODIC_OPERATION_HANDLERS
    specs.extend(BuiltinHandler(prefix + f"episodic_operations:{cls.__name__}",
                                bindings=(("memory", "episodic_store"),),
                                optional_modules=("galet_memory",))
                 for cls in EPISODIC_OPERATION_HANDLERS)
    return tuple(specs)


@dataclass(frozen=True)
class RegistrationReport:
    registered: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()
    unavailable: dict[str, str] = field(default_factory=dict)


ServiceProvider = HandlerServices | Callable[[Any], HandlerServices]


def register_builtin_handlers(
    registry: HandlerRegistry,
    *,
    services: ServiceProvider | None = None,
    collision: Literal["preserve", "error"] = "preserve",
) -> RegistrationReport:
    """Compose built-ins, preserving previously registered host factories.

    Register host adapters first. Existing names win by default; strict mode
    rejects collisions. Installed extensions remain a separate explicit step.
    Services are resolved on create(config=...), never during discovery. This
    function changes neither agent allowlists nor context permissions.
    """
    if collision not in ("preserve", "error"):
        raise ValueError(f"Unknown collision policy: {collision!r}")
    registered, preserved, unavailable = [], [], {}
    seen: set[str] = set()
    for spec in builtin_handlers():
        try:
            cls = spec.load()
        except ModuleNotFoundError as exc:
            if not any(exc.name == root or (exc.name or "").startswith(root + ".")
                       for root in spec.optional_modules):
                raise
            unavailable[spec.reference] = f"Optional dependency unavailable: {exc.name}"
            logger.warning("Skipping built-in %s: optional dependency %s unavailable",
                           spec.reference, exc.name)
            continue
        name = cls.name()
        if name in seen:
            raise ValueError(f"Duplicate built-in handler name: {name}")
        seen.add(name)
        if registry.has_tool(name):
            if collision == "error":
                raise ValueError(f"Duplicate handler name registered: {name}")
            preserved.append(name)
            continue

        def factory(config: Any, spec=spec, cls=cls) -> HandlerV2:
            resolved = services(config) if callable(services) else services
            if services is None:
                resolved = HandlerServices()
            if not isinstance(resolved, HandlerServices):
                raise TypeError("Host service provider must return HandlerServices")
            return spec.create(cls, resolved)

        registry.register(cls, factory=factory)
        registered.append(name)
    return RegistrationReport(tuple(registered), tuple(preserved), unavailable)
