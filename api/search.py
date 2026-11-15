"""The live catalog search. There is no store list here and no store filter: the offers are
whatever Shopify's Global Catalog returns for the buyer's request."""

import asyncio
import re
from urllib.parse import urlparse

import httpx

from api.shopify import CATALOG, UA, ShopifyError, tool

ASK = "dev.ucp.common.ask"


def is_size(label, size):
    """True for the size asked for, also when the store adds a measure: Queen (80"x 60")."""
    return bool(re.fullmatch(rf"{re.escape(size)}(\s*\(.*\))?", label.strip(), re.I))


def size_choice(product, size):
    """The product's own option name and label for the size, or None if it has none."""
    for option in product.get("options", []):
        for value in option.get("values", []):
            if is_size(value.get("label", ""), size):
                return {"name": option["name"], "label": value["label"]}
    return None


def variant_is_size(variant, size):
    return any(is_size(option.get("label", ""), size) for option in variant.get("options", []))


async def sized_offer(client, product, size, zip_code, budget_cents):
    """The lowest-priced in-stock variant in the requested size, or None if it cannot be confirmed."""
    choice = size_choice(product, size)
    if not choice:
        return None
    try:
        detail = await tool(
            client,
            CATALOG,
            "get_product",
            {
                "catalog": {
                    "id": product["id"],
                    "selected": [choice],
                    "context": {"address_country": "US", "postal_code": zip_code},
                }
            },
        )
    except (ShopifyError, httpx.HTTPError):
        return None
    variants = [
        v
        for v in detail["product"].get("variants", [])
        if variant_is_size(v, size)
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
        "product_url": (variant.get("url") or seller["url"]).split("?")[0],
        "variant_id": variant["id"],
        "variant_labels": [o["label"] for o in variant.get("options", [])],
        "price_cents": variant["price"]["amount"],
        "price_basis": "catalog price",
        "checkout_url": variant["checkout_url"],
    }


async def store_profile(client, offer):
    """The store's own UCP profile: where its endpoint is and whether it offers Ask."""
    fallback = f"https://{offer['myshopify_domain']}/api/ucp/mcp"
    try:
        response = await client.get(
            offer["storefront_url"].rstrip("/") + "/.well-known/ucp",
            headers={"User-Agent": UA},
            follow_redirects=True,
            timeout=10,
        )
        profile = response.json()["ucp"]
    except (httpx.HTTPError, ValueError, KeyError):
        return {"endpoint": fallback, "ask_offered": None}
    endpoints = [
        entry.get("endpoint")
        for entries in profile.get("services", {}).values()
        for entry in entries
        if entry.get("transport") == "mcp" and str(entry.get("endpoint", "")).startswith("https://")
    ]
    return {"endpoint": endpoints[0] if endpoints else fallback, "ask_offered": ASK in profile.get("capabilities", {})}


async def seller_offer(client, products, size, zip_code, budget_cents):
    """One offer for a seller: its first listed product that has the size in stock within budget."""
    for product in products:
        offer = await sized_offer(client, product, size, zip_code, budget_cents)
        if offer:
            return {**offer, **await store_profile(client, offer)}
    return None


async def search(client, query, size, budget_cents, zip_code, limit=6):
    """One size-checked offer per seller, in the catalog's order, six at most."""
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
    by_seller = {}
    for product in found.get("products", []):
        by_seller.setdefault(product["variants"][0]["seller"]["domain"], []).append(product)
    offers = await asyncio.gather(
        *(seller_offer(client, products, size, zip_code, budget_cents) for products in by_seller.values())
    )
    return [offer for offer in offers if offer][:limit]
