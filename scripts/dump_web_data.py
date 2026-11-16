"""Write the API's own answers to web/test-data.json, for the screen tests to draw.

Holds the finished saved check, three moments of its replay, each store as Merchant View
gets it, and two variants of the saved rows for states no saved store has.
Usage: uv run python -m scripts.dump_web_data
"""

import json
import time

from fastapi.testclient import TestClient

from api import db, goodterms, texts
from api.main import app

OUT = db.ROOT / "web" / "test-data.json"


def variant(client, sql):
    conn = db.connect()
    with conn:
        conn.execute(sql)
    conn.close()
    check = client.get("/api/checks/1").json()
    db.reset()
    return check


def main():
    clock = {"t": time.time()}
    goodterms.now = lambda: clock["t"]
    data = {}
    with TestClient(app) as client:
        data["final"] = client.get("/api/checks/1").json()
        data["latest"] = client.get("/api/checks/2").json()
        for store, choice in (("napqueensleep.com", "continue"), ("comformattress.com", "buy_anyway"), ("dwellinhaus.com", "skip")):
            client.post("/api/checks/2/decisions", json={"store": store, "choice": choice})
        data["decided"] = client.get("/api/checks/2").json()
        data["checkout_links"] = {
            store: client.get(f"/api/checks/2/checkout/{store}").json()["url"]
            for store in ("novillashop.com", "napqueensleep.com")
        }
        db.reset()
        replay = client.post("/api/checks/1/replay").json()["id"]
        for name, seconds in (("replay_start", 0.5), ("replay_replies", 4), ("replay_partial", 8)):
            clock["t"] += seconds
            data[name] = client.get(f"/api/checks/{replay}").json()
        data["stores"] = client.get("/api/stores").json()
        data["merchant"] = {
            store["domain"]: client.get(f"/api/stores/{store['domain']}").json()
            for store in data["stores"]
        }
        data["could_not_read"] = variant(
            client,
            "UPDATE findings SET page_status = 'unreadable', page_sentences = '[]'"
            " WHERE store_domain = 'sweetnight.com'",
        )
        data["two_yes_one_assistant_only"] = variant(
            client,
            "UPDATE findings SET page_status = 'doesnt_say', page_sentences = '[]'"
            " WHERE store_domain = 'sweetnight.com' AND condition = 'sale_item_returns'",
        )
        data["ask_blocked"] = variant(
            client,
            "UPDATE findings SET assistant_reply = NULL, reply_time = NULL, assistant_status = 'unavailable',"
            f" reply_note = '{texts.ask_blocked(1265).replace(chr(39), chr(39) * 2)}'"
            " WHERE store_domain = 'sweetnight.com'",
        )
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(db.ROOT)}")


if __name__ == "__main__":
    main()
