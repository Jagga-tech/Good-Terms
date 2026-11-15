import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from api.combine import page_status

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
DB = ROOT / "goodterms.db"
REPLY_KEYS = {"opened_returns": "opened", "free_return_shipping": "shipping", "sale_item_returns": "sale"}

SCHEMA = """
CREATE TABLE conditions (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    question TEXT NOT NULL,
    definition TEXT NOT NULL
);
CREATE TABLE buyers (
    id INTEGER PRIMARY KEY,
    conditions TEXT,
    zip TEXT
);
CREATE TABLE checks (
    id INTEGER PRIMARY KEY,
    search_text TEXT,
    requested_size TEXT,
    budget_cents INTEGER,
    saved_on TEXT,
    replay_started REAL,
    replay_pace REAL,
    started_at REAL,
    created TEXT NOT NULL
);
CREATE TABLE offers (
    check_id INTEGER NOT NULL REFERENCES checks(id),
    store_domain TEXT NOT NULL,
    seller_name TEXT,
    storefront_url TEXT,
    myshopify_domain TEXT,
    product_title TEXT,
    variant_id TEXT,
    variant_labels TEXT,
    price_cents INTEGER,
    price_basis TEXT,
    replies_in INTEGER NOT NULL DEFAULT 0,
    pages_read INTEGER NOT NULL DEFAULT 0,
    rows_check INTEGER,
    product_url TEXT,
    checkout_url TEXT,
    replies_at REAL,
    endpoint TEXT,
    ask_offered INTEGER,
    done_at REAL,
    PRIMARY KEY (check_id, store_domain)
);
CREATE TABLE pages (
    check_id INTEGER NOT NULL REFERENCES checks(id),
    store_domain TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL,
    via TEXT,
    fetched TEXT,
    text TEXT
);
CREATE TABLE findings (
    check_id INTEGER NOT NULL REFERENCES checks(id),
    store_domain TEXT NOT NULL,
    condition TEXT NOT NULL REFERENCES conditions(id),
    page_status TEXT NOT NULL CHECK (page_status IN ('yes', 'no', 'doesnt_say', 'unreadable', 'pending')),
    page_sentences TEXT NOT NULL DEFAULT '[]',
    date_read TEXT,
    assistant_status TEXT NOT NULL CHECK (assistant_status IN ('yes', 'no', 'doesnt_say', 'unavailable', 'pending')),
    assistant_reply TEXT,
    reply_time TEXT,
    reply_note TEXT,
    pages_disagree INTEGER NOT NULL DEFAULT 0,
    read_note TEXT,
    PRIMARY KEY (check_id, store_domain, condition),
    CHECK (page_status != 'yes' OR json_array_length(page_sentences) > 0)
);
"""


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def store_domain(url):
    return urlparse(url).netloc.removeprefix("www.")


def reset():
    """Rebuild the database from the fixtures: the six stores of the live run under $400.

    Four stores have their pages read, with the exact sentences from the saved combining
    cases. The other two were closed with their assistant's replies and a note that their
    pages were not read.
    """
    DB.unlink(missing_ok=True)
    run = load("live_run_under_400_2026-11-15.json")
    cases = load("combining_cases.json")["saved_cases_live_run_2026-11-15"]
    labels = load("rows_six_stores.json")["conditions"]
    asked = load("ask_replies_2026-11-15.json")["stores"]
    questions = {r["condition"]: r["question"] for r in next(iter(asked.values()))["replies"]}
    definitions = re.findall(
        r"^\d\. [^:]+: (.+)$", (FIXTURES / "status_definitions.md").read_text(), re.M
    )
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        for (condition, label), definition in zip(labels.items(), definitions):
            conn.execute(
                "INSERT INTO conditions VALUES (?, ?, ?, ?)",
                (condition, label, questions[condition], definition),
            )
        conn.execute(
            "INSERT INTO checks (id, search_text, requested_size, budget_cents, saved_on, created)"
            " VALUES (1, ?, 'Queen', ?, ?, ?)",
            (
                f"{run['query']}, under ${run['max_price_usd']}, shipping to {run['ships_to']}",
                run["max_price_usd"] * 100,
                run["searched_at"],
                run["searched_at"],
            ),
        )
        for myshopify, offer in run["offers"].items():
            name = offer["name"].strip()
            store = store_domain(offer["url"])
            saved = {case["condition"]: case for case in cases if case["store"] == name}
            conn.execute(
                "INSERT INTO offers (check_id, store_domain, seller_name, storefront_url,"
                " myshopify_domain, product_title, variant_id, variant_labels, price_cents,"
                " price_basis, replies_in, pages_read, rows_check)"
                " VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, 'catalog price', 1, 1, 1)",
                (
                    store,
                    name,
                    offer["url"],
                    myshopify,
                    offer["title"],
                    offer["variant"],
                    json.dumps(offer["labels"]),
                    offer["price"],
                ),
            )
            for condition in labels:
                case = saved[condition]
                reply = offer[REPLY_KEYS[condition]]
                status, disagree = page_status([s["label"] for s in case["page_sentences"]])
                sentences = [
                    {key: value for key, value in s.items() if key != "file"}
                    for s in case["page_sentences"]
                ]
                conn.execute(
                    "INSERT INTO findings (check_id, store_domain, condition, page_status,"
                    " page_sentences, date_read, assistant_status, assistant_reply, reply_time,"
                    " pages_disagree, read_note) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        store,
                        condition,
                        case.get("pages", status),
                        json.dumps(sentences, ensure_ascii=False),
                        None if case.get("pages_not_read") else run["searched_at"],
                        case["assistant"],
                        reply,
                        run["searched_at"],
                        int(disagree),
                        case.get("read_note"),
                    ),
                )
        conn.execute("INSERT INTO buyers (id) VALUES (1)")
        seed_saved_check(conn)
    conn.close()


def seed_saved_check(conn):
    """Check 2: one whole live check of 2026-11-15, saved after it finished."""
    saved = load("live_check_2026-11-15.json")
    conn.execute(
        "INSERT INTO checks (id, search_text, requested_size, budget_cents, saved_on, created)"
        " VALUES (2, ?, ?, ?, ?, ?)",
        (saved["search_text"], saved["requested_size"], saved["budget_cents"], saved["saved_on"], saved["saved_on"]),
    )
    for store in saved["stores"]:
        offer = store["offer"]
        conn.execute(
            "INSERT INTO offers (check_id, store_domain, seller_name, storefront_url, myshopify_domain,"
            " product_title, variant_id, variant_labels, price_cents, price_basis, replies_in, pages_read,"
            " rows_check, product_url, checkout_url, endpoint, ask_offered)"
            " VALUES (2, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 2, ?, ?, ?, ?)",
            (
                store["domain"],
                store["name"],
                offer["storefront_url"],
                offer["myshopify_domain"],
                offer["product_title"],
                offer["variant_id"],
                json.dumps(offer["variant_labels"]),
                offer["price_cents"],
                offer["price_basis"],
                offer["product_url"],
                offer["checkout_url"],
                offer["endpoint"],
                offer["ask_offered"],
            ),
        )
        for row in store["rows"]:
            disagree = len({s["label"] for s in row["page_sentences"]}) > 1
            conn.execute(
                "INSERT INTO findings (check_id, store_domain, condition, page_status, page_sentences,"
                " date_read, assistant_status, assistant_reply, reply_time, reply_note, pages_disagree,"
                " read_note) VALUES (2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    store["domain"],
                    row["condition"],
                    row["page_status"],
                    json.dumps(row["page_sentences"], ensure_ascii=False),
                    row["date_read"],
                    row["assistant_status"],
                    row["assistant_reply"],
                    row["reply_time"],
                    row["assistant_text"],
                    int(disagree),
                    row["read_note"],
                ),
            )
