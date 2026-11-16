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


def test_coco_already_knows_the_buyer_and_asks_no_setup_question(monkeypatch):
    monkeypatch.setattr(coco, "current", None)
    with TestClient(app) as client:
        state = client.get("/api/coco").json()
        assert state["lines"] == [] and state["zip"] == "94541" and state["conditions_confirmed"] is True
        assert len(state["conditions"]) == 3 and state["backup_mode"] is False
        assert client.post("/api/coco/first-run", json={"choice": "right"}).status_code in (404, 405)
        conv = coco.Conversation(backend=coco.SavedBackend(), client=object())
        assert "Their saved ZIP code: 94541." in conv.system() and "never ask for it" in conv.system()


def test_step_lines_come_from_the_real_search_and_check(monkeypatch):
    db.reset()
    now = {"t": 1000.0}
    monkeypatch.setattr(goodterms, "now", lambda: now["t"])
    conv = coco.Conversation(backend=coco.SavedBackend(), client=object())
    conv.step = {"who": "steps", "stores": None, "check_id": None}
    assert coco.step_view(conv.step) == [{"text": "Searching Shopify's catalog", "done": False}]

    async def flow():
        await conv.use("search_products", REQUEST)
        await conv.use("check_stores", {})
        conv.finishing.cancel()

    asyncio.run(flow())
    texts = lambda: [(s["text"], s["done"]) for s in coco.step_view(conv.step)]
    assert texts() == [
        ("Searched Shopify's catalog · 6 stores", True),
        ("Asking each store's assistant · 0 of 18", False),
        ("Reading store pages · 0 of 6", False),
    ]
    now["t"] += 2.2
    assert texts()[1] == ("Asking each store's assistant · 9 of 18", False)
    now["t"] += 6
    assert texts()[1:] == [("Asked each store's assistant · 18 answers", True), ("Reading store pages · 2 of 6", False)]
    now["t"] += 60
    assert texts()[2] == ("Read store pages · 6 of 6", True)


def test_sentence_count():
    assert coco.sentences("I searched for a Queen under $400.99 and found 6 stores. Buyer's Check is open.") == 2
    assert coco.sentences("What size, budget and ZIP code should I use?") == 1
    assert coco.sentences("One. Two. Three.") == 3
    quoted = 'The checks are finished. For Novilla, GoodTerms says: "Meets all 3 of your conditions." Its own words are on Buyer\'s Check.'
    assert coco.sentences(quoted) == 3
    assert coco.first_two(quoted) == 'The checks are finished. For Novilla, GoodTerms says: "Meets all 3 of your conditions."'
    assert coco.first_two("One. Two.") == "One. Two." and coco.first_two("Only one") == "Only one"
    assert coco.first_two("Novilla is $164.99. It is open. You pay there.") == "Novilla is $164.99. It is open."
    assert coco.short("3 of your conditions are not answered on its pages. That is not a yes.") == "3 of your conditions are not answered on its pages"


def test_coco_instructions_hold_the_rules():
    conv = coco.Conversation(backend=coco.SavedBackend(), client=object())
    db.reset()
    system = conv.system()
    for phrase in ("one or two short sentences, never three", "never recommend", "never pay, never complete a checkout", "one thing at a time", "Buyer's Check", "Opened returns, Free return shipping, Sale-item returns", "the size and the budget"):
        assert phrase in system
    assert [tool["name"] for tool in coco.TOOLS] == ["search_products", "check_stores", "get_prices", "open_review", "open_buyers_check"]


def buying(monkeypatch, check=2):
    db.reset()
    now = {"t": 1000.0}
    monkeypatch.setattr(goodterms, "now", lambda: now["t"])
    conv = coco.Conversation(backend=coco.SavedBackend(), client=object())
    conv.check_id = goodterms.replay_check(check)["id"]
    conv.turns = 1
    return conv, now


def test_buying_opens_nothing_before_the_check_has_finished(monkeypatch):
    conv, now = buying(monkeypatch)
    for store in ("", "Novilla", "NapQueen"):
        refused = conv.open_review(store, True)
        assert "error" in refused and "opened" not in refused and conv.review is None
    now["t"] += 9
    assert "error" in conv.open_review("", False)
    now["t"] += 60
    assert conv.open_review("", False)["opened"] is True


def test_buy_it_for_me_takes_the_lowest_priced_store_that_says_yes_to_all_3(monkeypatch):
    conv, now = buying(monkeypatch)
    now["t"] += 60
    went = conv.open_review("", False)
    assert went == {
        "store": "Novilla",
        "price": "$164.99",
        "result": "Meets all 3 of your conditions",
        "opened": True,
        "screen": "Review before checkout",
        "note": "Your buyer pays on the store's own page.",
    }
    assert conv.review == "novillashop.com"
    assert goodterms.checkout_link(conv.check_id, "novillashop.com")["url"].startswith("https://")
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    conn.close()


def test_a_named_store_with_a_no_or_a_gap_opens_only_after_the_buyers_own_yes(monkeypatch):
    conv, now = buying(monkeypatch)
    now["t"] += 60
    for name, domain, choice in (("NapQueen", "napqueensleep.com", "continue"), ("Comformattress", "comformattress.com", "buy_anyway")):
        assert conv.open_review(name, True)["needs_buyer_yes"] is True
        assert conv.open_review(name, True)["opened"] is False
        assert conv.review != domain
        conv.turns += 1
        assert conv.open_review(name, False)["opened"] is False
        conv.turns += 1
        went = conv.open_review(name, True)
        assert went["opened"] is True and conv.review == domain
        conn = db.connect()
        saved = conn.execute("SELECT choice FROM decisions WHERE store_domain = ?", (domain,)).fetchall()
        conn.close()
        assert [row[0] for row in saved] == [choice]
    assert "error" in conv.open_review("Nowhere Store", True)


def test_when_no_store_says_yes_to_all_3_coco_is_told_so_and_nothing_opens(monkeypatch):
    conv, now = buying(monkeypatch, check=1)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE findings SET page_status = 'doesnt_say', page_sentences = '[]' WHERE check_id = 1 AND condition = 'sale_item_returns'")
    conn.close()
    now["t"] += 60
    told = conv.open_review("", False)
    assert told["opened"] is False and told["no_store_says_yes_to_all_3"] is True and conv.review is None
    assert len(told["stores"]) == 6 and all("Meets all 3" not in s["result"] for s in told["stores"])


def test_a_failed_model_call_ends_in_a_plain_line_and_leaves_the_conversation_usable():
    db.reset()

    class Broken:
        class messages:
            @staticmethod
            def stream(**request):
                raise RuntimeError("model is down")

    conv = coco.Conversation(backend=coco.SavedBackend(), client=Broken())

    async def say(text):
        return [event async for event in conv.turn(text)]

    events = asyncio.run(say("I need a queen mattress under $400"))
    assert [e["type"] for e in events] == ["you", "delta", "line", "end"]
    assert conv.lines[-1] == {"who": "coco", "text": "I couldn't finish that. Please ask me again."}
    assert conv.messages == [] and not conv.lock.locked()
    asyncio.run(say("again"))
    assert len(conv.lines) == 4 and conv.messages == []


def test_backup_mode_is_off_unless_switched_on_by_hand(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.delenv("GOODTERMS_MODE", raising=False)
        assert client.get("/api/coco").json()["backup_mode"] is False
        assert isinstance(coco.make_backend(), coco.LiveBackend)
        monkeypatch.setenv("GOODTERMS_MODE", "saved")
        state = client.get("/api/coco").json()
        assert state["backup_mode"] is True and state["backup_date"] == "2026-11-15"
        assert isinstance(coco.make_backend(), coco.SavedBackend)
        replay = client.post("/api/checks/2/replay").json()["id"]
        assert client.get(f"/api/checks/{replay}").json()["saved_on"] == "2026-11-15"
