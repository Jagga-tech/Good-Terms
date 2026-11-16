import asyncio
import copy
import json
import re

import httpx
from api import db, goodterms, search
from tests.test_m3 import StubLabeler, Site, store_check

RUN = db.load("search_run_2026-11-15.json")
TWIN_SEARCH = db.load("catalog_search_2026-11-15.json")
REQUEST = RUN["request"]
SOURCES = [
    path
    for folder in ("api", "scripts", "web/src")
    for path in (db.ROOT / folder).rglob("*")
    if path.suffix in {".py", ".ts", ".tsx"} and ".test." not in path.name
]


def replay(calls):
    """Answer the search's requests from saved responses, and record what was asked."""
    asked = []

    def name_of(body):
        params = body["params"]
        return params["name"], params["arguments"]["catalog"].get("id")

    def handler(request):
        body = json.loads(request.content) if request.content else None
        asked.append({"method": request.method, "url": str(request.url), "request": body})
        for call in calls:
            if call["method"] != request.method or call["url"] != str(request.url):
                continue
            if body is None or name_of(call["request"]) == name_of(body):
                return httpx.Response(call["status"], json=call["response"])
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), asked


def run_search(calls, **request):
    client, asked = replay(calls)
    return asyncio.run(search.search(client, **{**REQUEST, **request})), asked


def test_the_size_rule():
    for label in ("Queen", "queen", "Queen (U.S.Standard)", 'Queen (80"x 60")'):
        assert search.is_size(label, "Queen")
    for label in ("Twin", "Full", "King", "Olympic Queen", "Queen Plus", "Short Queen", "Queen / King"):
        assert not search.is_size(label, "Queen")


def test_the_saved_live_search_gives_one_size_checked_offer_per_seller():
    offers, asked = run_search(RUN["calls"])
    assert offers == RUN["offers"]
    assert len(offers) == 6 and len({offer["myshopify_domain"] for offer in offers}) == 6
    assert len({offer["name"] for offer in offers}) >= 4
    for offer in offers:
        assert any(search.is_size(label, "Queen") for label in offer["variant_labels"])
        assert offer["price_cents"] <= REQUEST["budget_cents"]
        assert offer["price_basis"] == "catalog price"
        number = offer["variant_id"].rsplit("/", 1)[-1]
        assert offer["checkout_url"].startswith(f"{offer['storefront_url']}/buy/{number}:1")
        assert offer["storefront_url"].startswith("https://") and offer["myshopify_domain"].endswith(".myshopify.com")
        assert offer["endpoint"] == f"https://{offer['myshopify_domain']}/api/ucp/mcp" and offer["ask_offered"] is True
        assert "?" not in offer["product_url"]


def test_each_offer_is_the_lowest_priced_queen_in_stock_within_budget():
    offers, _ = run_search(RUN["calls"])
    by_seller = {offer["myshopify_domain"]: offer for offer in offers}
    lookups = [c for c in RUN["calls"] if c["method"] == "POST" and c["request"]["params"]["name"] == "get_product"]
    checked = 0
    for call in lookups:
        variants = call["response"]["result"]["structuredContent"]["product"]["variants"]
        offer = by_seller.get(variants[0]["seller"]["domain"])
        if not offer:
            continue
        fits = [v["price"]["amount"] for v in variants if search.variant_is_size(v, "Queen") and v["availability"]["available"] and v["price"]["amount"] <= REQUEST["budget_cents"]]
        assert offer["price_cents"] == min(fits)
        assert offer["variant_id"] in [v["id"] for v in variants if v["price"]["amount"] == min(fits)]
        checked += 1
    assert checked == 6
    novilla = next(o for o in offers if o["name"] == "Novilla")
    assert (novilla["price_cents"], novilla["variant_labels"]) == (16499, ["Queen", "6 inch"])


def test_search_sends_the_three_filters_and_no_store_filter():
    _, asked = run_search(RUN["calls"])
    catalog = asked[0]["request"]["params"]["arguments"]["catalog"]
    assert catalog["filters"] == {"ships_to": {"country": "US", "postal_code": "94541"}, "available": True, "price": {"max": 40000}}
    assert "shops" not in json.dumps([a["request"] for a in asked])
    source = (db.ROOT / "api" / "search.py").read_text()
    assert "shops" not in source and "myshopify.com" not in source
    for offer in RUN["offers"]:
        assert offer["name"].lower() not in source.lower() and offer["store_domain"] not in source
    hosts = {httpx.URL(a["url"]).host for a in asked if a["method"] == "POST"}
    assert hosts == {"catalog.shopify.com"}


def test_a_queen_search_that_returned_a_twin_never_shows_the_twin():
    """The saved search of 2026-11-15: its first result is a NapQueen Twin for a queen search."""
    found = TWIN_SEARCH["result"]["structuredContent"]["products"]
    first = found[0]["variants"][0]
    assert first["seller"]["name"] == "NapQueen" and [o["label"] for o in first["options"]] == ["Twin", '10"']
    calls = [{"method": "POST", "url": search.CATALOG, "request": {"params": {"name": "search_catalog", "arguments": {"catalog": {}}}}, "status": 200, "response": TWIN_SEARCH}]
    for product in found:
        detail = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"product": product}}}
        calls.append({"method": "POST", "url": search.CATALOG, "request": {"params": {"name": "get_product", "arguments": {"catalog": {"id": product["id"]}}}}, "status": 200, "response": detail})
    offers, _ = run_search(calls, budget_cents=20000)
    assert offers
    for offer in offers:
        assert any(search.is_size(label, "Queen") for label in offer["variant_labels"])
        assert not {"Twin", "Full", "Twin XL", "King"} & set(offer["variant_labels"])
    names = [offer["name"] for offer in offers]
    assert "Novilla" in names and len(names) == len(set(names))
    assert first["id"] not in [offer["variant_id"] for offer in offers]
    napqueen = next(offer for offer in offers if offer["name"] == "NapQueen")
    assert napqueen["variant_labels"][0] == "Queen" and napqueen["product_title"] != found[0]["title"]
    assert not any(name in names for name in ("Price Busters Furniture", "NEXOES"))


def test_a_seller_whose_first_product_does_not_fit_gets_its_next_one():
    calls = copy.deepcopy(RUN["calls"])
    products = calls[0]["response"]["result"]["structuredContent"]["products"]
    novilla = next(p for p in products if p["variants"][0]["seller"]["name"] == "Novilla")
    other = copy.deepcopy(novilla)
    other["id"] = "gid://shopify/p/does-not-fit"
    other["options"] = [{"name": "Bedding size", "values": [{"label": "Twin"}]}]
    products.insert(products.index(novilla), other)
    offers, _ = run_search(calls)
    assert next(o for o in offers if o["name"] == "Novilla")["price_cents"] == 16499


def test_store_profile_falls_back_when_the_public_profile_cannot_be_read():
    offer = {"storefront_url": "https://shop.test", "myshopify_domain": "shop-test.myshopify.com"}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    assert asyncio.run(search.store_profile(client, offer)) == {
        "endpoint": "https://shop-test.myshopify.com/api/ucp/mcp",
        "ask_offered": None,
    }


def test_a_store_without_an_assistant_says_so_and_is_not_asked(monkeypatch):
    labeler = StubLabeler({})
    check_id, store = store_check(Site(), labeler, replies=None)
    store.offer["ask_offered"] = 0
    asyncio.run(store.run())
    rows = goodterms.get_check(check_id)["stores"][0]["rows"]
    for row in rows:
        assert row["assistant_text"] == "No reply available. This store does not offer an assistant to ask."
        assert row["assistant_status"] == "unavailable" and row["read_note"] is None


def test_no_cart_no_checkout_no_deprecated_tool_and_no_shopify_credential_anywhere():
    banned = ("complete_checkout", "create_checkout", "update_checkout", "create_cart", "update_cart", "search_shop_policies_and_faqs")
    credential = re.compile(r"SHOPIFY_[A-Z]|client_secret|access_token|Authorization|Bearer |Shopify-Buyer-IP")
    read = set()
    assert len(SOURCES) > 15
    for path in SOURCES:
        source = path.read_text()
        for name in banned:
            assert name not in source, (path.name, name)
        assert not credential.search(source), path.name
        read |= set(re.findall(r"environ(?:\.get)?[\[(]\s*\"([A-Z_]+)\"", source))
    assert read == {"AGENT_PROFILE_URL", "LABELER_MODEL", "LABELER_EFFORT", "LABEL_CACHE", "COCO_MODEL", "GOODTERMS_MODE", "GOODTERMS_DB", "GOODTERMS_STATE"}
    for line in (db.ROOT / ".env.example").read_text().split():
        assert not line.upper().startswith("SHOPIFY")
