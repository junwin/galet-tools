from __future__ import annotations

import pytest

from galet_tools import discovery
from galet_tools.framework import HandlerRegistry, HandlerV2


class ExampleHandler(HandlerV2):
    def __init__(self, config) -> None:
        self.config = config

    @classmethod
    def name(cls) -> str:
        return "example"

    @classmethod
    def tool_def(cls) -> dict:
        return {
            "type": "function",
            "name": cls.name(),
            "description": "Example discovered handler",
            "parameters": {"type": "object", "properties": {}},
        }

    def execute(
        self,
        args: dict,
        *,
        account_name: str = "auto",
        **context,
    ) -> dict:
        return {"ok": True}


class FakeEntryPoint:
    def __init__(self, name: str, value: str, loaded) -> None:
        self.name = name
        self.value = value
        self._loaded = loaded

    def load(self):
        if isinstance(self._loaded, BaseException):
            raise self._loaded
        return self._loaded


class FakeEntryPoints(list):
    def select(self, *, group: str):
        assert group == discovery.ENTRY_POINT_GROUP
        return self


def test_registers_discovered_plugins_in_stable_order(monkeypatch) -> None:
    calls: list[str] = []

    def register_example(registry: HandlerRegistry) -> None:
        calls.append("register")
        registry.register(ExampleHandler)

    points = FakeEntryPoints(
        [
            FakeEntryPoint(
                "z-last",
                "pkg_z:register",
                lambda registry: calls.append("z"),
            ),
            FakeEntryPoint(
                "example",
                "pkg_example:register",
                register_example,
            ),
        ]
    )
    monkeypatch.setattr(discovery, "entry_points", lambda: points)

    registry = HandlerRegistry()
    loaded = discovery.register_installed_handlers(registry)

    assert loaded == ["example", "z-last"]
    assert calls == ["register", "z"]
    assert registry.has_tool("example")


def test_rejects_non_callable_entry_point(monkeypatch) -> None:
    points = FakeEntryPoints(
        [FakeEntryPoint("bad", "bad_pkg:value", object())]
    )
    monkeypatch.setattr(discovery, "entry_points", lambda: points)

    with pytest.raises(discovery.HandlerPluginError, match="callable registrar"):
        discovery.register_installed_handlers(HandlerRegistry())


def test_reports_plugin_load_failure(monkeypatch) -> None:
    points = FakeEntryPoints(
        [
            FakeEntryPoint(
                "broken",
                "broken_pkg:register",
                ImportError("missing"),
            )
        ]
    )
    monkeypatch.setattr(discovery, "entry_points", lambda: points)

    with pytest.raises(discovery.HandlerPluginError, match="broken") as error:
        discovery.register_installed_handlers(HandlerRegistry())

    assert isinstance(error.value.__cause__, ImportError)


def test_reports_registration_failure(monkeypatch) -> None:
    def fail(_registry: HandlerRegistry) -> None:
        raise ValueError("duplicate")

    points = FakeEntryPoints(
        [FakeEntryPoint("broken", "broken_pkg:register", fail)]
    )
    monkeypatch.setattr(discovery, "entry_points", lambda: points)

    with pytest.raises(
        discovery.HandlerPluginError,
        match="during registration",
    ) as error:
        discovery.register_installed_handlers(HandlerRegistry())

    assert isinstance(error.value.__cause__, ValueError)
