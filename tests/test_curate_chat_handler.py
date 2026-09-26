from types import SimpleNamespace

from galet_tools.tools.curate_chat_handler import CurateChatHandler


class FakeCuration:
    def __init__(self):
        self.calls = []

    def produce_digest(self, **kwargs):
        self.calls.append(("digest", kwargs))
        return SimpleNamespace(session_id=kwargs["session_id"], digest="A digest.", boundary_event=None)

    def archive(self, **kwargs):
        self.calls.append(("archive", kwargs))
        return SimpleNamespace(
            session_id=kwargs["session_id"], digest="A digest.",
            boundary_event=SimpleNamespace(event_id="boundary-1"),
        )


def test_digest_and_archive_delegate_with_trusted_account():
    service = FakeCuration()
    handler = CurateChatHandler(service)
    args = {"session_id": "session-1", "max_chars": 42, "idempotency_key": ""}
    digest = handler.execute({**args, "mode": "digest"}, account_name="alice")
    archive = handler.execute(
        {**args, "mode": "archive", "idempotency_key": "retry-1"},
        account_name="alice",
    )
    assert digest["status"] == "preview" and digest["boundary_event_id"] is None
    assert archive["status"] == "archived" and archive["boundary_event_id"] == "boundary-1"
    assert service.calls == [
        ("digest", {"account_name": "alice", "session_id": "session-1", "max_chars": 42, "publish": False}),
        ("archive", {
            "account_name": "alice", "session_id": "session-1",
            "max_chars": 42, "idempotency_key": "retry-1", "publish": False,
        }),
    ]


def test_invalid_input_never_calls_service():
    service = FakeCuration()
    handler = CurateChatHandler(service)
    for args, account in [
        ({"session_id": "", "mode": "digest"}, "alice"),
        ({"session_id": "s", "mode": "filter"}, "alice"),
        ({"session_id": "s", "mode": "archive", "max_chars": 0}, "alice"),
        ({"session_id": "s", "mode": "archive"}, "auto"),
    ]:
        assert handler.execute(args, account_name=account)["ok"] is False
    assert service.calls == []

def test_explicit_publication_returns_document_and_index_record():
    class PublishingCuration(FakeCuration):
        def produce_digest(self, **kwargs):
            self.calls.append(("digest", kwargs))
            return SimpleNamespace(
                session_id=kwargs["session_id"], digest="A digest.",
                boundary_event=None,
                publication=SimpleNamespace(path="/digests/alice/s.md", embedding_id="digest:alice:s"),
            )

    service = PublishingCuration()
    result = CurateChatHandler(service).execute(
        {"session_id": "s", "mode": "digest", "publish": True}, account_name="alice"
    )
    assert result["status"] == "published"
    assert result["published"] is True
    assert result["output_path"] == "/digests/alice/s.md"
    assert result["embedding_id"] == "digest:alice:s"
    assert service.calls[0][1]["publish"] is True
