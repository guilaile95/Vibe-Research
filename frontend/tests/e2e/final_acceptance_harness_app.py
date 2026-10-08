"""Isolated production upload/history/calendar routes, no schedulers or providers.

Required paths are all beneath VR_FINAL_FIXTURE_ROOT. Outbound connects,
subprocesses and writes outside that temporary root are rejected and recorded.
The browser checks the guard receipt so caught exceptions cannot hide a call.
"""
from __future__ import annotations
import os
import sys
import json
import socket
from pathlib import Path
from contextlib import asynccontextmanager, closing
from urllib.parse import urlsplit
from urllib.request import url2pathname

ROOT = Path(os.environ["VR_FINAL_FIXTURE_ROOT"]).resolve()
assert ROOT.is_dir()
required = ["VR_DATA_DIR", "VR_REPORTS_DIR", "VIBE_RESEARCH_REVIEW_DB", "VIBE_RESEARCH_CAMPAIGN_DB", "VIBE_RESEARCH_EVIDENCE_THESIS_DB", "HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP"]
for key in required:
    assert Path(os.environ[key]).resolve().is_relative_to(ROOT), key
assert os.environ.get("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH") == "1"
assert not os.environ.get("VR_API_KEY")
violations: list[str] = []
requests_seen: list[str] = []

def reject(kind: str):
    violations.append(kind)
    raise RuntimeError(f"Forbidden fixture operation: {kind}")

def inside(path) -> bool:
    if isinstance(path, int):
        return True
    if path in (None, ":memory:"):
        return True
    try:
        return Path(os.fsdecode(path)).resolve().is_relative_to(ROOT)
    except (TypeError, ValueError):
        return False

def sqlite_inside(path) -> bool:
    # SQLite file: URIs name the decoded file, not a literal relative "file:"
    # directory. Permit only production's read-only URI form; other URI modes
    # or remote authorities fail closed before SQLite opens anything.
    raw = os.fsdecode(path)
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return False
    if raw.startswith("file:"):
        uri = urlsplit(raw)
        if uri.netloc or uri.query != "mode=ro" or uri.fragment:
            return False
        decoded = Path(url2pathname(uri.path))
        return decoded.is_absolute() and inside(decoded)
    return inside(path)

def audit(event, args):
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and not inside(path): reject("write_outside_fixture")
    elif event == "sqlite3.connect" and not sqlite_inside(args[0]):
        reject("sqlite_outside_fixture")
    elif event in ("os.remove", "os.rmdir", "os.mkdir") and not inside(args[0]):
        reject("filesystem_outside_fixture")
    elif event in ("os.rename", "os.link", "os.symlink") and any(not inside(p) for p in args[:2]):
        reject("filesystem_outside_fixture")
    elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex") and args[0] not in (None, "localhost", "127.0.0.1", "::1"):
        reject("external_dns")
    elif event in ("socket.connect", "socket.sendto", "socket.sendmsg", "subprocess.Popen", "os.system"):
        reject(event)

# Windows implements event-loop wakeup with a loopback socketpair. Acquire the
# verification-only loop before installing the guard and before importing any
# product code; TestClient reuses it, while all later connects remain forbidden.
# The Linux browser/uvicorn path never takes this initialization branch.
verification_loop = None
if __name__ == "__main__" and sys.platform == "win32":
    import asyncio
    verification_loop = asyncio.SelectorEventLoop()

sys.addaudithook(audit)
socket.create_connection = lambda *a, **k: reject("socket.create_connection")
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
# Runtime source discovery is irrelevant to these route contracts and otherwise
# shells out to git during app import; keep that optional boundary inert.
import runtime_info_router
runtime_info_router._git_snapshot = lambda _path: (None, "unknown")
import app as product
import review_store
from fastapi.responses import JSONResponse

@asynccontextmanager
async def isolated_lifespan(_app):
    yield

app = product.app
app.router.lifespan_context = isolated_lifespan
review_path = Path(os.environ["VIBE_RESEARCH_REVIEW_DB"])
seeds = []
for date in ("2026-09-05", "2026-09-06"):
    seeds.append(review_store.save_daily_review_snapshot({
        "schema_version": "daily-review-v0.1", "trade_date": date,
        "generated_at": date + " 16:00:00", "data_cutoff": date,
        "status": "normal", "warnings": ["SYNTHETIC_HISTORY"],
    }, review_path))

ALLOWED = {("GET", "/api/health"), ("GET", "/api/myreports"), ("POST", "/api/myreports"),
           ("GET", "/api/daily-review/history"), ("GET", "/api/research-events"), ("GET", "/api/e2e/final-audit")}
@app.middleware("http")
async def whitelist(request, call_next):
    key = (request.method, request.url.path)
    requests_seen.append(f"{key[0]} {key[1]}")
    if key not in ALLOWED:
        violations.append("unexpected_http")
        return JSONResponse({"detail": "UNEXPECTED_FIXTURE_HTTP"}, status_code=503)
    return await call_next(request)

@app.get("/api/e2e/final-audit")
def receipt():
    return {"violations": violations, "requests": requests_seen, "seed_count": len(seeds),
            "lifespan": "isolated_no_scheduler", "reports_root_isolated": product.mr.REPORTS_DIR.resolve().is_relative_to(ROOT)}

if __name__ == "__main__":
    assert sys.argv[1:] == ["--verify-fixture"]
    import base64
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="http://127.0.0.1", backend_options={"loop_factory": lambda: verification_loop} if verification_loop is not None else {}) as client:
        first = client.post("/api/myreports", json={"name": "synthetic-first.txt", "content_b64": base64.b64encode(b"SYNTHETIC_FIRST_BYTES").decode()})
        assert first.status_code == 200, first.text
        rejected = client.post("/api/myreports", json={"name": "synthetic-rejected.html", "content_b64": base64.b64encode(b"SYNTHETIC_REJECTED_BYTES").decode()})
        assert rejected.status_code == 400, rejected.text
        assert len(client.get("/api/myreports").json()["data"]) == 1
        history = client.get("/api/daily-review/history?trade_date=2026-09-06&limit=20&offset=0")
        assert history.status_code == 200 and history.json()["data"]["items"][0]["trade_date"] == "2026-09-06"
        calendar = client.get("/api/research-events")
        assert calendar.status_code == 200 and calendar.json()["data"]["universe"]["status"] == "EMPTY", calendar.text
        assert client.get("/api/research-events?date_from=2000-01-01&date_to=2000-01-02").status_code == 422
        assert not violations, violations
    if verification_loop is not None:
        assert verification_loop.is_closed(), "TestClient must close its preinitialized loop"
    import sqlite3
    # Exercise URI normalization on every OS, independently of upload indexing.
    with closing(sqlite3.connect(f"{review_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
    assert sqlite_inside(review_path.resolve().as_uri() + "?mode=ro")
    for uri in ("file://example.invalid/fixture.db?mode=ro", "file:relative.db?mode=ro", review_path.resolve().as_uri() + "?mode=rw", review_path.resolve().as_uri() + "?mode=ro&vfs=custom", *(review_path.resolve().as_uri().replace("review.db", "re" + control + "view.db") + "?mode=ro" for control in ("\t", "\n", "\r", "\x00", "\x7f"))):
        assert not sqlite_inside(uri), uri
    assert not violations, violations
    # Explicit guard probes run only in this verification subprocess, never the
    # browser harness. Preserve their count rather than silently clearing it.
    for action in (lambda: socket.create_connection(("example.invalid", 80)), lambda: open(ROOT.parent / "forbidden-probe", "w"), lambda: socket.getaddrinfo("example.invalid", 80), lambda: sqlite3.connect(f"{(ROOT.parent / 'forbidden-probe.db').as_uri()}?mode=ro", uri=True)):
        try: action()
        except RuntimeError: pass
        else: raise AssertionError("guard probe did not fail closed")
    assert violations == ["socket.create_connection", "write_outside_fixture", "external_dns", "sqlite_outside_fixture"], violations
    print(json.dumps({"result": "PASS", "actual_routes": ["upload", "history", "calendar"], "expected_guard_probes": violations}))
