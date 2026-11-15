import pytest

from api import check, replies


@pytest.fixture(autouse=True)
def no_live_ask(tmp_path, monkeypatch):
    """Tests never ask a store's assistant. They use saved replies, and their own reply file."""

    async def refuse(*args, **kwargs):
        raise AssertionError("a test tried to call Ask live")

    monkeypatch.setattr(check, "ask", refuse)
    monkeypatch.setattr(replies, "FILE", tmp_path / "replies.db")
