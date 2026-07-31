"""顶部风险追踪适配器（影子模式）。

把顶部风险信封转换为主项目通用决策追踪记录，写入 decision_trace_store。
不新建第二套账本 / 第二个 SQLite。

Phase1 影子模式：
- 只记录审计轨迹，不参与任何加权 composite score；
- normal / partial 归档为一条 decision run；
- unavailable 明确不归档（返回 status=skipped），避免伪造空轨迹；
- 归档失败不影响顶部风险分析本身。
"""
from __future__ import annotations

import hashlib
from typing import Optional, Tuple

import decision_trace_store as store
from top_risk_schema import TopRiskEnvelope, _utc_now

TRACE_RESULT_TYPE = "top_risk_analysis"


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def make_decision_run_id(
    code: str,
    trade_date: Optional[str],
    input_fingerprint: Optional[str],
    config_hash: Optional[str],
) -> str:
    """按逻辑输入生成稳定身份，不使用每次请求的 generated_at。"""
    seed = "|".join(
        [
            TRACE_RESULT_TYPE,
            code or "",
            trade_date or "",
            input_fingerprint or "",
            config_hash or "",
        ]
    )
    return "tr_" + _short_hash(seed)


def _evidence_id(run_id: str, key: str) -> str:
    return f"{run_id}:ev:{key}"


def _explanation_id() -> str:
    return "exp"


def build_bundle(envelope: TopRiskEnvelope) -> Optional[dict]:
    """构造 save_decision_run_bundle 所需的三元组。

    unavailable → 返回 None（明确不归档规则）。
    """
    if envelope.status == "unavailable":
        return None

    generated_at = envelope.fetched_at or _utc_now()
    config_hash = getattr(envelope, "config_hash", None)
    input_fingerprint = getattr(envelope, "input_fingerprint", None)
    run_id = make_decision_run_id(
        envelope.code, envelope.trade_date, input_fingerprint, config_hash
    )

    run_record = {
        "decision_run_id": run_id,
        "trade_date": envelope.trade_date or "",
        "generated_at": generated_at,
        "result_type": TRACE_RESULT_TYPE,
        "schema_version": envelope.schema_version,
        "market_status": envelope.status,
        "source_fingerprint": input_fingerprint,
        "trace_status": "archived",
        "created_at": _utc_now(),
    }

    evidence_items: list[dict] = []
    supporting_ids: list[str] = []
    limiting_ids: list[str] = []

    for step in envelope.trace:
        if step.skipped:
            quality = "missing"
        else:
            quality = "valid"
            if step.direction == "RISK":
                supporting_ids.append(_evidence_id(run_id, step.step_id))
            else:
                limiting_ids.append(_evidence_id(run_id, step.step_id))

        value = {
            "direction": step.direction,
            "confidence": step.confidence,
            "passed": step.direction == "RISK",
            "skipped": step.skipped,
            "skipped_reason": step.skip_reason,
            "evidence": step.reasons,
            "warnings": [],
        }
        evidence_items.append(
            {
                "evidence_id": _evidence_id(run_id, step.step_id),
                "decision_run_id": run_id,
                "scope": "risk",
                "code": envelope.code,
                "evidence_key": f"top_risk.{step.step_id}",
                "value_json": value,
                "unit": None,
                "source_module": TRACE_RESULT_TYPE,
                "observed_at": generated_at,
                "quality_status": quality,
                "source_ref_json": None,
                "created_at": _utc_now(),
            }
        )

    summary_value = {
        "risk_score": envelope.risk_score,
        "confidence": envelope.confidence,
        "coverage": envelope.coverage,
        "status": envelope.status,
        "signal": envelope.signal,
        "signal_eligible": envelope.signal_eligible,
        "config_version": envelope.schema_version,
        "config_hash": config_hash,
        "input_fingerprint": input_fingerprint,
        "limitations": [l.model_dump() for l in envelope.limitations],
    }
    evidence_items.append(
        {
            "evidence_id": _evidence_id(run_id, "summary"),
            "decision_run_id": run_id,
            "scope": "risk",
            "code": envelope.code,
            "evidence_key": "top_risk.summary",
            "value_json": summary_value,
            "unit": None,
            "source_module": TRACE_RESULT_TYPE,
            "observed_at": generated_at,
            "quality_status": "valid" if envelope.status == "normal" else "partial",
            "source_ref_json": None,
            "created_at": _utc_now(),
        }
    )

    narrative = (envelope.data.narrative if envelope.data else None) or "顶部风险分析（影子模式）"
    explanation_items = [
        {
            "explanation_id": f"{run_id}:{_explanation_id()}",
            "decision_run_id": run_id,
            "code": envelope.code,
            "conclusion_type": "top_risk_signal",
            "conclusion_value": envelope.signal,
            "explanation_text": narrative,
            "supporting_evidence_ids": supporting_ids,
            "limiting_evidence_ids": limiting_ids,
            "rule_id": envelope.schema_version,
            "created_at": _utc_now(),
        }
    ]

    return {
        "run_record": run_record,
        "evidence_items": evidence_items,
        "explanation_items": explanation_items,
    }


def archive_top_risk(
    envelope: TopRiskEnvelope, db_path: Optional[str] = None
) -> Tuple[Optional[str], str]:
    """归档顶部风险信封到主项目决策追踪库。

    返回 (decision_run_id, trace_archive_status)：
    - unavailable → (None, "skipped") 明确不归档；
    - 正常/partial → ("tr_xxx", "archived")；
    - 异常 → (None, "failed")，不抛出，不影响分析 API。
    """
    try:
        bundle = build_bundle(envelope)
        if bundle is None:
            return (None, "skipped")
        store.save_decision_run_bundle(
            bundle["run_record"],
            bundle["evidence_items"],
            bundle["explanation_items"],
            db_path=db_path,
        )
        return (bundle["run_record"]["decision_run_id"], "archived")
    except Exception:
        return (None, "failed")
