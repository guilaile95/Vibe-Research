"""正式投资决策冻结服务层（P0-FD1）。

流程：显式调用方输入 → 严格验证 → canonical 快照 → 用户确认门 →
确定性快照哈希 → append-only SQLite 冻结 → 读 / 列 / 查。

无 AI 调用、无外部网络、无交易执行、无自动变更、不修改任何既有账本。

正式决策的三层视图（asset_view / trade_view / portfolio_view）独立原样保存，
不压缩为单一 BUY/SELL 字段；Next Best Action 严格枚举冻结；条件契约只保存不
评估；有效期契约（review_by）由调用方显式提供，服务不推断 TTL。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import frozen_decision_store as store

# 新冻结 payload 必填键（身份、提交时刻、哈希与有效期状态由服务生成/注入）
_REQUIRED_KEYS = frozenset(
    {
        "security_code",
        "strategy",
        "campaign_id",
        "thesis_id",
        "thesis_revision",
        "asset_view",
        "trade_view",
        "portfolio_view",
        "next_best_action",
        "action_envelope",
        "maintain_conditions",
        "upgrade_conditions",
        "downgrade_conditions",
        "invalidation_conditions",
        "strategy_horizon",
        "review_by",
        "key_assumptions",
        "event_invalidation_conditions",
        "risk_policy_version",
        "opportunity_policy_version",
        "decision_policy_version",
        "behavior_model_version",
        "user_confirmed",
    }
)

# 新冻结 payload 可选键（提供时原样冻结，缺省时使用确定性的空表示）
_OPTIONAL_KEYS = frozenset(
    {
        "data_quality",
        "evidence_confidence",
        "inference_confidence",
        "decision_confidence",
        "evidence_refs",
        "risk_refs",
        "source_refs",
    }
)

_INPUT_KEYS = _REQUIRED_KEYS | _OPTIONAL_KEYS

# 服务生成的字段，新冻结 payload 一律禁止携带
_SERVICE_FIELDS = frozenset(
    {
        "decision_id",
        "committed_at",
        "snapshot_schema_version",
        "snapshot_hash",
        "validity_status_at_commit",
    }
)

# 精确重放（完整冻结对象）额外允许的键
_REPLAY_EXTRA_KEYS = frozenset(
    {
        "decision_id",
        "committed_at",
        "snapshot_schema_version",
        "snapshot_hash",
        "validity_status_at_commit",
        "created_at",
        "snapshot_json",
    }
)
_REPLAY_KEYS = _INPUT_KEYS | _REPLAY_EXTRA_KEYS

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SNAPSHOT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class FrozenDecisionValidationError(ValueError):
    """输入校验失败：该 payload 不被接受为正式冻结内容。"""


class FrozenDecisionReplayNotFoundError(FrozenDecisionValidationError):
    """重放目标 decision_id 不存在。

    重放仅允许已提交的正式决策；调用方不能通过重放路径凭空创建记录
    （decision_id / committed_at / created_at 由服务在真实提交时生成）。
    """


def _validation_error(field: str, reason: str) -> FrozenDecisionValidationError:
    return FrozenDecisionValidationError(f"{field}：{reason}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _normalize_utc_timestamp(value: Any, field: str) -> str:
    """校验并规范化为 canonical UTC 时间戳（ISO 8601 微秒 + Z）。

    缺失/不可解析/非 UTC 时区一律拒绝；不推断、不兜底。
    """
    if not isinstance(value, str) or not value.strip():
        raise _validation_error(field, "必须是规范 UTC 时间戳")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _validation_error(field, "无法解析的时间戳") from None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise _validation_error(field, "必须是 UTC 时区时间戳（不允许本地时区偏移）")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _validation_error(field, "必须是规范非空字符串")
    return value


def _validate_json_object(value: Any, field: str) -> dict[str, Any]:
    """必须是 JSON 对象；拒绝 NaN / Infinity / 非 JSON 结构；不丢任何嵌套值。"""
    if not isinstance(value, dict):
        raise _validation_error(field, "必须是 JSON 对象")
    try:
        store.canonical_json(value)
    except (ValueError, TypeError) as exc:
        raise _validation_error(field, f"不是合法 canonical JSON：{exc}") from exc
    return value


def _validate_json_list(value: Any, field: str, item_str: bool = False) -> list[Any]:
    if not isinstance(value, list):
        raise _validation_error(field, "必须是 JSON 数组")
    if item_str and not all(isinstance(item, str) for item in value):
        raise _validation_error(field, "数组元素必须是字符串")
    try:
        store.canonical_json(value)
    except (ValueError, TypeError) as exc:
        raise _validation_error(field, f"不是合法 canonical JSON：{exc}") from exc
    return value


def _validate_strategy(value: Any) -> str:
    if not isinstance(value, str) or value not in store.STRATEGIES:
        raise _validation_error(
            "strategy", f"必须是 {', '.join(store.STRATEGIES)} 之一（不做大小写/别名归一化）"
        )
    return value


def _validate_next_best_action(value: Any) -> str:
    if not isinstance(value, str) or value not in store.NEXT_BEST_ACTIONS:
        raise _validation_error(
            "next_best_action",
            f"必须是 {', '.join(store.NEXT_BEST_ACTIONS)} 之一（不做别名归一化）",
        )
    return value


def _validate_security_code(value: Any) -> str:
    if not isinstance(value, str) or not _SECURITY_CODE_RE.fullmatch(value):
        raise _validation_error("security_code", "必须是严格 6 位 A 股数字代码")
    return value


def _validate_campaign_id(value: Any) -> str:
    if not isinstance(value, str) or not _CAMPAIGN_ID_RE.fullmatch(value):
        raise _validation_error("campaign_id", "必须是 campaign_ + 32 位小写 hex")
    return value


def _validate_thesis_id(value: Any) -> str:
    if not isinstance(value, str) or not _THESIS_ID_RE.fullmatch(value):
        raise _validation_error(
            "thesis_id", "必须是 32 位小写 hex（与 evidence_thesis_store.new_id 格式一致）"
        )
    return value


def _validate_thesis_revision(value: Any) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise _validation_error("thesis_revision", "必须是严格正整数")
    return value


def _validate_user_confirmed(value: Any) -> None:
    # 严格 bool 身份：False / None / 缺失 / "true" / 1 一律拒绝
    if value is not True:
        raise _validation_error("user_confirmed", "必须是严格 True（用户显式确认）")


def _validate_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    """新冻结输入全字段校验，返回规范化后的字段字典。"""
    keys = set(payload)
    unexpected = keys - _INPUT_KEYS
    if unexpected:
        raise _validation_error(
            ", ".join(sorted(unexpected)), "新冻结不允许的未知字段"
        )
    missing = _REQUIRED_KEYS - keys
    if missing:
        raise _validation_error(
            ", ".join(sorted(missing)), "缺少必填字段"
        )
    service_fields = keys & _SERVICE_FIELDS
    if service_fields:
        raise _validation_error(
            ", ".join(sorted(service_fields)), "由服务生成/注入，不得由调用方提供"
        )

    _validate_user_confirmed(payload["user_confirmed"])

    cleaned: dict[str, Any] = {}
    cleaned["security_code"] = _validate_security_code(payload["security_code"])
    cleaned["strategy"] = _validate_strategy(payload["strategy"])
    cleaned["campaign_id"] = _validate_campaign_id(payload["campaign_id"])
    cleaned["thesis_id"] = _validate_thesis_id(payload["thesis_id"])
    cleaned["thesis_revision"] = _validate_thesis_revision(payload["thesis_revision"])
    cleaned["asset_view"] = _validate_json_object(payload["asset_view"], "asset_view")
    cleaned["trade_view"] = _validate_json_object(payload["trade_view"], "trade_view")
    cleaned["portfolio_view"] = _validate_json_object(
        payload["portfolio_view"], "portfolio_view"
    )
    cleaned["next_best_action"] = _validate_next_best_action(
        payload["next_best_action"]
    )
    cleaned["action_envelope"] = _validate_json_object(
        payload["action_envelope"], "action_envelope"
    )
    for cond_key in (
        "maintain_conditions",
        "upgrade_conditions",
        "downgrade_conditions",
        "invalidation_conditions",
    ):
        cleaned[cond_key] = _validate_json_list(payload[cond_key], cond_key)

    horizon = payload["strategy_horizon"]
    if not isinstance(horizon, (str, dict)) or (
        isinstance(horizon, str) and not horizon.strip()
    ):
        raise _validation_error(
            "strategy_horizon", "必须是非空字符串或 JSON 对象"
        )
    try:
        store.canonical_json(horizon)
    except (ValueError, TypeError) as exc:
        raise _validation_error(
            "strategy_horizon", f"不是合法 canonical JSON：{exc}"
        ) from exc
    cleaned["strategy_horizon"] = horizon

    cleaned["review_by"] = _normalize_utc_timestamp(payload["review_by"], "review_by")
    cleaned["key_assumptions"] = _validate_json_list(
        payload["key_assumptions"], "key_assumptions"
    )
    cleaned["event_invalidation_conditions"] = _validate_json_list(
        payload["event_invalidation_conditions"], "event_invalidation_conditions"
    )
    for policy_key in (
        "risk_policy_version",
        "opportunity_policy_version",
        "decision_policy_version",
        "behavior_model_version",
    ):
        cleaned[policy_key] = _validate_nonempty_str(payload[policy_key], policy_key)

    for confidence_key in (
        "data_quality",
        "evidence_confidence",
        "inference_confidence",
        "decision_confidence",
    ):
        value = payload.get(confidence_key)
        try:
            store.canonical_json(value)
        except (ValueError, TypeError) as exc:
            raise _validation_error(
                confidence_key, f"不是合法 canonical JSON：{exc}"
            ) from exc
        cleaned[confidence_key] = value

    for refs_key in ("evidence_refs", "risk_refs", "source_refs"):
        cleaned[refs_key] = _validate_json_list(
            payload.get(refs_key, []), refs_key, item_str=True
        )

    return cleaned


def _build_snapshot(cleaned: Mapping[str, Any], decision_id: str, committed_at: str) -> dict[str, Any]:
    """构造确定性哈希覆盖的 protected snapshot 对象。"""
    return {
        "snapshot_schema_version": store.SCHEMA_VERSION,
        "decision_id": decision_id,
        "committed_at": committed_at,
        "validity_status_at_commit": store.VALIDITY_STATUS_AT_COMMIT,
        **{key: cleaned[key] for key in _INPUT_KEYS if key != "user_confirmed"},
    }


def freeze_decision(
    payload: Mapping[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """显式冻结一条正式决策（用户确认门之后）。

    - payload 不含 ``decision_id``：服务生成身份与唯一提交时刻；提交时刻
      不接受调用方注入。
    - payload 含 ``decision_id``：精确重放（幂等成功，或冲突 fail closed）。

    ``pre_write_validator`` 是服务内部使用的窄范围校验钩子；它接收本服务
    生成的同一 commit instant，成功后才允许 snapshot 写入。公共调用方不能
    传入该钩子或 committed_at。

    返回完整冻结对象（含 decision_id / snapshot_hash / committed_at）。
    """
    return _freeze_decision(payload, db_path)


def _freeze_decision(
    payload: Mapping[str, Any],
    db_path: str | Path | None = None,
    *,
    pre_write_validator: Callable[[Mapping[str, Any], str], None] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise FrozenDecisionValidationError("payload 必须是 JSON 对象")

    if "decision_id" in payload:
        return _replay_frozen(payload, db_path)

    cleaned = _validate_input(payload)
    decision_id = f"decision_{uuid.uuid4().hex}"
    commit_instant = _utc_now_iso()
    if pre_write_validator is not None:
        pre_write_validator(cleaned, commit_instant)
    snapshot = _build_snapshot(cleaned, decision_id, commit_instant)
    snapshot_json = store.canonical_json(snapshot)
    digest = store.snapshot_hash(snapshot)
    frozen = {
        **snapshot,
        "snapshot_json": snapshot_json,
        "snapshot_hash": digest,
        "user_confirmed": True,
        "created_at": _utc_now_iso(),
    }
    return store.write_frozen_decision(_resolve_db_path(db_path), frozen)


def _replay_frozen(
    payload: Mapping[str, Any], db_path: str | Path | None
) -> dict[str, Any]:
    """精确重放：仅允许已提交的 decision_id。

    流程：
    1. 字段 / canonical 文本 / 哈希校验（防篡改）
    2. 用正常 fail-closed 读路径确认目标已提交；不存在 → ReplayNotFound，
       绝不调用 append INSERT
    3. 已提交且内容逐字一致 → 幂等返回；不一致 → 冲突 fail closed
    """
    keys = set(payload)
    unexpected = keys - _REPLAY_KEYS
    if unexpected:
        raise _validation_error(
            ", ".join(sorted(unexpected)), "重放不允许的未知字段"
        )
    missing = _REPLAY_KEYS - keys
    if missing:
        raise _validation_error(", ".join(sorted(missing)), "重放缺少字段")

    _validate_user_confirmed(payload["user_confirmed"])

    if not isinstance(payload["decision_id"], str) or not re.fullmatch(
        r"^decision_[0-9a-f]{32}$", payload["decision_id"]
    ):
        raise _validation_error("decision_id", "格式不合法")
    if not isinstance(payload["snapshot_hash"], str) or not _SNAPSHOT_HASH_RE.fullmatch(
        payload["snapshot_hash"]
    ):
        raise _validation_error("snapshot_hash", "格式不合法")
    if payload["snapshot_schema_version"] != store.SCHEMA_VERSION:
        raise _validation_error(
            "snapshot_schema_version", f"必须为 {store.SCHEMA_VERSION}"
        )
    if payload["validity_status_at_commit"] != store.VALIDITY_STATUS_AT_COMMIT:
        raise _validation_error(
            "validity_status_at_commit", "必须为 CURRENT（冻结快照不可变）"
        )

    # 从重放字段重建 snapshot 并核对 canonical 文本与哈希
    snapshot = {key: payload[key] for key in store.SNAPSHOT_KEYS}
    expected_text = store.canonical_json(snapshot)
    if payload["snapshot_hash"] != store.snapshot_hash(snapshot):
        raise _validation_error("snapshot_hash", "与 snapshot 内容不一致（重放被篡改）")
    if payload["snapshot_json"] != expected_text:
        raise _validation_error("snapshot_json", "不是 canonical 表示（重放被篡改）")
    if not store.is_canonical_utc_timestamp(payload["created_at"]):
        raise _validation_error("created_at", "必须是 canonical UTC 时间戳")

    # 重放目标必须已提交：正常 fail-closed 读路径确认存在性，
    # 不存在则拒绝（禁止回填身份/时间，禁止重放创建新记录）。
    path = _resolve_db_path(db_path)
    existing = store.get_frozen_decision(path, payload["decision_id"])
    if existing is None:
        raise FrozenDecisionReplayNotFoundError(
            f"decision_id {payload['decision_id']} 不存在：重放仅允许已提交的正式决策"
        )

    frozen = {
        **snapshot,
        "snapshot_json": expected_text,
        "snapshot_hash": payload["snapshot_hash"],
        "user_confirmed": True,
        "created_at": payload["created_at"],
    }
    return store.write_frozen_decision(path, frozen)


def _resolve_db_path(db_path: str | Path | None) -> Path:
    return store.resolve_frozen_decision_db_path(db_path)


def get_decision(
    decision_id: str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """读取单条冻结决策；缺失返回 None；任何校验失败 fail closed。"""
    return store.get_frozen_decision(_resolve_db_path(db_path), decision_id)


def list_decisions(
    db_path: str | Path | None = None,
    security_code: str | None = None,
    strategy: str | None = None,
    campaign_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """确定性列举（committed_at ASC，decision_id ASC），支持精确过滤。"""
    return store.list_frozen_decisions(
        _resolve_db_path(db_path),
        security_code=security_code,
        strategy=strategy,
        campaign_id=campaign_id,
        limit=limit,
        offset=offset,
    )
