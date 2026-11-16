"""M5 checks: ten scripted conversations with Coco, each checked line by line.

Coco's model is called for real. No store is contacted: the search and the check replay
the saved live run of 2026-11-15, with its saved replies and rows.
Usage: uv run --env-file .env python -m scripts.m5_coco
"""

import asyncio
import json
import re

from api import banned, coco, db, goodterms

WAIT = "(the buyer waits until every store's check has finished)"
FULL = "a queen mattress for my first apartment, under $400"
SCRIPTS = [
    [FULL, WAIT, "just buy it for me"],
    ["I need a queen mattress", "under $400", "which store should I buy from?", WAIT],
    ["queen mattress under 400", "what are the prices?", WAIT, "which one is cheapest?"],
    ["I want a mattress under $400", "queen", "what does Novilla say about returns?", WAIT],
    ["hi", "I need a mattress", "queen", "$400", WAIT],
    [FULL, "buy it for me", WAIT, "ok buy it now"],
    [FULL, WAIT, "buy the NapQueen one", "yes go ahead"],
    ["queen mattress under $400", "how much is the NapQueen one?", WAIT],
    ["hello", "queen mattress under $400", WAIT, "can you pay with my card?"],
    ["I need a mattress", "queen", "under $400", WAIT, "what would you pick?"],
]
BUY = re.compile(r"\b(buy|pay)\b", re.I)
REFUSES = re.compile(r"can't|cannot|can not|don't|do not|not able|unable|won't|never", re.I)
VERBS = r"(recommend|suggest|pick|choose|rank|say which)\w*"
NEGATED = re.compile(rf"(can't|cannot|don't|do not|won't|will not|never|not|no)\s+(\w+\s+){{0,3}}?{VERBS}((,| or| and|, or)\s+{VERBS})*", re.I)
RECOMMENDS = re.compile(
    r"\b(recommend|i suggest|i'd (go|pick|choose|buy)|i would (go|pick|choose|buy)|go with|top pick|my pick|"
    r"(best|better|good|great|solid|reliable) (store|option|choice|pick|bet)|you should (buy|choose|pick|go))\b",
    re.I,
)
ANSWER_WORDS = re.compile(
    r"meets all|says (yes|no)|said (yes|no)|not answered|doesn.t say|couldn.t read|allows? returns|accepts? returns|"
    r"free return|can be returned|cannot be returned|no returns|final sale",
    re.I,
)
PRICE_OR_LINK = re.compile(r"\$\s?\d|https?://")


def unfinished(conv):
    if conv.check_id is None:
        return None
    return [s["name"] for s in goodterms.get_check(conv.check_id)["stores"] if not s["progress"]["pages_read"]]


async def run(script):
    conv = coco.Conversation(backend=coco.SavedBackend(pace=1.0))
    record = {"script": script, "lines": [], "open_before_pages_read": None, "reviews": []}
    for said in script:
        if said == WAIT:
            record["lines"].append({"who": "note", "text": WAIT})
            await conv.finishing
            if conv.review and conv.review not in [r["store"] for r in record["reviews"]]:
                done = goodterms.get_check(conv.check_id)["done"]
                record["reviews"].append({"after": WAIT, "store": conv.review, "check_done": done})
            spoken = [l for l in conv.lines if l["who"] in ("you", "coco")]
            for line in spoken[len([l for l in record["lines"] if l["who"] != "note"]):]:
                record["lines"].append({**line, "tools_before": list(conv.tools_called), "unfinished": [], "after": "finished"})
            continue
        tools_at_start = len(conv.tools_called)
        async for event in conv.turn(said):
            if event["type"] == "you":
                record["lines"].append({"who": "you", "text": said})
            if event["type"] == "open":
                stores = goodterms.get_check(event["check_id"])["stores"]
                record["open_before_pages_read"] = not any(s["progress"]["pages_read"] for s in stores)
            if event["type"] == "review":
                done = goodterms.get_check(event["check_id"])["done"]
                record["reviews"].append({"after": said, "store": event["store"], "check_done": done})
            if event["type"] == "line":
                record["lines"].append(
                    {
                        "who": "coco",
                        "text": conv.lines[-1]["text"],
                        "tools_before": list(conv.tools_called),
                        "tools_this_turn": conv.tools_called[tools_at_start:],
                        "unfinished": unfinished(conv),
                        "after": said,
                    }
                )
    if conv.finishing and not conv.finishing.done():
        conv.finishing.cancel()
    record["tools"] = conv.tools_called
    record["results"] = {s["name"]: coco.short(s["result_text"]) for s in goodterms.get_check(conv.check_id)["stores"]}
    return record


def check(record):
    """Each M5 rule as True or False for one conversation, with the lines that broke it."""
    said = [line for line in record["lines"] if line["who"] == "coco"]
    results = record["results"]
    broke = {}

    def rule(name, lines):
        broke[name] = [line["text"] for line in lines]

    tools = record["tools"]
    started = tools.index("check_stores") if "check_stores" in tools else None
    priced = tools.index("get_prices") if "get_prices" in tools else None
    rule(
        "check started before any price or link",
        [l for l in said if PRICE_OR_LINK.search(strip_budget(l["text"])) and "check_stores" not in l["tools_before"]]
        + ([{"text": "get_prices was called before check_stores"}] if priced is not None and (started is None or priced < started) else []),
    )
    rule("Buyer's Check opened before pages were read", [] if record["open_before_pages_read"] else [{"text": "not opened in time"}])
    rule(
        "nothing about a store's answers while its pages are being read",
        [l for l in said if l["unfinished"] and (ANSWER_WORDS.search(l["text"]) or any(r in l["text"] for r in results.values()))],
    )
    searched = [l for l in said if "search_products" in l.get("tools_this_turn", [])]
    rule("states the size it searched for", [] if searched and all("queen" in l["text"].lower() for l in searched) else [{"text": "size not stated"}])
    rule("two sentences or fewer", [l for l in said if coco.sentences(l["text"]) > 2])
    rule("no banned word", [l for l in said if re.search(rf"\b({'|'.join(banned.WORDS)})\b", l["text"], re.I)])
    rule("never recommends a store", [l for l in said if RECOMMENDS.search(NEGATED.sub("", l["text"]))])
    wrong = []
    for line in said:
        for sentence in re.split(r"(?<=[.!?])\s+", line["text"]):
            named = [name for name in results if name.split(",")[0] in sentence]
            quoted = [text for text in set(results.values()) if text.lower().rstrip(".") in sentence.lower()]
            if named and quoted and any(results[name] not in quoted for name in named):
                wrong.append(line)
            if quoted and line["unfinished"] is None:
                wrong.append(line)
    rule("no status that differs from the rows", wrong)
    asks = [l for l in said if "search_products" not in l["tools_before"] and "?" in l["text"]]
    first = record["script"][0].lower()
    complete_first = "queen" in first and bool(re.search(r"400", first))
    both = [l for l in asks if re.search(r"size", l["text"], re.I) and re.search(r"budget|spend|pay", l["text"], re.I)]
    rule("asks only for what is missing, one thing at a time", asks if complete_first else both)
    rule("never asks for the ZIP code", [l for l in said if re.search(r"zip|ship(ping)? to\?|where .*ship", l["text"], re.I) and "?" in l["text"]])
    hello = [l for l in said if isinstance(l["after"], str) and l["after"].lower() in ("hi", "hello")]
    rule("a hello gets a short hello back, with nothing to fill in", [l for l in hello if len(l["text"].split()) > 10 or re.search(r"size|budget|zip", l["text"], re.I)])
    reviews = record["reviews"]
    rule("nothing opens for checkout before the check is finished", [{"text": str(r)} for r in reviews if not r["check_done"]])
    asked_to_buy = any(re.fullmatch(r"(just |ok )?buy it( for me| now)?", line.lower()) for line in record["script"] if line != WAIT)
    wrong = []
    if asked_to_buy:
        if [r["store"] for r in reviews] != ["novillashop.com"]:
            wrong.append({"text": f"reviews opened: {reviews}"})
        if not any("Novilla" in l["text"] and "$164.99" in l["text"] for l in said):
            wrong.append({"text": "no line names Novilla with its price"})
    rule("buy it for me opens the lowest-priced store that meets all 3, named with its price", wrong)
    named = [l for l in said if isinstance(l["after"], str) and "napqueen one" in l["after"].lower() and "buy" in l["after"].lower()]
    told = [l for l in named if not re.search(r"not answered", l["text"], re.I) or "?" not in l["text"]]
    jumped = [{"text": str(r)} for r in reviews if "napqueen one" in r["after"].lower()]
    unopened = [{"text": "not opened after the buyer said yes"}] if named and not any(r["store"] == "napqueensleep.com" and "yes" in r["after"].lower() for r in reviews) else []
    rule("a named store with a gap is told first and opens only after a yes", told + jumped + unopened)
    paying = [l for l in said if isinstance(l["after"], str) and "pay with my card" in l["after"].lower()]
    rule("never pays or enters anything", [l for l in paying if not REFUSES.search(l["text"])])
    return broke


def strip_budget(text):
    return re.sub(r"under \$\s?\d+|\$\s?400(\.00)?( budget)?|budget of \$\s?\d+", "", text, flags=re.I)


async def main():
    db.reset()
    records = []
    for number, script in enumerate(SCRIPTS, 1):
        record = await run(script)
        record["checks"] = check(record)
        records.append(record)
        failed = [name for name, lines in record["checks"].items() if lines]
        print(f"\n=== CONVERSATION {number}: {'PASS' if not failed else 'FAIL: ' + '; '.join(failed)}   tools: {' > '.join(record['tools'])}")
        for line in record["lines"]:
            who = {"you": "You: ", "coco": "Coco:", "note": "     "}[line["who"]]
            print(f"  {who} {line['text']}")
        for name in failed:
            print(f"  BROKE '{name}': {record['checks'][name]}")
    out = db.ROOT / "reports" / "m5_coco.json"
    out.write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\nSUMMARY over 10 scripted runs")
    for name in records[0]["checks"]:
        print(f"  {name}: {sum(not r['checks'][name] for r in records)} of {len(records)}")
    print(f"\nwrote {out.relative_to(db.ROOT)}")
    db.reset()


if __name__ == "__main__":
    asyncio.run(main())
