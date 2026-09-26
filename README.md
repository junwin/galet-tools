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
- **Generic tools** — `file_load`, `file_save`, `patch_apply`,
  `execute_command`, `execute_command2`, `generate_svg`, and `generate_image`, registered
  under their existing names. `file_load` supports bounded line-range reads.
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

## Episodic curation example

The `curate_chat` handler takes an injected curation service. It is intentionally
not registered as a generic MCP default because the host must supply the
episodic store, digest generator, and trusted account.

Run a small SQLite session through digest preview, archive, and an idempotent
archive retry without an LLM key:

```bash
python -m pip install -e '.[memory]'
python examples/curate_chat.py
```

The example uses a deterministic digest generator. In an application, inject
`galet_memory.curation.CurationService` with the application's digest generator
and construct `CurateChatHandler(service)` through a registry factory.

## MCP server

An optional MCP (Model Context Protocol) server exposes the generic
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

- `allowlist` — tools to expose; the default includes `file_load`,
  `file_save`, `patch_apply`, legacy `execute_command`, structured
  `execute_command2`, `generate_svg`, and `generate_image`.
- `external_roots` — named external roots the tools may access; default
  none.
- `host` — default `127.0.0.1`; loopback only.
- `port` — default `8765`.
- `fonts` — font paths for the generators; default none.

### What it exposes

`tools/list` and `tools/call` over streamable HTTP at
`http://127.0.0.1:8765/mcp`.

### Smoke-test from the CLI

`galet-tools-smoke` is the end-to-end CLI client: it connects over HTTP
(streamable HTTP) to a running galet MCP server using the official MCP SDK
and performs real `tools/list` and `tools/call` round trips.

```bash
galet-tools-smoke list
galet-tools-smoke list --json
galet-tools-smoke call <tool> '<json args>'
```

The default URL is `http://127.0.0.1:8765/mcp`; override it with `--url`.
The default read timeout is 30s; override it with `--timeout`.

Example round trip (storage root from `galet-mcp.json`):

```bash
galet-tools-smoke call file_save '{"path":"smoke/hello.txt","file_content":"hello galet smoke"}'
galet-tools-smoke call file_load '{"path":"smoke/hello.txt"}'
galet-tools-smoke call execute_command2 '{"mode":"process","executable":"python","arguments":["-c","print(123)"],"script":"","shell":"none","location":"sandbox","external_root":"","working_directory":".","timeout_seconds":30,"success_exit_codes":[0]}'
```

Exit codes: `0` ok; `1` tool reported an error (`isError`); `2` usage or
bad JSON; `3` could not reach the server.

### Fail-closed behaviour

The server refuses to start when the allowlist is empty or has no overlap
with the registered tools, and only the advertised tools are callable.
Unknown tool names in the allowlist fail validation.

### Security

Binding is loopback-only by design: `host` must resolve to a loopback
address. Remote access needs a separate reverse-proxy design.

## License

MIT — see `LICENSE`.
