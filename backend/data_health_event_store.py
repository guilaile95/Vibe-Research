"""极小数据健康事件存储（单进程线程安全、原子写入、fail-closed）。

路径：VR_DATA_DIR/data_health_events.json
schema：data-health-events.v1

单条记录仅允许：source_id / last_success_at / last_error_at / last_error_code
顶层仅允许：schema_version / events
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA_VERSION = "data-health-events.v1"
EVENTS_FILENAME = "data_health_events.json"

# 可写入事件的 6 个事件型来源
EVENT_SOURCE_IDS = frozenset({
    "portfolio_advice_gate",
    "portfolio_quotes",
    "quotes",
    "announcements",
    "financials",
    "sector_research",
})

GATE_BUSINESS_CODES = frozenset({
    "NO_HOLDINGS",
    "HOLDING_QUOTES_UNAVAILABLE",
    "MARKET_BREADTH_UNAVAILABLE",
    "REVIEW_TRADE_DATE_UNAVAILABLE",
})

# Gate 可持久化 error_code
GATE_ALLOWED_ERROR_CODES = GATE_BUSINESS_CODES | frozenset({
    "SOURCE_TIMEOUT",
    "SOURCE_UNAVAILABLE",
})

# 非 Gate 事件来源可持久化 error_code（禁止四项 Gate 业务码）
NON_GATE_ALLOWED_ERROR_CODES = frozenset({
    "SOURCE_PARTIAL",
    "SOURCE_DEGRADED",
    "SOURCE_UNAVAILABLE",
    "SOURCE_CORRUPTED",
    "SOURCE_SCHEMA_INCOMPATIBLE",
    "SOURCE_TIMEOUT",
})

# 兼容旧名：全集（仅作文档/测试参考，校验走 source-specific）
ALLOWED_PERSISTED_ERROR_CODES = GATE_ALLOWED_ERROR_CODES | NON_GATE_ALLOWED_ERROR_CODES

# 规范 UTC：YYYY-MM-DDTHH:MM:SS.ffffffZ
_CANONICAL_UTC_RE = __import__("re").compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)

_RECORD_KEYS = frozenset({
    "source_id",
    "last_success_at",
    "last_error_at",
    "last_error_code",
})
_TOP_KEYS = frozenset({"schema_version", "events"})

_LOCK = threading.Lock()


class DataHealthEventStoreError(RuntimeError):
    """事件存储拒绝读写（损坏 / 高版本 / 非法字段等）。"""


def data_dir() -> str:
    return os.environ.get("VR_DATA_DIR") or os.path.join(
        os.path.expanduser("~"), ".vibe-research"
    )


def events_path() -> str:
    return os.path.join(data_dir(), EVENTS_FILENAME)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # 固定微秒精度，便于单调 +1µs
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"


def parse_utc(value: str | None) -> datetime | None:
    """仅接受规范 UTC：YYYY-MM-DDTHH:MM:SS.ffffffZ。非法返回 None。"""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or not _CANONICAL_UTC_RE.match(s):
        return None
    try:
        dt = datetime(
            int(s[0:4]), int(s[5:7]), int(s[8:10]),
            int(s[11:13]), int(s[14:16]), int(s[17:19]),
            int(s[20:26]),
            tzinfo=timezone.utc,
        )
    except (TypeError, ValueError):
        return None
    return dt


def allowed_error_codes_for(source_id: str) -> frozenset[str]:
    if source_id == "portfolio_advice_gate":
        return GATE_ALLOWED_ERROR_CODES
    return NON_GATE_ALLOWED_ERROR_CODES


def _max_existing_time(rec: dict[str, Any]) -> datetime | None:
    times: list[datetime] = []
    for key in ("last_success_at", "last_error_at"):
        dt = parse_utc(rec.get(key))
        if dt is not None:
            times.append(dt)
    if not times:
        return None
    return max(times)


def _next_observation_time(
    rec: dict[str, Any] | None,
    now: datetime | None = None,
) -> datetime:
    candidate = now if now is not None else _utc_now()
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    else:
        candidate = candidate.astimezone(timezone.utc)
    if rec is None:
        return candidate
    existing = _max_existing_time(rec)
    if existing is not None and candidate <= existing:
        return existing + timedelta(microseconds=1)
    return candidate


def _empty_store() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "events": {}}


def _validate_time_field(value: Any, *, allow_null: bool = True) -> None:
    if value is None:
        if allow_null:
            return
        raise DataHealthEventStoreError("illegal time")
    if not isinstance(value, str):
        raise DataHealthEventStoreError("illegal time")
    if parse_utc(value) is None:
        raise DataHealthEventStoreError("illegal time")


def _validate_record(source_id: str, rec: Any) -> dict[str, Any]:
    if not isinstance(rec, dict):
        raise DataHealthEventStoreError("illegal record")
    extra = set(rec.keys()) - _RECORD_KEYS
    if extra:
        raise DataHealthEventStoreError("extra record fields")
    missing = _RECORD_KEYS - set(rec.keys())
    if missing:
        raise DataHealthEventStoreError("missing record fields")
    if rec.get("source_id") != source_id:
        raise DataHealthEventStoreError("source_id mismatch")
    if source_id not in EVENT_SOURCE_IDS:
        raise DataHealthEventStoreError("unknown source_id")
    _validate_time_field(rec.get("last_success_at"))
    _validate_time_field(rec.get("last_error_at"))
    code = rec.get("last_error_code")
    err_at = rec.get("last_error_at")
    # error 字段必须成对：at is None ⇔ code is None
    if (err_at is None) != (code is None):
        raise DataHealthEventStoreError("error fields unpaired")
    if code is not None:
        if not isinstance(code, str):
            raise DataHealthEventStoreError("illegal error_code")
        if code == "SOURCE_NOT_INITIALIZED":
            raise DataHealthEventStoreError("illegal error_code")
        allowed = allowed_error_codes_for(source_id)
        if code not in allowed:
            raise DataHealthEventStoreError("illegal error_code for source")
    # 至少一个时间字段有值
    if rec.get("last_success_at") is None and rec.get("last_error_at") is None:
        raise DataHealthEventStoreError("empty record times")
    return rec


def _validate_store(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DataHealthEventStoreError("invalid root")
    extra = set(data.keys()) - _TOP_KEYS
    if extra:
        raise DataHealthEventStoreError("extra top-level fields")
    missing = _TOP_KEYS - set(data.keys())
    if missing:
        raise DataHealthEventStoreError("missing top-level fields")
    ver = data.get("schema_version")
    if not isinstance(ver, str):
        raise DataHealthEventStoreError("illegal schema_version")
    if ver != SCHEMA_VERSION:
        # 高版本或未知版本均拒绝
        raise DataHealthEventStoreError("unsupported schema_version")
    events = data.get("events")
    if not isinstance(events, dict):
        raise DataHealthEventStoreError("illegal events")
    for sid, rec in events.items():
        if not isinstance(sid, str) or sid not in EVENT_SOURCE_IDS:
            raise DataHealthEventStoreError("unknown source_id")
        _validate_record(sid, rec)
    return data


def _read_store_file(path: str) -> dict[str, Any]:
    """读取并严格校验；文件不存在返回空 store。损坏/非法抛 DataHealthEventStoreError。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return _empty_store()
    except OSError as e:
        raise DataHealthEventStoreError("read failed") from e
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError) as e:
        raise DataHealthEventStoreError("json corrupted") from e
    return _validate_store(data)


def load_events_readonly() -> dict[str, dict[str, Any]]:
    """只读加载 events 映射。

    - 文件不存在 → 空 dict
    - 不创建目录/文件，不更新 mtime，不迁移，不写备份
    - 损坏/高版本/额外字段 → 抛 DataHealthEventStoreError（调用方映射 SOURCE_CORRUPTED）
    """
    path = events_path()
    # 不持写锁也可：只读路径；与写锁串行由写入方保证
    data = _read_store_file(path)
    # 深拷贝避免调用方篡改
    out: dict[str, dict[str, Any]] = {}
    for sid, rec in data.get("events", {}).items():
        out[sid] = {
            "source_id": rec["source_id"],
            "last_success_at": rec.get("last_success_at"),
            "last_error_at": rec.get("last_error_at"),
            "last_error_code": rec.get("last_error_code"),
        }
    return out


def _atomic_write(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp = path + f".tmp.{os.urandom(4).hex()}"
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _blank_record(source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "last_success_at": None,
        "last_error_at": None,
        "last_error_code": None,
    }


def _mutate(
    source_id: str,
    mutator,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if source_id not in EVENT_SOURCE_IDS:
        raise DataHealthEventStoreError("unknown source_id")
    path = events_path()
    with _LOCK:
        data = _read_store_file(path)
        events = data["events"]
        existing = events.get(source_id)
        if existing is not None:
            # 再校验一次
            existing = _validate_record(source_id, existing)
            rec = dict(existing)
        else:
            rec = _blank_record(source_id)
        obs = _next_observation_time(existing, now=now)
        mutator(rec, obs)
        # 拒绝写入 SOURCE_NOT_INITIALIZED
        if rec.get("last_error_code") == "SOURCE_NOT_INITIALIZED":
            raise DataHealthEventStoreError("illegal error_code")
        validated = _validate_record(source_id, rec)
        events[source_id] = validated
        data = {"schema_version": SCHEMA_VERSION, "events": events}
        _validate_store(data)
        _atomic_write(path, data)
        return dict(validated)


def record_success(source_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """完整成功：更新 last_success_at，保留历史错误。"""

    def mut(rec: dict[str, Any], obs: datetime) -> None:
        rec["last_success_at"] = _format_utc(obs)

    return _mutate(source_id, mut, now=now)


def record_partial(source_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """部分成功：同一 observation_time 写 success + SOURCE_PARTIAL。"""

    def mut(rec: dict[str, Any], obs: datetime) -> None:
        ts = _format_utc(obs)
        rec["last_success_at"] = ts
        rec["last_error_at"] = ts
        rec["last_error_code"] = "SOURCE_PARTIAL"

    return _mutate(source_id, mut, now=now)


def record_degraded(source_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """降级成功：同一 observation_time 写 success + SOURCE_DEGRADED。"""

    def mut(rec: dict[str, Any], obs: datetime) -> None:
        ts = _format_utc(obs)
        rec["last_success_at"] = ts
        rec["last_error_at"] = ts
        rec["last_error_code"] = "SOURCE_DEGRADED"

    return _mutate(source_id, mut, now=now)


def record_failure(
    source_id: str,
    error_code: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Hard failure：只更新 last_error_at/code，保留 last_success_at。

    Gate 业务阻断码（NO_HOLDINGS / HOLDING_QUOTES_UNAVAILABLE /
    MARKET_BREADTH_UNAVAILABLE / REVIEW_TRADE_DATE_UNAVAILABLE）只能通过
    record_gate_blocked() 写入；通过 record_failure 写入视为编程错误。
    """
    if error_code == "SOURCE_NOT_INITIALIZED":
        raise DataHealthEventStoreError("illegal error_code")
    if source_id not in EVENT_SOURCE_IDS:
        raise DataHealthEventStoreError("unknown source_id")
    if source_id == "portfolio_advice_gate":
        # 当 source_id == portfolio_advice_gate：只允许 SOURCE_TIMEOUT / SOURCE_UNAVAILABLE
        if error_code in GATE_BUSINESS_CODES:
            raise DataHealthEventStoreError(
                "gate business code must go through record_gate_blocked"
            )
        if error_code not in ("SOURCE_TIMEOUT", "SOURCE_UNAVAILABLE"):
            raise DataHealthEventStoreError("illegal error_code for gate")
    else:
        if error_code not in allowed_error_codes_for(source_id):
            raise DataHealthEventStoreError("illegal error_code for source")

    def mut(rec: dict[str, Any], obs: datetime) -> None:
        rec["last_error_at"] = _format_utc(obs)
        rec["last_error_code"] = error_code

    return _mutate(source_id, mut, now=now)


def record_gate_allowed(*, now: datetime | None = None) -> dict[str, Any]:
    """Gate 评估允许：更新 last_success_at，保留历史错误。"""
    return record_success("portfolio_advice_gate", now=now)


def record_gate_blocked(
    error_code: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Gate 业务阻断：同次写 success=error=obs + 业务码。"""
    if error_code not in GATE_BUSINESS_CODES:
        raise DataHealthEventStoreError("illegal error_code")

    def mut(rec: dict[str, Any], obs: datetime) -> None:
        ts = _format_utc(obs)
        rec["last_success_at"] = ts
        rec["last_error_at"] = ts
        rec["last_error_code"] = error_code

    return _mutate("portfolio_advice_gate", mut, now=now)


def record_gate_failure(
    error_code: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Gate 运行失败：只写 last_error_at + SOURCE_TIMEOUT/SOURCE_UNAVAILABLE。"""
    if error_code not in ("SOURCE_TIMEOUT", "SOURCE_UNAVAILABLE"):
        raise DataHealthEventStoreError("illegal error_code")
    return record_failure("portfolio_advice_gate", error_code, now=now)


def safe_call(fn, *args, **kwargs) -> Any | None:
    """事件写入失败不得改变业务语义；仅吞掉异常并返回 None。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — 边界隔离
        try:
            import sys
            print(
                f"[data-health] event write failed: {type(exc).__name__}",
                file=sys.stderr,
            )
        except Exception:
            pass
        return None
