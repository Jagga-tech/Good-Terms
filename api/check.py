import asyncio
import json
import re
import time
from datetime import datetime, timezone

import httpx

from api import db
from api.combine import page_status
from api.reader import Reader, key
from api.shopify import ShopifyError, ask

STORE_LIMIT = 50.0
CUT_SHORT = "The read was cut short."


def squash(text):
    return " ".join(text.split())


def today():
    return datetime.now(timezone.utc).date().isoformat()


RETURNED = r"return|refund|money.back|send (it |them )?back"
YES_WORDS = {
    "opened_returns": [RETURNED],
    "free_return_shipping": [
        r"free|no (extra )?(cost|charge)|prepaid|pre-paid|we('ll| will)? (pay|cover)|our expense|complimentary"
    ],
    "sale_item_returns": [
        r"sale|discount|promo|clearance|deal|reduced|markdown",
        RETURNED + r"|same|(doesn.t|does not|won.t|will not) (change|affect)|unchanged|regardless|still appl",
    ],
}
TOPIC_WORDS = {
    "opened_returns": [RETURNED + r"|exchange|unused|unopened|opened|unworn|original (packag|condition)|same condition"],
    "free_return_shipping": [
        RETURNED + r"|pick.?up",
        r"free|shipping|label|cost|fee|charge|pay|responsible|expense|pick.?up|prepaid|deduct",
    ],
    "sale_item_returns": [r"sale|discount|promo|clearance|closeout|deal|reduced|markdown"],
}
PAYS_WORDS = {"free_return_shipping": [r"shipping|label|pick.?up|freight|postage|removal"]}
CLEARANCE_ONLY = re.compile(r"clearance|closeout|final sale", re.I)
OTHER_SALE = re.compile(r"sale|discount|promo|deal|reduced|markdown", re.I)
CANCELLATION = re.compile(r"\bcancel", re.I)
PER_LABEL = 2


def clearance_only(sentence):
    """True when a sentence speaks of clearance or final-sale items and of no other sale."""
    return bool(CLEARANCE_ONLY.search(sentence)) and not OTHER_SALE.search(CLEARANCE_ONLY.sub("", sentence))


def quote_check(findings, texts, condition=None, in_clearance=False):
    """Keep a finding only if its sentence is in a saved page word for word.

    texts is a list of (url, text). A sentence found on a different saved page than the one
    named keeps its real page. A yes is also dropped when the sentence itself does not use
    the words its condition is about: a trial length alone is not a yes to opened returns,
    and a sentence is not a yes to sale-item returns only because it mentions a sale. A
    sentence about cancelling an order never counts for a return condition. A sentence that
    answers must use the words of its condition, so a sentence about something else on some
    page cannot put a yes in doubt. A no to free return shipping must name what the buyer
    pays for; "these amounts will be deducted" on its own does not. A sentence about clearance or final-sale items alone does
    not answer for a sale-priced item, unless we found the product in the clearance collection.
    If any kept finding answers the condition, the closest-sentence findings are dropped.
    At most two sentences are kept per status.
    """
    squashed = [(url, squash(text)) for url, text in texts]
    kept = []
    for finding in findings:
        sentence = squash(finding.get("sentence", ""))
        if len(sentence) < 12:
            continue
        named = [(u, t) for u, t in squashed if key(u) == key(finding.get("url", ""))]
        home = next(((u, t) for u, t in named + squashed if sentence in t), None)
        if not home:
            continue
        if CANCELLATION.search(sentence) or CANCELLATION.search(finding.get("heading") or ""):
            continue
        answers = finding["status"] != "doesnt_say"
        needed = TOPIC_WORDS.get(condition, []) if answers else []
        needed = needed + (YES_WORDS.get(condition, []) if finding["status"] == "yes" else [])
        needed = needed + (PAYS_WORDS.get(condition, []) if finding["status"] in ("no", "unclear") else [])
        if not all(re.search(words, sentence, re.I) for words in needed):
            continue
        if answers and condition == "sale_item_returns" and clearance_only(sentence) and not in_clearance:
            continue
        entry = {"sentence": sentence, "url": home[0], "label": finding["status"]}
        heading = re.sub(r"^[^A-Za-z0-9]+", "", squash(finding.get("heading") or ""))
        if heading and heading in home[1]:
            entry["heading"] = heading
        same = [k for k in kept if k["label"] == entry["label"]]
        if entry not in kept and len(same) < PER_LABEL:
            kept.append(entry)
    answering = [entry for entry in kept if entry["label"] != "doesnt_say"]
    return answering or kept[:1]


def triggers(pages, assistant):
    """The conditions a second pass should read further for. Empty means no second pass."""
    if all(status == "yes" for status in pages.values()):
        return set(pages)
    return {
        condition
        for condition, status in pages.items()
        if status == "doesnt_say" or {status, assistant.get(condition)} == {"yes", "no"}
    }


def conditions(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM conditions ORDER BY rowid")]


def start_check(offers, search_text=None, requested_size=None, budget_cents=None):
    """Save a new check with its offers and one pending row per store per condition."""
    conn = db.connect()
    with conn:
        check_id = conn.execute(
            "INSERT INTO checks (search_text, requested_size, budget_cents, started_at, created)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                search_text,
                requested_size,
                budget_cents,
                time.time(),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        ).lastrowid
        for offer in offers:
            conn.execute(
                "INSERT INTO offers (check_id, store_domain, seller_name, storefront_url,"
                " myshopify_domain, product_title, variant_id, variant_labels, price_cents,"
                " price_basis, rows_check, product_url, checkout_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'catalog price', ?, ?, ?)",
                (
                    check_id,
                    offer["store_domain"],
                    offer["name"],
                    offer["storefront_url"],
                    offer["myshopify_domain"],
                    offer["product_title"],
                    offer["variant_id"],
                    json.dumps(offer["variant_labels"]),
                    offer["price_cents"],
                    check_id,
                    offer["product_url"],
                    offer.get("checkout_url"),
                ),
            )
            for condition in conditions(conn):
                conn.execute(
                    "INSERT INTO findings (check_id, store_domain, condition, page_status,"
                    " assistant_status) VALUES (?, ?, ?, 'pending', 'pending')",
                    (check_id, offer["store_domain"], condition["id"]),
                )
    conn.close()
    return check_id


def write(sql, values):
    conn = db.connect()
    with conn:
        conn.execute(sql, values)
    conn.close()


class StoreCheck:
    """One store's check: ask, read, label, read further if needed, then save in one step."""

    def __init__(self, check_id, offer, conds, client, labeler, reader=None, saved_replies=None):
        self.check_id = check_id
        self.offer = offer
        self.store = offer["store_domain"]
        self.conds = conds
        self.client = client
        self.labeler = labeler
        self.reader = reader or Reader(client, offer["product_url"])
        self.saved_replies = saved_replies
        self.product = f"{offer['product_title']} ({' / '.join(json.loads(offer['variant_labels']))})"
        self.findings = {}
        self.assistant = {}
        self.facts = []
        self.note = None

    def where(self):
        return self.check_id, self.store

    async def ask_one(self, condition):
        if self.saved_replies is not None:
            reply = self.saved_replies.get(condition["id"])
        else:
            try:
                reply = await ask(
                    self.client, self.offer["myshopify_domain"], condition["question"], self.offer["variant_id"]
                )
            except (ShopifyError, httpx.HTTPError):
                reply = None
        write(
            "UPDATE findings SET assistant_reply = ?, reply_time = ?, assistant_status = ?"
            " WHERE check_id = ? AND store_domain = ? AND condition = ?",
            (reply, today(), "pending" if reply else "unavailable", *self.where(), condition["id"]),
        )
        return condition["id"], reply

    async def ask_all(self):
        """Three questions at once. Each reply is saved the moment it arrives, then labeled."""
        replies = dict(await asyncio.gather(*(self.ask_one(c) for c in self.conds)))
        write(
            "UPDATE offers SET replies_in = 1, replies_at = ? WHERE check_id = ? AND store_domain = ?",
            (time.time(), *self.where()),
        )
        try:
            labels = await self.labeler.replies(self.conds, self.product, replies)
        except Exception:
            labels = {}
        for condition in self.conds:
            status = labels.get(condition["id"], "unavailable")
            self.assistant[condition["id"]] = status
            write(
                "UPDATE findings SET assistant_status = ?"
                " WHERE check_id = ? AND store_domain = ? AND condition = ?",
                (status, *self.where(), condition["id"]),
            )

    async def label_pages(self):
        texts = self.reader.texts()
        if not texts:
            return
        raw = await self.labeler.pages(self.conds, self.product, texts, self.facts)
        in_clearance = any("is listed" in fact for fact in self.facts)
        for c in self.conds:
            found = quote_check(raw.get(c["id"], []), texts, c["id"], in_clearance)
            if any(f["label"] == "yes" for f in found):
                found = [f for f in found if await self.stands(c, f)]
            self.findings[c["id"]] = found

    async def stands(self, condition, finding):
        """A sentence may put a yes in doubt only if it still says so when read on its own."""
        if finding["label"] not in ("no", "unclear"):
            return True
        again = await self.labeler.recheck(condition, self.product, finding)
        return again in ("no", "unclear")

    def page_statuses(self):
        return {c["id"]: page_status([f["label"] for f in self.findings.get(c["id"], [])])[0] for c in self.conds}

    async def steps(self):
        asking = asyncio.create_task(self.ask_all())
        try:
            await self.reader.first_pass()
            await self.label_pages()
            await asking
            further = triggers(self.page_statuses(), self.assistant) if self.reader.texts() else set()
            if further:
                await self.reader.second_pass(further)
                if "sale_item_returns" in further and not self.facts:
                    fact = await self.reader.clearance(self.reader.texts())
                    self.facts = [fact] if fact else []
                await self.label_pages()
        finally:
            if not asking.done():
                asking.cancel()

    async def run(self, limit=STORE_LIMIT):
        try:
            await asyncio.wait_for(self.steps(), limit)
        except asyncio.TimeoutError:
            self.note = CUT_SHORT
        except Exception as problem:
            self.note = f"{CUT_SHORT} ({type(problem).__name__})"
        self.save()

    def save(self):
        """The store's rows turn final here, in one step, and only here."""
        readable = bool(self.reader.texts())
        conn = db.connect()
        with conn:
            for page in self.reader.pages.values():
                conn.execute(
                    "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (*self.where(), page.url, page.status, page.via, today(), page.text),
                )
            for condition in self.conds:
                found = self.findings.get(condition["id"], [])
                status, disagree = page_status([f["label"] for f in found])
                conn.execute(
                    "UPDATE findings SET page_status = ?, page_sentences = ?, pages_disagree = ?,"
                    " date_read = ?, read_note = ?,"
                    " assistant_status = CASE assistant_status WHEN 'pending' THEN 'unavailable'"
                    " ELSE assistant_status END"
                    " WHERE check_id = ? AND store_domain = ? AND condition = ?",
                    (
                        status if readable or self.note else "unreadable",
                        json.dumps(found, ensure_ascii=False),
                        int(disagree),
                        today() if readable else None,
                        self.note,
                        *self.where(),
                        condition["id"],
                    ),
                )
            conn.execute(
                "UPDATE offers SET pages_read = 1, done_at = ? WHERE check_id = ? AND store_domain = ?",
                (time.time(), *self.where()),
            )
        conn.close()


async def run_check(check_id, labeler, limit=STORE_LIMIT):
    """Check every store of a saved check in parallel, each with its own time limit."""
    conn = db.connect()
    offers = [dict(row) for row in conn.execute("SELECT * FROM offers WHERE check_id = ?", (check_id,))]
    conds = conditions(conn)
    conn.close()
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *(StoreCheck(check_id, offer, conds, client, labeler).run(limit) for offer in offers)
        )
