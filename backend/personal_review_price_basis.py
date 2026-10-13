"""Offline adapter for explicit provider factor captures pinned to immutable bars.

Captures are public-market research inputs, never trade/account records. Content
hashes prove captured bytes and binding, not that a vendor's economics is correct.
No fetches, background ingestion, model use, or implicit write on read.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import re
from personal_review_snapshot import Snapshot
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import research_data_plane as rdp
import trade_calendar


class BasisError(ValueError):
    pass


class FactorRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    factor: float = Field(gt=0, allow_inf_nan=False)
    provider_revision: str = Field(min_length=1, max_length=120)
    adjustment_basis_id: str = Field(min_length=1, max_length=120)


class Capture(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["personal-review-adjustment-capture.v1"]
    code: str = Field(pattern=r"^\d{6}$")
    raw_snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_id: str = Field(min_length=1, max_length=120)
    provider_revision: str = Field(min_length=1, max_length=120)
    adjustment_basis_id: str = Field(min_length=1, max_length=120)
    formula: Literal["ADJUSTED_PRICE_EQUALS_RAW_TIMES_FACTOR"]
    price_unit: Literal["CNY_PER_SHARE"]
    source_id: str = Field(min_length=1, max_length=200)
    captured_at: str = Field(max_length=40)
    rows: list[FactorRow] = Field(min_length=1, max_length=1000)


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    raw_json: str = Field(min_length=2, max_length=1000000)


def _path():
    return Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research") / "personal_review_price_basis.sqlite3"


def _now():
    return datetime.now(timezone.utc)


def current_snapshot():
    """Pin already archived current generation without RDP's legacy auto-archive."""
    try:
        raw = json.loads(rdp._manifest_path(rdp.resolve_root()).read_text(encoding="utf8"))
        snapshot_id = hashlib.sha256(rdp._canonical_bytes(raw)).hexdigest()
        return rdp.read_manifest(snapshot_id=snapshot_id)
    except (OSError, ValueError, rdp.ResearchDataPlaneError) as exc:
        raise BasisError("本地价格快照未归档或无法核验") from exc


def qualify(raw_json):
    if not isinstance(raw_json, str) or len(raw_json.encode("utf8")) > 1000000:
        raise BasisError("因子采集超过字节上限")
    def duplicate_guard(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise BasisError("因子采集含重复字段")
            data[key] = value
        return data
    try:
        capture = Capture.model_validate(json.loads(raw_json, object_pairs_hook=duplicate_guard))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:0\d|1[0-3]):[0-5]\d|[+-]14:00)", capture.captured_at):
            raise BasisError("采集时间格式或时区偏移非法")
        timestamp = datetime.fromisoformat(capture.captured_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > _now():
            raise BasisError("采集时间未知或来自未来")
        manifest = rdp.read_manifest(snapshot_id=capture.raw_snapshot_id)
        if manifest["artifact_sha256"] != capture.raw_artifact_sha256 or manifest["provider_id"] != capture.provider_id:
            raise BasisError("原始价格快照或供应商身份不匹配")
        dates = [r.trade_date for r in capture.rows]
        calendar = trade_calendar._load_calendar()
        if not calendar or dates != sorted(set(dates)) or dates[0] not in calendar or dates[-1] not in calendar:
            raise BasisError("因子日期无序、重复或交易日历未知")
        if dates != [d for d in calendar if dates[0] <= d <= dates[-1]]:
            raise BasisError("因子交易会话覆盖不完整")
        if any(r.provider_revision != capture.provider_revision or r.adjustment_basis_id != capture.adjustment_basis_id for r in capture.rows):
            raise BasisError("因子不属于同一供应商版本和调整基准")
        prices = rdp.query_daily_bars(snapshot_id=capture.raw_snapshot_id, code=capture.code, date_from=dates[0], date_to=dates[-1], limit=1000)
        if [r["trade_date"] for r in prices["rows"]] != dates:
            raise BasisError("原始价格与因子覆盖不一致（停牌或缺失不可补齐）")
        for row, factor in zip(prices["rows"], capture.rows):
            if not math.isfinite(row["volume"]) or row["volume"] <= 0:
                raise BasisError("停牌或零成交会话不可推定价格覆盖")
            for key in ("open", "high", "low", "close"):
                derived = row[key] * factor.factor
                if not math.isfinite(derived) or derived <= 0:
                    raise BasisError("调整后价格不可表示")
        digest = hashlib.sha256(raw_json.encode("utf8")).hexdigest()
        return capture, prices, {"capture_sha256": digest, "code": capture.code, "provider_id": capture.provider_id,
            "provider_revision": capture.provider_revision, "adjustment_basis_id": capture.adjustment_basis_id,
            "raw_snapshot_id": capture.raw_snapshot_id, "raw_artifact_sha256": capture.raw_artifact_sha256,
            "captured_at": capture.captured_at, "from": dates[0], "through": dates[-1], "sessions": len(dates),
            "evidence_status": "PROVIDER_ASSERTED_ARCHIVED_RESEARCH_NOT_PIT_OR_TOTAL_RETURN"}
    except (ValueError, KeyError, TypeError, rdp.ResearchDataPlaneError) as exc:
        if isinstance(exc, BasisError):
            raise
        raise BasisError("价格因子采集格式、绑定或数值无法核验") from exc


def archive(raw_json):
    capture, _, receipt = qualify(raw_json)
    path = _path()
    Snapshot(path)  # Deny unsafe links/active journals before an explicit append.
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS captures (digest TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, raw_json TEXT NOT NULL, archived_at TEXT NOT NULL)")
            identity = json.dumps([capture.code, capture.provider_id, capture.provider_revision, capture.adjustment_basis_id, capture.raw_snapshot_id])
            prior = conn.execute("SELECT digest FROM captures WHERE identity=?", (identity,)).fetchone()
            if prior and prior[0] != receipt["capture_sha256"]:
                raise BasisError("同一采集版本的内容冲突，不覆盖历史")
            if not prior and (conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] >= 1000 or path.stat().st_size > 60 * 1024 * 1024):
                raise BasisError("因子归档条数或存储已达安全上限")
            conn.execute("INSERT OR IGNORE INTO captures VALUES (?,?,?,?)", (receipt["capture_sha256"], identity, raw_json, _now().isoformat()))
        return receipt
    except sqlite3.Error as exc:
        raise BasisError("因子归档不可写入，未修改价格或流水") from exc


def find(snapshot_id, code, start, end):
    try:
        source = Snapshot(_path())
        if source.source is None:
            return None
        entries = source.read(lambda conn: conn.execute("SELECT digest, raw_json, archived_at FROM captures ORDER BY archived_at DESC, digest LIMIT 1001").fetchall(), [])
        if len(entries) > 1000:
            raise BasisError("因子归档条数超过安全范围")
        for digest, raw, archived in entries:
            if len(raw.encode("utf8")) > 1000000:
                raise BasisError("因子采集超过字节上限")
            if hashlib.sha256(raw.encode("utf8")).hexdigest() != digest:
                raise BasisError("因子采集哈希不匹配")
            # Validate stored bytes before trusting any filtering fields.
            capture = Capture.model_validate_json(raw)
            if capture.raw_snapshot_id != snapshot_id or capture.code != code or capture.rows[0].trade_date > start or capture.rows[-1].trade_date < end:
                continue
            verified, prices, receipt = qualify(raw)
            source.assert_unchanged()
            return verified, prices, {**receipt, "archived_at": archived}
        source.assert_unchanged()
        return None
    except Exception as exc:
        raise BasisError("因子归档不可安全读取") from exc


def bounded_excursion(episode, snapshot_id):
    """First-entry executed-price reference; only simple complete buy/sell pairs."""
    if not episode["simple_round_trip"]:
        return None
    shanghai = timezone(timedelta(hours=8))
    start = datetime.fromisoformat(episode["opened_at"]).astimezone(shanghai).date().isoformat()
    end = datetime.fromisoformat(episode["closed_at"]).astimezone(shanghai).date().isoformat()
    selected = find(snapshot_id, episode["code"], start, end)
    if selected is None:
        return None
    capture, prices, receipt = selected
    factors = {r.trade_date: r.factor for r in capture.rows}
    reference = episode["entry_price"] * factors[start]
    interior = [(r, factors[r["trade_date"]]) for r in prices["rows"] if start < r["trade_date"] < end]
    if not interior or not math.isfinite(reference) or reference <= 0:
        return None
    high = max(r["high"] * factor for r, factor in interior)
    low = min(r["low"] * factor for r, factor in interior)
    favorable, adverse = max(0.0, (high / reference - 1) * 100), min(0.0, (low / reference - 1) * 100)
    if not all(math.isfinite(v) for v in (favorable, adverse)):
        raise BasisError("调整后区间幅度不可表示")
    return {"state": "INTERIOR_DAILY_ADJUSTED_BOUND", "bounded_mfe_pct": round(favorable, 4), "bounded_mae_pct": round(adverse, 4),
        "reference": "FIRST_ENTRY_EXECUTED_PRICE_TIMES_SAME_CAPTURE_FACTOR", "adjusted_entry_reference": reference,
        "interior_sessions": len(interior), "coverage_from": start, "coverage_through": end,
        "excluded_boundary_dates": [start, end], "source": receipt,
        "limitations": "仅内部完整日线的有利/不利幅度下界；不含首尾交易日，不是精确持有期MFE/MAE、可成交价、总回报、真实交易验证或PIT事实。"}


def receipt(digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise BasisError("采集哈希格式错误")
    source = Snapshot(_path())
    row = source.read(lambda conn: conn.execute("SELECT raw_json,archived_at FROM captures WHERE digest=?", (digest,)).fetchone(), None)
    if row is None:
        return None
    raw, archived = row
    if len(raw.encode("utf8")) > 1000000 or hashlib.sha256(raw.encode("utf8")).hexdigest() != digest:
        raise BasisError("因子采集哈希或大小无法核验")
    result = qualify(raw)[2]
    source.assert_unchanged()
    return {**result, "archived_at": archived}
