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
CREATE TABLE checks (
    id INTEGER PRIMARY KEY,
    search_text TEXT,
    requested_size TEXT,
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
    PRIMARY KEY (check_id, store_domain)
);
CREATE TABLE findings (
    store_domain TEXT NOT NULL,
    condition TEXT NOT NULL REFERENCES conditions(id),
    page_status TEXT NOT NULL CHECK (page_status IN ('yes', 'no', 'doesnt_say', 'unreadable', 'pending')),
    page_sentences TEXT NOT NULL DEFAULT '[]',
    date_read TEXT,
    assistant_status TEXT NOT NULL CHECK (assistant_status IN ('yes', 'no', 'doesnt_say', 'unavailable', 'pending')),
    assistant_reply TEXT,
    reply_time TEXT,
    pages_disagree INTEGER NOT NULL DEFAULT 0,
    cut_short INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (store_domain, condition),
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
    cases. The other two have their assistant's replies saved and their pages not read.
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
            "INSERT INTO checks VALUES (1, ?, 'Queen', ?)",
            (
                f"{run['query']}, under ${run['max_price_usd']}, shipping to {run['ships_to']}",
                run["searched_at"],
            ),
        )
        for myshopify, offer in run["offers"].items():
            name = offer["name"].strip()
            store = store_domain(offer["url"])
            saved = {case["condition"]: case for case in cases if case["store"] == name}
            conn.execute(
                "INSERT INTO offers VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, 'catalog price', 1, ?)",
                (
                    store,
                    name,
                    offer["url"],
                    myshopify,
                    offer["title"],
                    offer["variant"],
                    json.dumps(offer["labels"]),
                    offer["price"],
                    int(bool(saved)),
                ),
            )
            for condition in labels:
                case = saved.get(condition)
                reply = offer[REPLY_KEYS[condition]]
                if not case:
                    conn.execute(
                        "INSERT INTO findings (store_domain, condition, page_status,"
                        " assistant_status, assistant_reply, reply_time)"
                        " VALUES (?, ?, 'pending', 'pending', ?, ?)",
                        (store, condition, reply, run["searched_at"]),
                    )
                    continue
                status, disagree = page_status([s["label"] for s in case["page_sentences"]])
                sentences = [
                    {key: value for key, value in s.items() if key != "file"}
                    for s in case["page_sentences"]
                ]
                conn.execute(
                    "INSERT INTO findings (store_domain, condition, page_status, page_sentences,"
                    " date_read, assistant_status, assistant_reply, reply_time, pages_disagree)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        store,
                        condition,
                        case.get("pages", status),
                        json.dumps(sentences, ensure_ascii=False),
                        run["searched_at"],
                        case["assistant"],
                        reply,
                        run["searched_at"],
                        int(disagree),
                    ),
                )
    conn.close()
