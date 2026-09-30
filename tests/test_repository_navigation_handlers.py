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


def test_javascript_only_repository_uses_text_index_and_content_search(tmp_path):
    repo = tmp_path / "javascript"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "CustomerPanel.tsx").write_text(
        "export class CustomerPanel {\n"
        "  refreshAccessToken() { return 'token'; }\n"
        "}\n", encoding="utf-8")
    (repo / "node_modules" / "vendor-lib").mkdir(parents=True)
    (repo / "node_modules" / "vendor-lib" / "index.js").write_text(
        "export function refreshAccessToken() {}\n", encoding="utf-8")
    resolver = FakeStorageResolver(str(tmp_path), {"javascript": str(repo)})
    index = RepoIndexHandler(resolver)
    search = RepoSearchHandler(resolver)

    mapped = index.execute({**_base(), "external_root": "javascript", "operation": "map",
                            "query": "", "include_tests": False})
    assert mapped["results"] == ["src/CustomerPanel.tsx"]

    details = index.execute({**_base(), "external_root": "javascript", "operation": "lookup",
                             "query": "src/CustomerPanel.tsx", "include_tests": False})
    assert details["results"][0]["language"] == "typescript"
    assert details["results"][0]["index_type"] == "text"
    assert details["results"][0]["line_count"] == 3

    symbol = index.execute({**_base(), "external_root": "javascript", "operation": "symbol",
                            "query": "refreshAccessToken", "include_tests": False})
    assert symbol["results"][0]["kind"] == "text"
    assert symbol["results"][0]["path"] == "src/CustomerPanel.tsx"
    assert symbol["results"][0]["start_line"] == 2

    matches = search.execute({**_base(), "external_root": "javascript",
                              "query": "refresh access token", "limit": 10,
                              "include_tests": False})
    assert matches["results"][0]["path"] == "src/CustomerPanel.tsx"
    assert any("content line 2" in reason for reason in matches["results"][0]["reasons"])


def test_mixed_repository_keeps_python_ast_and_indexes_csharp_text(tmp_path):
    repo = tmp_path / "mixed"
    (repo / "python").mkdir(parents=True)
    (repo / "dotnet" / "Services").mkdir(parents=True)
    (repo / "python" / "service.py").write_text(
        "class PythonService:\n    def submit(self):\n        pass\n", encoding="utf-8")
    (repo / "dotnet" / "Services" / "InvoiceService.cs").write_text(
        "namespace Shop.Services;\n"
        "public class InvoiceService {\n"
        "    // Reconcile invoice payments with account records.\n"
        "    public Task SubmitAsync() => Task.CompletedTask;\n"
        "}\n", encoding="utf-8")
    (repo / "dotnet" / "Services" / "InvoiceServiceTests.cs").write_text(
        "public class InvoiceServiceTests {}\n", encoding="utf-8")
    resolver = FakeStorageResolver(str(tmp_path), {"mixed": str(repo)})
    index = RepoIndexHandler(resolver)
    search = RepoSearchHandler(resolver)

    mapped = index.execute({**_base(), "external_root": "mixed", "operation": "map",
                            "query": "", "include_tests": False})
    assert set(mapped["results"]) == {
        "python/service.py", "dotnet/Services/InvoiceService.cs"
    }

    python_symbol = index.execute({**_base(), "external_root": "mixed", "operation": "symbol",
                                   "query": "PythonService.submit", "include_tests": False})
    assert python_symbol["results"][0]["kind"] == "method"
    assert python_symbol["results"][0]["start_line"] == 2

    csharp_symbol = index.execute({**_base(), "external_root": "mixed", "operation": "symbol",
                                   "query": "SubmitAsync", "include_tests": False})
    assert csharp_symbol["results"][0]["path"] == "dotnet/Services/InvoiceService.cs"
    assert csharp_symbol["results"][0]["start_line"] == 4

    csharp_lookup = index.execute({**_base(), "external_root": "mixed", "operation": "lookup",
                                   "query": "dotnet/Services/InvoiceService.cs",
                                   "include_tests": False})
    assert csharp_lookup["results"][0]["language"] == "csharp"
    assert csharp_lookup["results"][0]["classes"] == []

    csharp_search = search.execute({**_base(), "external_root": "mixed",
                                    "query": "reconcile invoice payments", "limit": 10,
                                    "include_tests": False})
    assert csharp_search["results"][0]["path"] == "dotnet/Services/InvoiceService.cs"
    assert all("Tests.cs" not in result["path"] for result in csharp_search["results"])


def test_repository_root_cannot_escape_configured_root(tmp_path):
    _, resolver = _repo(tmp_path)
    result = RepoSearchHandler(resolver).execute(_base(
        root="../", query="streaming", limit=10, include_tests=False))
    assert result["ok"] is False
    assert "relative" in result["error"] or "outside" in result["error"]
