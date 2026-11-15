import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import db
from api.combine import combine, store_result

router = APIRouter(prefix="/api")


class NewCheck(BaseModel):
    stores: list[str]


def domain(value):
    value = re.sub(r"^https?://", "", value.strip().lower())
    return re.sub(r"^www\.", "", value.split("/")[0].split("?")[0])


def store_view(conn, store, offer):
    """One store as every screen and tool sees it: progress, result and the rows."""
    found = conn.execute(
        "SELECT f.*, c.label FROM findings f JOIN conditions c ON c.id = f.condition"
        " WHERE f.store_domain = ? ORDER BY c.rowid",
        (store,),
    ).fetchall()
    if not found:
        return {
            "domain": store,
            "name": None,
            "storefront_url": None,
            "checked": False,
            "progress": None,
            "result": "not_checked",
            "rows": [],
        }
    pages_read = bool(offer and offer["pages_read"])
    rows = []
    for row in found:
        pages = row["page_status"] if pages_read else "pending"
        shown, flag = combine(pages, row["assistant_status"], bool(row["pages_disagree"]))
        rows.append(
            {
                "condition": row["condition"],
                "condition_label": row["label"],
                "page_status": pages,
                "page_sentences": json.loads(row["page_sentences"]) if pages_read else [],
                "date_read": row["date_read"] if pages_read else None,
                "assistant_status": row["assistant_status"],
                "assistant_reply": row["assistant_reply"],
                "reply_time": row["reply_time"],
                "status_shown": shown,
                "counts_toward_meets_all_3": shown == "yes",
                "contradiction": flag,
                "read_note": row["read_note"] if pages_read else None,
            }
        )
    return {
        "domain": store,
        "name": offer["seller_name"] if offer else None,
        "storefront_url": offer["storefront_url"] if offer else None,
        "checked": True,
        "progress": {
            "replies_in": bool(offer and offer["replies_in"]),
            "pages_read": pages_read,
        },
        "result": store_result(rows, pages_read),
        "rows": rows,
    }


def offer_view(offer):
    if offer["price_cents"] is None:
        return None
    return {
        "product_title": offer["product_title"],
        "variant_id": offer["variant_id"],
        "variant_labels": json.loads(offer["variant_labels"]),
        "price_cents": offer["price_cents"],
        "price_basis": offer["price_basis"],
    }


def latest_offer(conn, store):
    return conn.execute(
        "SELECT * FROM offers WHERE store_domain = ? AND seller_name IS NOT NULL"
        " ORDER BY check_id DESC LIMIT 1",
        (store,),
    ).fetchone()


def check_stores(stores):
    """The rows for each store, by domain or link. The MCP tool and REST both return this."""
    conn = db.connect()
    try:
        return [store_view(conn, d, latest_offer(conn, d)) for d in map(domain, stores)]
    finally:
        conn.close()


@router.post("/checks")
def create_check(body: NewCheck):
    conn = db.connect()
    with conn:
        check_id = conn.execute(
            "INSERT INTO checks (created) VALUES (?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        ).lastrowid
        for store in dict.fromkeys(map(domain, body.stores)):
            known = latest_offer(conn, store)
            if known:
                conn.execute(
                    "INSERT INTO offers SELECT ?, store_domain, seller_name, storefront_url,"
                    " myshopify_domain, product_title, variant_id, variant_labels, price_cents,"
                    " price_basis, replies_in, pages_read FROM offers"
                    " WHERE check_id = ? AND store_domain = ?",
                    (check_id, known["check_id"], store),
                )
            else:
                conn.execute(
                    "INSERT INTO offers (check_id, store_domain) VALUES (?, ?)", (check_id, store)
                )
    conn.close()
    return {"id": check_id}


@router.get("/checks/{check_id}")
def get_check(check_id: int):
    conn = db.connect()
    try:
        check = conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
        if not check:
            raise HTTPException(404, "No such check")
        offers = conn.execute(
            "SELECT * FROM offers WHERE check_id = ? ORDER BY rowid", (check_id,)
        ).fetchall()
        return {
            "id": check["id"],
            "created": check["created"],
            "search_text": check["search_text"],
            "requested_size": check["requested_size"],
            "stores": [
                {**store_view(conn, offer["store_domain"], offer), "offer": offer_view(offer)}
                for offer in offers
            ],
        }
    finally:
        conn.close()


@router.get("/stores/{store}")
def get_store(store: str):
    return check_stores([store])[0]
