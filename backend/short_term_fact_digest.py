"""BK-11 Slice 3d 日事实摘要文本纯计算层 v0.1。

接收已批准的 ``short-term-fact-summary-v0.1`` envelope，输出确定性
Markdown 摘要文本（digest_text）。服务 Daily Review 历史区块与页面
接入前的基础模块。

硬性非目标：

- 不调用 LLM / AI 叙述
- 不依赖 live 外部数据 / 存储 / 数据库
- 不进行逐股身份跨日追踪（晋级率，Blocker 2）
- 不评估 legal zero（Blocker 6）
- 不验证 consecutive lbc 来源语义
- 不输出交易建议 / 预测 / 评分
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Dict, List, Optional

__all__ = [
    "SCHEMA_VERSION",
    "build_fact_digest",
]

SCHEMA_VERSION = "short-term-fact-digest-v0.1"
SOURCE_SCHEMA_VERSION = "short-term-fact-summary-v0.1"

_REASON_ORDER: tuple[str, ...] = (
    "INPUT_CONTRACT_INVALID",
    "SUMMARY_CONTRACT_INVALID",
    "OUTPUT_SUPPRESSED",
)

_TRADE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_STATUSES = frozenset({"normal", "partial", "unavailable", "invalid"})

_SUMMARY_FIELDS = frozenset({
    "schema_version",
    "window",
    "status",
    "reason_codes",
    "warnings",
    "limitations",
    "stats",
})

_WINDOW_FIELDS = frozenset({
    "count",
    "first_trade_date",
    "last_trade_date",
})

_STAT_FIELDS = frozenset({
    "status_distribution",
    "facts",
    "ladder",
    "gap",
})


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _fmt_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if _is_strict_int(value):
        return str(value)
    if _is_finite_number(value):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return "n/a"


def _validate_summary(summary_envelope: Any) -> Optional[Dict[str, Any]]:
    if type(summary_envelope) is not dict:
        return None
    if summary_envelope.get("schema_version") != SOURCE_SCHEMA_VERSION:
        return None
    if set(summary_envelope.keys()) != _SUMMARY_FIELDS:
        return None
    status = summary_envelope.get("status")
    if type(status) is not str or status not in _ALLOWED_STATUSES:
        return None
    window = summary_envelope.get("window")
    if type(window) is not dict or set(window.keys()) != _WINDOW_FIELDS:
        return None
    if not _is_strict_int(window.get("count")) or window["count"] < 0:
        return None
    for key in ("first_trade_date", "last_trade_date"):
        value = window.get(key)
        if type(value) is not str or _TRADE_DATE_RE.match(value) is None:
            return None
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
    stats = summary_envelope.get("stats")
    if stats is not None and (
            type(stats) is not dict or set(stats.keys()) != _STAT_FIELDS):
        return None
    return {
        "status": status,
        "window": window,
        "stats": stats,
    }


def _render_stats_text(stats: Dict[str, Any]) -> str:
    distribution = stats.get("status_distribution")
    if type(distribution) is not dict:
        distribution = {}
    lines: List[str] = []
    dist = (
        f"normal {distribution.get('normal', 0)} / "
        f"partial {distribution.get('partial', 0)} / "
        f"unavailable {distribution.get('unavailable', 0)} / "
        f"invalid {distribution.get('invalid', 0)}"
    )
    lines.append(f"- 状态分布：{dist}")

    facts = stats.get("facts")
    if type(facts) is dict:
        for key in ("limit_up_count", "advance_count",
                    "failed_board_rate", "seal_rate", "up_ratio"):
            item = facts.get(key)
            if type(item) is not dict:
                continue
            lines.append(
                f"- {key}：min {_fmt_number(item.get('min'))} / "
                f"max {_fmt_number(item.get('max'))} / "
                f"avg {_fmt_number(item.get('avg'))}"
                f"（{item.get('count', 0)} 天）")

    ladder = stats.get("ladder")
    if type(ladder) is dict:
        mb = ladder.get("max_boards")
        if type(mb) is dict:
            lines.append(
                f"- 梯队最高板：max {_fmt_number(mb.get('max'))} / "
                f"avg {_fmt_number(mb.get('avg'))}"
                f"（{ladder.get('days_with_ladder', 0)} 天有梯队数据）")

    gap = stats.get("gap")
    if type(gap) is dict:
        glc = gap.get("gap_level_count")
        if type(glc) is dict:
            lines.append(
                f"- 断层层级数：avg {_fmt_number(glc.get('avg'))} / "
                f"max {_fmt_number(glc.get('max'))}；"
                f"连续梯队日 {gap.get('continuous_days', 0)} 天")
    return "\n".join(lines)


def _fixed_limitations() -> List[str]:
    return [
        "deterministic digest of a fact-summary envelope",
        "stats describe normal-status days only",
        "does not compute layered promotion rates",
        "does not validate consecutive-limit-up semantics",
        "no per-stock cross-day identity tracking",
        "no trade advice, prediction, or scoring",
    ]


def _normal_envelope(
    digest_text: str,
    status: str,
    reason_codes: List[str],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason_codes": reason_codes,
        "warnings": [],
        "limitations": _fixed_limitations(),
        "digest_text": digest_text,
    }


def _invalid_envelope(reason_code: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid",
        "reason_codes": [reason_code, "OUTPUT_SUPPRESSED"],
        "warnings": [],
        "limitations": _fixed_limitations(),
        "digest_text": "",
    }


def _evaluate(summary_envelope: Any) -> Dict[str, Any]:
    summary = _validate_summary(summary_envelope)
    if summary is None:
        return _invalid_envelope("SUMMARY_CONTRACT_INVALID")
    if summary["stats"] is None:
        return _invalid_envelope("SUMMARY_CONTRACT_INVALID")

    window = summary["window"]
    status = summary["status"]
    header = (
        f"# 短线市场事实摘要（{window['count']} 天，"
        f"{window['first_trade_date']} ~ {window['last_trade_date']}）\n\n"
        f"摘要状态：{status}"
    )
    body = _render_stats_text(summary["stats"])
    footer = (
        "\n\n> 说明：统计基于 normal 状态天；不包含晋级率、逐股跨日"
        "追踪、交易建议或预测。"
    )
    digest_text = header + "\n\n" + body + footer

    codes: List[str] = []
    if status != "normal":
        codes.append("OUTPUT_SUPPRESSED")
    return _normal_envelope(
        digest_text=digest_text,
        status=status,
        reason_codes=codes,
    )


def build_fact_digest(summary_envelope: dict) -> dict:
    """构建日事实摘要文本（Slice 3d 范围），永不抛异常。

    输入为 fact-summary envelope。纯计算，不修改输入。普通异常返回
    固定 invalid envelope（不调用任何业务 helper、不包含异常文本）；
    KeyboardInterrupt / SystemExit / GeneratorExit 自然传播。
    """
    try:
        return _evaluate(summary_envelope)
    except Exception:
        # emergency fail-closed envelope：直接构造完整固定字面量。
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "invalid",
            "reason_codes": ["INPUT_CONTRACT_INVALID", "OUTPUT_SUPPRESSED"],
            "warnings": [],
            "limitations": [
                "deterministic digest of a fact-summary envelope",
                "stats describe normal-status days only",
                "does not compute layered promotion rates",
                "does not validate consecutive-limit-up semantics",
                "no per-stock cross-day identity tracking",
                "no trade advice, prediction, or scoring",
            ],
            "digest_text": "",
        }
