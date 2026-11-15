import json
import re
from urllib.parse import urlparse

from api import db
from api.reader import CLEARANCE, Page, Reader, key


def folder_for(domain):
    name = re.sub(r"[^a-z0-9]+", "_", domain.lower().removeprefix("www.").removesuffix(".com"))
    return db.FIXTURES / f"pages_{name}"


def save(reader, folder, product, facts=()):
    """Freeze what one live read saw: a text file per page and a report of every address tried."""
    folder.mkdir(exist_ok=True)
    pages = []
    for page in reader.pages.values():
        pages.append({"url": page.url, "status": page.status, "via": page.via, "chars": len(page.text)})
        if page.status == "200":
            name = re.sub(r"[^a-z0-9]+", "_", urlparse(page.url).path.lower()).strip("_")[:60] or "home"
            (folder / f"{name}.txt").write_text(page.url + "\n" + page.text, encoding="utf-8")
    report = {
        "store": reader.host,
        "product_url": reader.product_url,
        "product": product,
        "read_at": db.load("live_run_under_400_2026-11-15.json")["searched_at"],
        "pages": pages,
        "blocked": [p["url"] for p in pages if p["status"] == "blocked"],
        "candidates": reader.candidates,
        "facts": list(facts),
    }
    (folder / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


class FrozenReader(Reader):
    """The same reader, answered from a saved folder. It never touches the network."""

    def __init__(self, folder):
        self.report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        pages = self.report["pages"]
        product_url = self.report.get("product_url") or next(p["url"] for p in pages if p["via"] == "product page")
        super().__init__(client=None, product_url=product_url, pace=0.0)
        self.saved = {}
        for path in folder.glob("*.txt"):
            url, _, text = path.read_text(encoding="utf-8").partition("\n")
            self.saved[key(url)] = text
        self.statuses = {key(p["url"]): p["status"] for p in pages}
        self.blocked = {key(url) for url in self.report.get("blocked", [])}
        self.candidates = dict(self.report.get("candidates") or {
            key(p["url"]): p["via"] for p in pages if p["status"] == "200" and p["via"] not in ("product page", "home page")
        })
        self.sitemap_read = True

    async def allowed(self, url):
        return key(url) not in self.blocked

    async def fetch(self, url):
        if key(url) in self.saved:
            return "200", self.saved[key(url)]
        return self.statuses.get(key(url), "404"), ""

    async def clearance(self, texts):
        if "facts" in self.report:
            return next(iter(self.report["facts"]), None)
        handles = {
            name: entry for name, entry in (self.report.get("collections") or {}).items() if "clearance" in name
        }
        if not handles or not any(CLEARANCE.search(text) for _, text in texts):
            return None
        listed = "is" if any(entry.get("has_item") for entry in handles.values()) else "is not"
        return f"This product {listed} listed in the store's clearance collection."

    async def read(self, url, via):
        if key(url) in self.pages:
            return self.pages[key(url)]
        if not await self.allowed(url):
            page = Page(url, "blocked", via)
        else:
            status, text = await self.fetch(url)
            page = Page(url, status, via, text)
        self.pages[key(url)] = page
        return page
