# galet-tools

Self-contained generic tool handlers and the handler framework they run on.

## Install

Install from PyPI:

```bash
pip install galet-tools
```

Optional extras: `galet-tools[mcp]` for the MCP server,
`galet-tools[memory]` for the memory tools, `galet-tools[video]` for
video generation.

### Quick sample: start the MCP server

```bash
pip install "galet-tools[mcp]"
mkdir -p /tmp/galet-mcp/storage /tmp/galet-mcp/sandbox
cat > galet-mcp.json <<'EOF'
{
  "account": "demo",
  "storage_root": "/tmp/galet-mcp/storage",
  "storage_namespace": "demo",
  "sandbox_root": "/tmp/galet-mcp/sandbox"
}
EOF
galet-tools-mcp
```

The server exposes `tools/list` and `tools/call` at
`http://127.0.0.1:8765/mcp`. Smoke-test it from a second shell:

```bash
galet-tools-smoke list
```

## Background

The tools depend on narrow port interfaces owned by this package
(`ConfigProvider`, `StorageLocationResolver`, `SandboxRootResolver`,
`SecurityPolicy`, ...), never on host configuration code. A host application
implements those ports at its composition root.

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

As a library, install from PyPI:

```bash
pip install galet-tools
```

From source:

```bash
git clone https://github.com/junwin/galet-tools.git
cd galet-tools
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

## Named roots and relative paths

File, patch, repository, and command tools use one root selector:
`external_root`, with an exact configured name. Model-facing schemas no longer
expose `location`. Root names are arbitrary, case-sensitive aliases supplied
by the host's effective configuration. For example:

```json
{"external_root": "lucy_data_files", "path": "data/accounts/john/notes.txt"}
```

The resolver maps only the name to its configured directory. It does not infer
special behavior from aliases such as `sandbox`, `storage`, or `lucy_data_files`,
and it does not append account or namespace segments. Callers include those
segments explicitly when needed. The host supplies the effective mapping after global/local configuration
overrides; galet-tools does not load host configuration itself.

`path` (file/patch), `root` (repository), and `working_directory` (command) stay
relative to the selected directory. `.` selects the directory itself for
repository/command tools. Absolute paths and escapes in these handler fields
are rejected. Command scripts and program arguments retain their own path
requirements and may contain absolute paths; setting a working directory does
not confine everything a program can access.

Compatibility: direct runtime calls with an explicit legacy `location` retain
their storage/external or sandbox/external semantics, including legacy sandbox
account scoping. Older file/repository/command calls that omit both selectors
retain their historical defaults. A named root without `location` always uses
the configured mapping, never a storage namespace or account sandbox. Legacy
resolver methods and result `location` metadata remain for existing consumers.
New model-facing calls require a non-empty `external_root`; configure roots
explicitly rather than relying on legacy defaults.

## Applying a single-file patch

`patch_apply` wraps `git apply` and requires Git on PATH, but the selected
root does not need to be a Git repository. `path` is relative to that root:
with `external_root="repos"`, a file in a repository
may have `path="image_description/src/image_description/image/prompts.py"`.
Keep that full root-relative path throughout validation and application.

Supply a numbered unified diff. Both Git-style `a/` and `b/` header prefixes
and prefix-free headers are accepted. For `path="repo/file.txt"`, for example:

```diff
--- a/repo/file.txt
+++ b/repo/file.txt
@@ -1 +1 @@
-old
+new
```

Alternatively use `--- repo/file.txt` and `+++ repo/file.txt`. The handler
selects `-p1` or `-p0` only when Git reports exactly the requested file, then
uses that same setting for checking and applying. It does not retry another
setting after a content-check failure. Results report `strip_components`;
path inspection failures include `path_attempts` and Git diagnostics.

Use `check_only=true` first to validate without writing, then submit the same
patch with `check_only=false` to apply it. `*** Begin Patch` syntax is not
supported. Wrong-file, multi-file, binary, and escaping-path patches remain
rejected. Correct malformed hunk counts or headers rather than shortening `path`.

## Memory tools example

The `episodic_memory` handler takes an injected episodic store, and
`curate_chat` takes an injected curation service, and `reset_session` takes
the same curation service. `semantic_memory` takes an injected
`galet_memory.semantic.SemanticMemory`. `procedural_memory` exposes context/skill
recall and scoped context/skill edits. The episodic and procedural tools are
registered in the generic registry, with backends supplied by the host; MCP
constructs them when explicitly allowlisted. Curation/reset/semantic tools still
require application services and are not exposed by the generic MCP server.

See [memory tools](docs/memory-tools.md) for procedural operations, correlation
invalidation, storage configuration, and Inspector/smoke tests.

Run a small SQLite session through creation, event append and read, digest
preview, archive, an active-session read, and an idempotent
archive retry, and a context reset that retains history and session
metadata. It then writes and indexes the archived digest and recalls it
through `VectorSemanticMemory` in the `digests` namespace, using deterministic
embedding and index ports without an API key:

```bash
python -m pip install -e '.[memory]'
python examples/curate_chat.py
```

The example uses a deterministic digest generator and runs all four tool adapters
with one temporary session. The example explicitly writes the digest text,
embeds it, and inserts a `StoredEmbedding` into an in-memory index; curation
does not automatically publish to semantic memory. It checks that recall is
empty before publication and returns the digest afterward. In an application, inject
`galet_memory.curation.CurationService` with the application's digest generator
and construct `CurateChatHandler(service)` through a registry factory.

## Video generation

`video_generate` accepts an uploaded `image_id`, a motion `prompt`, and
`duration_seconds` (integer 3–10 for Omni; 4, 6, or 8 for legacy Veo). These three
arguments are required. The following arguments can be supplied for each request or omitted to use defaults:

| Argument | Default | Supported values |
| --- | --- | --- |
| `source` | `google` | Currently Google only; other providers fail explicitly |
| `model` | `gemini-omni-1.1-flash` | `gemini-omni-*` or explicit legacy `veo-*` model ID |
| `aspect_ratio` | `9:16` | `9:16`, `16:9` |
| `resolution` | `720p` | Omni: `360p`, `720p`, `1080p`, `4k`; legacy Veo: no `360p`, higher resolutions require 8 seconds |
| `preserve_subject` | `true` | Boolean; adds identity/garment preservation instructions |
| `add_sound` | `false` | Boolean; false removes audio, true retains provider audio |

Example tool arguments:

```json
{
  "image_id": "<uploaded image UUID>",
  "prompt": "One gentle step forward and a slight turn.",
  "duration_seconds": 4,
  "source": "google",
  "model": "gemini-omni-1.1-flash",
  "aspect_ratio": "9:16",
  "resolution": "720p",
  "preserve_subject": true,
  "add_sound": false
}
```

Install or upgrade `galet-tools[video]`; this includes `galet[gemini]>=0.1.25`
with the Omni adapter and required Google SDK. The handler selects the Omni
Interactions adapter for `gemini-omni-*` and the legacy Veo adapter for `veo-*`.
Google's Gemini API Veo 3.1 preview endpoints retired on October 22, 2026;
use `gemini-omni-1.1-flash` for new requests. This handler still requires an
uploaded image; Galet's prompt-only mode is not exposed here.

Silent output also requires **FFmpeg on the host PATH**
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
- `external_roots` — arbitrary named roots for file, patch, repository, and
  command tools; default none. Configure these for model-facing root-based
  calls. The example includes data-store and sandbox aliases, which have no
  special meaning to the resolver.
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
galet-tools-smoke call file_save '{"external_root":"lucy_data_files","path":"galet/smoke/hello.txt","file_content":"hello galet smoke","overwrite":true}'
galet-tools-smoke call file_load '{"external_root":"lucy_data_files","path":"galet/smoke/hello.txt","start_line":null,"line_count":null,"include_line_numbers":false}'
galet-tools-smoke call execute_command2 '{"mode":"process","executable":"python","arguments":["-c","print(123)"],"script":"","shell":"none","external_root":"sandbox","working_directory":".","timeout_seconds":30,"success_exit_codes":[0]}'
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




### Reliable small edits

Use `text_replace` with `external_root`, `path`, `old_text`, `new_text` and
`check_only` for exact edits to an existing UTF-8 file. The old text must occur
exactly once, including whitespace. It rejects ambiguous/absent matches, binary
files, symlinks and root escapes. It preserves line endings and permissions,
checks the source again before replacement and returns a diff limited to 4000
characters. Files/results are capped at 4 MiB; edit strings at 1 MiB each.
Use `check_only=true` to preview without writing. Use more unique surrounding
text if there are multiple matches; do not switch to an unguarded whole-file save.

For larger changes use `patch_apply` with numbered unified-diff hunks and
unchanged context lines. Failed context-free interior hunks report
`zero_context_hunk`; malformed patches report `malformed_patch` with Git stderr.
Valid full-file patches that Git accepts still work. Neither check nor apply
uses `--unidiff-zero`. Reread a narrow affected region after a mismatch instead
of repeatedly guessing line numbers/counts. These tools do not commit changes.
