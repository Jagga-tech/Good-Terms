import itertools
import re

from api import banned, db, texts

WEB = db.ROOT / "web"
SOURCES = [p for p in (WEB / "src").rglob("*") if p.is_file() and ".test." not in p.name]
APP_TEXT = SOURCES + [WEB / "index.html", *sorted((db.ROOT / "api").glob("*.py"))]
COLOURS = {"#3f7d5c", "#f6f8fb", "#223354"}
NAMED = "white|black|red|green|blue|gray|grey|orange|yellow|purple|pink|teal|silver|gold"


def read(path):
    return path.read_text(encoding="utf-8")


def test_only_the_three_colours_appear():
    for path in SOURCES + [WEB / "index.html"]:
        source = read(path)
        assert {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", source)} <= COLOURS, path
        assert all(v.strip().startswith("34 51 84") for v in re.findall(r"rgba?\(([^)]*)\)", source)), path
        assert not re.search(r"hsl|oklch|gradient|box-shadow|text-shadow", source), path
        assert not re.search(rf":\s*({NAMED})\s*[;}}]", source), path


def test_green_is_used_only_for_a_yes():
    css = read(WEB / "src" / "index.css")
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*var\(--green\)[^{}]*)\}", css):
        for part in selector.split(","):
            assert re.search(r"\.yes\b", part), part


def test_none_of_the_five_banned_words_in_the_apps_own_text():
    assert banned.WORDS == ("safe", "verified", "trusted", "guaranteed", "protected")
    for path in APP_TEXT:
        if path.name == "banned.py":
            continue
        assert not re.search(rf"\b({'|'.join(banned.WORDS)})\b", read(path), re.I), path


def test_no_shopify_logo_colours_or_wordmark():
    assert not (WEB / "public").exists()
    assert not [p for p in (WEB / "src").rglob("*") if p.suffix in {".svg", ".png", ".jpg", ".ico", ".webp"}]
    mentions = []
    for path in SOURCES + [WEB / "index.html"]:
        source = read(path)
        assert not re.search(r"<img|<svg|background-image|95bf47|5e8e3e|008060|004c3f|96bf48", source, re.I), path
        mentions += [line.strip() for line in source.splitlines() if "shopify" in line.lower()]
    assert len(mentions) == 3
    assert sum("Not affiliated with Shopify" in line for line in mentions) == 1
    assert sum("in your Shopify admin" in line for line in mentions) == 2


def test_no_status_text_is_hardcoded_in_the_web_app():
    statuses = ["pending", "yes", "assistant_only_yes", "no", "doesnt_say"]
    pages = ["yes", "no", "doesnt_say", "unreadable", "pending"]
    wording = {texts.status_text(s, p) for s, p in itertools.product(statuses, pages)}
    wording |= {texts.STILL_READING, texts.COULD_NOT_READ, "Not found on its pages", "Meets all 3"}
    wording |= {"Says no to", "not answered on its pages", "That is not a yes", "Not checked"}
    wording |= {texts.pages_text("doesnt_say", False, None)}
    wording -= {"Yes", "No"}
    for path in SOURCES:
        source = read(path)
        for phrase in wording:
            assert phrase not in source, (path.name, phrase)
        assert not re.search(r"""['">]\s*(Yes|No)\s*['"<]""", source), path


def test_nothing_looks_like_a_product_grid_or_a_chat_thread():
    for path in SOURCES:
        source = read(path).lower()
        assert not re.search(r"avatar|typing|add to cart|rating|badge|★|⭐|sale-tag|carousel|imessage", source), path
    css = read(WEB / "src" / "index.css")
    assert len(set(re.findall(r"font-weight:\s*(\w+)", css)) | {"400"}) == 2
    assert len(re.findall(r"font(?:-family)?:[^;]*sans-serif", css)) == 1
    assert not re.search(r"Iowan|Palatino|Georgia|[^-]serif", css)
    assert not re.search(r"border-(left|right)[^;]*var\(--(green|navy)\)", css)
