import json

from api import db

PROFILE = (db.ROOT / "docs" / "agent-profile.url").read_text().strip()
CATALOG = "https://catalog.shopify.com/api/ucp/mcp"
UA = "GoodTerms-prototype/0.1"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": UA,
}
META = {"meta": {"ucp-agent": {"profile": PROFILE}}}


class ShopifyError(Exception):
    pass


async def rpc(client, url, method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = await client.post(url, json=body, headers=HEADERS, timeout=30)
    if response.status_code != 200:
        raise ShopifyError(f"HTTP {response.status_code} from {url}: {response.text[:200]}")
    payload = response.json()
    if "error" in payload or payload.get("result", {}).get("isError"):
        raise ShopifyError(f"{method} at {url}: {json.dumps(payload)[:300]}")
    return payload["result"]


async def tool(client, url, name, arguments):
    result = await rpc(client, url, "tools/call", {"name": name, "arguments": {**META, **arguments}})
    return result["structuredContent"]


async def ask(client, myshopify_domain, question, variant_id):
    """One ask_business call with the product attached. Returns the reply word for word."""
    reply = await tool(
        client,
        f"https://{myshopify_domain}/api/ucp/mcp",
        "ask_business",
        {
            "ask": {
                "query": question,
                "ids": [variant_id],
                "context": {"address_country": "US", "language": "en"},
            }
        },
    )
    return (reply.get("answer") or {}).get("plain") or None
