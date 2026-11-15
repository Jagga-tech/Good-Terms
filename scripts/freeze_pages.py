"""Read stores' public pages once, live, and freeze the text under fixtures/.

Paced at one request a second per store, within each store's robots.txt. Reads the three
first-pass pages, then every page a second pass could pick for any open condition.
Usage: uv run python -m scripts.freeze_pages <product url or store domain> [...]
"""

import asyncio
import itertools
import sys

import httpx

from api.frozen import folder_for, save
from api.reader import PRIORITIES, Reader
from api.shopify import UA


async def find_product(client, base):
    """A mattress from the store's own product list: a queen if there is one."""
    response = await client.get(f"{base}/products.json?limit=250", headers={"User-Agent": UA}, timeout=20)
    if response.status_code != 200:
        return None, f"product list returned HTTP {response.status_code}"
    products = [p for p in response.json().get("products", []) if "mattress" in p.get("title", "").lower()]
    for product in products:
        queen = [v for v in product.get("variants", []) if "queen" in v.get("title", "").lower()]
        if queen:
            return f"{base}/products/{product['handle']}", {"title": product["title"], "variant": queen[0]["title"]}
    if products:
        first = products[0]
        return f"{base}/products/{first['handle']}", {"title": first["title"], "variant": first["variants"][0]["title"]}
    return None, "no mattress in the store's product list"


async def freeze(client, target):
    product = {}
    if "/products/" not in target:
        base = "https://" + target.removeprefix("https://").strip("/")
        probe = Reader(client, base + "/", pace=1.0)
        if not await probe.allowed(base + "/products.json"):
            return target, "robots.txt blocks the product list"
        await asyncio.sleep(1.0)
        target, product = await find_product(client, base)
        if not target:
            target, product = base + "/", {"title": None, "note": f"{product}; the home page was read in its place"}
    reader = Reader(client, target.split("?")[0], pace=1.0)
    await reader.first_pass()
    await reader.sitemap()
    conditions = list(PRIORITIES)
    for size in (3, 2, 1):
        for subset in itertools.combinations(conditions, size):
            for url in reader.choose(set(subset)):
                await reader.read(url, reader.candidates[url])
    fact = await reader.clearance(reader.texts())
    report = save(reader, folder_for(reader.host), product, [fact] if fact else [])
    read = sum(p["status"] == "200" for p in report["pages"])
    return reader.host, f"{read} pages saved, {len(report['blocked'])} blocked by robots.txt, product {reader.product_url}"


async def main():
    async with httpx.AsyncClient() as client:
        for store, outcome in await asyncio.gather(*(freeze(client, target) for target in sys.argv[1:])):
            print(f"{store}: {outcome}")


if __name__ == "__main__":
    asyncio.run(main())
