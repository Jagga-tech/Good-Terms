import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from api import check, db
from api.check import StoreCheck, quote_check, start_check, triggers
from api.main import app
from api.reader import SECOND_PASS_PAGES, Reader

BASE = "https://shop.test"
PRODUCT = f"{BASE}/products/cloud-mattress"
YES = "You can return an opened mattress within 100 nights for a full refund."
FREE = "Return shipping is free for opened mattresses."
SALE_NO = "Sale items cannot be returned."
HTML = "<html><head><title>x</title></head><body><main>{}</main></body></html>"
SITE = {
    "/robots.txt": "User-agent: *\nDisallow: /policies/refund-policy\n",
    "/products/cloud-mattress": HTML.format(
        '<p>Cloud Mattress</p><a href="/pages/returns">Returns</a><a href="/pages/sale-terms">Sale terms</a>'
        '<a href="/pages/faq">FAQ</a><a href="/pages/about">About</a>'
        + "".join(f'<a href="/pages/return-note-{i}">Return note {i}</a>' for i in range(12))
    ),
    "/pages/returns": HTML.format(f"<h2>Opened mattresses</h2><p>{YES} {FREE}</p>"),
    "/policies/shipping-policy": HTML.format("<p>We ship in 3 days.</p>"),
    "/pages/sale-terms": HTML.format(f"<p>{SALE_NO}</p>"),
    "/pages/faq": HTML.format("<p>Questions and answers.</p>"),
}
OFFER = {
    "store_domain": "shop.test",
    "name": "Shop Test",
    "storefront_url": BASE,
    "myshopify_domain": "shop-test.myshopify.com",
    "product_title": "Cloud Mattress",
    "product_url": PRODUCT,
    "variant_id": "gid://shopify/ProductVariant/1",
    "variant_labels": ["Queen"],
    "price_cents": 19900,
}
REPLIES = {"opened_returns": "Yes, you can.", "free_return_shipping": "Yes, it is free.", "sale_item_returns": "Yes."}


class Site:
    def __init__(self, pages=SITE, delay=0.0, limit_once=()):
        self.pages = pages
        self.delay = delay
        self.limit_once = set(limit_once)
        self.requests = []

    async def __call__(self, request):
        self.requests.append((request.url.path, time.monotonic()))
        if self.delay:
            await asyncio.sleep(self.delay)
        if request.url.path in self.limit_once:
            self.limit_once.discard(request.url.path)
            return httpx.Response(429, headers={"retry-after": "0"})
        body = self.pages.get(request.url.path)
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def paths(self):
        return [path for path, _ in self.requests]


class StubLabeler:
    def __init__(self, pages, replies=None, delay=0.0):
        self.page_findings = pages
        self.reply_labels = replies or {}
        self.delay = delay

    async def pages(self, conditions, product, pages, facts=()):
        await asyncio.sleep(self.delay)
        urls = [url for url, _ in pages]
        return {c: [f for f in found if f["url"] in urls] for c, found in self.page_findings.items()}

    async def replies(self, conditions, product, replies):
        return self.reply_labels

    async def recheck(self, condition, product, finding):
        return finding["label"]


def finding(status, sentence, path, heading=""):
    return {"status": status, "sentence": sentence, "url": BASE + path, "heading": heading}


@pytest.fixture()
def api():
    with TestClient(app) as client:
        yield client


def store_check(site, labeler, replies=REPLIES, pace=0.0):
    check_id = start_check([OFFER], "queen mattress", "Queen", 40000)
    conn = db.connect()
    offer = dict(conn.execute("SELECT * FROM offers WHERE check_id = ?", (check_id,)).fetchone())
    conds = check.conditions(conn)
    conn.close()
    client = site.client()
    reader = Reader(client, PRODUCT, pace=pace)
    return check_id, StoreCheck(check_id, offer, conds, client, labeler, reader, saved_replies=replies)


def test_quote_check_keeps_only_sentences_found_word_for_word():
    texts = [(BASE + "/pages/returns", f"Opened mattresses\n{YES}\n{FREE}"), (BASE + "/pages/faq", "Other text here.")]
    found = quote_check(
        [
            finding("yes", YES, "/pages/returns", "Opened mattresses"),
            finding("yes", "You can return an opened mattress any time.", "/pages/returns"),
            finding("no", FREE, "/pages/faq"),
            finding("yes", "  You can return an opened   mattress within 100 nights for a full refund.", "/pages/returns", "No such heading"),
            finding("doesnt_say", "Other text here.", "/pages/faq"),
        ],
        texts,
    )
    assert found == [
        {"sentence": YES, "url": BASE + "/pages/returns", "label": "yes", "heading": "Opened mattresses"},
        {"sentence": FREE, "url": BASE + "/pages/returns", "label": "no"},
        {"sentence": YES, "url": BASE + "/pages/returns", "label": "yes"},
    ]
    assert quote_check([finding("yes", "Made up sentence about returns.", "/pages/returns")], texts) == []
    assert quote_check([finding("doesnt_say", "Other text here.", "/pages/faq")], texts)[0]["label"] == "doesnt_say"
    trial = "You've got 100 nights to see if it's your dream sleep match."
    pages = [(BASE + "/pages/returns", f"{trial} {YES}")]
    assert quote_check([finding("yes", trial, "/pages/returns")], pages, "opened_returns") == []
    assert quote_check([finding("yes", YES, "/pages/returns", "** Opened mattresses")], [(BASE + "/pages/returns", f"** Opened mattresses {YES}")], "opened_returns")[0]["heading"] == "Opened mattresses"


def test_second_pass_triggers():
    said = lambda *statuses: dict(zip(("a", "b", "c"), statuses))
    assert triggers(said("no", "no", "no"), said("no", "no", "no")) == set()
    assert triggers(said("yes", "doesnt_say", "no"), {}) == {"b"}
    assert triggers(said("yes", "no", "no"), said("no", "no", "yes")) == {"a", "c"}
    assert triggers(said("yes", "yes", "yes"), said("yes", "yes", "yes")) == {"a", "b", "c"}


def test_reader_respects_robots_and_uses_the_returns_page_the_store_links_to():
    site = Site()
    reader = Reader(site.client(), PRODUCT, pace=0.0)
    asyncio.run(reader.first_pass())
    assert "/policies/refund-policy" not in site.paths()
    assert {page.url: page.status for page in reader.pages.values()} == {
        PRODUCT: "200",
        BASE + "/policies/refund-policy": "blocked",
        BASE + "/pages/returns": "200",
        BASE + "/policies/shipping-policy": "200",
    }
    assert len(reader.texts()) == 3
    assert YES in dict(reader.texts())[BASE + "/pages/returns"]


def test_reader_reads_at_most_eight_more_pages_chosen_for_the_open_condition():
    site = Site()
    reader = Reader(site.client(), PRODUCT, pace=0.0)

    async def both():
        await reader.first_pass()
        before = len(site.requests)
        await reader.second_pass({"sale_item_returns"})
        return [path for path in site.paths()[before:] if "sitemap" not in path]

    extra = asyncio.run(both())
    assert len(extra) == SECOND_PASS_PAGES
    assert extra[0] == "/pages/sale-terms"
    assert "/pages/about" not in extra


def test_reader_paces_requests_and_waits_on_429():
    site = Site(limit_once={"/policies/shipping-policy"})
    reader = Reader(site.client(), PRODUCT, pace=0.15)
    asyncio.run(reader.first_pass())
    times = [at for _, at in site.requests]
    assert all(later - earlier >= 0.14 for earlier, later in zip(times, times[1:]))
    assert site.paths().count("/policies/shipping-policy") == 2
    assert reader.pages[BASE + "/policies/shipping-policy"].status == "200"


def test_pipeline_rows_turn_final_in_one_step_and_a_bad_quote_is_not_a_yes(api):
    labeler = StubLabeler(
        {
            "opened_returns": [finding("yes", YES, "/pages/returns", "Opened mattresses")],
            "free_return_shipping": [finding("yes", "Return shipping is always free.", "/pages/returns")],
            "sale_item_returns": [finding("no", SALE_NO, "/pages/sale-terms")],
        },
        replies={"opened_returns": "yes", "free_return_shipping": "yes", "sale_item_returns": "yes"},
        delay=0.3,
    )
    site = Site()
    check_id, store = store_check(site, labeler)
    seen = []

    async def watch():
        task = asyncio.create_task(store.run())
        while not task.done():
            await asyncio.sleep(0.05)
            seen.append(api.get(f"/api/checks/{check_id}").json()["stores"][0])
        await task

    asyncio.run(watch())
    during = [s for s in seen if not s["progress"]["pages_read"]]
    assert during and any(s["progress"]["replies_in"] for s in during)
    for snapshot in during:
        assert snapshot["result"] == "still_reading"
        assert all(row["status_shown"] == "pending" and not row["page_sentences"] for row in snapshot["rows"])
    assert any(row["assistant_reply"] for s in during for row in s["rows"])
    final = api.get(f"/api/checks/{check_id}").json()["stores"][0]
    rows = {row["condition"]: row for row in final["rows"]}
    assert rows["opened_returns"]["status_shown"] == "yes"
    assert rows["opened_returns"]["page_sentences"] == [
        {"sentence": YES, "url": BASE + "/pages/returns", "label": "yes", "heading": "Opened mattresses"}
    ]
    assert rows["free_return_shipping"]["page_status"] == "doesnt_say"
    assert rows["free_return_shipping"]["status_shown"] == "assistant_only_yes"
    assert rows["sale_item_returns"]["status_shown"] == "no" and rows["sale_item_returns"]["contradiction"]
    assert final["result"] == "says_no"
    assert "/pages/sale-terms" in site.paths() and "/policies/refund-policy" not in site.paths()
    assert api.get("/api/stores/shop.test").json()["rows"] == final["rows"]


def test_a_store_that_runs_out_of_time_is_closed_with_what_was_found(api):
    labeler = StubLabeler({"opened_returns": [finding("yes", YES, "/pages/returns")]})
    check_id, store = store_check(Site(delay=0.4), labeler)
    asyncio.run(store.run(limit=0.6))
    final = api.get(f"/api/checks/{check_id}").json()["stores"][0]
    assert final["progress"]["pages_read"] is True
    for row in final["rows"]:
        assert row["read_note"] == "The read was cut short."
        assert row["page_status"] == "doesnt_say" and row["status_shown"] != "yes"


def test_a_store_whose_pages_cannot_be_read_is_never_a_yes(api):
    labeler = StubLabeler({}, replies={"opened_returns": "yes", "free_return_shipping": "no", "sale_item_returns": "doesnt_say"})
    blocked = {**SITE, "/robots.txt": "User-agent: *\nDisallow: /\n"}
    site = Site(blocked)
    check_id, store = store_check(site, labeler)
    asyncio.run(store.run())
    assert site.paths() == ["/robots.txt"]
    final = api.get(f"/api/checks/{check_id}").json()["stores"][0]
    assert [row["page_status"] for row in final["rows"]] == ["unreadable"] * 3
    assert final["rows"][0]["status_text"] == "Store's assistant says yes. We couldn't read its pages."
    assert final["rows"][1]["status_shown"] == "no"
    assert final["result"] == "says_no"


def test_no_checkout_or_deprecated_tool_is_called_anywhere():
    for path in (db.ROOT / "api").glob("*.py"):
        source = path.read_text()
        for name in ("complete_checkout", "create_checkout", "create_cart", "search_shop_policies_and_faqs"):
            assert name not in source, (path.name, name)


def test_a_cancellation_sentence_never_counts_for_a_return_condition():
    cancel = "Cancellations after shipping are subject to a 20% restocking fee, and the customer is responsible for the return shipping cost."
    texts = [(BASE + "/pages/returns", f"{cancel} {FREE}")]
    for status in ("yes", "no", "unclear", "doesnt_say"):
        assert quote_check([finding(status, cancel, "/pages/returns")], texts, "free_return_shipping") == []
    kept = quote_check([finding("no", cancel, "/pages/returns"), finding("yes", FREE, "/pages/returns")], texts, "free_return_shipping")
    assert [k["label"] for k in kept] == ["yes"]
    shipped = "If the order has already shipped, customers may be responsible for return shipping costs."
    under = [finding("unclear", shipped, "/pages/returns", "What is the cancellation policy?")]
    assert quote_check(under, [(BASE + "/pages/returns", f"What is the cancellation policy? {shipped}")], "free_return_shipping") == []


def test_a_sentence_is_not_a_sale_yes_only_because_it_mentions_a_sale():
    trial = "All mattresses bought during the Labor Day Sale are backed by our 100-Night Risk-Free Trial."
    same = "Mattresses bought on sale come with the same 100-night trial (after a 30-night break-in period) and 10-year warranty."
    unchanged = "Buying on sale doesn't change your coverage."
    returned = "Sale items can be returned within 30 days."
    texts = [(BASE + "/pages/sale-terms", " ".join([trial, same, unchanged, returned]))]
    check = lambda sentence: quote_check([finding("yes", sentence, "/pages/sale-terms")], texts, "sale_item_returns")
    assert check(trial) == []
    assert check(same) and check(unchanged) and check(returned)


def test_the_same_text_gets_the_same_label_and_is_asked_once(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from api import labeler

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("LABEL_CACHE", raising=False)
    answers = iter(["yes", "no", "doesnt_say"])
    calls = []

    async def create(**request):
        calls.append(request["messages"][0]["content"])
        answer = {"conditions": [{"condition": "opened_returns", "findings": [{"status": next(answers), "sentence": YES, "url": "x", "heading": ""}]}]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(answer))])

    def make():
        made = labeler.Labeler(cache=tmp_path / "labels.db")
        made.client = SimpleNamespace(messages=SimpleNamespace(create=create))
        return made

    conds = [{"id": "opened_returns", "label": "Opened returns", "definition": "d", "question": "q"}]
    ask = lambda lab, text: asyncio.run(lab.pages(conds, "Cloud Mattress", [(BASE + "/pages/returns", text)]))
    first = ask(make(), YES)
    again = ask(make(), YES)
    assert first == again and len(calls) == 1
    assert first["opened_returns"][0]["status"] == "yes"
    changed = ask(make(), YES + " New words on the page.")
    assert len(calls) == 2 and changed["opened_returns"][0]["status"] == "no"
    assert ask(make(), YES) == first and len(calls) == 2


def test_a_sentence_about_something_else_cannot_put_a_yes_in_doubt():
    address = "If you need to change the address during the delivering period, the additional charge is on you."
    texts = [(BASE + "/pages/returns", f"{FREE} {address}")]
    kept = quote_check([finding("yes", FREE, "/pages/returns"), finding("unclear", address, "/pages/returns")], texts, "free_return_shipping")
    assert [k["label"] for k in kept] == ["yes"]
    vague = "These amounts will be deducted from your refund."
    pays = "If the return is for personal reasons, you will need to cover the shipping costs."
    both = [(BASE + "/pages/returns", f"{vague} {pays}")]
    assert quote_check([finding("no", vague, "/pages/returns")], both, "free_return_shipping") == []
    assert quote_check([finding("no", pays, "/pages/returns")], both, "free_return_shipping")[0]["label"] == "no"


def test_a_clearance_sentence_does_not_answer_for_a_sale_priced_item():
    clearance = "Clearance Items: All clearance items are considered final sale and are not eligible for returns."
    sale = "Sale items and clearance items cannot be returned."
    texts = [(BASE + "/pages/returns", f"{clearance} {sale}")]
    check = lambda sentence, listed=False: quote_check([finding("no", sentence, "/pages/returns")], texts, "sale_item_returns", listed)
    assert check(clearance) == []
    assert check(clearance, listed=True)[0]["label"] == "no"
    assert check(sale)[0]["label"] == "no"


def run_store_with_ask(fake_ask, monkeypatch, api):
    monkeypatch.setattr(check, "ask", fake_ask)
    labeler = StubLabeler({}, replies={"opened_returns": "yes", "free_return_shipping": "yes", "sale_item_returns": "yes"})
    check_id, store = store_check(Site(), labeler, replies=None)
    asyncio.run(store.run())
    return api.get(f"/api/checks/{check_id}").json()["stores"][0]


def test_a_reply_is_saved_with_its_time_and_reused_for_the_rest_of_the_day(api, monkeypatch):
    asked = []

    async def fake_ask(client, domain, question, variant):
        asked.append(question)
        return f"Reply number {len(asked)}."

    first = run_store_with_ask(fake_ask, monkeypatch, api)
    assert len(asked) == 3
    second = run_store_with_ask(fake_ask, monkeypatch, api)
    assert len(asked) == 3
    for before, after in zip(first["rows"], second["rows"]):
        assert before["assistant_reply"] == after["assistant_reply"]
        assert before["reply_time"] == after["reply_time"]
        assert len(before["reply_time"]) == len("2026-11-15 14:02")
    from api import replies

    monkeypatch.setattr(replies, "now", lambda: "2099-01-01 09:00")
    run_store_with_ask(fake_ask, monkeypatch, api)
    assert len(asked) == 6


def test_a_blocked_ask_is_said_in_plain_words_and_is_never_a_yes(api, monkeypatch):
    from api.shopify import ShopifyError

    async def blocked(client, domain, question, variant):
        raise ShopifyError("HTTP 429", 429, 1265)

    store = run_store_with_ask(blocked, monkeypatch, api)
    for row in store["rows"]:
        assert row["assistant_reply"] is None and row["assistant_status"] == "unavailable"
        assert row["assistant_text"].startswith("Shopify's limit on questions to store assistants was reached")
        assert "asked again after" in row["assistant_text"]
        assert row["status_shown"] != "assistant_only_yes"


def test_after_a_long_429_no_further_question_is_sent(monkeypatch):
    from api import shopify

    calls = []

    async def limited(request):
        calls.append(request.url.host)
        body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "Rate limit exceeded", "data": "Too many requests, please retry after 1265 seconds"}}
        return httpx.Response(429, json=body)

    monkeypatch.setattr(shopify, "ask_blocked_until", 0.0)

    async def two_asks():
        async with httpx.AsyncClient(transport=httpx.MockTransport(limited)) as client:
            for domain in ("a.myshopify.com", "b.myshopify.com"):
                with pytest.raises(shopify.ShopifyError) as problem:
                    await shopify.ask(client, f"https://{domain}/api/ucp/mcp", "q", "gid://shopify/ProductVariant/1")
                assert problem.value.status == 429 and problem.value.retry_after > 1200

    asyncio.run(two_asks())
    assert calls == ["a.myshopify.com"]
