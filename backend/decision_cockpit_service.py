"""明日决策驱动舱编排层：候选池 → 信号 → 计划 → LLM 解释（含确定性兜底）。

本模块是唯一对外编排入口；所有业务规则拆分到：
- ``decision_cockpit_signals``：纯阈值信号评估（strong/medium/weak/unknown）。
- ``decision_cockpit_store``：证据 / 信号 / 计划持久化。
- ``ai_result_store`` / ``portfolio_advice_account_metrics``：持仓建议只读摘要与账户资金。
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

import account_profile
import ai_result_service
import astock
import chat as chat_layer
import market
import portfolio as pf
import review_history
import sector_research_data as srd
import watchlist_store

from decision_cockpit_signals import (
    MAX_CANDIDATES,
    build_candidate_pool,
    compute_cash_exec,
    evaluate_market_short,
    evaluate_trend,
    evaluate_value,
)
from decision_cockpit_store import (
    create_plan as store_create_plan,
    freeze_plan as store_freeze_plan,
    get_current_plan as store_get_current_plan,
    get_plan as store_get_plan,
    get_signals_for_plan,
    list_plans as store_list_plans,
    upsert_evidence,
    upsert_signal,
)


class DecisionCockpitError(RuntimeError):
    """决策驱动舱未预期异常基类。"""


class DecisionCockpitMarketDataError(DecisionCockpitError):
    """市场核心数据（广度）不可用。"""


class DecisionCockpitModelError(DecisionCockpitError):
    """模型调用失败。"""


def _now_beijing() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _db_path() -> Any:
    return review_history.resolve_review_db_path()


def _codes_fingerprint(codes: list[str]) -> str:
    blob = json.dumps(sorted(set(codes)), ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# 数据读取（只读编排）
# ---------------------------------------------------------------------------


def _get_sector_codes() -> list[str]:
    """动态读取所有板块代表公司代码（不硬编码 PCB）。"""
    codes: list[str] = []
    seen: set[str] = set()
    for key in srd.list_sector_source_keys():
        src = srd.get_sector_source(key)
        if src is None:
            continue
        for c in src.representative_company_codes or []:
            if c not in seen:
                seen.add(c)
                codes.append(c)
    return codes


def _get_candidate_pool_inputs() -> dict:
    """读取候选池所需的各数据源。"""
    holdings = pf.get_portfolio_holdings_snapshot().get("holdings", [])
    wl = watchlist_store.load_watchlist()
    sector_codes = _get_sector_codes()

    emotion = _safe_call(market.get_short_term_emotion) or {}
    breadth = _safe_call(market.get_market_breadth) or {}
    turnover_top = _safe_call(market.get_turnover_top) or {}
    lianban = list(emotion.get("lianban_stocks") or []) if isinstance(emotion, dict) else []
    tt_stocks = list(turnover_top.get("stocks") or []) if isinstance(turnover_top, dict) else []
    high_turnover = list((breadth.get("data") or {}).get("high_turnover") or []) if isinstance(breadth, dict) else []
    return {
        "holdings": holdings,
        "watchlist": wl,
        "sector_codes": sector_codes,
        "lianban": lianban,
        "turnover_top": tt_stocks,
        "high_turnover": high_turnover,
    }


def _safe_call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 候选池 + 信号
# ---------------------------------------------------------------------------


def assemble_candidate_pool(*, max_candidates: int = MAX_CANDIDATES) -> list[dict]:
    """组装候选池（去重 + 受保护源优先）。"""
    inp = _get_candidate_pool_inputs()
    return build_candidate_pool(
        inp["holdings"], inp["watchlist"], inp["sector_codes"],
        inp["lianban"], inp["turnover_top"], inp["high_turnover"],
        max_candidates=max_candidates,
    )


def _evidence_path(code: str, kind: str) -> str:
    return f"{kind}/{code}"


def compute_candidate_signals(
    candidate: dict,
    *,
    evidence_log: list[dict] | None = None,
) -> list[dict]:
    """单个候选：拉 K 线 / 财务 / 估值分位 → 价值 + 趋势信号。

    任何数据源失败不抛异常，按 unknown 兜底并把失败登记到证据日志。"""
    code = candidate.get("code", "")
    sigs: list[dict] = []

    # K 线（趋势）
    bars: list[dict] = []
    try:
        bars = astock.kline(code, category=4, offset=80) or []
        if bars:
            upsert_evidence(_db_path(), _evidence_path(code, "kline"), {
                "n": len(bars), "first": bars[0], "last": bars[-1],
            })
            if evidence_log is not None:
                evidence_log.append({"path": _evidence_path(code, "kline"), "ok": True})
    except Exception as e:  # noqa: BLE001
        if evidence_log is not None:
            evidence_log.append({"path": _evidence_path(code, "kline"), "ok": False, "error": str(e)})
    sigs.extend(evaluate_trend(code, bars))

    # 财务 + 估值分位（价值）
    financials: dict = {}
    valuation: dict = {}
    try:
        financials = astock.financials(code) or {}
        if financials:
            upsert_evidence(_db_path(), _evidence_path(code, "financials"), financials)
    except Exception:  # noqa: BLE001
        financials = {}
    try:
        valuation = astock.valuation_percentile(code) or {}
        if valuation:
            upsert_evidence(_db_path(), _evidence_path(code, "valuation_percentile"), valuation)
    except Exception:  # noqa: BLE001
        valuation = {}
    sigs.extend(evaluate_value(code, valuation, financials))

    return sigs


def _compute_all_signals(candidates: list[dict]) -> tuple[str, list[dict]]:
    """为候选池全量计算信号，按 plan_id 落库。返回 (plan_id, signals)。"""
    plan_id = f"cockpit-{_codes_fingerprint([c['code'] for c in candidates])}-{_now_beijing()}"
    evidence_log: list[dict] = []
    all_sigs: list[dict] = []
    for c in candidates:
        sigs = compute_candidate_signals(c, evidence_log=evidence_log)
        for s in sigs:
            rec = {"plan_id": plan_id, "candidate_code": c["code"], **s}
            upsert_signal(
                _db_path(),
                plan_id=plan_id,
                candidate_code=c["code"],
                dimension=s["dimension"],
                label=s["label"],
                assessment=s["assessment"],
                confidence=s.get("confidence"),
                evidence_paths=[_evidence_path(c["code"], s["dimension"])],
            )
            all_sigs.append(rec)
    return plan_id, all_sigs


# ---------------------------------------------------------------------------
# 市场 + 账户 + 持仓建议 只读摘要
# ---------------------------------------------------------------------------


def _market_short_summary() -> dict:
    breadth = _safe_call(market.get_market_breadth) or {}
    emotion = _safe_call(market.get_short_term_emotion) or {}
    return evaluate_market_short(
        breadth if isinstance(breadth, dict) else None,
        emotion if isinstance(emotion, dict) else None,
    )


def _account_funding_summary() -> dict:
    st = account_profile.get_account_profile_status()
    if st["status"] != "valid":
        return {"configured": False, "data": None}
    return {"configured": True, "data": st["data"]}


def _portfolio_summary() -> dict:
    snap = pf.get_portfolio_holdings_snapshot().get("holdings", [])
    cash = _account_funding_summary()
    cash_avail = cash["data"]["available_cash"] if cash["configured"] else None
    holdings_view: list[dict] = []
    for h in snap:
        if not isinstance(h, dict):
            continue
        shares = h.get("shares")
        price = h.get("price")
        exe = compute_cash_exec(shares, price, cash_avail)
        holdings_view.append({
            "code": h.get("code"),
            "name": h.get("name"),
            "shares": shares,
            "cost": h.get("cost"),
            "price": price,
            "cash_executable": exe,
        })
    return {"cash": cash, "holdings": holdings_view}


def _portfolio_advice_summary() -> dict | None:
    """最新持仓建议只读摘要（无建议返回 None）。"""
    try:
        rec = ai_result_service.get_ai_result(ai_result_service.PORTFOLIO_ADVICE)
    except ai_result_service.AiResultCorruptedError:
        return None
    except Exception:  # noqa: BLE001
        return None
    if rec is None:
        return None
    return {
        "trade_date": rec.get("trade_date"),
        "generated_at": rec.get("generated_at"),
        "schema_version": rec.get("schema_version"),
        "stale": bool(rec.get("stale")),
    }


# ---------------------------------------------------------------------------
# LLM 解释（含确定性兜底）
# ---------------------------------------------------------------------------


def _deterministic_explanation(market_short: dict, signals: list[dict]) -> str:
    """LLM 不可用时的纯文本摘要（基于信号统计）。"""
    counts = {"strong": 0, "medium": 0, "weak": 0, "unknown": 0}
    for s in signals:
        counts[s.get("assessment", "unknown")] += 1
    parts = [
        f"市场状态：{market_short.get('status', 'unknown')}；"
        f"信号合计 {len(signals)} 条（强 {counts['strong']} / 中 "
        f"{counts['medium']} / 弱 {counts['weak']} / 未知 {counts['unknown']}）。",
    ]
    top_strong = [s for s in signals if s.get("assessment") == "strong"]
    top_weak = [s for s in signals if s.get("assessment") == "weak"]
    if top_strong:
        labels = ", ".join(f"{s['candidate_code']}/{s['label']}" for s in top_strong[:5])
        parts.append(f"强信号：{labels}。")
    if top_weak:
        labels = ", ".join(f"{s['candidate_code']}/{s['label']}" for s in top_weak[:5])
        parts.append(f"弱信号：{labels}。")
    return "".join(parts)


def _build_explanation_prompt(trade_date: str, market_short: dict, signals: list[dict]) -> list[dict]:
    summary = {
        "trade_date": trade_date,
        "market_short": market_short,
        "signal_counts": {},
        "top_strong": [],
        "top_weak": [],
    }
    counts: dict[str, int] = {}
    for s in signals:
        a = s.get("assessment", "unknown")
        counts[a] = counts.get(a, 0) + 1
    summary["signal_counts"] = counts
    summary["top_strong"] = [
        {"code": s["candidate_code"], "dimension": s["dimension"], "label": s["label"]}
        for s in signals if s.get("assessment") == "strong"
    ][:8]
    summary["top_weak"] = [
        {"code": s["candidate_code"], "dimension": s["dimension"], "label": s["label"]}
        for s in signals if s.get("assessment") == "weak"
    ][:8]
    return [
        {
            "role": "system",
            "content": "你是 A 股投资决策助手。根据提供的明日计划摘要（信号统计 + 市场状态），"
                       "用简洁的中文给出 3-5 句投资备忘，不要给出具体买卖指令，"
                       "不要编造数据。仅输出纯文本。",
        },
        {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
    ]


def generate_explanation(cfg: Any, trade_date: str, market_short: dict, signals: list[dict]) -> dict:
    """尝试 LLM 生成解释；失败回退到确定性摘要。"""
    fallback_text = _deterministic_explanation(market_short, signals)
    result = {"text": fallback_text, "source": "deterministic", "model": None}
    if cfg is None:
        return result
    try:
        messages = _build_explanation_prompt(trade_date, market_short, signals)
        parts: list[str] = []
        for ev in chat_layer.stream_messages(cfg, messages, use_tools=False):
            if not isinstance(ev, dict):
                continue
            etype = ev.get("type")
            if etype == "delta":
                t = ev.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif etype == "error":
                raise DecisionCockpitModelError(str(ev.get("message", ""))[:200])
            elif etype == "done":
                break
        text = "".join(parts).strip()
        if text:
            result = {"text": text, "source": "llm", "model": cfg.get("model")}
        return result
    except DecisionCockpitModelError:
        return result
    except Exception:  # noqa: BLE001
        return result


# ---------------------------------------------------------------------------
# 计划生成 / 读取（对外编排入口）
# ---------------------------------------------------------------------------


def generate_tomorrow_plan(
    trade_date: str,
    cfg: Any = None,
    *,
    force: bool = False,
) -> dict:
    """生成一个新的明日计划版本（候选池 + 信号 + 解释 + 持久化）。

    - 市场广度不可用 → 抛 ``DecisionCockpitMarketDataError``。
    - ``force=False`` 时，若当日已有 frozen 计划则不重复生成。
    """
    market_short = _market_short_summary()
    if market_short.get("status") == "unavailable":
        raise DecisionCockpitMarketDataError("市场核心数据暂不可用，无法生成明日计划")

    candidates = assemble_candidate_pool()
    if not candidates:
        raise DecisionCockpitError("候选池为空：请至少配置持仓、自选股或板块代表公司")

    # 重复生成保护
    if not force:
        existing = store_get_current_plan(_db_path(), trade_date)
        if existing and existing.get("status") == "frozen":
            return {
                "id": existing["id"],
                "trade_date": trade_date,
                "version": existing["version"],
                "status": existing["status"],
                "skipped": True,
                "reason": "frozen_exists",
            }

    signal_plan_id, signals = _compute_all_signals(candidates)
    explanation = generate_explanation(cfg, trade_date, market_short, signals)

    payload = {
        "schema_version": "tomorrow-plan.v1",
        "trade_date": trade_date,
        "generated_at": _now_beijing(),
        "signal_plan_id": signal_plan_id,
        "market_short": market_short,
        "account_funding": _account_funding_summary(),
        "portfolio": _portfolio_summary(),
        "advice": _portfolio_advice_summary(),
        "candidates": candidates,
        "signals": signals,
        "explanation": explanation,
    }
    plan = store_create_plan(_db_path(), trade_date=trade_date, payload=payload, generated_at=payload["generated_at"])
    return {**plan, "skipped": False}


def freeze_tomorrow_plan(plan_id: int, expected_version: int) -> dict:
    return store_freeze_plan(_db_path(), plan_id, expected_version=expected_version)


def get_current_plan(trade_date: str) -> dict | None:
    """读取当前计划（含信号）。"""
    plan = store_get_current_plan(_db_path(), trade_date)
    if plan is None:
        return None
    signal_plan_id = (plan.get("payload") or {}).get("signal_plan_id")
    plan["signals"] = get_signals_for_plan(_db_path(), signal_plan_id) if signal_plan_id else []
    return plan


def get_plan(plan_id: int) -> dict | None:
    """读取单个计划（含信号）。"""
    plan = store_get_plan(_db_path(), plan_id)
    if plan is None:
        return None
    signal_plan_id = (plan.get("payload") or {}).get("signal_plan_id")
    plan["signals"] = get_signals_for_plan(_db_path(), signal_plan_id) if signal_plan_id else []
    return plan


def list_plans(trade_date: str | None = None, limit: int = 30, offset: int = 0) -> list[dict]:
    return store_list_plans(_db_path(), trade_date, limit=limit, offset=offset)


def get_overview(trade_date: str) -> dict:
    """总览（只读聚合）：市场 / 账户 / 持仓建议 / 当前计划 / 候选池构成。"""
    market_short = _market_short_summary()
    current = store_get_current_plan(_db_path(), trade_date)
    inp = _get_candidate_pool_inputs()
    pool = build_candidate_pool(
        inp["holdings"], inp["watchlist"], inp["sector_codes"],
        inp["lianban"], inp["turnover_top"], inp["high_turnover"],
    )
    return {
        "trade_date": trade_date,
        "market_short": market_short,
        "account_funding": _account_funding_summary(),
        "advice": _portfolio_advice_summary(),
        "current_plan": current,
        "candidate_pool": pool,
    }
