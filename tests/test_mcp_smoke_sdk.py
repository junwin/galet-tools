import pytest

mcp_types = pytest.importorskip('mcp.types')
from galet_tools.mcp import smoke


@pytest.mark.parametrize('is_error,expected', [(False, 0), (True, 1)])
def test_smoke_uses_pinned_sdk_error_field(monkeypatch, capsys, is_error, expected):
    async def call(*args):
        return mcp_types.CallToolResult(content=[mcp_types.TextContent(text='reply')], is_error=is_error)
    monkeypatch.setattr(smoke, '_call_tool', call)
    assert smoke._run_call('http://localhost/mcp', 10, 'procedural_memory', {}) == expected
    assert capsys.readouterr().out.strip() == 'reply'
