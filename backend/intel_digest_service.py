"""Service layer for Intel Daily Digest logic.

URL normalization, fingerprint computation, Asia/Shanghai date processing,
metadata derivation, and persistence coordination.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import zoneinfo
from datetime import datetime
from pathlib import Path
from typing import Any

import intel_digest_store as store

TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "spm",
        "from",
        "ref",
        "fbclid",
        "gclid",
        "v",
        "_hsenc",
        "_hsmi",
        "mkt_tok",
    }
)

SECTOR_NAME_MAP = {
    "ai": "AI 人工智能",
    "semiconductor": "半导体 / 芯片",
    "robotics": "机器人 / 具身智能",
    "newenergy": "新能源 / 电池",
    "biotech": "生物医药 / 医疗",
    "lowsky": "低空经济 / 飞行汽车",
    "consumer": "大消费 / 零售",
    "macro": "全球宏观 / 财报",
    "computing": "算力 / 数据中心",
    "automotive": "智能汽车 / 自动驾驶",
    "quantum": "量子科技 / 前沿",
    "space": "商业航天 / 卫星",
}


def normalize_url(raw_url: str) -> str:
    """
    Normalize URL per spec section IX:
    - Scheme and hostname lowercase
    - Path casing preserved
    - Fragment removed
    - Common tracking parameters removed
    - Default port normalized (http 80, https 443 removed)
    - Non-default port preserved
    - Query parameters deterministically sorted
    - NO url.rstrip(":")
    """
    if not raw_url:
        return ""
    stripped = raw_url.strip()
    if not stripped:
        return ""

    parts = urllib.parse.urlsplit(stripped)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    if ":" in netloc:
        host, port_str = netloc.split(":", 1)
        if (scheme == "http" and port_str == "80") or (
            scheme == "https" and port_str == "443"
        ):
            netloc = host

    path = parts.path  # preserve path casing

    query_params = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS]
    filtered.sort(key=lambda x: (x[0], x[1]))
    new_query = urllib.parse.urlencode(filtered)

    return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))


def compute_input_fingerprint(
    sector_key: str, input_items: list[dict[str, Any]]
) -> str:
    """
    Compute input fingerprint per spec section VIII.

    Input includes: sector_key, news title, source, published_at, normalized URL, snippet.
    Input items are deterministically sorted so ordering variations produce identical fingerprint.
    """
    normalized_items = []
    for item in input_items:
        raw_url = (
            item.get("url")
            or item.get("source_url")
            or item.get("link")
            or ""
        )
        norm_url = normalize_url(str(raw_url))
        title = str(
            item.get("title") or item.get("zh") or item.get("headline") or ""
        ).strip()
        source = str(item.get("source") or "").strip()
        published_at = str(
            item.get("published_at")
            or item.get("time")
            or item.get("date")
            or ""
        ).strip()
        summary = str(
            item.get("summary") or item.get("snippet") or item.get("text") or ""
        ).strip()

        normalized_items.append(
            {
                "normalized_url": norm_url,
                "title": title,
                "published_at": published_at,
                "source": source,
                "summary": summary,
            }
        )

    # Deterministic sort
    normalized_items.sort(
        key=lambda x: (
            x["normalized_url"],
            x["title"],
            x["published_at"],
            x["source"],
            x["summary"],
        )
    )

    payload = {
        "sector_key": sector_key.strip(),
        "items": normalized_items,
    }
    raw_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


def get_shanghai_now() -> datetime:
    tz = zoneinfo.ZoneInfo("Asia/Shanghai")
    return datetime.now(tz)


def get_digest_date_shanghai() -> str:
    return get_shanghai_now().strftime("%Y-%m-%d")


def compute_digest_id(
    digest_date: str, sector_key: str, input_fingerprint: str
) -> str:
    raw = f"{digest_date}|{sector_key}|{input_fingerprint}"
    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"idg_{hashed}"


def save_digest(
    sector_key: str,
    status: str,
    summary_text: str,
    source_refs: list[Any] | dict[str, Any] | str,
    input_items: list[dict[str, Any]],
    sector_name: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """
    Save intel digest with derived authoritative fields.

    Only 'normal' and 'partial' status are persisted.
    If status is 'unavailable', returns (None, False).
    """
    if status not in ("normal", "partial"):
        return None, False

    now_shanghai = get_shanghai_now()
    digest_date = now_shanghai.strftime("%Y-%m-%d")
    iso_now = now_shanghai.isoformat()

    resolved_sector_name = (
        sector_name.strip()
        if sector_name and sector_name.strip()
        else SECTOR_NAME_MAP.get(sector_key, sector_key)
    )
    input_fp = compute_input_fingerprint(sector_key, input_items)
    digest_id = compute_digest_id(digest_date, sector_key, input_fp)

    record = {
        "digest_id": digest_id,
        "digest_date": digest_date,
        "sector_key": sector_key,
        "sector_name": resolved_sector_name,
        "status": status,
        "summary_text": summary_text,
        "source_refs": source_refs,
        "input_fingerprint": input_fp,
        "generated_at": iso_now,
        "created_at": iso_now,
    }

    return store.save_intel_digest(record, db_path=db_path)


def get_latest_digest(
    sector_key: str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    return store.get_latest_intel_digest(sector_key, db_path=db_path)


def get_digest_by_date(
    sector_key: str, digest_date: str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    return store.get_intel_digest_by_date(
        sector_key, digest_date, db_path=db_path
    )
