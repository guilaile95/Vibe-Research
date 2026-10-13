"""Date-owned, bounded research view of existing immutable source receipts."""
from __future__ import annotations

import os

from fact_lake_store import open_existing_fact_lake_snapshot, FactLakeNotInitializedError, FactLakeBusyError
import trade_calendar
import shortline_research_contract as C
from shortline_research_archive import load_research_days
from shortline_regime_annotations import read_regime_annotations
from shortline_research_metrics import (daily_observation, cohort_feedback, historical_summary, historical_samples, structure_diagnostics)


def _base(day):
    return {"schema_version": C.VERSION, "trade_date": day, "previous_trade_date": None,
            "status": "unavailable", "reason_codes": [], "message": "研究归档尚不可用",
            "selection_mode": "CURRENT_STORED_POSTHOC", "point_in_time_claim": "NONE", "research_only": True,
            "fixture": False, "ingestion_enabled": False, "schedule_enabled": False,
            "projection": None, "evidence": [], "input_requirements": [
                "固定交易日的完整涨停/炸板/跌停池原始响应，含源业务日期、总数与分页回执",
                "昨日涨停与炸板完整并集每只股票的目标日daily OHLC/pre_close和stk_limit原始响应",
                "既有FactLake归档需由明确授权的手动采集流程写入；浏览本页不会联网或创建归档",
                "历史窗口需要逐日真实积累；离线合成案例不代表实盘取数或历史验收",
            ], "limitations": C.LIMITATIONS}


def research_dates(day):
    """Fixed prior exchange sessions, never replace gaps with older valid data."""
    previous = trade_calendar.previous_trade_date(day)
    if previous is None:
        return []
    dates = [day, previous]
    # 90 entry sessions plus one prior day required for their feedback.
    while len(dates) < 92:
        earlier = trade_calendar.previous_trade_date(dates[-1])
        if earlier is None:
            break
        dates.append(earlier)
    return list(reversed(dates))


def build_research_projection(day, dates, inputs):
    observations = {d: daily_observation(inputs[d]) for d in dates}
    feedback = {d: cohort_feedback(inputs[dates[i - 1]], inputs[d]) for i, d in enumerate(dates) if i}
    return {"daily": observations[day], "cohort": feedback[day],
            "history": historical_summary(dates, observations, feedback, day),
            "samples": historical_samples(dates, observations, feedback, day),
            "structure": structure_diagnostics(dates, inputs, observations, day)}


def query_shortline_research(trade_date):
    day = C.day(trade_date)
    result = _base(day)
    dates = research_dates(day)
    if not dates:
        result.update(reason_codes=["CALENDAR_UNAVAILABLE"], message="所选日期未获离线交易日历确认，未猜测相邻交易日")
        return result
    result["previous_trade_date"] = dates[-2]
    root = os.environ.get("VR_FACT_LAKE_ROOT", "").strip()
    if not root:
        result.update(reason_codes=["ARCHIVE_NOT_CONNECTED"], message="尚未连接研究归档；需先配置归档与原始数据采集，当前页面不会启动采集")
        return result
    try:
        lake = open_existing_fact_lake_snapshot(root)
        inputs = load_research_days(lake, dates)
        annotations = read_regime_annotations(lake, day)
        captures = [capture for day_inputs in inputs.values() for capture in day_inputs.values() if capture]
        if not captures and not annotations["events"]:
            lake.assert_unchanged()
            result.update(reason_codes=["RESEARCH_RECEIPTS_MISSING"], message="归档已连接，但缺少这个窗口的版本化短线研究原始回执")
            return result
        fixture_states = {item["fixture"] for item in captures} or {False}
        if len(fixture_states) != 1:
            raise ValueError("mixed acquired and fixture evidence")
        projection = build_research_projection(day, dates, inputs)
        projection["structure"]["regime_events"] = annotations
        evidence = [{"trade_date": d, "kind": kind, "status": capture["status"], "complete": capture["complete"],
                     "source_finality": capture["source_finality"], "source_total": capture["source_total"],
                     "row_count": len(capture["rows"]), "reason_codes": capture["reason_codes"],
                     "receipts": capture["evidence"]} for d in dates for kind, capture in inputs[d].items() if capture]
        lake.assert_unchanged()
        current_complete = all(inputs[day][kind] and inputs[day][kind]["status"] == "normal" for kind in C.KINDS)
        full = current_complete and projection["cohort"]["status"] == "normal"
        result.update(status="normal" if full else "partial", reason_codes=[] if full else ["INPUT_COVERAGE_PARTIAL"],
                      message="合成案例：仅验证软件，未获取真实市场数据" if True in fixture_states else "已读取原始回执并重算事后研究；缺失指标保持未知",
                      fixture=True in fixture_states, projection=projection, evidence=evidence)
        return result
    except FactLakeNotInitializedError:
        result.update(reason_codes=["ARCHIVE_NOT_INITIALIZED"], message="配置的归档尚未初始化；未自动创建或迁移")
    except FactLakeBusyError:
        result.update(reason_codes=["ARCHIVE_BUSY"], message="归档有待落盘事务或读取时发生变化；未写入、检查点或展示不一致结果")
    except Exception:
        result.update(reason_codes=["ARCHIVE_VALIDATION_FAILED"], message="归档身份、完整性、版本或价格合同未通过核验，未展示结果")
    return result
