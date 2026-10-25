import json

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
    assert scope.handlers['semantic_memory'].runtime._closed
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


def test_semantic_mcp_over_http(semantic_config, monkeypatch):
    import asyncio
    import socket
    import threading
    import time

    import uvicorn
    from galet_tools.mcp import server, smoke

    config, note, _ = semantic_config
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
        assert [t.name for t in tools] == ['semantic_memory']
        response = asyncio.run(smoke._call_tool(url, 10, 'semantic_memory',
            {'action': 'recall', 'query': 'apples', 'namespaces': ['vol_7']}))
        assert not response.is_error
        result = json.loads(response.content[0].text)
        assert result['ok'] and result['count'] == 1
        assert result['documents'][0]['path'] == str(note)
        assert result['documents'][0]['snippet'] == note.read_text()
    finally:
        if servers:
            servers[0].should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()
    assert not errors, errors
