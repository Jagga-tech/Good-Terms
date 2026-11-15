"""M3 live check: a real search, real Ask calls, real page reads and model labels, timed.

Each run does a live catalog search for the demo request, checks the first six stores, and
reports when the assistants' replies were all in and when every store was finished.
Usage: uv run --env-file .env python -m scripts.m3_live [runs]
"""

import asyncio
import json
import sys
import time

import httpx

from api import db, goodterms
from api.check import run_check, start_check
from api.labeler import Labeler
from api.search import search

REQUEST = {"query": "queen mattress", "size": "Queen", "budget_cents": 40000, "zip_code": "94541"}
REPLIES_TARGET = 15.0
DONE_TARGET = 60.0


async def one_run(labeler):
    began = time.time()
    async with httpx.AsyncClient() as client:
        offers = await search(client, **REQUEST)
    search_seconds = time.time() - began
    check_id = start_check(offers, "queen mattress, under $400, shipping to 94541", "Queen", 40000)
    running = asyncio.create_task(run_check(check_id, labeler))
    early_yes = []
    while not running.done():
        for store in goodterms.get_check(check_id)["stores"]:
            if not store["progress"]["pages_read"]:
                early_yes += [store["name"] for row in store["rows"] if row["status_shown"] == "yes"]
        await asyncio.sleep(0.25)
    await running
    conn = db.connect()
    started = conn.execute("SELECT started_at FROM checks WHERE id = ?", (check_id,)).fetchone()[0]
    times = {
        row["store_domain"]: (row["replies_at"], row["done_at"], row["seller_name"])
        for row in conn.execute("SELECT * FROM offers WHERE check_id = ?", (check_id,))
    }
    pages = dict(
        conn.execute(
            "SELECT store_domain, SUM(status = '200') FROM pages WHERE check_id = ? GROUP BY store_domain", (check_id,)
        ).fetchall()
    )
    conn.close()
    view = goodterms.get_check(check_id)
    stores = []
    for store in view["stores"]:
        replies_at, done_at, _ = times[store["domain"]]
        stores.append(
            {
                "name": store["name"],
                "domain": store["domain"],
                "price": store["offer"]["price_text"],
                "variant": store["offer"]["variant_labels"],
                "replies_seconds": round(replies_at - started, 1) if replies_at else None,
                "done_seconds": round(done_at - started, 1),
                "pages_read": pages.get(store["domain"], 0),
                "result": store["result"],
                "result_text": store["result_text"],
                "rows": store["rows"],
            }
        )
    replies = [s["replies_seconds"] for s in stores if s["replies_seconds"] is not None]
    return {
        "check_id": check_id,
        "search_seconds": round(search_seconds, 1),
        "stores_checked": len(stores),
        "replies_seconds": max(replies) if replies else None,
        "done_seconds": max(s["done_seconds"] for s in stores),
        "early_yes": early_yes,
        "meets_all_3": [s["name"] for s in stores if s["result"] == "meets_all_3"],
        "price_gap": (view["price_gap"] or {}).get("text"),
        "stores": stores,
    }


async def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    db.reset()
    labeler = Labeler()
    results = []
    for number in range(1, runs + 1):
        result = await one_run(labeler)
        results.append(result)
        print(
            f"\nRUN {number}: search {result['search_seconds']}s, {result['stores_checked']} stores,"
            f" replies in {result['replies_seconds']}s, all done {result['done_seconds']}s,"
            f" yes shown before pages read: {len(result['early_yes'])}"
        )
        for store in result["stores"]:
            statuses = ", ".join(row["status_shown"] for row in store["rows"])
            print(
                f"  {store['name'][:22]:22} {store['price']:>8}  replies {store['replies_seconds']}s  done {store['done_seconds']}s"
                f"  pages {store['pages_read']}  {store['result']}  [{statuses}]"
            )
        print(f"  meets all 3: {result['meets_all_3'] or 'none'}")
        print(f"  {result['price_gap']}")
        if number < runs:
            await asyncio.sleep(20)
    out = db.ROOT / "reports" / "m3_live.json"
    out.write_text(json.dumps({"model": labeler.model, "effort": labeler.effort, "runs": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    fast_replies = sum(r["replies_seconds"] is not None and r["replies_seconds"] <= REPLIES_TARGET for r in results)
    fast_done = sum(r["done_seconds"] < DONE_TARGET for r in results)
    print(f"\nSUMMARY over {runs} runs (model {labeler.model}, effort {labeler.effort})")
    print(f"  replies within {REPLIES_TARGET:.0f}s: {fast_replies} of {runs}; slowest {max(r['replies_seconds'] or 0 for r in results)}s")
    print(f"  all stores done under {DONE_TARGET:.0f}s: {fast_done} of {runs}; slowest {max(r['done_seconds'] for r in results)}s")
    print(f"  yes shown before pages read: {sum(len(r['early_yes']) for r in results)}")
    print(f"  demo rule (one store meets all 3): held in {sum(bool(r['meets_all_3']) for r in results)} of {runs} runs")
    last = results[-1]
    print("\nEVERY YES ROW in the last run, with its sentence:")
    for store in last["stores"]:
        for row in store["rows"]:
            if row["status_shown"] == "yes":
                for sentence in row["page_sentences"]:
                    heading = f" (under the heading \"{sentence['heading']}\")" if sentence.get("heading") else ""
                    print(f"  {store['name']} / {row['condition_label']}{heading}: \"{sentence['sentence']}\" <{sentence['url']}>")
    print(f"\nwrote {out.relative_to(db.ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
