import json
import subprocess
import sys

UA = "terms-check-research/0.1"
STORES = sys.argv[1:]


def fetch(url):
    r = subprocess.run(["curl", "-sS", "-L", "-m", "25", "-A", UA, "-w", "\n%{http_code}", url], capture_output=True, text=True)
    body, _, code = r.stdout.rpartition("\n")
    return code, body


for s in STORES:
    for suffix in ["", "/draft"]:
        url = f"https://{s}/.well-known/ucp{suffix}"
        code, body = fetch(url)
        try:
            d = json.loads(body)["ucp"]
        except Exception:
            print(s, suffix or "/", code, "no profile")
            continue
        caps = sorted(d.get("capabilities", {}).keys())
        eps = sorted({e.get("endpoint") for v in d.get("services", {}).values() for e in v if e.get("endpoint")})
        print(s, suffix or "/", code, "version", d.get("version"))
        print("   ask:", "dev.ucp.common.ask" in caps, "| caps:", ", ".join(c.replace("dev.ucp.", "").replace("dev.shopify.", "shopify:") for c in caps))
        print("   endpoints:", eps)
