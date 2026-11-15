import pytest
from fastapi.testclient import TestClient

from api import db, goodterms, texts
from api.main import app

CASES = db.load("combining_cases.json")


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(goodterms, "now", lambda: now["t"])
    return now


def test_price_gap_equals_the_difference_between_the_two_prices_to_the_cent(client):
    check = client.get("/api/checks/1").json()
    gap = check["price_gap"]
    prices = {store["name"]: store["offer"]["price_cents"] for store in check["stores"]}
    meeting = {s["name"]: prices[s["name"]] for s in check["stores"] if s["result"] == "meets_all_3"}
    assert gap["cheapest"] == {"name": "NapQueen", "price_cents": min(prices.values())}
    assert gap["cheapest_meeting_all_3"] == {"name": "Novilla", "price_cents": min(meeting.values())}
    assert gap["difference_cents"] == 29999 - 22900 == 7099
    assert gap["text"] == (
        "Cheapest overall: $229.00 at NapQueen. Cheapest that says yes to all 3 of your"
        " conditions: $299.99 at Novilla. Difference: $70.99."
    )
    for store in check["stores"]:
        assert store["offer"]["price_text"] in (gap["text"] if store["name"] in ("NapQueen", "Novilla") else store["offer"]["price_text"])


def test_price_gap_says_so_when_no_store_meets_all_three():
    stores = [
        {"name": "A", "result": "says_no", "offer": {"price_cents": 10000}},
        {"name": "B", "result": "not_answered_on_pages", "offer": {"price_cents": 9950}},
    ]
    gap = texts.price_gap(stores)
    assert gap["text"] == "Cheapest overall: $99.50 at B. No store says yes to all 3 of your conditions."
    assert gap["difference_cents"] is None
    stores[1]["result"] = "meets_all_3"
    same = texts.price_gap(stores)
    assert same["text"] == "Cheapest overall: $99.50 at B. It also says yes to all 3 of your conditions."
    assert "$0.00" not in same["text"] and same["difference_cents"] == 0


def test_finished_check_is_sorted_yes_then_unanswered_then_no_cheapest_first(client):
    check = client.get("/api/checks/1").json()
    assert check["done"] is True
    assert [(s["name"], s["result"]) for s in check["stores"]] == [
        ("Novilla", "meets_all_3"),
        ("SweetNight", "meets_all_3"),
        ("NapQueen", "not_answered_on_pages"),
        ("Dwellinhaus", "says_no"),
        ("Lee Furniture, NC", "says_no"),
        ("BedStory", "says_no"),
    ]
    assert all(store["offer"]["within_budget"] for store in check["stores"])


def test_status_and_result_wording(client):
    stores = {s["name"]: s for s in client.get("/api/checks/1").json()["stores"]}
    napqueen = stores["NapQueen"]
    assert napqueen["rows"][0]["status_text"] == "Store's assistant says yes. Not found on its pages."
    assert napqueen["rows"][1]["status_text"] == "Doesn't say"
    assert napqueen["result_text"] == "3 of your conditions are not answered on its pages. That is not a yes."
    assert stores["Novilla"]["result_text"] == "Meets all 3 of your conditions"
    assert [row["status_text"] for row in stores["Novilla"]["rows"]] == ["Yes"] * 3
    bedstory = stores["BedStory"]
    assert bedstory["result_text"] == "Says no to 1 of your conditions"
    assert bedstory["rows"][1]["status_text"] == "No"
    assert bedstory["rows"][1]["contradiction_text"] == (
        "This store's pages say different things. This store's pages and its assistant contradict each other."
    )
    assert bedstory["rows"][0]["contradiction_text"] == "This store's pages say different things."
    assert texts.status_text("assistant_only_yes", "unreadable") == "Store's assistant says yes. We couldn't read its pages."
    assert texts.result_text("could_not_read", []) == "We couldn't read this store's pages"
    assert texts.result_text("not_answered_on_pages", [{"status_shown": "doesnt_say"}, {"status_shown": "yes"}]).startswith("1 of your conditions is not")


def test_a_no_that_comes_only_from_the_assistant_says_so(client):
    for store in client.get("/api/checks/1").json()["stores"]:
        if store["name"] not in ("Dwellinhaus", "Lee Furniture, NC"):
            continue
        assert store["result_text"] == "Says no to 2 of your conditions"
        for row in store["rows"]:
            assert row["pages_text"] == row["read_note"] == "Pages were not read in this saved run."
            assert row["page_sentences"] == [] and row["date_read"] is None
            assert row["assistant_reply"]
            if row["status_shown"] == "no":
                assert row["assistant_status"] == "no" and row["page_status"] != "no"
                assert row["status_text"] == "Store's assistant says no."


def test_replay_shows_replies_first_and_no_yes_until_each_stores_pages_are_read(client, clock):
    final = {s["domain"]: s for s in client.get("/api/checks/1").json()["stores"]}
    replay_id = client.post("/api/checks/1/replay").json()["id"]
    order = [s["domain"] for s in client.get(f"/api/checks/{replay_id}").json()["stores"]]
    seen_partial = False
    for step in range(0, 40):
        clock["t"] = 1000.0 + step * 0.5
        check = client.get(f"/api/checks/{replay_id}").json()
        finished = [s for s in check["stores"] if s["progress"]["pages_read"]]
        if len(finished) < 6:
            assert [s["domain"] for s in check["stores"]] == order
            assert check["done"] is False and check["price_gap"] is None
        seen_partial = seen_partial or 0 < len(finished) < 6
        for store in check["stores"]:
            if store["progress"]["pages_read"]:
                assert {**store, "offer": None} == {**final[store["domain"]], "offer": None}
                continue
            assert store["result"] == "still_reading"
            assert store["result_text"] == "Still reading this store's pages"
            for row in store["rows"]:
                assert row["status_shown"] == "pending" and not row["counts_toward_meets_all_3"]
                assert row["status_text"] == row["pages_text"] == "Still reading this store's pages"
                assert row["page_sentences"] == [] and row["contradiction_text"] is None
                assert bool(row["assistant_reply"]) == store["progress"]["replies_in"]
    assert seen_partial
    assert check["done"] is True and check["price_gap"]["difference_cents"] == 7099
    assert client.get("/api/checks/1").json()["stores"] == check["stores"]


def test_replay_replies_arrive_before_any_pages(client, clock):
    replay_id = client.post("/api/checks/1/replay").json()["id"]
    clock["t"] = 1000.0 + 4.0
    stores = client.get(f"/api/checks/{replay_id}").json()["stores"]
    assert all(s["progress"] == {"replies_in": True, "pages_read": False} for s in stores)


def test_store_list_and_store_view_hold_nothing_about_the_buyer(client):
    listed = client.get("/api/stores").json()
    assert [s["name"] for s in listed] == ["BedStory", "Comformattress", "Dwellinhaus", "Lee Furniture, NC", "NapQueen", "Novilla", "SweetNight"]
    latest = {s["domain"]: s for s in client.get("/api/checks/2").json()["stores"]}
    older = {s["domain"]: s for s in client.get("/api/checks/1").json()["stores"]}
    for store in listed:
        source = latest.get(store["domain"]) or older[store["domain"]]
        assert client.get(f"/api/stores/{store['domain']}").json()["rows"] == source["rows"]
    view = client.get("/api/stores/bedstory.com").json()
    keys = set(view) | {key for row in view["rows"] for key in row}
    assert not any(word in key for key in keys for word in ("offer", "price", "budget", "decision", "total"))
