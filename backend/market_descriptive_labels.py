"""Market descriptive label 单一权威（P0-MO1-R1 提取）。

把 ``market.py`` 中既有的确定性描述 label 阈值规则提取为跨模块共享的单一
authority——``market.py``（sentiment / overview）与
``market_overview_runtime.py``（P0-MO1）共同 import，**只存在一套阈值**。

规则（与提取前逐字一致，含边界语义）：

- ``breadth_label``：``r<0.25 冰点 · r<0.40 偏弱 · r<=0.60 中性 · r<=0.75 偏强 ·
  else 普涨``（中性/偏强含上界）。
- ``speculation_label``：``z>=100 亢奋 · z>=60 活跃 · z>=30 普通 · else 冰点``。

纯函数、零依赖、零 I/O；None / NaN / 非数值 → None（与提取前行为一致）。
"""

from __future__ import annotations

from typing import Any


def breadth_label(up_ratio: Any) -> str | None:
    """大盘宽度标签（按上涨占比机械分档）。"""
    if up_ratio is None:
        return None
    if not isinstance(up_ratio, (int, float)) or isinstance(up_ratio, bool):
        return None
    if up_ratio != up_ratio:  # NaN
        return None
    r = float(up_ratio)
    if r < 0.25:
        return "冰点"
    if r < 0.40:
        return "偏弱"
    if r <= 0.60:
        return "中性"
    if r <= 0.75:
        return "偏强"
    return "普涨"


def speculation_label(zt_count: Any) -> str | None:
    """题材投机标签（按涨停家数机械分档）。"""
    if zt_count is None:
        return None
    if not isinstance(zt_count, (int, float)) or isinstance(zt_count, bool):
        return None
    z = int(zt_count)
    if z >= 100:
        return "亢奋"
    if z >= 60:
        return "活跃"
    if z >= 30:
        return "普通"
    return "冰点"


__all__ = ["breadth_label", "speculation_label"]
