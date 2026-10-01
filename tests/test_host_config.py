"""Host config loading and validation tests (galet-mcp.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from galet_tools.host.config import (
    DEFAULT_ALLOWLIST,
    GaletConfig,
    GaletConfigError,
    load_config,
)

_MISSING = object()

REQUIRED_KEYS = ("account", "storage_root", "storage_namespace", "sandbox_root")
OPTIONAL_KEYS = ("allowlist", "external_roots", "host", "port", "fonts")


def _base(tmp_path: Path) -> dict:
    return {
        "account": "junwin",
        "allowlist": list(DEFAULT_ALLOWLIST),
        "storage_root": str(tmp_path / "lucy_storage"),
        "storage_namespace": "main",
        "external_roots": {},
        "sandbox_root": str(tmp_path / "sandbox"),
        "host": "127.0.0.1",
        "port": 8765,
        "fonts": [],
    }


def _write_config(tmp_path: Path, **overrides: object) -> Path:
    data = _base(tmp_path)
    for key, value in overrides.items():
        if value is _MISSING:
            data.pop(key, None)
        else:
            data[key] = value
    path = tmp_path / "galet-mcp.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestValidConfig:
    def test_every_value_preserved(self, tmp_path: Path) -> None:
        overrides = {
            "allowlist": ["file_load", "generate_svg"],
            "storage_root": str(tmp_path / "storage"),
            "storage_namespace": "prod",
            "external_roots": {"notes": str(tmp_path / "notes")},
            "host": "localhost",
            "port": 9000,
            "fonts": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
        }
        cfg = load_config(_write_config(tmp_path, **overrides))
        assert cfg.account == "junwin"
        assert cfg.allowlist == ["file_load", "generate_svg"]
        assert cfg.storage_root == str(tmp_path / "storage")
        assert cfg.storage_namespace == "prod"
        assert cfg.external_roots == {"notes": str(tmp_path / "notes")}
        assert cfg.sandbox_root == str(tmp_path / "sandbox")
        assert (cfg.host, cfg.port) == ("localhost", 9000)
        assert cfg.fonts == ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


class TestOptionalDefaults:
    def test_absent_keys_use_defaults(self, tmp_path: Path) -> None:
        path = _write_config(tmp_path, **{key: _MISSING for key in OPTIONAL_KEYS})
        self._assert_defaults(load_config(path))

    @pytest.mark.parametrize("key", OPTIONAL_KEYS)
    def test_explicit_null_uses_default(self, tmp_path: Path, key: str) -> None:
        self._assert_defaults(load_config(_write_config(tmp_path, **{key: None})))

    def _assert_defaults(self, cfg: GaletConfig) -> None:
        assert cfg.allowlist == DEFAULT_ALLOWLIST
        assert cfg.external_roots == {}
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8765
        assert cfg.fonts == []


class TestRequiredKeys:
    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    @pytest.mark.parametrize("value", [None, "", "   ", _MISSING])
    def test_null_blank_or_missing_raises(self, tmp_path, key, value) -> None:
        with pytest.raises(GaletConfigError, match="must be a non-empty string"):
            load_config(_write_config(tmp_path, **{key: value}))


class TestSchemaErrors:
    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(GaletConfigError, match="config file not found"):
            load_config(tmp_path / "galet-mcp.json")

    def test_invalid_json_raises(self, tmp_path) -> None:
        (tmp_path / "galet-mcp.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(GaletConfigError, match="is not valid JSON"):
            load_config(tmp_path / "galet-mcp.json")

    def test_non_object_json_raises(self, tmp_path) -> None:
        (tmp_path / "galet-mcp.json").write_text(json.dumps([1, 2]), encoding="utf-8")
        with pytest.raises(GaletConfigError, match="must contain a JSON object"):
            load_config(tmp_path / "galet-mcp.json")


class TestAllowlistFailClosed:
    @pytest.mark.parametrize(
        ("allowlist", "match"),
        [
            ("file_load", "must be a list of tool name strings"),
            ([1, 2], "must be a list of tool name strings"),
            (["file_load", "bogus_tool"], "contains unknown tool names"),
            (["execute_command"], "contains unknown tool names"),
            ([], "must not be empty"),
            (["   "], "must not be empty"),
        ],
    )
    def test_invalid_allowlist_raises(self, tmp_path, allowlist, match) -> None:
        path = _write_config(tmp_path, allowlist=allowlist)
        with pytest.raises(GaletConfigError, match=match):
            load_config(path)


class TestPathValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"storage_root": "relative/storage"},
            {"sandbox_root": "relative/sandbox"},
            {"external_roots": {"notes": "relative/notes"}},
        ],
    )
    def test_relative_path_rejected(self, tmp_path, overrides) -> None:
        with pytest.raises(GaletConfigError, match="must be an absolute path"):
            load_config(_write_config(tmp_path, **overrides))


class TestHostPortFonts:
    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
    def test_non_loopback_host_rejected(self, tmp_path, host) -> None:
        with pytest.raises(GaletConfigError, match="must be loopback only"):
            load_config(_write_config(tmp_path, host=host))

    @pytest.mark.parametrize("port", [0, 70000, "not-a-number", True])
    def test_invalid_port_rejected(self, tmp_path, port) -> None:
        path = _write_config(tmp_path, port=port)
        with pytest.raises(GaletConfigError, match="must be (an integer|in 1\\.\\.65535)"):
            load_config(path)

    @pytest.mark.parametrize("fonts", ["DejaVuSans.ttf", [1, 2]])
    def test_fonts_wrong_type_rejected(self, tmp_path, fonts) -> None:
        path = _write_config(tmp_path, fonts=fonts)
        with pytest.raises(GaletConfigError, match="key 'fonts' must be a list"):
            load_config(path)

