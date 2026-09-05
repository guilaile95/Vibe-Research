"""Native Intel RSS 新鲜度评估模块（TREND-PARITY Wave 3）。

严格遵循 Wave 3 Behavior Contract：
- 新鲜度是 Query / Display / AI Candidate Policy，绝非抓取侧破坏性丢弃（Store All Facts, Filter at Display）。
- 仅对 RSS 生效；Hotlist 等非 RSS 来源恒为 eligible（reason=NOT_RSS）。
- 若 Feed 级别 max_age_days == 0：该 Feed 禁用新鲜度过滤，恒为 eligible（reason=FEED_FRESHNESS_DISABLED）。
- 若 Feed 级别 max_age_days > 0：覆写全局 max_age_days。
- 若 Feed 级别 max_age_days is None：继承全局配置。
- 若全局 rss_freshness_enabled 为 False：不过滤（reason=FRESHNESS_DISABLED）。
- 若全局生效的 max_age_days == 0：不按文章年龄过滤（reason=FRESHNESS_DISABLED）。
- published_at 缺失、NULL 或无法解析：恒为 eligible（reason=PUBLISHED_AT_UNKNOWN），绝不得因无法证明过期而删除/隐藏。
- 文章年龄超过生效阈值：excluded（reason=EXPIRED）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

REASON_FRESH = "FRESH"
REASON_FRESHNESS_DISABLED = "FRESHNESS_DISABLED"
REASON_FEED_FRESHNESS_DISABLED = "FEED_FRESHNESS_DISABLED"
REASON_PUBLISHED_AT_UNKNOWN = "PUBLISHED_AT_UNKNOWN"
REASON_EXPIRED = "EXPIRED"
REASON_NOT_RSS = "NOT_RSS"

VALID_REASONS = (
    REASON_FRESH,
    REASON_FRESHNESS_DISABLED,
    REASON_FEED_FRESHNESS_DISABLED,
    REASON_PUBLISHED_AT_UNKNOWN,
    REASON_EXPIRED,
    REASON_NOT_RSS,
)


@dataclass(frozen=True)
class FreshnessResult:
    eligible: bool
    reason: str
    effective_max_age_days: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "effective_max_age_days": self.effective_max_age_days,
        }


def _parse_iso_or_ts(
    published_at: str | None,
    published_ts: int | float | None,
) -> datetime | None:
    """尝试从 published_ts 或 published_at 解析时间为 UTC datetime。"""
    if published_ts is not None and published_ts > 0:
        try:
            return datetime.fromtimestamp(published_ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass

    if not published_at or not str(published_at).strip():
        return None

    raw = str(published_at).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def evaluate_freshness(
    *,
    source_type: str = "rss",
    published_at: str | None = None,
    published_ts: int | float | None = None,
    source_max_age_days: int | None = None,
    global_enabled: bool = False,
    global_max_age_days: int = 1,
    now: datetime | None = None,
) -> FreshnessResult:
    """唯一新鲜度评估策略。

    返回 FreshnessResult(eligible, reason, effective_max_age_days)。
    """
    # 1. 仅对 RSS 来源生效
    if str(source_type).lower() != "rss":
        return FreshnessResult(
            eligible=True,
            reason=REASON_NOT_RSS,
            effective_max_age_days=None,
        )

    # 2. 全局开关未开启时，所有 RSS 都不做时效过滤，不论 per-feed 是 NULL / 0 / 正整数
    if not global_enabled:
        return FreshnessResult(
            eligible=True,
            reason=REASON_FRESHNESS_DISABLED,
            effective_max_age_days=None,
        )

    # 3. 只有 global_enabled = True 时，才继续解释 per-feed 配置：
    #    0 → feed freshness disabled
    if source_max_age_days == 0:
        return FreshnessResult(
            eligible=True,
            reason=REASON_FEED_FRESHNESS_DISABLED,
            effective_max_age_days=0,
        )

    #    N > 0 → override global; NULL / <=0 → inherit global
    if source_max_age_days is not None and source_max_age_days > 0:
        effective_days = int(source_max_age_days)
    else:
        effective_days = int(global_max_age_days)

    if effective_days <= 0:
        return FreshnessResult(
            eligible=True,
            reason=REASON_FRESHNESS_DISABLED,
            effective_max_age_days=0,
        )

    # 5. 解析发布时间
    dt = _parse_iso_or_ts(published_at, published_ts)
    if dt is None:
        # published_at 缺失或不可解析：绝不得因无法证明过期而丢弃
        return FreshnessResult(
            eligible=True,
            reason=REASON_PUBLISHED_AT_UNKNOWN,
            effective_max_age_days=effective_days,
        )

    # 6. 计算年龄
    current_time = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    age_seconds = (current_time - dt).total_seconds()

    # 未来时间或合理微小偏差视为新鲜
    if age_seconds <= 0:
        return FreshnessResult(
            eligible=True,
            reason=REASON_FRESH,
            effective_max_age_days=effective_days,
        )

    max_seconds = effective_days * 86400
    if age_seconds > max_seconds:
        return FreshnessResult(
            eligible=False,
            reason=REASON_EXPIRED,
            effective_max_age_days=effective_days,
        )

    return FreshnessResult(
        eligible=True,
        reason=REASON_FRESH,
        effective_max_age_days=effective_days,
    )


def evaluate_item_freshness(
    item: dict[str, Any],
    *,
    global_enabled: bool = False,
    global_max_age_days: int = 1,
    source_max_age_days: int | None = None,
    now: datetime | None = None,
) -> FreshnessResult:
    """便捷评估单个 item 字典的新鲜度。"""
    source_type = str(item.get("source_type") or "rss")
    published_at = item.get("published_at")
    published_ts = item.get("published_ts")
    feed_max_age = source_max_age_days if source_max_age_days is not None else item.get("source_max_age_days")
    if feed_max_age is None:
        feed_max_age = item.get("max_age_days")

    return evaluate_freshness(
        source_type=source_type,
        published_at=published_at,
        published_ts=published_ts,
        source_max_age_days=feed_max_age,
        global_enabled=global_enabled,
        global_max_age_days=global_max_age_days,
        now=now,
    )
