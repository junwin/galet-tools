"""Disposable procedural scopes and correlation invalidation tool test.

    python -m pip install -e '.[memory]'
    python examples/memory_tools.py
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from galet_memory import EpisodicEvent, FileProceduralMemory, SqliteEpisodicMemory
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler
from galet_tools.tools.procedural_memory_handler import ProceduralMemoryHandler


def main():
    with TemporaryDirectory(prefix='galet-memory-tools-') as directory:
        procedural = ProceduralMemoryHandler(FileProceduralMemory(directory, context_resolution='most_specific'))
        def call(action, **args):
            result = procedural.execute({'action': action, **args}, account_name='demo')
            assert result['ok'], result
            return result
        call('save_skill', scope='global', skill_name='review', text='Global review')
        call('save_context', scope='global', context_name='dev', text='Global context',
             frontmatter={'imports': ['review']})
        global_result = call('recall', context_name='dev')['memory']
        call('save_skill', scope='account', skill_name='review', text='Account review')
        call('update_context', scope='account', context_name='dev', text='Account context', inherit_existing=True)
        account_result = call('recall', context_name='dev')['memory']
        assert global_result['text'] == 'Global context'
        assert global_result['skills'][0]['text'] == 'Global review'
        assert account_result['text'] == 'Account context'
        assert account_result['skills'][0]['text'] == 'Account review'
        with SqliteEpisodicMemory(Path(directory) / 'chat.sqlite') as memory:
            memory.create_session(account_name='demo', agent_name='lucy', session_id='test-session')
            for event in memory.add_events('test-session', [EpisodicEvent('user', 'Request'), EpisodicEvent('assistant', 'Response')]):
                memory.link_event('test-correlation', 'test-session', event.event_id)
            memory.append_event('test-session', EpisodicEvent('user', 'Keep this'))
            handler = EpisodicMemoryHandler(memory)
            args = {'action': 'invalidate_events', 'session_id': 'test-session', 'correlation_id': 'test-correlation'}
            result = handler.execute(args, account_name='demo')
            assert result['ok'] and result['event_count'] == 2, result
            assert [event.content for event in memory.get_session('test-session').events] == ['Keep this']
            assert handler.execute(args, account_name='demo')['status'] == 'already_invalidated'
            print(json.dumps({'global_context': global_result['text'], 'account_context': account_result['text'],
                              'account_skill': account_result['skills'][0]['text'], 'invalidation': result}, indent=2))


if __name__ == '__main__':
    main()
