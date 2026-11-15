import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ucp_call import rpc

PROFILE = "https://shopify.dev/ucp/agent-profiles/2026-08-25/valid-with-capabilities.json"
args = {"meta": {"ucp-agent": {"profile": PROFILE}}, "catalog": {"query": "queen mattress", "filters": {"price": {"max": 20000}, "ships_to": {"country": "US", "postal_code": "94541"}}, "context": {"address_country": "US", "postal_code": "94541", "currency": "USD"}, "pagination": {"limit": 10}}}
code, res = rpc("https://catalog.shopify.com/api/ucp/mcp", "tools/call", {"name": "search_catalog", "arguments": args})
json.dump(res, open("catalog_search.json", "w"), indent=1)
sc = res.get("result", {}).get("structuredContent", {})
print("http", code, "| top keys", sorted(sc.keys()), "| error", res.get("error"))
prods = sc.get("products") or (sc.get("catalog") or {}).get("products") or []
print("products", len(prods))
allkeys, vkeys, skeys = set(), set(), set()
for p in prods:
    allkeys |= set(p.keys())
    vs = p.get("variants") or []
    sellers = set()
    for v in vs:
        vkeys |= set(v.keys())
        s = v.get("seller") or {}
        skeys |= set(s.keys())
        sellers.add(s.get("domain"))
    v0 = vs[0] if vs else {}
    print("-", (p.get("title") or "")[:60], "| id", p.get("id"), "| variants", len(vs), "| sellers", sorted(x for x in sellers if x), "| price", (v0.get("price") or {}), "| list", v0.get("list_price"))
print("product keys:", sorted(allkeys))
print("variant keys:", sorted(vkeys))
print("seller keys:", sorted(skeys))
for p in prods[:1]:
    v = (p.get("variants") or [{}])[0]
    print("sample seller:", json.dumps(v.get("seller"))[:900])
    print("sample checkout_url:", str(v.get("checkout_url"))[:160])
    print("sample availability:", json.dumps(v.get("availability"))[:300])
print("messages:", json.dumps(sc.get("messages"))[:400])
