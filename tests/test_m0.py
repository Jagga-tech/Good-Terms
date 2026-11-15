import json
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app

ROOT = Path(__file__).resolve().parent.parent
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}|shp(at|ss|ca|pa)_[A-Za-z0-9]{10,}")


def tracked():
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def test_health():
    assert TestClient(app).get("/api/health").json() == {"ok": True}


def test_profile_declares_what_the_plan_lists():
    ucp = json.loads((ROOT / "docs" / "agent-profile.json").read_text())["ucp"]
    assert ucp["version"] == "2026-08-25"
    assert ucp["payment_handlers"] == {}
    assert {"dev.ucp.shopping", "dev.ucp.common"} <= set(ucp["services"])
    for name in (
        "dev.shopify.catalog.global",
        "dev.shopify.catalog",
        "dev.ucp.shopping.cart",
        "dev.ucp.shopping.checkout",
        "dev.ucp.common.ask",
    ):
        assert ucp["capabilities"][name][0]["version"] == "2026-08-25"


def test_env_is_ignored_and_example_is_empty():
    assert ".env" not in tracked()
    assert ".env" in (ROOT / ".gitignore").read_text().split()
    for line in (ROOT / ".env.example").read_text().split():
        assert line.endswith("=")


def test_no_secret_in_tracked_files():
    for name in tracked():
        path = ROOT / name
        if path.suffix in {".pdf", ".png", ".lock"} or not path.is_file():
            continue
        assert not SECRET.search(path.read_text(errors="ignore")), name
