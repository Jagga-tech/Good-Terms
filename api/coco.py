"""Coco, the buyer's personal shopping agent: one conversation, four tools, and the gates."""

import asyncio
import json
import os
import re

import anthropic
import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import banned, db, goodterms
from api.check import run_check, start_check
from api.search import search

router = APIRouter(prefix="/api")
MODEL = os.environ.get("COCO_MODEL", "claude-sonnet-5-5")

SYSTEM = """You are Coco, a personal shopping agent. You work for one person, your buyer, and you speak \
to them directly: "I" for yourself, "you" and "your conditions" for them.

What you do: you find products and prices. A separate service called GoodTerms then checks each \
store against your buyer's saved conditions and shows what each store says, with the store's own \
words, on a screen called Buyer's Check. Your buyer reads the answers there and decides. You never \
buy and never pay; the buyer pays in the store's own checkout.

You already know your buyer. Their saved conditions: {conditions}. Their saved ZIP code: {zip}. \
Use that ZIP for every search and never ask for it; if they name a different ZIP in a request, use \
theirs for that search.

How a request goes:
1. You need two things from your buyer to search: the size and the budget. If either is missing, \
ask for what is missing in one short question, once. If you have both, do not ask anything.
2. Call search_products. Then call check_stores, then open_buyers_check, straight away in the same \
turn. Do not wait for the check, and do not show prices before the check has started.
3. Then tell your buyer what you did in one or two short sentences. Name the size you searched \
for and how many stores you found, and say Buyer's Check is open.

Later, GoodTerms tells you when every store's check has finished. Say only that the checks are \
finished and that the answers are on Buyer's Check, in one or two short sentences. Do not list or \
summarise the results in that message, even if your buyer asked about a store earlier. Your \
messages carry no results unless your buyer asks about a store after its check has finished; then \
give its result in one sentence and point to Buyer's Check in the other.

Messages inside <goodterms_event> tags come from the app, not from your buyer.

How you write: every message is one or two short sentences, never three. This holds for every \
message, including refusals and answers to follow-up questions; if you have more to say, say the \
most useful two sentences and stop. Plain text, no lists and no formatting. No greetings, no \
exclamation marks, no emoji, no sales language. Say nothing before or between tool calls; speak \
once, after them.

What you never do, even when asked:
- You never recommend, rank or suggest a store or a purchase, and you never say which store is \
best or which you would pick. What each store says is on Buyer's Check, and the choice is your \
buyer's. You may state a price as a fact.
- You never say what a store answers to a condition from your own reading. While a store's pages \
are still being read you say nothing about its answers. If you mention a store's result after its \
check has finished, use exactly the words GoodTerms gave you for it, and point to Buyer's Check for \
the store's own words.
- You never buy, pay or complete a checkout. If your buyer asks you to buy for them, say plainly \
that you can't buy or pay, and point them to Buyer's Check, where they can review a store's answers \
and go to that store's own checkout.
- You never use these words: {banned}."""

TOOLS = [
    {
        "name": "search_products",
        "description": "Search Shopify's catalog live for the buyer's request. Returns up to six stores that have the product in the requested size, in stock and within budget. Returns no prices and no links.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for, for example: queen mattress"},
                "size": {"type": "string", "description": "The size asked for, for example: Queen"},
                "budget_dollars": {"type": "number", "description": "The most the buyer will pay, in dollars"},
                "zip_code": {"type": "string", "description": "The ZIP code to ship to"},
            },
            "required": ["query", "size", "budget_dollars", "zip_code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_stores",
        "description": "Send the stores from the last search to GoodTerms to be checked against the buyer's conditions. Starts the check and returns at once, before any answer exists.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_prices",
        "description": "The catalog price at each store from the last search. Refused until the check has started.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "open_buyers_check",
        "description": "Open the Buyer's Check screen for the check that was started.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]
COULD_NOT_FINISH = "I couldn't finish that. Please ask me again."
DEFAULT_ZIP = "94541"


class LiveBackend:
    """Real search, real check."""

    async def search(self, query, size, budget_cents, zip_code):
        async with httpx.AsyncClient() as client:
            return await search(client, query, size, budget_cents, zip_code)

    async def start(self, offers, request):
        from api.labeler import Labeler

        text = f"{request['query']}, under ${request['budget_cents'] // 100}, shipping to {request['zip_code']}"
        check_id = start_check(offers, text, request["size"], request["budget_cents"])
        self.running = asyncio.create_task(run_check(check_id, Labeler()))
        return check_id

    async def wait(self, check_id):
        await self.running


class SavedBackend:
    """Replays the saved search and the saved check of 2026-11-15. Contacts no store."""

    def __init__(self, pace=1.0):
        self.pace = pace

    async def search(self, query, size, budget_cents, zip_code):
        calls = db.load("search_run_2026-11-15.json")["calls"]

        def answer(request):
            body = json.loads(request.content) if request.content else None
            for call in calls:
                if call["method"] != request.method or call["url"] != str(request.url):
                    continue
                same = body is None or (
                    call["request"]["params"]["name"] == body["params"]["name"]
                    and call["request"]["params"]["arguments"]["catalog"].get("id")
                    == body["params"]["arguments"]["catalog"].get("id")
                )
                if same:
                    return httpx.Response(call["status"], json=call["response"])
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            return await search(client, query, size, budget_cents, zip_code)

    async def start(self, offers, request):
        return goodterms.replay_check(2, self.pace)["id"]

    async def wait(self, check_id):
        while not goodterms.get_check(check_id)["done"]:
            await asyncio.sleep(0.2)


def make_backend():
    return SavedBackend() if os.environ.get("GOODTERMS_MODE") == "saved" else LiveBackend()


class Conversation:
    def __init__(self, backend=None, client=None):
        self.backend = backend or make_backend()
        self.client = client or anthropic.AsyncAnthropic()
        self.messages = []
        self.lines = []
        self.tools_called = []
        self.offers = None
        self.request = None
        self.check_id = None
        self.lock = asyncio.Lock()
        self.finishing = None
        self.step = None

    def system(self):
        conn = db.connect()
        labels = [row["label"] for row in conn.execute("SELECT label FROM conditions ORDER BY rowid")]
        conn.close()
        return SYSTEM.format(
            conditions=", ".join(labels), zip=buyer()["zip"] or "not saved yet", banned=", ".join(banned.WORDS)
        )

    async def use(self, name, args):
        """Run one tool. The gates live here, in code, not in the instructions."""
        self.tools_called.append(name)
        if name == "search_products":
            self.request = {
                "query": args["query"],
                "size": args["size"],
                "budget_cents": round(args["budget_dollars"] * 100),
                "zip_code": args["zip_code"],
            }
            self.offers = await self.backend.search(**self.request)
            self.check_id = None
            if self.step:
                self.step["stores"] = len(self.offers)
            return {
                "size_searched": args["size"],
                "stores_found": len(self.offers),
                "stores": [
                    {"store": o["name"], "product": o["product_title"], "variant": " / ".join(o["variant_labels"])}
                    for o in self.offers
                ],
            }
        if name == "check_stores":
            if not self.offers:
                return {"error": "There are no stores to check. Search first."}
            if self.check_id is None:
                self.check_id = await self.backend.start(self.offers, self.request)
                if self.step:
                    self.step["check_id"] = self.check_id
                self.finishing = asyncio.create_task(self.when_finished(self.check_id))
            return {
                "started": True,
                "stores": len(self.offers),
                "note": "No answer exists yet. Answers appear on Buyer's Check as each store's pages are read.",
            }
        if self.check_id is None:
            return {"error": "The check has not started. Call check_stores first."}
        if name == "get_prices":
            stores = goodterms.get_check(self.check_id)["stores"]
            return {
                "prices": [
                    {"store": s["name"], "price": s["offer"]["price_text"], "basis": s["offer"]["price_basis"]}
                    for s in stores
                    if s["offer"]
                ]
            }
        if name == "open_buyers_check":
            return {"opened": True, "screen": "Buyer's Check"}
        return {"error": f"No such tool: {name}"}

    async def turn(self, text, said_by="you"):
        """One turn: the buyer's line (or an app event), tool calls, then Coco's line."""
        async with self.lock:
            if said_by == "you":
                self.lines.append({"who": "you", "text": text})
                yield {"type": "you", "text": text}
            self.messages.append({"role": "user", "content": text})
            for _ in range(6):
                spoken = ""
                async with self.client.messages.stream(
                    model=MODEL,
                    max_tokens=1000,
                    system=self.system(),
                    tools=TOOLS,
                    messages=self.messages,
                    output_config={"effort": "low"},
                ) as stream:
                    async for delta in stream.text_stream:
                        spoken += delta
                        yield {"type": "delta", "text": delta}
                    message = await stream.get_final_message()
                self.messages.append({"role": "assistant", "content": message.content})
                if spoken.strip():
                    self.lines.append({"who": "coco", "text": spoken.strip()})
                    yield {"type": "line"}
                if message.stop_reason != "tool_use":
                    if message.stop_reason != "end_turn" and not spoken.strip():
                        self.lines.append({"who": "coco", "text": COULD_NOT_FINISH})
                        yield {"type": "delta", "text": COULD_NOT_FINISH}
                        yield {"type": "line"}
                    break
                results = []
                for block in message.content:
                    if block.type != "tool_use":
                        continue
                    if block.name == "search_products":
                        self.step = {"who": "steps", "stores": None, "check_id": None}
                        self.lines.append(self.step)
                        yield {"type": "steps"}
                    result = await self.use(block.name, block.input)
                    yield {"type": "steps"}
                    if block.name == "open_buyers_check" and result.get("opened"):
                        yield {"type": "open", "check_id": self.check_id}
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
                self.messages.append({"role": "user", "content": results})
            yield {"type": "end"}

    async def when_finished(self, check_id):
        """When every store is done, GoodTerms tells Coco, with each store's result word for word."""
        await self.backend.wait(check_id)
        stores = goodterms.get_check(check_id)["stores"]
        results = "; ".join(f"{s['name']}: {s['result_text']}" for s in stores)
        event = (
            "<goodterms_event>Every store's check has finished. Each store's result, word for word: "
            f"{results}. The store's own words are on Buyer's Check.</goodterms_event>"
        )
        async for _ in self.turn(event, said_by="goodterms"):
            pass


current = None


def conversation():
    global current
    if current is None:
        current = Conversation()
    return current


def sentences(text):
    """How many sentences a line has. Prices like $164.99 do not end a sentence."""
    return len([part for part in re.split(r"[.!?][\"'”’)]*(?:\s+|$)", text.strip()) if part.strip()])


class Said(BaseModel):
    text: str


def buyer():
    """The one buyer. Coco already knows them: three saved conditions and a saved ZIP code."""
    return {"confirmed": True, "zip": DEFAULT_ZIP}


def condition_list():
    conn = db.connect()
    conds = [dict(row) for row in conn.execute("SELECT id, label, definition FROM conditions ORDER BY rowid")]
    conn.close()
    return conds


def step_view(step):
    """The work Coco has really done so far, read from the search and the check themselves."""
    if step["stores"] is None:
        return [{"text": "Searching Shopify's catalog", "done": False}]
    count = step["stores"]
    out = [{"text": f"Searched Shopify's catalog · {count} store{'' if count == 1 else 's'}", "done": True}]
    if step["check_id"]:
        stores = goodterms.get_check(step["check_id"])["stores"]
        rows = [row for store in stores for row in store["rows"]]
        answers = sum(bool(row["assistant_reply"]) for row in rows)
        asked = all(store["progress"]["replies_in"] for store in stores)
        waiting = f"Asking each store's assistant · {answers} of {len(rows)}"
        out.append({"text": f"Asked each store's assistant · {answers} answers" if asked else waiting, "done": asked})
        read = sum(store["progress"]["pages_read"] for store in stores)
        reading = f"Reading store pages · {read} of {len(stores)}"
        out.append({"text": f"Read store pages · {read} of {len(stores)}" if read == len(stores) else reading, "done": read == len(stores)})
    return out


def lines_view(conv):
    return [{"who": "steps", "steps": step_view(l)} if l["who"] == "steps" else l for l in conv.lines]


@router.get("/coco")
def get_coco():
    conv = conversation()
    saved = buyer()
    done = bool(conv.check_id) and goodterms.get_check(conv.check_id)["done"]
    return {
        "conditions_confirmed": saved["confirmed"],
        "conditions": condition_list(),
        "zip": saved["zip"],
        "backup_mode": os.environ.get("GOODTERMS_MODE") == "saved",
        "lines": lines_view(conv),
        "check_id": conv.check_id,
        "check_done": done,
        "busy": conv.lock.locked(),
    }


@router.post("/coco")
async def say(body: Said):
    conv = conversation()

    async def stream():
        async for event in conv.turn(body.text.strip()):
            yield json.dumps(event) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/coco/reset")
def reset_coco():
    global current
    current = None
    return {"ok": True}
