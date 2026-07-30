"""顶部风险分析服务层。

职责：
- 一次性从主项目数据层（astock）构建标准化 TopRiskFact；
- evaluator 不取数、不联网；service 负责所有 I/O；
- 运行 TopRiskEngine，产出 Pydantic 信封（fail-closed）；
- 写入 Data Health 事件；
- 通过 top_risk_trace_service 复用主项目通用决策追踪层
  （decision_trace_store），不新建第二套账本；
- 简单 TTL 缓存（unavailable 不缓存）。

Phase 1 影子模式：signal 恒为 unknown，不参与任何加权 composite score、
不改最终交易结论或仓位。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional

from top_risk_schema import (
    SCHEMA_VERSION,
    TopRiskData,
    TopRiskEnvelope,
    TopRiskFact,
    TopRiskLimitation,
    TopRiskResult,
    TopRiskStepTrace,
)
from top_risk_engine import TopRiskEngine
from top_risk_trace_service import archive_top_risk

_CONFIG_PATH = __import__("os").path.join(
    __import__("os").path.dirname(__file__), "top_risk_config.yaml"
)
_ENGINE: Optional[TopRiskEngine] = None
_ENGINE_LOCK = threading.Lock()

# 简单 TTL 缓存：key=(code, days) → (fetched_at, envelope_dict)
_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_CACHE_TTL = 900.0  # 15 分钟
_CACHE_LOCK = threading.Lock()


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _get_engine() -> TopRiskEngine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        _ENGINE = TopRiskEngine.from_yaml(_CONFIG_PATH)
    return _ENGINE


def _engine_config_hash() -> Optional[str]:
    try:
        return _get_engine().config_hash
    except Exception:
        return None


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _unavailable_envelope(
    code: str, limitations: list[dict], name: Optional[str] = None
) -> TopRiskEnvelope:
    now = datetime.now(timezone.utc)
    return TopRiskEnvelope(
        schema_version=SCHEMA_VERSION,
        source="Vibe-Research top-risk engine",
        source_tier="reference",
        code=code,
        name=name,
        trade_date=None,
        fetched_at=now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z",
        status="unavailable",
        is_stale=False,
        risk_score=None,
        confidence=None,
        coverage={"completed": 0, "total": 0, "ratio": 0.0},
        signal="unknown",
        signal_eligible=False,
        config_hash=None,
        decision_run_id=None,
        trace_archive_status="skipped",
        warnings=[],
        limitations=[TopRiskLimitation(**l) for l in limitations],
        data=None,
        trace=[],
    )


def _build_facts(code: str, days: int) -> tuple[TopRiskFact, list[dict]]:
    """从主项目数据层构建标准化事实。任一来源失败 → None + limitation（不抛）。"""
    limitations: list[dict] = []
    name: Optional[str] = None
    price_history: Optional[list[float]] = None
    volume_history: Optional[list[float]] = None
    trade_date: Optional[str] = None
    valuation: Optional[dict] = None
    fund_flow: Optional[list[dict]] = None
    margin: Optional[list[dict]] = None

    # 名称（轻量，失败不影响）
    try:
        from astock import tencent_quote

        q = tencent_quote([code])
        name = (q.get(code) or {}).get("name")
    except Exception:
        name = None

    # K 线（价格 + 量）
    try:
        from astock import kline

        bars = kline(code, category=4, offset=max(days, 60))
        closes: list[float] = []
        vols: list[float] = []
        dates: list[str] = []
        for b in bars or []:
            c = _num(b.get("close", b.get("Close")))
            v = _num(b.get("volume", b.get("vol", b.get("amount"))))
            d = b.get("date")
            if c is not None:
                closes.append(c)
                vols.append(v if v is not None else 0.0)
                dates.append(str(d) if d is not None else "")
        if closes:
            price_history = closes
            volume_history = vols
            trade_date = dates[-1][:10] if dates and dates[-1] else None
        else:
            limitations.append(
                {"field": "price_history", "reason_code": "SOURCE_PARTIAL", "detail": "K线返回为空"}
            )
    except Exception as exc:
        limitations.append(
            {"field": "price_history", "reason_code": "SOURCE_UNAVAILABLE", "detail": str(exc)[:160]}
        )

    # 估值分位
    try:
        from astock import valuation_percentile

        vp = valuation_percentile(code)
        metrics = (vp or {}).get("metrics") or {}
        if metrics:
            valuation = metrics
        else:
            limitations.append(
                {"field": "valuation", "reason_code": "SOURCE_PARTIAL", "detail": "估值分位无数据"}
            )
    except Exception as exc:
        limitations.append(
            {"field": "valuation", "reason_code": "SOURCE_UNAVAILABLE", "detail": str(exc)[:160]}
        )

    # 资金流
    try:
        from astock import stock_fund_flow_120d

        ff = stock_fund_flow_120d(code)
        fund_flow = ff if ff else None
        if not ff:
            limitations.append(
                {"field": "fund_flow", "reason_code": "SOURCE_PARTIAL", "detail": "资金流为空"}
            )
    except Exception as exc:
        limitations.append(
            {"field": "fund_flow", "reason_code": "SOURCE_UNAVAILABLE", "detail": str(exc)[:160]}
        )

    # 融资融券
    try:
        from astock import margin_trading

        mt = margin_trading(code, page_size=30)
        margin = mt if mt else None
        if not mt:
            limitations.append(
                {"field": "margin_trading", "reason_code": "SOURCE_PARTIAL", "detail": "融资融券为空"}
            )
    except Exception as exc:
        limitations.append(
            {"field": "margin_trading", "reason_code": "SOURCE_UNAVAILABLE", "detail": str(exc)[:160]}
        )

    facts = TopRiskFact(
        code=code,
        name=name,
        trade_date=trade_date,
        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "Z",
        price_history=price_history,
        volume_history=volume_history,
        valuation=valuation,
        fund_flow=fund_flow,
        margin_trading=margin,
        events=None,  # Phase1 无可靠来源
        sentiment_series=None,  # Phase1 无可靠来源
    )
    return facts, limitations


def _build_narrative(result: TopRiskResult, risk_drivers, safety_signals) -> Optional[str]:
    if result.status == "unavailable":
        return "数据不足，顶部风险分析暂不可用。"
    score = result.risk_score or 0
    level = "高" if score >= 66 else ("中" if score >= 33 else "低")
    parts = [f"顶部风险强度{level}（{score}/100）"]
    if risk_drivers:
        parts.append("主要风险：" + "、".join(risk_drivers))
    if safety_signals:
        parts.append("缓解信号：" + "、".join(safety_signals))
    if result.coverage and result.coverage.get("ratio", 1.0) < 1.0:
        parts.append("（部分数据源缺失，结论偏保守）")
    return "；".join(parts) + "。"


def _record_health(status: str, code: str) -> None:
    """Data Health 事件（fail-closed，不阻塞响应）。"""
    try:
        import data_health_event_store as _dhes

        if status == "normal":
            _dhes.safe_call(_dhes.record_success, "top_risk_analysis")
        elif status == "partial":
            _dhes.safe_call(_dhes.record_partial, "top_risk_analysis")
        else:
            _dhes.safe_call(_dhes.record_failure, "top_risk_analysis", "SOURCE_UNAVAILABLE")
    except Exception:
        pass


def _attach_trace(envelope: TopRiskEnvelope) -> None:
    """归档到决策追踪层（fail-closed），回填追踪身份。"""
    run_id, status = archive_top_risk(envelope)
    envelope.decision_run_id = run_id
    envelope.trace_archive_status = status


def analyze_top_risk(code: str, days: int = 120) -> TopRiskEnvelope:
    """顶部风险分析权威入口（影子模式）。返回 Pydantic 信封，绝不抛未捕获异常。"""
    code = (code or "").strip()
    if not code:
        env = _unavailable_envelope(
            code, [{"field": "code", "reason_code": "INVALID_INPUT", "detail": "代码为空"}]
        )
        _attach_trace(env)
        return env

    try:
        engine = _get_engine()
    except Exception as exc:
        env = _unavailable_envelope(
            code,
            [{"field": "config", "reason_code": "CONFIG_ERROR", "detail": str(exc)[:160]}],
        )
        _attach_trace(env)
        return env

    facts, build_limitations = _build_facts(code, days)
    try:
        result = engine.run(facts)
    except Exception as exc:
        env = _unavailable_envelope(
            code,
            [{"field": "engine", "reason_code": "ENGINE_ERROR", "detail": str(exc)[:160]}],
            name=facts.name,
        )
        _attach_trace(env)
        return env

    all_limits = list(build_limitations) + result.limitations

    # 步骤 trace + 汇总
    trace = [
        TopRiskStepTrace(
            step_id=s.step_id,
            label=s.label,
            direction=s.direction,
            weight=s.weight,
            step_risk=round(s.step_risk, 3),
            confidence=int(round(s.confidence)),
            skipped=s.skipped,
            skip_reason=s.skip_reason,
            reasons=s.reasons,
            details=s.details,
        )
        for s in result.steps
    ]
    risk_drivers = [s.label for s in result.steps if s.direction == "RISK" and not s.skipped]
    safety_signals = [s.label for s in result.steps if s.direction == "SAFE" and not s.skipped]
    narrative = _build_narrative(result, risk_drivers, safety_signals)
    data = TopRiskData(
        name=facts.name,
        completed_steps=result.coverage["completed"],
        total_steps=result.coverage["total"],
        risk_drivers=risk_drivers,
        safety_signals=safety_signals,
        narrative=narrative,
    )

    envelope = TopRiskEnvelope(
        schema_version=SCHEMA_VERSION,
        source="Vibe-Research top-risk engine",
        source_tier="reference",
        code=code,
        name=facts.name,
        trade_date=facts.trade_date,
        fetched_at=facts.fetched_at,
        status=result.status,
        is_stale=False,
        risk_score=result.risk_score,
        confidence=result.confidence,
        coverage=result.coverage,
        signal="unknown",
        signal_eligible=False,
        config_hash=engine.config_hash,
        decision_run_id=None,
        trace_archive_status=None,
        warnings=[],
        limitations=[TopRiskLimitation(**l) for l in all_limits],
        data=data,
        trace=trace,
    )

    # Data Health 事件 + 决策追踪归档（均 fail-closed）
    _record_health(result.status, code)
    _attach_trace(envelope)

    # 写缓存（unavailable 不缓存）
    if envelope.status != "unavailable":
        cache_key = (code, days)
        with _CACHE_LOCK:
            _CACHE[cache_key] = (_now_ts(), envelope.model_dump())

    return envelope
