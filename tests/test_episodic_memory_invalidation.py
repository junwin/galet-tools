import pytest

from galet_memory import NewEvent, JsonlEpisodicMemory, SqliteEpisodicMemory
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler


@pytest.fixture(params=[SqliteEpisodicMemory, JsonlEpisodicMemory])
def memory(request, tmp_path):
    with request.param(tmp_path / 'store') as memory:
        memory.create_session(account_name='acct', session_id='s')
        yield memory


def linked(memory, correlation='c', session='s', account='acct'):
    return memory.append_events(account_name=account, session_id=session, events=[
        NewEvent('user', 'Request', account, correlation_ids=(correlation,)),
        NewEvent('assistant', 'Response', 'lucy', correlation_ids=(correlation,)),
    ])


def call(handler, **args):
    return handler.execute({'action': 'invalidate_exchange', 'session_id': 's', 'correlation_id': 'c', **args},
                           account_name='acct')


def test_invalidate_request_and_responses_keep_unrelated_and_retain_originals(memory):
    targets = linked(memory)
    keep = linked(memory, correlation='keep')
    handler = EpisodicMemoryHandler(memory)
    before = handler.execute({'action': 'get_session', 'session_id': 's'}, account_name='acct')
    assert 'events' not in before['session']
    result = call(handler, expected_last_event_id=before['session']['last_event_id'])
    assert result['ok'] and result['status'] == 'invalidated'
    assert result['event_ids'] == [event.event_id for event in targets]
    assert result['event_count'] == 2
    assert list(memory.get_recent_events(account_name='acct', session_id='s').events) == keep
    assert len(memory.get_audit_snapshot(account_name='acct', session_id='s').events) == 5
    repeated = call(handler, expected_last_event_id=before['session']['last_event_id'])
    assert repeated['status'] == 'already_invalidated'
    assert repeated['marker_event_id'] == result['marker_event_id']
    assert len(memory.get_audit_snapshot(account_name='acct', session_id='s').events) == 5
    recent = handler.execute({'action': 'get_recent_events', 'session_id': 's'}, account_name='acct')
    assert [e['event_id'] for e in recent['events']] == [e.event_id for e in keep]


def test_missing_target_and_conflict(memory):
    linked(memory)
    assert call(EpisodicMemoryHandler(memory), correlation_id='absent')['status'] == 'not_found'
    conflict = call(EpisodicMemoryHandler(memory), expected_last_event_id='wrong')
    assert not conflict['ok'] and 'EpisodicConcurrencyError' in conflict['error']
    assert len(memory.get_recent_events(account_name='acct', session_id='s').events) == 2


def test_unowned_session_and_account_override_rejected(memory):
    memory.create_session(account_name='other', session_id='other')
    linked(memory, session='other', account='other')
    handler = EpisodicMemoryHandler(memory)
    assert not call(handler, session_id='other')['ok']
    assert not call(handler, account_name='other', session_id='other')['ok']
    assert len(memory.get_recent_events(account_name='other', session_id='other').events) == 2
    result = handler.execute({'action': 'delete_sessions', 'session_ids': ['s', 'other']}, account_name='acct')
    assert not result['ok']
    assert memory.get_session(account_name='acct', session_id='s') is not None


@pytest.mark.parametrize('args,error', [
    ({'session_id': ''}, 'session_id is required'),
    ({'session_id': ['s']}, 'session_id is required'),
    ({'correlation_id': ''}, 'correlation_id is required'),
    ({'expected_last_event_id': 123}, 'expected_last_event_id must'),
])
def test_invalid_request(memory, args, error):
    result = call(EpisodicMemoryHandler(memory), **args)
    assert not result['ok'] and error in result['error']


def test_context_injection_and_schema(memory):
    linked(memory)
    result = EpisodicMemoryHandler().execute(
        {'action': 'invalidate_exchange', 'session_id': 's', 'correlation_id': 'c'},
        account_name='acct', episodic_store=memory)
    assert result['status'] == 'invalidated'
    schema = EpisodicMemoryHandler.tool_def()['parameters']
    assert 'invalidate_exchange' in schema['properties']['action']['enum']
    assert schema['properties']['expected_last_event_id']['anyOf'] == [{'type': 'string'}, {'type': 'null'}]
    assert schema['required'] == ['action']


def test_tool_does_not_expose_raw_internal_events(memory):
    handler = EpisodicMemoryHandler(memory)
    for args in ({'action': 'get_audit_snapshot'}, {'action': 'get_session', 'session_id': 's', 'event_scope': 'raw'}):
        assert not handler.execute(args, account_name='acct')['ok']
