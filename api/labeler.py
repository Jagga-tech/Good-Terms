import asyncio
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

import anthropic

from api import db

STATUSES = ["yes", "no", "doesnt_say"]

SYSTEM = """You label what an online store says about a buyer's return conditions. Your labels are shown \
to the buyer next to the store's own words, so a wrong "yes" does real harm. When in doubt, the \
answer is not a yes.

Judge only the text you are given. Never use what you know about the store, its reputation, or what \
stores usually do.

The buyer's case is fixed: they buy the product named below, open it, use it, and then want to \
return it. Each condition asks one narrow question about that case.

What counts:
- yes: the text explicitly says the buyer can do this in their case. Conditions attached to a yes \
(a time window, a clean item, a donation receipt) are still a yes.
- no: the text says the buyer cannot do this, or must pay for it. "Unused and in original \
packaging" is a no to returning an opened, used item.
- doesnt_say: nothing explicitly covers the buyer's case.

Rules that decide the hard cases:
- "Not excluded" is not a yes. Text that only fails to rule the buyer's case out is doesnt_say. \
Listing clearance or final-sale items as non-returnable says nothing about an item bought at a sale \
price. A statement that no exception or exclusion is mentioned is not a yes.
- A different case is doesnt_say, never a no. A free return label offered only for unopened items \
says nothing about an opened one: it does not say the buyer pays. A no needs words that say the \
buyer cannot do it or must pay for it.
- A trial length, a badge, a slogan or advice to try the item for some nights is not a yes on its \
own. A yes to opened returns must itself say the item can be returned or refunded.
- Hedged words ("may", "possibly", "case by case", "contact us for next steps", "does not appear \
to") are not a yes.
- Return shipping means the cost of getting the item back to the store. A fee the buyer pays for \
that (a return label, freight, pickup or removal fee, even when taken out of the refund) is a no to \
free return shipping. Money kept for other reasons (the original outbound shipping, payment \
processing fees, a restocking fee) is not return shipping and does not answer the condition.
- Cancelling an order is not returning it. A sentence about order changes or cancellations (before \
or after shipping) never answers a return condition: not as a yes, not as a no, not as unclear.
- A yes to sale-item returns must itself say that an item bought on sale can be returned or \
refunded, or that buying on sale leaves the trial or return terms the same as at full price. A \
sentence is not a yes because it mentions a sale. Saying that purchases in some sale come with a \
trial or a warranty, without saying the terms are the same or that they can be returned, is not a yes.
- Each condition is judged on its own question. Free returns do not answer whether a sale-priced \
item can be returned, and the reverse."""

PAGES_TASK = """Label one page of the store for each condition. Other pages are labeled separately, so \
judge only what this page says.

For each condition, list the sentences on this page that speak to the buyer's case, each with a \
status:
- yes or no: as defined.
- unclear: the sentence says the buyer's case might be refused, limited or charged for ("may be \
rejected", "may not be eligible", "at our discretion", "may be responsible for"). It must put a yes \
in real doubt. A sentence that is only vague, friendly or non-committal ("we're here to help", \
"contact us", "easy returns") is not unclear: leave it out, or give it as the closest sentence with \
doesnt_say. A trial length, a slogan or a general condition of the item is not unclear either.
- doesnt_say: use this only when no sentence on this page answers the condition. Then return \
either an empty list or the one closest sentence, which covers a different case.

Copy each sentence exactly, character for character, as one whole sentence from the page. Do not \
join text from two places, fix typos, or shorten. If a sentence only has its meaning under its \
section heading (for example the heading says the section is about opened items), copy that heading \
line exactly into "heading"; otherwise leave "heading" empty.

If sentences on this page disagree, list each of them. Give at most two sentences per condition. \
Prefer a sentence that itself names the buyer's case."""

REPLIES_TASK = """Label the reply the store's assistant gave to each condition's question.

Give one status per condition: yes, no or doesnt_say, as defined. A reply that opens with "Yes" but \
whose only support for the buyer's case is that no exclusion or exception is stated is doesnt_say. \
A reply that says the store's information does not specify, or that hedges, is doesnt_say. A reply \
that requires the item to be unused is a no to opened returns."""


class LabelError(Exception):
    pass


def schema(conditions, item):
    return {
        "type": "object",
        "properties": {
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"condition": {"type": "string", "enum": conditions}, **item},
                    "required": ["condition", *item],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["conditions"],
        "additionalProperties": False,
    }


FINDINGS = {
    "findings": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": [*STATUSES, "unclear"]},
                "sentence": {"type": "string"},
                "url": {"type": "string"},
                "heading": {"type": "string"},
            },
            "required": ["status", "sentence", "url", "heading"],
            "additionalProperties": False,
        },
    }
}
REPLY = {"status": {"type": "string", "enum": STATUSES}}


def describe(conditions, product):
    lines = [f"Product: {product}", "", "Conditions:"]
    lines += [f"- {c['id']}: {c['label']}. {c['definition']}" for c in conditions]
    return "\n".join(lines)


CACHE = db.ROOT / "labels.db"


class Labeler:
    """The one place a model is used: it labels each source separately.

    Every answer is saved under a hash of exactly what was asked: the model, the rules and
    the text. The same page text or reply therefore always gets the same label, and the
    model is asked again only when the text changes. LABEL_CACHE=refresh asks again and
    replaces the saved answers; LABEL_CACHE=off neither reads nor saves.
    """

    def __init__(self, model=None, effort=None, cache=None):
        self.client = anthropic.AsyncAnthropic()
        self.model = model or os.environ.get("LABELER_MODEL", "claude-sonnet-5-5")
        self.effort = effort or os.environ.get("LABELER_EFFORT", "low")
        self.mode = os.environ.get("LABEL_CACHE", "on")
        self.cache = cache or CACHE
        self.limit = asyncio.Semaphore(16)
        self.asked = 0
        self.reused = 0
        conn = sqlite3.connect(self.cache)
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS labels (key TEXT PRIMARY KEY, saved TEXT, answer TEXT)")
        conn.close()

    def saved(self, key):
        conn = sqlite3.connect(self.cache)
        row = conn.execute("SELECT answer FROM labels WHERE key = ?", (key,)).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None

    def save(self, key, answer):
        conn = sqlite3.connect(self.cache)
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO labels VALUES (?, ?, ?)",
                (key, datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(answer)),
            )
        conn.close()

    async def call(self, task, body, output):
        asked = json.dumps([self.model, self.effort, SYSTEM, task, body, output], sort_keys=True)
        key = hashlib.sha256(asked.encode()).hexdigest()
        if self.mode == "on":
            answer = self.saved(key)
            if answer is not None:
                self.reused += 1
                return answer
        async with self.limit:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=SYSTEM,
                messages=[{"role": "user", "content": f"{task}\n\n{body}"}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": output}},
            )
        if response.stop_reason != "end_turn":
            raise LabelError(f"labeler stopped with {response.stop_reason}")
        text = next((block.text for block in response.content if block.type == "text"), "")
        answer = {entry["condition"]: entry for entry in json.loads(text)["conditions"]}
        self.asked += 1
        if self.mode != "off":
            self.save(key, answer)
        return answer

    async def page(self, conditions, product, url, text, facts):
        body = [describe(conditions, product)]
        if facts:
            body.append("Facts we checked ourselves. Use them to judge, never quote them:")
            body += [f"- {fact}" for fact in facts]
        body.append(f'<page url="{url}">\n{text}\n</page>')
        found = await self.call(PAGES_TASK, "\n\n".join(body), schema([c["id"] for c in conditions], FINDINGS))
        return {
            c["id"]: [{**f, "url": url} for f in found.get(c["id"], {}).get("findings", [])] for c in conditions
        }

    async def pages(self, conditions, product, pages, facts=()):
        """Per condition, the sentences on the store's pages that answer it, with a status each.

        Each page is labeled on its own, so an unchanged page keeps its label.
        """
        labeled = await asyncio.gather(*(self.page(conditions, product, url, text, facts) for url, text in pages))
        return {c["id"]: [f for page in labeled for f in page[c["id"]]] for c in conditions}

    async def recheck(self, condition, product, finding):
        """A second look at one sentence on its own, before it is allowed to put a yes in doubt."""
        text = "\n".join(part for part in (finding.get("heading"), finding["sentence"]) if part)
        found = await self.page([condition], product, finding["url"], text, ())
        for again in found[condition["id"]]:
            if " ".join(again["sentence"].split()) in " ".join(finding["sentence"].split()):
                return again["status"]
        return "doesnt_say"

    async def reply(self, condition, product, reply):
        body = (
            f"{describe([condition], product)}\n\n"
            f'<reply condition="{condition["id"]}">\nQuestion: {condition["question"]}\nReply: {reply}\n</reply>'
        )
        found = await self.call(REPLIES_TASK, body, schema([condition["id"]], REPLY))
        return found.get(condition["id"], {}).get("status", "doesnt_say")

    async def replies(self, conditions, product, replies):
        """Per condition, the status of the assistant's reply. Each reply is judged in its own call."""
        asked = [c for c in conditions if replies.get(c["id"])]
        statuses = await asyncio.gather(*(self.reply(c, product, replies[c["id"]]) for c in asked))
        return {c["id"]: status for c, status in zip(asked, statuses)}
