# galet-tools

Self-contained generic tool handlers and the handler framework they run on.

## Lineage

This package is extracted from the Lucy monorepo (`src/handlers`) as described
in the Lucy design doc `software/ai/lucy/design/handlers-extraction.md` and
the plan `software/ai/lucy/plan/handlers-extraction.md`.

It is a fresh repository with no shared git history. Handler logic moves
verbatim; the only intentional changes are the import namespace
(`src.handlers.*` -> `galet_tools.*`) and the configuration boundary: tools
depend on narrow port interfaces owned by this package (`ConfigProvider`,
`StorageLocationResolver`, `SandboxRootResolver`, `SecurityPolicy`, ...),
never on Lucy's `ConfigManager`. Lucy implements those ports at its
composition root.

## Features

- **Handler framework** — `HandlerV2` ABC, `HandlerRegistry`, schema
  handling, and permission filtering.
- **Generic tools** — `file_load`, `file_save`, `execute_command`,
  `generate_svg`, `generate_image`, registered under their existing names.
- **Ports** — sibling-owned interfaces the host implements, keeping the tools
  free of any host dependency.
- **Handler discovery** — installed packages can contribute handlers through
  Python package entry points without changing Lucy or galet-tools.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

Run the suite:

```bash
python -m pytest -q
```

## Using the registry in a host

Galet owns the handler contract and base registry. A host such as Lucy composes
the generic handlers, its own host-specific handlers, and installed extension
packages:

```python
from galet_tools import HandlerRegistry, register_installed_handlers
from galet_tools.register_generic_defaults import register_generic_defaults

registry = HandlerRegistry()
register_generic_defaults(registry)
register_lucy_handlers(registry)
register_installed_handlers(registry)
```

Discovery adds installed capabilities to the registry; it does not grant them
to an agent. The host should continue to apply its agent and context allowlists
when selecting tool definitions.

### Creating a handler extension

An extension package declares a registrar in its `pyproject.toml`:

```toml
[project.entry-points."galet_tools.handlers"]
web = "galet_web_tools:register"
```

The target is a callable that receives the shared registry:

```python
def register(registry):
    registry.register(SearchHandler)
    registry.register(FetchHandler)
```

Entry points are loaded in deterministic name order. A plugin that cannot be
loaded, does not resolve to a callable, or fails during registration raises
`HandlerPluginError` with the responsible entry-point name. This is
intentionally fail-fast so a host cannot start with an unexpectedly incomplete
tool set.

## MCP server

An optional MCP (Model Context Protocol) server exposes the five generic
tools over streamable HTTP. Install the extra:

```bash
.venv/bin/pip install -e '.[mcp]'
```

Copy the example config and start the server:

```bash
cp galet-mcp.example.json galet-mcp.json
galet-tools-mcp
```

`galet-tools-mcp` reads `galet-mcp.json` from the current directory by
default; point it elsewhere with `--config <path>`.

### Configuration

`galet-mcp.json` mirrors `galet-mcp.example.json`. Required keys are
`account`, `storage_root`, `storage_namespace`, and `sandbox_root`; a
null, blank, or (for the two path keys) relative value fails validation.
Optional keys left out or set to null fall back to their defaults:

- `allowlist` — tools to expose; default is all five (`file_load`,
  `file_save`, `execute_command`, `generate_svg`, `generate_image`).
- `external_roots` — named external roots the tools may access; default
  none.
- `host` — default `127.0.0.1`; loopback only.
- `port` — default `8765`.
- `fonts` — font paths for the generators; default none.

### What it exposes

`tools/list` and `tools/call` over streamable HTTP at
`http://127.0.0.1:8765/mcp`.

### Fail-closed behaviour

The server refuses to start when the allowlist is empty or has no overlap
with the registered tools, and only the advertised tools are callable.
Unknown tool names in the allowlist fail validation.

### Security

Binding is loopback-only by design: `host` must resolve to a loopback
address. Remote access needs a separate reverse-proxy design.

## License

MIT — see `LICENSE`.
