"""Real SQLite/JSONL integration of model-facing explicit contracts."""
import pytest
from galet_memory import JsonlEpisodicMemory, SqliteEpisodicMemory, CurationService, DigestMatch
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler
from galet_tools.tools.reset_session_handler import ResetSessionHandler


@pytest.fixture(params=[SqliteEpisodicMemory, JsonlEpisodicMemory])
def setup(request, tmp_path):
    with request.param(tmp_path / 'store') as memory:
        handler = EpisodicMemoryHandler(memory)
        def call(action, **args):
            return handler.execute({'action': action, **args}, account_name='acct')
        assert call('create_session', session_id='s', friendly_name='Chat')['ok']
        yield memory, handler, call


def append(call, text, role='user', actor='acct', **fields):
    result = call('append_event', session_id='s', event={'role': role, 'actor': actor, 'content': text, **fields})
    assert result['ok'], result
    return result['event']


def test_filtered_recent_payloads_correlations_and_pagination(setup):
    _, _, call = setup
    first = append(call, {'text': 'First', 'attachments': [{'uuid': 'image-1'}]}, correlation_ids=['c'])
    append(call, 'Tool report', role='tool', actor='processor', kind='report')
    second = append(call, 'Second', correlation_ids=['c', 'c2'])
    append(call, 'Answer', role='assistant', actor='peace', correlation_ids=['c'])
    third = append(call, 'Third')
    page = call('get_recent_events', session_id='s', count=2, event_kinds=['user_message'])
    assert page['ok'] and [e['event_id'] for e in page['events']] == [second['event_id'], third['event_id']]
    older = call('get_recent_events', session_id='s', count=2, event_kinds=['user_message'], before_event_id=page['before_event_id'])
    assert older['events'] == [first]
    assert first['content'] == {'text': 'First', 'attachments': [{'uuid': 'image-1'}]}
    assert first['correlation_ids'] == ['c'] and first['sequence'] > 0 and first['stored_at']
    assert call('get_event', session_id='s', event_id=first['event_id'])['event'] == first
    exchange = call('get_exchange', session_id='s', correlation_id='c')['exchange']
    assert len(exchange['events']) == 3
    assert len(call('get_recent_events', session_id='s', actors=['peace'])['events']) == 1
    assert call('get_event', session_id='s', event_id='absent')['event'] is None
    assert call('get_exchange', session_id='s', correlation_id='absent')['exchange'] is None


def test_period_occurrence_order_bounds_and_cursor(setup):
    _, _, call = setup
    end = append(call, 'Excluded', created_at='2026-10-03T00:00:00Z')
    late = append(call, 'Late', created_at='2026-10-02T00:00:00Z')
    early = append(call, 'Early', created_at='2026-10-01T00:00:00Z')
    args = dict(session_id='s', start='2026-10-01T00:00:00Z', end='2026-10-03T00:00:00Z', count=1)
    page = call('get_events_by_period', **args)
    assert page['ok'] and page['events'] == [early] and page['next_cursor']
    next_page = call('get_events_by_period', **args, cursor=page['next_cursor'])
    assert next_page['events'] == [late] and next_page['next_cursor'] is None
    assert end not in next_page['events']
    assert not call('get_events_by_period', **{**args, 'start': '2026-10-01T00:00:00'})['ok']


def test_metadata_updates_list_clear_delete_and_empty_tail_guard(setup):
    _, _, call = setup
    assert call('create_session', session_id='t')['ok']
    page = call('list_sessions', count=1)
    assert page['ok'] and page['next_cursor']
    page2 = call('list_sessions', count=1, cursor=page['next_cursor'])
    assert {page['sessions'][0]['session_id'], page2['sessions'][0]['session_id']} == {'s', 't'}
    assert call('update_session', session_id='s', changes={'context_name': 'dev', 'tags': ['keep']})['ok']
    updated = call('update_session', session_id='s', changes={'friendly_name': None, 'tags': [], 'metadata': {}})['session']
    assert updated['friendly_name'] is None and updated['context_name'] == 'dev' and updated['tags'] == []
    event = call('append_event', session_id='s', event={'role': 'user', 'actor': 'acct', 'content': False}, expected_last_event_id='')
    assert event['ok'] and event['event']['content'] is False
    conflict = call('clear_session_events', session_id='s', expected_last_event_id='')
    assert not conflict['ok'] and 'EpisodicConcurrencyError' in conflict['error']
    assert call('clear_session_events', session_id='s', expected_last_event_id=event['event']['event_id'])['removed_event_count'] == 1
    assert call('delete_session', session_id='s')['deleted'] is True
    assert call('delete_session', session_id='s')['deleted'] is False
    assert call('delete_sessions', session_ids=['t', 't'])['session_ids'] == ['t']


def test_batch_append_is_atomic_and_filters_validate(setup):
    _, _, call = setup
    batch = [{'role': 'user', 'actor': 'acct', 'content': {'n': i}, 'correlation_ids': ['c']} for i in range(2)]
    assert call('append_events', session_id='s', events=batch, expected_last_event_id='')['count'] == 2
    assert call('invalidate_exchange', session_id='s', correlation_id='c')['event_count'] == 2
    bad = call('append_events', session_id='s', events=[{**batch[0], 'correlation_ids': ['new']}, batch[1]])
    assert not bad['ok']
    assert call('get_recent_events', session_id='s')['events'] == []
    for args in ({'count': True}, {'count': -1}, {'actors': 'peace'}, {'event_kinds': [1]}):
        assert not call('get_recent_events', session_id='s', **args)['ok']
    assert call('get_recent_events', session_id='s', count=0)['events'] == []
    assert not call('append_event', session_id='s', event={'role': 'user', 'content': 'hi'})['ok']


def test_digest_provenance_and_context_reset_keep_history(setup):
    memory, _, call = setup
    append(call, 'Private exchange', correlation_ids=['c'])
    class Generator:
        def generate(self, request):
            return 'Summary of Private exchange'
    curation = CurationService(memory, Generator())
    archived = curation.archive(account_name='acct', session_id='s')
    digests = call('list_digests', session_id='s')
    assert digests['ok'] and len(digests['digests']) == 1
    digest_id = digests['digests'][0]['digest_id']
    assert call('get_digest', session_id='s', digest_id=digest_id)['digest']['text'] == archived.digest
    requests = []
    def search(request):
        requests.append(request)
        return [DigestMatch('s', archived.digest, metadata={'digest_id': digest_id})]
    memory.digest_search = search
    assert len(call('search_digests', query='Private')['matches']) == 1
    assert requests[-1].account_name == 'acct' and requests[-1].count == 3
    append(call, 'Later')
    reset = ResetSessionHandler(curation).execute({}, account_name='acct', conversation_id='s')
    assert reset['ok'] and call('get_recent_events', session_id='s')['events'] == []
    assert len(memory.get_transcript_snapshot(account_name='acct', session_id='s').events) >= 3
    invalidated = call('invalidate_exchange', session_id='s', correlation_id='c')
    assert digest_id in invalidated['invalidated_digest_ids']
    assert call('get_digest', session_id='s', digest_id=digest_id)['digest'] is None
    assert call('search_digests', query='Private')['matches'] == []


def test_all_session_scoped_operations_enforce_account(setup):
    memory, handler, call = setup
    memory.create_session(account_name='other', session_id='foreign')
    for action, args in [
        ('get_session', {}), ('get_recent_events', {}),
        ('get_events_by_period', {'start': '2026-10-01T00:00:00Z', 'end': '2026-10-02T00:00:00Z'}),
        ('get_event', {'event_id': 'e'}), ('get_exchange', {'correlation_id': 'c'}),
        ('invalidate_exchange', {'correlation_id': 'c'}), ('list_digests', {}),
        ('get_digest', {'digest_id': 'd'}), ('search_digests', {'query': 'Private'}),
        ('update_session', {'changes': {'friendly_name': 'Changed'}}),
        ('clear_session_events', {}), ('delete_session', {}),
        ('append_event', {'event': {'role': 'user', 'actor': 'acct', 'content': 'Oops'}}),
    ]:
        result = call(action, session_id='foreign', **args)
        assert not result['ok'], (action, result)
    assert call('list_sessions')['count'] == 1
    assert not handler.execute({'action': 'list_sessions', 'account_name': 'other'}, account_name='acct')['ok']
    assert not call('recall', session_id='s')['ok']
