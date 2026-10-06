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
  `execute_command`, `execute_command2`, and `generate_svg`, registered
  under their existing names. `file_load` supports bounded line-range reads.
- **Repository navigation** — `repo_index` and `repo_search` preserve Python AST
  navigation and also search supported JavaScript, TypeScript, C#, Java, and other
  source files using bounded text indexing.
- **Ports** — sibling-owned interfaces the host implements, keeping the tools
  free of any host dependency.
- **Handler discovery** — installed packages can contribute handlers through
  Python package entry points without changing Lucy or galet-tools.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

### Update the project and all dependencies

From the `galet-tools` directory, with your virtual environment active, run:

```bash
python -m pip install --upgrade --upgrade-strategy eager -e '.[memory,mcp,video]'
```

This installs your local `galet-tools` in editable mode and upgrades its
runtime dependencies, including `galet-memory` and `galet`, to the newest
versions allowed by `pyproject.toml`. It includes the memory, MCP, and video
extras; exact version pins remain in effect.

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

### Repository navigation

`repo_index` maps supported source files, looks up a file or directory, and
finds symbols. Python files use AST-based classes, functions, methods, and exact
line ranges. Other supported languages, including JavaScript, TypeScript, and
C#, use a lightweight text index that returns matching lines and line numbers.
`repo_search` ranks both Python and other source files using paths and content;
Python also uses structural metadata. Common dependency, generated, and build
directories are skipped, and tests are omitted unless `include_tests` is true.

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

## Memory tools example

The `episodic_memory` handler takes an injected episodic store, and
`curate_chat` takes an injected curation service, and `reset_session` takes
the same episodic store. `semantic_memory` takes an injected
`galet_memory.semantic.SemanticMemory`. `procedural_memory` exposes context/skill
recall and scoped context/skill edits. The episodic and procedural tools are
registered in the generic registry, with backends supplied by the host; MCP
constructs them when explicitly allowlisted. Curation/reset/semantic tools still
require application services and are not exposed by the generic MCP server.

See [memory tools](docs/memory-tools.md) for procedural operations, correlation
invalidation, configuration pointing at Lucy storage, and Inspector/smoke tests.

Run a small SQLite session through creation, event append and read, digest
preview, archive, an active-session read, and an idempotent
archive retry, and a reset that clears events while retaining the session
metadata. It then writes and indexes the archived digest and recalls it
through `VectorSemanticMemory` in the `digests` namespace, using deterministic
embedding and index ports without an API key:

```bash
python -m pip install -e '.[memory]'
python examples/curate_chat.py
```

The memory extra requires galet-memory 0.1.23 or later.

The example uses a deterministic digest generator and runs all four tool adapters
with one temporary session. The example explicitly writes the digest text,
embeds it, and inserts a `StoredEmbedding` into an in-memory index; curation
does not automatically publish to semantic memory. It checks that recall is
empty before publication and returns the digest afterward. In an application, inject
`galet_memory.curation.CurationService` with the application's digest generator
and construct `CurateChatHandler(service)` through a registry factory.

## Video generation

`video_generate` accepts an uploaded `image_id`, a motion `prompt`, and
`duration_seconds` (4, 6, or 8). These three arguments are required. The
following arguments can be supplied for each request or omitted to use defaults:

| Argument | Default | Supported values |
| --- | --- | --- |
| `source` | `google` | Currently Google only; other providers fail explicitly |
| `model` | `veo-3.1-fast-generate-preview` | Google video model ID |
| `aspect_ratio` | `9:16` | `9:16`, `16:9` |
| `resolution` | `720p` | `720p`, `1080p`, `4k`; the latter two require 8 seconds |
| `preserve_subject` | `true` | Boolean; adds identity/garment preservation instructions |
| `add_sound` | `false` | Boolean; false removes audio, true retains provider audio |

Example tool arguments:

```json
{
  "image_id": "<uploaded image UUID>",
  "prompt": "One gentle step forward and a slight turn.",
  "duration_seconds": 4,
  "source": "google",
  "model": "veo-3.1-fast-generate-preview",
  "aspect_ratio": "9:16",
  "resolution": "720p",
  "preserve_subject": true,
  "add_sound": false
}
```

Install `galet-tools[video]` and Galet's Gemini SDK dependency (`galet[gemini]`)
for Google generation. Silent output also requires **FFmpeg on the host PATH**
(e.g. `sudo apt install ffmpeg` on Debian/Ubuntu). The handler checks this before
submitting a paid generation request. Google's Gemini Developer API does not
accept the SDK's `generate_audio` setting, so silent output is implemented by
removing all audio tracks after download, copying the video stream without
re-encoding. This does not reduce provider generation charges. `add_sound=true`
retains whatever audio the provider returns; it does not synthesize a separate
soundtrack. Subject preservation is a prompt instruction, not a guarantee.

Results include the selected source, model, aspect ratio, resolution,
`preserve_subject`, and `add_sound` alongside the video metadata. Defaults are
applied by the handler, including for older callers supplying only the three
original arguments. The tool schema uses `strict=false` so defaulted arguments
can genuinely be omitted.

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
  `execute_command2`, `generate_svg`.
- `external_roots` — named external roots the tools may access; default
  none.
- `host` — default `127.0.0.1`; loopback only.
- `port` — default `8765`.
- `fonts` — font paths for the generators; default none.
- `episodic_memory_db_path` — optional absolute relational SQLite path; defaults
  to `<storage_root>/<storage_namespace>/chat2.sqlite` when episodic tools are allowed.
- `procedural_memory` — optional root/layout/context-resolution overrides. See
  [memory configuration](docs/memory-tools.md#mcp-configuration).

### What it exposes

`tools/list` and `tools/call` over streamable HTTP. With the default port, the
endpoint is `http://127.0.0.1:8765/mcp`.

### Test interactively with MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) provides a
browser interface for testing galet-tools as an MCP user. Start
`galet-tools-mcp`, then run:

```bash
npx --yes @modelcontextprotocol/inspector@latest --web --server-url http://127.0.0.1:8700/mcp --transport http
```

This command requires Node.js and npm. The server URL must use the `port` from
your `galet-mcp.json`; the example above uses `8700`. In the Inspector, use
**Tools** to list the tools, inspect their schemas, enter arguments, and run
real `tools/call` requests against the server.

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

