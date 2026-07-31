"""顶部风险引擎：声明式配置驱动，逐步骤运行 evaluator 并聚合分数。

职责边界：
- 只消费 TopRiskFact（已标准化事实），不取数、不访问网络；
- 聚合 risk_score / confidence / coverage，并产出 status；
- enabled=false 的步骤不执行、不进入 coverage 分母，并产生能力未启用 limitation；
- enabled 步骤跳过：required=false → partial，required=true → unavailable；
- 无有效步骤 → status=unavailable，risk_score=None，signal=unknown。
"""
from __future__ import annotations

import hashlib
import json
import math
import yaml
from dataclasses import replace
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


_DISABLED_LIMITATION_DETAILS = {
    "sentiment_source_not_connected": "情绪背离分析尚未启用，不计入当前风险评分。",
    "event_source_not_connected": "事件兑现分析尚未启用，不计入当前风险评分。",
}


def _disabled_limitation(cfg: dict[str, Any], step_id: str) -> dict[str, str]:
    reason = str(cfg.get("limitation") or "capability_not_enabled")
    return {
        "field": step_id,
        "reason_code": "CAPABILITY_NOT_ENABLED",
        "detail": _DISABLED_LIMITATION_DETAILS.get(
            reason, "该分析能力当前未启用，不计入当前风险评分。"
        ),
    }


class TopRiskEngine:
    def __init__(self, steps: list[dict[str, Any]]):
        self.steps = steps or []
        for cfg in self.steps:
            step_id = str(cfg.get("id", "unknown"))
            try:
                weight = float(cfg.get("weight", 1.0))
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"step {step_id} weight must be a finite positive number"
                ) from exc
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError(
                    f"step {step_id} weight must be a finite positive number"
                )
        self.config_hash = _config_hash(self.steps)

    @classmethod
    def from_yaml(cls, path: str) -> "TopRiskEngine":
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cls(cfg.get("steps", []))

    def run(self, facts: TopRiskFact) -> TopRiskResult:
        step_results: list[TopRiskStepResult] = []
        limitations: list[dict] = []

        enabled_steps = [cfg for cfg in self.steps if cfg.get("enabled", True) is not False]
        required_failures = False

        for cfg in self.steps:
            step_id = str(cfg.get("id", "unknown"))
            label = str(cfg.get("label", step_id))
            weight = float(cfg.get("weight", 1.0))
            enabled = cfg.get("enabled", True) is not False
            required = bool(cfg.get("required", False))

            if not enabled:
                limitations.append(_disabled_limitation(cfg, step_id))
                continue

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
                        "detail": "分析步骤当前不可执行。",
                    }
                )
                required_failures = required_failures or required
                continue

            try:
                res = evaluator(facts, cfg.get("params", {}) or {})
                if not isinstance(res, TopRiskStepResult):
                    raise TypeError("evaluator must return TopRiskStepResult")
                res = replace(res, step_id=step_id, label=label, weight=weight)
            except Exception:  # noqa: BLE001 — 步骤级隔离，绝不扩散
                step_results.append(
                    TopRiskStepResult(
                        step_id=step_id,
                        label=label,
                        direction="NEUTRAL",
                        weight=weight,
                        step_risk=0.0,
                        confidence=0.0,
                        skipped=True,
                        skip_reason="分析步骤执行失败",
                    )
                )
                limitations.append(
                    {
                        "field": step_id,
                        "reason_code": "EVALUATOR_ERROR",
                        "detail": "分析步骤执行失败。",
                    }
                )
                required_failures = required_failures or required
                continue

            step_results.append(res)
            if res.skipped:
                limitations.append(
                    {
                        "field": step_id,
                        "reason_code": "REQUIRED_DATA_MISSING" if required else "OPTIONAL_DATA_MISSING",
                        "detail": "该分析步骤缺少必要输入，未纳入本次评分。",
                    }
                )
                required_failures = required_failures or required

        total = len(enabled_steps)
        completed = [s for s in step_results if not s.skipped]

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

        # enabled 步骤全部成功才是 normal；任一 enabled 步骤跳过则 partial。
        # required 步骤失败通常使整条链 unavailable，即使其它步骤有结果。
        status = "unavailable" if required_failures else (
            "normal" if len(completed) == total else "partial"
        )
        if status == "unavailable":
            risk_score = None
            confidence = None

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
