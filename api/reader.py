import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from api.shopify import UA

BARRED = {"kv-mart-us.myshopify.com"}
LINK_WORDS = re.compile(
    r"return|refund|sale|deal|clearance|faq|trial|warrant|guarantee|exchange|shipping|polic|outlet|help", re.I
)
SKIP_LINK = re.compile(
    r"/products/|/cart|/account|/checkout|/search|\.(png|jpg|jpeg|gif|svg|webp|pdf|css|js)(\?|$)"
    r"|/blogs/|privacy|cookie|terms-of-service|/collections/",
    re.I,
)
PRIORITIES = {
    "opened_returns": ("return|refund", "trial", "faq", "warrant|guarantee|exchange"),
    "free_return_shipping": ("return|refund", "shipping", "trial|faq"),
    "sale_item_returns": ("sale|clearance|deal|promo|outlet|final|black-friday|cyber", "return|refund", "faq|trial"),
}
RETURNS = re.compile(r"return|refund", re.I)
SHIPPING = re.compile(r"shipping", re.I)
CLEARANCE = re.compile(r"clearance|final sale", re.I)
SECOND_PASS_PAGES = 8
PAGE_CHARS = 40000


class Text(HTMLParser):
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "tr", "section", "summary", "details", "td", "dd", "dt"}
    SKIP = {"script", "style", "noscript", "svg", "template", "head"}

    def __init__(self):
        super().__init__()
        self.out = []
        self.links = []
        self.skip = 0
        self.href = None
        self.anchor = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.anchor = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join("".join(self.anchor).split())))
            self.href = None

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(data)
        if self.href is not None:
            self.anchor.append(data)


def to_text(html):
    parser = Text()
    try:
        parser.feed(html)
    except Exception:
        pass
    lines = [" ".join(line.split()) for line in "".join(parser.out).split("\n")]
    return "\n".join(line for line in lines if line), parser.links


def key(url):
    return url.split("#")[0].split("?")[0].rstrip("/")


@dataclass
class Page:
    url: str
    status: str
    via: str
    text: str = ""


@dataclass
class Reader:
    """Reads one store's public pages: paced, within robots.txt, three pages first."""

    client: object
    product_url: str
    pace: float = 0.4
    pages: dict = field(default_factory=dict)
    candidates: dict = field(default_factory=dict)

    def __post_init__(self):
        self.product_url = self.product_url.split("?")[0]
        parsed = urlparse(self.product_url)
        self.host = parsed.netloc
        self.base = f"{parsed.scheme}://{parsed.netloc}"
        self.robots = None
        self.lock = asyncio.Lock()
        self.last = 0.0
        self.sitemap_read = False

    async def fetch(self, url):
        """One paced GET. Waits and retries on HTTP 429."""
        async with self.lock:
            for attempt in range(3):
                wait = self.last + self.pace - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    response = await self.client.get(
                        url, headers={"User-Agent": UA}, follow_redirects=True, timeout=15
                    )
                except Exception as problem:
                    self.last = time.monotonic()
                    return type(problem).__name__, ""
                self.last = time.monotonic()
                if response.status_code != 429 or attempt == 2:
                    return str(response.status_code), response.text
                retry_after = response.headers.get("retry-after", "")
                await asyncio.sleep(min(float(retry_after), 5.0) if retry_after.isdigit() else 2.0)

    async def allowed(self, url):
        if self.host in BARRED:
            return False
        if self.robots is None:
            self.robots = RobotFileParser()
            status, body = await self.fetch(self.base + "/robots.txt")
            self.robots.parse(body.splitlines() if status == "200" else [])
        return self.robots.can_fetch(UA, url)

    async def read(self, url, via):
        if key(url) in self.pages:
            return self.pages[key(url)]
        if not await self.allowed(url):
            page = Page(url, "blocked", via)
        else:
            status, html = await self.fetch(url)
            page = Page(url, status, via)
            if status == "200":
                text, links = to_text(html)
                if re.search(r"/policies/|/pages/", urlparse(url).path):
                    body = re.search(r'(shopify-policy__body|class="rte|<main)', html)
                    if body:
                        text, _ = to_text(html[body.start():])
                page.text = text
                self.collect(url, links)
        self.pages[key(url)] = page
        return page

    def collect(self, url, links):
        for href, anchor in links:
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            full = urljoin(url, href).split("#")[0]
            if urlparse(full).netloc != self.host or SKIP_LINK.search(full):
                continue
            if LINK_WORDS.search(urlparse(full).path) or LINK_WORDS.search(anchor):
                self.candidates.setdefault(key(full), anchor or "link")

    def linked(self, pattern):
        for url in self.candidates:
            if url not in self.pages and pattern.search(urlparse(url).path) and "/policies/" not in url:
                return url
        return None

    async def first_pass(self):
        """The product page, the return policy and the shipping policy.

        When a policy address is missing or blocked, the page the store links to is read instead.
        """
        await self.read(self.product_url, "product page")
        for path, pattern, fallbacks in (
            ("/policies/refund-policy", RETURNS, ("/pages/refund-policy", "/pages/return-policy")),
            ("/policies/shipping-policy", SHIPPING, ("/pages/shipping-policy",)),
        ):
            page = await self.read(self.base + path, "policy address")
            if page.status == "200":
                continue
            linked = self.linked(pattern)
            for url in ([linked] if linked else [self.base + f for f in fallbacks]):
                if (await self.read(url, "page the store links to")).status == "200":
                    break

    async def sitemap(self):
        if self.sitemap_read:
            return
        self.sitemap_read = True
        if not await self.allowed(self.base + "/sitemap.xml"):
            return
        _, index = await self.fetch(self.base + "/sitemap.xml")
        for location in re.findall(r"<loc>([^<]+sitemap_pages[^<]*)</loc>", index or "")[:1]:
            _, listing = await self.fetch(location.replace("&amp;", "&"))
            for page in re.findall(r"<loc>([^<]+)</loc>", listing or ""):
                if LINK_WORDS.search(urlparse(page).path) and not SKIP_LINK.search(page):
                    self.candidates.setdefault(key(page), "sitemap")

    def choose(self, conditions):
        """Up to eight unread pages, taken in turn for each open condition.

        Best match first, and among equal matches the shorter address: a store's own sale or
        returns page before a long landing page that only mentions the word.
        """
        self.candidates.setdefault(self.base + "/pages/refund-policy", "second return-policy address")
        unread = [(url, anchor) for url, anchor in self.candidates.items() if url not in self.pages]
        queues = []
        for condition in sorted(conditions):
            ranked = []
            for position, (url, anchor) in enumerate(unread):
                words = urlparse(url).path + " " + anchor
                rank = next(
                    (i for i, pattern in enumerate(PRIORITIES[condition]) if re.search(pattern, words, re.I)), None
                )
                if rank is not None:
                    ranked.append((rank, len(urlparse(url).path), position, url))
            queues.append([url for *_, url in sorted(ranked)])
        chosen = []
        while any(queues) and len(chosen) < SECOND_PASS_PAGES:
            for queue in queues:
                while queue and queue[0] in chosen:
                    queue.pop(0)
                if queue and len(chosen) < SECOND_PASS_PAGES:
                    chosen.append(queue.pop(0))
        return chosen

    async def second_pass(self, conditions):
        await self.sitemap()
        for url in self.choose(conditions):
            await self.read(url, self.candidates[url])

    async def clearance(self, texts):
        """Whether this product is in the store's clearance collection, when its pages mention one.

        A fact we check ourselves from the store's public collection list. It is never quoted.
        """
        if not any(CLEARANCE.search(text) for _, text in texts):
            return None
        url = self.base + "/collections/clearance/products.json?limit=250"
        if not await self.allowed(url):
            return None
        status, body = await self.fetch(url)
        if status == "404":
            return "The store has no clearance collection."
        try:
            handles = [product.get("handle") for product in json.loads(body)["products"]]
        except (ValueError, KeyError, TypeError):
            return None
        listed = "is" if key(self.product_url).rsplit("/", 1)[-1] in handles else "is not"
        return f"This product {listed} listed in the store's clearance collection."

    def texts(self):
        """The saved text of every page read, one entry per distinct text."""
        seen = set()
        out = []
        for page in self.pages.values():
            if page.status == "200" and page.text and page.text not in seen:
                seen.add(page.text)
                out.append((page.url, page.text[:PAGE_CHARS]))
        return out
