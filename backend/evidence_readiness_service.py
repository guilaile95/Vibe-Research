"""Read-only readiness of the already configured archives, not an importer.

Feature services remain the qualification authorities. This projection neither
collects evidence nor treats hashes as proof of provider authenticity.
"""
from __future__ import annotations

import cohort_identity_service as cohort
import next_day_verification as journal
import short_term_fact_store as store
import short_term_seal_quality_service as seal
import trade_calendar

SCHEMA_VERSION = "evidence-readiness.v0.1"
_FEATURES = ("seal_quality", "cohort_identity", "next_day_verification")
_REQUIREMENTS = {
    "seal_quality": "所选交易日的已发布涨停池原始回执，日期绑定、重放校验和封板字段覆盖通过现有检查。",
    "cohort_identity": "所选日及前一交易日的完整 v0.2 收盘名单；来源、时间、全名单与涨停家数一致。",
    "next_day_verification": f"写下条件前已落库的合格收盘事实；次日收盘后另需目标日事实。基线至少需要 {journal.MIN_SAMPLES} 个有效相邻日样本。",
}
_NEXT = {
    "seal_quality": "查看封板质量卡的来源与字段覆盖；缺少归档时需先通过现有获准来源获得证据，此处不能采集或导入。",
    "cohort_identity": "查看两日名单卡的来源明细；缺少任一天完整归档时保持未知，不用连板精选名单补齐。",
    "next_day_verification": "在明日验证卡查看保存窗口与逐项证据；先有事实再写条件，历史日期不能补写预测。",
}


def _item(key, status, reasons, dates):
    return {"feature": key, "status": status, "reason_codes": list(reasons),
            "required_dates": dates, "requirements": _REQUIREMENTS[key], "next_step": _NEXT[key]}


def _journal_readiness(day, now):
    # First distinguish missing/busy from ineligible using the same no-sidecar
    # reader as the feature. _fact_record owns semantic/temporal admission.
    try:
        records = store.load_final_fact_records_readonly((day,))
        if day not in records:
            return "missing", ["ARCHIVE_MISSING"], {key: False for key in journal.LEGACY_METRICS}
        fact = journal._fact_record(records[day], day, now)
        metrics = {key: journal._value(fact, key) is not None for key in journal.LEGACY_METRICS}
        return ("ready", [], metrics) if any(metrics.values()) else ("ineligible", ["NO_EVIDENCE"], metrics)
    except store.FactStoreBusyError:
        return "busy", ["ARCHIVE_BUSY"], {key: False for key in journal.LEGACY_METRICS}
    except (store.FactStoreError, ValueError, TypeError, KeyError, OverflowError, OSError):
        return "ineligible", ["ARCHIVE_INELIGIBLE"], {key: False for key in journal.LEGACY_METRICS}


def query_evidence_readiness(trade_date):
    day = seal.validate_trade_date(trade_date)
    now = journal._now()
    previous = trade_calendar.previous_trade_date(day)
    boundary = journal._boundary(day, now)
    dates = {"seal_quality": [day], "cohort_identity": ([previous, day] if previous else [day]),
             "next_day_verification": [day] + ([boundary["next_trade_date"]] if boundary["next_trade_date"] else [])}
    sessions = trade_calendar._load_calendar()
    if sessions is None or day not in sessions:
        reason = "CALENDAR_UNAVAILABLE" if sessions is None else "NON_TRADING_DATE"
        features = [_item(key, "ineligible", [reason], dates[key]) for key in _FEATURES]
        metrics = {key: False for key in journal.LEGACY_METRICS}
    else:
        quality = seal.query_seal_quality(day)
        reasons = quality["reason_codes"]
        status = ("ready" if quality["status"] == "normal" else
                  "busy" if "ARCHIVE_BUSY" in reasons else
                  "not_configured" if "ARCHIVE_NOT_CONNECTED" in reasons else
                  "missing" if any(code in reasons for code in ("ARCHIVE_NOT_INITIALIZED", "ARCHIVE_OBSERVATION_MISSING")) else "ineligible")
        features = [_item("seal_quality", status, reasons, dates["seal_quality"])]
        identity = cohort.query_cohort_identity(day)
        reasons = identity["reason_codes"]
        status = ("ready" if identity["status"] == "normal" else "busy" if "ARCHIVE_BUSY" in reasons else
                  "missing" if "ARCHIVE_MISSING" in reasons else "ineligible")
        features.append(_item("cohort_identity", status, reasons, dates["cohort_identity"]))
        if boundary["state"] == "CALENDAR_UNKNOWN":
            status, reasons, metrics = "ineligible", ["CALENDAR_UNKNOWN"], {key: False for key in journal.LEGACY_METRICS}
        else:
            status, reasons, metrics = _journal_readiness(day, now)
        features.append(_item("next_day_verification", status, reasons, dates["next_day_verification"]))
    return {"schema_version": SCHEMA_VERSION, "trade_date": day, "generated_at": journal._stamp(now),
            "read_only": True, "ingestion_enabled": False, "features": features,
            "journal": {**boundary, "prior_metric_available": metrics, "verification_claim": "NONE"},
            "limitations": ["只检查服务端已配置的归档；不连接来源、不上传导入、不创建归档。",
                            "各功能依次读取已有归档；不是跨数据源的原子快照。",
                            "可读取仅指现有合同检查通过；不证明上游真实性、历史当时已知或真实使用验收。",
                            "明日验证的可读取状态仅指所选日事前事实；不是预测已保存、次日已验证或有统计优势。"]}
