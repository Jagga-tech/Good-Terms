import hashlib
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LABELS = {"confirms": "CONFIRMS", "rejects": "REJECTS", "doesnt_say": "DOESN'T SAY"}


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def log(tool, args):
    with open(os.path.join(HERE, "calls.log"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "tool": tool, "args": args}) + "\n")


def domain(value):
    v = value.strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = v.split("/")[0].split("?")[0]
    v = re.sub(r"^www\.", "", v)
    return v


def check_one(store, evidence, rules):
    d = domain(store)
    data = evidence["stores"].get(d)
    if data is None:
        return f"TERMS CHECK\nStore: {d}\nResult: NOT CHECKED\nThis store has not been read yet. Do not treat it as passing.\n"
    statuses = [data["findings"][c]["status"] for c in rules["deal_breakers"]]
    if "rejects" in statuses:
        result = "BLOCKED BY YOUR RULE"
        action = "Do not prepare a checkout at this store unless the buyer changes the rule."
    elif "doesnt_say" in statuses:
        result = "NEEDS YOUR DECISION"
        action = "Ask the buyer before preparing a checkout. The store does not say, which is not a yes."
    else:
        result = "MEETS YOUR RULES"
        action = "All saved deal-breakers are confirmed by the store's own pages."
    check_id = "TC-" + hashlib.sha256((d + evidence["read_at"]).encode()).hexdigest()[:6].upper()
    lines = [
        f"TERMS CHECK  |  ID {check_id}  |  read {evidence['read_at']}",
        f"Store: {data['name']} ({d})",
        f"Result: {result}",
    ]
    for i, c in enumerate(rules["deal_breakers"], 1):
        f = data["findings"][c]
        lines.append(f"{i}. {evidence['conditions'][c]}: {LABELS[f['status']]}. {f['finding']} Source: {f['url']}")
    lines.append(f"Full evidence: https://termscheck.example/r/{check_id}")
    lines.append(action)
    lines.append("Show the result line and the three numbered lines to the buyer without changing the status words.")
    return "\n".join(lines) + "\n"


def check(stores):
    evidence = load("evidence.json")
    rules = load("rules.json")
    log("terms_check", stores)
    return "\n".join(check_one(s, evidence, rules) for s in stores)


def prepare(store, url):
    evidence = load("evidence.json")
    d = domain(store)
    log("prepare_checkout", [store, url])
    total = evidence["stores"].get(d, {}).get("total", "unknown")
    return (
        f"SANDBOX CHECKOUT PREPARED\nStore: {d}\nItem: {url}\nTotal: ${total}\n"
        "Status: waiting for buyer approval. Nothing has been paid and no order exists.\n"
    )
