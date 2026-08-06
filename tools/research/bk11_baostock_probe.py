"""BK-11 零成本数据源可行性探测 harness（BaoStock 专用，研究工具）。

本模块不属于生产代码：

- 不被 ``app.py`` 导入，不被普通后端启动调用；
- 不写 ``short_term_facts.sqlite3``，不接受数据库路径；
- 不接受 Token / 账号 / 密码；
- 不自动选择日期，所有探测日期必须显式传入；
- 输出仅为聚合统计与脱敏摘要：不输出完整股票行、完整代码列表、
  URL、traceback 或原始异常文本；
- 只做串行、低频、有界探测（默认串行，不建线程池）。

请求预算：所有真实来源调用纳入统一预算（login、query_all_stock 分页、
主探测尝试、重试、determinism 复查），预算不足时失败关闭，绝不绕过。

``KeyboardInterrupt`` / ``SystemExit`` / ``GeneratorExit`` 自然传播。

``baostock`` 只在 ``BaoStockClient`` 实例化时惰性导入，测试可使用
同协议的 fake client，不需要安装 baostock。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

DEFAULT_FIELDS = "date,code,open,high,low,close,preclose,tradestatus,pctChg,isST"
INCLUDED_PREFIXES = ("60", "00", "30", "68")
_STRICT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SIX_DIGIT_RE = re.compile(r"^\d{6}$")

DEFAULT_SAMPLE_SIZE = 120
MAX_SAMPLE_SIZE = 120
SAMPLE_DEFAULT_MAX_REQUESTS = 150
FULL_MAX_TARGETS = 6500
FULL_MAX_REQUESTS = 6600
MAX_RETRY = 1
RETRY_DELAY_SECONDS = 1.0
CONSECUTIVE_FAIL_STOP = 10
SAMPLE_EARLY_WINDOW = 50
SAMPLE_EARLY_FAIL_RATE = 0.05
FULL_FAIL_STOP = 20
FULL_FAIL_RATE = 0.01
WALL_CLOCK_LIMIT_SECONDS = 60 * 60
DEFAULT_SOCKET_TIMEOUT = 30.0
DEFAULT_DETERMINISM_CHECKS = 5
MAX_DETERMINISM_CHECKS = 5


class ProbeError(RuntimeError):
    """探测流程错误（不携带来源异常文本）。"""


def _strict_parse_date(value: str) -> Optional[date]:
    m = _STRICT_DATE_RE.match(value)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _is_finite_float(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    return False


def _parse_float_field(value: Any) -> Tuple[Optional[float], bool]:
    """解析数值字段。返回 ``(parsed, invalid)``。

    空字符串 / ``'-'`` / ``None`` 视为缺失（missing，不是 invalid）；
    其他无法解析或非有限值视为 invalid。
    """
    if value is None:
        return None, False
    if isinstance(value, str):
        text = value.strip()
        if text == "" or text == "-":
            return None, False
        try:
            parsed = float(text)
        except ValueError:
            return None, True
        if not math.isfinite(parsed):
            return None, True
        return parsed, False
    if _is_finite_float(value):
        return float(value), False
    return None, True


def _normalize_baostock_code(code: str) -> str:
    """把 ``sh.600000`` / ``sz.000001`` 归一化为六位代码。"""
    if len(code) == 9 and code[2] == "." and code[:2] in ("sh", "sz"):
        return code[3:]
    return code


def _code_to_baostock(code: str) -> str:
    """把六位代码转成 baostock 要求的前缀格式。"""
    if code.startswith(("60", "68")):
        return f"sh.{code}"
    return f"sz.{code}"


def is_target_code(code: str) -> bool:
    """目标股票池：严格 ``sh.60xxxx`` / ``sh.68xxxx`` / ``sz.00xxxx`` /
    ``sz.30xxxx``。

    必须保留交易所前缀：``sh.000001``（上证指数）与 ``sz.000001``（平安
    银行）数字相同但证券类型不同，仅靠六位数字无法区分。
    """
    if not isinstance(code, str):
        return False
    if len(code) != 9 or code[2] != ".":
        return False
    exchange = code[:2]
    digits = code[3:]
    if exchange not in ("sh", "sz") or not _SIX_DIGIT_RE.match(digits):
        return False
    if exchange == "sh":
        return digits.startswith(("60", "68"))
    return digits.startswith(("00", "30"))


class BaoStockClient:
    """BaoStock 真实客户端薄封装（惰性导入 baostock）。

    login 后对底层 socket 设置超时，避免库内无限阻塞读。
    """

    def __init__(self, socket_timeout: float = DEFAULT_SOCKET_TIMEOUT) -> None:
        self.socket_timeout = socket_timeout
        self._bs: Any = None
        self._logged_in = False

    def _import(self) -> Any:
        if self._bs is None:
            try:
                import baostock as bs  # type: ignore
            except Exception as exc:
                raise ProbeError("baostock import failed") from exc
            self._bs = bs
        return self._bs

    def login(self) -> dict:
        bs = self._import()
        lg = bs.login()
        self._logged_in = lg.error_code == "0"
        if self._logged_in:
            self._apply_socket_timeout()
        return {
            "ok": self._logged_in,
            "error_code": lg.error_code,
            "error_msg": lg.error_msg,
        }

    def logout(self) -> dict:
        bs = self._import()
        if self._logged_in:
            try:
                lo = bs.logout()
                self._logged_in = False
                return {"ok": lo.error_code == "0", "error_code": lo.error_code}
            except Exception:
                self._logged_in = False
                return {"ok": False, "error_code": "logout_exception"}
        return {"ok": True, "error_code": "0"}

    def _apply_socket_timeout(self) -> None:
        try:
            import baostock.common.context as conx  # type: ignore

            sock = getattr(conx, "default_socket", None)
            if sock is not None and hasattr(sock, "settimeout"):
                sock.settimeout(self.socket_timeout)
        except Exception:
            # 超时防护不可用时不阻断探测；库内默认行为继续。
            pass

    def query_all_stock(self, day: str) -> Tuple[list, int]:
        """返回 ``(rows, pages)``；pages 为实际分页网络请求次数。"""
        bs = self._import()
        rs = bs.query_all_stock(day=day)
        if getattr(rs, "error_code", None) != "0":
            raise ProbeError("query_all_stock failed")
        rows: list = []
        row_count = 0
        while rs.next():
            rows.append(list(rs.get_row_data()))
            row_count += 1
        # 每页 2000 行（BAOSTOCK_PER_PAGE_COUNT）；页数 = 1 + (rows-1)//2000。
        # 注意：恰好整除时客户端会多发一次空页探测请求，本计数按保守下限
        # 记录（不影响本次 7329 行 = 4 页的精确性）。
        pages = 1 + max(0, row_count - 1) // 2000 if row_count else 0
        return rows, pages

    def query_history_k_day(self, code: str, day: str, fields: str) -> list:
        bs = self._import()
        rs = bs.query_history_k_data_plus(
            code,
            fields,
            start_date=day,
            end_date=day,
            frequency="d",
            adjustflag="3",
        )
        if getattr(rs, "error_code", None) != "0":
            raise ProbeError("query_history_k_data_plus failed")
        field_names = list(getattr(rs, "fields", []) or [])
        rows: list = []
        while rs.next():
            row = rs.get_row_data()
            if field_names:
                rows.append(dict(zip(field_names, row)))
            else:
                rows.append({"raw": list(row)})
        return rows


# ---------------------------------------------------------------------------
# 股票池与抽样（失败关闭）
# ---------------------------------------------------------------------------

def parse_all_stock_rows(
    raw_rows: Sequence[Sequence[Any]],
) -> Tuple[List[Dict[str, str]], int, int, int]:
    """解析 query_all_stock 原始行。

    返回 ``(targets, excluded, duplicate_code_count, conflicting_status_count)``。

    目标股票要求：``sh.60xxxx`` / ``sh.68xxxx`` / ``sz.00xxxx`` /
    ``sz.30xxxx``。每行输出 ``{"code", "bs_code", "trade_status"}``。

    同一目标代码重复出现：同状态重复计入 ``duplicate_code_count``（保留
    首条）；不同状态计入 ``conflicting_status_count``（来源合同失败，
    调用方必须失败关闭，不得静默保留首次值）。
    """
    targets: List[Dict[str, str]] = []
    excluded = 0
    status_by_code: Dict[str, List[str]] = {}
    order: Dict[str, Dict[str, str]] = {}
    for row in raw_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            excluded += 1
            continue
        code_raw = row[0]
        status_raw = row[1]
        if not isinstance(code_raw, str):
            excluded += 1
            continue
        code_raw = code_raw.strip()
        if len(code_raw) != 9 or code_raw[2] != ".":
            excluded += 1
            continue
        if not is_target_code(code_raw):
            excluded += 1
            continue
        code = _normalize_baostock_code(code_raw)
        status = status_raw.strip() if isinstance(status_raw, str) else str(status_raw)
        status_by_code.setdefault(code, []).append(status)
        if code not in order:
            order[code] = {"code": code, "bs_code": code_raw, "trade_status": status}
    duplicate_code_count = 0
    conflicting_status_count = 0
    for code, statuses in status_by_code.items():
        if len(statuses) > 1:
            distinct = set(statuses)
            if len(distinct) > 1:
                conflicting_status_count += 1
        duplicate_code_count += len(statuses) - 1
    targets = sorted(order.values(), key=lambda e: e["code"])
    return targets, excluded, duplicate_code_count, conflicting_status_count


def _strat_key(entry: Dict[str, str]) -> str:
    code = entry["code"]
    prefix = code[:2]
    status = "suspended" if entry["trade_status"] == "0" else "active"
    return f"{prefix}/{status}"


def build_stratified_sample(
    targets: Sequence[Dict[str, str]],
    sample_size: int,
    seed: int = 0,
) -> List[Dict[str, str]]:
    """确定性分层抽样：按 板块前缀/停牌状态 分层后轮转取前 sample_size。"""
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    strata: Dict[str, List[Dict[str, str]]] = {}
    for entry in targets:
        strata.setdefault(_strat_key(entry), []).append(entry)
    for key in strata:
        strata[key].sort(key=lambda e: e["code"])
    order = sorted(strata.keys())
    sampled: List[Dict[str, str]] = []
    idx = {key: 0 for key in order}
    # seed 只影响轮转起点（确定性），不引入随机源。
    start = seed % max(1, len(order))
    keys = order[start:] + order[:start]
    while len(sampled) < sample_size:
        progressed = False
        for key in keys:
            bucket = strata[key]
            if idx[key] < len(bucket) and len(sampled) < sample_size:
                sampled.append(bucket[idx[key]])
                idx[key] += 1
                progressed = True
        if not progressed:
            break
    return sampled


# ---------------------------------------------------------------------------
# 单股单日探测
# ---------------------------------------------------------------------------

def _row_violations(
    row: Dict[str, Any],
    code: str,
    day: str,
    expected_trade_status: str,
) -> List[str]:
    """检查单日 K 行合同；返回违规码列表（空=无违规）。"""
    violations: List[str] = []
    row_date = row.get("date")
    if str(row_date).strip() != day:
        violations.append("date_mismatch")
    row_code = _normalize_baostock_code(str(row.get("code", "")).strip())
    if row_code != code:
        violations.append("code_mismatch")
    tradestatus = row.get("tradestatus")
    if tradestatus not in (None, "", "-", "0", "1"):
        violations.append("invalid_tradestatus")
    if str(tradestatus).strip() != expected_trade_status:
        # universe=0/K线=1 与 universe=1/K线=0 均落入此违规码
        violations.append("trade_status_mismatch")
    for field in ("pctChg", "open", "high", "low", "close", "preclose"):
        value = row.get(field)
        parsed, invalid = _parse_float_field(value)
        if invalid:
            kind = "invalid_pct_chg" if field == "pctChg" else "invalid_ohlc"
            violations.append(kind)
    return violations


def probe_stock(
    client: Any,
    entry: Dict[str, str],
    day: str,
    *,
    fields: str = DEFAULT_FIELDS,
    retries: int = MAX_RETRY,
    sleep: Callable[[float], None] = time.sleep,
    budget: List[int],
    calls: List[int],
) -> Dict[str, Any]:
    """探测单只股票单日 K 线（失败关闭，不抛普通异常）。

    每次真实来源调用（含重试）消耗统一预算并计入 calls。
    """
    code = entry["code"]
    expected_status = entry["trade_status"]
    attempt = 0
    while True:
        started = time.monotonic()
        if budget[0] <= 0:
            return {
                "code": code,
                "ok": False,
                "error": "budget_exhausted",
                "retries": max(0, attempt - 1),
                "rows": [],
                "elapsed": 0.0,
                "violations": ["request_error"],
            }
        budget[0] -= 1
        calls[0] += 1
        try:
            rows = client.query_history_k_day(_code_to_baostock(code), day, fields)
            elapsed = time.monotonic() - started
            break
        except Exception:
            elapsed = time.monotonic() - started
            attempt += 1
            if attempt > retries:
                return {
                    "code": code,
                    "ok": False,
                    "error": "request_error",
                    "retries": attempt - 1,
                    "rows": [],
                    "elapsed": elapsed,
                    "violations": ["request_error"],
                }
            sleep(RETRY_DELAY_SECONDS)
    violations: List[str] = []
    for row in rows:
        violations.extend(_row_violations(row, code, day, expected_status))
    # 单日去重检查
    unique_dates = {str(r.get("date", "")).strip() for r in rows}
    if len(rows) > 1 or len(unique_dates) > 1:
        violations.append("duplicate_row")
    return {
        "code": code,
        "ok": True,
        "error": None,
        "retries": attempt,
        "rows": rows,
        "elapsed": elapsed,
        "violations": sorted(set(violations)),
    }


def _result_counts(results: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "success": 0,
        "failure": 0,
        "empty": 0,
        "date_mismatch": 0,
        "code_mismatch": 0,
        "duplicate": 0,
        "invalid_pct_chg": 0,
        "invalid_ohlc": 0,
        "invalid_tradestatus": 0,
        "trade_status_mismatch": 0,
        "request_error": 0,
        "retries": 0,
    }
    for r in results:
        counts["retries"] += int(r.get("retries", 0))
        if not r.get("ok"):
            counts["failure"] += 1
            counts["request_error"] += 1
            continue
        counts["success"] += 1
        rows = r.get("rows") or []
        if not rows:
            counts["empty"] += 1
        for v in r.get("violations") or []:
            if v == "duplicate_row":
                counts["duplicate"] += 1
                continue
            if v in counts:
                counts[v] += 1
    return counts


def _latency_stats(elapsed_values: Sequence[float]) -> Dict[str, Optional[float]]:
    values = [float(v) for v in elapsed_values if v is not None]
    if not values:
        return {"p50": None, "p95": None, "mean": None, "max": None}
    values.sort()

    def _pct(p: float) -> float:
        idx = min(len(values) - 1, max(0, int(math.ceil(p / 100.0 * len(values))) - 1))
        return round(values[idx], 4)

    return {
        "p50": _pct(50.0),
        "p95": _pct(95.0),
        "mean": round(statistics.fmean(values), 4),
        "max": round(values[-1], 4),
    }


def _run_determinism_checks(
    client: Any,
    targets: Sequence[Dict[str, str]],
    day: str,
    checks: int,
    fields: str,
    budget: List[int],
    calls: List[int],
    primary_by_code: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """对前 checks 个目标各追加一次复查请求（复用主探测结果，不重复首查）。

    预算不足时停止并返回 ``determinism_incomplete=true``，不绕过预算。
    """
    details: List[Dict[str, Any]] = []
    identical = 0
    incomplete = False
    elapsed_values: List[float] = []
    for entry in targets[:checks]:
        primary = primary_by_code.get(entry["code"])
        if primary is None:
            continue
        if budget[0] <= 0:
            incomplete = True
            break
        started = time.monotonic()
        budget[0] -= 1
        calls[0] += 1
        try:
            rows = client.query_history_k_day(
                _code_to_baostock(entry["code"]), day, fields
            )
            ok = True
        except Exception:
            rows = []
            ok = False
        elapsed = time.monotonic() - started
        elapsed_values.append(elapsed)
        same = ok == primary.get("ok") and rows == primary.get("rows")
        if same:
            identical += 1
        details.append(
            {
                "checked": len(details) + 1,
                "identical": same,
                "first_ok": primary.get("ok"),
                "second_ok": ok,
                "first_rows": len(primary.get("rows") or []),
                "second_rows": len(rows),
                "elapsed": elapsed,
            }
        )
    return {
        "checked": len(details),
        "identical": identical,
        "all_identical": len(details) > 0 and identical == len(details),
        "incomplete": incomplete,
        "request_count": len(details),
        "latency": _latency_stats(elapsed_values),
        "details": details,
    }


def run_probe(
    client: Any,
    targets: Sequence[Dict[str, str]],
    day: str,
    *,
    fields: str = DEFAULT_FIELDS,
    max_requests: int,
    consecutive_fail_stop: int,
    early_window: int,
    early_fail_rate: float,
    fail_rate_stop: float,
    wall_clock_limit: float,
    retries: int = MAX_RETRY,
    sleep: Callable[[float], None] = time.sleep,
    determinism_checks: int = 0,
    fail_count_stop: Optional[int] = None,
    result_sink: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """串行探测目标列表；统一预算 + 熔断；返回聚合统计。"""
    results: List[Dict[str, Any]] = []
    consecutive_fail = 0
    started = time.monotonic()
    budget_exhausted = False
    circuit_open = ""
    determinism: Optional[Dict[str, Any]] = None
    budget: List[int] = [max_requests]
    calls: List[int] = [0]

    for entry in targets:
        code = entry["code"]
        if budget[0] <= 0:
            budget_exhausted = True
            break
        if time.monotonic() - started > wall_clock_limit:
            circuit_open = "wall_clock_limit"
            break
        result = probe_stock(
            client,
            entry,
            day,
            fields=fields,
            retries=retries,
            sleep=sleep,
            budget=budget,
            calls=calls,
        )
        results.append(result)
        if result_sink is not None:
            result_sink.append(result)
        if not result.get("ok"):
            consecutive_fail += 1
        else:
            consecutive_fail = 0
        if consecutive_fail >= consecutive_fail_stop:
            circuit_open = "consecutive_failures"
            break
        failures = sum(1 for r in results if not r.get("ok"))
        attempt_failures = failures + sum(
            int(r.get("retries", 0)) for r in results
        )
        if calls[0] >= early_window:
            if calls[0] and attempt_failures / calls[0] > early_fail_rate:
                circuit_open = "early_failure_rate"
                break
        if fail_count_stop is not None and failures > fail_count_stop:
            circuit_open = "failure_count"
            break
        # 失败率熔断需要足够样本量，避免单次失败误触发
        if (
            calls[0] >= 100
            and attempt_failures / calls[0] > fail_rate_stop
        ):
            circuit_open = "failure_rate"
            break
        if result.get("error") == "budget_exhausted":
            budget_exhausted = True
            break

    primary_by_code = {r["code"]: r for r in results}
    if determinism_checks > 0 and not circuit_open:
        determinism = _run_determinism_checks(
            client,
            targets,
            day,
            determinism_checks,
            fields,
            budget,
            calls,
            primary_by_code,
        )
        if determinism["incomplete"]:
            budget_exhausted = True

    counts = _result_counts(results)
    latency_values = [float(r["elapsed"]) for r in results]
    determinism_request_count = 0
    if determinism is not None:
        latency_values.extend(
            [float(d["elapsed"]) for d in determinism.get("details", [])]
        )
        determinism_request_count = determinism["request_count"]
    latency = _latency_stats(latency_values)
    total_elapsed = time.monotonic() - started
    request_count = calls[0]
    per_second = request_count / total_elapsed if total_elapsed > 0 else 0.0

    return {
        "target_count": len(targets),
        "processed_target_count": len(results),
        "request_count": request_count,
        "primary_request_count": len(results),
        "retry_request_count": sum(int(r.get("retries", 0)) for r in results),
        "determinism_request_count": determinism_request_count,
        "budget_exhausted": budget_exhausted,
        "circuit_open": circuit_open,
        "counts": counts,
        "latency": latency,
        "latency_includes_determinism": True,
        "total_elapsed_seconds": round(total_elapsed, 2),
        "requests_per_second": round(per_second, 3),
        "estimated_daily_production_minutes": round(
            total_elapsed / 60.0, 2
        ) if total_elapsed else 0.0,
        "determinism": determinism,
    }


# ---------------------------------------------------------------------------
# 市场宽度（失败关闭）
# ---------------------------------------------------------------------------

def compute_breadth(
    universe: Sequence[Dict[str, str]],
    probe_results: Sequence[Dict[str, Any]],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """按现有 BK-11 口径计算市场宽度（advance/decline/flat/suspended/eligible）。

    breadth_identity 只在全部失败关闭条件满足时成立（见 meta 条件）。
    """
    eligible = len(universe)
    suspended_codes = {e["code"] for e in universe if e["trade_status"] == "0"}
    suspended = len(suspended_codes)
    advance = decline = flat = 0
    missing_pct_chg = 0
    for r in probe_results:
        code = r.get("code")
        for row in r.get("rows") or []:
            if code in suspended_codes:
                # 停牌股允许 pctChg 为空，但必须状态一致
                # （trade_status_mismatch==0 由 identity 条件统一把关）
                continue
            pct, invalid = _parse_float_field(row.get("pctChg"))
            if invalid:
                missing_pct_chg += 1
                continue
            if pct is None:
                missing_pct_chg += 1
                continue
            if pct > 0:
                advance += 1
            elif pct < 0:
                decline += 1
            else:
                flat += 1
    valid = advance + decline + flat
    counts_ok = eligible == valid + suspended and missing_pct_chg == 0
    identity = (
        counts_ok
        and meta.get("processed_target_count") == eligible
        and meta.get("failure_count", 0) == 0
        and meta.get("empty_count", 0) == 0
        and meta.get("date_mismatch", 0) == 0
        and meta.get("code_mismatch", 0) == 0
        and meta.get("duplicate_row", 0) == 0
        and meta.get("invalid_pct_chg", 0) == 0
        and meta.get("trade_status_mismatch", 0) == 0
        and meta.get("circuit_open", "") == ""
        and meta.get("budget_exhausted") is False
        and meta.get("duplicate_code_count", 0) == 0
        and meta.get("conflicting_status_count", 0) == 0
    )
    return {
        "advance_count": advance,
        "decline_count": decline,
        "flat_count": flat,
        "suspended_count": suspended,
        "eligible_count": eligible,
        "valid_count": valid,
        "missing_pct_chg": missing_pct_chg,
        "breadth_identity": identity,
    }


# ---------------------------------------------------------------------------
# 停牌交叉验证（聚合输出）
# ---------------------------------------------------------------------------

def cross_check_suspension(
    baostock_suspended: Sequence[str],
    eastmoney_suspended: Sequence[str],
) -> Dict[str, Any]:
    """比较两个来源的停牌代码集合，只输出聚合统计。"""
    bs_set = set(baostock_suspended)
    em_set = set(eastmoney_suspended)
    intersection = bs_set & em_set
    union = bs_set | em_set
    jaccard = len(intersection) / len(union) if union else None
    return {
        "baostock_suspended_count": len(bs_set),
        "eastmoney_suspended_count": len(em_set),
        "intersection_count": len(intersection),
        "only_baostock_count": len(bs_set - em_set),
        "only_eastmoney_count": len(em_set - bs_set),
        "jaccard": round(jaccard, 4) if jaccard is not None else None,
    }


# ---------------------------------------------------------------------------
# 汇总输出
# ---------------------------------------------------------------------------

def build_summary(
    *,
    mode: str,
    trade_date: str,
    fields: str,
    universe_stats: Optional[Dict[str, Any]],
    probe: Optional[Dict[str, Any]],
    breadth: Optional[Dict[str, Any]],
    suspension_cross: Optional[Dict[str, Any]],
    login: Optional[Dict[str, Any]],
    logout: Optional[Dict[str, Any]],
    session_request_count: int = 2,
) -> Dict[str, Any]:
    """构造脱敏汇总 JSON（聚合统计，无完整股票行/代码列表）。"""
    summary: Dict[str, Any] = {
        "tool": "bk11_baostock_probe",
        "mode": mode,
        "trade_date": trade_date,
        "fields": fields,
        "login": login,
        "logout": logout,
        "universe_stats": universe_stats,
        "probe": probe,
        "breadth": breadth,
        "suspension_cross": suspension_cross,
    }
    universe_pages = 0
    if isinstance(universe_stats, dict):
        universe_pages = int(universe_stats.get("universe_request_count", 0) or 0)
    primary = 0
    retry = 0
    determinism = 0
    if isinstance(probe, dict):
        primary = int(probe.get("primary_request_count", 0) or 0)
        retry = int(probe.get("retry_request_count", 0) or 0)
        determinism = int(probe.get("determinism_request_count", 0) or 0)
    summary["request_accounting"] = {
        "session_request_count": session_request_count,
        "universe_request_count": universe_pages,
        "primary_request_count": primary,
        "retry_request_count": retry,
        "determinism_request_count": determinism,
        "total_source_request_count": (
            session_request_count + universe_pages + primary + retry + determinism
        ),
    }
    return summary


def _fetch_universe(
    client: Any,
    day: str,
    budget: List[int],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """login 后拉取并过滤股票池；返回 ``(universe_stats, targets)`` 组合。"""
    if budget[0] <= 0:
        raise ProbeError("budget exhausted before universe query")
    budget[0] -= 1
    try:
        raw_rows, pages = client.query_all_stock(day=day)
    except Exception as exc:
        raise ProbeError("query_all_stock failed") from exc
    if pages - 1 > budget[0]:
        budget[0] = 0
        raise ProbeError("budget exhausted during universe query")
    budget[0] -= max(0, pages - 1)
    targets, excluded, dup, conflict = parse_all_stock_rows(raw_rows)
    universe_stats = {
        "raw_rows": len(raw_rows),
        "excluded_count": excluded,
        "target_count": len(targets),
        "duplicate_code_count": dup,
        "conflicting_status_count": conflict,
        "suspended_in_universe": sum(1 for e in targets if e["trade_status"] == "0"),
        "universe_request_count": pages,
    }
    return universe_stats, targets


def run_sample_probe(
    client: Any,
    day: str,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = 0,
    max_requests: int = 0,
    retries: int = MAX_RETRY,
    determinism_checks: int = DEFAULT_DETERMINISM_CHECKS,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """小样本探测编排：login → query_all_stock → 分层抽样 → 串行探测。"""
    budget = [max_requests if max_requests > 0 else SAMPLE_DEFAULT_MAX_REQUESTS]
    login = client.login()
    budget[0] -= 1
    logout: Optional[Dict[str, Any]] = None
    universe_stats: Optional[Dict[str, Any]] = None
    probe_result: Optional[Dict[str, Any]] = None
    try:
        if not login["ok"]:
            return build_summary(
                mode="sample",
                trade_date=day,
                fields=DEFAULT_FIELDS,
                universe_stats=None,
                probe=None,
                breadth=None,
                suspension_cross=None,
                login=login,
                logout=logout,
            )
        universe_stats, targets = _fetch_universe(client, day, budget)
        if universe_stats["conflicting_status_count"] > 0:
            universe_stats["contract_failure"] = "conflicting_status"
            return build_summary(
                mode="sample",
                trade_date=day,
                fields=DEFAULT_FIELDS,
                universe_stats=universe_stats,
                probe=None,
                breadth=None,
                suspension_cross=None,
                login=login,
                logout=logout,
            )
        if universe_stats["duplicate_code_count"] > 0:
            universe_stats["contract_warning"] = "duplicate_codes"
        sampled = build_stratified_sample(targets, sample_size, seed)
        probe_result = run_probe(
            client,
            sampled,
            day,
            fields=DEFAULT_FIELDS,
            max_requests=budget[0],
            consecutive_fail_stop=CONSECUTIVE_FAIL_STOP,
            early_window=SAMPLE_EARLY_WINDOW,
            early_fail_rate=SAMPLE_EARLY_FAIL_RATE,
            fail_rate_stop=SAMPLE_EARLY_FAIL_RATE,
            fail_count_stop=None,
            wall_clock_limit=WALL_CLOCK_LIMIT_SECONDS,
            retries=retries,
            determinism_checks=determinism_checks,
            sleep=sleep,
        )
        probe_result["sample_size"] = len(sampled)
    finally:
        logout = client.logout()
    return build_summary(
        mode="sample",
        trade_date=day,
        fields=DEFAULT_FIELDS,
        universe_stats=universe_stats,
        probe=probe_result,
        breadth=None,
        suspension_cross=None,
        login=login,
        logout=logout,
    )


def run_full_probe(
    client: Any,
    day: str,
    *,
    max_requests: int = 0,
    retries: int = MAX_RETRY,
    determinism_checks: int = DEFAULT_DETERMINISM_CHECKS,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """全市场单日探测编排（只执行一个交易日，失败关闭）。"""
    budget = [max_requests if max_requests > 0 else FULL_MAX_REQUESTS]
    login = client.login()
    budget[0] -= 1
    logout: Optional[Dict[str, Any]] = None
    universe_stats: Optional[Dict[str, Any]] = None
    probe_result: Optional[Dict[str, Any]] = None
    breadth: Optional[Dict[str, Any]] = None
    try:
        if not login["ok"]:
            return build_summary(
                mode="full",
                trade_date=day,
                fields=DEFAULT_FIELDS,
                universe_stats=None,
                probe=None,
                breadth=None,
                suspension_cross=None,
                login=login,
                logout=logout,
            )
        universe_stats, targets = _fetch_universe(client, day, budget)
        if universe_stats["conflicting_status_count"] > 0:
            universe_stats["contract_failure"] = "conflicting_status"
            return build_summary(
                mode="full",
                trade_date=day,
                fields=DEFAULT_FIELDS,
                universe_stats=universe_stats,
                probe=None,
                breadth=None,
                suspension_cross=None,
                login=login,
                logout=logout,
            )
        if universe_stats["duplicate_code_count"] > 0:
            universe_stats["contract_warning"] = "duplicate_codes"
        if len(targets) > FULL_MAX_TARGETS:
            universe_stats["universe_too_large"] = True
            return build_summary(
                mode="full",
                trade_date=day,
                fields=DEFAULT_FIELDS,
                universe_stats=universe_stats,
                probe=None,
                breadth=None,
                suspension_cross=None,
                login=login,
                logout=logout,
            )
        all_results: List[Dict[str, Any]] = []
        probe_result = run_probe(
            client,
            targets,
            day,
            fields=DEFAULT_FIELDS,
            max_requests=budget[0],
            consecutive_fail_stop=CONSECUTIVE_FAIL_STOP,
            early_window=SAMPLE_EARLY_WINDOW,
            early_fail_rate=SAMPLE_EARLY_FAIL_RATE,
            fail_rate_stop=FULL_FAIL_RATE,
            fail_count_stop=FULL_FAIL_STOP,
            wall_clock_limit=WALL_CLOCK_LIMIT_SECONDS,
            retries=retries,
            determinism_checks=determinism_checks,
            sleep=sleep,
            result_sink=all_results,
        )
        counts = probe_result["counts"]
        meta = {
            "processed_target_count": probe_result["processed_target_count"],
            "failure_count": counts["failure"],
            "empty_count": counts["empty"],
            "date_mismatch": counts["date_mismatch"],
            "code_mismatch": counts["code_mismatch"],
            "duplicate_row": counts["duplicate"],
            "invalid_pct_chg": counts["invalid_pct_chg"],
            "trade_status_mismatch": counts["trade_status_mismatch"],
            "circuit_open": probe_result["circuit_open"],
            "budget_exhausted": probe_result["budget_exhausted"],
            "duplicate_code_count": universe_stats["duplicate_code_count"],
            "conflicting_status_count": universe_stats["conflicting_status_count"],
        }
        breadth = compute_breadth(targets, all_results, meta)
    finally:
        logout = client.logout()
    return build_summary(
        mode="full",
        trade_date=day,
        fields=DEFAULT_FIELDS,
        universe_stats=universe_stats,
        probe=probe_result,
        breadth=breadth,
        suspension_cross=None,
        login=login,
        logout=logout,
    )


def run_cross_probe(
    client: Any,
    day: str,
    suspension_file: str,
) -> Dict[str, Any]:
    """停牌交叉验证编排（BaoStock vs 东财指定日期停复牌文件）。"""
    budget = [10]
    login = client.login()
    budget[0] -= 1
    logout: Optional[Dict[str, Any]] = None
    universe_stats: Optional[Dict[str, Any]] = None
    suspension_cross: Optional[Dict[str, Any]] = None
    try:
        if not login["ok"]:
            return build_summary(
                mode="cross",
                trade_date=day,
                fields=DEFAULT_FIELDS,
                universe_stats=None,
                probe=None,
                breadth=None,
                suspension_cross=None,
                login=login,
                logout=logout,
            )
        universe_stats, targets = _fetch_universe(client, day, budget)
        if universe_stats["conflicting_status_count"] > 0:
            universe_stats["contract_failure"] = "conflicting_status"
            return build_summary(
                mode="cross",
                trade_date=day,
                fields=DEFAULT_FIELDS,
                universe_stats=universe_stats,
                probe=None,
                breadth=None,
                suspension_cross=None,
                login=login,
                logout=logout,
            )
        bs_suspended = [e["code"] for e in targets if e["trade_status"] == "0"]
        with open(suspension_file, encoding="utf-8") as f:
            em_suspended = [line.strip() for line in f if line.strip()]
        suspension_cross = cross_check_suspension(bs_suspended, em_suspended)
    finally:
        logout = client.logout()
    return build_summary(
        mode="cross",
        trade_date=day,
        fields=DEFAULT_FIELDS,
        universe_stats=universe_stats,
        probe=None,
        breadth=None,
        suspension_cross=suspension_cross,
        login=login,
        logout=logout,
    )


def _validate_cli_args(args: argparse.Namespace) -> None:
    """任何 login/live 请求前完成参数校验；非法参数抛 ProbeError。"""
    if _strict_parse_date(args.trade_date) is None:
        raise ProbeError("invalid trade date; must be strict YYYY-MM-DD")
    if not (1 <= args.sample_size <= MAX_SAMPLE_SIZE):
        raise ProbeError(f"sample_size must be in 1..{MAX_SAMPLE_SIZE}")
    if not (0 <= args.retries <= MAX_RETRY):
        raise ProbeError(f"retries must be in 0..{MAX_RETRY}")
    if not (0 <= args.determinism_checks <= MAX_DETERMINISM_CHECKS):
        raise ProbeError(
            f"determinism_checks must be in 0..{MAX_DETERMINISM_CHECKS}"
        )
    if args.mode == "sample":
        budget = (
            SAMPLE_DEFAULT_MAX_REQUESTS
            if args.max_requests <= 0
            else args.max_requests
        )
        if not (1 <= budget <= SAMPLE_DEFAULT_MAX_REQUESTS):
            raise ProbeError(
                f"sample max_requests must be in 1..{SAMPLE_DEFAULT_MAX_REQUESTS}"
            )
    elif args.mode == "full":
        budget = FULL_MAX_REQUESTS if args.max_requests <= 0 else args.max_requests
        if not (1 <= budget <= FULL_MAX_REQUESTS):
            raise ProbeError(
                f"full max_requests must be in 1..{FULL_MAX_REQUESTS}"
            )
    if args.mode == "cross" and not args.suspension_file:
        raise ProbeError("--suspension-file is required for cross mode")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="BaoStock 零成本数据源可行性探测（研究工具，聚合输出）"
    )
    parser.add_argument("--mode", required=True, choices=("sample", "full", "cross"))
    parser.add_argument("--trade-date", required=True, help="严格 YYYY-MM-DD，必须显式传入")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--retries", type=int, default=MAX_RETRY)
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--determinism-checks", type=int, default=DEFAULT_DETERMINISM_CHECKS)
    parser.add_argument("--suspension-file", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        _validate_cli_args(args)
    except ProbeError as exc:
        print(f"invalid arguments: {exc}", file=sys.stderr)
        return 2

    client = BaoStockClient()
    try:
        if args.mode == "sample":
            summary = run_sample_probe(
                client,
                args.trade_date,
                sample_size=args.sample_size,
                seed=args.seed,
                max_requests=args.max_requests,
                retries=args.retries,
                determinism_checks=args.determinism_checks,
            )
        elif args.mode == "full":
            summary = run_full_probe(
                client,
                args.trade_date,
                max_requests=args.max_requests,
                retries=args.retries,
                determinism_checks=args.determinism_checks,
            )
        else:
            summary = run_cross_probe(
                client,
                args.trade_date,
                args.suspension_file,
            )
    except ProbeError as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 2
    _emit(summary, args.output)
    return 0


def _emit(summary: Dict[str, Any], output: str) -> None:
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
