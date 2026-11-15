import asyncio
import itertools
import json

import pytest
from fastapi.testclient import TestClient

from api import db
from api.combine import combine, page_status, store_result
from api.main import app
from api.mcp_server import mcp

CASES = db.load("combining_cases.json")
RUN = db.load("live_run_under_400_2026-11-15.json")
SAVED = CASES["saved_cases_live_run_2026-11-15"]
PAGES = ["yes", "no", "doesnt_say", "unreadable", "pending"]
ASSISTANT = ["yes", "no", "doesnt_say", "unavailable", "pending"]


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def saved_row(case):
    pages, disagree = page_status([s["label"] for s in case["page_sentences"]])
    shown, flag = combine(pages, case["assistant"], disagree)
    return {"page_status": pages, "status_shown": shown, "contradiction": flag}


@pytest.mark.parametrize("case", CASES["table_cases"], ids=lambda c: f"{c['pages']}+{c['assistant']}")
def test_every_row_of_the_combining_table(case):
    shown, flag = combine(case["pages"], case["assistant"])
    assert shown == case["status_shown"]
    assert flag == case["contradiction_flag"]
    assert (shown == "yes") == case["counts_toward_meets_all_3"]


@pytest.mark.parametrize("case", SAVED, ids=lambda c: f"{c['store']}-{c['condition']}")
def test_every_saved_combining_case(case):
    row = saved_row(case)
    if "pages" in case:
        assert row["page_status"] == case["pages"]
    if "status_shown" in case:
        assert row["status_shown"] == case["status_shown"]
        assert row["contradiction"] == case["contradiction_flag"]
        assert (row["status_shown"] == "yes") == case["counts_toward_meets_all_3"]
    else:
        assert row["status_shown"] in case.get("status_shown_any_of", ["doesnt_say"])
        assert row["contradiction"] is True
    if case.get("pages_disagree"):
        assert page_status([s["label"] for s in case["page_sentences"]])[1] is True


@pytest.mark.parametrize("case", SAVED, ids=lambda c: f"{c['store']}-{c['condition']}")
def test_saved_page_sentences_are_in_the_saved_page_text(case):
    for sentence in case["page_sentences"]:
        assert sentence["sentence"] in (db.FIXTURES / sentence["file"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("expected", CASES["store_results_live_run_2026-11-15"], ids=lambda e: e["store"])
def test_saved_store_results(expected):
    rows = [saved_row(case) for case in SAVED if case["store"] == expected["store"]]
    assert len(rows) == 3
    result = store_result(rows, pages_read=True)
    assert result in expected.get("result_any_of", [expected.get("result")])
    page_yes = sum(row["status_shown"] == "yes" for row in rows)
    assert page_yes <= expected.get("page_yes_at_most", expected.get("page_yes"))
    if "page_yes" in expected:
        assert page_yes == expected["page_yes"]
    if "assistant_only_yes" in expected:
        assert sum(r["status_shown"] == "assistant_only_yes" for r in rows) == expected["assistant_only_yes"]


@pytest.mark.parametrize("pair", CASES["six_original_stores"], ids=lambda p: f"{p['store']}-{p['condition']}")
def test_six_original_stores_pairs(pair):
    shown, _ = combine(pair["pages"], pair["assistant"])
    assert shown == pair["status_shown"]
    assert (shown == "yes") == pair["counts_toward_meets_all_3"]


def test_a_yes_always_needs_a_page_yes():
    for pages, assistant, disagree in itertools.product(PAGES, ASSISTANT, [False, True]):
        shown, _ = combine(pages, assistant, disagree)
        if shown == "yes":
            assert pages == "yes"
        if pages == "pending":
            assert shown == "pending"
        if pages in ("doesnt_say", "unreadable") and assistant == "yes":
            assert shown == "assistant_only_yes"


def test_two_page_yeses_and_one_assistant_only_yes_is_not_meets_all_3():
    rows = [
        {"page_status": "yes", "status_shown": "yes"},
        {"page_status": "yes", "status_shown": "yes"},
        {"page_status": "doesnt_say", "status_shown": "assistant_only_yes"},
    ]
    assert store_result(rows, pages_read=True) == "not_answered_on_pages"
    assert store_result(rows[:2], pages_read=True) != "meets_all_3"
    three_yes = [{"page_status": "yes", "status_shown": "yes"}] * 3
    assert store_result(three_yes, pages_read=True) == "meets_all_3"
    assert store_result(three_yes, pages_read=False) == "still_reading"
    unreadable = [{"page_status": "unreadable", "status_shown": "assistant_only_yes"}] * 3
    assert store_result(unreadable, pages_read=True) == "could_not_read"


def test_six_stores_return_rows_identical_to_the_fixtures(client):
    check = client.get("/api/checks/1").json()
    assert [store["name"] for store in check["stores"]] == [o["name"].strip() for o in RUN["offers"].values()]
    for store, offer in zip(check["stores"], RUN["offers"].values()):
        view = client.get(f"/api/stores/{store['domain']}").json()
        assert {**view, "offer": store["offer"]} == store
        assert store["offer"] == {
            "product_title": offer["title"],
            "variant_id": offer["variant"],
            "variant_labels": offer["labels"],
            "price_cents": offer["price"],
            "price_basis": "catalog price",
        }
        assert offer["url"].endswith(store["domain"])
        cases = {c["condition"]: c for c in SAVED if c["store"] == store["name"]}
        assert store["progress"] == {"replies_in": True, "pages_read": bool(cases)}
        assert [row["condition"] for row in store["rows"]] == list(db.REPLY_KEYS)
        for row in store["rows"]:
            assert row["assistant_reply"] == offer[db.REPLY_KEYS[row["condition"]]]
            assert row["reply_time"] == RUN["searched_at"]
            if not cases:
                assert row["status_shown"] == row["page_status"] == row["assistant_status"] == "pending"
                assert row["page_sentences"] == []
                continue
            case = cases[row["condition"]]
            expected = saved_row(case)
            assert row["page_sentences"] == [
                {"sentence": s["sentence"], "url": s["url"], "label": s["label"]}
                for s in case["page_sentences"]
            ]
            assert row["assistant_status"] == case["assistant"]
            assert row["page_status"] == expected["page_status"]
            assert row["status_shown"] == expected["status_shown"]
            assert row["contradiction"] == expected["contradiction"]
            assert row["date_read"] == RUN["searched_at"]
    assert {store["name"]: store["result"] for store in check["stores"]} == {
        "NapQueen": "not_answered_on_pages",
        "Novilla": "meets_all_3",
        "SweetNight": "meets_all_3",
        "Dwellinhaus": "still_reading",
        "BedStory": "says_no",
        "Lee Furniture, NC": "still_reading",
    }


def test_every_yes_row_has_the_stores_exact_sentence(client):
    yes_rows = 0
    for store in client.get("/api/checks/1").json()["stores"]:
        for row in store["rows"]:
            if row["page_status"] == "yes" or row["status_shown"] == "yes":
                yes_rows += 1
                assert any(s["label"] == "yes" and s["sentence"] for s in row["page_sentences"])
    assert yes_rows == 7
    conn = db.connect()
    with pytest.raises(db.sqlite3.IntegrityError):
        conn.execute("UPDATE findings SET page_sentences = '[]' WHERE page_status = 'yes'")
    conn.close()


def test_seed_holds_an_assistant_only_yes_and_a_pages_disagree_case(client):
    napqueen = client.get("/api/stores/napqueensleep.com").json()
    assert [row["status_shown"] for row in napqueen["rows"]] == ["yes", "doesnt_say", "assistant_only_yes"]
    assert napqueen["rows"][2]["counts_toward_meets_all_3"] is False
    shipping = client.get("/api/stores/bedstory.com").json()["rows"][1]
    assert shipping["status_shown"] == "no" and shipping["contradiction"] is True
    assert [s["label"] for s in shipping["page_sentences"]] == ["yes", "no"]


def test_no_row_is_yes_while_pages_are_being_read(client):
    conn = db.connect()
    with conn:
        conn.execute("UPDATE offers SET pages_read = 0")
    conn.close()
    for store in client.get("/api/checks/1").json()["stores"]:
        assert store["result"] == "still_reading"
        for row in store["rows"]:
            assert row["status_shown"] == "pending"
            assert row["counts_toward_meets_all_3"] is False
            assert row["page_sentences"] == []
            assert row["assistant_reply"]
    assert client.get("/api/stores/novillashop.com").json()["result"] == "still_reading"


def test_unknown_store_is_not_checked_never_a_yes(client):
    view = client.get("/api/stores/example.com").json()
    assert view["result"] == "not_checked" and view["rows"] == [] and view["checked"] is False
    check_id = client.post("/api/checks", json={"stores": ["https://www.example.com/p", "novillashop.com"]}).json()["id"]
    stores = client.get(f"/api/checks/{check_id}").json()["stores"]
    assert [s["result"] for s in stores] == ["not_checked", "meets_all_3"]
    assert client.get("/api/checks/999").status_code == 404


def test_mcp_tool_returns_the_same_rows(client):
    stores = [db.store_domain(o["url"]) for o in RUN["offers"].values()] + ["example.com"]
    result = asyncio.run(mcp.call_tool("check_stores", {"stores": stores}))
    from_tool = [json.loads(item.text) for item in result.content]
    assert from_tool == [client.get(f"/api/stores/{store}").json() for store in stores]
    assert [tool.name for tool in asyncio.run(mcp.list_tools())] == ["check_stores"]
