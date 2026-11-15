import json
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import db, texts
from api.combine import combine, store_result

router = APIRouter(prefix="/api")
RESULT_ORDER = {"meets_all_3": 0, "says_no": 2}


class NewCheck(BaseModel):
    stores: list[str]


def now():
    return time.time()


def domain(value):
    value = re.sub(r"^https?://", "", value.strip().lower())
    return re.sub(r"^www\.", "", value.split("/")[0].split("?")[0])


def store_view(conn, store, offer, replies_in=None, pages_read=None):
    """One store as every screen and tool sees it: progress, result and the rows."""
    found = conn.execute(
        "SELECT f.*, c.label, c.question FROM findings f JOIN conditions c ON c.id = f.condition"
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
            "result_text": texts.result_text("not_checked", []),
            "rows": [],
        }
    if replies_in is None:
        replies_in = bool(offer and offer["replies_in"])
    if pages_read is None:
        pages_read = bool(offer and offer["pages_read"])
    rows = []
    for row in found:
        pages = row["page_status"] if pages_read else "pending"
        assistant = row["assistant_status"] if replies_in else "pending"
        disagree = bool(row["pages_disagree"]) and pages_read
        shown, flag = combine(pages, assistant, disagree)
        sentences = json.loads(row["page_sentences"]) if pages_read else []
        read_note = row["read_note"] if pages_read else None
        sources_contradict = {pages, assistant} == {"yes", "no"}
        rows.append(
            {
                "condition": row["condition"],
                "condition_label": row["label"],
                "question": row["question"],
                "page_status": pages,
                "page_sentences": sentences,
                "pages_text": texts.pages_text(pages, bool(sentences), read_note),
                "date_read": row["date_read"] if pages_read else None,
                "read_note": read_note,
                "assistant_status": assistant,
                "assistant_reply": row["assistant_reply"] if replies_in else None,
                "reply_time": row["reply_time"] if replies_in else None,
                "status_shown": shown,
                "status_text": texts.status_text(shown, pages),
                "counts_toward_meets_all_3": shown == "yes",
                "contradiction": flag,
                "contradiction_text": texts.contradiction_text(disagree, sources_contradict),
            }
        )
    result = store_result(rows, pages_read)
    return {
        "domain": store,
        "name": offer["seller_name"] if offer else None,
        "storefront_url": offer["storefront_url"] if offer else None,
        "checked": True,
        "progress": {"replies_in": replies_in, "pages_read": pages_read},
        "result": result,
        "result_text": texts.result_text(result, rows),
        "rows": rows,
    }


def offer_view(offer, budget_cents):
    if offer["price_cents"] is None:
        return None
    return {
        "product_title": offer["product_title"],
        "variant_id": offer["variant_id"],
        "variant_labels": json.loads(offer["variant_labels"]),
        "price_cents": offer["price_cents"],
        "price_text": texts.dollars(offer["price_cents"]),
        "price_basis": offer["price_basis"],
        "within_budget": budget_cents is None or offer["price_cents"] <= budget_cents,
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


def new_check(conn, **columns):
    columns["created"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    return conn.execute(
        f"INSERT INTO checks ({names}) VALUES ({marks})", tuple(columns.values())
    ).lastrowid


def copy_offer(conn, check_id, source_check, store):
    conn.execute(
        "INSERT INTO offers SELECT ?, store_domain, seller_name, storefront_url,"
        " myshopify_domain, product_title, variant_id, variant_labels, price_cents,"
        " price_basis, replies_in, pages_read FROM offers"
        " WHERE check_id = ? AND store_domain = ?",
        (check_id, source_check, store),
    )


@router.post("/checks")
def create_check(body: NewCheck):
    conn = db.connect()
    with conn:
        check_id = new_check(conn)
        for store in dict.fromkeys(map(domain, body.stores)):
            known = latest_offer(conn, store)
            if known:
                copy_offer(conn, check_id, known["check_id"], store)
            else:
                conn.execute(
                    "INSERT INTO offers (check_id, store_domain) VALUES (?, ?)", (check_id, store)
                )
    conn.close()
    return {"id": check_id}


@router.post("/checks/{check_id}/replay")
def replay_check(check_id: int, pace: float = 1.0):
    """A new check that replays a saved one from the start: replies first, then pages."""
    conn = db.connect()
    with conn:
        source = conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
        if not source:
            raise HTTPException(404, "No such check")
        new_id = new_check(
            conn,
            search_text=source["search_text"],
            requested_size=source["requested_size"],
            budget_cents=source["budget_cents"],
            saved_on=source["saved_on"],
            replay_started=now(),
            replay_pace=max(pace, 0.01),
        )
        for offer in conn.execute(
            "SELECT store_domain FROM offers WHERE check_id = ? ORDER BY rowid", (check_id,)
        ).fetchall():
            copy_offer(conn, new_id, check_id, offer["store_domain"])
    conn.close()
    return {"id": new_id}


def replay_progress(check, index, offer):
    """Where one store stands in a replay: its replies arrive first, its pages finish later."""
    elapsed = (now() - check["replay_started"]) / check["replay_pace"]
    return (
        bool(offer["replies_in"]) and elapsed >= 1 + 0.5 * index,
        bool(offer["pages_read"]) and elapsed >= 5 + 2 * index,
    )


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
        stores = []
        for index, offer in enumerate(offers):
            progress = replay_progress(check, index, offer) if check["replay_started"] else ()
            view = store_view(conn, offer["store_domain"], offer, *progress)
            view["offer"] = offer_view(offer, check["budget_cents"])
            stores.append(view)
        done = all(not s["checked"] or s["progress"]["pages_read"] for s in stores)
        if done:
            stores.sort(
                key=lambda s: (
                    RESULT_ORDER.get(s["result"], 1),
                    s["offer"]["price_cents"] if s["offer"] else 0,
                )
            )
        return {
            "id": check["id"],
            "created": check["created"],
            "saved_on": check["saved_on"],
            "search_text": check["search_text"],
            "requested_size": check["requested_size"],
            "budget_cents": check["budget_cents"],
            "conditions": [
                row["label"] for row in conn.execute("SELECT label FROM conditions ORDER BY rowid")
            ],
            "done": done,
            "price_gap": texts.price_gap(stores) if done else None,
            "stores": stores,
        }
    finally:
        conn.close()


@router.get("/stores")
def list_stores():
    """The stores whose check has finished, for Merchant View's own lookup."""
    conn = db.connect()
    try:
        found = conn.execute(
            "SELECT store_domain, seller_name FROM offers WHERE check_id = 1 AND pages_read = 1"
            " ORDER BY seller_name COLLATE NOCASE"
        ).fetchall()
        return [{"domain": row["store_domain"], "name": row["seller_name"]} for row in found]
    finally:
        conn.close()


@router.get("/stores/{store}")
def get_store(store: str):
    return check_stores([store])[0]
