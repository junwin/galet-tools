from galet_memory.semantic import SemanticDocument, SemanticMemoryResult
from galet_tools.tools.semantic_memory_handler import SemanticMemoryHandler


class FakeMemory:
    def __init__(self):
        self.requests = []

    def recall(self, request):
        self.requests.append(request)
        return SemanticMemoryResult(
            documents=[SemanticDocument(
                source_id="note-1", title="A note", snippet="Remember this",
                score=0.8, source_type="document",
            )],
            metadata={"backend": "example"},
        )

    def list_namespaces(self, account_name):
        assert account_name == "alice"
        return ["notes"]


def test_recall_and_namespaces_use_injected_memory():
    memory = FakeMemory()
    handler = SemanticMemoryHandler(memory)
    result = handler.execute(
        {"action": "recall", "query": "remember", "namespaces": ["notes"]},
        account_name="alice",
    )
    assert result["ok"] and result["documents"][0]["snippet"] == "Remember this"
    assert memory.requests[0].account_name == "alice"
    assert memory.requests[0].namespaces == ["notes"]
    namespaces = handler.execute({"action": "namespaces"}, account_name="alice")
    assert namespaces["ok"] and namespaces["namespaces"] == ["notes"]


def test_missing_query_and_unknown_action_are_errors():
    handler = SemanticMemoryHandler(FakeMemory())
    assert handler.execute({"action": "recall", "query": ""}, account_name="alice")["ok"] is False
    assert handler.execute({"action": "search"}, account_name="alice")["ok"] is False
