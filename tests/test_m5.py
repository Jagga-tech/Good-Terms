import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import coco, db, goodterms
from api.main import app

REQUEST = {"query": "queen mattress", "size": "Queen", "budget_dollars": 400, "zip_code": "94541"}


@pytest.fixture()
def conv():
    db.reset()
    return coco.Conversation(backend=coco.SavedBackend(pace=0.01), client=object())


def use(conv, name, args=None):
    return asyncio.run(conv.use(name, args or {}))


def test_no_price_and_no_link_before_the_check_has_started(conv):
    assert "error" in use(conv, "check_stores")
    assert "error" in use(conv, "get_prices")
    assert "error" in use(conv, "open_buyers_check")
    found = use(conv, "search_products", REQUEST)
    assert found["stores_found"] == 6 and found["size_searched"] == "Queen"
    assert "$" not in str(found) and "http" not in str(found) and "price" not in str(found).lower()
    assert "error" in use(conv, "get_prices")
    assert "error" in use(conv, "open_buyers_check")
    assert conv.check_id is None


def test_check_stores_starts_the_check_and_returns_at_once_with_no_answers(conv):
    async def flow():
        await conv.use("search_products", REQUEST)
        started = await conv.use("check_stores", {})
        view = goodterms.get_check(conv.check_id)
        opened = await conv.use("open_buyers_check", {})
        prices = await conv.use("get_prices", {})
        conv.finishing.cancel()
        return started, view, opened, prices

    started, view, opened, prices = asyncio.run(flow())
    assert started["started"] is True and "result" not in str(started).lower()
    assert not any(store["progress"]["pages_read"] for store in view["stores"])
    assert all(row["status_shown"] == "pending" for store in view["stores"] for row in store["rows"])
    assert opened == {"opened": True, "screen": "Buyer's Check"}
    assert {p["store"]: p["price"] for p in prices["prices"]}["Novilla"] == "$164.99"
    assert all(p["basis"] == "catalog price" for p in prices["prices"]) and "http" not in str(prices)
    assert conv.tools_called == ["search_products", "check_stores", "open_buyers_check", "get_prices"]


def test_a_checkout_link_is_refused_until_that_stores_check_has_finished(monkeypatch):
    db.reset()
    now = {"t": 1000.0}
    monkeypatch.setattr(goodterms, "now", lambda: now["t"])
    check_id = goodterms.replay_check(2)["id"]
    stores = [store["domain"] for store in goodterms.get_check(check_id)["stores"]]
    for store in stores:
        with pytest.raises(HTTPException) as refused:
            goodterms.checkout_link(check_id, store)
        assert refused.value.status_code == 409
    now["t"] += 6
    first, last = stores[0], stores[-1]
    assert first == "novillashop.com"
    assert goodterms.checkout_link(check_id, first)["url"].startswith("https://")
    with pytest.raises(HTTPException):
        goodterms.checkout_link(check_id, last)
    now["t"] += 60
    for store in ("novillashop.com", "sweetnight.com"):
        link = goodterms.checkout_link(check_id, store)["url"]
        assert link.startswith("https://") and "/buy/" in link
    with TestClient(app) as client:
        assert client.get(f"/api/checks/2/checkout/{first}").json()["url"].startswith("https://")
        assert client.get("/api/checks/2/checkout/example.com").status_code == 404


def test_first_run_conditions_are_confirmed_once_and_saved():
    with TestClient(app) as client:
        before = client.get("/api/coco").json()
        assert before["conditions_confirmed"] is False and len(before["conditions"]) == 3
        assert before["lines"] == [] and before["check_id"] is None
        assert client.post("/api/buyer/conditions").json()["conditions_confirmed"] is True
        assert client.get("/api/coco").json()["conditions_confirmed"] is True


def test_sentence_count():
    assert coco.sentences("I searched for a Queen under $400.99 and found 6 stores. Buyer's Check is open.") == 2
    assert coco.sentences("What size, budget and ZIP code should I use?") == 1
    assert coco.sentences("One. Two. Three.") == 3
    quoted = 'The checks are finished. For Novilla, GoodTerms says: "Meets all 3 of your conditions." Its own words are on Buyer\'s Check.'
    assert coco.sentences(quoted) == 3


def test_coco_instructions_hold_the_rules():
    conv = coco.Conversation(backend=coco.SavedBackend(), client=object())
    db.reset()
    system = conv.system()
    for phrase in ("one or two short sentences, never three", "never recommend", "never buy", "Buyer's Check", "Opened returns, Free return shipping, Sale-item returns"):
        assert phrase in system
    assert [tool["name"] for tool in coco.TOOLS] == ["search_products", "check_stores", "get_prices", "open_buyers_check"]
