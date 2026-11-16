"""Pre-demo check: is everything ready to record, right now, live?

Checks the agent profile, runs the demo request live (twice by default), and reports both
timings and whether the demo rule holds, counting only yeses found on stores' pages.
Replies saved today are reused. Unless --ask is given it sends no new question to any
store's assistant, because Ask without credentials has a small limit; the search is not
pinned, so a store with no saved reply then shows as not asked.
Usage: uv run --env-file .env python -m scripts.predemo [runs] [--ask]
"""

import asyncio
import os
import sys

import httpx

from api import db, replies
from api.labeler import Labeler
from api.search import search
from scripts import smoke
from scripts.m3_live import DONE_TARGET, REPLIES_TARGET, REQUEST, one_run


def line(ok, text):
    print(f"{'PASS' if ok else 'FAIL'}  {text}")
    return ok


async def new_questions():
    """How many questions a live run would send to stores' assistants right now."""
    async with httpx.AsyncClient() as client:
        offers = await search(client, **REQUEST)
    conn = db.connect()
    questions = [row["question"] for row in conn.execute("SELECT question FROM conditions ORDER BY rowid")]
    conn.close()
    missing = sum(
        replies.lookup(offer["store_domain"], offer["variant_id"], question) is None
        for offer in offers
        for question in questions
    )
    return len(offers), missing


async def main():
    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    runs = int(arguments[0]) if arguments else 2
    ok = True
    try:
        smoke.check_profile()
    except SystemExit as problem:
        ok = line(False, f"agent profile: {problem}")
    ok &= line(bool(os.environ.get("ANTHROPIC_API_KEY")), "model key is set in the environment")
    db.reset()
    stores, missing = await new_questions()
    ok &= line(stores >= 4, f"live search returned {stores} stores with a Queen in stock under $400")
    print(f"      a live run now would ask stores' assistants {missing} new questions; {stores * 3 - missing} are saved from today")
    replies.ask_new = "--ask" in sys.argv
    if not replies.ask_new:
        print("      new questions are switched off for this run; a store with no saved reply shows as not asked. Add --ask to allow them.")
    if not ok:
        raise SystemExit(1)
    labeler = Labeler()
    results = []
    for number in range(1, runs + 1):
        result = await one_run(labeler)
        results.append(result)
        print(
            f"\nRUN {number}: search {result['search_seconds']}s, replies in {result['replies_seconds']}s,"
            f" all {result['stores_checked']} stores done {result['done_seconds']}s,"
            f" replies received {result['replies_received']} of {result['replies_asked']}"
        )
        for store in result["stores"]:
            statuses = ", ".join(row["status_shown"] for row in store["rows"])
            print(f"  {store['name'][:22]:22} {store['price']:>8}  done {store['done_seconds']}s  {store['result']}  [{statuses}]")
        print(f"  {result['price_gap']}")
        if number < runs:
            await asyncio.sleep(20)
    print()
    for number, result in enumerate(results, 1):
        replies_in = result["replies_seconds"]
        ok &= line(replies_in is not None and replies_in <= REPLIES_TARGET, f"run {number}: assistants' replies in within {REPLIES_TARGET:.0f}s ({replies_in}s)")
        ok &= line(result["done_seconds"] < DONE_TARGET, f"run {number}: all stores done under {DONE_TARGET:.0f}s ({result['done_seconds']}s)")
        ok &= line(result["replies_received"] == result["replies_asked"], f"run {number}: every assistant reply received ({result['replies_received']} of {result['replies_asked']})")
        ok &= line(not result["early_yes"], f"run {number}: no yes shown before a store's pages were read")
        ok &= line(bool(result["meets_all_3"]), f"run {number}: demo rule, one store says yes to all 3 on its pages ({', '.join(result['meets_all_3']) or 'none'})")
    same = len({tuple(tuple(r["status_shown"] for r in s["rows"]) for s in sorted(result["stores"], key=lambda s: s["name"])) for result in results}) == 1
    ok &= line(same, "the same stores gave the same rows in every run")
    print("\nREADY TO RECORD" if ok else "\nNOT READY")
    db.reset()
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
