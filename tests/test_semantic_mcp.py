import json
from dataclasses import replace

import pytest

from galet_memory import build_memory
from galet_tools.host.config import GaletConfigError, load_config
from galet_tools.mcp.server import GaletMcpError, dispatch_call, resolve_startup_scope


class Embeddings:
    def __init__(self, profile):
        self.profile = profile

    def embed(self, texts, *, model):
        return [[1.0] + [0.0] * 1535 for text in texts]


@pytest.fixture
def semantic_config(tmp_path, monkeypatch):
    import galet_memory.assembly as assembly
    monkeypatch.setattr(assembly, 'galet_embedding_factory', lambda: Embeddings)
    notes = tmp_path / 'notes'
    notes.mkdir()
    note = notes / 'test.md'
    note.write_text('An orchard full of apples.')
    raw = {
        'config_version': 1,
        'external_roots': {'data': str(tmp_path), 'obsidian': str(notes)},
        'embedding_profiles': {'test': {'provider': 'test', 'model': 'test-model', 'dimensions': 1536}},
        'memory': {'semantic': {'metadata_version': 3, 'embedding_profile': 'test',
            'database': {'external_root': 'data', 'relative_path': 'semantic.sqlite', 'create': True}}},
    }
    with build_memory(raw) as memory:
        memory.ingest_file(account_name='acct', external_root='obsidian', relative_path='test.md', namespace='vol_7')
        memory.ingest_file(account_name='other', external_root='obsidian', relative_path='test.md', namespace='private')
    raw['memory']['semantic']['database']['create'] = False
    # These must never be opened by the semantic-only MCP configuration.
    raw['memory']['episodic'] = {'database': {'external_root': 'data', 'relative_path': 'missing.sqlite'}}
    path = tmp_path / 'memory.json'
    path.write_text(json.dumps(raw))
    config = tmp_path / 'mcp.json'
    config.write_text(json.dumps({'account': 'acct', 'allowlist': ['semantic_memory'],
        'memory_config_path': str(path), 'storage_root': str(tmp_path),
        'storage_namespace': 'unused', 'sandbox_root': str(tmp_path)}))
    return load_config(config), note, path


@pytest.fixture
def all_memory_config(semantic_config):
    config, note, path = semantic_config
    raw = json.loads(path.read_text())
    raw['memory'].update({
        'episodic': {'database': {'external_root': 'data', 'relative_path': 'episodic.sqlite', 'create': True}},
        'procedural': {'root': {'external_root': 'data', 'relative_path': '.'},
            'context_resolution': 'most_specific', 'layout': {
                'global_contexts': 'contexts', 'account_contexts': 'contexts/{account}',
                'project_contexts': None, 'global_skills': 'skills',
                'account_skills': 'skills/{account}', 'project_skills': None,
            }},
        'working': {'database': {'external_root': 'data', 'relative_path': 'working.sqlite', 'create': True}},
    })
    path.write_text(json.dumps(raw))
    return replace(config, allowlist=['semantic_memory', 'episodic_memory', 'procedural_memory']), note, path


def memory_call(scope, name, args):
    result = dispatch_call(scope, name, args)
    assert not result['isError'], result
    payload = json.loads(result['content'][0]['text'])
    assert payload['ok'], payload
    return payload


def call(scope, args):
    result = dispatch_call(scope, 'semantic_memory', args)
    assert not result['isError'], result
    return json.loads(result['content'][0]['text'])


def test_v3_recall_through_mcp_uses_configured_model_roots_and_account(semantic_config):
    config, note, _ = semantic_config
    scope, definitions = resolve_startup_scope(config)
    try:
        assert [d['name'] for d in definitions] == ['semantic_memory']
        assert definitions[0]['inputSchema']['required'] == ['action']
        result = call(scope, {'action': 'recall', 'query': 'apples'})
        assert result['ok'] and result['count'] == 1
        assert result['documents'][0]['path'] == str(note)
        assert result['documents'][0]['snippet'] == note.read_text()
        assert call(scope, {'action': 'namespaces'})['namespaces'] == ['vol_7']
        assert call(scope, {'action': 'recall', 'query': 'apples', 'namespaces': ['private']})['count'] == 0
        rejected = dispatch_call(scope, 'semantic_memory', {'action': 'namespaces', 'account_name': 'other'})
        assert rejected['isError']
        note.write_text('The orchard text changed after indexing.')
        assert call(scope, {'action': 'recall', 'query': 'apples'})['documents'][0]['snippet'] == note.read_text()
        note.unlink()
        missing = call(scope, {'action': 'recall', 'query': 'apples'})
        assert missing['documents'] == []
        assert missing['metadata']['unavailable_resources']
    finally:
        scope.close()
    assert scope.memory_runtime._closed
    assert not (note.parent.parent / 'missing.sqlite').exists()


def test_semantic_startup_rejects_version_mismatch(semantic_config):
    config, _, path = semantic_config
    raw = json.loads(path.read_text())
    raw['memory']['semantic']['metadata_version'] = 2
    path.write_text(json.dumps(raw))
    with pytest.raises(GaletMcpError, match='metadata version mismatch'):
        resolve_startup_scope(config)


@pytest.mark.parametrize('memory_path', [None, 'relative.json'])
def test_semantic_requires_absolute_config_path(tmp_path, memory_path):
    path = tmp_path / 'mcp.json'
    path.write_text(json.dumps({'account': 'acct', 'allowlist': ['semantic_memory'],
        'memory_config_path': memory_path, 'storage_root': str(tmp_path),
        'storage_namespace': 'data', 'sandbox_root': str(tmp_path)}))
    with pytest.raises(GaletConfigError, match='memory_config_path'):
        load_config(path)


def test_semantic_mcp_over_http(all_memory_config, monkeypatch):
    import asyncio
    import socket
    import threading
    import time

    import uvicorn
    from galet_tools.mcp import server, smoke

    config, note, _ = all_memory_config
    monkeypatch.setattr(server, 'load_config', lambda path: config)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    url = f'http://127.0.0.1:{listener.getsockname()[1]}/mcp'
    servers, errors = [], []

    def run(app, **kwargs):
        instance = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
        servers.append(instance)
        instance.run(sockets=[listener])

    monkeypatch.setattr(uvicorn, 'run', run)

    def serve():
        try:
            server.serve()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not errors and not (servers and servers[0].started) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not errors, errors
        assert servers and servers[0].started
        tools = asyncio.run(smoke._fetch_tools(url, 10))
        assert {t.name for t in tools} == set(config.allowlist)
        response = asyncio.run(smoke._call_tool(url, 10, 'semantic_memory',
            {'action': 'recall', 'query': 'apples', 'namespaces': ['vol_7']}))
        assert not response.is_error
        result = json.loads(response.content[0].text)
        assert result['ok'] and result['count'] == 1
        assert result['documents'][0]['path'] == str(note)
        assert result['documents'][0]['snippet'] == note.read_text()
        for tool, args in [
            ('procedural_memory', {'action': 'save_context', 'scope': 'account', 'context_name': 'http', 'text': 'HTTP context'}),
            ('procedural_memory', {'action': 'recall', 'context_name': 'http'}),
            ('episodic_memory', {'action': 'create_session', 'session_id': 'http-session'}),
            ('episodic_memory', {'action': 'append_event', 'session_id': 'http-session',
                'event': {'role': 'user', 'actor': 'acct', 'content': 'HTTP event'}}),
            ('episodic_memory', {'action': 'get_recent_events', 'session_id': 'http-session'}),
        ]:
            response = asyncio.run(smoke._call_tool(url, 10, tool, args))
            assert not response.is_error
            payload = json.loads(response.content[0].text)
            assert payload['ok'], payload
            if args['action'] == 'recall':
                assert payload['memory']['text'] == 'HTTP context'
            if args['action'] == 'get_recent_events':
                assert payload['events'][0]['content'] == 'HTTP event'

    finally:
        if servers:
            servers[0].should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()
    assert not errors, errors


def test_embedding_failure_is_logged_with_mcp_fallback_summary(semantic_config, caplog):
    import logging

    config, _, _ = semantic_config
    caplog.set_level(logging.INFO)
    scope, _ = resolve_startup_scope(config)

    class Unavailable:
        def embed(self, *args, **kwargs):
            raise ConnectionError('embedding service unavailable')

    try:
        scope.handlers['semantic_memory'].memory.embeddings = Unavailable()
        result = call(scope, {'action': 'recall', 'query': 'apples'})
        assert result['metadata']['backend'] == 'keyword'
        assert 'mcp_semantic_ready' in caplog.text
        assert 'provider=test model=test-model dimensions=1536' in caplog.text
        assert 'mcp_call_start' in caplog.text
        assert 'backend=keyword reason=embedding_provider_unavailable' in caplog.text
        assert 'duration_ms=' in caplog.text and 'call_id=' in caplog.text
        assert 'apples' not in caplog.text
    finally:
        scope.close()


def test_one_shared_runtime_persists_all_memory_components(all_memory_config, monkeypatch):
    import galet_memory
    from galet_memory import WorkingRunUnavailable

    config, note, _ = all_memory_config
    original = galet_memory.build_memory
    built = []
    def build(*args, **kwargs):
        runtime = original(*args, **kwargs)
        built.append(runtime)
        return runtime
    monkeypatch.setattr(galet_memory, 'build_memory', build)
    scope, _ = resolve_startup_scope(config)
    runtime = scope.memory_runtime
    assert built == [runtime]
    assert scope.handlers['semantic_memory'].memory is runtime.semantic
    assert scope.handlers['episodic_memory'].memory is runtime.episodic
    assert scope.handlers['procedural_memory'].memory is runtime.procedural
    try:
        memory_call(scope, 'procedural_memory', {'action': 'save_context', 'scope': 'global', 'context_name': 'dev', 'text': 'Global'})
        memory_call(scope, 'procedural_memory', {'action': 'save_context', 'scope': 'account', 'context_name': 'dev', 'text': 'Account'})
        assert (note.parent.parent / 'contexts/acct/dev.md').read_text().endswith('Account')
        assert memory_call(scope, 'procedural_memory', {'action': 'recall', 'context_name': 'dev'})['memory']['text'] == 'Account'
        memory_call(scope, 'episodic_memory', {'action': 'create_session', 'session_id': 'shared'})
        memory_call(scope, 'episodic_memory', {'action': 'append_event', 'session_id': 'shared',
            'event': {'role': 'user', 'actor': 'acct', 'content': 'Persisted event'}})
        runtime.working.start_run('acct', 'run')
        runtime.working.put('acct', 'run', 'status', {'ready': True}, expected_version=0)
        with pytest.raises(WorkingRunUnavailable):
            runtime.working.get('other', 'run', 'status')
        for name in config.allowlist:
            assert dispatch_call(scope, name, {'action': 'recall', 'account_name': 'other'})['isError']
    finally:
        scope.close()
    assert runtime._closed
    reopened, _ = resolve_startup_scope(config)
    try:
        assert memory_call(reopened, 'episodic_memory', {'action': 'get_recent_events', 'session_id': 'shared'})['events'][0]['content'] == 'Persisted event'
        assert memory_call(reopened, 'procedural_memory', {'action': 'recall', 'context_name': 'dev'})['memory']['text'] == 'Account'
        assert call(reopened, {'action': 'recall', 'query': 'apples'})['count'] == 1
        assert reopened.memory_runtime.working.get('acct', 'run', 'status').value == {'ready': True}
    finally:
        reopened.close()


def test_allowlisted_component_must_exist_in_shared_config(semantic_config):
    config, _, _ = semantic_config
    config = replace(config, allowlist=['procedural_memory'])
    with pytest.raises(GaletMcpError, match='does not enable procedural'):
        resolve_startup_scope(config)


def test_shared_config_rejects_legacy_overrides(semantic_config):
    config, _, _ = semantic_config
    with pytest.raises(GaletMcpError, match='cannot be combined'):
        resolve_startup_scope(replace(config, episodic_memory_db_path='/legacy.sqlite'))


def test_failed_handler_binding_closes_shared_runtime(semantic_config, monkeypatch):
    from galet_tools.host import memory
    config, _, _ = semantic_config
    original = memory.build_configured_memory
    built = []
    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        built.append(result)
        return result
    def fail(*args):
        raise RuntimeError('binding failed')
    monkeypatch.setattr(memory, 'build_configured_memory', build)
    monkeypatch.setattr(memory, 'memory_handlers', fail)
    with pytest.raises(RuntimeError, match='binding failed'):
        resolve_startup_scope(config)
    assert built[0]._closed


def test_paired_example_configs_build_all_components(tmp_path, monkeypatch):
    from pathlib import Path
    import galet_memory.assembly as assembly
    monkeypatch.setattr(assembly, 'galet_embedding_factory', lambda: Embeddings)
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / 'galet-memory-mcp.example.json').read_text())
    raw['external_roots'] = {'memory_test': str(tmp_path), 'obsidian': str(tmp_path)}
    (tmp_path / 'digests').mkdir()
    memory_path = tmp_path / 'memory.json'
    memory_path.write_text(json.dumps(raw))
    mcp = json.loads((root / 'galet-mcp.example.json').read_text())
    mcp['memory_config_path'] = str(memory_path)
    mcp_path = tmp_path / 'mcp.json'
    mcp_path.write_text(json.dumps(mcp))
    scope, _ = resolve_startup_scope(load_config(mcp_path))
    try:
        assert all(getattr(scope.memory_runtime, kind) is not None
                   for kind in ('semantic', 'episodic', 'procedural', 'working'))
        assert scope.memory_runtime.config.procedural.layout['account_contexts'] == 'contexts/{account}'
    finally:
        scope.close()


def test_shared_config_conflict_is_reported_by_loader(semantic_config, tmp_path):
    config, _, _ = semantic_config
    path = tmp_path / 'conflict.json'
    path.write_text(json.dumps({'account': 'acct', 'allowlist': ['episodic_memory'],
        'memory_config_path': config.memory_config_path,
        'episodic_memory_db_path': str(tmp_path / 'legacy.sqlite'),
        'storage_root': str(tmp_path), 'storage_namespace': 'data', 'sandbox_root': str(tmp_path)}))
    with pytest.raises(GaletConfigError, match='cannot be combined'):
        load_config(path)


def test_nonsemantic_tools_do_not_construct_embedding_provider(all_memory_config, monkeypatch):
    import galet_memory.assembly as assembly
    config, _, _ = all_memory_config
    monkeypatch.setattr(assembly, 'galet_embedding_factory', lambda: pytest.fail('semantic provider must not be built'))
    scope, definitions = resolve_startup_scope(replace(config, allowlist=['episodic_memory', 'procedural_memory']))
    try:
        assert scope.memory_runtime.semantic is None
        assert scope.memory_runtime.working is not None
        assert {d['name'] for d in definitions} == {'episodic_memory', 'procedural_memory'}
    finally:
        scope.close()


def test_all_component_preflight_precedes_database_creation(all_memory_config):
    config, note, path = all_memory_config
    raw = json.loads(path.read_text())
    raw['memory']['working']['database'] = {
        'external_root': 'data', 'relative_path': 'missing-working.sqlite', 'create': False,
    }
    path.write_text(json.dumps(raw))
    with pytest.raises(GaletMcpError, match='cannot configure memory'):
        resolve_startup_scope(config)
    assert not (note.parent.parent / 'episodic.sqlite').exists()
