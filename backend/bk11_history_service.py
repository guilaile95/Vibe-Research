"""BK-11 短线市场历史只读查询服务（生产接入 v0.1）。

职责：从已批准的 ``short_term_fact_store`` 读取每日权威快照，并复用已批准
的纯计算链（snapshot selector / fact compare / fact summary / fact digest）
组装一个确定性的历史查询 envelope。

硬性边界：

- 只读：不写数据库、不创建数据库文件、不修改快照、不自动修复损坏数据、
  不发起外部请求。
- 不使用系统当前时间改变业务结果；data_time 只取自存储快照自身。
- 不泄漏数据库路径、异常文本或 traceback。
- 普通存储异常失败关闭为稳定 error envelope；KeyboardInterrupt /
  SystemExit / GeneratorExit 自然传播。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import short_term_fact_compare as fact_compare
import short_term_fact_digest as fact_digest
import short_term_fact_store as store
import short_term_fact_summary as fact_summary
import short_term_snapshot_selector as snapshot_selector

SCHEMA_VERSION = "bk11-history-query-v0.1"
DEFAULT_DAYS = 5
MAX_DAYS = 60

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RESPONSE_STATUSES = frozenset({"normal", "partial", "unavailable"})

_FIXED_LIMITATIONS = {
    "empty": ["暂无已保存的 BK-11 短线历史快照。"],
    "error": ["短线市场历史存储当前无法安全读取。"],
    "normal": [
        "数据来自本地 BK-11 历史存储；生产快照写入仍受上游输入缺失阻塞。",
    ],
    "partial": [
        "数据来自本地 BK-11 历史存储；最新快照仅部分可用。",
        "生产快照写入仍受上游输入缺失阻塞。",
    ],
    "unavailable": [
        "数据来自本地 BK-11 历史存储；最新快照当前不可用。",
        "生产快照写入仍受上游输入缺失阻塞。",
    ],
}

_FIXED_REASON_CODES = {
    "empty": ["SOURCE_NOT_INITIALIZED"],
    "error": ["SOURCE_CORRUPTED"],
    "normal": [],
    "partial": ["SOURCE_PARTIAL"],
    "unavailable": ["SOURCE_UNAVAILABLE"],
}


def _base_envelope(days: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "empty",
        "window": {"requested": days, "snapshot_count": 0},
        "trade_date": None,
        "data_time": None,
        "snapshots": [],
        "latest": None,
        "delta": None,
        "summary": None,
        "digest": None,
        "reason_codes": [],
        "warnings": [],
        "limitations": [],
    }


def empty_envelope(days: int) -> dict[str, Any]:
    env = _base_envelope(days)
    env["status"] = "empty"
    env["reason_codes"] = list(_FIXED_REASON_CODES["empty"])
    env["limitations"] = list(_FIXED_LIMITATIONS["empty"])
    return env


def error_envelope(days: int) -> dict[str, Any]:
    env = _base_envelope(days)
    env["status"] = "error"
    env["reason_codes"] = list(_FIXED_REASON_CODES["error"])
    env["limitations"] = list(_FIXED_LIMITATIONS["error"])
    return env


def _valid_stored_envelope(envelope: Any) -> bool:
    """已存 daily-facts envelope 的最小 fail-closed 校验。

    只做读路径需要的形状校验；写入校验仍由 store 负责。
    """
    if type(envelope) is not dict:
        return False
    if envelope.get("schema_version") != store.STORED_SCHEMA_VERSION:
        return False
    trade_date = envelope.get("trade_date")
    if type(trade_date) is not str or _TRADE_DATE_RE.match(trade_date) is None:
        return False
    session = envelope.get("session")
    if type(session) is not str or session not in store._ALLOWED_SESSIONS:
        return False
    status = envelope.get("status")
    if type(status) is not str or status not in _RESPONSE_STATUSES:
        return False
    if type(envelope.get("is_final")) is not bool:
        return False
    sections = envelope.get("sections")
    if type(sections) is not dict or set(sections.keys()) != {
            "facts", "ladder", "gap"}:
        return False
    return True


def query_history(
    days: int = DEFAULT_DAYS,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """查询有界历史窗口（最新 ``days`` 个交易日），永不写入任何文件。

    返回值：
    - 数据库不存在 → ``empty`` envelope（不创建数据库文件）
    - 数据库损坏 / 已存 envelope 非法 / 前后序快照缺一 → ``error``
      envelope（fail-closed，无异常文本与路径）
    - 正常 → status 跟随最新快照（normal / partial / unavailable），
      附 delta（最新 vs 最近前序）、窗口 summary、确定性 digest。
    """
    path = store.resolve_db_path(db_path)
    if not path.exists():
        return empty_envelope(days)

    try:
        snapshots = store.list_snapshots(path)
        selection = snapshot_selector.select_daily_snapshots(snapshots)
        if selection["status"] != "normal" or not selection["selection"]:
            return empty_envelope(days)
        rows = list(selection["selection"])  # 按 trade_date 升序

        # 有界窗口：只取最新 days 个交易日
        window_rows = rows[-days:]
        envelopes = [
            _load_selected(path, row) for row in window_rows
        ]

        # 最近一个可比较的前序快照（不随窗口缩小而丢失）
        delta: dict[str, Any] | None = None
        if len(rows) >= 2:
            prev_env = _load_selected(path, rows[-2])
            delta = fact_compare.compute_fact_compare(prev_env, envelopes[-1])

        summary = fact_summary.compute_fact_summary(envelopes)
        digest = fact_digest.build_fact_digest(summary)
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except (store.FactStoreError, OSError):
        return error_envelope(days)

    latest = envelopes[-1]
    status = latest["status"]
    response = _base_envelope(days)
    response["status"] = status
    response["window"] = {
        "requested": days,
        "snapshot_count": len(window_rows),
    }
    response["trade_date"] = latest["trade_date"]
    response["data_time"] = latest.get("snapshot_at") or latest.get("fetched_at")
    response["snapshots"] = [dict(row) for row in window_rows]
    response["latest"] = latest
    response["delta"] = delta
    response["summary"] = summary
    response["digest"] = digest
    response["reason_codes"] = list(_FIXED_REASON_CODES[status])
    response["limitations"] = list(_FIXED_LIMITATIONS[status])
    return response


def _load_selected(
    path: Path,
    row: dict[str, Any],
) -> dict[str, Any]:
    """加载每日权威快照；缺记录或非法 envelope 一律失败关闭。"""
    envelope = store.load_daily_facts(
        row["trade_date"],
        row["session"],
        db_path=path,
    )
    if envelope is None or not _valid_stored_envelope(envelope):
        raise store.FactStoreError(
            "selected snapshot missing or invalid; query suppressed"
        )
    return envelope
