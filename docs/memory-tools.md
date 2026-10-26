# Memory tools

Install the optional memory backend and MCP SDK from a galet-tools checkout:

```bash
python -m pip install -U -e '.[memory,mcp]'
```

The shared configuration and procedural layout require galet-memory 0.1.28 or
newer. Upgrade it in the same virtual environment that runs MCP and pytest:

```bash
.venv/bin/python -m pip install --upgrade 'galet-memory[vec]>=0.1.28'
.venv/bin/python -m pytest
```

For development against a galet-memory checkout, install that checkout into the
same environment:

```bash
python -m pip install -e '../galet-memory[vec]'
```

Handlers are also usable directly from Python with injected backends.
Generic registry factories leave memory backends to the host; MCP constructs
them from its configuration. Base-package registration does not import
`galet_memory`, and memory storage is opened only when a memory tool is allowed.

## MCP configuration

Use one `memory_config_path` for semantic, episodic, procedural and working
memory. Galet-memory loads and validates its own config and constructs one
`MemoryRuntime`; MCP injects its backends into the allowlisted tools and closes
the runtime once on shutdown. Galet owns credential lookup, including
`GALET_CREDENTIAL_PATH`. MCP retains the account, tool allowlist and HTTP options.

Start with the paired examples:

```bash
python -m pip install -e '../galet-memory[vec]'
python -m pip install -e '.[memory,mcp]'
mkdir -p /tmp/galet-memory-mcp/digests
cp galet-memory-mcp.example.json galet-memory-mcp.json
cp galet-mcp.example.json galet-mcp.json
```

Set MCP's `memory_config_path` to the absolute path of `galet-memory-mcp.json`.
Review the example roots for your machine. The memory example creates NEW empty
test stores under `/tmp/galet-memory-mcp`; it does not copy existing application
data. To recall your verified migration, add this root to the memory config:

```json
"migration": "/tmp/memory-v3-migration-PdLyn1"
```

and replace only `memory.semantic.database` with:

```json
{
  "external_root": "migration",
  "relative_path": "migrated-v3-verified.sqlite",
  "create": false
}
```

Keep the episodic, procedural and working roots in the disposable workspace for
initial write tests. Use `create:false` when deliberately opening an existing
database. Existing schemas and embedding profiles are validated; no implicit
migration runs. Create configured root directories and the digest directory
before startup.

Allow `semantic_memory`, `episodic_memory`, and `procedural_memory` in MCP's
allowlist. Each allowed tool must have its component in the memory config.
Components belonging to tools outside the allowlist are not opened. Working
memory, if configured, is internal host state attached to `scope.memory_runtime`;
it has no MCP tool. Its persistence and account isolation are checked with the
same runtime in the integration tests.

The sample explicitly preserves the established procedural paths:

| Scope | Contexts | Skills |
| --- | --- | --- |
| Global | `contexts/<name>.md` | `skills/<name>.md` |
| Account | `contexts/<account>/<name>.md` | `skills/<account>/<name>.md` |

Project paths are disabled by null layout entries. Set all relevant layout
fields explicitly when adopting existing files: galet-memory's defaults use
`procedural/global/...` and `procedural/accounts/...` instead. The selected
`context_resolution` applies to context merging/precedence; skills resolve to
the most specific visible scope.

Without `memory_config_path`, the older episodic/procedural MCP options still
work and log a deprecation warning. They cannot be combined with the shared
config: move `episodic_memory_db_path` into `memory.episodic.database` and move
MCP's `procedural_memory` settings into `memory.procedural` (root expressed as
external root plus relative path). There is no silent precedence or merging.

### Testing all configured memory types

Start the server with the config reviewed above, then use a second terminal:

```bash
export GALET_CREDENTIAL_PATH=/home/junwin/credential
galet-tools-mcp --config galet-mcp.json --log-file /tmp/galet-mcp.log
```

```bash
galet-tools-smoke --url http://127.0.0.1:8700/mcp list
galet-tools-smoke --url http://127.0.0.1:8700/mcp call semantic_memory '{"action":"recall","query":"Tyntesfield country house","namespaces":["vol_7"]}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call procedural_memory '{"action":"save_context","scope":"account","context_name":"mcp-check","text":"Shared configuration test"}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call procedural_memory '{"action":"recall","context_name":"mcp-check"}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call episodic_memory '{"action":"create_session","session_id":"mcp-config-check"}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call episodic_memory '{"action":"append_event","session_id":"mcp-config-check","event":{"role":"user","actor":"junwin","content":"Shared configuration test"}}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call episodic_memory '{"action":"get_recent_events","session_id":"mcp-config-check"}'
```

Use a fresh session ID for a repeat creation test. Restart the server, repeat
the procedural recall and episodic read, and confirm the content persists.
Semantic recall must report `backend:vector` for a vector test. Working memory's
host-level lifecycle/persistence test is in `tests/test_semantic_mcp.py`.

### Applying the same assembly in Lucy

The reusable functions live in `galet_tools.host.memory`, outside the MCP server:

```python
from galet_tools.host.memory import build_configured_memory, memory_handlers

tools = ['semantic_memory', 'episodic_memory', 'procedural_memory']
runtime = build_configured_memory(memory_config_path, tools)
handlers = memory_handlers(runtime, tools)
# Inject runtime.semantic, runtime.episodic, runtime.procedural and runtime.working
# into the application's services. Close runtime once at application shutdown.
```

An application can also call `galet_memory.load_memory_config` and `build_memory`
directly to build every configured component. Both routes use the same config
contract. Lucy currently constructs its semantic, episodic and procedural
services separately in `src/container_config.py`; adoption needs a singleton
runtime, injection into tool and prompt-building consumers, and shutdown cleanup.
Its semantic wrapper and digest search/publication adapters need separate review:
MCP recall success does not validate Lucy's curation integration. This change
does not alter Lucy or switch its databases.

## Procedural tool

| Action | Arguments | Result |
| --- | --- | --- |
| `recall` | `context_name` and/or `skill_names`, optional `project_name` | Resolved context, skills, missing imports, required tools and source metadata in `memory`. |
| `list_contexts` | Optional `scope` and `project_name` | Context names; effective scope includes all visible names without duplicates. |
| `read_context` | `context_name`, optional `scope` and `project_name` | Raw body/frontmatter of the selected file. |
| `save_context` | `context_name`, `text`, explicit write scope, optional `frontmatter` | Replace the selected context file; return its path. |
| `update_context` | `context_name`, explicit write scope, optional `text`/`frontmatter`/`inherit_existing` | Preserve omitted body and merge supplied frontmatter. |
| `save_skill` | `skill_name`, `text`, explicit write scope, optional `frontmatter` | Replace the selected skill file; return its path. |

Writes require `scope="global"`, `"account"` or `"project"`; project writes also
require `project_name`. `effective` is the default for listing/reading and the
only recall scope. `read_context` returns the most specific raw file in effective
scope; `recall` applies the configured context resolution and skill imports.
Use `context_name="none"` plus `skill_names` to inspect named skills.

For example, call `procedural_memory` with:

```json
{"action":"save_skill","scope":"global","skill_name":"review","text":"Inspect changes and run relevant checks.","frontmatter":{"mandatory_tools":["file_load"]}}
```

```json
{"action":"save_context","scope":"global","context_name":"dev","text":"Development context.","frontmatter":{"imports":["review"]}}
```

```json
{"action":"update_context","scope":"account","context_name":"dev","inherit_existing":true,"text":"Account development context."}
```

```json
{"action":"recall","context_name":"dev"}
```

Saving an account skill named `review` then changes the skill selected for this
account; the global skill remains available to other accounts.

## Explicit episodic actions

Sessions belong to accounts and have no agent selector. The trusted execution
account is used unless no account was supplied by the host; an argument cannot
switch a fixed account. All backend operations receive `account_name`.

| Actions | Parameters and result |
| --- | --- |
| `create_session`, `get_session`, `update_session` | Metadata in `session`; create accepts optional identity/name/context/tags/metadata, update accepts a `changes` object. No transcript is loaded. |
| `list_sessions` | `count` (20), optional `cursor`; returns `sessions`, `next_cursor`. |
| `append_event`, `append_events` | `event` or `events`: role, actor, original JSON content, optional kind/time/metadata/correlation_ids. Event and correlations are saved atomically. |
| `get_event` | `session_id`, `event_id`; returns `event` or null. |
| `get_recent_events` | `session_id`, `count` (10), optional `event_kinds`, `actors`, `before_event_id`; returns events in append order and a continuation `before_event_id`. |
| `get_events_by_period` | `session_id`, timezone-aware ISO `start`, `end`, optional filters, `count` (100), `cursor`; returns occurrence order for `[start,end)` and `next_cursor`. |
| `get_exchange`, `invalidate_exchange` | `session_id`, `correlation_id`; read linked events or hide them idempotently. |
| `get_digest`, `list_digests`, `search_digests` | Read by `digest_id`, paginate with count/cursor, or search query with optional session/count. Search requires an injected configured digest search provider; the generic MCP store has none. |
| `clear_session_events`, `delete_session`, `delete_sessions` | Explicit destructive operations; bulk deletion takes `session_ids` (1–100). |

Counts apply after filtering and can be zero. Events retain complete JSON
payloads, `actor`, `role`, `kind`, occurrence/stored timestamps, append sequence,
metadata and `correlation_ids`. No truncation or prompt-token budgeting happens
here. Session updates distinguish omitted fields (unchanged) from null (clear a
nullable name/context) and empty tags/metadata (replace with empty).

```json
{"action":"get_recent_events","session_id":"s","count":10,"event_kinds":["user_message"]}
{"action":"append_event","session_id":"s","event":{"role":"user","actor":"junwin","content":{"text":"Hello"},"correlation_ids":["request-1"]}}
{"action":"update_session","session_id":"s","changes":{"friendly_name":null,"tags":[]}}
{"action":"invalidate_exchange","session_id":"s","correlation_id":"request-1"}
```

Invalidation hides the request and linked response/tool/media events while
retaining originals. It returns `status` (`invalidated`, `already_invalidated`,
`not_found`), target IDs/count, affected digest IDs and marker/provenance fields.
Unrelated exchanges remain visible; affected derived digests cannot reintroduce
hidden content. The tool does not expose audit snapshots or internal markers.

Conditional append, clear and invalidation accept `expected_last_event_id`.
Omit it or pass null for no guard; pass an empty string to guard an empty stream
(mapped to `EMPTY_TAIL`); otherwise pass the true tail from `get_session` or an
event page. Account errors and stale-tail conflicts return structured `ok:false`.
Lucy still owns the restriction on invalidating a running exchange.

This is a coordinated **breaking API and storage change**. `recall`,
`invalidate_events`, episodic `reset_session`, `agent_name`, `event_scope`, and
combined metadata/transcript reads are removed. Use the explicit methods above.
Use fresh storage: old schemas are rejected, with no migration or fallback.
The separate `reset_session` tool retains its client action name but now needs
an injected `CurationService` (constructor or `curation_service` context). It
calls account-scoped `reset_context`, preserving history. `curate_chat` continues
to use that service for previews and archives. Update Lucy's factories and
prompt-builder consumers before coordinated release/deployment.

Schemas use optional action-specific fields (`strict:false`), rather than
requiring dummy values for every action. Python and MCP share these definitions.

## Run tests

A disposable example exercises global/account procedural resolution and linked
request/response invalidation without touching application storage:

```bash
python examples/memory_tools.py
```

For MCP Inspector or the bundled HTTP smoke client:

```bash
galet-tools-mcp --config galet-mcp.json
galet-tools-smoke --url http://127.0.0.1:8700/mcp list
galet-tools-smoke --url http://127.0.0.1:8700/mcp call procedural_memory '{"action":"list_contexts"}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call procedural_memory '{"action":"recall","context_name":"dev"}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call episodic_memory '{"action":"get_recent_events","session_id":"<session-id>","count":10,"event_kinds":["user_message"]}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call episodic_memory '{"action":"invalidate_exchange","session_id":"<session-id>","correlation_id":"<correlation-id>"}'
```

Python and MCP calls share the same handler definitions and execution logic.
MCP `isError` remains reserved for dispatch/execution failures; a structured
handler result with `ok:false` is a normal tool result containing the failure.

## Semantic recall against an existing V3 database

Add `semantic_memory` to the MCP allowlist and set `memory_config_path` to an
absolute path to a galet-memory config. Its semantic section selects the database,
metadata version, embedding profile and authorized source roots. MCP opens the semantic component and any other allowlisted memory components.
For the semantic-only allowlist below, episodic and procedural stores are not opened.
The configured MCP account applies to recall and namespace listing.

To test a migrated database, create separate test configs. For example, with the
verified migration copy from the migration walkthrough:

```bash
export GALET_CREDENTIAL_PATH=/home/junwin/credential
export MEMORY_MIGRATION_DIR=/tmp/memory-v3-migration-PdLyn1
python - <<'PYCONFIG'
import json
import os
from pathlib import Path

workspace = Path(os.environ['MEMORY_MIGRATION_DIR'])
original = Path('/home/junwin/src/repos/galet-memory/memory_config.json')
memory = json.loads(original.read_text())
# Absolute source paths keep any shared config file references valid after copying.
for key in ('external_roots_file', 'embedding_profiles_file'):
    if key in memory:
        memory[key] = str((original.parent / memory[key]).resolve())
if 'external_roots_file' in memory:
    roots = json.loads(Path(memory.pop('external_roots_file')).read_text())['external_roots']
    memory['external_roots'] = roots
memory['external_roots']['migration_test'] = str(workspace)
memory['external_roots']['obsidian'] = '/home/junwin/obsidian/test'
semantic = memory['memory']['semantic']
semantic['metadata_version'] = 3
semantic['database'] = {
    'external_root': 'migration_test',
    'relative_path': 'migrated-v3-verified.sqlite',
    'create': False,
}
memory_path = workspace / 'memory-mcp-test.json'
mcp_path = workspace / 'galet-mcp-test.json'
# Exclusive creation avoids replacing earlier test configurations.
with memory_path.open('x') as output:
    json.dump(memory, output, indent=2)
with mcp_path.open('x') as output:
    json.dump({
        'account': 'junwin',
        'allowlist': ['semantic_memory'],
        'memory_config_path': str(memory_path),
        'storage_root': str(workspace),
        'storage_namespace': 'mcp',
        'sandbox_root': str(workspace),
        'host': '127.0.0.1',
        'port': 8700,
    }, output, indent=2)
print(mcp_path)
PYCONFIG

galet-tools-mcp --config "$MEMORY_MIGRATION_DIR/galet-mcp-test.json"
```

In another terminal, list tools/namespaces and try a query whose answer you know
is in `vol_7`:

```bash
galet-tools-smoke --url http://127.0.0.1:8700/mcp list
galet-tools-smoke --url http://127.0.0.1:8700/mcp call semantic_memory '{"action":"namespaces"}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call semantic_memory '{"action":"recall","query":"your known vol_7 subject","namespaces":["vol_7"],"top_k":5}'
```

Omitting `namespaces` searches all namespaces belonging to the configured
account. Omitting `embedding_model` uses the configured profile. Each vector
recall makes a live query embedding request. Check `ok`, the returned documents,
scores, source paths and `metadata.unavailable_resources`; an empty successful
result is not evidence that the expected note was found. The smoke command
prints handler failures as structured `ok:false` results even when the MCP
transport succeeded.

The semantic tool exposes recall and utilities, with no ingestion or deletion
actions. This setup uses the verified copy and leaves Lucy's configuration and
original database in place. It validates MCP/handler/memory integration; Lucy's
own construction and prompt assembly still need a separate check.

### Diagnosing vector-to-keyword fallback

Run `galet-tools-mcp --config galet-mcp.json --log-file /tmp/galet-mcp.log`
to keep application logs while watching stderr. Startup reports the semantic
schema version and provider/model/dimensions. Each call reports its ID, duration,
outcome and recall backend. `backend=keyword` is logged at WARNING even if the
handler returns `ok:true`.

Install galet-memory's embedding-failure logging change too: it logs the original
exception and traceback when query embedding fails, before attempting keyword
fallback. This makes missing credentials, provider outages and other embedding
errors visible in the MCP process. A vector recall reports `backend=vector`.
