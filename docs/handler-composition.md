# Composing built-in handlers in an application host

`register_builtin_handlers` is the supported package-level registrar. A host
calls it once after registering its own adapters. Future package handlers are
added to the package manifest, so a package upgrade makes their definitions
available without imports, stubs or individual registrations in the host.
Registration makes tools discoverable; the host must still enforce its agent,
context and execution allowlists.

```python
from galet_tools import HandlerRegistry, HandlerServices, register_builtin_handlers

registry = HandlerRegistry()
registry.register(HostFileLoad, factory=host_file_load_factory)

def services_for_config(config):
    return HandlerServices(
        storage_resolver=host_storage_resolver(config),
        sandbox_resolver=host_sandbox_resolver(config),
        security_policy=host_security_policy(config),
    )

report = register_builtin_handlers(registry, services=services_for_config)
# report.preserved includes file_load: its host class AND factory are unchanged.
# report.registered contains newly added names, usable by a discovery catalog.
handler = registry.create("file_load", config=config)
```

The example's `HostFileLoad`, factories, resolvers and `config` are supplied by
the application. Services can also be a single `HandlerServices` instance when
configuration does not vary. The service provider is called with the exact
`config` passed to `registry.create`; discovery does not call it or construct
backends. It must return `HandlerServices`. Hosts retain ownership of lifetimes,
account boundaries and credentials. No environment or config files are read by
the registrar, and it never creates or closes a memory database.

## Precedence and extension discovery

1. Register host-specific classes and factories first.
2. Call `register_builtin_handlers`. Existing names win, and the report records
   them in `preserved`. Call order and manifest order are deterministic. Duplicate
   names *within* the built-in manifest always fail rather than being hidden.
3. Call `register_installed_handlers` explicitly if the host also supports third
   party entry points. Its existing sorted order and strict duplicate behavior
   remain unchanged: extensions cannot silently replace host or built-in names.

Use `collision="error"` when any overlap is an error. This API never replaces
registry internals or loosens the registry's ordinary duplicate checks.
`register_generic_defaults(registry)` remains available with strict duplicate
behavior, and now also accepts `services=` for correct constructor injection.

The built-in registrar is intentionally **not** installed as a
`galet_tools.handlers` entry point: existing hosts already register many of its
names before loading entry points. Automatically adding it there would break
those hosts on upgrade. A host adopts this composition API once; subsequent
built-in additions require no host changes. Lucy integration is the next part
of [Lucy #258](https://github.com/junwin/lucy/issues/258).

## Constructor ports and execution context

| Service | Use |
| --- | --- |
| `storage_resolver` | Storage/external roots for file, patch, repository and media tools |
| `sandbox_resolver` | Account-specific command working directories |
| `security_policy` | Command authorization and output limits |
| `image_api`, `video_api` | Optional injected media APIs; existing handlers retain their lazy provider fallback |
| `semantic_memory` | Semantic backend |
| `episodic_store` | Session/event/digest backend, including individual episodic operation tools |
| `procedural_memory` | Scoped context/skill backend |

Missing required constructor ports raise `MissingHandlerServiceError` on
`registry.create`, naming the handler and missing services. Definitions remain
available and unrelated tools work. Optional memory backends can be bound in
`HandlerServices`, or supplied by the host per execution:

```python
services = HandlerServices(
    episodic_store=shared_episodic_store,
    procedural_memory=shared_procedural_memory,
    semantic_memory=shared_semantic_memory,
)
handler = registry.create("procedural_memory", config=config)
context = services.execution_context()
context.update(account_name=trusted_account, conversation_id=conversation_id)
result = handler.execute(arguments, **context)
```

`execution_context()` returns only non-None memory services using the established
handler keyword names. The host merges request fields separately and must never
accept service objects or trusted account identity from tool arguments. Per-call
services take precedence according to the existing memory handlers' execution
contracts. A memory tool without a bound or per-call backend returns its existing
explicit unavailable-service error. Installing `galet-tools[memory]` supplies
memory implementation dependencies; backend configuration remains host-owned.

## Optional dependencies and package additions

Discovery imports lightweight handler definitions independently. It does not
import the optional `galet`, `galet_memory` or `mcp` runtimes. If a handler starts
requiring an optional import at definition time, its `BuiltinHandler` manifest
entry must declare the optional module root. A matching missing module skips
that handler, logs a warning and adds its reference/reason to
`report.unavailable`. Unexpected import errors and implementation defects
propagate; they are not silently treated as missing optional dependencies.

To add a supported built-in, add its class reference and explicit constructor
bindings to `builtin_handlers()` in `galet_tools.composition`. Required bindings
must name their service ports. Parameterless handlers need no bindings. If a
new category needs a new service, evolve `HandlerServices` and document it here;
a host must supply that new capability before using the tool. Automatic
discovery cannot manufacture services that the host does not have.
