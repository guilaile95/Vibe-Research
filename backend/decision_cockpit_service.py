"""明日决策驱动舱编排层：候选池 → 信号 → 计划 → LLM 解释（含确定性兜底）。

本模块是唯一对外编排入口；所有业务规则拆分到：
- ``decision_cockpit_signals``：纯阈值信号评估（strong/medium/weak/unknown）。
- ``decision_cockpit_store``：证据 / 信号 / 计划持久化。
- ``ai_result_service``：持仓建议只读全量快照（plan 内固化，UPSERT 不影响旧 plan）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
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
    RULE_VERSION_SHORT,
    RULE_VERSION_TREND,
    RULE_VERSION_VALUE,
    aggregate_candidate_dimensions,
    build_candidate_pool,
    compute_cash_exec,
    evaluate_candidate_short,
    evaluate_market_short,
    evaluate_trend,
    evaluate_value,
)
from decision_cockpit_store import (
    create_plan as store_create_plan,
    evidence_exists,
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


class DecisionCockpitSnapshotError(DecisionCockpitError):
    """缺少不可变每日复盘快照，无法生成计划。"""


_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now_beijing() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _db_path() -> Any:
    return review_history.resolve_review_db_path()


def _codes_fingerprint(codes: list[str]) -> str:
    blob = json.dumps(sorted(set(codes)), ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _validate_trade_date(trade_date: Any) -> str:
    """严格校验：date.fromisoformat；拒绝空/非法日历/未来日。"""
    if not isinstance(trade_date, str) or not trade_date.strip():
        raise DecisionCockpitError("trade_date 不能为空")
    raw = trade_date.strip()
    if not _TRADE_DATE_RE.match(raw):
        raise DecisionCockpitError("trade_date 必须是 YYYY-MM-DD 格式")
    try:
        from datetime import date as _date
        d = _date.fromisoformat(raw)
    except ValueError as e:
        raise DecisionCockpitError(f"trade_date 非法日历日期：{raw}") from e
    # 规范化回 ISO（fromisoformat 已保证合法）
    normalized = d.isoformat()
    if normalized != raw:
        raise DecisionCockpitError(f"trade_date 非法：{raw}")
    today = _beijing_today()
    if d > today:
        raise DecisionCockpitError(f"trade_date 不能是未来日期：{raw}")
    return normalized


def _beijing_today():
    from datetime import datetime, timezone, timedelta, date as _date
    return datetime.now(timezone(timedelta(hours=8))).date()


def _require_latest_review_trade_date(trade_date: str) -> dict:
    """生成仅允许最新已保存不可变复盘快照的 trade_date。

    不一致 → DecisionCockpitSnapshotError(409)
    「明日计划只能基于最新已保存复盘生成」
    """
    latest = review_history.get_latest_review_history_snapshot(trade_date=None)
    if latest is None:
        raise DecisionCockpitSnapshotError(
            "尚无已保存的每日复盘快照，请先生成并保存复盘后再生成明日计划"
        )
    latest_td = latest.get("trade_date")
    if not latest_td or str(latest_td) != trade_date:
        raise DecisionCockpitSnapshotError(
            "明日计划只能基于最新已保存复盘生成"
        )
    snap_id = latest.get("id")
    payload_hash = latest.get("payload_hash")
    if snap_id is None or not payload_hash:
        raise DecisionCockpitSnapshotError(
            f"最新复盘快照缺少 id/payload_hash，拒绝绑定（trade_date={trade_date}）"
        )
    return {
        "source_review_id": int(snap_id),
        "source_review_hash": str(payload_hash),
        "source_review_cutoff_at": latest.get("data_cutoff"),
        "source_review_generated_at": latest.get("generated_at"),
        "source_review_trade_date": str(latest_td),
    }


def _safe_call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


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
    high_turnover = (
        list((breadth.get("data") or {}).get("high_turnover") or [])
        if isinstance(breadth, dict)
        else []
    )
    amount_top = (
        list((breadth.get("data") or {}).get("amount_top") or [])
        if isinstance(breadth, dict)
        else []
    )
    return {
        "holdings": holdings,
        "watchlist": wl,
        "sector_codes": sector_codes,
        "lianban": lianban,
        "turnover_top": tt_stocks or amount_top,
        "high_turnover": high_turnover,
        "emotion": emotion if isinstance(emotion, dict) else {},
        "breadth": breadth if isinstance(breadth, dict) else {},
    }


def _code_set(items: list[dict] | None) -> set[str]:
    out: set[str] = set()
    for it in items or []:
        if isinstance(it, dict):
            c = it.get("code")
            if isinstance(c, str) and len(c) == 6 and c.isdigit():
                out.add(c)
    return out


def _lianban_meta_map(lianban: list[dict] | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in lianban or []:
        if not isinstance(it, dict):
            continue
        c = it.get("code")
        if isinstance(c, str) and len(c) == 6:
            out[c] = it
    return out


def _industry_rank_for_code(code: str, board_rows: list[dict] | None) -> int | None:
    """若候选在行业榜中有精确 code 匹配则返回 rank；否则 None。

    行业榜通常是板块级，不一定含个股 code；有则用，无则 unknown。
    """
    if not board_rows:
        return None
    for i, row in enumerate(board_rows):
        if not isinstance(row, dict):
            continue
        if row.get("code") == code:
            return int(row.get("rank") or (i + 1))
        # 部分源把成分在 members 里
        members = row.get("members") or row.get("stocks") or []
        if isinstance(members, list):
            for m in members:
                mc = m.get("code") if isinstance(m, dict) else m
                if mc == code:
                    return int(row.get("rank") or (i + 1))
    return None


# ---------------------------------------------------------------------------
# 不可变复盘快照绑定（P2）
# ---------------------------------------------------------------------------


def _bind_review_snapshot(trade_date: str) -> dict:
    """绑定最新已保存不可变复盘快照；trade_date 必须与最新快照完全一致。

    绝不重新生成复盘或伪造 snapshot。非最新 → 409。
    """
    return _require_latest_review_trade_date(trade_date)


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
    market_short: dict | None = None,
    short_ctx: dict | None = None,
    evidence_log: list[dict] | None = None,
) -> list[dict]:
    """单个候选：价值 + 趋势 + 短线信号。

    任何数据源失败不抛异常，按 unknown 兜底并把失败登记到证据日志。
    """
    code = candidate.get("code", "")
    sigs: list[dict] = []
    ctx = short_ctx or {}

    # K 线（趋势，不复权）
    bars: list[dict] = []
    try:
        bars = astock.kline(code, category=4, offset=80) or []
        if bars:
            upsert_evidence(_db_path(), _evidence_path(code, "kline"), {
                "n": len(bars), "first": bars[0], "last": bars[-1],
                "price_adjustment": "none",
            })
            if evidence_log is not None:
                evidence_log.append({"path": _evidence_path(code, "kline"), "ok": True})
    except Exception as e:  # noqa: BLE001
        if evidence_log is not None:
            evidence_log.append({
                "path": _evidence_path(code, "kline"), "ok": False, "error": str(e),
            })
    sigs.extend(evaluate_trend(code, bars))

    # 财务 + 估值分位 + full_valuation（价值）
    financials: dict = {}
    valuation: dict = {}
    full_val: dict = {}
    try:
        financials = astock.financials(code) or {}
        if financials:
            upsert_evidence(_db_path(), _evidence_path(code, "financials"), financials)
    except Exception:  # noqa: BLE001
        financials = {}
    try:
        valuation = astock.valuation_percentile(code) or {}
        if valuation:
            upsert_evidence(
                _db_path(), _evidence_path(code, "valuation_percentile"), valuation,
            )
    except Exception:  # noqa: BLE001
        valuation = {}
    try:
        full_val = astock.full_valuation(code) or {}
        if full_val:
            upsert_evidence(
                _db_path(), _evidence_path(code, "full_valuation"), full_val,
            )
    except Exception:  # noqa: BLE001
        full_val = {}
    sigs.extend(evaluate_value(code, valuation, financials, full_val or None))

    # 候选级短线
    sigs.extend(evaluate_candidate_short(
        code,
        market_short=market_short,
        lianban_codes=ctx.get("lianban_codes"),
        turnover_top_codes=ctx.get("turnover_top_codes"),
        high_turnover_codes=ctx.get("high_turnover_codes"),
        sector_rank=ctx.get("sector_rank_by_code", {}).get(code),
        lianban_meta=ctx.get("lianban_meta", {}).get(code),
    ))

    return sigs


def _build_short_context(inp: dict) -> dict:
    lianban = inp.get("lianban") or []
    turnover = inp.get("turnover_top") or []
    high_to = inp.get("high_turnover") or []
    sector_rank_by_code: dict[str, int] = {}
    board = _safe_call(lambda: market.get_board_ranking("industry", top_n=100))
    board_rows: list[dict] = []
    if isinstance(board, dict):
        data = board.get("data")
        if isinstance(data, list):
            board_rows = data
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            board_rows = data["items"]
    return {
        "lianban_codes": _code_set(lianban),
        "turnover_top_codes": _code_set(turnover),
        "high_turnover_codes": _code_set(high_to),
        "lianban_meta": _lianban_meta_map(lianban),
        "sector_rank_by_code": sector_rank_by_code,
        "board_rows": board_rows,
    }


def _compute_all_signals(
    candidates: list[dict],
    *,
    market_short: dict,
    short_ctx: dict,
) -> tuple[str, list[dict]]:
    """为候选池全量计算信号，按 plan_id 落库。返回 (plan_id, signals)。"""
    plan_id = f"cockpit-{_codes_fingerprint([c['code'] for c in candidates])}-{_now_beijing()}"
    evidence_log: list[dict] = []
    all_sigs: list[dict] = []
    # 预填行业 rank（若 board 含个股 code）
    board_rows = short_ctx.get("board_rows") or []
    rank_map = dict(short_ctx.get("sector_rank_by_code") or {})
    for c in candidates:
        code = c["code"]
        if code not in rank_map:
            r = _industry_rank_for_code(code, board_rows)
            if r is not None:
                rank_map[code] = r
    short_ctx = {**short_ctx, "sector_rank_by_code": rank_map}

    for c in candidates:
        sigs = compute_candidate_signals(
            c,
            market_short=market_short,
            short_ctx=short_ctx,
            evidence_log=evidence_log,
        )
        for s in sigs:
            dim = s["dimension"]
            refs = list(s.get("evidence_refs") or [])
            if not refs:
                # 按维度映射到真实 evidence 路径（禁止 value/{code} 这种维度伪路径）
                if dim == "value":
                    refs = [
                        _evidence_path(c["code"], "financials"),
                        _evidence_path(c["code"], "valuation_percentile"),
                        _evidence_path(c["code"], "full_valuation"),
                    ]
                elif dim == "trend":
                    refs = [_evidence_path(c["code"], "kline")]
                elif dim == "short":
                    refs = ["market/short"]
                else:
                    refs = []
            # 只保留已落库的 evidence（避免悬空引用）
            live_refs = [p for p in refs if evidence_exists(_db_path(), p) or p.startswith("market/")]
            if not live_refs and refs:
                # 数据缺口：仍写信号但 evidence_refs 空 + data_status unknown
                live_refs = []
            rule_ver = s.get("rule_version")
            if not rule_ver:
                if dim == "value":
                    rule_ver = RULE_VERSION_VALUE
                elif dim == "trend":
                    rule_ver = RULE_VERSION_TREND
                elif dim == "short":
                    rule_ver = RULE_VERSION_SHORT
            data_status = s.get("data_status")
            if data_status is None:
                if s.get("assessment") == "unknown":
                    data_status = "unknown"
                elif live_refs:
                    data_status = "normal"
                else:
                    data_status = "partial"
            raw_value = s.get("value") if "value" in s else s.get("raw_value")
            ctx = s.get("context") if isinstance(s.get("context"), dict) else None
            counter = s.get("counter_evidence")
            rec = {
                "plan_id": plan_id,
                "candidate_code": c["code"],
                **s,
                "evidence_refs": live_refs,
                "evidence_paths": live_refs,
                "rule_version": rule_ver,
                "data_status": data_status,
                "raw_value": raw_value,
            }
            upsert_signal(
                _db_path(),
                plan_id=plan_id,
                candidate_code=c["code"],
                dimension=dim,
                label=s["label"],
                assessment=s["assessment"],
                confidence=s.get("confidence"),
                evidence_refs=live_refs,
                raw_value=raw_value,
                context=ctx,
                counter_evidence=counter if isinstance(counter, list) else None,
                data_status=data_status,
                rule_version=rule_ver,
            )
            all_sigs.append(rec)
    return plan_id, all_sigs


# ---------------------------------------------------------------------------
# 市场 + 账户 + 持仓建议全量快照 + 现金可执行性
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
        return {
            "configured": False,
            "data": None,
            "status": st.get("status"),
            "reason_code": st.get("reason_code"),
        }
    return {
        "configured": True,
        "data": st["data"],
        "status": "valid",
        "reason_code": None,
    }


def _payload_hash(obj: Any) -> str:
    blob = json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _portfolio_advice_full_snapshot(trade_date: str | None = None) -> dict | None:
    """持仓建议完整快照（仅精确 trade_date，无跨日 fallback）。

    包含 result_type / trade_date / generated_at / input_fingerprint /
    payload_hash / validated payload。后续 UPSERT 不会改写已固化进 plan 的副本。
    无精确匹配 → None（调用方写 warning）。
    """
    if not trade_date:
        return None
    try:
        rec = ai_result_service.get_ai_result(
            ai_result_service.PORTFOLIO_ADVICE, trade_date=trade_date,
        )
    except ai_result_service.AiResultCorruptedError:
        return None
    except Exception:  # noqa: BLE001
        return None
    if rec is None:
        return None
    # 二次校验：绝不接受其他 trade_date
    if str(rec.get("trade_date") or "") != str(trade_date):
        return None

    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return None

    fingerprint = None
    try:
        db = review_history.resolve_review_db_path()
        from ai_result_store import get_result
        raw = get_result(db, ai_result_service.PORTFOLIO_ADVICE, trade_date)
        if isinstance(raw, dict):
            fingerprint = raw.get("input_fingerprint")
    except Exception:  # noqa: BLE001
        fingerprint = None

    snapshot = {
        "result_type": rec.get("result_type") or ai_result_service.PORTFOLIO_ADVICE,
        "trade_date": rec.get("trade_date"),
        "generated_at": rec.get("generated_at"),
        "schema_version": rec.get("schema_version"),
        "model_provider": rec.get("model_provider"),
        "model_name": rec.get("model_name"),
        "input_fingerprint": fingerprint,
        "payload": copy.deepcopy(payload),
        "stale": bool(rec.get("stale")),
    }
    snapshot["payload_hash"] = _payload_hash(snapshot["payload"])
    return snapshot


def _advice_buy_actions(advice_snapshot: dict | None) -> list[dict]:
    """从建议 payload 提取买入类动作（add），携带 execution_quantity / estimated_amount。"""
    if not isinstance(advice_snapshot, dict):
        return []
    payload = advice_snapshot.get("payload") or {}
    holdings = payload.get("holdings") if isinstance(payload, dict) else None
    if not isinstance(holdings, list):
        return []
    actions: list[dict] = []
    for h in holdings:
        if not isinstance(h, dict):
            continue
        action = h.get("action")
        if action not in ("add", "buy"):
            continue
        actions.append({
            "code": h.get("code"),
            "name": h.get("name"),
            "action": action,
            "execution_quantity": h.get("execution_quantity"),
            "estimated_amount": h.get("estimated_amount"),
            "execution_size_pct_of_holding": h.get("execution_size_pct_of_holding"),
            "current_price": h.get("current_price"),
        })
    return actions


def _quote_map(codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    try:
        q = astock.tencent_quote(codes)
        return q if isinstance(q, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _cash_executability_from_advice(
    advice_snapshot: dict | None,
    available_cash: float | None,
) -> dict:
    """P7：按建议原始买入动作算现金可执行性，不用当前持仓股数当买入需求。

    支持 execution_quantity；若无数量但有 estimated_amount + 最新价，
    则反推股数（floor 到 100 股）。现金未配置 → data_status=unavailable。
    """
    if advice_snapshot is None:
        return {
            "available_cash": available_cash,
            "cash_configured": available_cash is not None,
            "data_status": "unavailable" if available_cash is None else "normal",
            "warning": "该交易日没有已保存持仓建议",
            "actions": [],
        }
    actions = _advice_buy_actions(advice_snapshot)
    codes = [a["code"] for a in actions if isinstance(a.get("code"), str)]
    quotes = _quote_map(codes)
    items: list[dict] = []
    for a in actions:
        code = a.get("code")
        q = quotes.get(code) if isinstance(code, str) else None
        price = None
        if isinstance(q, dict):
            price = q.get("price")
        if price is None:
            price = a.get("current_price")
        intended = a.get("execution_quantity")
        est_amt = a.get("estimated_amount")
        # estimated_amount → 反推股数（当无 execution_quantity）
        if (intended is None or intended <= 0) and est_amt is not None and price:
            try:
                p = float(price)
                amt = float(est_amt)
                if p > 0 and amt > 0:
                    intended = int(amt // p)
            except (TypeError, ValueError):
                pass
        exe = compute_cash_exec(intended, price, available_cash)
        if available_cash is None:
            exe["data_status"] = "unavailable"
        elif exe.get("reason") == "invalid_inputs":
            exe["data_status"] = "unknown"
        elif exe.get("reason") in ("insufficient_cash", "partial"):
            exe["data_status"] = "partial"
        else:
            exe["data_status"] = "normal"
        items.append({
            "code": code,
            "name": a.get("name"),
            "action": a.get("action"),
            "intended_quantity": intended,
            "execution_quantity": a.get("execution_quantity"),
            "estimated_amount": est_amt,
            "estimated_amount_from_advice": est_amt,
            **exe,
        })
    data_status = "normal"
    if available_cash is None:
        data_status = "unavailable"
    elif not items:
        data_status = "normal"
    return {
        "available_cash": available_cash,
        "cash_configured": available_cash is not None,
        "data_status": data_status,
        "actions": items,
    }


def _portfolio_summary(advice_snapshot: dict | None = None) -> dict:
    """持仓只读摘要 + 基于建议动作的现金可执行性。"""
    snap = pf.get_portfolio_holdings_snapshot().get("holdings", [])
    cash = _account_funding_summary()
    cash_avail = cash["data"]["available_cash"] if cash["configured"] else None
    holdings_view: list[dict] = []
    for h in snap:
        if not isinstance(h, dict):
            continue
        holdings_view.append({
            "code": h.get("code"),
            "name": h.get("name"),
            "shares": h.get("shares"),
            "cost": h.get("cost"),
            "price": h.get("price"),
        })
    cash_exec = _cash_executability_from_advice(advice_snapshot, cash_avail)
    return {
        "cash": cash,
        "holdings": holdings_view,
        "cash_executability": cash_exec,
    }


# ---------------------------------------------------------------------------
# LLM 解释（仅解释，不改确定性结果）
# ---------------------------------------------------------------------------


def _deterministic_explanation(market_short: dict, signals: list[dict]) -> str:
    """LLM 不可用时的纯文本摘要（基于信号统计）。"""
    counts = {"strong": 0, "medium": 0, "weak": 0, "unknown": 0}
    for s in signals:
        counts[s.get("assessment", "unknown")] = counts.get(s.get("assessment", "unknown"), 0) + 1
    parts = [
        f"市场状态：{market_short.get('status', 'unknown')}；"
        f"信号合计 {len(signals)} 条（强 {counts.get('strong', 0)} / 中 "
        f"{counts.get('medium', 0)} / 弱 {counts.get('weak', 0)} / 未知 {counts.get('unknown', 0)}）。",
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
        "market_short": {"status": market_short.get("status")},
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
            "content": (
                "你是 A 股投资决策助手。根据提供的明日计划摘要（信号统计 + 市场状态），"
                "用简洁的中文给出 3-5 句投资备忘，不要给出具体买卖指令，"
                "不要编造数据，不要修改或覆盖任何确定性信号。仅输出纯文本。"
            ),
        },
        {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
    ]


def generate_explanation(cfg: Any, trade_date: str, market_short: dict, signals: list[dict]) -> dict:
    """尝试 LLM 生成解释；失败回退到确定性摘要。LLM 只解释，不改信号/候选/动作。"""
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
                # 解释失败不抛 502：仍返回确定性兜底
                return result
            elif etype == "done":
                break
        text = "".join(parts).strip()
        if text:
            result = {"text": text, "source": "llm", "model": cfg.get("model")}
        return result
    except Exception:  # noqa: BLE001 — explain-only fail-open
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
    """生成一个新的明日计划 draft（候选池 + 信号 + 解释 + 持久化）。

    - trade_date 必须 YYYY-MM-DD；
    - 必须绑定已有 daily_review_snapshots（缺失 → 409）；
    - 市场广度不可用 → ``DecisionCockpitMarketDataError``；
    - ``force=False`` 时，若当日已有 frozen 计划则跳过（不生成新 draft 也可返回提示）；
    - 新 draft 不 supersede frozen，不成为 current（见 store.create_plan）；
    - LLM 仅解释，失败回退确定性文本。
    """
    trade_date = _validate_trade_date(trade_date)

    # P2：仅允许最新已保存复盘 trade_date（先于任何写操作 / 市场拉取）
    review_binding = _bind_review_snapshot(trade_date)

    market_short = _market_short_summary()
    if market_short.get("status") == "unavailable":
        raise DecisionCockpitMarketDataError("市场核心数据暂不可用，无法生成明日计划")

    # 市场短线证据（供 short 维度 evidence_refs）
    try:
        upsert_evidence(_db_path(), "market/short", {
            "status": market_short.get("status"),
            "warnings": market_short.get("warnings"),
            "trade_date": trade_date,
        })
    except Exception:  # noqa: BLE001
        pass

    # 重复生成保护：已有 frozen 且未 force → 返回现有 frozen（不写）
    if not force:
        existing = store_get_current_plan(_db_path(), trade_date)
        if existing and existing.get("status") == "frozen":
            return {
                "id": existing["id"],
                "trade_date": trade_date,
                "version": existing["version"],
                "status": existing["status"],
                "is_current": existing.get("is_current", 1),
                "skipped": True,
                "reason": "frozen_exists",
            }

    inp = _get_candidate_pool_inputs()
    candidates = build_candidate_pool(
        inp["holdings"], inp["watchlist"], inp["sector_codes"],
        inp["lianban"], inp["turnover_top"], inp["high_turnover"],
    )
    if not candidates:
        raise DecisionCockpitError("候选池为空：请至少配置持仓、自选股或板块代表公司")

    short_ctx = _build_short_context(inp)
    signal_plan_id, signals = _compute_all_signals(
        candidates, market_short=market_short, short_ctx=short_ctx,
    )

    # P3：仅精确 trade_date 建议；无则 None + warning（不跨日、不触发 LLM）
    warnings: list[str] = []
    advice_snapshot = _portfolio_advice_full_snapshot(trade_date)
    if advice_snapshot is None:
        warnings.append("该交易日没有已保存持仓建议")
    portfolio = _portfolio_summary(advice_snapshot)
    explanation = generate_explanation(cfg, trade_date, market_short, signals)

    # 候选级三维摘要（value/trend/short；≥3 可用信号才聚合，否则 unknown）
    candidate_summaries = aggregate_candidate_dimensions(candidates, signals)

    payload = {
        "schema_version": "tomorrow-plan.v1",
        "trade_date": trade_date,
        "generated_at": _now_beijing(),
        "signal_plan_id": signal_plan_id,
        # P2 绑定
        "source_review_id": review_binding["source_review_id"],
        "source_review_hash": review_binding["source_review_hash"],
        "source_review_cutoff_at": review_binding["source_review_cutoff_at"],
        "source_review_generated_at": review_binding.get("source_review_generated_at"),
        "market_short": market_short,
        "account_funding": portfolio["cash"],
        "portfolio": {
            "holdings": portfolio["holdings"],
            "cash_executability": portfolio["cash_executability"],
        },
        # P3：完整建议快照（非薄摘要；可为 null）
        "source_advice_snapshot": advice_snapshot,
        "warnings": warnings,
        "candidates": candidates,
        "candidate_summaries": candidate_summaries,
        "signals": signals,
        "explanation": explanation,
    }
    plan = store_create_plan(
        _db_path(),
        trade_date=trade_date,
        payload=payload,
        generated_at=payload["generated_at"],
    )
    return {**plan, "skipped": False}


def freeze_tomorrow_plan(plan_id: int, expected_version: int) -> dict:
    return store_freeze_plan(_db_path(), plan_id, expected_version=expected_version)


def get_current_plan(trade_date: str) -> dict | None:
    """读取当前计划（含信号）。无 current frozen 时返回 None。"""
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
    """总览（只读聚合）：市场 / 账户 / 持仓建议 / 当前计划 / 候选池构成。

    只读路径不写文件、不建表、不生成计划、不迁移 schema。
    历史 trade_date（非最新复盘日）只读已保存计划，不把「今日」实时
    市场/候选池伪装成历史数据。
    """
    try:
        trade_date = _validate_trade_date(trade_date)
    except DecisionCockpitError:
        # 非法日期：仍返回空壳（HTTP 层可 400；此处兜底）
        raise

    latest = review_history.get_latest_review_history_snapshot(trade_date=None)
    latest_td = str(latest.get("trade_date")) if latest else None
    is_latest_review_day = (latest_td is not None and trade_date == latest_td)

    plans = store_list_plans(_db_path(), trade_date, limit=20, offset=0)
    current = store_get_current_plan(_db_path(), trade_date)

    warnings: list[str] = []
    if is_latest_review_day:
        market_short = _market_short_summary()
        inp = _get_candidate_pool_inputs()
        pool = build_candidate_pool(
            inp["holdings"], inp["watchlist"], inp["sector_codes"],
            inp["lianban"], inp["turnover_top"], inp["high_turnover"],
        )
        account = _account_funding_summary()
        advice = _portfolio_advice_full_snapshot(trade_date)
    else:
        # 历史日：只读已保存计划内固化的快照；不拉 live 市场/K 线/财务
        market_short = None
        pool = []
        account = {"configured": False, "data": None, "status": "historical_readonly"}
        advice = None
        if current and isinstance(current.get("payload"), dict):
            pl = current["payload"]
            market_short = pl.get("market_short")
            pool = list(pl.get("candidates") or [])
            account = pl.get("account_funding") or account
            advice = pl.get("source_advice_snapshot")
        elif plans:
            # 无 current 时仍不伪造 live pool
            pass
        warnings.append("历史交易日仅展示已保存计划，不混入今日实时行情")

    if advice is None and is_latest_review_day:
        warnings.append("该交易日没有已保存持仓建议")

    advice_summary = None
    if isinstance(advice, dict):
        advice_summary = {
            "result_type": advice.get("result_type"),
            "trade_date": advice.get("trade_date"),
            "generated_at": advice.get("generated_at"),
            "input_fingerprint": advice.get("input_fingerprint"),
            "payload_hash": advice.get("payload_hash"),
            "stale": advice.get("stale"),
            "schema_version": advice.get("schema_version"),
        }

    return {
        "trade_date": trade_date,
        "is_latest_review_day": is_latest_review_day,
        "latest_review_trade_date": latest_td,
        "market_short": market_short,
        "account_funding": account,
        "advice": advice_summary,
        "current_plan": current,
        "candidate_pool": pool,
        "plans": plans,
        "warnings": warnings,
    }
