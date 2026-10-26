import json
import logging
from dataclasses import replace

import pytest
from galet_memory import SqliteEpisodicMemory, NewEvent
from galet_tools.host.config import GaletConfig
from galet_tools.mcp.server import dispatch_call, resolve_startup_scope
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler
from galet_tools.tools.episodic_operations import EPISODIC_OPERATION_HANDLERS


@pytest.fixture
def existing_sessions(tmp_path):
    database = tmp_path / 'lucy-episodic.sqlite'
    with SqliteEpisodicMemory(database) as memory:
        for sid in ('one', 'two'):
            memory.create_session(account_name='junwin', session_id=sid)
        memory.create_session(account_name='other', session_id='private')
        memory.append_event(account_name='junwin', session_id='one',
            event=NewEvent('user', 'Original message', 'junwin', correlation_ids=('request',)))
    path = tmp_path / 'memory.json'
    path.write_text(json.dumps({'config_version': 1, 'external_roots': {'data': str(tmp_path)},
        'memory': {'episodic': {'database': {'external_root': 'data',
            'relative_path': database.name, 'create': False}}}}))
    return GaletConfig(account='junwin',
        allowlist=['episodic_list_sessions', 'episodic_get_session', 'episodic_get_recent_events'],
        memory_config_path=str(path), storage_root=str(tmp_path), storage_namespace='unused',
        sandbox_root=str(tmp_path), external_roots={}, host='127.0.0.1', port=8765, fonts=[]), database


def call(scope, name, args):
    result = dispatch_call(scope, name, args)
    assert not result['isError'], result
    data = json.loads(result['content'][0]['text'])
    assert data['ok'], data
    return data


def test_simple_tools_list_preexisting_account_sessions_and_read_events(existing_sessions, caplog):
    config, database = existing_sessions
    caplog.set_level(logging.INFO)
    scope, definitions = resolve_startup_scope(config)
    try:
        assert scope.tool_names == set(config.allowlist)
        schema = next(d['inputSchema'] for d in definitions if d['name'] == 'episodic_list_sessions')
        assert set(schema['properties']) == {'count', 'cursor'}
        assert schema['required'] == []
        assert schema['properties']['count']['default'] == 20
        first = call(scope, 'episodic_list_sessions', {})
        assert {s['session_id'] for s in first['sessions']} == {'one', 'two'}
        assert first['account_name'] == 'junwin'
        assert first['metadata']['database_path'] == str(database)
        page = call(scope, 'episodic_list_sessions', {'count': 1, 'cursor': ''})
        next_page = call(scope, 'episodic_list_sessions', {'count': 1, 'cursor': page['next_cursor']})
        assert {page['sessions'][0]['session_id'], next_page['sessions'][0]['session_id']} == {'one', 'two'}
        assert call(scope, 'episodic_get_session', {'session_id': 'one'})['session']['session_id'] == 'one'
        events = call(scope, 'episodic_get_recent_events', {'session_id': 'one', 'before_event_id': ''})
        assert events['events'][0]['content'] == 'Original message'
        assert f'database={database}' in caplog.text and 'has_sessions=True' in caplog.text
        assert 'Original message' not in caplog.text
        assert dispatch_call(scope, 'episodic_list_sessions', {'account_name': 'other'})['isError']
        forbidden = dispatch_call(scope, 'episodic_get_session', {'session_id': 'private'})
        assert not json.loads(forbidden['content'][0]['text'])['ok']
        assert dispatch_call(scope, 'episodic_delete_session', {'session_id': 'one'})['isError']
        spoofed = dispatch_call(scope, 'episodic_list_sessions', {'action': 'delete_session', 'session_id': 'one'})
        assert not json.loads(spoofed['content'][0]['text'])['ok']
    finally:
        scope.close()
    assert scope.memory_runtime._closed


def test_count_zero_is_explicit_and_diagnosable(existing_sessions):
    config, database = existing_sessions
    with SqliteEpisodicMemory(database, initialize_schema=False) as memory:
        result = EpisodicMemoryHandler(memory).execute(
            {'action': 'list_sessions', 'count': 0, 'cursor': ''}, account_name='junwin')
        assert result['ok'] and result['sessions'] == []
        assert result['metadata']['reason'] == 'count_zero'
        assert result['metadata']['database_path'] == str(database)
        assert memory.list_sessions(account_name='junwin').items


def test_operation_handler_defaults_and_exchange_invalidation(existing_sessions):
    _, database = existing_sessions
    handlers = {cls.ACTION: cls for cls in EPISODIC_OPERATION_HANDLERS}
    with SqliteEpisodicMemory(database, initialize_schema=False) as memory:
        recent = handlers['get_recent_events'](memory)
        assert recent.tool_def()['parameters']['properties']['count']['default'] == 10
        assert recent.tool_def()['parameters']['required'] == ['session_id']
        invalidation = handlers['invalidate_exchange'](memory)
        result = invalidation.execute({'session_id': 'one', 'correlation_id': 'request'}, account_name='junwin')
        assert result['ok'] and result['event_count'] == 1
        assert recent.execute({'session_id': 'one'}, account_name='junwin')['events'] == []


def test_operation_tools_in_legacy_mode_share_and_close_backend(existing_sessions, monkeypatch):
    config, database = existing_sessions
    scope, _ = resolve_startup_scope(replace(config, memory_config_path=None,
                                            episodic_memory_db_path=str(database)))
    try:
        assert call(scope, 'episodic_list_sessions', {})['count'] == 2
        store = scope.handlers['episodic_list_sessions'].memory
        assert scope.handlers['episodic_get_session'].memory is store
        original_close = store.close
        closed = []
        def close():
            closed.append(True)
            original_close()
        monkeypatch.setattr(store, 'close', close)
    finally:
        scope.close()
    assert closed == [True]
