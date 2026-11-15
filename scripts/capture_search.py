"""Run the demo search once, live, and save every raw response it used as a fixture.

Calls only the Global Catalog and each store's public /.well-known/ucp file. It asks no
store's assistant anything.
Usage: uv run python -m scripts.capture_search
"""

import asyncio
import json
from datetime import date

import httpx

from api import db
from api.search import search
from scripts.m3_live import REQUEST


async def main():
    saved = {"request": REQUEST, "captured_on": date.today().isoformat(), "calls": []}

    async def record(response):
        await response.aread()
        request = response.request
        body = json.loads(request.content) if request.content else None
        saved["calls"].append(
            {"method": request.method, "url": str(request.url), "request": body, "status": response.status_code, "response": response.json()}
        )

    async with httpx.AsyncClient(event_hooks={"response": [record]}) as client:
        offers = await search(client, **REQUEST)
    saved["offers"] = offers
    out = db.FIXTURES / f"search_run_{saved['captured_on']}.json"
    out.write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out.relative_to(db.ROOT)}: {len(saved['calls'])} calls, {len(offers)} offers")
    for offer in offers:
        print(f"  {offer['name'][:24]:24} ${offer['price_cents'] / 100:>7.2f}  {' / '.join(offer['variant_labels'])[:26]:26} ask offered: {offer['ask_offered']}  {offer['endpoint']}")


if __name__ == "__main__":
    asyncio.run(main())
