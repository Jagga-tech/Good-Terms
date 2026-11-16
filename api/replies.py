"""Every assistant reply, saved with the time it was asked.

A reply is reused for the same store, product and question for the rest of the day, so a
store's assistant is asked each question once a day at most. The file outlives restarts.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from api import db

FILE = Path(os.environ.get("GOODTERMS_STATE") or db.ROOT / "labels.db")
ask_new = True


def connect():
    conn = sqlite3.connect(FILE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS replies (store TEXT, variant TEXT, question TEXT, day TEXT,"
        " asked TEXT, reply TEXT, PRIMARY KEY (store, variant, question, day))"
    )
    return conn


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def lookup(store, variant, question):
    """Today's saved reply and the time it was asked, or None."""
    conn = connect()
    row = conn.execute(
        "SELECT reply, asked FROM replies WHERE store = ? AND variant = ? AND question = ? AND day = ?",
        (store, variant, question, now()[:10]),
    ).fetchone()
    conn.close()
    return row


def remember(store, variant, question, reply):
    asked = now()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO replies VALUES (?, ?, ?, ?, ?, ?)",
            (store, variant, question, asked[:10], asked, reply),
        )
    conn.close()
    return asked
