"""BK-11 T+1 可信 final 涨停池快照生产者 v0.1。

通过三次连续、间隔满足要求且内容一致的适配器观测，为已完成历史交易日
产生可信 final 快照。所有普通失败路径失败关闭；``KeyboardInterrupt`` /
``SystemExit`` / ``GeneratorExit`` 自然传播。

公开 API
--------
``fetch_final_limit_up_pool_snapshot(requested_trade_date: str) -> dict``

返回的 dict 始终包含完整合同字段（见 SCHEMA_VERSION 与函数签名）。

本版本只支持 ``requested_trade_date < Asia/Shanghai today`` 的已完成历史
交易日（T+1 复盘场景）。不通过任意时钟阈值猜测同日来源已经 final。

运行时观测只通过 ``short_term_limit_up_pool_adapter.fetch_limit_up_pool_snapshot``
进行，不直接调用行情上游，不复制适配器实现，不新增运行时依赖。

本生产者不得正向证明 legal zero：稳定重复的 source pool = [] 仍无法证明
全市场当日确实无涨停，适配器会将其标为 partial / UNEXPLAINED_EMPTY。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import trade_calendar
import short_term_limit_up_pool_adapter as pool_adapter

__all__ = [
    "SCHEMA_VERSION",
    "REQUIRED_OBSERVATIONS",
    "OBSERVATION_INTERVAL_SECONDS",
    "fetch_final_limit_up_pool_snapshot",
]

SCHEMA_VERSION = "short-term-limit-up-final-snapshot-v0.1"
REQUIRED_OBSERVATIONS = 3
OBSERVATION_INTERVAL_SECONDS = 2.2

_ADAPTER_SCHEMA_VERSION = pool_adapter.SCHEMA_VERSION
_ADAPTER_SOURCE_ID = "eastmoney_getTopicZTPool"
_ADAPTER_ENDPOINT = "getTopicZTPool"
# status=normal 的 final 候选必须携带完整适配器 v0.1 合同（25 字段）
_ADAPTER_REQUIRED_FIELDS = frozenset({
    "schema_version",
    "source_id",
    "endpoint",
    "requested_trade_date",
    "observed_at",
    "status",
    "reason_codes",
    "rows",
    "transport_success",
    "parse_success",
    "required_field_present",
    "data_array_present",
    "trade_date_match",
    "row_count",
    "legal_zero",
    "upstream_null",
    "unexplained_empty",
    "coverage_warning",
    "target_universe_empty_after_filter",
    "source_pool_row_count",
    "http_status",
    "error_class",
    "excluded_universe_count",
    "invalid_row_count",
    "duplicate_code_count",
})
_SHANGHAI_TZ = timezone(timedelta(hours=8))
_STRICT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SIX_DIGIT_RE = re.compile(r"^\d{6}$")
_VALID_SESSION_TYPES = (tuple, list, set, frozenset)
_STABILITY_EPSILON = 1e-9

# Reason code 固定集合与顺序（未知 code 不得进入输出）
_REASON_CODE_ORDER: tuple[str, ...] = (
    "NON_TRADING_DATE",
    "TRADING_CALENDAR_UNAVAILABLE",
    "NOT_FINAL",
    "SOURCE_UNAVAILABLE",
    "SOURCE_PARTIAL",
    "SNAPSHOT_SCHEMA_INVALID",
    "SNAPSHOT_UNSTABLE",
    "STABILITY_WINDOW_ERROR",
)
_REASON_CODE_SET = frozenset(_REASON_CODE_ORDER)

# 稳定指纹只覆盖确定性内容；observed_at / http_status / 耗时 / 内存地址 /
# 字段插入顺序均排除
_FINGERPRINT_KEYS: tuple[str, ...] = (
    "requested_trade_date",
    "rows",
    "row_count",
    "source_pool_row_count",
    "excluded_universe_count",
    "invalid_row_count",
    "duplicate_code_count",
    "target_universe_empty_after_filter",
    "trade_date_match",
    "legal_zero",
)

# 测试可 monkeypatch 的私有引用；不得公开
_fetch_adapter_snapshot = pool_adapter.fetch_limit_up_pool_snapshot
_sleep = time.sleep
_monotonic = time.monotonic


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strict_parse_date(s: str) -> Optional[date]:
    """严格 YYYY-MM-DD → date；无效日历日期返回 None。"""
    m = _STRICT_DATE_RE.match(s)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _normalize_reason_codes(codes: list[str]) -> list[str]:
    """去重、固定顺序；未知 reason code 丢弃（不得进入输出）。"""
    seen: set[str] = set()
    out: list[str] = []
    for code in _REASON_CODE_ORDER:
        if code in codes and code not in seen:
            out.append(code)
            seen.add(code)
    return out


def _output(
    *,
    requested_trade_date: str,
    status: str,
    reason_codes: list[str],
    session: str,
    is_final: bool,
    finality_basis: Optional[str],
    completed_observations: int,
    stable_observation_count: int,
    actual_window: Optional[float],
    first_mono: Optional[float],
    last_mono: Optional[float],
    snapshot: Optional[dict],
) -> dict:
    normalized = _normalize_reason_codes(reason_codes)
    return {
        "schema_version": SCHEMA_VERSION,
        "requested_trade_date": requested_trade_date,
        "observed_at": _now_utc_iso(),
        "status": status,
        "reason_codes": normalized,
        "session": session,
        "is_final": is_final,
        "finality_basis": finality_basis,
        "required_observations": REQUIRED_OBSERVATIONS,
        "completed_observations": completed_observations,
        "stable_observation_count": stable_observation_count,
        "observation_interval_seconds": OBSERVATION_INTERVAL_SECONDS,
        "required_stability_window_seconds": (
            OBSERVATION_INTERVAL_SECONDS * (REQUIRED_OBSERVATIONS - 1)
        ),
        "actual_stability_window_seconds": actual_window,
        "first_observation_monotonic": first_mono,
        "last_observation_monotonic": last_mono,
        "snapshot": snapshot,
        "warnings": [],
    }


def _failure(
    *,
    requested_trade_date: str,
    status: str,
    reason_codes: list[str],
    completed_observations: int = 0,
    stable_observation_count: int = 0,
    actual_window: Optional[float] = None,
    first_mono: Optional[float] = None,
    last_mono: Optional[float] = None,
) -> dict:
    return _output(
        requested_trade_date=requested_trade_date,
        status=status,
        reason_codes=reason_codes,
        session="not_final",
        is_final=False,
        finality_basis=None,
        completed_observations=completed_observations,
        stable_observation_count=stable_observation_count,
        actual_window=actual_window,
        first_mono=first_mono,
        last_mono=last_mono,
        snapshot=None,
    )


# ---------------------------------------------------------------------------
# 交易日历信任边界（与已批准适配器规则一致）
# ---------------------------------------------------------------------------

def _load_sessions_safe() -> tuple[Optional[Any], Optional[str]]:
    """安全加载 sessions。返回 ``(sessions, reason_code)``。

    容器必须非空，每个成员必须为严格合法 YYYY-MM-DD 字符串。
    KeyboardInterrupt/SystemExit/GeneratorExit 自然传播。
    """
    try:
        sessions = trade_calendar._load_calendar()
    except Exception:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if sessions is None:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if not isinstance(sessions, _VALID_SESSION_TYPES):
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if not sessions:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    for item in sessions:
        if type(item) is not str:
            return None, "TRADING_CALENDAR_UNAVAILABLE"
        if _strict_parse_date(item) is None:
            return None, "TRADING_CALENDAR_UNAVAILABLE"
    return sessions, None


def _today_shanghai_safe() -> tuple[Optional[date], Optional[str]]:
    """安全获取上海今日。返回 ``(today, reason_code)``。"""
    try:
        today = trade_calendar._today_shanghai()
    except Exception:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    if type(today) is not date:
        return None, "TRADING_CALENDAR_UNAVAILABLE"
    return today, None


# ---------------------------------------------------------------------------
# 时钟与 sleep（失败关闭）
# ---------------------------------------------------------------------------

def _safe_monotonic() -> tuple[Optional[float], Optional[str]]:
    """安全读取 monotonic 时钟。返回 ``(t, reason_code)``。"""
    try:
        t = _monotonic()
    except Exception:
        return None, "STABILITY_WINDOW_ERROR"
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None, "STABILITY_WINDOW_ERROR"
    if math.isnan(float(t)) or math.isinf(float(t)):
        return None, "STABILITY_WINDOW_ERROR"
    return float(t), None


def _safe_sleep(seconds: float) -> Optional[str]:
    """安全 sleep。返回 None 或 ``STABILITY_WINDOW_ERROR``。"""
    try:
        _sleep(seconds)
    except Exception:
        return "STABILITY_WINDOW_ERROR"
    return None


# ---------------------------------------------------------------------------
# 适配器观测
# ---------------------------------------------------------------------------

def _fetch_adapter(requested_trade_date: str) -> tuple[Optional[dict], Optional[str]]:
    """调用适配器。返回 ``(obs, reason_code)``。进程控制异常自然传播。"""
    try:
        obs = _fetch_adapter_snapshot(requested_trade_date)
    except Exception:
        return None, "SOURCE_UNAVAILABLE"
    return obs, None


def _check_row(row: Any) -> Optional[str]:
    """行合同：dict、字段集严格等于 stock_code+lbc、代码六位数字、lbc int>0。"""
    if not isinstance(row, dict):
        return "SNAPSHOT_SCHEMA_INVALID"
    if set(row.keys()) != {"stock_code", "lbc"}:
        return "SNAPSHOT_SCHEMA_INVALID"
    code = row.get("stock_code")
    lbc = row.get("lbc")
    if not isinstance(code, str) or _SIX_DIGIT_RE.match(code) is None:
        return "SNAPSHOT_SCHEMA_INVALID"
    if isinstance(lbc, bool) or not isinstance(lbc, int) or lbc <= 0:
        return "SNAPSHOT_SCHEMA_INVALID"
    return None


def _check_rows(rows: Any) -> Optional[str]:
    """rows 必须为 list、每行合同正确、升序且唯一。"""
    if not isinstance(rows, list):
        return "SNAPSHOT_SCHEMA_INVALID"
    seen: set[str] = set()
    prev_code: Optional[str] = None
    for row in rows:
        err = _check_row(row)
        if err is not None:
            return err
        code = row["stock_code"]
        if code in seen:
            return "SNAPSHOT_SCHEMA_INVALID"
        seen.add(code)
        if prev_code is not None and code < prev_code:
            return "SNAPSHOT_SCHEMA_INVALID"
        prev_code = code
    return None


def _validate_common_contract(obs: Any, requested_trade_date: str) -> Optional[str]:
    """完整字段集合 + 公共字段类型校验（在 status 分类之前）。

    返回 None（通过）或 ``SNAPSHOT_SCHEMA_INVALID``。
    """
    if not isinstance(obs, dict):
        return "SNAPSHOT_SCHEMA_INVALID"
    if set(obs.keys()) != _ADAPTER_REQUIRED_FIELDS:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("schema_version") != _ADAPTER_SCHEMA_VERSION:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("source_id") != _ADAPTER_SOURCE_ID:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("endpoint") != _ADAPTER_ENDPOINT:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("requested_trade_date") != requested_trade_date:
        return "SNAPSHOT_SCHEMA_INVALID"
    observed_at = obs.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at:
        return "SNAPSHOT_SCHEMA_INVALID"
    try:
        parsed_observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return "SNAPSHOT_SCHEMA_INVALID"
    if parsed_observed.tzinfo is None or parsed_observed.utcoffset() != timedelta(0):
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("status") not in ("normal", "partial", "unavailable"):
        return "SNAPSHOT_SCHEMA_INVALID"
    reason_codes = obs.get("reason_codes")
    if not isinstance(reason_codes, list):
        return "SNAPSHOT_SCHEMA_INVALID"
    if any(type(code) is not str for code in reason_codes):
        return "SNAPSHOT_SCHEMA_INVALID"
    if not isinstance(obs.get("rows"), list):
        return "SNAPSHOT_SCHEMA_INVALID"
    for key in (
        "transport_success", "parse_success", "required_field_present",
        "data_array_present", "legal_zero", "upstream_null",
        "unexplained_empty", "coverage_warning",
        "target_universe_empty_after_filter",
    ):
        if type(obs.get(key)) is not bool:
            return "SNAPSHOT_SCHEMA_INVALID"
    trade_date_match = obs.get("trade_date_match")
    if trade_date_match is not True and trade_date_match is not False \
            and trade_date_match is not None:
        return "SNAPSHOT_SCHEMA_INVALID"
    row_count = obs.get("row_count")
    if type(row_count) is not int or row_count < 0:
        return "SNAPSHOT_SCHEMA_INVALID"
    source_count = obs.get("source_pool_row_count")
    if type(source_count) is not int or source_count < 0:
        return "SNAPSHOT_SCHEMA_INVALID"
    http_status = obs.get("http_status")
    if http_status is not None and (
            type(http_status) is not int or http_status < 100 or http_status > 599):
        return "SNAPSHOT_SCHEMA_INVALID"
    error_class = obs.get("error_class")
    if not isinstance(error_class, str) or not error_class:
        return "SNAPSHOT_SCHEMA_INVALID"
    for key in ("excluded_universe_count", "invalid_row_count",
                "duplicate_code_count"):
        value = obs.get(key)
        if type(value) is not int or value < 0:
            return "SNAPSHOT_SCHEMA_INVALID"
    return None


def _normal_admission(obs: dict) -> Optional[str]:
    """status=normal 的完整准入。返回 None（通过）或失败 reason code。"""
    if obs.get("reason_codes") != []:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("transport_success") is not True:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("parse_success") is not True:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("required_field_present") is not True:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("data_array_present") is not True:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("trade_date_match") is not True:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("coverage_warning") is not False:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("upstream_null") is not False:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("unexplained_empty") is not False:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("legal_zero") is not False:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("error_class") != "NONE":
        return "SNAPSHOT_SCHEMA_INVALID"
    # 精确零判定：bool 不得冒充 0
    if obs.get("invalid_row_count") != 0:
        return "SNAPSHOT_SCHEMA_INVALID"
    if obs.get("duplicate_code_count") != 0:
        return "SNAPSHOT_SCHEMA_INVALID"
    rows = obs.get("rows")
    if _check_rows(rows) is not None:
        return "SNAPSHOT_SCHEMA_INVALID"
    row_count = obs.get("row_count")
    source_count = obs.get("source_pool_row_count")
    excluded = obs.get("excluded_universe_count")
    if row_count != len(rows):
        return "SNAPSHOT_SCHEMA_INVALID"
    if source_count != row_count + excluded:
        return "SNAPSHOT_SCHEMA_INVALID"
    target_empty = obs.get("target_universe_empty_after_filter")
    if rows:
        if target_empty is not False:
            return "SNAPSHOT_SCHEMA_INVALID"
    else:
        # 目标 universe 为空：来源池非空且全部被 universe 排除
        if source_count <= 0:
            return "SNAPSHOT_SCHEMA_INVALID"
        if excluded != source_count:
            return "SNAPSHOT_SCHEMA_INVALID"
        if target_empty is not True:
            return "SNAPSHOT_SCHEMA_INVALID"
    return None


def _classify_observation(obs: Any, requested_trade_date: str) -> Optional[str]:
    """完整合同 + 公共类型校验 → status 分类 → normal 完整准入。

    返回 None（normal 通过）或失败 reason code：
    SOURCE_UNAVAILABLE / SOURCE_PARTIAL / SNAPSHOT_SCHEMA_INVALID。
    """
    common_err = _validate_common_contract(obs, requested_trade_date)
    if common_err is not None:
        return common_err
    status = obs.get("status")
    if status == "unavailable":
        return "SOURCE_UNAVAILABLE"
    if status == "partial":
        return "SOURCE_PARTIAL"
    return _normal_admission(obs)


def _canonicalize_observation(obs: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 ``(canonical_string, digest, error_code)``。

    canonical JSON 使用 ``allow_nan=False``；任何普通异常（含 digest 计算）
    结构化失败为 ``SNAPSHOT_SCHEMA_INVALID``，不泄漏异常原文。
    进程控制异常自然传播。
    """
    try:
        canonical_payload = {key: obs[key] for key in _FINGERPRINT_KEYS}
        canonical_string = json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except Exception:
        return None, None, "SNAPSHOT_SCHEMA_INVALID"
    try:
        digest = hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()
    except Exception:
        return None, None, "SNAPSHOT_SCHEMA_INVALID"
    return canonical_string, digest, None


def _timing(times: list[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """由 observation-start 时间序列推导 ``(first, last, actual)``。

    无时间：全部 None；一条：first=last、actual=0.0；两条及以上：last-first。
    """
    if not times:
        return None, None, None
    first = times[0]
    last = times[-1]
    return first, last, last - first


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def fetch_final_limit_up_pool_snapshot(requested_trade_date: str) -> dict:
    """对已完成历史交易日的涨停池快照执行 T+1 可信 final 生产。

    日期预检、日历校验全部在首次适配器请求前完成；失败路径不发起
    无意义请求与等待。本函数不会抛出未处理的普通异常。
    KeyboardInterrupt / SystemExit / GeneratorExit 自然传播。
    """
    # 1) 输入预检（不得调用适配器）
    if not isinstance(requested_trade_date, str) or not requested_trade_date:
        return _failure(
            requested_trade_date=(
                requested_trade_date if isinstance(requested_trade_date, str) else ""
            ),
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
        )
    if _STRICT_DATE_RE.match(requested_trade_date) is None:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
        )
    req_date = _strict_parse_date(requested_trade_date)
    if req_date is None:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
        )

    # 2) 交易日历（失败关闭，0 请求）
    sessions, cal_err = _load_sessions_safe()
    if cal_err is not None:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=[cal_err],
        )
    today, today_err = _today_shanghai_safe()
    if today_err is not None:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=[today_err],
        )
    if requested_trade_date not in sessions:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NON_TRADING_DATE"],
        )
    if req_date >= today:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NOT_FINAL"],
        )

    # 3) 连续稳定观测（无 pre-loop monotonic 锚点；成功路径恰 3 次读取）
    observation_times: list[float] = []
    observations: list[dict] = []
    canonical_strings: list[str] = []
    digests: list[str] = []
    stable_count = 0
    completed_observations = 0

    for i in range(REQUIRED_OBSERVATIONS):
        if i > 0:
            sleep_err = _safe_sleep(OBSERVATION_INTERVAL_SECONDS)
            if sleep_err is not None:
                first, last, actual = _timing(observation_times)
                return _failure(
                    requested_trade_date=requested_trade_date,
                    status="unavailable",
                    reason_codes=[sleep_err],
                    completed_observations=completed_observations,
                    stable_observation_count=stable_count,
                    actual_window=actual,
                    first_mono=first,
                    last_mono=last,
                )
        t, clock_err = _safe_monotonic()
        if clock_err is not None:
            first, last, actual = _timing(observation_times)
            return _failure(
                requested_trade_date=requested_trade_date,
                status="unavailable",
                reason_codes=[clock_err],
                completed_observations=completed_observations,
                stable_observation_count=stable_count,
                actual_window=actual,
                first_mono=first,
                last_mono=last,
            )
        if observation_times and t < observation_times[-1]:
            # 时钟倒退：失败关闭
            first, last, actual = _timing(observation_times)
            return _failure(
                requested_trade_date=requested_trade_date,
                status="unavailable",
                reason_codes=["STABILITY_WINDOW_ERROR"],
                completed_observations=completed_observations,
                stable_observation_count=stable_count,
                actual_window=actual,
                first_mono=first,
                last_mono=last,
            )
        observation_times.append(t)

        obs, source_err = _fetch_adapter(requested_trade_date)
        if source_err is not None:
            # 适配器抛普通异常：该次不计入 completed_observations
            first, last, actual = _timing(observation_times)
            return _failure(
                requested_trade_date=requested_trade_date,
                status="unavailable",
                reason_codes=[source_err],
                completed_observations=completed_observations,
                stable_observation_count=stable_count,
                actual_window=actual,
                first_mono=first,
                last_mono=last,
            )
        # 适配器调用正常返回一个值 → 计入 completed_observations
        completed_observations += 1
        admission_err = _classify_observation(obs, requested_trade_date)
        if admission_err is not None:
            status = (
                "partial" if admission_err == "SOURCE_PARTIAL" else "unavailable"
            )
            first, last, actual = _timing(observation_times)
            return _failure(
                requested_trade_date=requested_trade_date,
                status=status,
                reason_codes=[admission_err],
                completed_observations=completed_observations,
                stable_observation_count=stable_count,
                actual_window=actual,
                first_mono=first,
                last_mono=last,
            )
        canonical, digest, canon_err = _canonicalize_observation(obs)
        if canon_err is not None:
            first, last, actual = _timing(observation_times)
            return _failure(
                requested_trade_date=requested_trade_date,
                status="unavailable",
                reason_codes=[canon_err],
                completed_observations=completed_observations,
                stable_observation_count=stable_count,
                actual_window=actual,
                first_mono=first,
                last_mono=last,
            )
        if not canonical_strings or canonical == canonical_strings[0]:
            stable_count += 1
        observations.append(obs)
        canonical_strings.append(canonical)
        digests.append(digest)

    first_mono, last_mono, actual_window = _timing(observation_times)
    required_window = OBSERVATION_INTERVAL_SECONDS * (REQUIRED_OBSERVATIONS - 1)

    if actual_window is None or actual_window + _STABILITY_EPSILON < required_window:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["STABILITY_WINDOW_ERROR"],
            completed_observations=completed_observations,
            stable_observation_count=stable_count,
            actual_window=actual_window,
            first_mono=first_mono,
            last_mono=last_mono,
        )

    # 稳定性最终依据：三份 canonical JSON string 完全一致（digest 仅辅助）
    if len(set(canonical_strings)) != 1:
        return _failure(
            requested_trade_date=requested_trade_date,
            status="unavailable",
            reason_codes=["NOT_FINAL", "SNAPSHOT_UNSTABLE"],
            completed_observations=completed_observations,
            stable_observation_count=stable_count,
            actual_window=actual_window,
            first_mono=first_mono,
            last_mono=last_mono,
        )

    return _output(
        requested_trade_date=requested_trade_date,
        status="normal",
        reason_codes=[],
        session="final",
        is_final=True,
        finality_basis="three_identical_normal_observations",
        completed_observations=REQUIRED_OBSERVATIONS,
        stable_observation_count=REQUIRED_OBSERVATIONS,
        actual_window=actual_window,
        first_mono=first_mono,
        last_mono=last_mono,
        snapshot=observations[-1],
    )
