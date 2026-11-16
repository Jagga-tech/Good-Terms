import re

import pytest
from fastapi.testclient import TestClient

from api import db, goodterms, texts
from api.main import app

SAVED = db.load("live_check_2026-11-15.json")
LINKS = {store["domain"]: store["offer"]["checkout_url"] for store in SAVED["stores"]}


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def stores(client, check_id=2):
    return {store["name"]: store for store in client.get(f"/api/checks/{check_id}").json()["stores"]}


def labels(store):
    return [action["label"] for action in store["actions"]]


def test_the_options_depend_on_the_result(client):
    seen = stores(client)
    assert labels(seen["Novilla"]) == ["Review before checkout"]
    assert labels(seen["Comformattress"]) == ["Skip this store", "Buy anyway"]
    assert [a["first"] for a in seen["Comformattress"]["actions"]] == [True, False]
    assert labels(seen["NapQueen"]) == ["Skip this store", "Continue without an answer"]
    assert [a["first"] for a in seen["NapQueen"]["actions"]] == [False, False]
    assert [a["label"] for a in texts.actions("could_not_read")] == ["Skip this store", "Open the store's site"]
    assert texts.actions("still_reading") == [] and texts.actions("not_checked") == []


def test_no_buttons_and_no_choice_until_a_stores_pages_are_read(client, monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(goodterms, "now", lambda: now["t"])
    replay = client.post("/api/checks/2/replay").json()["id"]
    for store in stores(client, replay).values():
        assert store["actions"] == [] and store["review_allowed"] is False
        for choice in ("skip", "continue", "buy_anyway", "checkout"):
            refused = client.post(f"/api/checks/{replay}/decisions", json={"store": store["domain"], "choice": choice})
            assert refused.status_code == 409
        assert client.get(f"/api/checks/{replay}/checkout/{store['domain']}").status_code == 409
    now["t"] += 60
    assert labels(stores(client, replay)["Novilla"]) == ["Review before checkout"]


def test_go_to_checkout_gives_the_catalogs_link_for_the_exact_variant(client):
    for name in ("Novilla", "SweetNight"):
        store = stores(client)[name]
        link = client.get(f"/api/checks/2/checkout/{store['domain']}").json()["url"]
        assert link == LINKS[store["domain"]]
        number = store["offer"]["variant_id"].rsplit("/", 1)[-1]
        assert link.startswith("https://") and f"/buy/{number}:1" in link
        done = client.post("/api/checks/2/decisions", json={"store": store["domain"], "choice": "checkout"}).json()
        assert done["choice"] == "checkout" and done["text"] == "You went to this store's checkout."


def test_a_store_with_a_gap_gives_its_link_only_after_the_buyers_choice(client):
    for name, choice, wrong in (("NapQueen", "continue", "buy_anyway"), ("Comformattress", "buy_anyway", "continue")):
        store = stores(client)[name]
        assert store["review_allowed"] is False and store["decision"] is None
        assert client.get(f"/api/checks/2/checkout/{store['domain']}").status_code == 409
        assert client.post("/api/checks/2/decisions", json={"store": store["domain"], "choice": "checkout"}).status_code == 409
        assert client.post("/api/checks/2/decisions", json={"store": store["domain"], "choice": wrong}).status_code == 409
        said = client.post("/api/checks/2/decisions", json={"store": store["domain"], "choice": choice}).json()
        assert said["text"] == texts.DECISIONS[choice] and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", said["time"])
        after = stores(client)[name]
        assert after["decision"]["choice"] == choice and after["review_allowed"] is True
        assert client.get(f"/api/checks/2/checkout/{store['domain']}").json()["url"] == LINKS[store["domain"]]
    skipped = stores(client)["Dwellinhaus"]
    assert client.post("/api/checks/2/decisions", json={"store": skipped["domain"], "choice": "skip"}).json()["text"] == "You skipped this store."
    assert stores(client)["Dwellinhaus"]["review_allowed"] is False
    assert client.get(f"/api/checks/2/checkout/{skipped['domain']}").status_code == 409


def test_a_finished_flow_records_choices_and_creates_no_checkout(client):
    novilla = stores(client)["Novilla"]
    client.post("/api/checks/2/decisions", json={"store": novilla["domain"], "choice": "checkout"})
    conn = db.connect()
    assert [tuple(row)[:3] for row in conn.execute("SELECT * FROM decisions")] == [(2, "novillashop.com", "checkout")]
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert not any("checkout" in table or "payment" in table or "cart" in table for table in tables)


def test_price_note_final_total_note_and_the_card_note(client):
    check = client.get("/api/checks/2").json()
    assert check["price_note"] == "Prices are from Shopify's catalog. Shipping and tax are added at checkout."
    assert check["final_total_note"] == "The final total, with shipping and tax, appears on the store's own checkout page."
    assert check["price_gap"]["text"] == "Cheapest overall: $164.99 at Novilla. It also says yes to all 3 of your conditions."
    notes = {name: store["card_note"] for name, store in stores(client).items()}
    assert notes["BedStory"] == "Its pages say different things" and notes["Novilla"] is None
    assert stores(client, 1)["BedStory"]["card_note"] == "Its pages say different things"
    prices = {store["offer"]["price_cents"] for store in check["stores"]}
    assert min(prices) == 16499 and check["price_gap"]["difference_cents"] == 0


def test_no_payment_field_anywhere_in_the_code():
    payment = re.compile(r"card.?number|cvv|cvc|expir|credit.?card|cc-number|autocomplete=.cc-|type=.password", re.I)
    sources = [p for folder in ("api", "web/src", "scripts") for p in (db.ROOT / folder).rglob("*") if p.suffix in {".py", ".ts", ".tsx", ".css"}]
    assert len(sources) > 20
    for path in sources:
        assert not payment.search(path.read_text()), path.name


def test_each_offer_carries_the_catalogs_own_photo_or_none(client):
    for store in stores(client).values():
        assert store["offer"]["image_url"].startswith("https://cdn.shopify.com/")
    seen = db.saved_photos()
    for store in SAVED["stores"]:
        assert stores(client)[store["name"]]["offer"]["image_url"] == seen[store["offer"]["variant_id"]]
    for store in stores(client, 1).values():
        assert store["offer"]["image_url"] is None
