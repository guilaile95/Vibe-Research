"""11 个只读数据健康 Adapter。

禁止：联网、写文件、初始化 schema、触发业务刷新。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

import data_health_event_store as event_store
import data_health_service as svc

_REQUIRED_RECORD_KEYS = frozenset({
    "source_id",
    "module",
    "display_name",
    "status",
    "is_stale",
    "observed_at",
    "last_success_at",
    "data_trade_date",
    "data_cutoff",
    "stale_after_seconds",
    "is_cached",
    "is_degraded",
    "coverage_current",
    "coverage_expected",
    "last_error_code",
    "last_error_summary",
    "last_error_at",
    "blocks_advice",
    "block_reason",
    "detail_path",
})

# AdapterReadError 只允许这四个稳定公开错误码
_ALLOWED_ADAPTER_ERROR_CODES = frozenset({
    "SOURCE_UNAVAILABLE",
    "SOURCE_CORRUPTED",
    "SOURCE_SCHEMA_INCOMPATIBLE",
    "SOURCE_TIMEOUT",
})

# last_error_code 允许的稳定公开错误码集合（含 None 与初始化码）
_ALLOWED_RECORD_ERROR_CODES = frozenset({
    "SOURCE_NOT_INITIALIZED",
    "SOURCE_STALE",
    "SOURCE_PARTIAL",
    "SOURCE_UNAVAILABLE",
    "SOURCE_CORRUPTED",
    "SOURCE_SCHEMA_INCOMPATIBLE",
    "SOURCE_TIMEOUT",
    "SOURCE_DEGRADED",
    "NO_HOLDINGS",
    "HOLDING_QUOTES_UNAVAILABLE",
    "MARKET_BREADTH_UNAVAILABLE",
    "REVIEW_TRADE_DATE_UNAVAILABLE",
})

# 规范 UTC：YYYY-MM-DDTHH:MM:SS.ffffffZ
_CANONICAL_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
# 仅日期：YYYY-MM-DD
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AdapterReadError(Exception):
    """可预期的单 Adapter 读取失败（仅此异常由聚合层隔离为 unavailable）。

    仅允许四种稳定公开错误码：SOURCE_UNAVAILABLE / SOURCE_CORRUPTED /
    SOURCE_SCHEMA_INCOMPATIBLE / SOURCE_TIMEOUT。其它错误码视为编程错误。
    """

    def __init__(self, error_code: str = "SOURCE_UNAVAILABLE"):
        if error_code not in _ALLOWED_ADAPTER_ERROR_CODES:
            raise ValueError(
                f"illegal AdapterReadError code: {error_code!r}; "
                "must be one of SOURCE_UNAVAILABLE/SOURCE_CORRUPTED/"
                "SOURCE_SCHEMA_INCOMPATIBLE/SOURCE_TIMEOUT"
            )
        super().__init__(error_code)
        self.error_code = error_code


@dataclass
class HealthReadContext:
    now_utc: datetime
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    events_load_error: str | None = None  # SOURCE_CORRUPTED when event file unreadable


class DataHealthAdapter(Protocol):
    source_id: str
    module: str
    display_name: str

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        ...


def _meta(source_id: str) -> dict[str, str]:
    for s in svc.SOURCE_REGISTRY:
        if s["source_id"] == source_id:
            return s
    return {"source_id": source_id, "module": source_id, "display_name": source_id}


def _is_strict_bool(v: Any) -> bool:
    """严格 bool：拒绝 0/1/None/其它类型。"""
    return isinstance(v, bool)


def _is_optional_bool(v: Any) -> bool:
    """bool 或 None；拒绝 0/1。"""
    return v is None or isinstance(v, bool)


def _is_canonical_utc_or_none(v: Any) -> bool:
    if v is None:
        return True
    if not isinstance(v, str):
        return False
    return bool(_CANONICAL_UTC_RE.match(v))


def _is_date_only_or_none(v: Any) -> bool:
    if v is None:
        return True
    if not isinstance(v, str):
        return False
    return bool(_DATE_ONLY_RE.match(v))


def _is_non_negative_int_or_none(v: Any) -> bool:
    """非负 int 或 None；bool 不得当作 int。"""
    if v is None:
        return True
    if isinstance(v, bool):
        return False
    if not isinstance(v, int):
        return False
    return v >= 0


def validate_data_health_record(
    adapter: "DataHealthAdapter",
    record: Any,
) -> svc.DataHealthRecord:
    """严格校验 DataHealthRecord。

    校验失败抛 RuntimeError，由聚合层映射为 HTTP 500（不进入响应体）。
    """
    if not isinstance(record, dict):
        raise RuntimeError("invalid DataHealthRecord: not a mapping")

    # 1. 字段集合精确相等
    if set(record.keys()) != _REQUIRED_RECORD_KEYS:
        missing = _REQUIRED_RECORD_KEYS - set(record.keys())
        extra = set(record.keys()) - _REQUIRED_RECORD_KEYS
        raise RuntimeError(
            "invalid DataHealthRecord: keys mismatch "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )

    # 2. source_id 与 adapter 一致
    sid = record["source_id"]
    if not isinstance(sid, str) or sid != adapter.source_id:
        raise RuntimeError("invalid DataHealthRecord: source_id mismatch")

    # 3. source_id 必须在注册表
    if sid not in svc.REGISTERED_SOURCE_IDS:
        raise RuntimeError("invalid DataHealthRecord: source_id not in registry")

    # 4. module / display_name 与注册表完全一致
    meta = _meta(sid)
    if record["module"] != meta["module"]:
        raise RuntimeError("invalid DataHealthRecord: module mismatch")
    if record["display_name"] != meta["display_name"]:
        raise RuntimeError("invalid DataHealthRecord: display_name mismatch")

    # 5. status 是三态之一
    status = record["status"]
    if status not in svc.VALID_STATUSES:
        raise RuntimeError("invalid DataHealthRecord: illegal status")

    # 6. is_stale / blocks_advice 必须是严格 bool
    if not _is_strict_bool(record["is_stale"]):
        raise RuntimeError("invalid DataHealthRecord: is_stale must be strict bool")
    if not _is_strict_bool(record["blocks_advice"]):
        raise RuntimeError("invalid DataHealthRecord: blocks_advice must be strict bool")

    # 7. is_cached / is_degraded 必须是 bool 或 null
    if not _is_optional_bool(record["is_cached"]):
        raise RuntimeError("invalid DataHealthRecord: is_cached must be bool or null")
    if not _is_optional_bool(record["is_degraded"]):
        raise RuntimeError("invalid DataHealthRecord: is_degraded must be bool or null")

    # 8. 时间字段必须是规范 UTC、date-only 或 null
    for key in ("observed_at", "last_success_at", "last_error_at"):
        if not _is_canonical_utc_or_none(record[key]):
            raise RuntimeError(f"invalid DataHealthRecord: {key} must be canonical UTC or null")
    for key in ("data_trade_date", "data_cutoff"):
        if not _is_date_only_or_none(record[key]):
            raise RuntimeError(f"invalid DataHealthRecord: {key} must be date-only or null")

    # 9. stale_after_seconds 必须是非负 int 或 null
    sas = record["stale_after_seconds"]
    if sas is not None:
        if isinstance(sas, bool) or not isinstance(sas, int) or sas < 0:
            raise RuntimeError("invalid DataHealthRecord: stale_after_seconds must be non-negative int or null")

    # 10. coverage 必须是非负 int 或 null，bool 不得当作 int
    cov_c = record["coverage_current"]
    cov_e = record["coverage_expected"]
    if not _is_non_negative_int_or_none(cov_c):
        raise RuntimeError("invalid DataHealthRecord: coverage_current must be non-negative int or null")
    if not _is_non_negative_int_or_none(cov_e):
        raise RuntimeError("invalid DataHealthRecord: coverage_expected must be non-negative int or null")
    # 两个 coverage 都存在时 current <= expected
    if cov_c is not None and cov_e is not None and cov_c > cov_e:
        raise RuntimeError("invalid DataHealthRecord: coverage_current > coverage_expected")

    # 11. last_error_code 必须是稳定公开错误码或 null
    code = record["last_error_code"]
    if code is not None:
        if not isinstance(code, str) or code not in _ALLOWED_RECORD_ERROR_CODES:
            raise RuntimeError("invalid DataHealthRecord: illegal last_error_code")

    # 12. last_error_summary 必须等于该错误码的安全映射
    expected_summary = svc.error_summary(code)
    if record["last_error_summary"] != expected_summary:
        raise RuntimeError("invalid DataHealthRecord: last_error_summary mismatch")

    # 13. detail_path 必须以 / 开头或为 null
    dp = record["detail_path"]
    if dp is not None:
        if not isinstance(dp, str) or not dp.startswith("/"):
            raise RuntimeError("invalid DataHealthRecord: detail_path must start with / or be null")

    # 14. Gate 不变量
    is_gate = sid == "portfolio_advice_gate"
    blocks = record["blocks_advice"]
    block_reason = record["block_reason"]
    if not is_gate:
        if blocks is not False:
            raise RuntimeError("invalid DataHealthRecord: non-gate blocks_advice must be false")
        if block_reason is not None:
            raise RuntimeError("invalid DataHealthRecord: non-gate block_reason must be null")
    else:
        if blocks is True:
            # blocks_advice=true 时必须是四项业务码
            if code not in svc.GATE_BUSINESS_CODES:
                raise RuntimeError("invalid DataHealthRecord: gate blocks_advice=true requires business code")
            # blocks_advice=true 时 block_reason 必须等于安全摘要
            if block_reason != svc.error_summary(code):
                raise RuntimeError("invalid DataHealthRecord: gate block_reason must equal safe summary")
        else:
            # blocks_advice=false 时 block_reason 必须为 null
            if block_reason is not None:
                raise RuntimeError("invalid DataHealthRecord: gate block_reason must be null when not blocking")

    return record  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# daily_review
# ---------------------------------------------------------------------------

class DailyReviewAdapter:
    source_id = "daily_review"
    module = "每日复盘"
    display_name = "每日复盘"

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        m = _meta(self.source_id)
        import daily_review as dr
        import daily_review_cache as drc

        review: dict | None = None
        cache_meta: dict | None = None
        saved_at: str | None = None
        source_kind: str | None = None

        # 先读有效内存结果（不触发 generate）
        mem = dr._cached_review()
        if isinstance(mem, dict):
            review = mem
            source_kind = "memory"
            cache_meta = {
                "source": "memory",
                "stale": False,
                "saved_at": None,
            }

        if review is None:
            try:
                disk_review, disk_saved = drc.load_latest_review()
            except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                raise AdapterReadError("SOURCE_CORRUPTED") from exc
            if disk_review is None:
                # 文件存在但 loader 拒绝 → 可能损坏
                path = drc.cache_path()
                if os.path.isfile(path):
                    return svc.unavailable_record(
                        m["source_id"], m["module"], m["display_name"],
                        "SOURCE_CORRUPTED",
                        detail_path="/daily-review",
                    )
                return svc.not_initialized_record(
                    m["source_id"], m["module"], m["display_name"],
                    detail_path="/daily-review",
                )
            review = disk_review
            saved_at = disk_saved
            source_kind = "persisted"
            cache_meta = {
                "source": "persisted",
                "stale": True,
                "saved_at": saved_at,
            }

        status = review.get("status")
        if status not in ("normal", "partial", "unavailable"):
            return svc.unavailable_record(
                m["source_id"], m["module"], m["display_name"],
                "SOURCE_CORRUPTED", detail_path="/daily-review",
            )

        trade_date = review.get("trade_date")
        if not isinstance(trade_date, str) or not trade_date.strip():
            trade_date = None
        else:
            trade_date = trade_date.strip()[:10]

        generated_at = review.get("generated_at")
        gen_dt = svc.parse_flexible_time(generated_at, naive_as="beijing")
        saved_dt = svc.parse_flexible_time(
            (cache_meta or {}).get("saved_at") or saved_at, naive_as="beijing"
        )
        basis = saved_dt or gen_dt
        observed_at = svc.format_utc(basis or gen_dt)

        # is_cached
        is_cached: bool | None
        if source_kind == "memory":
            is_cached = True
        elif source_kind == "persisted":
            is_cached = True
        else:
            is_cached = None

        # stale：权威 cache_meta.stale 优先
        is_stale = False
        if cache_meta and cache_meta.get("stale") is True:
            is_stale = True
        else:
            is_stale = svc.is_stale_cn_trade_date(
                trade_date, basis, context.now_utc, fallback_hours=36.0,
            )

        error_code = None
        if status == "unavailable":
            error_code = "SOURCE_UNAVAILABLE"
        elif status == "partial":
            error_code = "SOURCE_PARTIAL"

        # coverage from components
        health = review.get("data_health") if isinstance(review.get("data_health"), dict) else {}
        comps = health.get("components") if isinstance(health.get("components"), dict) else {}
        expected = len(comps) if comps else None
        current = None
        if comps:
            current = sum(1 for v in comps.values() if v == "normal")

        return svc.make_record(
            source_id=m["source_id"],
            module=m["module"],
            display_name=m["display_name"],
            status=status,  # type: ignore[arg-type]
            is_stale=is_stale,
            observed_at=observed_at,
            last_success_at=observed_at if status in ("normal", "partial") else None,
            data_trade_date=trade_date,
            data_cutoff=None,
            stale_after_seconds=None,
            is_cached=is_cached,
            is_degraded=None,
            coverage_current=current,
            coverage_expected=expected,
            last_error_code=error_code,
            last_error_at=None,
            blocks_advice=False,
            block_reason=None,
            detail_path="/daily-review",
        )


# ---------------------------------------------------------------------------
# event-based helpers
# ---------------------------------------------------------------------------

def _event_for(context: HealthReadContext, source_id: str) -> dict[str, Any] | None:
    if context.events_load_error:
        return None  # caller handles corruption
    return context.events.get(source_id)


def _corrupted_event_record(source_id: str) -> svc.DataHealthRecord:
    m = _meta(source_id)
    return svc.unavailable_record(
        m["source_id"], m["module"], m["display_name"],
        "SOURCE_CORRUPTED",
        detail_path=None,
    )


class EventSourceAdapter:
    """通用事件型 Adapter（非 gate）。"""

    source_id: str
    module: str
    display_name: str
    stale_after_seconds: int | None
    calendar_type: str
    detail_path: str | None = None
    force_null_coverage: bool = False

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        m = _meta(self.source_id)
        if context.events_load_error:
            return _corrupted_event_record(self.source_id)

        event = _event_for(context, self.source_id)
        status, code, is_degraded, ls, le, observed = svc.map_event_quality(event)

        is_stale = False
        basis = svc.parse_flexible_time(observed, naive_as="utc")
        thr = self.stale_after_seconds
        if thr is not None and basis is not None:
            if self.calendar_type == "CN_MARKET_CONSERVATIVE":
                is_stale = svc.is_stale_cn_intraday_observation(
                    basis, context.now_utc, stale_after_seconds=thr,
                )
            else:
                is_stale = svc.is_stale_continuous(basis, context.now_utc, thr)

        # is_cached / is_degraded for event sources without cache proof
        is_cached: bool | None = None
        if is_degraded is None and status in ("normal", "partial") and code not in (
            "SOURCE_PARTIAL", "SOURCE_DEGRADED",
        ):
            is_degraded = None

        cov_c = None if self.force_null_coverage else None
        cov_e = None if self.force_null_coverage else None

        return svc.make_record(
            source_id=m["source_id"],
            module=m["module"],
            display_name=m["display_name"],
            status=status,
            is_stale=is_stale if status != "unavailable" or basis is not None else False,
            observed_at=observed,
            last_success_at=ls,
            data_trade_date=None,
            data_cutoff=None,
            stale_after_seconds=thr,
            is_cached=is_cached,
            is_degraded=is_degraded,
            coverage_current=cov_c,
            coverage_expected=cov_e,
            last_error_code=code,
            last_error_at=le,
            blocks_advice=False,
            block_reason=None,
            detail_path=self.detail_path,
        )


class PortfolioQuotesAdapter(EventSourceAdapter):
    source_id = "portfolio_quotes"
    module = "持仓行情"
    display_name = "持仓行情覆盖"
    stale_after_seconds = 300
    calendar_type = "CN_MARKET_CONSERVATIVE"
    detail_path = "/portfolio"
    force_null_coverage = True


class QuotesAdapter(EventSourceAdapter):
    source_id = "quotes"
    module = "个股行情"
    display_name = "个股行情"
    stale_after_seconds = 300
    calendar_type = "CN_MARKET_CONSERVATIVE"
    detail_path = "/stock-data"
    force_null_coverage = True


class AnnouncementsAdapter(EventSourceAdapter):
    source_id = "announcements"
    module = "公告"
    display_name = "个股公告"
    stale_after_seconds = 86400
    calendar_type = "CONTINUOUS"
    detail_path = "/stock-data"
    force_null_coverage = True


class FinancialsAdapter(EventSourceAdapter):
    source_id = "financials"
    module = "财务"
    display_name = "财务数据"
    stale_after_seconds = 604800
    calendar_type = "REPORTING_PERIOD"
    detail_path = "/stock-data"
    force_null_coverage = True


class SectorResearchAdapter(EventSourceAdapter):
    source_id = "sector_research"
    module = "板块研究"
    display_name = "板块动态数据"
    stale_after_seconds = 86400
    calendar_type = "CONTINUOUS"
    detail_path = "/sectors"
    force_null_coverage = True


# ---------------------------------------------------------------------------
# portfolio_advice_gate
# ---------------------------------------------------------------------------

class PortfolioAdviceGateAdapter:
    source_id = "portfolio_advice_gate"
    module = "持仓建议"
    display_name = "持仓建议 Gate"

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        m = _meta(self.source_id)
        if context.events_load_error:
            rec = _corrupted_event_record(self.source_id)
            rec["detail_path"] = "/portfolio"
            return rec

        event = _event_for(context, self.source_id)
        status, blocks, reason, code, ls, le, observed = svc.map_gate_event(event)

        is_stale = False
        basis = svc.parse_flexible_time(observed, naive_as="utc")
        if basis is not None:
            if svc.is_stale_continuous(basis, context.now_utc, 300):
                is_stale = True
            else:
                # 依赖观察时间更新
                dep_times: list[datetime] = []
                # portfolio file mtime
                import portfolio as pf
                if os.path.isfile(pf.PF_FILE):
                    try:
                        mtime = datetime.fromtimestamp(
                            os.path.getmtime(pf.PF_FILE), tz=timezone.utc
                        )
                        dep_times.append(mtime)
                    except OSError:
                        pass
                # portfolio_quotes observed
                pq = context.events.get("portfolio_quotes") if not context.events_load_error else None
                if pq:
                    _, _, _, _, _, pq_obs = svc.map_event_quality(pq)
                    pq_dt = svc.parse_flexible_time(pq_obs, naive_as="utc")
                    if pq_dt:
                        dep_times.append(pq_dt)
                # daily_review observed — best effort readonly
                try:
                    dr_ad = DailyReviewAdapter()
                    dr_rec = dr_ad.read(context)
                    dr_dt = svc.parse_flexible_time(dr_rec.get("observed_at"), naive_as="utc")
                    if dr_dt:
                        dep_times.append(dr_dt)
                except AdapterReadError:
                    pass
                for dep in dep_times:
                    if dep > basis:
                        is_stale = True
                        break

        return svc.make_record(
            source_id=m["source_id"],
            module=m["module"],
            display_name=m["display_name"],
            status=status,
            is_stale=is_stale,
            observed_at=observed,
            last_success_at=ls,
            stale_after_seconds=300,
            is_cached=None,
            is_degraded=None,
            coverage_current=None,
            coverage_expected=None,
            last_error_code=code,
            last_error_at=le,
            blocks_advice=blocks,
            block_reason=reason,
            detail_path="/portfolio",
        )


# ---------------------------------------------------------------------------
# news_radar
# ---------------------------------------------------------------------------

class NewsRadarAdapter:
    source_id = "news_radar"
    module = "资讯雷达"
    display_name = "资讯雷达"

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        m = _meta(self.source_id)
        import newsradar
        path = newsradar.get_cache_file()
        if not os.path.isfile(path):
            return svc.not_initialized_record(
                m["source_id"], m["module"], m["display_name"],
                detail_path="/intel",
                stale_after_seconds=86400,
            )
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise AdapterReadError("SOURCE_CORRUPTED") from exc
        if not isinstance(data, dict):
            return svc.unavailable_record(
                m["source_id"], m["module"], m["display_name"],
                "SOURCE_CORRUPTED", detail_path="/intel",
                stale_after_seconds=86400,
            )
        # skeleton has generated_at None — treat as not initialized if no generated_at
        gen = data.get("generated_at")
        if gen is None or (isinstance(gen, str) and not gen.strip()):
            return svc.not_initialized_record(
                m["source_id"], m["module"], m["display_name"],
                detail_path="/intel",
                stale_after_seconds=86400,
            )
        gen_dt = svc.parse_flexible_time(gen, naive_as="beijing")
        if gen_dt is None:
            return svc.unavailable_record(
                m["source_id"], m["module"], m["display_name"],
                "SOURCE_CORRUPTED", detail_path="/intel",
                stale_after_seconds=86400,
            )
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        failed = stats.get("failed_sources", 0) or 0
        total = stats.get("total_sources", 0) or 0
        try:
            failed = int(failed)
            total = int(total)
        except (TypeError, ValueError):
            failed, total = 0, 0

        if total > 0 and failed >= total:
            status: svc.DataHealthStatus = "unavailable"
            code = "SOURCE_UNAVAILABLE"
            is_degraded = None
        elif failed > 0:
            status = "partial"
            code = "SOURCE_PARTIAL"
            is_degraded = False
        else:
            status = "normal"
            code = None
            is_degraded = None

        observed = svc.format_utc(gen_dt)
        is_stale = svc.is_stale_continuous(gen_dt, context.now_utc, 86400)
        industries = data.get("industries") if isinstance(data.get("industries"), list) else []
        item_count = 0
        for ind in industries:
            if isinstance(ind, dict) and isinstance(ind.get("items"), list):
                item_count += len(ind["items"])

        return svc.make_record(
            source_id=m["source_id"],
            module=m["module"],
            display_name=m["display_name"],
            status=status,
            is_stale=is_stale,
            observed_at=observed,
            last_success_at=observed if status in ("normal", "partial") else None,
            stale_after_seconds=86400,
            is_cached=True,
            is_degraded=is_degraded,
            coverage_current=total - failed if total else item_count,
            coverage_expected=total if total else None,
            last_error_code=code,
            last_error_at=None,
            blocks_advice=False,
            block_reason=None,
            detail_path="/intel",
        )


# ---------------------------------------------------------------------------
# my_reports
# ---------------------------------------------------------------------------

class MyReportsAdapter:
    source_id = "my_reports"
    module = "我的研报"
    display_name = "我的研报"

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        m = _meta(self.source_id)
        import myreports

        index_path = myreports._index_path()
        if not index_path.exists():
            return svc.not_initialized_record(
                m["source_id"], m["module"], m["display_name"],
                detail_path="/my-reports",
            )
        # 只读：不迁移、不写回
        try:
            entries = myreports._load_index_normalized()
        except myreports.ReportIndexCorruptedError:
            return svc.unavailable_record(
                m["source_id"], m["module"], m["display_name"],
                "SOURCE_CORRUPTED", detail_path="/my-reports",
            )
        except (OSError, UnicodeError) as exc:
            raise AdapterReadError("SOURCE_UNAVAILABLE") from exc

        index_entry_count = len(entries)
        max_imported: datetime | None = None
        missing_files = 0
        for e in entries:
            ia = e.get("imported_at")
            dt = svc.parse_flexible_time(ia, naive_as="utc")
            if dt and (max_imported is None or dt > max_imported):
                max_imported = dt
            rid = e.get("id")
            if not rid:
                missing_files += 1
                continue
            ext = e.get("ext") or ""
            if ext and not str(ext).startswith("."):
                ext = "." + str(ext)
            candidate = myreports.REPORTS_DIR / f"{rid}{ext}"
            try:
                if candidate.exists():
                    continue
                # 兼容仅 id 前缀的落盘名
                found = False
                if myreports.REPORTS_DIR.exists():
                    for p in myreports.REPORTS_DIR.iterdir():
                        if p.is_file() and (
                            p.name == f"{rid}{ext}" or p.stem == str(rid)
                        ):
                            found = True
                            break
                if not found:
                    missing_files += 1
            except OSError:
                missing_files += 1

        coverage_expected = index_entry_count
        coverage_current = index_entry_count - missing_files
        if missing_files > 0 and index_entry_count > 0:
            status: svc.DataHealthStatus = "partial"
            code = "SOURCE_PARTIAL"
        else:
            status = "normal"
            code = None

        observed = svc.format_utc(max_imported)
        return svc.make_record(
            source_id=m["source_id"],
            module=m["module"],
            display_name=m["display_name"],
            status=status,
            is_stale=False,
            observed_at=observed,
            last_success_at=observed,
            stale_after_seconds=None,
            is_cached=None,
            is_degraded=None,
            coverage_current=coverage_current,
            coverage_expected=coverage_expected,
            last_error_code=code,
            last_error_at=None,
            blocks_advice=False,
            block_reason=None,
            detail_path="/my-reports",
        )


# ---------------------------------------------------------------------------
# watchlist_portfolio_storage
# ---------------------------------------------------------------------------

class WatchlistPortfolioStorageAdapter:
    source_id = "watchlist_portfolio_storage"
    module = "本地存储"
    display_name = "自选股与持仓存储"

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        m = _meta(self.source_id)
        import watchlist_store
        import portfolio as pf

        wl_status = "not_configured"
        wl_updated: datetime | None = None
        wl_count = 0
        try:
            st = watchlist_store.get_watchlist_status()
            wl_status = st.get("status") or "not_configured"
            if wl_status == "valid" and isinstance(st.get("data"), dict):
                codes = st["data"].get("codes") or []
                wl_count = len(codes) if isinstance(codes, list) else 0
                wl_updated = svc.parse_flexible_time(
                    st["data"].get("updated_at"), naive_as="utc"
                )
        except (OSError, json.JSONDecodeError, UnicodeError):
            wl_status = "corrupted"

        pf_state = "not_configured"  # not_configured | valid | corrupted
        pf_count = 0
        pf_mtime: datetime | None = None
        if not os.path.isfile(pf.PF_FILE):
            pf_state = "not_configured"
        else:
            try:
                pf_mtime = datetime.fromtimestamp(
                    os.path.getmtime(pf.PF_FILE), tz=timezone.utc
                )
                with open(pf.PF_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                pf._validate_data(data)
                hs = data.get("holdings") or []
                pf_count = len(hs) if isinstance(hs, list) else 0
                pf_state = "valid"
            except pf.PortfolioDataCorruptedError:
                pf_state = "corrupted"
            except (json.JSONDecodeError, OSError, UnicodeError):
                pf_state = "corrupted"

        # 映射
        if wl_status == "not_configured" and pf_state == "not_configured":
            return svc.not_initialized_record(
                m["source_id"], m["module"], m["display_name"],
                detail_path="/portfolio",
            )
        if wl_status == "corrupted" and pf_state in ("corrupted", "not_configured"):
            return svc.unavailable_record(
                m["source_id"], m["module"], m["display_name"],
                "SOURCE_CORRUPTED", detail_path="/portfolio",
            )
        if pf_state == "corrupted" and wl_status in ("corrupted", "not_configured"):
            return svc.unavailable_record(
                m["source_id"], m["module"], m["display_name"],
                "SOURCE_CORRUPTED", detail_path="/portfolio",
            )

        # 一好一坏 / 一好一未配置 → partial
        good_wl = wl_status == "valid"
        good_pf = pf_state == "valid"
        bad_wl = wl_status == "corrupted"
        bad_pf = pf_state == "corrupted"
        missing_wl = wl_status == "not_configured"
        missing_pf = pf_state == "not_configured"

        if (good_wl and (bad_pf or missing_pf)) or (good_pf and (bad_wl or missing_wl)):
            status: svc.DataHealthStatus = "partial"
            code = "SOURCE_PARTIAL" if (bad_wl or bad_pf) else "SOURCE_PARTIAL"
        elif good_wl and good_pf:
            status = "normal"
            code = None
        elif bad_wl or bad_pf:
            status = "unavailable"
            code = "SOURCE_CORRUPTED"
        else:
            status = "normal"
            code = None

        obs = svc.max_time(wl_updated, pf_mtime)
        observed = svc.format_utc(obs)
        return svc.make_record(
            source_id=m["source_id"],
            module=m["module"],
            display_name=m["display_name"],
            status=status,
            is_stale=False,
            observed_at=observed,
            last_success_at=observed if status in ("normal", "partial") else None,
            stale_after_seconds=None,
            is_cached=None,
            is_degraded=None,
            coverage_current=wl_count + pf_count,
            coverage_expected=None,
            last_error_code=code,
            last_error_at=None,
            blocks_advice=False,
            block_reason=None,
            detail_path="/portfolio",
        )


# ---------------------------------------------------------------------------
# evidence_ledger
# ---------------------------------------------------------------------------

class EvidenceLedgerAdapter:
    source_id = "evidence_ledger"
    module = "证据账本"
    display_name = "投资逻辑与证据账本"

    def read(self, context: HealthReadContext) -> svc.DataHealthRecord:
        m = _meta(self.source_id)
        import evidence_thesis_service as ets
        import evidence_thesis_store as store

        db_path = ets.resolve_db_path()
        if not Path(db_path).exists():
            return svc.not_initialized_record(
                m["source_id"], m["module"], m["display_name"],
                detail_path="/thesis",
            )

        # WAL-aware 只读快照：在 store._LOCK 内安全读取主文件 + WAL
        try:
            with store.readonly_health_snapshot(db_path) as conn:
                # 只读 schema 校验：不执行 DDL
                try:
                    if not store._table_exists(conn, "schema_meta"):
                        return svc.unavailable_record(
                            m["source_id"], m["module"], m["display_name"],
                            "SOURCE_CORRUPTED", detail_path="/thesis",
                        )
                    ver = store._read_schema_version(conn)
                except store.EvidenceLedgerSchemaVersionError:
                    return svc.unavailable_record(
                        m["source_id"], m["module"], m["display_name"],
                        "SOURCE_SCHEMA_INCOMPATIBLE", detail_path="/thesis",
                    )
                except store.EvidenceLedgerCorruptedError:
                    return svc.unavailable_record(
                        m["source_id"], m["module"], m["display_name"],
                        "SOURCE_CORRUPTED", detail_path="/thesis",
                    )
                except sqlite3.DatabaseError as exc:
                    raise AdapterReadError("SOURCE_CORRUPTED") from exc

                if ver is None:
                    return svc.unavailable_record(
                        m["source_id"], m["module"], m["display_name"],
                        "SOURCE_CORRUPTED", detail_path="/thesis",
                    )
                if ver != store.SCHEMA_VERSION:
                    return svc.unavailable_record(
                        m["source_id"], m["module"], m["display_name"],
                        "SOURCE_SCHEMA_INCOMPATIBLE", detail_path="/thesis",
                    )

                try:
                    row = conn.execute("PRAGMA integrity_check").fetchone()
                except sqlite3.DatabaseError as exc:
                    raise AdapterReadError("SOURCE_CORRUPTED") from exc
                if row is None or str(row[0]).lower() != "ok":
                    return svc.unavailable_record(
                        m["source_id"], m["module"], m["display_name"],
                        "SOURCE_CORRUPTED", detail_path="/thesis",
                    )

                try:
                    ecount = conn.execute(
                        "SELECT COUNT(*) FROM evidence_records WHERE deleted = 0"
                    ).fetchone()[0]
                    tcount = conn.execute(
                        "SELECT COUNT(*) FROM investment_theses"
                    ).fetchone()[0]
                    max_u = conn.execute(
                        """
                        SELECT MAX(u) FROM (
                            SELECT MAX(updated_at) AS u FROM evidence_records WHERE deleted = 0
                            UNION ALL
                            SELECT MAX(updated_at) AS u FROM investment_theses
                        )
                        """
                    ).fetchone()[0]
                except sqlite3.DatabaseError as exc:
                    raise AdapterReadError("SOURCE_UNAVAILABLE") from exc

                max_dt = svc.parse_flexible_time(max_u, naive_as="utc")
                observed = svc.format_utc(max_dt)
                total = int(ecount or 0) + int(tcount or 0)
                return svc.make_record(
                    source_id=m["source_id"],
                    module=m["module"],
                    display_name=m["display_name"],
                    status="normal",
                    is_stale=False,
                    observed_at=observed,
                    last_success_at=observed,
                    stale_after_seconds=None,
                    is_cached=None,
                    is_degraded=None,
                    coverage_current=total,
                    coverage_expected=total,
                    last_error_code=None,
                    last_error_at=None,
                    blocks_advice=False,
                    block_reason=None,
                    detail_path="/thesis",
                )
        except FileNotFoundError:
            return svc.not_initialized_record(
                m["source_id"], m["module"], m["display_name"],
                detail_path="/thesis",
            )
        except store._ReadonlySnapshotUnavailable as exc:
            raise AdapterReadError("SOURCE_UNAVAILABLE") from exc
        except (OSError, sqlite3.DatabaseError) as exc:
            raise AdapterReadError("SOURCE_CORRUPTED") from exc


# ---------------------------------------------------------------------------
# Registry & collection
# ---------------------------------------------------------------------------

def build_adapters() -> list[DataHealthAdapter]:
    return [
        DailyReviewAdapter(),
        PortfolioAdviceGateAdapter(),
        PortfolioQuotesAdapter(),
        QuotesAdapter(),
        AnnouncementsAdapter(),
        FinancialsAdapter(),
        NewsRadarAdapter(),
        SectorResearchAdapter(),
        MyReportsAdapter(),
        WatchlistPortfolioStorageAdapter(),
        EvidenceLedgerAdapter(),
    ]


_ADAPTERS: list[DataHealthAdapter] | None = None


def get_adapters() -> list[DataHealthAdapter]:
    global _ADAPTERS
    if _ADAPTERS is None:
        _ADAPTERS = build_adapters()
    return _ADAPTERS


def reset_adapters_for_tests() -> None:
    global _ADAPTERS
    _ADAPTERS = None


def _safe_adapter_read(
    adapter: DataHealthAdapter,
    context: HealthReadContext,
) -> svc.DataHealthRecord:
    """仅隔离 AdapterReadError；编程错误 / 非法 record 向上冒泡 → HTTP 500。"""
    try:
        rec = adapter.read(context)
    except AdapterReadError as exc:
        if exc.error_code not in _ALLOWED_ADAPTER_ERROR_CODES:
            # 不应发生：AdapterReadError 构造时已校验
            raise RuntimeError("illegal AdapterReadError code") from exc
        m = _meta(adapter.source_id)
        return svc.unavailable_record(
            m["source_id"], m["module"], m["display_name"],
            exc.error_code,
        )
    # 严格校验：失败抛 RuntimeError → HTTP 500（不进入响应体）
    return validate_data_health_record(adapter, rec)


def _validate_adapter_registry(adapters_list: list[DataHealthAdapter]) -> None:
    """严格校验 Adapter 注册表：
    - 数量恰好为 11
    - source_id 集合与 SOURCE_REGISTRY 完全相等
    - 不允许重复 source_id
    - 顺序与注册表一致
    """
    if len(adapters_list) != len(svc.SOURCE_REGISTRY):
        raise RuntimeError(
            f"adapter registry size invalid: {len(adapters_list)} != {len(svc.SOURCE_REGISTRY)}"
        )
    expected_ids = [s["source_id"] for s in svc.SOURCE_REGISTRY]
    actual_ids = [getattr(ad, "source_id", None) for ad in adapters_list]
    if len(set(actual_ids)) != len(actual_ids):
        raise RuntimeError("adapter registry has duplicate source_id")
    if set(actual_ids) != set(expected_ids):
        raise RuntimeError("adapter registry source_id set mismatch")
    if actual_ids != expected_ids:
        raise RuntimeError("adapter registry order mismatch")
    # module / display_name 与注册表完全一致
    for ad, expected in zip(adapters_list, svc.SOURCE_REGISTRY):
        if getattr(ad, "module", None) != expected["module"]:
            raise RuntimeError(f"adapter module mismatch for {expected['source_id']}")
        if getattr(ad, "display_name", None) != expected["display_name"]:
            raise RuntimeError(f"adapter display_name mismatch for {expected['source_id']}")


def collect_all_records(
    *,
    now_utc: datetime | None = None,
) -> list[svc.DataHealthRecord]:
    now = now_utc or datetime.now(timezone.utc)
    events: dict[str, dict[str, Any]] = {}
    events_err: str | None = None
    try:
        events = event_store.load_events_readonly()
    except event_store.DataHealthEventStoreError:
        events_err = "SOURCE_CORRUPTED"
        events = {}

    context = HealthReadContext(
        now_utc=now,
        events=events,
        events_load_error=events_err,
    )
    adapters = get_adapters()
    _validate_adapter_registry(adapters)
    items: list[svc.DataHealthRecord] = []
    for ad in adapters:
        items.append(_safe_adapter_read(ad, context))
    return items


def get_health_overview(*, now_utc: datetime | None = None) -> dict[str, Any]:
    items = collect_all_records(now_utc=now_utc)
    return svc.aggregate_health(items)


def get_source_detail(
    source_id: str,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any] | None:
    if source_id not in svc.REGISTERED_SOURCE_IDS:
        return None
    items = collect_all_records(now_utc=now_utc)
    rec = next((it for it in items if it["source_id"] == source_id), None)
    if rec is None:
        return None
    calc = dict(svc.SOURCE_CALCULATION.get(source_id, {}))
    related = list(svc.SOURCE_RELATED_PAGES.get(source_id, []))
    return {
        "record": rec,
        "calculation": calc,
        "related_pages": related,
    }
