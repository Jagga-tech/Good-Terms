"""M3 checks on frozen page text and saved replies. Calls the model; never calls a store.

Scores the labeler and the pipeline against the answer key and writes reports/m3_frozen.json.
Usage: uv run --env-file .env python -m scripts.m3_frozen
"""

import asyncio
import json

from api import db, goodterms
from api.check import StoreCheck, conditions, squash, start_check
from api.frozen import FrozenReader, folder_for
from api.labeler import Labeler

BUNDLE_FOLDERS = {
    "novillashop.com": "pages_novilla",
    "napqueensleep.com": "pages_napqueen",
    "sweetnight.com": "pages_sweetnight",
    "bedstory.com": "pages_bedstory",
}
CONDITIONS = ["opened_returns", "free_return_shipping", "sale_item_returns"]
KNOWN_DIFFERENCES = {
    ("bonanest.com", "opened_returns"): "Key says doesn't say; the labeler says no, from the 'unworn or unused' sentence. Listed, key unchanged.",
}
RUN = db.load("live_run_under_400_2026-11-15.json")
CASES = db.load("combining_cases.json")["saved_cases_live_run_2026-11-15"]
ASKED = db.load("ask_replies_2026-11-15.json")["stores"]
NOT_EXCLUDED = db.load("not_excluded_cases.json")
LIVE = {db.store_domain(o["url"]): o for o in RUN["offers"].values()}


def page_key():
    """The 29 scoreable page labels: six original stores and four of the five extra ones."""
    key = {}
    for store, data in db.load("rows_six_stores.json")["stores"].items():
        for condition, finding in data["findings"].items():
            key[(store, condition)] = {"confirms": "yes", "rejects": "no"}.get(finding["status"], "doesnt_say")
    extra = db.load("labels_five_extra_stores.json")
    for store, data in extra["stores"].items():
        if "Do not re-read" in data.get("note", ""):
            continue
        for condition, label in zip(extra["conditions"], data["labels"]):
            if label in ("yes", "no", "doesnt_say"):
                key[(store, condition)] = label
    return key


def folder(store):
    return db.FIXTURES / BUNDLE_FOLDERS[store] if store in BUNDLE_FOLDERS else folder_for(store)


def saved_replies(store):
    if store in LIVE:
        return {c: LIVE[store][db.REPLY_KEYS[c]] for c in CONDITIONS}
    if store in ASKED:
        return {r["condition"]: r["reply"] for r in ASKED[store]["replies"]}
    return {}


async def run_stores(stores, labeler):
    offers = []
    readers = {}
    for store in stores:
        readers[store] = FrozenReader(folder(store))
        product = readers[store].report.get("product") or {}
        offers.append(
            {
                "store_domain": store,
                "name": store,
                "storefront_url": f"https://{store}",
                "myshopify_domain": "",
                "product_title": LIVE.get(store, {}).get("title") or product.get("title") or "Queen mattress",
                "product_url": readers[store].product_url,
                "variant_id": "",
                "variant_labels": LIVE.get(store, {}).get("labels") or [product.get("variant") or "Queen"],
                "price_cents": 0,
            }
        )
    check_id = start_check(offers)
    conn = db.connect()
    rows = [dict(row) for row in conn.execute("SELECT * FROM offers WHERE check_id = ?", (check_id,))]
    conds = conditions(conn)
    conn.close()
    await asyncio.gather(
        *(
            StoreCheck(check_id, row, conds, None, labeler, readers[row["store_domain"]], saved_replies(row["store_domain"])).run(300)
            for row in rows
        )
    )
    view = goodterms.get_check(check_id)
    return {store["domain"]: store for store in view["stores"]}, readers


async def label_replies(labeler, conds, items):
    """items: (name, condition, reply, expected). One call per item so each is judged alone."""

    async def one(name, condition, reply, expected):
        got = await labeler.replies([c for c in conds if c["id"] == condition], "A queen mattress", {condition: reply})
        return {"case": name, "condition": condition, "expected": expected, "got": got[condition], "match": got[condition] == expected, "reply": reply}

    return await asyncio.gather(*(one(*item) for item in items))


async def label_sentences(labeler, conds, items):
    async def one(entry):
        cond = [c for c in conds if c["id"] == entry["condition"]]
        found = await labeler.pages(cond, "A queen mattress", [(entry["url"], entry["sentence"])])
        statuses = [f["status"] for f in found[entry["condition"]] if squash(f["sentence"]) == squash(entry["sentence"])]
        got = statuses[0] if statuses and statuses[0] != "unclear" else "doesnt_say"
        return {"case": entry["store"], "condition": entry["condition"], "expected": entry["expected"], "got": got, "match": got == entry["expected"], "sentence": entry["sentence"]}

    return await asyncio.gather(*(one(entry) for entry in items))


async def main():
    db.reset()
    labeler = Labeler()
    conn = db.connect()
    conds = conditions(conn)
    conn.close()
    key = page_key()
    key_stores = sorted({store for store, _ in key})
    frozen = [s for s in dict.fromkeys(key_stores + list(BUNDLE_FOLDERS)) if (folder(s) / "report.json").exists()]
    not_frozen = [s for s in key_stores if s not in frozen]
    stores, readers = await run_stores(frozen, labeler)

    page_labels = []
    for (store, condition), expected in sorted(key.items()):
        if store in not_frozen:
            page_labels.append({"store": store, "condition": condition, "key": expected, "got": None, "match": False, "note": "store not frozen"})
            continue
        row = next(r for r in stores[store]["rows"] if r["condition"] == condition)
        page_labels.append({"store": store, "condition": condition, "key": expected, "got": row["page_status"], "match": row["page_status"] == expected, "sentences": row["page_sentences"], "read_note": row["read_note"]})

    cases = []
    for case in CASES:
        store = next((d for d, o in LIVE.items() if o["name"].strip() == case["store"]), None)
        if store not in stores:
            continue
        row = next(r for r in stores[store]["rows"] if r["condition"] == case["condition"])
        allowed = case.get("status_shown_any_of") or [case.get("status_shown", "doesnt_say")]
        flag = case.get("contradiction_flag", True if case.get("pages_disagree") or case.get("scoreable") is False else None)
        cases.append(
            {
                "store": case["store"],
                "condition": case["condition"],
                "expected_status": allowed,
                "got_status": row["status_shown"],
                "status_match": row["status_shown"] in allowed,
                "expected_flag": flag,
                "got_flag": row["contradiction"],
                "flag_match": flag is None or flag == row["contradiction"],
                "expected_pages": case.get("pages"),
                "got_pages": row["page_status"],
                "expected_assistant": case["assistant"],
                "got_assistant": row["assistant_status"],
                "sentences": row["page_sentences"],
            }
        )

    quotes = []
    for store, view in stores.items():
        texts = [squash(page.text) for page in readers[store].pages.values()]
        for row in view["rows"]:
            for sentence in row["page_sentences"]:
                quotes.append({"store": store, "condition": row["condition"], "label": sentence["label"], "found": any(squash(sentence["sentence"]) in text for text in texts)})

    wrong_yes = [p for p in page_labels if p["got"] == "yes" and p["key"] != "yes"]
    wrong_yes += [c for c in cases if c["got_pages"] == "yes" and c["expected_pages"] not in (None, "yes")]
    wrong_yes += [c for c in cases if c["got_status"] == "yes" and "yes" not in c["expected_status"]]

    reply_items = [(f"not_excluded/{e['store']}", e["condition"], e["reply"], e["expected"]) for e in NOT_EXCLUDED["ask_replies"]]
    reply_items += [(f"ask_replies/{store}", r["condition"], r["reply"], r["reply_label"]) for store, data in ASKED.items() for r in data["replies"]]
    reply_items += [(f"live_run/{c['store']}", c["condition"], c["assistant_reply"], c["assistant"]) for c in CASES]
    mine = json.loads((db.FIXTURES / "ask_replies" / "napqueen-opened-returns-2026-11-15.json").read_text())
    reply_items.append(("smoke/NapQueen", "opened_returns", mine["reply"], mine["expected"]["assistant_status"]))
    replies = await label_replies(labeler, conds, reply_items)
    sentences = await label_sentences(labeler, conds, NOT_EXCLUDED["page_sentences"])

    scoreable = [p for p in page_labels if p["got"] is not None]
    report = {
        "model": labeler.model,
        "effort": labeler.effort,
        "not_frozen": not_frozen,
        "page_labels": page_labels,
        "page_labels_matched": sum(p["match"] for p in page_labels),
        "page_labels_scored": len(scoreable),
        "page_labels_in_key": len(page_labels),
        "wrong_yes": wrong_yes,
        "saved_cases": cases,
        "quotes_found": sum(q["found"] for q in quotes),
        "quotes_total": len(quotes),
        "reply_labels": replies,
        "not_excluded_sentences": sentences,
        "stores": {d: {"result": s["result"], "rows": s["rows"]} for d, s in stores.items()},
    }
    out = db.ROOT / "reports" / "m3_frozen.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"model {labeler.model}, effort {labeler.effort}; model asked {labeler.asked} times, saved labels reused {labeler.reused} times")
    print(f"\nPAGE LABELS vs key: {report['page_labels_matched']} of {len(page_labels)} match ({len(scoreable)} scored; not frozen: {not_frozen or 'none'})")
    for p in page_labels:
        if not p["match"]:
            known = KNOWN_DIFFERENCES.get((p["store"], p["condition"]))
            print(f"  {'KNOWN DIFFERENCE' if known else 'DIFF'} {p['store']} {p['condition']}: key={p['key']} got={p['got']} {known or p.get('note', '')}")
            for s in p.get("sentences", []):
                print(f"       [{s['label']}] {s['sentence'][:150]}  <{s['url']}>")
    print(f"\nWRONG YES: {len(wrong_yes)}")
    for w in wrong_yes:
        print("  ", json.dumps({k: w[k] for k in w if k not in ("sentences",)})[:300])
    print(f"\nQUOTES found word for word: {report['quotes_found']} of {report['quotes_total']}")
    print(f"\nSAVED CASES (live run): status {sum(c['status_match'] for c in cases)} of {len(cases)}, flags {sum(c['flag_match'] for c in cases)} of {len(cases)}")
    for c in cases:
        if not (c["status_match"] and c["flag_match"]):
            print(f"  DIFF {c['store']} {c['condition']}: expected {c['expected_status']} flag={c['expected_flag']}; got {c['got_status']} flag={c['got_flag']} (pages {c['got_pages']}, assistant {c['got_assistant']})")
    for name in ("not_excluded", "ask_replies", "live_run", "smoke"):
        group = [r for r in replies if r["case"].startswith(name)]
        print(f"\nREPLY LABELS {name}: {sum(r['match'] for r in group)} of {len(group)}")
        for r in group:
            if not r["match"]:
                print(f"  DIFF {r['case']} {r['condition']}: expected {r['expected']} got {r['got']}: {r['reply'][:140]}")
    print(f"\nNOT-EXCLUDED PAGE SENTENCES: {sum(s['match'] for s in sentences)} of {len(sentences)}")
    for s in sentences:
        if not s["match"]:
            print(f"  DIFF {s['case']} {s['condition']}: expected {s['expected']} got {s['got']}: {s['sentence'][:140]}")
    print(f"\nwrote {out.relative_to(db.ROOT)}")
    db.reset()


if __name__ == "__main__":
    asyncio.run(main())
