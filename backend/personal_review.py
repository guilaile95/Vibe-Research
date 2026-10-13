"""Local personal review: annotations, not a second trade/decision authority.

No provider/model calls. Writes append only to an isolated local database. Trades,
account openings and formal attribution are read from their existing authorities.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import account_event_store
import account_profile
import formal_trade_attribution_store as attribution_store
import formal_trade_attribution as formal_authority
import performance_attribution_service as performance
import position_reality_service as positions
import trade_calendar
import trade_ledger_service as ledger
import trade_ledger_store
from personal_review_snapshot import Snapshot

VERSION = "personal-review.v1"
SHANGHAI = timezone(timedelta(hours=8))
MAX_TRADES = 10000


class ReviewError(ValueError):
    pass


class ReviewUnavailable(RuntimeError):
    pass


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    environment: str = Field(default="", max_length=500)
    closing_board_rank: int | None = Field(default=None, ge=1, le=100)
    judgment: Literal["unknown", "correct", "incorrect"] = "unknown"
    execution: Literal["unknown", "followed", "deviated"] = "unknown"
    violations: list[str] = Field(default_factory=list, max_length=10)
    stop_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    pattern_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    pattern_revision: int | None = Field(default=None, ge=1)
    note: str = Field(default="", max_length=2000)


class Pattern(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    setup: str = Field(min_length=1, max_length=1000)
    entry_rule: str = Field(min_length=1, max_length=1000)
    exit_rule: str = Field(min_length=1, max_length=1000)
    invalidation: str = Field(min_length=1, max_length=1000)


def _now():
    return datetime.now(timezone.utc)


def _instant(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:0\d|1[0-3]):[0-5]\d|[+-]14:00)", value):
        raise ValueError("invalid timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _day(value):
    return _instant(value).astimezone(SHANGHAI).date().isoformat()


def _path():
    return Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research") / "personal_review.sqlite3"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _read(conn):
    rows = conn.execute("SELECT kind, entity_id, revision, payload FROM revisions ORDER BY kind, entity_id, revision LIMIT 20001").fetchall()
    if len(rows) > 20000:
        raise ValueError("review revision row budget exceeded")
    output = {"assessment": {}, "pattern": {}}
    for kind, entity_id, revision, raw in rows:
        if len(raw.encode("utf8")) > 16000:
            raise ValueError("review payload budget exceeded")
        item = json.loads(raw)
        model = Assessment if kind == "assessment" else Pattern if kind == "pattern" else None
        if model is None or type(revision) is not int or revision < 1 or item["revision"] != revision:
            raise ValueError("invalid revision")
        model.model_validate({**item["content"], "revision": revision - 1})
        saved = _instant(item["saved_at"])
        expected_keys = {"revision", "content", "saved_at", "effective_from", "effective_rule"} if kind == "pattern" else {"revision", "content", "saved_at", "stop_recorded_at", "trade_fingerprint", "classification"}
        if set(item) != expected_keys:
            raise ValueError("invalid stored fields")
        if kind == "pattern":
            if (item["effective_from"] != (saved.astimezone(SHANGHAI).date() + timedelta(days=1)).isoformat()
                    or item["effective_rule"] != "NEXT_SHANGHAI_CALENDAR_DAY"):
                raise ValueError("invalid effective boundary")
        else:
            if item["classification"] != "RETROSPECTIVE_SELF_ASSESSMENT" or len(item["trade_fingerprint"]) != 64:
                raise ValueError("invalid annotation provenance")
            if (item["content"]["stop_price"] is None) != (item["stop_recorded_at"] is None):
                raise ValueError("invalid stop timestamp")
            if item["stop_recorded_at"] and _instant(item["stop_recorded_at"]) > saved:
                raise ValueError("future stop timestamp")
        history = output[kind].setdefault(entity_id, [])
        if revision != len(history) + 1:
            raise ValueError("revision gap")
        if history and (_instant(history[-1]["saved_at"]) > saved or (kind == "pattern" and history[-1]["effective_from"] >= item["effective_from"])):
            raise ValueError("non-monotonic history")
        history.append(item)
    return output


def history():
    try:
        return Snapshot(_path()).read(_read, {"assessment": {}, "pattern": {}})
    except Exception as exc:
        raise ReviewUnavailable("个人复查记录不可读取，已停止操作") from exc


def _ledger_rows(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    trades = [dict(r) for r in conn.execute("SELECT * FROM trade_records WHERE voided_at IS NULL ORDER BY created_at DESC LIMIT ?", (MAX_TRADES + 1,))] if "trade_records" in tables else []
    events = [dict(r) for r in conn.execute("SELECT * FROM account_events WHERE voided_at IS NULL ORDER BY created_at,rowid LIMIT 20001")] if "account_events" in tables else []
    if len(trades) > MAX_TRADES or len(events) > 20000:
        raise ReviewUnavailable("正式流水超过个人复查安全范围，未计算截断统计")
    return trades, events


def _trade(trade_id):
    snapshot = Snapshot(ledger.resolve_db_path())
    def lookup(conn):
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        row = conn.execute("SELECT * FROM trade_records WHERE trade_id=?", (trade_id,)).fetchone() if "trade_records" in tables else None
        return dict(row) if row else None
    trade = snapshot.read(lookup, None)
    if trade is None or trade.get("voided_at") or trade["execution_status"] == "not_executed":
        raise ReviewError("只能标注现有未作废的成交记录")
    if _instant(trade["executed_at"]) > _now():
        raise ReviewError("未来成交不可提前标注为个人复查")
    return trade


def save(kind: str, entity_id: str, body: Assessment | Pattern):
    """CAS append; retry of identical content at the previous revision is idempotent."""
    import re
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", entity_id):
        raise ReviewError("记录标识格式错误")
    content = body.model_dump(exclude={"revision"})
    if isinstance(body, Assessment):
        if any(not v.strip() or len(v) > 100 for v in body.violations):
            raise ReviewError("违反条目须为1–100字")
        if (body.pattern_id is None) != (body.pattern_revision is None):
            raise ReviewError("模式与版本必须同时选择")
        _trade(entity_id)
    elif any(not value.strip() for value in content.values()):
        raise ReviewError("模式定义不能只含空白")
    # Existing corrupt files must never be repaired or overwritten implicitly.
    history()
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS revisions (kind TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,entity_id,revision))")
            all_history = _read(conn)
            prior = all_history[kind].get(entity_id, [])
            current = prior[-1] if prior else None
            if current and current["content"] == content and body.revision in (len(prior), len(prior) - 1):
                return current
            if sum(len(items) for group in all_history.values() for items in group.values()) >= 20000 or path.stat().st_size > 60 * 1024 * 1024:
                raise ReviewError("个人复查修订数量或存储已达安全上限")
            if body.revision != len(prior):
                raise ReviewError("记录已改变，请重新加载后保存")
            now = _now()
            if current and now < _instant(current["saved_at"]):
                raise ReviewError("服务器时间早于已存修订，停止倒填")
            result = {"revision": len(prior) + 1, "content": content, "saved_at": _stamp(now)}
            if kind == "pattern":
                effective = (now.astimezone(SHANGHAI).date() + timedelta(days=1)).isoformat()
                if current and current["effective_from"] >= effective:
                    raise ReviewError("同一模式每天仅能发布一个新版本；当前待生效版本保留")
                result["effective_from"] = effective
                result["effective_rule"] = "NEXT_SHANGHAI_CALENDAR_DAY"
            else:
                trade = _trade(entity_id)
                if body.pattern_id:
                    versions = all_history["pattern"].get(body.pattern_id, [])
                    selected = next((v for v in versions if v["revision"] == body.pattern_revision), None)
                    entry_day = _day(trade["executed_at"])
                    effective = [v for v in versions if v["effective_from"] <= entry_day]
                    if not selected or not effective or selected != effective[-1]:
                        raise ReviewError("只能选择成交当日已生效的模式版本，不可事后倒填规则")
                result["stop_recorded_at"] = (current["stop_recorded_at"] if current and current["content"]["stop_price"] == body.stop_price else _stamp(now)) if body.stop_price is not None else None
                result["trade_fingerprint"] = _digest(trade)
                result["classification"] = "RETROSPECTIVE_SELF_ASSESSMENT"
            conn.execute("INSERT INTO revisions VALUES (?,?,?,?)", (kind, entity_id, result["revision"], json.dumps(result, ensure_ascii=False, allow_nan=False)))
            return result
    except sqlite3.Error as exc:
        raise ReviewUnavailable("个人复查保存失败，未改变正式账本") from exc


def _numeric(value, *, positive=False):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def _formal_map(conn):
    attribution_store._schema_contract(conn)
    rows = conn.execute("SELECT * FROM formal_trade_attributions ORDER BY created_at,attribution_id LIMIT 10001").fetchall()
    if len(rows) > MAX_TRADES:
        raise ReviewUnavailable("正式归属超过个人复查安全范围")
    records = [attribution_store._row(row) for row in rows]
    return {record["trade_id"]: record for record in records}


def _validate_formal_bindings(trades, records):
    """Validate canonical attribution anchors against this exact ledger image."""
    for trade in trades:
        record = records.get(trade["trade_id"])
        if record is None:
            continue
        anchor = formal_authority.verify_trade_record(trade)
        if (record["security_code"] != trade["code"]
                or any(record[field] != anchor[field] for field in ("trade_id", "trade_operation", "trade_execution_status"))
                or any((record[field] is None) != (anchor[field] is None) or (record[field] is not None and _instant(record[field]) != _instant(anchor[field])) for field in ("trade_executed_at", "trade_created_at"))
                or (anchor["thesis_id"] is not None and (record["thesis_id"] != anchor["thesis_id"] or record["thesis_revision"] != anchor["thesis_revision"]))):
            raise ReviewUnavailable("正式归属与当前流水锚不一致，已停止个人复查投影")


def _formal(trade_id, records):
    item = records.get(trade_id)
    return ({key: item[key] for key in ("campaign_id", "decision_id", "decision_committed_at", "trade_executed_at")} if item else None)


def episodes(trades, events, assessments, formal_records=None):
    """Single-account ledger projection; no inferred initial inventory or split allocation."""
    openings = [e for e in events if e["event_type"] == "ACCOUNT_OPENING"]
    if len(openings) != 1:
        return [], [{"code": None, "reason": "OPENING_INVENTORY_UNKNOWN"}], []
    start = _instant(openings[0]["ledger_start_at"])
    # Validate canonical events/corrections first, but never feed corrected rows
    # into the raw-trade accounting authority under the guise of original IDs.
    positions.build_effective_events(events, trades, ledger_start_ts=start)
    corrected = set()
    for event in events:
        if event["event_type"] == "CORRECTION":
            if event["target_event_type"] != "trade":
                return [], [{"code": None, "reason": "ACCOUNT_CORRECTION_REQUIRES_RECONCILIATION"}], []
            corrected.add(event["target_event_id"])
    grouped = defaultdict(list)
    for trade in trades:
        if trade["execution_status"] != "not_executed" and trade["actual_quantity"] > 0:
            grouped[trade["code"]].append(trade)
    inventory = defaultdict(int)
    for event in events:
        if event["event_type"] == "LEGACY_POSITION_OPENING":
            inventory[event["code"]] += event["shares"]
    closed, diagnostics, open_rows = [], [], []
    for code in sorted(set(grouped) | set(inventory)):
        rows = grouped[code]
        if not rows and inventory[code] > 0:
            open_rows.append({"code": code, "remaining_quantity": inventory[code], "trade_ids": [], "legacy": True})
            continue
        rows.sort(key=lambda r: (_instant(r["executed_at"]), _instant(r["created_at"]), r["trade_id"]))
        if any(t["trade_id"] in corrected for t in rows):
            diagnostics.append({"code": code, "reason": "CORRECTED_TRADE_REQUIRES_RECONCILIATION"})
            continue
        if any(_instant(row["executed_at"]) > _now() for row in rows):
            diagnostics.append({"code": code, "reason": "FUTURE_EXECUTION_UNVERIFIED"})
            continue
        directions = defaultdict(set)
        for row in rows:
            directions[_instant(row["executed_at"])].add(row["operation"] in ("buy", "add"))
        if any(len(v) > 1 for v in directions.values()):
            diagnostics.append({"code": code, "reason": "SAME_INSTANT_ORDER_UNKNOWN"})
            continue
        quantity, legacy, batch = inventory[code], inventory[code] > 0, []
        for row in rows:
            if not _numeric(row["actual_price"], positive=True) or type(row["actual_quantity"]) is not int or row["operation"] not in ("buy", "add", "sell", "reduce"):
                diagnostics.append({"code": code, "reason": "INVALID_EXECUTION"})
                batch = []
                break
            buying = row["operation"] in ("buy", "add")
            quantity += row["actual_quantity"] * (1 if buying else -1)
            if quantity < 0:
                diagnostics.append({"code": code, "reason": "OVERSELL_OR_MISSING_HISTORY"})
                batch = []
                break
            batch.append(row)
            if quantity == 0:
                if legacy:
                    diagnostics.append({"code": code, "reason": "LEGACY_OPENING_EPISODE_UNSCORED"})
                    legacy = False
                else:
                    closed.append(_episode(batch, assessments, openings[0]["event_id"], formal_records or {}))
                batch = []
        if batch:
            open_rows.append({"code": code, "remaining_quantity": quantity, "trade_ids": [r["trade_id"] for r in batch], "legacy": legacy})
    return sorted(closed, key=lambda r: (r["closed_at"], r["episode_id"]), reverse=True), diagnostics, open_rows


def _episode(rows, assessments, account_id, formal_records):
    ids = [r["trade_id"] for r in rows]
    facts = [_formal(t, formal_records) for t in ids]
    campaigns = {f["campaign_id"] if f else None for f in facts}
    known_costs = all(_numeric(r.get("fee")) and _numeric(r.get("other_cost")) for r in rows)
    eligible = len(campaigns) == 1
    # Reuse PA1 on the same frozen source rows used by structure/gross/fingerprint.
    # Re-reading live rows by ID here would mix different source generations.
    for index, row in enumerate(rows):
        performance._validate_trade_id(row["trade_id"], index)
    accounting = performance._compute_attribution_from_trades(trades=rows) if known_costs and eligible else None
    latest = assessments.get(ids[0], [])
    assessment = latest[-1] if latest and latest[-1]["trade_fingerprint"] == _digest(rows[0]) else None
    return {"episode_id": _digest({"account": account_id, "trades": ids})[:32], "account_id": account_id,
        "code": rows[0]["code"], "name": rows[0]["name"], "trade_ids": ids,
        "opened_at": rows[0]["executed_at"], "closed_at": rows[-1]["executed_at"],
        "holding_calendar_days": (datetime.fromisoformat(_day(rows[-1]["executed_at"])) - datetime.fromisoformat(_day(rows[0]["executed_at"]))).days,
        "state": "CLOSED" if eligible else "MIXED_CAMPAIGN_UNSCORED", "campaign_id": next(iter(campaigns)) if eligible else None,
        "formal_attributions": facts, "gross_pnl": round(sum(r["actual_price"] * r["actual_quantity"] * (-1 if r["operation"] in ("buy", "add") else 1) for r in rows), 2),
        "net_pnl": accounting["totals"]["total_realized_pnl"] if accounting else None,
        "fees": accounting["totals"]["total_fees"] if accounting else None,
        "fee_coverage": "LEDGER_RECORDED" if known_costs else "UNKNOWN",
        "computation_fingerprint": accounting["computation_fingerprint"] if accounting else None,
        "input_fingerprint": _digest(rows), "assessment": assessment,
        "entry_price": rows[0]["actual_price"], "simple_round_trip": len(rows) == 2}


def summarize(items, requested=None):
    sample = [r for r in items if r["state"] == "CLOSED"]
    if requested is not None:
        sample = sample[:requested]
    scored = [r for r in sample if r["net_pnl"] is not None]
    wins, losses = sum(r["net_pnl"] > 0 for r in scored), sum(r["net_pnl"] < 0 for r in scored)
    judged = [r for r in sample if r["assessment"]]
    return {"requested": requested, "closed_count": len(sample), "insufficient_samples": requested is not None and len(sample) < requested,
        "money_scored": len(scored), "wins": wins, "losses": losses, "flat": len(scored) - wins - losses,
        "win_rate_excluding_flat": wins / (wins + losses) if wins + losses else None,
        "net_pnl": round(sum(r["net_pnl"] for r in scored), 2) if scored else None,
        "self_assessed_count": len(judged), "self_reported_deviations": sum(r["assessment"]["content"]["execution"] == "deviated" for r in judged),
        "self_reported_violations": sum(len(r["assessment"]["content"]["violations"]) for r in judged)}


def excursion(episode):
    """Already-imported research bars, never today's quote or a provider fetch."""
    result = {"state": "NO_EVIDENCE", "mfe_pct": None, "mae_pct": None,
        "raw_interior_high": None, "raw_interior_low": None, "unit": "CNY_PER_SHARE_UNADJUSTED",
        "reason": "EXACT_HOLDING_INTERVAL_AND_CORPORATE_ACTION_BASIS_UNPROVEN",
        "boundary": "EXCLUDES_ENTRY_AND_EXIT_DAY; DAILY_BARS_NOT_EXECUTABLE_PRICES", "source": None, "adjusted_bound": None}
    if not episode["simple_round_trip"] or episode["state"] != "CLOSED":
        return {**result, "state": "COMPLEX_EPISODE_UNSUPPORTED"}
    start, end = _day(episode["opened_at"]), _day(episode["closed_at"])
    calendar = trade_calendar._load_calendar()
    if not calendar or start not in calendar or end not in calendar:
        return {**result, "state": "CALENDAR_UNKNOWN"}
    expected = [d for d in calendar if start < d < end]
    if not expected:
        return {**result, "state": "NO_INTERIOR_SESSIONS"}
    import research_data_plane as rdp
    import personal_review_price_basis as basis
    try:
        snapshot = basis.current_snapshot()
        data = rdp.query_daily_bars(snapshot_id=snapshot["snapshot_id"], code=episode["code"], date_from=expected[0], date_to=expected[-1], limit=1000)
    except (rdp.ResearchDataPlaneError, basis.BasisError):
        return result
    rows = data["rows"]
    if data["adjustment"] != "UNADJUSTED" or [r["trade_date"] for r in rows] != expected or any(not _numeric(r.get("volume"), positive=True) for r in rows):
        return {**result, "state": "PRICE_COVERAGE_OR_BASIS_UNKNOWN"}
    try:
        adjusted = basis.bounded_excursion(episode, snapshot["snapshot_id"])
    except basis.BasisError:
        adjusted = {"state": "BASIS_ARCHIVE_INVALID"}
    return {**result, "adjusted_bound": adjusted, "state": "RAW_INTERIOR_PRICE_RANGE", "raw_interior_high": max(r["high"] for r in rows),
        "raw_interior_low": min(r["low"] for r in rows),
        "source": {"provider_id": data["provider_id"], "adjustment": data["adjustment"], "fetched_at": data["fetched_at"], "as_of": data["as_of"], "provenance": data["provenance"], "sessions": len(rows)}}


def view():
    notes_source = Snapshot(_path())
    stored = notes_source.read(_read, {"assessment": {}, "pattern": {}})
    ledger_source = Snapshot(ledger.resolve_db_path())
    trades, events = ledger_source.read(_ledger_rows, ([], []))
    formal_source = Snapshot(attribution_store.resolve_formal_trade_attribution_db_path())
    formal_records = formal_source.read(_formal_map, {})
    _validate_formal_bindings(trades, formal_records)
    try:
        closed, diagnostics, opened = episodes(trades, events, stored["assessment"], formal_records)
    except (ValueError, KeyError, TypeError, positions.PositionDerivationError) as exc:
        raise ReviewUnavailable("正式账本边界无法核验，未计算个人统计") from exc
    profile = account_profile.get_account_profile_status()
    equity = profile.get("data") or {}
    risk_rows = []
    for item in opened:
        versions = stored["assessment"].get(item["trade_ids"][0], []) if item["trade_ids"] else []
        tag = versions[-1] if versions else None
        trade = next((t for t in trades if item["trade_ids"] and t["trade_id"] == item["trade_ids"][0]), None)
        stop = tag["content"]["stop_price"] if tag and trade and tag["trade_fingerprint"] == _digest(trade) else None
        # A scenario at entry reference price, not hard-risk or current NAV.
        risk_rows.append({**item, "entry_reference_stop_scenario": round(max(0, trade["actual_price"] - stop) * item["remaining_quantity"], 2) if stop is not None and not item["legacy"] else None,
            "stop_recorded_at": tag["stop_recorded_at"] if tag else None})
    patterns = []
    for pattern_id, versions in stored["pattern"].items():
        for index, version in enumerate(versions):
            linked = [e for e in closed if e["assessment"] and e["assessment"]["content"]["pattern_id"] == pattern_id and e["assessment"]["content"]["pattern_revision"] == version["revision"]]
            patterns.append({"pattern_id": pattern_id, **version, "effective_until": versions[index + 1]["effective_from"] if index + 1 < len(versions) else None, "statistics": summarize(linked)})
    now = _now().astimezone(SHANGHAI)
    monday = now.date() - timedelta(days=now.weekday())
    next_monday = monday + timedelta(days=7)
    week = [e for e in closed if monday.isoformat() <= _day(e["closed_at"]) < next_monday.isoformat()]
    notes_source.assert_unchanged()
    ledger_source.assert_unchanged()
    formal_source.assert_unchanged()
    return {"weekly": {"from": monday.isoformat(), "through_exclusive": next_monday.isoformat(), "timezone": "Asia/Shanghai", "summary": summarize(week), "privacy": "LOCAL_ONLY_NO_MODEL"}, "schema_version": VERSION, "privacy": "LOCAL_ONLY_EXCLUDED_FROM_MODEL_CONTEXT", "as_of": _stamp(_now()),
        "data_time": max((t["executed_at"] for t in trades if t.get("executed_at")), default=None),
        "trade_count": len(trades), "closed_episodes": closed, "diagnostics": diagnostics,
        "windows": [summarize(closed, n) for n in (10, 20, 50)], "patterns": patterns,
        "risk": {"open_episodes": risk_rows, "equity_reference": equity.get("total_assets"), "equity_effective_at": equity.get("effective_at"), "equity_confirmation": equity.get("confirmation_status", "UNKNOWN"), "risk_ratio": None,
            "boundary": "SELF_REPORTED_STOP_SCENARIO; EQUITY_TIME_NOT_ALIGNED; NOT_HARD_RISK"},
        "assessment_history": stored["assessment"],
        "limitations": ["仅本地个人复查，不改变持仓、正式决策、归属或硬风险权限，也不发送给模型。", "净收益复用正式流水成本；LEDGER_RECORDED 仅表示账本所记费用，旧默认零不证明实际无费用。", "收盘板位、环境与判断/执行评价均为事后自评，不是事前信号或因果证明。", "已闭合轮次须有账户期初边界；缺失历史、修正、混合归属及顺序不明不纳入样本。", "模式在上海下一自然日生效，历史版本保留；未启用旧 VA 数据迁移。"]}
