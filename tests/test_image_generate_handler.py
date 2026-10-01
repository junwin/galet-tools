import base64
import io
from PIL import Image
import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock
from galet.imagegen_dto import ImageGenResponse, ImageResult
from galet_tools.tools.image_generate_handler import ImageGenerateHandler


def png_base64():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


def make_handler(tmp_path):
    resolver = SimpleNamespace(storage_base_dir=lambda: str(tmp_path))
    api = Mock()
    api.generate_image.return_value = ImageGenResponse(images=[ImageResult(b64_json=png_base64(), mime_type='image/png')], model='gpt-image-1')
    return ImageGenerateHandler(resolver, api), api


def upload(tmp_path, account='john'):
    image_id = str(uuid.uuid4())
    directory = tmp_path / 'images' / account
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (image_id + '.png')).write_bytes(b'png-input')
    (directory / (image_id + '.json')).write_text(json.dumps({'id': image_id, 'account': account, 'mime_type': 'image/png'}))
    return image_id


def test_text_generation_calls_galet_and_stores_png(tmp_path):
    handler, api = make_handler(tmp_path)
    result = handler.execute({'prompt': 'A wooded hill', 'model': 'gpt-image-1'}, account_name='john')
    assert result['ok']
    assert result['image']['url'].startswith('/download/image/')
    assert result['mime_type'] == 'image/png'
    assert (tmp_path / result['path']).read_bytes().startswith(b'\x89PNG')
    metadata = json.loads((tmp_path / 'images' / 'john' / (result['image_id'] + '.json')).read_text())
    assert metadata['id'] == result['image_id']
    assert metadata['account'] == 'john'
    assert 'base64' not in json.dumps(result)
    assert api.generate_image.call_args.kwargs == {'model': 'gpt-image-1', 'prompt': 'A wooded hill', 'size': '1024x1024', 'quality': 'standard', 'n': 1}


def test_reference_uuid_and_explicit_history_become_image_messages(tmp_path):
    image_id = upload(tmp_path)
    handler, api = make_handler(tmp_path)
    result = handler.execute({'prompt': 'Change background', 'model': 'gpt-image-1', 'image_ids': [image_id], 'messages': [{'role': 'assistant', 'text': 'Previous draft', 'image_ids': []}]}, account_name='john', history=['unrelated chat'])
    assert result['ok']
    messages = api.generate_image.call_args.kwargs['messages']
    assert messages[0].role == 'assistant'
    assert messages[1].images[0].data == b'png-input'
    assert messages[1].images[0].mime_type == 'image/png'
    assert len(messages) == 2


def test_other_account_reference_never_reaches_provider(tmp_path):
    image_id = upload(tmp_path, 'arla')
    handler, api = make_handler(tmp_path)
    result = handler.execute({'prompt': 'Edit', 'model': 'gpt-image-1', 'image_ids': [image_id]}, account_name='john')
    assert not result['ok']
    api.generate_image.assert_not_called()


def test_empty_provider_result_is_failure(tmp_path):
    handler, api = make_handler(tmp_path)
    api.generate_image.return_value = ImageGenResponse(images=[])
    result = handler.execute({'prompt': 'Draw', 'model': 'gpt-image-1'})
    assert not result['ok']
    assert 'no images' in result['error']


def test_strict_schema_requires_all_arguments():
    params = ImageGenerateHandler.tool_def()['parameters']
    assert set(params['required']) == set(params['properties'])


def test_reference_symlink_cannot_escape_storage(tmp_path):
    image_id = upload(tmp_path)
    target = tmp_path / 'images' / 'john' / (image_id + '.png')
    target.unlink()
    target.symlink_to('/etc/hosts')
    handler, api = make_handler(tmp_path)
    result = handler.execute({'prompt': 'Edit', 'model': 'gpt-image-1', 'image_ids': [image_id]}, account_name='john')
    assert not result['ok']
    assert 'escapes storage root' in result['error']
    api.generate_image.assert_not_called()


def test_generated_uuid_is_reusable_without_reupload(tmp_path):
    handler, api = make_handler(tmp_path)
    first = handler.execute({'prompt': 'Draw', 'model': 'gpt-image-1'}, account_name='john')
    second = handler.execute({'prompt': 'Edit', 'model': 'gpt-image-1', 'image_ids': [first['image_id']]}, account_name='john')
    assert second['ok']
    reference = api.generate_image.call_args.kwargs['messages'][0].images[0]
    assert reference.data.startswith(b'\x89PNG')
    assert reference.mime_type == 'image/png'


def test_large_image_returns_small_tool_result(tmp_path):
    import os
    handler, api = make_handler(tmp_path)
    out = io.BytesIO()
    Image.frombytes('RGB', (512, 512), os.urandom(512 * 512 * 3)).save(out, format='PNG')
    api.generate_image.return_value = ImageGenResponse([ImageResult(b64_json=base64.b64encode(out.getvalue()).decode())])
    result = handler.execute({'prompt': 'Draw', 'model': 'gpt-image-1'}, account_name='john')
    assert result['ok']
    assert (tmp_path / result['path']).stat().st_size > 500_000
    assert len(json.dumps(result)) < 1000


def test_invalid_provider_image_does_not_leave_saved_files(tmp_path):
    handler, api = make_handler(tmp_path)
    api.generate_image.return_value = ImageGenResponse([ImageResult(b64_json='YWJj')])
    result = handler.execute({'prompt': 'Draw', 'model': 'gpt-image-1'}, account_name='john')
    assert not result['ok']
    assert not list(tmp_path.rglob('*.png'))


def test_provider_https_image_is_downloaded_and_saved(tmp_path, monkeypatch):
    from galet_tools.tools import image_generate_handler as module
    handler, api = make_handler(tmp_path)
    api.generate_image.return_value = ImageGenResponse([ImageResult(url='https://provider.example/result.png')])
    download = Mock()
    download.__enter__ = Mock(return_value=download)
    download.__exit__ = Mock(return_value=False)
    download.read.return_value = base64.b64decode(png_base64())
    fetch = Mock(return_value=download)
    monkeypatch.setattr(module, 'urlopen', fetch)
    result = handler.execute({'prompt': 'Draw', 'model': 'gpt-image-1'}, account_name='john')
    assert result['ok']
    fetch.assert_called_once_with('https://provider.example/result.png', timeout=30)
    assert (tmp_path / result['path']).exists()
    assert 'provider.example' not in json.dumps(result)


def test_webp_is_saved_as_png_with_alpha(tmp_path):
    handler, api = make_handler(tmp_path)
    out = io.BytesIO()
    Image.new('RGBA', (16, 16), (255, 0, 0, 120)).save(out, format='WEBP', lossless=True)
    api.generate_image.return_value = ImageGenResponse([ImageResult(b64_json=base64.b64encode(out.getvalue()).decode(), mime_type='image/webp')])
    result = handler.execute({'prompt': 'Draw', 'model': 'gpt-image-1'}, account_name='john')
    assert result['ok']
    with Image.open(tmp_path / result['path']) as saved:
        assert saved.format == 'PNG'
        assert saved.size == (16, 16)
        assert saved.getpixel((0, 0))[3] == 120
