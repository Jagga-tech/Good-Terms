"""M0 smoke test: four live Shopify calls with our own agent profile and no credentials.

First checks that the pinned profile address serves the same file as docs/agent-profile.json
with a public Cache-Control header. Then runs one catalog search, one get_product,
one tools/list and one ask_business. Exits 0 only if everything passes.
Usage: python3 scripts/smoke.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROFILE = os.environ.get(
    "AGENT_PROFILE_URL",
    "https://cdn.jsdelivr.net/gh/Jagga-tech/Good-Terms@c4141f1e304f2776f109ed555a9f1fa1f6d2bd69/docs/agent-profile.json",
)
LOCAL_PROFILE = Path(__file__).resolve().parent.parent / "docs" / "agent-profile.json"
CATALOG = "https://catalog.shopify.com/api/ucp/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": "GoodTerms-prototype/0.1",
}
META = {"meta": {"ucp-agent": {"profile": PROFILE}}}
SIZE = "Queen"
ZIP = "94541"
QUESTION = (
    "I want to buy this queen mattress. If I open it and sleep on it, "
    "can I still return it for a refund?"
)


def rpc(url, method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as error:
        raise SystemExit(f"FAIL {method} {url}: HTTP {error.code} {error.read()[:300]!r}")
    if "error" in payload or payload.get("result", {}).get("isError"):
        raise SystemExit(f"FAIL {method} {url}: {json.dumps(payload)[:500]}")
    return payload["result"]


def tool(url, name, arguments):
    return rpc(url, "tools/call", {"name": name, "arguments": {**META, **arguments}})[
        "structuredContent"
    ]


def size_option(product):
    for option in product.get("options", []):
        if any(value.get("label") == SIZE for value in option.get("values", [])):
            return option["name"]
    return None


def has_size(variant):
    return any(option.get("label") == SIZE for option in variant.get("options", []))


def check_profile():
    request = urllib.request.Request(PROFILE, headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        cache = response.headers.get("Cache-Control", "")
        served = json.loads(response.read())
    if "public" not in cache:
        raise SystemExit(f"FAIL profile: Cache-Control is '{cache}', needs public")
    if served != json.loads(LOCAL_PROFILE.read_text()):
        raise SystemExit("FAIL profile: pinned address differs from docs/agent-profile.json")
    print(f"PASS profile: matches docs/agent-profile.json, Cache-Control: {cache}")


def main():
    print(f"profile: {PROFILE}")
    check_profile()

    found = tool(
        CATALOG,
        "search_catalog",
        {
            "catalog": {
                "query": "queen mattress",
                "filters": {
                    "ships_to": {"country": "US", "postal_code": ZIP},
                    "available": True,
                    "price": {"max": 40000},
                },
            }
        },
    )
    products = found.get("products", [])
    product = next((p for p in products if size_option(p)), None)
    if not product:
        raise SystemExit(f"FAIL search_catalog: {len(products)} products, none with a {SIZE} option")
    print(f"PASS search_catalog: {len(products)} products, using '{product['title']}'")

    detail = tool(
        CATALOG,
        "get_product",
        {
            "catalog": {
                "id": product["id"],
                "selected": [{"name": size_option(product), "label": SIZE}],
                "context": {"address_country": "US", "postal_code": ZIP},
            }
        },
    )
    variant = next((v for v in detail["product"].get("variants", []) if has_size(v)), None)
    if not variant:
        raise SystemExit(f"FAIL get_product: no {SIZE} variant returned")
    seller = variant["seller"]
    price = variant["price"]["amount"] / 100
    print(f"PASS get_product: {SIZE} variant {variant['id']} at ${price:.2f} from {seller['name']}")
    print(f"     checkout link: {variant.get('checkout_url')}")

    store = f"https://{urllib.parse.urlparse(seller['url']).netloc}/api/ucp/mcp"
    names = [t["name"] for t in rpc(store, "tools/list", META)["tools"]]
    if "ask_business" not in names:
        raise SystemExit(f"FAIL tools/list {store}: no ask_business in {names}")
    print(f"PASS tools/list {store}: {', '.join(names)}")

    reply = tool(
        store,
        "ask_business",
        {
            "ask": {
                "query": QUESTION,
                "ids": [variant["id"]],
                "context": {"address_country": "US", "language": "en"},
            }
        },
    )
    answer = (reply.get("answer") or {}).get("plain", "")
    if not answer:
        raise SystemExit(f"FAIL ask_business: empty answer {json.dumps(reply)[:400]}")
    print(f"PASS ask_business: {answer}")
    print("SMOKE OK: profile check and 4 of 4 live calls passed, no Shopify credentials used")


if __name__ == "__main__":
    sys.exit(main())
