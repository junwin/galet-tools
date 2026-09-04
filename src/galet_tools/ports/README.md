# galet_tools.ports

Sibling-owned public contracts for the generic tool handlers. Ports are
defined here first (dependency inversion); Lucy implements the adapters at
its composition root in Phase B. Handlers in galet_tools depend only on
these Protocols, never on Lucy ConfigManager.

Status key: defined = port file exists in this repo; planned = to be
defined in plan step 2 (Phase A), grounded in the Lucy sources below.

## Port-to-handler mapping

| Port | Handlers (registered tool names) | Lucy source of truth |
|---|---|---|
| StorageLocationResolver (defined) | file_load, file_save, execute_command (external roots only) | src/handlers/file_load_handler2.py, src/handlers/file_save_handler.py, src/handlers/command_execution_handler2.py |
| SandboxRootResolver (defined) | execute_command | src/handlers/command_execution_handler2.py |
| SecurityPolicy (defined) | execute_command | src/handlers/command_execution_handler2.py |
| ConfigProvider (defined) | generate_image | src/handlers/generate_image_handler.py |
| CredentialProvider (planned) | web_search (tool deferred) | web_search_handler (deferred) |
| RegistryProvider / ToolResolver (planned) | sandbox_execute (tool deferred) | src/handlers/handler_registry.py (orchestrator creation) |

Registered handler/profile names stay unchanged by the extraction: file_load,
file_save, execute_command, generate_svg, generate_image.

## Actual config reads each port covers

Verified against the Lucy sources listed above (2026-09-04):

| Port | Config / inputs actually read today |
|---|---|
| StorageLocationResolver | storage_root_path + storage_namespace joined, then abspath, for the storage base; external_roots[name] (missing name or non-map raises ValueError) for the external base. These are the only config reads in file_load and file_save. execute_command also reads external_roots here with identical helper semantics; it never reads storage_root_path or storage_namespace. |
| SandboxRootResolver | code_sandbox_path for the sandbox base, fenced per account (join(base, account_name) when the base dir exists), then abspath; a missing path raises ValueError. This is the only code_sandbox_path read in execute_command. handler_utils.py has a similar helper but execute_command does not import that module (only scrape_web_page uses it). |
| SecurityPolicy | Reads nothing from ConfigManager or env: execute_command keeps no command allow/deny lists in config today. The refusal rules are inline pure logic over the command string (bare interactive shells via INTERACTIVE_BARE, shell-only syntax without an explicit wrapper, benign-command warning status via _BENIGN_COMMANDS, output truncation via MAX_OUTPUT_CHARS = 10,000). Protocol surface: is_command_allowed(command, *, wrapper="none") -> bool plus max_output_chars() -> int, the host decision seam execute_command consults once moved. Relative-path validation and realpath containment (_validate_and_normalize_relative_path, _resolve_dir_safe) stay inline per plan step 4; per-account sandbox fencing belongs to SandboxRootResolver. |
| ConfigProvider | Nothing today: the only self.config occurrence in generate_image is the constructor assignment (never read by any method); the sole host dependency is the hardcoded Linux TrueType font path list in _render_image (lines 109-110: DejaVuSans-Bold.ttf then FreeSansBold.ttf, tried in order with ImageFont.truetype, load_default fallback). Port created to host-provide that list at move time; surface is truetype_font_paths() only, kept narrow because no other moved tool needs a keyed lookup (see t2.5). generate_svg reads no config at all (pydantic + XML validation only, verified t2.4). |
| CredentialProvider | Per design doc (tool deferred to a later pass): credential_path/brave.json -> subscription_key. Not code-verified in this phase. |
| RegistryProvider / ToolResolver | No config reads: resolves and constructs child handlers via the registry create(name, config) pattern used by orchestrators such as sandbox_execute. |

Notes:

- execute_command maps location=sandbox to SandboxRootResolver (code sandbox
  path), not to the storage base used by file_load/file_save; location=external
  maps to StorageLocationResolver.external_root_dir, which is why that port row
  now also lists execute_command.
- Path rules stay inline per handler on the move (_read_file_safe,
  _write_file_safe, _resolve_dir_safe); the ports carry only what each tool
  resolves, except SecurityPolicy, which is the policy itself.
- generate_svg takes ConfigManager in Lucy today but never reads it; its
  constructor should drop the config dependency when moved (verified t2.4).
  generate_image is in the same position but swaps ConfigManager for
  ConfigProvider at move time: the constructor stops storing config and
  _render_image reads candidate font paths from the port instead of the
  hardcoded Linux list.

## Verification log (coverage per tool move)

Each row records the confirmation that a defined port surface covers the
actual config reads of the Lucy handler before that tool moves. Method:
full handler read plus grep for config reads (self.config.get) on the Lucy
source; every read maps 1:1 to a protocol member.

| Step | Tool verified (Lucy source) | Port | Verdict |
|---|---|---|---|
| t2.1 | file_load (src/handlers/file_load_handler2.py) | StorageLocationResolver | Fully covered. Reads exactly storage_root_path, storage_namespace and external_roots (see coverage table above); the protocol was created to match. No reads left uncovered. |
| t2.2 | file_save (src/handlers/file_save_handler.py) | StorageLocationResolver | Fully covered. file_save reads exactly the same three keys as file_load, in the same two helpers: _storage_base_dir joins storage_root_path with storage_namespace, _external_root_dir resolves external_roots[name]. ValueError semantics match the protocol (missing storage key, non-map external_roots, unknown root name). No new port and no protocol change required. |
| t2.3 | execute_command (src/handlers/command_execution_handler2.py) | SandboxRootResolver, SecurityPolicy (StorageLocationResolver re-confirmed) | Fully covered. Full read plus grep show exactly two ConfigManager reads: code_sandbox_path in _sandbox_base_dir (per-account join when the base dir exists, then abspath; ValueError when missing) and external_roots in _external_root_dir (non-map and unknown-name ValueError semantics identical to file_load and file_save). SandboxRootResolver.sandbox_base_dir(*, account_name) maps 1:1 to the sandbox read. The external_roots read was already covered by StorageLocationResolver.external_root_dir, so no protocol extension was needed: execute_command never reads storage_root_path or storage_namespace, and location=sandbox resolves to the code sandbox path, not the storage base. No command allow/deny rules are read from ConfigManager or env; the guards are inline pure logic. SecurityPolicy was created as the host decision seam (is_command_allowed plus max_output_chars) per design Precision fix 2, not as a mapping of an existing config read. |
| t2.4 | generate_svg (src/handlers/generate_svg_handler.py) | None — no port required | Confirmed zero external dependencies. Full handler read plus targeted grep: the only imports beyond stdlib (base64, logging, typing, xml.etree.ElementTree) are pydantic and ConfigManager, and the ConfigManager import serves only the constructor type annotation — __init__(self, config) stores self.config but no method ever reads it (grep finds the assignment as the single self.config occurrence in the file). No config, storage, sandbox, credential, environment, file or network reads anywhere; all work is in-memory (pydantic validation, XML parse and sanitize, base64 data URI). generate_svg is fully self-contained, so no port file was created; the unused config parameter should be dropped at move time as noted above. |
| t2.5 | generate_image (src/handlers/generate_image_handler.py) | ConfigProvider | Fully covered — port created for the de-hardcoding need. Full read plus grep confirm generate_image keeps zero ConfigManager reads: the single self.config occurrence is the constructor assignment (line 29) and no method ever reads it; there is no env, file, network or subprocess access. The only host dependency is the hardcoded TrueType font path list in _render_image (lines 109-110), which plan step 4 makes configurable at move time. ConfigProvider therefore exists not to map a current read but to replace that list: its surface is a single truetype_font_paths() -> list[str] returning candidates in preference order (an empty list is safe — the handler falls back to ImageFont.load_default()). Shape checked against the other 4 tools before fixing it: file_load and file_save read exactly storage_root_path, storage_namespace and external_roots (all StorageLocationResolver, t2.1/t2.2); execute_command reads code_sandbox_path (SandboxRootResolver) and external_roots (StorageLocationResolver, t2.3); generate_svg reads nothing (t2.4). None of them needs a generic keyed config lookup, so ConfigProvider was deliberately not widened to a get(key) shape. No changes to existing ports required. |
