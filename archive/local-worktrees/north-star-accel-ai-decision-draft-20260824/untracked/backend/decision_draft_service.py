"""Campaign-scoped AI draft orchestration for Formal Decision Review.

The generated artifact is advisory and uncommitted.  It can draft only the
three editable views plus assumptions/invalidations.  Deterministic Preview,
NBA, Action Envelope, explicit confirmation and Frozen Decision remain owned
by the existing decision-commit vertical.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, Mapping
from uuid import uuid4

import account_reality_service
import ai_result_service
import decision_commit_runtime as commit_runtime
import decision_draft_store
import portfolio_advice_service
import position_reality_service


PROMPT_VERSION = "campaign-decision-draft.prompt.v0.1"
ANALYSIS_POLICY_VERSION = "campaign-decision-draft.analysis-policy.v0.1"
SOURCE_REF_PREFIX = "decision_ai_draft:"
MODEL_REF_PREFIX = "decision_ai_model:"
PROMPT_REF = f"decision_ai_prompt:{PROMPT_VERSION}"
POLICY_REF = f"decision_ai_policy:{ANALYSIS_POLICY_VERSION}"

_STANCES = {"WAIT", "SUPPORT", "OPPOSE"}
_PAYLOAD_KEYS = {
    "asset_view",
    "trade_view",
    "portfolio_view",
    "key_assumptions",
    "event_invalidation_conditions",
    "limitations",
}

ModelRunner = Callable[[Any, list[dict[str, str]]], str]


class DecisionDraftError(RuntimeError):
    pass


class DecisionDraftUnavailableError(DecisionDraftError):
    pass


class DecisionDraftModelError(DecisionDraftError):
    pass


class DecisionDraftModelOutputError(DecisionDraftError, ValueError):
    pass


class DecisionDraftPersistError(DecisionDraftError):
    pass


def _canonical_fingerprint(value: Any) -> str:
    encoded = decision_draft_store.canonical_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_text(value: object, field: str, *, max_length: int = 4000) -> str:
    if not isinstance(value, str):
        raise DecisionDraftModelOutputError(f"{field} 必须是文本")
    text = value.strip()
    if not text or len(text) > max_length:
        raise DecisionDraftModelOutputError(f"{field} 必须是 1-{max_length} 个字符")
    return text


def _validate_view(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionDraftModelOutputError(f"{name} 必须是对象")
    expected_view = "PORTFOLIO" if name == "portfolio_view" else name.removesuffix("_view").upper()
    if name == "portfolio_view":
        if set(value) != {"view", "constraint"}:
            raise DecisionDraftModelOutputError("portfolio_view 字段不符合草案契约")
        if value.get("view") != expected_view:
            raise DecisionDraftModelOutputError("portfolio_view.view 不符合草案契约")
        return {
            "view": expected_view,
            "constraint": _require_text(value.get("constraint"), "portfolio_view.constraint"),
        }
    if set(value) != {"view", "stance", "note"}:
        raise DecisionDraftModelOutputError(f"{name} 字段不符合草案契约")
    if value.get("view") != expected_view:
        raise DecisionDraftModelOutputError(f"{name}.view 不符合草案契约")
    stance = value.get("stance")
    if stance not in _STANCES:
        raise DecisionDraftModelOutputError(f"{name}.stance 必须是 WAIT/SUPPORT/OPPOSE")
    return {
        "view": expected_view,
        "stance": stance,
        "note": _require_text(value.get("note"), f"{name}.note"),
    }


def _validate_text_list(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > 20:
        raise DecisionDraftModelOutputError(f"{field} 必须是不超过 20 项的数组")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_require_text(item, f"{field}[{index}]", max_length=1000))
    if not allow_empty and not result:
        raise DecisionDraftModelOutputError(f"{field} 不能为空")
    return result


def validate_model_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PAYLOAD_KEYS:
        raise DecisionDraftModelOutputError("模型草案顶层字段不符合契约")
    return {
        "asset_view": _validate_view(value["asset_view"], "asset_view"),
        "trade_view": _validate_view(value["trade_view"], "trade_view"),
        "portfolio_view": _validate_view(value["portfolio_view"], "portfolio_view"),
        "key_assumptions": _validate_text_list(value["key_assumptions"], "key_assumptions"),
        "event_invalidation_conditions": _validate_text_list(
            value["event_invalidation_conditions"], "event_invalidation_conditions"
        ),
        "limitations": _validate_text_list(value["limitations"], "limitations"),
    }


def current_holding_context(security_code: str) -> tuple[dict[str, Any], str]:
    try:
        portfolio = position_reality_service.read_portfolio_authority(include_metadata=True)
    except Exception as exc:  # noqa: BLE001 - fail closed at the product boundary
        raise DecisionDraftUnavailableError("Canonical Holding 当前不可读") from exc
    holdings = portfolio.get("holdings") if isinstance(portfolio, Mapping) else None
    if not isinstance(holdings, list):
        raise DecisionDraftUnavailableError("Canonical Holding 当前不可用")
    matches = [item for item in holdings if isinstance(item, Mapping) and item.get("code") == security_code]
    if len(matches) != 1:
        raise DecisionDraftUnavailableError("该 Campaign 当前没有唯一的 Canonical Holding")
    holding = copy.deepcopy(dict(matches[0]))
    try:
        fingerprint = ai_result_service.compute_portfolio_fingerprint([holding])
    except Exception as exc:  # noqa: BLE001
        raise DecisionDraftUnavailableError("Canonical Holding fingerprint 无法验证") from exc
    return holding, fingerprint


def _build_context(campaign_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ports = commit_runtime.PRODUCTION_PORTS
    as_of = commit_runtime.utc_now_iso()
    campaign = commit_runtime._read_campaign(ports, campaign_id)
    raw_thesis = commit_runtime._read_thesis_once(ports, campaign_id)
    if raw_thesis is None:
        raise DecisionDraftUnavailableError("Current Thesis 尚未就绪")
    frozen = commit_runtime._read_frozen(ports, campaign)
    critical_data = commit_runtime._read_critical_data(ports, campaign, as_of)
    authorities = commit_runtime.evaluate_authorities(
        campaign=campaign,
        as_of=as_of,
        current_thesis_projection=raw_thesis,
        frozen_decisions=frozen,
        critical_data=critical_data,
        evidence_reader=ports.evidence_reader,
    )
    current = authorities.current_thesis_projection
    if authorities.formal_thesis_evaluation != "EVALUATED" or current is None:
        raise DecisionDraftUnavailableError("Current Thesis 尚未形成可用的 Formal 评估")
    original = current.get("original")
    if not isinstance(original, Mapping):
        raise DecisionDraftUnavailableError("Current Thesis Original 当前不可用")
    thesis_id = current.get("thesis_id")
    thesis_revision = original.get("revision")
    if not isinstance(thesis_id, str) or isinstance(thesis_revision, bool) or not isinstance(thesis_revision, int):
        raise DecisionDraftUnavailableError("Current Thesis identity 当前不可验证")
    holding, holding_fingerprint = current_holding_context(str(campaign["security_code"]))
    try:
        account = account_reality_service.get_account_reality()
    except Exception as exc:  # noqa: BLE001
        raise DecisionDraftUnavailableError("Account Reality 当前不可读") from exc

    context = {
        "schema_version": "campaign-decision-draft-context.v0.1",
        "as_of": as_of,
        "campaign": copy.deepcopy(dict(campaign)),
        "holding": holding,
        "holding_fingerprint": holding_fingerprint,
        "account_reality": copy.deepcopy(account),
        "current_thesis": copy.deepcopy(dict(raw_thesis)),
        "critical_data": copy.deepcopy(dict(critical_data)),
        "hard_risk": authorities.hard_risk.to_dict(),
        "material_change": (
            authorities.material_change.to_dict() if authorities.material_change is not None else None
        ),
        "sell_engine": authorities.sell_engine.to_dict(),
        "formal_decision": copy.deepcopy(dict(authorities.formal_decision)),
    }
    identity = {
        "campaign_id": campaign["campaign_id"],
        "security_code": campaign["security_code"],
        "strategy": campaign["strategy"],
        "thesis_id": thesis_id,
        "thesis_revision": thesis_revision,
        "holding_fingerprint": holding_fingerprint,
        "context_as_of": as_of,
        "context_fingerprint": _canonical_fingerprint(context),
    }
    return context, identity


def _messages(context: Mapping[str, Any], focus: str | None) -> list[dict[str, str]]:
    focus_text = focus.strip() if isinstance(focus, str) else ""
    if len(focus_text) > 1000:
        raise DecisionDraftUnavailableError("本次关注点不能超过 1000 个字符")
    system = """你是 Vibe-Research 的 Campaign Decision Draft 助手。你只能根据给定的 server-side context 起草可编辑内容；不得创造事实，不得把 UNKNOWN 解释为正常，不得生成 Next Best Action、Action Envelope、Frozen Decision、Trade 或修改 Thesis。输出必须是一个纯 JSON 对象，不能有 Markdown 或解释文字。\n\n严格结构：\n{\"asset_view\":{\"view\":\"ASSET\",\"stance\":\"WAIT|SUPPORT|OPPOSE\",\"note\":\"...\"},\"trade_view\":{\"view\":\"TRADE\",\"stance\":\"WAIT|SUPPORT|OPPOSE\",\"note\":\"...\"},\"portfolio_view\":{\"view\":\"PORTFOLIO\",\"constraint\":\"...\"},\"key_assumptions\":[\"...\"],\"event_invalidation_conditions\":[\"...\"],\"limitations\":[\"...\"]}\n\n每个判断必须能由 context 支撑。数据缺失或冲突时保持 WAIT，并把限制写入 limitations。"""
    user = (
        "请为以下同一 Campaign / Current Thesis / Canonical Holding 上下文起草三视图。"
        + (f"\n用户本次关注点：{focus_text}" if focus_text else "")
        + "\nSERVER_CONTEXT_JSON:\n"
        + decision_draft_store.canonical_json(context)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_campaign_decision_draft(
    campaign_id: str,
    cfg: Mapping[str, Any],
    *,
    focus: str | None = None,
    model_runner: ModelRunner | None = None,
) -> dict[str, Any]:
    context, identity = _build_context(campaign_id)
    runner = model_runner or portfolio_advice_service._default_model_runner
    try:
        raw_text = runner(cfg, _messages(context, focus))
    except portfolio_advice_service.PortfolioAdviceModelError as exc:
        raise DecisionDraftModelError("AI 草案生成失败") from exc
    except Exception as exc:  # noqa: BLE001
        raise DecisionDraftModelError("AI 草案生成失败") from exc
    try:
        payload = validate_model_payload(portfolio_advice_service._parse_model_json(raw_text))
    except (portfolio_advice_service.PortfolioAdviceModelOutputError, DecisionDraftModelOutputError) as exc:
        raise DecisionDraftModelOutputError("AI 草案输出不符合严格结构") from exc

    provider = str(cfg.get("provider") or "api").strip()
    model = str(cfg.get("model") or "").strip()
    if not model:
        raise DecisionDraftUnavailableError("缺少模型配置")
    generated_at = commit_runtime.utc_now_iso()
    record = {
        "schema_version": decision_draft_store.DRAFT_SCHEMA_VERSION,
        "draft_id": f"decision_draft_{uuid4().hex}",
        **identity,
        "generated_at": generated_at,
        "model_provider": provider,
        "model_name": model,
        "prompt_version": PROMPT_VERSION,
        "analysis_policy_version": ANALYSIS_POLICY_VERSION,
        "payload": payload,
    }
    try:
        return decision_draft_store.append(record)
    except decision_draft_store.DecisionDraftStoreError as exc:
        raise DecisionDraftPersistError("AI 草案已生成但无法持久化") from exc


def provenance_refs(record: Mapping[str, Any]) -> list[str]:
    return [
        f"{SOURCE_REF_PREFIX}{record['draft_id']}",
        f"{MODEL_REF_PREFIX}{record['model_provider']}/{record['model_name']}",
        PROMPT_REF,
        POLICY_REF,
    ]


__all__ = [
    "ANALYSIS_POLICY_VERSION",
    "DecisionDraftError",
    "DecisionDraftModelError",
    "DecisionDraftModelOutputError",
    "DecisionDraftPersistError",
    "DecisionDraftUnavailableError",
    "PROMPT_VERSION",
    "SOURCE_REF_PREFIX",
    "current_holding_context",
    "generate_campaign_decision_draft",
    "provenance_refs",
    "validate_model_payload",
]
