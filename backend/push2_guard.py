"""Persisted, source-scoped Push2 request budget and refusal circuit breaker.

Independent local implementation; stores no URLs, payloads or user data. SQLite
transactions reserve budget before I/O across processes. Datacenter is isolated.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

DAILY_LIMIT = 500
REFUSAL_COOLDOWN = 3600
FAILURE_COOLDOWN = 300
FAILURE_THRESHOLD = 3


class Push2Blocked(RuntimeError):
    """No further request may be sent to this source yet."""


def applies(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(re.fullmatch(r"(?:(?:[0-9]+\.)?push2|push2delay|push2ex)\.eastmoney\.com", host))


def _path() -> Path:
    root = os.environ.get("VR_DATA_DIR", "").strip()
    return (Path(root) if root else Path.home() / ".vibe-research") / "push2_guard.sqlite3"


def _update(*, reserve: bool, outcome: str | None = None) -> None:
    now = time.time()
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    conn = None
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=1)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS guard (id INTEGER PRIMARY KEY CHECK(id=1), day TEXT NOT NULL, used INTEGER NOT NULL, failures INTEGER NOT NULL, blocked_until REAL NOT NULL)")
        row = conn.execute("SELECT day, used, failures, blocked_until FROM guard WHERE id=1").fetchone()
        old_day, used, failures, until = row or (day, 0, 0, 0.0)
        if (type(used) is not int or used < 0 or type(failures) is not int
                or failures < 0 or not isinstance(until, (int, float))
                or not math.isfinite(until) or until < 0
                or not isinstance(old_day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", old_day)):
            raise Push2Blocked("Push2 safety state is invalid")
        if old_day != day:
            used = 0
        if reserve:
            if now < until:
                raise Push2Blocked("Push2 source cooldown is active")
            if used >= DAILY_LIMIT:
                raise Push2Blocked("Push2 daily request budget exhausted")
            used += 1
        elif outcome == "refusal":
            until = max(until, now + REFUSAL_COOLDOWN)
        elif outcome == "failure":
            failures += 1
            if failures >= FAILURE_THRESHOLD:
                until = max(until, now + FAILURE_COOLDOWN)
                failures = 0
        elif outcome == "success":
            failures = 0
        conn.execute("INSERT OR REPLACE INTO guard VALUES (1, ?, ?, ?, ?)", (day, used, failures, until))
        conn.commit()
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        raise Push2Blocked("Push2 safety state is unavailable") from exc
    finally:
        if conn is not None:
            conn.close()


def reserve() -> None:
    _update(reserve=True)


def record(outcome: str) -> None:
    _update(reserve=False, outcome=outcome)
