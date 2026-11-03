"""Host integration coverage for automatic built-in composition (Lucy #258)."""
from __future__ import annotations

from types import SimpleNamespace
import subprocess
import sys

import pytest

from galet_tools import HandlerRegistry, HandlerServices, MissingHandlerServiceError
from galet_tools import register_builtin_handlers
from galet_tools import composition
from galet_tools.composition import BuiltinHandler
from galet_tools.framework.handler_v2 import HandlerV2
from tests.conftest import FakeStorageResolver, FakeSandboxResolver, FakeSecurityPolicy


class NewGenericHandler(HandlerV2):
    def __init__(self, storage_resolver):
        self.storage = storage_resolver

    @classmethod
    def name(cls):
        return "new_generic_tool"

    @classmethod
    def tool_def(cls):
        return {"type": "function", "name": cls.name(), "description": "Future package tool",
                "parameters": {"type": "object", "properties": {}}}

    def execute(self, args, **context):
        return {"ok": True, "root": self.storage.storage_base_dir()}


class HostFileLoad(NewGenericHandler):
    @classmethod
    def name(cls):
        return "file_load"


def test_future_package_tool_and_host_collision(monkeypatch, tmp_path):
    """A host calls one registrar and never imports the new handler class."""
    original = composition.builtin_handlers
    new_spec = BuiltinHandler(__name__ + ":NewGenericHandler", ("storage_resolver",),
                              (("storage_resolver", "storage_resolver"),))
    monkeypatch.setattr(composition, "builtin_handlers", lambda: (*original(), new_spec))
    registry = HandlerRegistry()
    host_instance = object()
    registry.register(HostFileLoad, factory=lambda config: host_instance)
    storage = FakeStorageResolver(str(tmp_path))
    configs = []

    def host_services(config):
        configs.append(config)
        return HandlerServices(storage_resolver=storage)

    report = register_builtin_handlers(registry, services=host_services)
    assert configs == []  # Discovery must not construct backends.
    assert report.preserved == ("file_load",)
    assert "new_generic_tool" in report.registered
    assert registry.create("file_load", config={}) is host_instance
    config = object()
    handler = registry.create("new_generic_tool", config=config)
    assert configs == [config]
    assert handler.execute({}) == {"ok": True, "root": storage.storage_base_dir()}
    assert "new_generic_tool" in {tool["name"] for tool in registry.tools()}
    # Discovery does not grant agent or context permissions.
    assert registry.eligible_tool_names(SimpleNamespace(allowed_tools=[])) == []
    agent = SimpleNamespace(name="tester", allowed_tools=["new_generic_tool"])
    assert registry.eligible_tool_names(agent) == ["new_generic_tool"]
    context = SimpleNamespace(extra={"allowed_tools": ["file_load"]})
    assert registry.eligible_tool_names(agent, context) == []
    second = register_builtin_handlers(registry, services=host_services)
    assert not second.registered
    assert set(second.preserved) == set(registry.tool_names())


def test_real_constructor_ports_and_no_arg_handler(tmp_path):
    storage = FakeStorageResolver(str(tmp_path))
    sandbox = FakeSandboxResolver(str(tmp_path))
    security = FakeSecurityPolicy(allowed=False)
    registry = HandlerRegistry()
    report = register_builtin_handlers(registry, services=HandlerServices(
        storage_resolver=storage, sandbox_resolver=sandbox, security_policy=security))
    assert report.unavailable == {}
    registry.create("generate_svg", config=None)  # No config constructor parameter.
    saved = registry.create("file_save", config=None).execute({
        "location": "storage", "external_root": "", "path": "example.txt",
        "file_content": "composed", "overwrite": True})
    assert saved["ok"]
    loaded = registry.create("file_load", config=None).execute({
        "location": "storage", "external_root": "", "path": "example.txt"})
    assert loaded["result"] == "composed"
    command = registry.create("execute_command2", config=None)
    result = command.execute({"mode": "process", "executable": "echo",
                              "arguments": ["test"], "location": "sandbox"})
    assert result["ok"] is False
    assert security.execution_calls


def test_missing_required_ports_are_named_at_creation():
    registry = HandlerRegistry()
    register_builtin_handlers(registry)
    assert registry.has_tool("execute_command2")
    with pytest.raises(MissingHandlerServiceError, match="execute_command2.*storage_resolver.*sandbox_resolver.*security_policy"):
        registry.create("execute_command2", config=None)
    # Missing backend leaves unrelated tools usable and gives a clear tool error.
    registry.create("generate_svg", config=None)
    result = registry.create("procedural_memory", config=None).execute({"action": "list_contexts"})
    assert result["ok"] is False
    assert "procedural_memory not available" in result["error"]


def test_memory_backends_and_execution_context_share_host_instances():
    class Episodic:
        def list_sessions(self, **kwargs):
            return SimpleNamespace(items=[], next_cursor=None)

    class Repository:
        def list_resolved_context_names(self, account, **kwargs):
            return [account]

    episodic = Episodic()
    procedural = SimpleNamespace(repository=Repository())
    semantic = object()
    services = HandlerServices(episodic_store=episodic, procedural_memory=procedural,
                               semantic_memory=semantic)
    registry = HandlerRegistry()
    register_builtin_handlers(registry, services=services)
    assert services.execution_context() == {
        "episodic_store": episodic, "procedural_memory": procedural, "semantic_memory": semantic}
    for tool, backend in (("episodic_memory", episodic), ("procedural_memory", procedural),
                          ("semantic_memory", semantic), ("episodic_list_sessions", episodic)):
        assert registry.create(tool, config=None).memory is backend
    assert registry.create("episodic_list_sessions", config=None).execute(
        {}, account_name="john")["ok"]
    # A host can supply request-scoped services instead of binding them at startup.
    contextual = HandlerRegistry()
    register_builtin_handlers(contextual)
    result = contextual.create("procedural_memory", config=None).execute(
        {"action": "list_contexts"}, account_name="john", **services.execution_context())
    assert result["context_names"] == ["john"]
    result = contextual.create("episodic_list_sessions", config=None).execute(
        {}, account_name="john", **services.execution_context())
    assert result["ok"]


def test_strict_collisions_and_manifest_duplicates_fail(monkeypatch):
    registry = HandlerRegistry()
    register_builtin_handlers(registry)
    with pytest.raises(ValueError, match="Duplicate handler name"):
        register_builtin_handlers(registry, collision="error")
    with pytest.raises(ValueError, match="collision policy"):
        register_builtin_handlers(HandlerRegistry(), collision="replace")
    spec = BuiltinHandler(__name__ + ":NewGenericHandler")
    monkeypatch.setattr(composition, "builtin_handlers", lambda: (spec, spec))
    with pytest.raises(ValueError, match="Duplicate built-in"):
        register_builtin_handlers(HandlerRegistry())


def test_optional_missing_import_is_reported_but_internal_faults_fail(monkeypatch, caplog):
    missing = BuiltinHandler("missing_package.handler:Handler", optional_modules=("missing_package",))
    good = BuiltinHandler("galet_tools.tools.generate_svg_handler:GenerateSvgHandler")
    monkeypatch.setattr(composition, "builtin_handlers", lambda: (missing, good))
    registry = HandlerRegistry()
    report = register_builtin_handlers(registry)
    assert report.registered == ("generate_svg",)
    assert "missing_package" in report.unavailable[missing.reference]
    assert "optional dependency" in caplog.text
    # Programming errors must never masquerade as unavailable optional extras.
    monkeypatch.setattr(composition, "builtin_handlers", lambda: (
        BuiltinHandler("internal_typo.handler:Handler", optional_modules=("galet_memory",)),))
    with pytest.raises(ModuleNotFoundError, match="internal_typo"):
        register_builtin_handlers(HandlerRegistry())


def test_discovery_does_not_import_optional_runtimes():
    subprocess.run([sys.executable, "-c", """
import sys
from galet_tools import HandlerRegistry, register_builtin_handlers
register_builtin_handlers(HandlerRegistry())
assert not any(name == root or name.startswith(root + '.')
               for name in sys.modules for root in ('galet', 'galet_memory', 'mcp'))
"""], check=True)


def test_invalid_service_provider_fails_at_creation():
    registry = HandlerRegistry()
    register_builtin_handlers(registry, services=lambda config: None)
    with pytest.raises(TypeError, match="must return HandlerServices"):
        registry.create("generate_svg", config=None)
