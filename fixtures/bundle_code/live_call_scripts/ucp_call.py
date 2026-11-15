import json
import subprocess
import sys

UA = "terms-check-research/0.1"


def rpc(endpoint, method, params, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "id": rid, "params": params})
    r = subprocess.run(
        ["curl", "-sS", "-m", "60", "-A", UA, "-H", "Content-Type: application/json", "-H", "Accept: application/json, text/event-stream",
         "-w", "\n%{http_code}", "-X", "POST", "--data", body, endpoint],
        capture_output=True, text=True)
    out, _, code = r.stdout.rpartition("\n")
    text = out
    if out.lstrip().startswith("event:") or "\ndata:" in out or out.startswith("data:"):
        lines = [l[5:].strip() for l in out.splitlines() if l.startswith("data:")]
        text = lines[-1] if lines else out
    try:
        return code, json.loads(text)
    except Exception:
        return code, {"raw": out[:600], "err": r.stderr[:300]}


if __name__ == "__main__":
    endpoint = sys.argv[1]
    for profile in sys.argv[2:]:
        code, res = rpc(endpoint, "tools/list", {"arguments": {"meta": {"ucp-agent": {"profile": profile}}}})
        tools = [t.get("name") for t in res.get("result", {}).get("tools", [])] if isinstance(res, dict) else []
        print(profile.split("agent-profiles/")[-1], "->", code, tools if tools else json.dumps(res)[:500])
