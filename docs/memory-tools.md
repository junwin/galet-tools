# Procedural and episodic tools

Install the optional memory backend and MCP SDK from a galet-tools checkout:

```bash
python -m pip install -U -e '.[memory,mcp]'
```

The memory extra requires released `galet-memory>=0.1.23`. The handlers are also
usable directly from Python, with a backend passed to their constructor or via
`execute(..., procedural_memory=...)` / `execute(..., episodic_store=...)`.
Generic registry factories leave memory backends to the host; MCP constructs
them from its configuration. Base-package registration does not import
`galet_memory`, and memory storage is opened only when a memory tool is allowed.

## MCP configuration

Add `procedural_memory` and `episodic_memory` to `allowlist`. The default
allowlist remains the existing filesystem/command/SVG set. These optional
settings let the test server use the same storage as Lucy:

```json
{
  "account": "junwin",
  "allowlist": ["procedural_memory", "episodic_memory"],
  "storage_root": "/home/junwin/lucy_storage",
  "storage_namespace": "data",
  "sandbox_root": "/home/junwin/sandbox",
  "episodic_memory_db_path": "/home/junwin/lucy_storage/data/chat2.sqlite",
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

## Invalidate an exchange

The enhanced `episodic_memory` tool accepts:

```json
{"action":"invalidate_events","session_id":"<session-id>","correlation_id":"<correlation-id>"}
```

It calls galet-memory's public manager operation to hide all events linked to
that correlation within the account/session, including the request and linked
responses/tool/media events. It retains original records, leaves unrelated
correlations/sessions intact, and excludes affected derived memory through the
package's visibility rules. It does not infer child correlations or delete a
whole trace. Events without a correlation link are not targeted.

The result reports `status` (`invalidated`, `already_invalidated`, `not_found`),
`event_ids`, `event_count`, `invalidated_digest_ids`, `marker_event_id` and
`unprovenanced_digests_invalidated`. Missing/unowned sessions and tail conflicts
return a structured `ok:false` error. Repeating a successful call appends no
additional marker. Normal tool reads do not expose internal deletion markers
or raw invalidated records.

`get_session` additionally accepts `event_scope="active"`, `"all"` or
`"archived"` and returns `session.last_event_id`, the true append tail. Supply
this value as `expected_last_event_id` on invalidation for a conditional write;
null/omitted means no guard. Lucy owns the running-exchange restriction; for
manual storage testing, invalidate a completed exchange.

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
galet-tools-smoke --url http://127.0.0.1:8700/mcp call episodic_memory '{"action":"get_session","session_id":"<session-id>","event_scope":"all"}'
galet-tools-smoke --url http://127.0.0.1:8700/mcp call episodic_memory '{"action":"invalidate_events","session_id":"<session-id>","correlation_id":"<correlation-id>"}'
```

Python and MCP calls share the same handler definitions and execution logic.
MCP `isError` remains reserved for dispatch/execution failures; a structured
handler result with `ok:false` is a normal tool result containing the failure.
