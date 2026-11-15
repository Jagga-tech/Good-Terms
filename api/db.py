import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
DB = ROOT / "goodterms.db"
PAGE_STATUS = {"confirms": "yes", "rejects": "no", "doesnt_say": "doesnt_say"}

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
    myshopify_domain TEXT,
    total TEXT,
    replies_in INTEGER NOT NULL DEFAULT 0,
    pages_read INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (check_id, store_domain)
);
CREATE TABLE findings (
    store_domain TEXT NOT NULL,
    condition TEXT NOT NULL REFERENCES conditions(id),
    page_status TEXT NOT NULL CHECK (page_status IN ('yes', 'no', 'doesnt_say', 'unreadable', 'pending')),
    sentence TEXT,
    page_summary TEXT,
    source_url TEXT,
    date_read TEXT,
    assistant_status TEXT NOT NULL CHECK (assistant_status IN ('yes', 'no', 'doesnt_say', 'unavailable', 'pending')),
    assistant_reply TEXT,
    reply_time TEXT,
    pages_disagree INTEGER NOT NULL DEFAULT 0,
    cut_short INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (store_domain, condition),
    CHECK (page_status != 'yes' OR sentence IS NOT NULL OR page_summary IS NOT NULL)
);
"""


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def reset():
    """Rebuild the database from the fixtures: the six original stores, both sources per row."""
    DB.unlink(missing_ok=True)
    rows = load("rows_six_stores.json")
    replies = load("ask_replies_2026-11-15.json")
    definitions = re.findall(
        r"^\d\. [^:]+: (.+)$", (FIXTURES / "status_definitions.md").read_text(), re.M
    )
    first_store = next(iter(replies["stores"].values()))
    questions = {reply["condition"]: reply["question"] for reply in first_store["replies"]}
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        for (condition, label), definition in zip(rows["conditions"].items(), definitions):
            conn.execute(
                "INSERT INTO conditions VALUES (?, ?, ?, ?)",
                (condition, label, questions[condition], definition),
            )
        conn.execute(
            "INSERT INTO checks (id, requested_size, created) VALUES (1, 'Queen', ?)",
            (rows["read_at"],),
        )
        for store, data in rows["stores"].items():
            asked = replies["stores"][store]
            conn.execute(
                "INSERT INTO offers VALUES (1, ?, ?, ?, ?, 1, 1)",
                (store, data["name"], urlparse(asked["endpoint"]).netloc, data["total"]),
            )
            by_condition = {reply["condition"]: reply for reply in asked["replies"]}
            for condition, finding in data["findings"].items():
                reply = by_condition[condition]
                conn.execute(
                    "INSERT INTO findings (store_domain, condition, page_status, page_summary,"
                    " source_url, date_read, assistant_status, assistant_reply, reply_time)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        store,
                        condition,
                        PAGE_STATUS[finding["status"]],
                        finding["finding"],
                        finding["url"],
                        rows["read_at"],
                        reply["reply_label"],
                        reply["reply"],
                        replies["asked_at"],
                    ),
                )
    conn.close()
