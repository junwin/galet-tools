from pathlib import Path
import os

import pytest

from galet_tools.tools.text_replace_handler import TextReplaceHandler
from tests.conftest import FakeStorageResolver


def run(tmp_path, old='old', new='new', **overrides):
    handler = TextReplaceHandler(FakeStorageResolver(str(tmp_path/'resolver'), {'repo': str(tmp_path)}))
    return handler.execute({'external_root': 'repo', 'path': 'index.html',
                            'old_text': old, 'new_text': new, 'check_only': False, **overrides})


def test_image_filename_replacement_preserves_bytes_and_mode(tmp_path):
    target = tmp_path/'index.html'
    target.write_bytes(b'<!doctype html>\r\n<img src="assets/peruse-nouveautes-v6.jpg">\r\n')
    target.chmod(0o640)
    result = run(tmp_path, 'assets/peruse-nouveautes-v6.jpg', 'assets/New Arrivals.jpg')
    assert result['ok'] and result['applied']
    assert result['match_count'] == 1
    assert 'New Arrivals.jpg' in result['diff']
    assert target.read_bytes() == b'<!doctype html>\r\n<img src="assets/New Arrivals.jpg">\r\n'
    assert target.stat().st_mode & 0o777 == 0o640


def test_category_insertion_check_only_and_apply(tmp_path):
    target = tmp_path/'index.html'
    original = 'const categories=[\n  {id:"clothing"}\n];\n'
    target.write_text(original)
    new = 'const categories=[\n  {id:"new",gallery:"assets/New Arrivals/gallery.json"},'
    checked = run(tmp_path, 'const categories=[', new, check_only=True)
    assert checked['ok'] and not checked['applied']
    assert target.read_text() == original
    assert run(tmp_path, 'const categories=[', new)['applied']
    assert 'id:"new"' in target.read_text()


@pytest.mark.parametrize('text,old,count', [('old old','old',2), ('aaa','aa',2), ('unchanged','old',0)])
def test_absent_or_ambiguous_is_unchanged(tmp_path, text, old, count):
    target=tmp_path/'index.html';target.write_text(text)
    result=run(tmp_path, old)
    assert result['error_code']=='match_not_unique'
    assert result['match_count']==count
    assert target.read_text()==text


@pytest.mark.parametrize('path', ['../outside', '/etc/passwd', r'C:\file', r'dir\file'])
def test_invalid_paths(tmp_path,path):
    assert run(tmp_path,path=path)['error_code']=='invalid_path'


def test_symlink_escape_and_missing_file(tmp_path):
    outside=tmp_path.parent/'outside.txt';outside.write_text('old')
    (tmp_path/'index.html').symlink_to(outside)
    assert not run(tmp_path)['ok']
    assert outside.read_text()=='old'
    (tmp_path/'index.html').unlink()
    assert not run(tmp_path)['ok']


@pytest.mark.parametrize('data', [b'\xff', b'old\0binary'])
def test_nontext_not_modified(tmp_path,data):
    p=tmp_path/'index.html';p.write_bytes(data)
    assert run(tmp_path)['error_code']=='invalid_encoding'
    assert p.read_bytes()==data


def test_bounded_preview_and_no_final_newline(tmp_path):
    p=tmp_path/'index.html';p.write_text('old'+'x'*10000)
    result=run(tmp_path)
    assert len(result['diff'])<=4000 and result['diff_truncated']
    assert p.read_text()=='new'+'x'*10000


def test_changed_source_is_not_overwritten(tmp_path, monkeypatch):
    p=tmp_path/'index.html';p.write_text('old')
    original=Path.read_bytes;reads=0
    def read(path):
        nonlocal reads
        if path==p:
            reads+=1
            if reads==2:p.write_text('someone else')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',read)
    result=run(tmp_path)
    assert result['error_code']=='source_changed'
    assert p.read_text()=='someone else'
    assert sorted(f.name for f in tmp_path.iterdir())==['index.html','resolver']


def test_strict_schema_and_registry():
    from galet_tools.register_generic_defaults import register_generic_defaults
    from galet_tools.framework.handler_registry import HandlerRegistry
    schema=TextReplaceHandler.tool_def()['parameters']
    assert set(schema['required'])==set(schema['properties'])
    reg=HandlerRegistry();register_generic_defaults(reg)
    assert 'text_replace' in reg.tool_names()
