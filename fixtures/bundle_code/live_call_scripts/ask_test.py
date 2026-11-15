import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ucp_call import rpc

PROFILE = "https://shopify.dev/ucp/agent-profiles/draft/valid-with-capabilities.json"
QUESTIONS = [
    "Can I return a mattress after opening it and sleeping on it?",
    "If I return an opened mattress, is return shipping free or do I pay for it?",
    "Can I return a mattress that I bought on sale or at a discount?",
]

out = {}
for endpoint in sys.argv[2:]:
    out[endpoint] = []
    for q in QUESTIONS:
        code, res = rpc(endpoint, "tools/call", {"name": "ask_business", "arguments": {"meta": {"ucp-agent": {"profile": PROFILE}}, "ask": {"query": q, "context": {"address_country": "US"}}}})
        sc = res.get("result", {}).get("structuredContent", {}) if isinstance(res, dict) else {}
        ans = (sc.get("answer") or {}).get("plain")
        out[endpoint].append({"q": q, "http": code, "answer": ans, "keys": sorted(sc.keys()), "links": sc.get("links"), "messages": sc.get("messages"), "ucp": (sc.get("ucp") or {}).get("version"), "error": res.get("error") if isinstance(res, dict) else None, "raw": None if ans else json.dumps(res)[:700]})
        time.sleep(1.5)
json.dump(out, open(sys.argv[1], "w"), indent=1)
for ep, rows in out.items():
    print("==", ep)
    for r in rows:
        print(" Q:", r["q"])
        print("   http", r["http"], "| keys", r["keys"], "| ucp", r["ucp"], "| links", r["links"], "| messages", r["messages"])
        print("   A:", r["answer"] if r["answer"] else r["raw"])
