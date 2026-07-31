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

import hashlib
import json
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
    _utc_now,
)
from top_risk_engine import TopRiskEngine
from top_risk_trace_service import archive_top_risk
from data_health_service import is_stale_cn_trade_date

_CONFIG_PATH = __import__("os").path.join(
    __import__("os").path.dirname(__file__), "top_risk_config.yaml"
)
_ENGINE: Optional[TopRiskEngine] = None
_ENGINE_LOCK = threading.Lock()

# 简单 TTL 缓存：key=(code, days, config_hash) → (cached_at, envelope_dict)。
# 缓存命中直接返回已归档信封，不重新计算、不重复写 decision_trace_store。
_CACHE: dict[tuple[str, int, str], tuple[float, dict]] = {}
_CACHE_TTL = 900.0  # 15 分钟
_CACHE_LOCK = threading.Lock()

_FUND_FLOW_TIE_FIELDS = ("main_net", "large_net", "super_net")
_MARGIN_TIE_FIELDS = ("rzye", "rzmre", "rzche")


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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_number(value: Any) -> float | None:
    num = _num(value)
    return round(num, 8) if num is not None else None


def _canonical_rows(rows: Optional[list[dict]], fields: tuple[str, ...]) -> list[dict]:
    normalized: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        normalized.append({key: _canonical_number(row.get(key)) for key in fields})
    return normalized


def make_input_fingerprint(facts: TopRiskFact) -> str:
    """仅对标准化必要事实做稳定哈希；不含请求时间、路径、异常或敏感信息。"""
    valuation: dict[str, dict[str, float | None]] = {}
    for metric in ("pe_ttm", "pb"):
        raw = (facts.valuation or {}).get(metric) or {}
        valuation[metric] = {
            "current": _canonical_number(raw.get("current")),
            "percentile": _canonical_number(raw.get("percentile")),
        }
    payload = {
        "code": facts.code,
        "trade_date": facts.trade_date,
        "prices": [_canonical_number(v) for v in (facts.price_history or [])],
        "volumes": [_canonical_number(v) for v in (facts.volume_history or [])],
        "valuation": valuation,
        "fund_flow": _canonical_rows(
            _sort_by_date(facts.fund_flow, tie_fields=_FUND_FLOW_TIE_FIELDS),
            _FUND_FLOW_TIE_FIELDS,
        ),
        "margin_trading": _canonical_rows(
            _sort_by_date(facts.margin_trading, tie_fields=_MARGIN_TIE_FIELDS),
            _MARGIN_TIE_FIELDS,
        ),
        "events": facts.events or [],
        "sentiment_series": facts.sentiment_series or [],
    }
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "inp_" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]


def unavailable_envelope(
    code: str, limitations: list[dict], name: Optional[str] = None
) -> TopRiskEnvelope:
    """构造统一的 fail-closed unavailable 信封，供 service 与 API 路由复用。"""
    return TopRiskEnvelope(
        schema_version=SCHEMA_VERSION,
        source="Vibe-Research top-risk engine",
        source_tier="reference",
        code=code,
        name=name,
        trade_date=None,
        fetched_at=_utc_now(),
        status="unavailable",
        is_stale=True,
        risk_score=None,
        confidence=None,
        coverage={"completed": 0, "total": 0, "ratio": 0.0},
        signal="unknown",
        signal_eligible=False,
        config_hash=None,
        input_fingerprint=None,
        decision_run_id=None,
        trace_archive_status="skipped",
        warnings=[],
        limitations=[TopRiskLimitation(**l) for l in limitations],
        data=None,
        trace=[],
    )


def _normalize_kline(bars: list[dict]) -> tuple[list[float], list[Optional[float]], Optional[str]]:
    """标准化 K 线数据。

    规则：
    - 同时支持 datetime 和 date 字段；
    - 丢弃无有效日期或无 close 的行；
    - 同日选优与输入顺序无关：有效 volume > 较晚完整 datetime > 数值 tie-break；
    - 按交易日期升序排序；
    - price_history 与 volume_history 保持一一对齐；
    - volume 只允许读取 volume 或 vol，严禁把 amount 当作 volume；
    - 缺失 volume 保留 None，严禁转换为 0；
    - trade_date 使用排序后最后一条有效交易日期。
    """
    # 解析每条 bar，提取 (date_key, close, volume, duplicate_priority)
    parsed: list[tuple[str, float, Optional[float], tuple]] = []
    for b in bars or []:
        if not isinstance(b, dict):
            continue
        # 日期：兼容 datetime / date 字段
        date_raw = b.get("datetime") or b.get("date")
        if date_raw is None:
            continue
        date_str = str(date_raw).strip()
        # 提取日期部分（YYYY-MM-DD），兼容 datetime 格式
        date_key = date_str[:10]
        if len(date_key) != 10 or date_key.count("-") != 2:
            continue

        close_val = b.get("close", b.get("Close"))
        close_num = _num(close_val)
        if close_num is None:
            continue  # 无有效 close → 丢弃

        # volume 仅读取 volume / vol；绝不使用 amount
        vol_val = b.get("volume", b.get("vol"))
        vol_num = _num(vol_val)  # 缺失或无效 → None

        datetime_part = date_str[10:].lstrip(" T")
        duplicate_priority = (
            vol_num is not None,
            bool(datetime_part),
            datetime_part,
            close_num,
            vol_num if vol_num is not None else float("-inf"),
        )
        parsed.append((date_key, close_num, vol_num, duplicate_priority))

    if not parsed:
        return [], [], None

    # 先按明确优先级选优，再按日期去重；不依赖上游返回顺序。
    seen: dict[str, tuple[float, Optional[float], tuple]] = {}
    for date_key, close_num, vol_num, priority in parsed:
        current = seen.get(date_key)
        if current is None or priority > current[2]:
            seen[date_key] = (close_num, vol_num, priority)

    # 按日期升序排序
    sorted_dates = sorted(seen.keys())

    prices: list[float] = []
    volumes: list[Optional[float]] = []
    for dk in sorted_dates:
        c, v, _priority = seen[dk]
        prices.append(c)
        volumes.append(v)

    trade_date = sorted_dates[-1] if sorted_dates else None
    return prices, volumes, trade_date


def _sort_by_date(
    rows: Optional[list[dict]],
    date_field: str = "date",
    tie_fields: tuple[str, ...] = _FUND_FLOW_TIE_FIELDS,
) -> list[dict]:
    """按日期与明确业务投影排序；无关元数据不参与次级键。"""

    def _date_key(row: dict) -> tuple:
        d = row.get(date_field) if row else None
        business_tie = tuple(
            (value is None, value if value is not None else 0.0)
            for value in (_canonical_number(row.get(field)) for field in tie_fields)
        )
        return (d is None, str(d) if d is not None else "", business_tie)

    if not rows:
        return []
    return sorted(rows, key=_date_key)


def _build_facts(code: str, days: int) -> tuple[TopRiskFact, list[dict]]:
    """从主项目数据层构建标准化事实。任一来源失败 → None + limitation（不抛）。"""
    limitations: list[dict] = []
    name: Optional[str] = None
    price_history: Optional[list[float]] = None
    volume_history: Optional[list[Optional[float]]] = None
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
        prices, vols, tdate = _normalize_kline(bars)
        if prices:
            price_history = prices
            volume_history = vols
            trade_date = tdate
        else:
            limitations.append(
                {"field": "price_history", "reason_code": "SOURCE_PARTIAL", "detail": "K线返回为空"}
            )
    except Exception:
        limitations.append(
            {"field": "price_history", "reason_code": "SOURCE_UNAVAILABLE", "detail": "核心行情数据当前不可用。"}
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
    except Exception:
        limitations.append(
            {"field": "valuation", "reason_code": "SOURCE_UNAVAILABLE", "detail": "估值数据当前不可用。"}
        )

    # 资金流（按日期升序排序，保证指纹确定性）
    try:
        from astock import stock_fund_flow_120d

        ff = stock_fund_flow_120d(code)
        if ff:
            fund_flow = _sort_by_date(ff, tie_fields=_FUND_FLOW_TIE_FIELDS)
        else:
            limitations.append(
                {"field": "fund_flow", "reason_code": "SOURCE_PARTIAL", "detail": "资金流为空"}
            )
    except Exception:
        limitations.append(
            {"field": "fund_flow", "reason_code": "SOURCE_UNAVAILABLE", "detail": "资金流数据当前不可用。"}
        )

    # 融资融券（按日期升序排序，保证引擎读到的时间序列方向正确）
    try:
        from astock import margin_trading

        mt = margin_trading(code, page_size=30)
        if mt:
            margin = _sort_by_date(mt, tie_fields=_MARGIN_TIE_FIELDS)
        else:
            limitations.append(
                {"field": "margin_trading", "reason_code": "SOURCE_PARTIAL", "detail": "融资融券为空"}
            )
    except Exception:
        limitations.append(
            {"field": "margin_trading", "reason_code": "SOURCE_UNAVAILABLE", "detail": "融资融券数据当前不可用。"}
        )

    facts = TopRiskFact(
        code=code,
        name=name,
        trade_date=trade_date,
        fetched_at=_utc_now(),
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


def _record_health(service_status: str) -> None:
    """记录服务级能力健康；不把单只股票自身数据缺失映射为全局故障。"""
    try:
        import data_health_event_store as _dhes

        if service_status == "normal":
            _dhes.safe_call(_dhes.record_success, "top_risk_analysis")
        elif service_status == "partial":
            _dhes.safe_call(_dhes.record_partial, "top_risk_analysis")
        else:
            _dhes.safe_call(_dhes.record_failure, "top_risk_analysis", "SOURCE_UNAVAILABLE")
    except Exception:
        pass


def _service_health_from_run(facts: TopRiskFact, _result: TopRiskResult) -> str:
    """按引擎/配置/核心行情能力评估全局服务，不采纳单标的 optional 缺失。"""
    if not facts.price_history or not facts.trade_date:
        return "unavailable"
    # 有核心行情且引擎已成功执行，即使该标的某 optional 步骤不适用，服务仍健康。
    return "normal"


def _compute_is_stale(
    trade_date: Optional[str], now_utc: Optional[datetime] = None
) -> bool:
    """复用 Data Health 的权威 A 股交易日 freshness 规则。"""
    if not trade_date:
        return True
    return is_stale_cn_trade_date(trade_date, None, now_utc or _now_utc())


def attach_trace_and_archive(envelope: TopRiskEnvelope) -> TopRiskEnvelope:
    """归档并回填追踪身份；路由只依赖该公开 service 入口。"""
    run_id, status = archive_top_risk(envelope)
    envelope.decision_run_id = run_id
    envelope.trace_archive_status = status
    return envelope


def analyze_top_risk(code: str, days: int = 120) -> TopRiskEnvelope:
    """顶部风险分析权威入口（影子模式）。返回 Pydantic 信封，绝不抛未捕获异常。"""
    code = (code or "").strip()
    if not code:
        env = unavailable_envelope(
            code, [{"field": "code", "reason_code": "INVALID_INPUT", "detail": "代码为空"}]
        )
        return attach_trace_and_archive(env)

    try:
        engine = _get_engine()
    except Exception:
        _record_health("unavailable")
        env = unavailable_envelope(
            code,
            [{"field": "config", "reason_code": "CONFIG_ERROR", "detail": "顶部风险配置当前不可用。"}],
        )
        return attach_trace_and_archive(env)

    cache_key = (code, days, engine.config_hash)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and _now_ts() - cached[0] <= _CACHE_TTL:
            cached_envelope = TopRiskEnvelope(**cached[1])
            cached_envelope.is_stale = _compute_is_stale(cached_envelope.trade_date)
            return cached_envelope
        if cached:
            _CACHE.pop(cache_key, None)

    facts, build_limitations = _build_facts(code, days)
    try:
        result = engine.run(facts)
    except Exception:
        _record_health("unavailable")
        env = unavailable_envelope(
            code,
            [{"field": "engine", "reason_code": "ENGINE_ERROR", "detail": "顶部风险引擎当前不可执行。"}],
            name=facts.name,
        )
        return attach_trace_and_archive(env)

    all_limits = list(build_limitations) + result.limitations
    input_fingerprint = make_input_fingerprint(facts)

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
        is_stale=_compute_is_stale(facts.trade_date),
        risk_score=result.risk_score,
        confidence=result.confidence,
        coverage=result.coverage,
        signal="unknown",
        signal_eligible=False,
        config_hash=engine.config_hash,
        input_fingerprint=input_fingerprint,
        decision_run_id=None,
        trace_archive_status=None,
        warnings=[],
        limitations=[TopRiskLimitation(**l) for l in all_limits],
        data=data,
        trace=trace,
    )

    # Data Health 记录服务级能力；单标的 optional 缺失只保留在 envelope limitations。
    _record_health(_service_health_from_run(facts, result))
    attach_trace_and_archive(envelope)

    # 写缓存（unavailable 不缓存）；缓存命中直接返回，避免重复归档。
    if envelope.status != "unavailable":
        with _CACHE_LOCK:
            _CACHE[cache_key] = (_now_ts(), envelope.model_dump())

    return envelope
