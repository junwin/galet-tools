import pytest

from galet_memory import EpisodicEvent, JsonlEpisodicMemory, SqliteEpisodicMemory
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler


@pytest.fixture(params=[SqliteEpisodicMemory, JsonlEpisodicMemory])
def memory(request, tmp_path):
    with request.param(tmp_path / 'store') as memory:
        memory.create_session(account_name='acct', agent_name='lucy', session_id='s')
        yield memory


def linked(memory, correlation='c', session='s'):
    events = memory.add_events(session, [EpisodicEvent('user', 'Request'), EpisodicEvent('assistant', 'Response')])
    for event in events:
        memory.link_event(correlation, session, event.event_id)
    return events


def call(handler, **args):
    return handler.execute({'action': 'invalidate_events', 'session_id': 's', 'correlation_id': 'c', **args},
                           account_name='acct')


def test_invalidate_request_and_responses_keep_unrelated_and_retain_originals(memory):
    targets = linked(memory)
    keep = linked(memory, correlation='keep')
    handler = EpisodicMemoryHandler(memory)
    before = handler.execute({'action': 'get_session', 'session_id': 's', 'event_scope': 'all'}, account_name='acct')
    result = call(handler, expected_last_event_id=before['session']['last_event_id'])
    assert result['ok'] and result['status'] == 'invalidated'
    assert result['event_ids'] == [event.event_id for event in targets]
    assert result['event_count'] == 2
    assert memory.get_session('s', event_scope='all').events == keep
    assert len(memory.get_session('s', event_scope='raw').events) == 5
    repeated = call(handler, expected_last_event_id=before['session']['last_event_id'])
    assert repeated['status'] == 'already_invalidated'
    assert repeated['marker_event_id'] == result['marker_event_id']
    assert len(memory.get_session('s', event_scope='raw').events) == 5
    recall = handler.execute({'action': 'recall', 'session_id': 's'}, account_name='acct')
    assert [e['event_id'] for e in recall['events']] == [e.event_id for e in keep]


def test_missing_target_and_conflict(memory):
    linked(memory)
    assert call(EpisodicMemoryHandler(memory), correlation_id='absent')['status'] == 'not_found'
    conflict = call(EpisodicMemoryHandler(memory), expected_last_event_id='wrong')
    assert not conflict['ok'] and 'EpisodicConcurrencyError' in conflict['error']
    assert len(memory.get_session('s', event_scope='all').events) == 2


def test_unowned_session_and_account_override_rejected(memory):
    memory.create_session(account_name='other', agent_name='lucy', session_id='other')
    linked(memory, session='other')
    handler = EpisodicMemoryHandler(memory)
    assert not call(handler, session_id='other')['ok']
    assert not call(handler, account_name='other', session_id='other')['ok']
    assert len(memory.get_session('other').events) == 2
    # An account cannot remove another account's events through a bulk action.
    result = handler.execute({'action': 'delete_sessions', 'session_id': ['s', 'other']}, account_name='acct')
    assert not result['ok']
    assert memory.session_exists('s')


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
        {'action': 'invalidate_events', 'session_id': 's', 'correlation_id': 'c'},
        account_name='acct', episodic_store=memory)
    assert result['status'] == 'invalidated'
    schema = EpisodicMemoryHandler.tool_def()['parameters']
    assert 'invalidate_events' in schema['properties']['action']['enum']
    assert schema['properties']['expected_last_event_id']['anyOf'] == [{'type': 'string'}, {'type': 'null'}]
    assert set(schema['properties']) == set(schema['required'])


def test_tool_does_not_expose_raw_internal_events(memory):
    linked(memory)
    handler = EpisodicMemoryHandler(memory)
    call(handler)
    result = handler.execute({'action': 'get_session', 'session_id': 's', 'event_scope': 'raw'}, account_name='acct')
    assert not result['ok'] and 'event_scope must' in result['error']
