"""顶部风险引擎：声明式配置驱动，逐步骤运行 evaluator 并聚合分数。

职责边界：
- 只消费 TopRiskFact（已标准化事实），不取数、不访问网络；
- 聚合 risk_score / confidence / coverage，并产出 status；
- 任一 evaluator 抛异常 → 该步骤 skipped（不扩散、不影响其他步骤）；
- 无有效步骤 → status=unavailable，risk_score=None，signal=unknown。
"""
from __future__ import annotations

import hashlib
import json
import yaml
from typing import Any

from top_risk_schema import (
    TopRiskFact,
    TopRiskResult,
    TopRiskStepResult,
)
from top_risk_evaluators import EVALUATORS


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _config_hash(steps: list[dict[str, Any]]) -> str:
    canon = json.dumps(steps, sort_keys=True, ensure_ascii=False)
    return "cfg_" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


# Phase 1 已知缺失来源（无可靠舆情 / 事件）导致的 skipped 属预期，
# 不计入“关键事实缺失”，因此不应把结果判为 partial。
_PHASE1_EXPECTED_SKIPS = frozenset({"narrative_divergence", "catalyst_priced_in"})


class TopRiskEngine:
    def __init__(self, steps: list[dict[str, Any]]):
        self.steps = steps or []
        self.config_hash = _config_hash(self.steps)

    @classmethod
    def from_yaml(cls, path: str) -> "TopRiskEngine":
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cls(cfg.get("steps", []))

    def run(self, facts: TopRiskFact) -> TopRiskResult:
        step_results: list[TopRiskStepResult] = []
        limitations: list[dict] = []

        for cfg in self.steps:
            step_id = str(cfg.get("id", "unknown"))
            label = str(cfg.get("label", step_id))
            weight = float(cfg.get("weight", 1.0))
            evaluator = EVALUATORS.get(str(cfg.get("evaluator", "")))

            if evaluator is None:
                step_results.append(
                    TopRiskStepResult(
                        step_id=step_id,
                        label=label,
                        direction="NEUTRAL",
                        weight=weight,
                        step_risk=0.0,
                        confidence=0.0,
                        skipped=True,
                        skip_reason="evaluator 未注册",
                    )
                )
                limitations.append(
                    {
                        "field": step_id,
                        "reason_code": "EVALUATOR_MISSING",
                        "detail": f"评估器 {cfg.get('evaluator')} 未注册",
                    }
                )
                continue

            try:
                res = evaluator(facts, cfg.get("params", {}) or {})
            except Exception as exc:  # noqa: BLE001 — 步骤级隔离，绝不扩散
                step_results.append(
                    TopRiskStepResult(
                        step_id=step_id,
                        label=label,
                        direction="NEUTRAL",
                        weight=weight,
                        step_risk=0.0,
                        confidence=0.0,
                        skipped=True,
                        skip_reason=f"evaluator 异常: {type(exc).__name__}",
                    )
                )
                limitations.append(
                    {
                        "field": step_id,
                        "reason_code": "EVALUATOR_ERROR",
                        "detail": str(exc)[:200],
                    }
                )
                continue

            step_results.append(res)

        total = len(self.steps)
        completed = [s for s in step_results if not s.skipped]
        # 关键事实缺失：排除 Phase 1 已知的预期 skipped（无可靠舆情/事件来源）。
        data_skipped = [
            s for s in step_results
            if s.skipped and s.step_id not in _PHASE1_EXPECTED_SKIPS
        ]

        if not completed:
            return TopRiskResult(
                status="unavailable",
                risk_score=None,
                confidence=None,
                coverage={"completed": 0, "total": total, "ratio": 0.0},
                steps=step_results,
                limitations=limitations,
            )

        coverage_ratio = (len(completed) / total) if total else 0.0
        w_sum = sum(s.weight for s in completed) or 1.0
        # 加权风险分（step_risk ∈ [-0.5, 1.0]）→ 映射到 0-100
        weighted = sum(s.weight * s.step_risk for s in completed) / w_sum
        risk_score = int(round(_clamp(weighted, -0.5, 1.0) * 100))
        risk_score = _clamp(risk_score, 0, 100)

        # 置信度：已完成步骤的加权平均 × 覆盖因子（部分缺失适度打折）
        conf_avg = sum(s.weight * s.confidence for s in completed) / w_sum
        confidence = int(round(_clamp(conf_avg, 0, 100) * (0.6 + 0.4 * coverage_ratio)))

        # 仅当核心事实（价格/估值/融资等）缺失时才判 partial；
        # 预期的 Phase 1 来源缺口不降级。
        status = "normal" if not data_skipped else "partial"

        return TopRiskResult(
            status=status,
            risk_score=risk_score,
            confidence=confidence,
            coverage={
                "completed": len(completed),
                "total": total,
                "ratio": round(coverage_ratio, 3),
            },
            steps=step_results,
            limitations=limitations,
        )
