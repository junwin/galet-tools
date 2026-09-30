import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock
from galet.imagegen_dto import ImageGenResponse, ImageResult
from galet_tools.tools.image_generate_handler import ImageGenerateHandler


def make_handler(tmp_path):
    resolver = SimpleNamespace(storage_base_dir=lambda: str(tmp_path))
    api = Mock()
    api.generate_image.return_value = ImageGenResponse(images=[ImageResult(b64_json='YWJj', mime_type='image/webp')], model='gpt-image-1')
    return ImageGenerateHandler(resolver, api), api


def upload(tmp_path, account='john'):
    image_id = str(uuid.uuid4())
    directory = tmp_path / 'images' / account
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (image_id + '.png')).write_bytes(b'png-input')
    (directory / (image_id + '.json')).write_text(json.dumps({'id': image_id, 'account': account, 'mime_type': 'image/png'}))
    return image_id


def test_text_generation_calls_galet_and_returns_real_mime(tmp_path):
    handler, api = make_handler(tmp_path)
    result = handler.execute({'prompt': 'A wooded hill', 'model': 'gpt-image-1'}, account_name='john')
    assert result['ok']
    assert result['image']['url'] == 'data:image/webp;base64,YWJj'
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
