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
from galet_memory.ports import EmbeddingMatch, EmbeddingRecord, FileTextLoader, StoredEmbedding
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
    """Small in-memory index for demonstrating explicit digest publication."""

    def __init__(self):
        self.records: list[StoredEmbedding] = []

    def upsert(self, embedding: StoredEmbedding) -> None:
        self.records.append(embedding)

    def list_namespaces(self, account_name):
        return sorted({
            record.namespace for record in self.records
            if record.account_name == account_name
        })

    def query(self, *, account_name, namespaces, vector, limit, filters=None):
        matches = []
        for stored in self.records:
            if stored.account_name != account_name or stored.namespace not in namespaces:
                continue
            if filters and any(getattr(stored, key) != value for key, value in filters.items()):
                continue
            # The deterministic example vectors are identical, so the score
            # stands in for a real index's similarity calculation.
            matches.append(EmbeddingMatch(
                EmbeddingRecord(
                    id=stored.id, source_id=stored.source_id,
                    source_type=stored.source_type, metadata=stored.metadata,
                ),
                0.9,
            ))
        return matches[:limit]


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
            embeddings = ExampleEmbeddings()
            index = ExampleIndex()
            semantic = SemanticMemoryHandler(VectorSemanticMemory(
                embeddings=embeddings, index=index, text_loader=FileTextLoader(),
            ))
            recall_args = {
                "action": "recall", "query": "What happened in this chat?",
                "namespaces": ["digests"], "source_type": "digest",
            }
            before_publish = semantic.execute(recall_args, account_name="example")
            assert before_publish["ok"] and before_publish["count"] == 0, before_publish

            # The host explicitly publishes the curation result: save the
            # digest text, embed it, and add a searchable record to its index.
            digest_path = Path(directory) / "session-digest.md"
            digest_path.write_text(archived["digest"], encoding="utf-8")
            vector = embeddings.embed(
                [archived["digest"]], model="text-embedding-3-small"
            )[0]
            index.upsert(StoredEmbedding(
                id="digest-1", account_name="example", namespace="digests",
                vector=vector, source_type="digest", source_id=session_id,
                model="text-embedding-3-small", provider="example",
                metadata={
                    "path": str(digest_path), "title": "Curation demo digest",
                    "session_id": session_id, "tags": ["curation"],
                },
            ))
            recalled = semantic.execute(recall_args, account_name="example")
            assert recalled["ok"] and recalled["count"] == 1, recalled
            assert recalled["documents"][0]["source_id"] == session_id, recalled
            assert recalled["documents"][0]["snippet"] == archived["digest"], recalled
            namespaces = semantic.execute({"action": "namespaces"}, account_name="example")
            assert namespaces["ok"] and namespaces["namespaces"] == ["digests"], namespaces
            print(json.dumps({
                "created": created, "before": before, "digest": digest,
                "archive": archived, "retry": retry, "after": after,
                "reset": reset, "cleared": cleared,
                "before_publish": before_publish, "semantic_recall": recalled,
                "namespaces": namespaces,
            }, indent=2))


if __name__ == "__main__":
    main()
