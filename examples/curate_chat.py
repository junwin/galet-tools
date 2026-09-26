"""Run episodic, curation, reset, and semantic tools without external services.

From a galet-tools checkout:
    python -m pip install -e '.[memory]'
    python examples/curate_chat.py
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from galet_memory.curation import CurationService, DigestGenerationRequest
from galet_memory.episodic import SqliteEpisodicMemory
from galet_memory import VectorSemanticMemory
from galet_memory.ports import EmbeddingMatch, EmbeddingRecord, FileTextLoader
from galet_tools.tools.curate_chat_handler import CurateChatHandler
from galet_tools.tools.episodic_memory_handler import EpisodicMemoryHandler
from galet_tools.tools.reset_session_handler import ResetSessionHandler
from galet_tools.tools.semantic_memory_handler import SemanticMemoryHandler


class ExampleDigestGenerator:
    def generate(self, request: DigestGenerationRequest) -> str:
        return "Summary: " + " ".join(str(event.content) for event in request.events)


class ExampleEmbeddings:
    def embed(self, texts, *, model):
        assert texts and model
        return [[1.0, 0.0] for _ in texts]


class ExampleIndex:
    def __init__(self, path: Path):
        self.path = path

    def list_namespaces(self, account_name):
        assert account_name == "example"
        return ["notes"]

    def query(self, *, account_name, namespaces, vector, limit, filters=None):
        assert account_name == "example" and namespaces == ["notes"]
        assert vector == [1.0, 0.0] and limit >= 1
        return [EmbeddingMatch(
            EmbeddingRecord(
                id="note-1", source_id="note-1", source_type="document",
                metadata={"path": str(self.path), "title": "Shop hours", "tags": ["store"]},
            ),
            0.9,
        )]


def main() -> None:
    with TemporaryDirectory() as directory:
        with SqliteEpisodicMemory(str(Path(directory) / "sessions.sqlite")) as store:
            episodic = EpisodicMemoryHandler(store)
            created = episodic.execute(
                {"action": "create_session", "agent_name": "demo",
                 "friendly_name": "curation demo"},
                account_name="example",
            )
            assert created["ok"], created
            session_id = created["session"]["session_id"]
            for role, text in (("user", "Hello."), ("assistant", "Welcome.")):
                added = episodic.execute(
                    {"action": "append_event", "session_id": session_id,
                     "role": role, "kind": "message", "content": text},
                    account_name="example",
                )
                assert added["ok"], added
            before = episodic.execute(
                {"action": "get_session", "session_id": session_id},
                account_name="example",
            )
            assert before["ok"] and len(before["session"]["events"]) == 2, before
            handler = CurateChatHandler(CurationService(store, ExampleDigestGenerator()))
            base = {"session_id": session_id, "max_chars": 32000, "idempotency_key": ""}
            digest = handler.execute({**base, "mode": "digest"}, account_name="example")
            assert digest["ok"] and digest["status"] == "preview", digest
            assert len(store.get_session(session_id, include_events=True).events) == 2
            archived = handler.execute(
                {**base, "mode": "archive", "idempotency_key": "example-operation"},
                account_name="example",
            )
            assert archived["ok"] and archived["boundary_event_id"], archived
            retry = handler.execute(
                {**base, "mode": "archive", "idempotency_key": "example-operation"},
                account_name="example",
            )
            assert retry["boundary_event_id"] == archived["boundary_event_id"], retry
            active = store.get_session(
                session_id, include_events=True, event_scope="active"
            )
            assert active is not None and len(active.events) == 1
            after = episodic.execute(
                {"action": "get_session", "session_id": session_id},
                account_name="example",
            )
            assert after["ok"] and len(after["session"]["events"]) == 1, after
            assert after["session"]["events"][0]["kind"] == "session_digest", after
            reset = ResetSessionHandler(store).execute(
                {}, account_name="example", conversation_id=session_id
            )
            assert reset == {"action": "reset_session", "ok": True}, reset
            cleared = episodic.execute(
                {"action": "get_session", "session_id": session_id},
                account_name="example",
            )
            assert cleared["ok"] and cleared["session"]["events"] == [], cleared
            assert cleared["session"]["friendly_name"] == "curation demo", cleared
            note = Path(directory) / "shop-hours.md"
            note.write_text("The shop opens at nine.", encoding="utf-8")
            semantic = SemanticMemoryHandler(VectorSemanticMemory(
                embeddings=ExampleEmbeddings(),
                index=ExampleIndex(note),
                text_loader=FileTextLoader(),
            ))
            recalled = semantic.execute(
                {"action": "recall", "query": "When does the shop open?",
                 "namespaces": ["notes"]},
                account_name="example",
            )
            assert recalled["ok"] and recalled["count"] == 1, recalled
            assert recalled["documents"][0]["snippet"] == "The shop opens at nine."
            namespaces = semantic.execute({"action": "namespaces"}, account_name="example")
            assert namespaces["ok"] and namespaces["namespaces"] == ["notes"], namespaces
            print(json.dumps({
                "created": created, "before": before, "digest": digest,
                "archive": archived, "retry": retry, "after": after,
                "reset": reset, "cleared": cleared,
                "semantic_recall": recalled, "namespaces": namespaces,
            }, indent=2))


if __name__ == "__main__":
    main()
