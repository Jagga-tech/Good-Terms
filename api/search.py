import asyncio
from urllib.parse import urlparse

from api.shopify import CATALOG, ShopifyError, tool


def size_option(product, size):
    for option in product.get("options", []):
        if any(value.get("label", "").lower() == size.lower() for value in option.get("values", [])):
            return option["name"]
    return None


def is_size(variant, size):
    return any(o.get("label", "").lower() == size.lower() for o in variant.get("options", []))


async def sized_offer(client, product, size, zip_code, budget_cents):
    """The lowest-priced in-stock variant in the requested size, or None if it cannot be confirmed."""
    name = size_option(product, size)
    if not name:
        return None
    try:
        detail = await tool(
            client,
            CATALOG,
            "get_product",
            {
                "catalog": {
                    "id": product["id"],
                    "selected": [{"name": name, "label": size}],
                    "context": {"address_country": "US", "postal_code": zip_code},
                }
            },
        )
    except ShopifyError:
        return None
    variants = [
        v
        for v in detail["product"].get("variants", [])
        if is_size(v, size)
        and (v.get("availability") or {}).get("available")
        and v["price"]["amount"] <= budget_cents
        and str(v.get("checkout_url", "")).startswith("https://")
    ]
    if not variants:
        return None
    variant = min(variants, key=lambda v: v["price"]["amount"])
    seller = variant["seller"]
    return {
        "name": seller["name"].strip(),
        "storefront_url": seller["url"],
        "store_domain": urlparse(seller["url"]).netloc.removeprefix("www."),
        "myshopify_domain": seller["domain"],
        "product_title": detail["product"]["title"],
        "product_url": variant.get("url") or seller["url"],
        "variant_id": variant["id"],
        "variant_labels": [o["label"] for o in variant.get("options", [])],
        "price_cents": variant["price"]["amount"],
        "checkout_url": variant["checkout_url"],
    }


async def search(client, query, size, budget_cents, zip_code, limit=6):
    """A live catalog search with no store filter: one size-checked offer per seller."""
    found = await tool(
        client,
        CATALOG,
        "search_catalog",
        {
            "catalog": {
                "query": query,
                "filters": {
                    "ships_to": {"country": "US", "postal_code": zip_code},
                    "available": True,
                    "price": {"max": budget_cents},
                },
            }
        },
    )
    first_per_seller = {}
    for product in found.get("products", []):
        seller = product["variants"][0]["seller"]["domain"]
        if size_option(product, size):
            first_per_seller.setdefault(seller, product)
    offers = await asyncio.gather(
        *(sized_offer(client, p, size, zip_code, budget_cents) for p in first_per_seller.values())
    )
    return [offer for offer in offers if offer][:limit]
