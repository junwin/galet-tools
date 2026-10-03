import pytest

from galet_memory import FileProceduralMemory
from galet_tools.tools.procedural_memory_handler import ProceduralMemoryHandler


@pytest.fixture
def handler(tmp_path):
    return ProceduralMemoryHandler(FileProceduralMemory(tmp_path, context_resolution='most_specific'))


def call(handler, action, **args):
    return handler.execute({'action': action, **args}, account_name='acct')


def test_global_account_and_project_contexts_and_skill_overrides(handler):
    assert call(handler, 'save_skill', scope='global', skill_name='review', text='Global review',
                frontmatter={'mandatory_tools': ['file_load']})['ok']
    assert call(handler, 'save_context', scope='global', context_name='dev', text='Global context',
                frontmatter={'imports': ['review'], 'search_namespaces': ['documents']})['ok']
    global_result = call(handler, 'recall', context_name='dev')['memory']
    assert global_result['text'] == 'Global context'
    assert global_result['skills'][0]['text'] == 'Global review'
    assert global_result['required_tools'] == ['file_load']
    assert call(handler, 'save_skill', scope='account', skill_name='review', text='Account review')['ok']
    assert call(handler, 'save_context', scope='account', context_name='dev', text='Account context',
                frontmatter={'imports': ['review', 'missing']})['ok']
    account_result = call(handler, 'recall', context_name='dev')['memory']
    assert account_result['text'] == 'Account context'
    assert account_result['skills'][0]['text'] == 'Account review'
    assert account_result['missing_imports'] == ['missing']
    assert call(handler, 'save_context', scope='project', project_name='shop', context_name='dev', text='Shop')['ok']
    assert call(handler, 'recall', context_name='dev', project_name='shop')['memory']['text'] == 'Shop'
    # Global definitions remain available to another execution account.
    other = handler.execute({'action': 'recall', 'context_name': 'dev'}, account_name='other')['memory']
    assert other['text'] == 'Global context'
    assert other['skills'][0]['text'] == 'Global review'


def test_list_raw_reads_effective_reads_and_inherited_updates(handler):
    call(handler, 'save_context', scope='global', context_name='dev', text='Original', frontmatter={'imports': ['one']})
    call(handler, 'save_context', scope='account', context_name='local', text='Local')
    assert call(handler, 'list_contexts')['context_names'] == ['dev', 'local']
    assert call(handler, 'list_contexts', scope='global')['context_names'] == ['dev']
    assert call(handler, 'list_contexts', scope='account')['context_names'] == ['local']
    assert call(handler, 'read_context', context_name='dev')['text'] == 'Original'
    result = call(handler, 'update_context', context_name='dev', scope='account',
                  inherit_existing=True, frontmatter={'tag': 'new'})
    assert result['ok']
    assert call(handler, 'read_context', context_name='dev')['frontmatter'] == {'imports': ['one'], 'tag': 'new'}
    assert call(handler, 'read_context', context_name='dev')['text'] == 'Original'
    call(handler, 'update_context', scope='account', context_name='dev', text='Changed')
    assert call(handler, 'read_context', scope='account', context_name='dev')['text'] == 'Changed'
    assert call(handler, 'read_context', scope='global', context_name='dev')['text'] == 'Original'


def test_named_skills_and_execution_context_injection(handler):
    call(handler, 'save_skill', scope='account', skill_name='review', text='Inspect this')
    injected = ProceduralMemoryHandler()
    result = injected.execute({'action': 'recall', 'context_name': 'none', 'skill_names': ['review']},
                              account_name='acct', procedural_memory=handler.memory)
    assert result['ok']
    assert result['memory']['skills'][0]['text'] == 'Inspect this'
    assert 'Inspect this' in result['memory']['resolved_text']


@pytest.mark.parametrize('args,error', [
    ({'action': 'save_context', 'context_name': 'dev', 'text': 'X'}, 'writes require scope'),
    ({'action': 'save_skill', 'scope': 'global', 'text': 'X'}, 'skill_name is required'),
    ({'action': 'save_context', 'scope': 'global', 'context_name': 'dev'}, 'text is required'),
    ({'action': 'recall'}, 'context_name or skill_names'),
    ({'action': 'recall', 'context_name': 'dev', 'skill_names': 'review'}, 'skill_names must'),
    ({'action': 'recall', 'context_name': 'dev', 'scope': 'global'}, 'recall uses effective'),
    ({'action': 'read_context', 'context_name': 'absent'}, 'not found'),
    ({'action': 'save_context', 'scope': 'project', 'context_name': 'dev', 'text': 'X'}, 'project_name'),
    ({'action': 'save_context', 'scope': 'account', 'context_name': '../escape', 'text': 'X'}, 'invalid procedural name'),
    ({'action': 'save_context', 'scope': 'account', 'context_name': 'dev', 'text': 'X', 'frontmatter': []}, 'frontmatter'),
    ({'action': 'list_contexts', 'account_name': 'other'}, 'execution account'),
])
def test_invalid_arguments_do_not_write(handler, args, error):
    result = handler.execute(args, account_name='acct')
    assert not result['ok'] and error in result['error']
    assert list(handler.memory.repository.root.rglob('*.md')) == []


def test_missing_backend_and_management_capability():
    assert not ProceduralMemoryHandler().execute({'action': 'list_contexts'}, account_name='acct')['ok']
    assert 'does not support' in ProceduralMemoryHandler(object()).execute(
        {'action': 'list_contexts'}, account_name='acct')['error']
