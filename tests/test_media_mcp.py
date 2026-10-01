import base64
import io
from PIL import Image
from unittest.mock import Mock
from galet.imagegen_dto import ImageGenResponse, ImageResult
from galet_tools.host.config import GaletConfig, DEFAULT_ALLOWLIST
from galet_tools.mcp.server import resolve_startup_scope, dispatch_call


def test_explicit_media_allowlist_builds_executable_handlers(tmp_path):
    config = GaletConfig(account='john', allowlist=['image_generate', 'video_generate', 'generate_svg'], storage_root=str(tmp_path), storage_namespace='data', external_roots={}, sandbox_root=str(tmp_path / 'sandbox'), host='127.0.0.1', port=8765, fonts=[])
    scope, tools = resolve_startup_scope(config)
    assert {tool['name'] for tool in tools} == set(config.allowlist)
    assert set(config.allowlist) <= set(scope.handlers)
    api = Mock()
    out = io.BytesIO()
    Image.new('RGB', (32, 32), 'red').save(out, format='PNG')
    api.generate_image.return_value = ImageGenResponse([ImageResult(b64_json=base64.b64encode(out.getvalue()).decode())])
    scope.handlers['image_generate']._image_api = api
    result = dispatch_call(scope, 'image_generate', {'prompt': 'Draw a hill', 'model': 'gpt-image-1'})
    assert not result['isError']
    api.generate_image.assert_called_once()
    assert 'image_generate' not in DEFAULT_ALLOWLIST
    assert 'video_generate' not in DEFAULT_ALLOWLIST
