"""AR1: Canonical manual Account Reality & Settled NAV Candidate v0.1.

把 S1A ledger-derived positions + 手工当前账户事实（account_profile）+ settled
收盘价事实（kline 日线 close/date）放进一个可审计、可对账、fail-closed 的账户现实层。

本轮边界：
- primary authority 是用户显式确认的 account_profile；legacy profile 不自动提升
- ledger cash 是 reconciliation candidate，不是第二 canonical cash
- settled NAV 使用 MANUAL CURRENT CASH FACT（account_profile.available_cash），
  ledger_cash_candidate 与 cash_reconciliation 同时输出供审计
- settled NAV 的跨组件 cutoff 未证明，保持 non-canonical；不建 NAV history / drawdown
- positions 只来自 S1A derivation（不求和 portfolio.json）
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import account_event_store
import account_profile
import astock
import cash_event_service
import position_reality_service
import trade_ledger_service
import trade_ledger_store

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

_FACT_MANUAL = "MANUAL_CURRENT_FACT"
_FACT_DERIVED = "DERIVED_FACT"
_CASH_SOURCE_ACCOUNT_PROFILE = "ACCOUNT_PROFILE"
_CASH_SOURCE_LEDGER = "LEDGER_DERIVED"
_CASH_COVERAGE_TRADES_ONLY = "TRADES_ONLY"
_CASH_COVERAGE_TRADES_PLUS_CASH_EVENTS = "TRADES_PLUS_MANUAL_CASH_EVENTS"

_REASON_CORPORATE_ACTION_UNSUPPORTED = "CORPORATE_ACTION_UNSUPPORTED"
_REASON_ACCOUNT_PROFILE_CORRUPTED = "ACCOUNT_PROFILE_CORRUPTED"
_REASON_CASH_UNKNOWN = "CASH_UNKNOWN"
_REASON_OPENING_CASH_UNKNOWN = "OPENING_CASH_UNKNOWN"
_REASON_NOT_BOOTSTRAPPED = "NOT_BOOTSTRAPPED"
_REASON_PRICING_PARTIAL = "PRICING_PARTIAL"
_REASON_PRICING_UNAVAILABLE = "PRICING_UNAVAILABLE"
_REASON_PRICING_MIXED_CUTOFF = "PRICING_MIXED_CUTOFF"
_REASON_CASH_EFFECTIVE_AT_UNPROVEN = "CASH_EFFECTIVE_AT_UNPROVEN"
_REASON_ACCOUNT_TOTAL_ASSETS_UNPROVEN = "ACCOUNT_TOTAL_ASSETS_UNPROVEN"
_REASON_ACCOUNT_FACT_STALE = "ACCOUNT_FACT_STALE_RECONFIRM_REQUIRED"
_REASON_ACCOUNT_MUTATION_TIME_INVALID = "ACCOUNT_MUTATION_TIME_INVALID"
_REASON_POSITION_AUTHORITY_NOT_CANONICAL = "POSITION_AUTHORITY_NOT_CANONICAL"
_REASON_ACCOUNT_CASH_RECONCILIATION_MISMATCH = "ACCOUNT_CASH_RECONCILIATION_MISMATCH"
_REASON_ACCOUNT_CASH_RECONCILIATION_UNKNOWN = "ACCOUNT_CASH_RECONCILIATION_UNKNOWN"
_REASON_ACCOUNT_COVERAGE_INCOMPLETE = "ACCOUNT_COVERAGE_INCOMPLETE"
_REASON_NAV_COMPONENT_CUTOFF_MISMATCH = "NAV_COMPONENT_CUTOFF_MISMATCH"
_TEMPORAL_UNPROVEN = "UNPROVEN"
_TEMPORAL_PROVEN = "PROVEN"
_NAV_TEMPORAL_MIXED_UNPROVEN = "MIXED_UNPROVEN"
_NAV_TEMPORAL_UNAVAILABLE = "UNAVAILABLE"


class AccountRealityError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _latest_relevant_mutation() -> tuple[str | None, str | None]:
    """Return the latest durable account mutation recording/effective time.

    Reads active and voided rows so a correction/void cannot make a newer mutation
    disappear from the freshness decision. Invalid stored time fails the authority
    closed without rewriting either ledger.
    """
    db_path = trade_ledger_service.resolve_db_path()
    timestamps: list[datetime] = []
    try:
        events = account_event_store.list_events(db_path, include_voided=True)
        trades = trade_ledger_store.list_records(db_path, include_voided=True, limit=None)
    except Exception:
        return None, _REASON_ACCOUNT_MUTATION_TIME_INVALID
    trades = [
        row
        for row in trades
        if row.get("execution_status") in {"full", "partial"}
        and (row.get("actual_quantity") or 0) > 0
    ]
    for row, fields in (
        *((row, ("created_at", "voided_at")) for row in events),
        *((row, ("created_at", "voided_at", "executed_at")) for row in trades),
    ):
        for field in fields:
            raw = row.get(field)
            if raw in (None, ""):
                continue
            parsed = _parse_utc(raw)
            if parsed is None:
                return None, _REASON_ACCOUNT_MUTATION_TIME_INVALID
            timestamps.append(parsed)
    if not timestamps:
        return None, None
    latest = max(timestamps)
    return latest.isoformat(timespec="microseconds"), None


def _valid_price(value: Any) -> float | None:
    """finite 且 > 0 的价格才有效。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        return None
    return number


def _valid_price_date(value: Any) -> str | None:
    """从 kline bar 的 datetime/date 提取合法 YYYY-MM-DD；非法 → None（不冒充 cutoff）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    date_part = m.group(1)
    try:
        datetime.strptime(date_part, "%Y-%m-%d")
    except ValueError:
        return None
    return date_part


# ---------------------------------------------------------------------------
# Cash reality
# ---------------------------------------------------------------------------


def _manual_profile_fact(
    field: str,
    *,
    unproven_reason: str,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one profile field without promoting legacy updated_at to effective_at."""
    status = status or account_profile.get_account_profile_status()
    profile = status.get("data")
    if status["status"] != "valid" or profile is None:
        fact_status = (
            "CORRUPTED"
            if status["status"] == "corrupted"
            else "UNKNOWN"
        )
        reason_code = (
            _REASON_ACCOUNT_PROFILE_CORRUPTED
            if fact_status == "CORRUPTED"
            else _REASON_CASH_UNKNOWN
        )
        return {
            "value": None,
            "source": _CASH_SOURCE_ACCOUNT_PROFILE,
            "updated_at": None,
            "recorded_at": None,
            "effective_at": None,
            "temporal_status": _TEMPORAL_UNPROVEN,
            "temporal_reason_code": unproven_reason,
            "authority": None,
            "authority_state": "CORRUPTED" if fact_status == "CORRUPTED" else "UNPROVEN",
            "confirmation_id": None,
            "fact_type": _FACT_MANUAL,
            "status": fact_status,
            "reason_code": reason_code,
        }
    confirmed = profile.get("confirmation_status") == "CONFIRMED"
    return {
        "value": round(float(profile[field]), 2),
        "source": _CASH_SOURCE_ACCOUNT_PROFILE,
        "updated_at": profile.get("updated_at"),
        "recorded_at": profile.get("recorded_at") if confirmed else None,
        "effective_at": profile.get("effective_at") if confirmed else None,
        "temporal_status": _TEMPORAL_PROVEN if confirmed else _TEMPORAL_UNPROVEN,
        "temporal_reason_code": None if confirmed else unproven_reason,
        "authority": profile.get("authority") if confirmed else None,
        "authority_state": "CANONICAL" if confirmed else "UNPROVEN",
        "confirmation_id": profile.get("confirmation_id") if confirmed else None,
        "fact_type": _FACT_MANUAL,
        "status": "AVAILABLE",
        "reason_code": None if confirmed else unproven_reason,
    }


def _current_cash_fact(status: dict[str, Any] | None = None) -> dict[str, Any]:
    return _manual_profile_fact(
        "available_cash",
        unproven_reason=_REASON_CASH_EFFECTIVE_AT_UNPROVEN,
        status=status,
    )


def _current_total_assets_fact(status: dict[str, Any] | None = None) -> dict[str, Any]:
    return _manual_profile_fact(
        "total_assets",
        unproven_reason=_REASON_ACCOUNT_TOTAL_ASSETS_UNPROVEN,
        status=status,
    )


def _apply_mutation_freshness(
    fact: dict[str, Any],
    latest_mutation_at: str | None,
    mutation_error: str | None,
) -> dict[str, Any]:
    if fact.get("authority_state") != "CANONICAL":
        return fact
    if mutation_error is not None:
        return {
            **fact,
            "status": "UNKNOWN",
            "authority_state": "UNKNOWN",
            "temporal_status": _TEMPORAL_UNPROVEN,
            "temporal_reason_code": mutation_error,
            "reason_code": mutation_error,
        }
    recorded = _parse_utc(fact.get("recorded_at"))
    latest = _parse_utc(latest_mutation_at)
    if recorded is None:
        return {
            **fact,
            "status": "UNKNOWN",
            "authority_state": "UNKNOWN",
            "temporal_status": _TEMPORAL_UNPROVEN,
            "temporal_reason_code": _REASON_ACCOUNT_MUTATION_TIME_INVALID,
            "reason_code": _REASON_ACCOUNT_MUTATION_TIME_INVALID,
        }
    if latest is not None and latest > recorded:
        return {
            **fact,
            "status": "STALE",
            "authority_state": "STALE",
            "temporal_status": "STALE",
            "temporal_reason_code": _REASON_ACCOUNT_FACT_STALE,
            "reason_code": _REASON_ACCOUNT_FACT_STALE,
            "stale_since": latest_mutation_at,
        }
    return fact


def _ledger_cash_candidate(derived: dict[str, Any]) -> dict[str, Any]:
    """opening_cash + Σ effective active executed trade net_cash_flow
    + Σ active supported cash event delta（TRADES_PLUS_MANUAL_CASH_EVENTS candidate）。

    仅当 bootstrap 完成且 opening_cash 已知才能计算；否则 UNKNOWN（不反推）。

    - trade 部分：复用 position_reality_service.build_effective_events（S1A 同一
      correction semantics，DRY）→ effective corrected trade → compute_fields()。
    - cash event 部分：复用 cash_event_service（CASH_DEPOSIT/WITHDRAWAL/DIVIDEND/FEE/TAX，
      delta 由 event_type 决定）。
    保证 Position effective facts 与 Cash effective facts 完全一致。
    """
    ledger_start = derived.get("ledger_start")
    if ledger_start is None:
        return {
            "value": None,
            "source": _CASH_SOURCE_LEDGER,
            "coverage": _CASH_COVERAGE_TRADES_PLUS_CASH_EVENTS,
            "fact_type": _FACT_DERIVED,
            "effective_at": None,
            "temporal_status": _TEMPORAL_UNPROVEN,
            "temporal_reason_code": _REASON_CASH_EFFECTIVE_AT_UNPROVEN,
            "status": "UNKNOWN",
            "reason_code": _REASON_NOT_BOOTSTRAPPED,
        }
    opening_cash = ledger_start.get("opening_cash")
    if opening_cash is None:
        return {
            "value": None,
            "source": _CASH_SOURCE_LEDGER,
            "coverage": _CASH_COVERAGE_TRADES_PLUS_CASH_EVENTS,
            "fact_type": _FACT_DERIVED,
            "effective_at": None,
            "temporal_status": _TEMPORAL_UNPROVEN,
            "temporal_reason_code": _REASON_CASH_EFFECTIVE_AT_UNPROVEN,
            "status": "UNKNOWN",
            "reason_code": _REASON_OPENING_CASH_UNKNOWN,
        }
    db_path = trade_ledger_service.resolve_db_path()
    events = account_event_store.list_events(db_path)
    trades = trade_ledger_store.list_records(db_path, include_voided=False, limit=None)

    # 与 S1A derive_positions 相同的 ledger 边界（derived 的 ledger_start_at 已是
    # bootstrap 规范化后的 UTC ISO；derive 已校验其可解析）
    ledger_start_ts = None
    raw_start = ledger_start.get("ledger_start_at")
    if isinstance(raw_start, str) and raw_start:
        try:
            ledger_start_ts = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        except ValueError:
            ledger_start_ts = None

    effective = position_reality_service.build_effective_events(
        events, trades, ledger_start_ts=ledger_start_ts
    )
    cash = round(float(opening_cash), 2)
    for key, t in effective.items():
        if not key.startswith("trade:"):
            continue
        computed = trade_ledger_service.compute_fields(t)
        cash = round(cash + float(computed["net_cash_flow"]), 2)
    # manual cash events（active 仅）：消费"已应用 active CORRECTION 后的 effective
    # cash facts"（P0-S1B-C）——复用 build_effective_events 同一 correction machinery
    # （DRY），再经 validate_effective_cash_events 保证 persisted 完整性。
    # 未知 event_type / 损坏 amount / 损坏 correction payload → AccountEventCorruptedError
    # fail closed，不得静默忽略、不得 or 0.0 补零、不得回退 raw amount。
    for key, ev in effective.items():
        if not key.startswith("account_event:"):
            continue  # trade 条目走上面 trade 循环；这里只处理 account events
        if ev.get("event_type") in cash_event_service.CASH_EVENT_TYPES:
            account_event_store.validate_persisted_cash_event(ev)
            cash = round(
                cash + cash_event_service.cash_delta_for(ev["event_type"], ev["amount"]),
                2,
            )
        else:
            account_event_store.validate_event_type(ev.get("event_type"))
    return {
        "value": cash,
        "source": _CASH_SOURCE_LEDGER,
        "coverage": _CASH_COVERAGE_TRADES_PLUS_CASH_EVENTS,
        "fact_type": _FACT_DERIVED,
        "effective_at": None,
        "temporal_status": _TEMPORAL_UNPROVEN,
        "temporal_reason_code": _REASON_CASH_EFFECTIVE_AT_UNPROVEN,
        "status": "AVAILABLE",
    }


def _cash_reconciliation(
    current_fact: dict[str, Any], ledger_candidate: dict[str, Any]
) -> dict[str, Any]:
    """仅有效手工事实允许 MATCH/MISMATCH；损坏或缺失均保持 UNKNOWN。"""
    current_value = current_fact.get("value")
    ledger_value = ledger_candidate.get("value")
    if current_fact.get("status") == "AVAILABLE" and current_value is not None and ledger_value is not None:
        status = (
            "MATCH"
            if round(float(current_value), 2) == round(float(ledger_value), 2)
            else "MISMATCH"
        )
    else:
        status = "UNKNOWN"
    return {
        "status": status,
        "current_fact_value": current_value,
        "ledger_candidate_value": ledger_value,
        "reason_code": current_fact.get("reason_code") if status == "UNKNOWN" else None,
    }


# ---------------------------------------------------------------------------
# Settled pricing v0.1（kline 日线 close / price_date）
# ---------------------------------------------------------------------------


def _fetch_settled_price(code: str) -> dict[str, Any]:
    """取最近一根日线 close/date；失败/空/非法 → UNPRICED（不冒充 cutoff）。"""
    try:
        bars = astock.kline(code, category=4, offset=5) or []
    except Exception:
        return {"code": code, "close": None, "price_date": None, "pricing_status": "UNPRICED"}
    if not bars:
        return {"code": code, "close": None, "price_date": None, "pricing_status": "UNPRICED"}
    last = bars[-1]
    close = _valid_price(last.get("close"))
    price_date = _valid_price_date(last.get("datetime") or last.get("date"))
    if close is None or price_date is None:
        return {"code": code, "close": None, "price_date": None, "pricing_status": "UNPRICED"}
    return {"code": code, "close": close, "price_date": price_date, "pricing_status": "PRICED"}


def _settled_pricing(open_positions: list[dict[str, Any]]) -> dict[str, Any]:
    """对 OPEN positions 定价；输出 per-position rows 与顶层 pricing 状态。

    顶层状态：
    - 无持仓 → COMPLETE（无需定价），unified_price_date=None
    - 全部 PRICED 且 price_date 一致 → COMPLETE + unified_price_date
    - 全部 PRICED 但 price_date 不一致 → MIXED_CUTOFF（unified null，不选任一日期冒充）
    - 部分 PRICED → PARTIAL
    - 全部 UNPRICED → UNAVAILABLE
    """
    total = len(open_positions)
    rows: list[dict[str, Any]] = []
    priced_count = 0
    dates: set[str] = set()
    for pos in open_positions:
        code = pos["code"]
        shares = int(pos["shares"])
        px = _fetch_settled_price(code)
        if px["pricing_status"] == "PRICED":
            priced_count += 1
            dates.add(str(px["price_date"]))
            market_value = round(float(px["close"]) * shares, 2)
        else:
            market_value = None
        rows.append({
            "code": code,
            "name": pos.get("name") or code,
            "shares": shares,
            "price": px["close"],
            "price_date": px["price_date"],
            "pricing_status": px["pricing_status"],
            "market_value": market_value,
        })

    if total == 0:
        status = "COMPLETE"
        unified = None
    elif priced_count == total and len(dates) == 1:
        status = "COMPLETE"
        unified = next(iter(dates))
    elif priced_count == total:
        status = "MIXED_CUTOFF"
        unified = None
    elif priced_count > 0:
        status = "PARTIAL"
        unified = None
    else:
        status = "UNAVAILABLE"
        unified = None

    priced_market_value = round(
        sum(r["market_value"] for r in rows if r["market_value"] is not None), 2
    )
    return {
        "mode": "SETTLED_CLOSE",
        "status": status,
        "priced_holdings": priced_count,
        "total_holdings": total,
        "unified_price_date": unified,
        "priced_market_value": priced_market_value,
        "positions": rows,
    }


# ---------------------------------------------------------------------------
# Settled NAV（candidate）
# ---------------------------------------------------------------------------


def _settled_nav(
    derived: dict[str, Any],
    current_fact: dict[str, Any],
    pricing: dict[str, Any],
) -> tuple[float | None, str | None]:
    """settled NAV 只在 derivation valid + bootstrap 完成 + cash fact available + pricing COMPLETE 时输出。

    返回 (nav, skip_reason)；skip_reason 用于 reason_codes（不输出看起来完整但缺分量的 NAV）。
    """
    if derived.get("derivation_status") != "OK":
        return None, "DERIVATION_INVALID"
    if derived.get("bootstrap_status") != "BOOTSTRAPPED":
        return None, _REASON_NOT_BOOTSTRAPPED
    if current_fact.get("value") is None:
        return None, current_fact.get("reason_code") or _REASON_CASH_UNKNOWN
    if pricing["status"] != "COMPLETE":
        return None, pricing["status"]
    nav = round(float(current_fact["value"]) + float(pricing["priced_market_value"]), 2)
    return nav, None


# ---------------------------------------------------------------------------
# Account reality 聚合
# ---------------------------------------------------------------------------


def get_account_reality() -> dict[str, Any]:
    """组装 Current Account Reality Candidate（只读，不写任何源）。"""
    derived = position_reality_service.derive_positions()

    profile_status = account_profile.get_account_profile_status()
    latest_mutation_at, mutation_error = _latest_relevant_mutation()
    current_fact = _apply_mutation_freshness(
        _current_cash_fact(profile_status), latest_mutation_at, mutation_error
    )
    total_assets_fact = _apply_mutation_freshness(
        _current_total_assets_fact(profile_status), latest_mutation_at, mutation_error
    )
    ledger_candidate = _ledger_cash_candidate(derived)
    cash_recon = _cash_reconciliation(current_fact, ledger_candidate)

    position_canonical = derived.get("canonical") is True
    cash_subfact_canonical = current_fact.get("authority_state") == "CANONICAL"
    total_assets_canonical = total_assets_fact.get("authority_state") == "CANONICAL"
    reconciliation_eligible = cash_recon["status"] == "MATCH"
    # Corporate actions can only be proven irrelevant when this ledger has never
    # contained a security position. Any current or closed position keeps aggregate
    # Account coverage partial while preserving the narrower confirmed subfacts.
    coverage_eligible = not derived.get("positions")
    account_canonical = bool(
        position_canonical
        and cash_subfact_canonical
        and total_assets_canonical
        and reconciliation_eligible
        and coverage_eligible
    )
    canonical_reason_codes: list[str] = []
    if not position_canonical:
        canonical_reason_codes.append(_REASON_POSITION_AUTHORITY_NOT_CANONICAL)
    if not cash_subfact_canonical:
        canonical_reason_codes.append(
            current_fact.get("reason_code") or _REASON_CASH_EFFECTIVE_AT_UNPROVEN
        )
    if not total_assets_canonical:
        canonical_reason_codes.append(
            total_assets_fact.get("reason_code") or _REASON_ACCOUNT_TOTAL_ASSETS_UNPROVEN
        )
    if cash_recon["status"] == "MISMATCH":
        canonical_reason_codes.append(_REASON_ACCOUNT_CASH_RECONCILIATION_MISMATCH)
    elif cash_recon["status"] != "MATCH":
        canonical_reason_codes.append(_REASON_ACCOUNT_CASH_RECONCILIATION_UNKNOWN)
    if not coverage_eligible:
        canonical_reason_codes.append(_REASON_ACCOUNT_COVERAGE_INCOMPLETE)
    fact_authority_states = {
        current_fact.get("authority_state"),
        total_assets_fact.get("authority_state"),
    }
    if account_canonical:
        account_authority_state = "CANONICAL"
    elif "STALE" in fact_authority_states:
        account_authority_state = "STALE"
    elif "CORRUPTED" in fact_authority_states:
        account_authority_state = "CORRUPTED"
    elif "UNKNOWN" in fact_authority_states:
        account_authority_state = "UNKNOWN"
    elif position_canonical and cash_subfact_canonical and total_assets_canonical:
        account_authority_state = "PARTIAL"
    else:
        account_authority_state = "UNPROVEN"

    open_positions = [p for p in derived.get("positions", []) if p.get("status") == "OPEN"]
    pricing = _settled_pricing(open_positions)

    settled_nav, nav_skip = _settled_nav(derived, current_fact, pricing)

    reason_codes: list[str] = [_REASON_CORPORATE_ACTION_UNSUPPORTED]  # 事实边界：corporate action 尚未纳入现金覆盖
    if current_fact.get("status") == "CORRUPTED":
        reason_codes.append(_REASON_ACCOUNT_PROFILE_CORRUPTED)
    if nav_skip:
        reason_codes.append(nav_skip)
    if pricing["status"] == "PARTIAL":
        reason_codes.append(_REASON_PRICING_PARTIAL)
    elif pricing["status"] == "UNAVAILABLE":
        reason_codes.append(_REASON_PRICING_UNAVAILABLE)
    elif pricing["status"] == "MIXED_CUTOFF":
        reason_codes.append(_REASON_PRICING_MIXED_CUTOFF)

    # nav_reconciliation vs account_profile.total_assets（只读）
    nav_recon: dict[str, Any] = {
        "status": "UNKNOWN",
        "account_profile_total_assets": None,
        "computed_nav": None,
    }
    profile = profile_status.get("data")
    if (
        profile_status["status"] == "valid"
        and profile is not None
        and profile.get("total_assets") is not None
        and settled_nav is not None
    ):
        total_assets = round(float(profile["total_assets"]), 2)
        nav_recon = {
            "status": "MATCH" if total_assets == settled_nav else "MISMATCH",
            "account_profile_total_assets": total_assets,
            "computed_nav": settled_nav,
        }

    # confidence：确定性规则映射（非虚构权重）
    if account_canonical:
        confidence = "HIGH"
    elif settled_nav is not None:
        confidence = "HIGH" if cash_recon["status"] == "MATCH" else "MEDIUM"
    else:
        confidence = "LOW"

    # 当前没有任何可信的 cash effective_at producer。即使 settled_nav 数值可计算，
    # 也只能作为 pricing date + 未证明现金时间的 mixed candidate，不能给出统一 cutoff。
    nav_temporal_state = (
        _NAV_TEMPORAL_MIXED_UNPROVEN
        if settled_nav is not None
        else _NAV_TEMPORAL_UNAVAILABLE
    )
    nav_temporal_reason_codes = sorted({
        (
            _REASON_NAV_COMPONENT_CUTOFF_MISMATCH
            if current_fact.get("temporal_status") == _TEMPORAL_PROVEN
            else current_fact.get("temporal_reason_code")
            or _REASON_CASH_EFFECTIVE_AT_UNPROVEN
        ),
        *([nav_skip] if nav_skip else []),
        *(
            [_REASON_PRICING_MIXED_CUTOFF]
            if pricing["status"] == "MIXED_CUTOFF"
            else []
        ),
    })
    return {
        "account_status": "CANONICAL" if account_canonical else derived.get("bootstrap_status", "UNKNOWN"),
        "canonical": account_canonical,
        "canonical_reason_codes": list(dict.fromkeys(canonical_reason_codes)),
        "account_authority": {
            "state": account_authority_state,
            "source": _CASH_SOURCE_ACCOUNT_PROFILE,
            "confirmation_id": current_fact.get("confirmation_id"),
            "effective_at": current_fact.get("effective_at"),
            "recorded_at": current_fact.get("recorded_at"),
            "latest_relevant_mutation_at": latest_mutation_at,
            "reason_codes": list(dict.fromkeys(canonical_reason_codes)),
        },
        "bootstrap_status": derived.get("bootstrap_status"),
        "account_total_assets": {
            "current_fact": total_assets_fact,
        },
        "cash": {
            "current_fact": current_fact,
            "ledger_candidate": ledger_candidate,
            "reconciliation": cash_recon["status"],
            "coverage": _CASH_COVERAGE_TRADES_PLUS_CASH_EVENTS,
            "cash_subfact_canonical": cash_subfact_canonical,
        },
        "cash_event_support": {
            "supported": sorted(cash_event_service.CASH_EVENT_TYPES),
            "unsupported": ["CORPORATE_ACTION"],
        },
        "positions": pricing["positions"],
        "pricing": {
            "mode": pricing["mode"],
            "status": pricing["status"],
            "priced_holdings": pricing["priced_holdings"],
            "total_holdings": pricing["total_holdings"],
            "unified_price_date": pricing["unified_price_date"],
        },
        "market_value": pricing["priced_market_value"],
        "settled_nav": settled_nav,
        "nav_authority": "SETTLED_NAV_CANDIDATE",
        "nav_canonical": False,
        "nav_cash_source": _CASH_SOURCE_ACCOUNT_PROFILE if settled_nav is not None else None,
        "nav_reconciliation": {
            **nav_recon,
            "reason_code": (
                _REASON_ACCOUNT_PROFILE_CORRUPTED
                if profile_status["status"] == "corrupted"
                else None
            ),
        },
        "nav_temporal_state": nav_temporal_state,
        "nav_temporal_reason_codes": nav_temporal_reason_codes,
        "confidence": confidence,
        "reason_codes": sorted(set(reason_codes)),
        # pricing.unified_price_date 只描述收盘价事实；cash effective_at 未证明，
        # 因而不能将其提升为统一账户 data_cutoff。
        "data_cutoff": None,
        "as_of": _utc_now(),
    }
