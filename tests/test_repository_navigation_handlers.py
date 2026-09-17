from pathlib import Path

from galet_tools.tools.repo_index_handler import RepoIndexHandler
from galet_tools.tools.repo_search_handler import RepoSearchHandler
from tests.conftest import FakeStorageResolver


def _repo(tmp_path: Path) -> tuple[Path, FakeStorageResolver]:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "service.py").write_text(
        '"""Streaming session support."""\n\n'
        'class FunctionCallingProcessor:\n'
        '    def process_message_streaming(self, session_id: str) -> str:\n'
        '        return session_id\n\n'
        'def helper() -> None:\n'
        '    pass\n', encoding="utf-8")
    (repo / "tests" / "test_service.py").write_text(
        'class TestStreaming:\n'
        '    def test_process_message_streaming(self):\n'
        '        pass\n', encoding="utf-8")
    return repo, FakeStorageResolver(str(tmp_path), {"repo": str(repo)})


def _base(**extra):
    return {"location": "external", "external_root": "repo", "root": ".", **extra}


def test_repo_index_supports_qualified_symbol_and_excludes_tests(tmp_path):
    _, resolver = _repo(tmp_path)
    result = RepoIndexHandler(resolver).execute(_base(
        operation="symbol", query="FunctionCallingProcessor.process_message_streaming",
        include_tests=False))
    assert result["ok"] is True
    assert result["count"] == 1
    match = result["results"][0]
    assert match["path"] == "src/service.py"
    assert match["symbol"] == "FunctionCallingProcessor.process_message_streaming"
    assert match["start_line"] == 4
    assert match["end_line"] == 5


def test_repo_index_lookup_returns_structural_ranges(tmp_path):
    _, resolver = _repo(tmp_path)
    result = RepoIndexHandler(resolver).execute(_base(
        operation="lookup", query="src/service.py", include_tests=False))
    module = result["results"][0]
    assert module["path"] == "src/service.py"
    assert module["classes"][0]["methods"][0]["name"] == "process_message_streaming"
    assert module["classes"][0]["methods"][0]["start_line"] == 4


def test_repo_search_ranks_production_and_can_include_tests(tmp_path):
    _, resolver = _repo(tmp_path)
    handler = RepoSearchHandler(resolver)
    production = handler.execute(_base(query="streaming session", limit=10, include_tests=False))
    assert production["ok"] is True
    assert production["results"][0]["path"] == "src/service.py"
    assert all(not item["path"].startswith("tests/") for item in production["results"])

    with_tests = handler.execute(_base(query="streaming", limit=10, include_tests=True))
    assert any(item["path"] == "tests/test_service.py" for item in with_tests["results"])


def test_repo_index_map_excludes_tests_by_default(tmp_path):
    _, resolver = _repo(tmp_path)
    result = RepoIndexHandler(resolver).execute(_base(
        operation="map", query="", include_tests=False))
    assert result["results"] == ["src/service.py"]


def test_repository_root_cannot_escape_configured_root(tmp_path):
    _, resolver = _repo(tmp_path)
    result = RepoSearchHandler(resolver).execute(_base(
        root="../", query="streaming", limit=10, include_tests=False))
    assert result["ok"] is False
    assert "relative" in result["error"] or "outside" in result["error"]
