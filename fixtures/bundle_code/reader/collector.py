import hashlib
import json
import os
import re
import subprocess
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

UA = "terms-check-research/0.1"
LINK_WORDS = re.compile(r"return|refund|sale|deal|clearance|faq|trial|warrant|guarantee|exchange|shipping|polic|outlet|help", re.I)
COLLECTION_WORDS = re.compile(r"sale|clearance|final|outlet|deal|discount|promo", re.I)
SKIP_LINK = re.compile(r"/products/|/cart|/account|/checkout|/search|\.(png|jpg|jpeg|gif|svg|webp|pdf|css|js)(\?|$)|/blogs/|privacy|cookie|terms-of-service|/collections/", re.I)
TOPICS = {
    "opened": re.compile(r"unopened|opened|unused|used|original packag|trial|nights|slept|sleep on|expand|unbox|unworn|same condition", re.I),
    "shipping": re.compile(r"return shipping|shipping cost|prepaid|label|pick ?up|restock|deduct|at (your|their|buyer|customer)[^.]{0,20}(cost|expense)|responsible for", re.I),
    "sale": re.compile(r"sale item|sale price|on sale|final sale|clearance|discounted|promotion|non-returnable|cannot be returned|not eligible", re.I),
}
MAX_PAGES = 26


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


def fetch(url):
    out = subprocess.run(["curl", "-sS", "-L", "-m", "25", "-A", UA, "-w", "\n__HTTP__%{http_code}", url],
                         capture_output=True, text=True, errors="replace").stdout
    body, _, code = out.rpartition("\n__HTTP__")
    time.sleep(0.4)
    return code.strip() or "000", body


def to_text(html):
    p = Text()
    try:
        p.feed(html)
    except Exception:
        pass
    text = "".join(p.out)
    lines = [" ".join(l.split()) for l in text.split("\n")]
    return "\n".join(l for l in lines if l), p.links


def passages(text, pattern, cap, width):
    hits = []
    seen = set()
    for line in text.split("\n"):
        for sent in re.split(r"(?<=[.!?])\s+", line):
            if pattern.search(sent) and 25 < len(sent) < 600:
                key = sent[:80].lower()
                if key in seen:
                    continue
                seen.add(key)
                hits.append(sent[:width])
                if len(hits) >= cap:
                    return hits
    return hits


def run(product_url, outdir, cap, width):
    u = urlparse(product_url)
    base = f"{u.scheme}://{u.netloc}"
    store_dir = os.path.join(outdir, u.netloc.replace(".", "_"))
    os.makedirs(store_dir, exist_ok=True)
    rp = RobotFileParser()
    code, robots = fetch(base + "/robots.txt")
    rp.parse(robots.splitlines() if code == "200" else [])
    report = {"store": u.netloc, "pages": [], "blocked": [], "product": {}, "collections": {}}

    def allowed(url):
        return rp.can_fetch(UA, url)

    handle = u.path.rstrip("/").split("/")[-1]
    code, body = fetch(f"{base}/products/{handle}.js")
    if code == "200":
        try:
            d = json.loads(body)
            v = next((x for x in d.get("variants", []) if str(x.get("id")) in product_url), d.get("variants", [{}])[0])
            report["product"] = {"title": d.get("title", "")[:80], "tags": d.get("tags", [])[:12], "variant": v.get("title"),
                                 "price": v.get("price"), "compare_at": v.get("compare_at_price"), "available": v.get("available")}
        except ValueError:
            pass

    queue = [(product_url.split("?")[0], "product page", 0), (base + "/", "home page", 0),
             (base + "/policies/refund-policy", "policy address", 1), (base + "/pages/refund-policy", "policy address", 1),
             (base + "/policies/shipping-policy", "policy address", 1)]
    code, sm = fetch(base + "/sitemap.xml")
    for loc in re.findall(r"<loc>([^<]+sitemap_pages[^<]*)</loc>", sm or ""):
        c2, pages_xml = fetch(loc.replace("&amp;", "&"))
        for page in re.findall(r"<loc>([^<]+)</loc>", pages_xml or ""):
            if LINK_WORDS.search(urlparse(page).path):
                queue.append((page, "sitemap", 1))
    seen_urls = set()
    seen_text = {}
    texts = {}
    while queue and len(seen_urls) < MAX_PAGES:
        url, how, depth = queue.pop(0)
        key = url.split("#")[0].rstrip("/")
        if key in seen_urls:
            continue
        seen_urls.add(key)
        if not allowed(url):
            report["blocked"].append(url)
            continue
        code, html = fetch(url)
        if code != "200":
            report["pages"].append({"url": url, "status": code, "via": how})
            continue
        text, links = to_text(html)
        digest = hashlib.sha256(text[-4000:].encode()).hexdigest()[:10] if how != "product page" else "product"
        main = text
        entry = {"url": url, "status": code, "via": how, "chars": len(text)}
        policy_like = bool(re.search(r"/policies/|/pages/", urlparse(url).path))
        if policy_like:
            m = re.search(r'(shopify-policy__body|class="rte|<main)', html)
            if m:
                main, _ = to_text(html[m.start():])
        body_digest = hashlib.sha256(main.encode()).hexdigest()[:10]
        if body_digest in seen_text and policy_like:
            entry["same_text_as"] = seen_text[body_digest]
        else:
            seen_text[body_digest] = url
            texts[url] = main
            name = re.sub(r"[^a-z0-9]+", "_", urlparse(url).path.lower()).strip("_")[:60] or "home"
            with open(os.path.join(store_dir, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(url + "\n" + main)
        report["pages"].append(entry)
        if depth < 2:
            for href, anchor in links:
                if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                    continue
                full = urljoin(url, href).split("#")[0]
                if urlparse(full).netloc != u.netloc or SKIP_LINK.search(full):
                    continue
                if LINK_WORDS.search(urlparse(full).path) or LINK_WORDS.search(anchor):
                    queue.append((full, f"link '{anchor[:30]}' on {urlparse(url).path[:40]}", depth + 1))
    code, cj = fetch(base + "/collections.json?limit=250")
    try:
        for c in json.loads(cj).get("collections", []):
            if COLLECTION_WORDS.search(c.get("handle", "")) or COLLECTION_WORDS.search(c.get("title", "")):
                c2, pj = fetch(f"{base}/collections/{c['handle']}/products.json?limit=250")
                try:
                    handles = [p.get("handle") for p in json.loads(pj).get("products", [])]
                    report["collections"][c["handle"]] = {"products": len(handles), "has_item": handle in handles}
                except ValueError:
                    report["collections"][c["handle"]] = {"products": "unreadable"}
    except ValueError:
        report["collections"] = {"note": "collections.json unreadable"}
    report["passages"] = {}
    for url, text in texts.items():
        found = {t: passages(text, pat, cap, width) for t, pat in TOPICS.items()}
        if any(found.values()):
            report["passages"][url] = found
    with open(os.path.join(store_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    return report


def show(report, policy_only):
    print("=" * 8, report["store"])
    print("product:", json.dumps(report["product"]))
    print("collections:", json.dumps(report["collections"]))
    if report["blocked"]:
        print("blocked by robots:", report["blocked"])
    for p in report["pages"]:
        extra = f" same_as={urlparse(p['same_text_as']).path}" if p.get("same_text_as") else ""
        print(f"  [{p['status']}] {urlparse(p['url']).path or '/'} ({p['via'][:50]}){extra}")
    for url, found in report["passages"].items():
        path = urlparse(url).path
        if policy_only and not re.search(r"/policies/|/pages/", path) and "/products/" not in path:
            continue
        print("--", path)
        for topic, hits in found.items():
            for h in hits:
                print(f"   {topic}: {h}")


if __name__ == "__main__":
    outdir = sys.argv[1]
    cap = int(sys.argv[2])
    width = int(sys.argv[3])
    for url in sys.argv[4:]:
        show(run(url, outdir, cap, width), True)
