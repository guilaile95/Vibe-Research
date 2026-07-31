"""顶部风险分析：数据契约（fact / step result / envelope）。

设计原则（明确区别于旧 SignalModule 体系）：
- 不复制旧 SignalModule / CATEGORY_WEIGHT / aggregator；
- 独立结构化合同：schema_version / status(normal|partial|unavailable) /
  risk_score / confidence / coverage；
- 步骤级 trace，全部可审计；
- 影子模式（Phase 1）：signal 恒为 unknown，signal_eligible 恒为 False，
  不参与任何加权 composite score、不改最终交易结论或仓位。

本模块只定义契约与纯数据结构，不含任何取数或网络逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

TopRiskStatus = Literal["normal", "partial", "unavailable"]
SignalDirection = Literal["RISK", "SAFE", "NEUTRAL"]

SCHEMA_VERSION = "top-risk-analysis-v0.1"


def _utc_now() -> str:
    """统一 UTC 时间生成函数。

    格式：2026-07-30T09:30:12.123456Z
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@dataclass
class TopRiskFact:
    """由 service 层一次性构建的标准化事实。

    evaluator 只读本对象，不取数、不改共享状态、不访问网络。
    events / sentiment_series 在 Phase 1 无可靠来源，恒为 None。
    """

    code: str
    name: Optional[str] = None
    trade_date: Optional[str] = None  # 最新交易日 YYYY-MM-DD（来自 price_history 末项）
    fetched_at: str = field(default_factory=_utc_now)
    price_history: Optional[list[float]] = None  # 收盘价，按时间升序
    volume_history: Optional[list[Optional[float]]] = None  # 成交量，与 price_history 对齐；缺失为 None
    valuation: Optional[dict] = None  # {"pe_ttm": {current, percentile, ...}, "pb": {...}}
    fund_flow: Optional[list[dict]] = None  # [{date, main_net, ...}]，按日期升序
    margin_trading: Optional[list[dict]] = None  # [{date, rzye, rzmre, ...}]，按日期升序
    events: Optional[list[dict]] = None  # Phase1：主项目无可靠来源 → None
    sentiment_series: Optional[list[dict]] = None  # Phase1：主项目无可靠来源 → None


@dataclass
class TopRiskStepResult:
    """单步骤评估结果。"""

    step_id: str
    label: str
    direction: SignalDirection
    weight: float
    step_risk: float  # 该步骤风险贡献，范围 [-0.5, 1.0]（RISK 正，SAFE 负，NEUTRAL 0）
    confidence: float  # 0-100
    skipped: bool
    skip_reason: Optional[str] = None
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class TopRiskResult:
    status: TopRiskStatus
    risk_score: Optional[int]  # 0-100
    confidence: Optional[int]  # 0-100
    coverage: dict  # {completed, total, ratio}
    steps: list[TopRiskStepResult]
    limitations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pydantic 响应契约（供 API 序列化，fail-closed）
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field  # noqa: E402


class TopRiskLimitation(BaseModel):
    field: str = ""
    reason_code: str = ""
    detail: str = ""


class TopRiskStepTrace(BaseModel):
    step_id: str
    label: str
    direction: str
    weight: float
    step_risk: float
    confidence: int
    skipped: bool
    skip_reason: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class TopRiskData(BaseModel):
    name: Optional[str] = None
    completed_steps: int = 0
    total_steps: int = 0
    risk_drivers: list[str] = Field(default_factory=list)  # 主要风险证据（标签）
    safety_signals: list[str] = Field(default_factory=list)  # 主要安全证据
    narrative: Optional[str] = None  # 一句话结论


class TopRiskEnvelope(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source: str = "Vibe-Research top-risk engine"
    source_tier: str = "reference"
    code: str
    name: Optional[str] = None
    trade_date: Optional[str] = None
    fetched_at: str
    status: TopRiskStatus
    is_stale: bool = False
    risk_score: Optional[int] = None
    confidence: Optional[int] = None
    coverage: Optional[dict] = None
    signal: str = "unknown"
    signal_eligible: bool = False
    # 追踪身份（影子模式接入主项目决策追踪层）
    config_hash: Optional[str] = None
    # 标准化必要事实的安全稳定指纹；不含请求时间、路径、异常或完整 DataFrame。
    input_fingerprint: Optional[str] = None
    decision_run_id: Optional[str] = None
    # archived=已归档 / failed=归档异常（不影响分析） / skipped=unavailable 明确不归档
    trace_archive_status: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[TopRiskLimitation] = Field(default_factory=list)
    data: Optional[TopRiskData] = None
    trace: list[TopRiskStepTrace] = Field(default_factory=list)
