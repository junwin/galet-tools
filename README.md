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

## Status

Scaffold only (Phase A step 1 of the plan): `pyproject.toml`, the
`galet_tools` package skeleton, and an empty `tests/` directory. Ports,
framework, and the five generic tools (`file_load`, `file_save`,
`execute_command`, `generate_svg`, `generate_image`) land in the following
steps.

## Features

- **Handler framework** — `HandlerV2` ABC, `HandlerRegistry`, schema
  handling, and permission filtering.
- **Generic tools** — `file_load`, `file_save`, `execute_command`,
  `generate_svg`, `generate_image`, registered under their existing names.
- **Ports** — sibling-owned interfaces the host implements, keeping the tools
  free of any host dependency.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

Run the suite:

```bash
python -m pytest -q
```

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
`account`, `storage_root`, `storage_namespace`, and `sandbox_root`; a null,
blank, or (for the two path keys) relative value fails validation.
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
