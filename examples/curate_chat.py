"""Run curate_chat with a temporary SQLite store and no API key.

From a galet-tools checkout:
    python -m pip install -e '.[memory]'
    python examples/curate_chat.py
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from galet_memory.curation import CurationService, DigestGenerationRequest
from galet_memory.episodic import EpisodicEvent, SqliteEpisodicMemory
from galet_tools.tools.curate_chat_handler import CurateChatHandler


class ExampleDigestGenerator:
    def generate(self, request: DigestGenerationRequest) -> str:
        return "Summary: " + " ".join(str(event.content) for event in request.events)


def main() -> None:
    with TemporaryDirectory() as directory:
        with SqliteEpisodicMemory(str(Path(directory) / "sessions.sqlite")) as store:
            session = store.create_session(
                account_name="example", agent_name="demo",
                friendly_name="curation demo",
            )
            store.append_event(
                session.session_id,
                EpisodicEvent(role="user", actor="visitor", kind="message", content="Hello."),
            )
            store.append_event(
                session.session_id,
                EpisodicEvent(role="assistant", actor="demo", kind="message", content="Welcome."),
            )
            handler = CurateChatHandler(CurationService(store, ExampleDigestGenerator()))
            base = {"session_id": session.session_id, "max_chars": 32000, "idempotency_key": ""}
            digest = handler.execute({**base, "mode": "digest"}, account_name="example")
            assert digest["ok"] and digest["status"] == "preview", digest
            assert len(store.get_session(session.session_id, include_events=True).events) == 2
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
                session.session_id, include_events=True, event_scope="active"
            )
            assert active is not None and len(active.events) == 1
            print(json.dumps({"digest": digest, "archive": archived, "retry": retry}, indent=2))


if __name__ == "__main__":
    main()
