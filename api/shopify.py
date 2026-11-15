import asyncio
import json
import re
import time

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
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


ask_blocked_until = 0.0


async def rpc(client, url, method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = await client.post(url, json=body, headers=HEADERS, timeout=30)
    if response.status_code != 200:
        wait = re.search(r"retry after (\d+) seconds", response.text)
        header = response.headers.get("retry-after", "")
        seconds = int(wait.group(1)) if wait else int(header) if header.isdigit() else None
        raise ShopifyError(
            f"HTTP {response.status_code} from {url}: {response.text[:200]}", response.status_code, seconds
        )
    payload = response.json()
    if "error" in payload or payload.get("result", {}).get("isError"):
        raise ShopifyError(f"{method} at {url}: {json.dumps(payload)[:300]}")
    return payload["result"]


async def tool(client, url, name, arguments):
    result = await rpc(client, url, "tools/call", {"name": name, "arguments": {**META, **arguments}})
    return result["structuredContent"]


async def ask(client, endpoint, question, variant_id):
    """One ask_business call with the product attached. Returns the reply word for word.

    On HTTP 429 it waits and retries once when the wait is short. When Shopify asks for a
    long wait, no further question is sent to any store until that time has passed.
    """
    global ask_blocked_until
    arguments = {
        "ask": {"query": question, "ids": [variant_id], "context": {"address_country": "US", "language": "en"}}
    }
    for attempt in range(2):
        if time.time() < ask_blocked_until:
            raise ShopifyError("Ask is blocked", 429, ask_blocked_until - time.time())
        try:
            reply = await tool(client, endpoint, "ask_business", arguments)
            return (reply.get("answer") or {}).get("plain") or None
        except ShopifyError as problem:
            if problem.status != 429:
                raise
            wait = problem.retry_after or 30
            if attempt or wait > 5:
                ask_blocked_until = max(ask_blocked_until, time.time() + wait)
                raise
            await asyncio.sleep(wait)
