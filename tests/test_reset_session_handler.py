import json

from galet_tools.tools.reset_session_handler import ResetSessionHandler


class Store:
    def __init__(self):
        self.reset_ids = []

    def reset_session(self, session_id):
        self.reset_ids.append(session_id)


def test_reset_uses_current_conversation_and_signals_client():
    store = Store()
    handler = ResetSessionHandler(store)
    result = handler.execute({}, account_name="alice", conversation_id="session-1")
    assert result == {"action": "reset_session", "ok": True}
    assert store.reset_ids == ["session-1"]
    assert json.loads(handler.execute_raw("{}", conversation_id="session-2"))["ok"]
    assert store.reset_ids == ["session-1", "session-2"]


def test_missing_context_or_store_does_not_claim_success():
    store = Store()
    handler = ResetSessionHandler(store)
    assert handler.execute({})["ok"] is False
    assert store.reset_ids == []
    assert ResetSessionHandler().execute({}, conversation_id="session-1")["ok"] is False
