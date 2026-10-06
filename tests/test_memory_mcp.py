import builtins
import json
from pathlib import Path

import pytest

from galet_memory import NewEvent, SqliteEpisodicMemory
from galet_tools.host.config import GaletConfig, GaletConfigError, load_config
from galet_tools.mcp.server import GaletMcpError, dispatch_call, resolve_startup_scope


def config(tmp_path, **overrides):
    values = dict(account='acct', allowlist=['procedural_memory', 'episodic_memory'],
                  storage_root=str(tmp_path), storage_namespace='data', external_roots={},
                  sandbox_root=str(tmp_path / 'sandbox'), host='127.0.0.1', port=8765, fonts=[])
    values.update(overrides)
    return GaletConfig(**values)


def payload(scope, name, args):
    result = dispatch_call(scope, name, args)
    assert not result['isError'], result
    return json.loads(result['content'][0]['text'])


def test_memory_tools_are_listed_and_callable_with_configured_roots(tmp_path):
    path = tmp_path / 'lucy-data/chat2.sqlite'
    path.parent.mkdir()
    with SqliteEpisodicMemory(path) as memory:
        memory.create_session(account_name='acct', session_id='s')
        memory.append_events(account_name='acct', session_id='s', events=[
            NewEvent('user', 'Request', 'acct', correlation_ids=('c',)),
            NewEvent('assistant', 'Response', 'lucy', correlation_ids=('c',)),
        ])
    settings = config(tmp_path, episodic_memory_db_path=str(path),
                      procedural_memory={'root': str(tmp_path / 'procedural')})
    scope, definitions = resolve_startup_scope(settings)
    try:
        assert {tool['name'] for tool in definitions} == {'procedural_memory', 'episodic_memory'}
        episodic_schema = next(tool['inputSchema'] for tool in definitions if tool['name'] == 'episodic_memory')
        assert 'invalidate_exchange' in episodic_schema['properties']['action']['enum']
        assert payload(scope, 'procedural_memory', {'action': 'save_skill', 'scope': 'global',
            'skill_name': 'review', 'text': 'Inspect it'})['ok']
        assert payload(scope, 'procedural_memory', {'action': 'save_context', 'scope': 'global',
            'context_name': 'dev', 'text': 'Global', 'frontmatter': {'imports': ['review']}})['ok']
        global_file = tmp_path / 'procedural/contexts/dev.md'
        assert global_file.is_file()
        assert payload(scope, 'procedural_memory', {'action': 'update_context', 'scope': 'account',
            'context_name': 'dev', 'inherit_existing': True, 'text': 'Account'})['ok']
        recalled = payload(scope, 'procedural_memory', {'action': 'recall', 'context_name': 'dev'})
        assert recalled['memory']['text'] == 'Account'
        assert recalled['memory']['skills'][0]['text'] == 'Inspect it'
        assert (tmp_path / 'procedural/contexts/acct/dev.md').is_file()
        before = payload(scope, 'episodic_memory', {'action': 'get_recent_events', 'session_id': 's'})
        assert len(before['events']) == 2
        invalidated = payload(scope, 'episodic_memory', {'action': 'invalidate_exchange', 'session_id': 's',
            'correlation_id': 'c', 'expected_last_event_id': before['last_event_id']})
        assert invalidated['status'] == 'invalidated' and invalidated['event_count'] == 2
        assert payload(scope, 'episodic_memory', {'action': 'get_recent_events', 'session_id': 's'})['events'] == []
    finally:
        scope.close()
    with SqliteEpisodicMemory(path) as memory:
        assert memory.get_recent_events(account_name='acct', session_id='s').events == ()
        assert len(memory.get_audit_snapshot(account_name='acct', session_id='s').events) == 3


@pytest.mark.parametrize('name', ['procedural_memory', 'episodic_memory'])
def test_mcp_account_cannot_be_overridden(tmp_path, name):
    scope, _ = resolve_startup_scope(config(tmp_path))
    try:
        result = dispatch_call(scope, name, {'action': 'list_contexts', 'account_name': 'other'})
        assert result['isError'] and 'fixed MCP account' in result['content'][0]['text']
    finally:
        scope.close()


def test_default_tools_do_not_import_memory_or_open_databases(tmp_path, monkeypatch):
    original_import = builtins.__import__
    def reject_memory(name, *args, **kwargs):
        if name.startswith('galet_memory'):
            raise ImportError('memory extra absent')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', reject_memory)
    scope, _ = resolve_startup_scope(config(tmp_path, allowlist=['file_load']))
    assert scope.tool_names == {'file_load'}
    assert not list(tmp_path.rglob('*.sqlite'))
    with pytest.raises(GaletMcpError, match='memory tools require'):
        resolve_startup_scope(config(tmp_path))


@pytest.mark.parametrize('options,error', [
    ({'episodic_memory_db_path': 'relative.sqlite'}, 'absolute path'),
    ({'procedural_memory': []}, 'must be an object'),
    ({'procedural_memory': {'root': 'relative'}}, 'absolute path'),
    ({'procedural_memory': {'layout': []}}, 'layout must be an object'),
    ({'procedural_memory': {'layout': {'wrong': 'contexts'}}}, 'unknown keys'),
    ({'procedural_memory': {'layout': {'global_contexts': 1}}}, 'strings or null'),
    ({'procedural_memory': {'context_resolution': 'wrong'}}, 'context_resolution'),
])
def test_memory_configuration_errors_are_reported(tmp_path, options, error):
    base = dict(account='acct', storage_root=str(tmp_path), storage_namespace='data', sandbox_root=str(tmp_path))
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({**base, **options}))
    with pytest.raises(GaletConfigError, match=error):
        load_config(path)
