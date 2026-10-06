# Procedural and episodic tools

Install the optional memory backend and MCP SDK from a galet-tools checkout:

```bash
python -m pip install -U -e '.[memory,mcp]'
```

The memory extra currently pins the immutable galet-memory PR #33 merge commit
`1215486ccdb300c438e51b76ef0ec14355559708`. Its explicit API is not yet
available under a new PyPI version. Replace this pin with the coordinated
release requirement before publishing galet-tools. The handlers are also
usable directly from Python, with a backend passed to their constructor or via
`execute(..., procedural_memory=...)` / `execute(..., episodic_store=...)`.
Generic registry factories leave memory backends to the host; MCP constructs
them from its configuration. Base-package registration does not import
`galet_memory`, and memory storage is opened only when a memory tool is allowed.

## MCP configuration

Add `procedural_memory` and `episodic_memory` to `allowlist`. The default
allowlist remains the existing filesystem/command/SVG set. These optional
settings select a **fresh schema-v2 database** for integration testing:

```json
{
  "account": "junwin",
  "allowlist": ["procedural_memory", "episodic_memory"],
  "storage_root": "/home/junwin/lucy_storage",
  "storage_namespace": "data",
  "sandbox_root": "/home/junwin/sandbox",
  "episodic_memory_db_path": "/home/junwin/lucy_storage/data/episodic-v2.sqlite",
  "procedural_memory": {
    "root": "/home/junwin/lucy_storage/data",
    "context_resolution": "most_specific"
  },
  "host": "127.0.0.1",
  "port": 8700
}
```

Without overrides, episodic storage is `<storage_root>/<storage_namespace>/chat2.sqlite`
and procedural storage uses the same base directory. The database path and
procedural root must be absolute. The configured MCP account is fixed for the
server; tool arguments cannot switch it, and episodic operations check session
ownership. Tools use galet-memory's current relational SQLite implementation.

The default procedural layout matches Lucy's global/account layout:

| Scope | Contexts | Skills |
| --- | --- | --- |
| Global | `contexts/<name>.md` | `skills/<name>.md` |
| Account | `contexts/<account>/<name>.md` | `skills/<account>/<name>.md` |

Project paths are disabled by default. Override any of the six `ProceduralLayout`
fields in `procedural_memory.layout` to use a different layout, e.g.:

```json
{
  "project_contexts": "contexts/{account}/projects/{project}",
  "project_skills": "skills/{account}/projects/{project}"
}
```

`context_resolution` accepts `most_specific` (default, account context overrides
global) or `merge` (combine configured context scopes). Skill resolution always
chooses the most specific matching skill, as implemented by galet-memory.

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
