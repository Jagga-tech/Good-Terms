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
        " WHERE f.check_id = ? AND f.store_domain = ? ORDER BY c.rowid",
        (offer["rows_check"] if offer else None, store),
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
        replies_in = True
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
                "assistant_text": row["reply_note"] if replies_in and not row["assistant_reply"] else None,
                "status_shown": shown,
                "status_text": texts.status_text(shown, pages),
                "counts_toward_meets_all_3": shown == "yes",
                "contradiction": flag,
                "contradiction_text": texts.contradiction_text(disagree, sources_contradict),
            }
        )
    result = store_result(rows, pages_read)
    disagree = pages_read and any(row["pages_disagree"] for row in found)
    return {
        "card_note": texts.PAGES_DISAGREE if disagree else None,
        "domain": store,
        "name": offer["seller_name"] if offer else None,
        "storefront_url": offer["storefront_url"] if offer else None,
        "checked": True,
        "progress": {
            "replies_in": replies_in and bool(offer["replies_in"]),
            "pages_read": pages_read,
        },
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
        "SELECT * FROM offers WHERE store_domain = ? AND pages_read = 1"
        " AND rows_check IS NOT NULL ORDER BY rows_check DESC, check_id DESC LIMIT 1",
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
        " price_basis, replies_in, pages_read, rows_check, product_url, checkout_url,"
        " replies_at, endpoint, ask_offered, done_at FROM offers"
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
            view["actions"] = texts.actions(view["result"])
            view["decision"] = decision_view(conn, check_id, offer["store_domain"])
            view["review_allowed"] = may_review(view)
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
            "price_note": texts.PRICE_NOTE,
            "final_total_note": texts.FINAL_TOTAL,
            "price_gap": texts.price_gap(stores) if done else None,
            "stores": stores,
        }
    finally:
        conn.close()


def decision_view(conn, check_id, store):
    row = conn.execute(
        "SELECT choice, time FROM decisions WHERE check_id = ? AND store_domain = ? ORDER BY rowid DESC LIMIT 1",
        (check_id, store),
    ).fetchone()
    return {"choice": row["choice"], "time": row["time"], "text": texts.DECISIONS[row["choice"]]} if row else None


def may_review(view):
    """The before-checkout screen is for a store that meets all 3, or one the buyer chose to go on with."""
    chosen = (view.get("decision") or {}).get("choice")
    return view["result"] == "meets_all_3" or (
        chosen in ("continue", "buy_anyway", "checkout") and view["result"] in ("says_no", "not_answered_on_pages")
    )


class Decision(BaseModel):
    store: str
    choice: str


@router.post("/checks/{check_id}/decisions")
def decide(check_id: int, body: Decision):
    """Record the buyer's choice at one store. Only a choice its result offers is accepted."""
    view = next((s for s in get_check(check_id)["stores"] if s["domain"] == domain(body.store)), None)
    if not view:
        raise HTTPException(404, "No such store in this check")
    offered = {action["action"] for action in view["actions"]}
    allowed = body.choice in offered or (body.choice == "checkout" and view["review_allowed"])
    if not allowed:
        raise HTTPException(409, "That choice is not open at this store")
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO decisions VALUES (?, ?, ?, ?)",
            (check_id, view["domain"], body.choice, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        saved = decision_view(conn, check_id, view["domain"])
    conn.close()
    return saved


def checkout_link(check_id, store):
    """The catalog's checkout link for one store's offer. Refused until that store's check is done."""
    conn = db.connect()
    try:
        offer = conn.execute(
            "SELECT * FROM offers WHERE check_id = ? AND store_domain = ?", (check_id, domain(store))
        ).fetchone()
        check = conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
        if not offer:
            raise HTTPException(404, "No such store in this check")
        offers = conn.execute("SELECT * FROM offers WHERE check_id = ? ORDER BY rowid", (check_id,)).fetchall()
        index = [o["store_domain"] for o in offers].index(offer["store_domain"])
        done = replay_progress(check, index, offer)[1] if check["replay_started"] else bool(offer["pages_read"])
    finally:
        conn.close()
    link = offer["checkout_url"] or ""
    if not done:
        raise HTTPException(409, "This store's check has not finished, so its checkout link is not given yet.")
    view = next(s for s in get_check(check_id)["stores"] if s["domain"] == offer["store_domain"])
    if not view["review_allowed"]:
        raise HTTPException(409, "The checkout link is given after the buyer's choice at this store.")
    if not link.startswith("https://"):
        raise HTTPException(404, "The catalog gave no checkout link for this offer")
    return {"url": link}


@router.get("/checks/{check_id}/checkout/{store}")
def get_checkout_link(check_id: int, store: str):
    return checkout_link(check_id, store)


@router.get("/stores")
def list_stores():
    """The stores whose check has finished, for Merchant View's own lookup."""
    conn = db.connect()
    try:
        found = conn.execute(
            "SELECT store_domain, MAX(seller_name) AS seller_name FROM offers"
            " WHERE pages_read = 1 AND rows_check IS NOT NULL"
            " GROUP BY store_domain ORDER BY seller_name COLLATE NOCASE"
        ).fetchall()
        return [{"domain": row["store_domain"], "name": row["seller_name"]} for row in found]
    finally:
        conn.close()


@router.get("/stores/{store}")
def get_store(store: str):
    return check_stores([store])[0]
