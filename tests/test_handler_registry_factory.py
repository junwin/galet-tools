from __future__ import annotations

from galet_tools.framework import HandlerRegistry, HandlerV2


class MultiPortHandler(HandlerV2):
    def __init__(self, first, second) -> None:
        self.first = first
        self.second = second

    @classmethod
    def name(cls) -> str:
        return "multi_port"

    @classmethod
    def tool_def(cls) -> dict:
        return {
            "type": "function",
            "name": cls.name(),
            "description": "A handler with two narrow dependencies",
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


def test_factory_constructs_handler_from_host_config() -> None:
    registry = HandlerRegistry()
    registry.register(
        MultiPortHandler,
        factory=lambda config: MultiPortHandler(
            config["first"],
            config["second"],
        ),
    )

    handler = registry.create(
        "multi_port",
        config={"first": "one", "second": "two"},
    )

    assert isinstance(handler, MultiPortHandler)
    assert handler.first == "one"
    assert handler.second == "two"


def test_default_single_config_constructor_is_unchanged() -> None:
    class ConfigHandler(MultiPortHandler):
        def __init__(self, config) -> None:
            self.config = config

        @classmethod
        def name(cls) -> str:
            return "config_handler"

    registry = HandlerRegistry()
    registry.register(ConfigHandler)
    config = object()

    handler = registry.create("config_handler", config=config)

    assert handler.config is config
