"""Campaign 领域服务层 v0.1（P0-S2A：Campaign Core Identity & Strategy Boundary）。

职责：
- 服务端生成稳定唯一 ``campaign_id``（``campaign_{uuid4hex}``，匹配仓库前缀约定）；
- 校验 security_code（复用 ``alert_rules.CODE_PATTERN``，6 位 A 股代码）与 strategy；
- create 一律落库为 ``DRAFT``（客户端不得伪造成 ACTIVE/CLOSED 等）；
- 只提供 create / get / list，**不存在任何 update / delete 路径** ——
  Strategy 结构性不可变由接口与领域层共同保证，不依赖调用方自觉。

同一 security_code 允许多个 Campaign（身份由 campaign_id 决定，
与 security_code 无关；无 UNIQUE(security_code) / UNIQUE(security_code, strategy)）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from alert_rules import CODE_PATTERN

import campaign_store
from campaign_store import STATUSES, STRATEGIES, CampaignAlreadyExistsError
from campaign_store import _THESIS_ID_RE
from campaign_store import CampaignNotFoundError as StoreCampaignNotFoundError
from campaign_store import CampaignStoreCorruptedError, CampaignStoreError
from campaign_store import CampaignStoreInputError
from campaign_store import CampaignThesisBindingConflictError as StoreCampaignThesisBindingConflictError
from campaign_store import CampaignTransitionConflictError as StoreCampaignTransitionConflictError

import evidence_thesis_service  # READ ONLY：只调用 canonical read API，绝不写 thesis

DRAFT_STATUS = "DRAFT"


class CampaignServiceError(RuntimeError):
    """Campaign 服务错误基类（API 层统一映射为稳定 HTTP 状态）。"""


class CampaignInputError(CampaignServiceError, ValueError):
    """入参不满足领域契约。"""


class CampaignNotFoundError(CampaignServiceError, LookupError):
    """目标 Campaign 不存在。"""


class ThesisNotFoundError(CampaignServiceError, LookupError):
    """目标 Existing Thesis 不存在。"""


class ThesisBindingNotFoundError(CampaignServiceError, LookupError):
    """Campaign 尚无 thesis binding。"""


class CampaignConflictError(CampaignServiceError):
    """campaign_id / transition_id 冲突或状态冲突（防御性或 CAS 失败）。"""


class CampaignTransitionConflictError(CampaignServiceError):
    """expected_status 不符或 transition graph 不允许（→ 409）。"""


class CampaignThesisBindingConflictError(CampaignServiceError):
    """绑定冲突：已绑定 / thesis 已被其他 Campaign 绑定 / subject 不匹配（→ 409）。"""


class CampaignThesisArchivedError(CampaignThesisBindingConflictError):
    """Thesis 已归档，不可绑定（→ 409，detail 说明 archived thesis 不可绑定）。"""


class CampaignThesisFormalIncompleteError(CampaignThesisBindingConflictError):
    """Thesis 未完成 Formal 化（formal_state NULL/draft/confirmed 或缺失），
    不可正式绑定（→ 409 NEEDS_USER_COMPLETION）。"""


class CampaignThesisStrategyConflictError(CampaignThesisBindingConflictError):
    """Thesis strategy 与 Campaign strategy 不一致（→ 409 semantic conflict）。"""

    def __init__(self, thesis_strategy: Any, campaign_strategy: Any) -> None:
        self.thesis_strategy = thesis_strategy
        self.campaign_strategy = campaign_strategy
        super().__init__(
            f"thesis strategy {thesis_strategy} != campaign strategy {campaign_strategy}"
        )


def _is_valid_security_code(value: Any) -> bool:
    return isinstance(value, str) and CODE_PATTERN.fullmatch(value.strip()) is not None


def create_campaign(security_code: str, strategy: str) -> dict:
    """创建 Campaign（状态恒为 DRAFT），返回持久化记录。

    - security_code 非 6 位 A 股代码 / strategy 非 SHORT|SWING|MEDIUM → InputError；
    - lowercase / typo strategy 不做 silent normalization（仓库无统一 normalize 契约）。
    """
    if not _is_valid_security_code(security_code):
        raise CampaignInputError("security_code must be a 6-digit A-share code")
    if strategy not in STRATEGIES:
        raise CampaignInputError(
            "strategy must be exactly one of SHORT/SWING/MEDIUM (no normalization)"
        )
    campaign_id = f"campaign_{uuid.uuid4().hex}"
    created_at = campaign_store._format_timestamp(datetime.now(timezone.utc))
    try:
        return campaign_store.create_campaign(
            campaign_id=campaign_id,
            security_code=security_code.strip(),
            strategy=strategy,
            status=DRAFT_STATUS,
            created_at=created_at,
        )
    except CampaignAlreadyExistsError as exc:
        raise CampaignConflictError("campaign_id collision (defensive)") from exc
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc


def get_campaign(campaign_id: str) -> dict:
    """按 campaign_id 精确读取；不存在 → CampaignNotFoundError。"""
    try:
        record = campaign_store.get_campaign(campaign_id)
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    if record is None:
        raise CampaignNotFoundError(f"campaign {campaign_id} not found")
    return record


def list_campaigns(
    *,
    security_code: str | None = None,
    strategy: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """确定性查询（created_at ASC, campaign_id ASC）。

    过滤值非法 → CampaignInputError。
    """
    if security_code is not None and not _is_valid_security_code(security_code):
        raise CampaignInputError("security_code must be a 6-digit A-share code")
    if strategy is not None and strategy not in STRATEGIES:
        raise CampaignInputError("strategy must be one of SHORT/SWING/MEDIUM")
    if status is not None and status not in STATUSES:
        raise CampaignInputError("status must be one of the frozen enum")
    try:
        return campaign_store.list_campaigns(
            security_code=security_code,
            strategy=strategy,
            status=status,
        )
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc


def transition_campaign(
    campaign_id: str,
    expected_status: str,
    to_status: str,
) -> tuple[dict, dict]:
    """原子迁移 Campaign 状态（CAS：expected_status + 冻结 graph）。

    返回 (迁移后 Campaign, transition 记录)；失败按契约抛：
    - 入参非法 → CampaignInputError（422）
    - Campaign 不存在 → CampaignNotFoundError（404）
    - expected_status 不符 / graph 不允许 / transition_id 冲突 → CampaignTransitionConflictError（409）
    """
    if expected_status not in STATUSES or to_status not in STATUSES:
        raise CampaignInputError("expected_status/to_status must be frozen enum values")
    transition_id = f"campaign_transition_{uuid.uuid4().hex}"
    transitioned_at = campaign_store._format_timestamp(datetime.now(timezone.utc))
    try:
        return campaign_store.transition_campaign(
            campaign_id=campaign_id,
            expected_status=expected_status,
            to_status=to_status,
            transition_id=transition_id,
            transitioned_at=transitioned_at,
        )
    except StoreCampaignNotFoundError as exc:
        raise CampaignNotFoundError(str(exc)) from exc
    except StoreCampaignTransitionConflictError as exc:
        raise CampaignTransitionConflictError(str(exc)) from exc
    except CampaignAlreadyExistsError as exc:
        raise CampaignTransitionConflictError(str(exc)) from exc
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc


def list_campaign_transitions(campaign_id: str) -> list[dict]:
    """Campaign 的 transition 历史（transitioned_at ASC, transition_id ASC）。

    ID 格式非法 → CampaignInputError；Campaign 无历史 → 空列表。
    """
    try:
        return campaign_store.list_campaign_transitions(campaign_id)
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc


def next_campaign_actions(campaign_id: str) -> tuple[dict, list[str]]:
    """返回 (Campaign, 下一合法动作列表)。

    下一合法动作派生自 frozen graph（本域唯一权威），只读、零写入；
    terminal 状态 → 空列表。Campaign 不存在 → CampaignNotFoundError。
    """
    campaign = get_campaign(campaign_id)
    try:
        actions = list(campaign_store.next_actions(campaign["status"]))
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    return campaign, actions


def _read_existing_thesis(thesis_id: str) -> dict:
    """通过 Evidence Thesis canonical read API 只读获取 thesis aggregate。

    - 不存在 → ThesisNotFoundError
    - thesis 读取异常 → CampaignServiceError（500，脱敏）
    绝不调用任何 thesis 写 API。

    canonical aggregate 形状为 ``{"thesis": {...}, "evidence_links": [...]}``
    （非 archived 实时组装 / archived snapshot），这里归一化为扁平 thesis dict
    （含 formal_state / strategy / frozen_revision 等 formal 字段）；
    若读取结果本身已是扁平 dict（既有 fake provider / 兼容形状）则原样使用。
    """
    try:
        db_path = evidence_thesis_service.resolve_db_path()
        thesis = evidence_thesis_service.get_thesis(db_path, thesis_id)
    except Exception as exc:  # noqa: BLE001 — 外部域读取失败，统一 500
        raise CampaignServiceError("Campaign 存储不可用") from exc
    if thesis is None:
        raise ThesisNotFoundError(f"thesis {thesis_id} not found")
    if isinstance(thesis, dict) and isinstance(thesis.get("thesis"), dict):
        thesis = thesis["thesis"]
    return thesis


def bind_campaign_thesis(campaign_id: str, thesis_id: str) -> dict:
    """建立 Campaign ↔ Existing Thesis 的不可变绑定。

    校验链（全部显式，无模糊匹配/AI 推断）：
    1. Campaign 存在（store）；
    2. Thesis 存在（evidence canonical read API）；
    3. thesis.subject_type == "stock"；
    4. thesis.subject_id == campaign.security_code（完全一致）；
    5. thesis.current_revision 为 strict positive integer → 永久锚定；
    6. Thesis 未 archived（已归档不可绑定 → 409 CampaignThesisArchivedError）；
    7. Thesis formal_state == "frozen"（NULL/draft/confirmed/缺失 → 409
       CampaignThesisFormalIncompleteError，NEEDS_USER_COMPLETION；
       LEGACY thesis 的 strategy 缺失同样归入该 gate）；
    8. thesis.strategy == campaign.strategy（不一致 → 409
       CampaignThesisStrategyConflictError，semantic conflict）；
    9. 快照 campaign.strategy → campaign_strategy_at_bind；
    10. store 原子 INSERT（Campaign 已绑定 / thesis 已被绑定 → Conflict）。

    Binding 一旦成功不可修改/替换/删除（本域不提供任何 update/delete 路径）。

    推荐流程 Freeze → Bind：未冻结（含 pre-freeze grandfather 场景）一律拒绝
    正式绑定；已有 grandfather binding 不受影响（由 Current Thesis Projection
    输出 NOT_READY/NOT_FROZEN）。
    """
    if not isinstance(thesis_id, str) or not _THESIS_ID_RE.fullmatch(thesis_id.strip()):
        raise CampaignInputError("thesis_id must be a 32-hex evidence thesis id")
    tid = thesis_id.strip()

    try:
        campaign = campaign_store.get_campaign(campaign_id)
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    if campaign is None:
        raise CampaignNotFoundError(f"campaign {campaign_id} not found")

    thesis = _read_existing_thesis(tid)

    subject_type = thesis.get("subject_type")
    subject_id = thesis.get("subject_id")
    if subject_type != "stock":
        raise CampaignThesisBindingConflictError(
            "thesis subject_type must be 'stock'"
        )
    if not isinstance(subject_id, str) or subject_id.strip() != campaign["security_code"]:
        raise CampaignThesisBindingConflictError(
            "thesis subject_id must exactly match campaign.security_code"
        )

    revision = thesis.get("current_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
        raise CampaignThesisBindingConflictError(
            "thesis current_revision must be a positive integer"
        )

    # P0-PH2 S2D-E：Formal Alignment gates（409 语义冲突，绝不降级为 422）
    if thesis.get("status") == "archived":
        raise CampaignThesisArchivedError(
            "archived thesis cannot be bound to a campaign"
        )
    if thesis.get("formal_state") != "frozen":
        raise CampaignThesisFormalIncompleteError(
            "thesis formal_state must be 'frozen' before binding "
            "(NEEDS_USER_COMPLETION)"
        )
    thesis_strategy = thesis.get("strategy")
    if thesis_strategy is None:
        # LEGACY 或 formal 字段不完整的 thesis：strategy 缺失归入 NEEDS_USER_COMPLETION
        raise CampaignThesisFormalIncompleteError(
            "thesis strategy missing (NEEDS_USER_COMPLETION)"
        )
    if thesis_strategy != campaign["strategy"]:
        raise CampaignThesisStrategyConflictError(
            thesis_strategy, campaign["strategy"]
        )

    try:
        return campaign_store.bind_campaign_thesis(
            campaign_id=campaign["campaign_id"],
            thesis_id=tid,
            thesis_revision_at_bind=revision,
            campaign_strategy_at_bind=campaign["strategy"],
            bound_at=campaign_store._format_timestamp(datetime.now(timezone.utc)),
        )
    except StoreCampaignNotFoundError as exc:
        raise CampaignNotFoundError(str(exc)) from exc
    except StoreCampaignThesisBindingConflictError as exc:
        raise CampaignThesisBindingConflictError(str(exc)) from exc
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc


def get_campaign_thesis_binding(campaign_id: str) -> dict:
    """读取 Campaign 的 thesis binding；未绑定 → ThesisBindingNotFoundError。"""
    try:
        binding = campaign_store.get_campaign_thesis_binding(campaign_id)
    except CampaignStoreCorruptedError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    except CampaignStoreInputError as exc:
        raise CampaignInputError(str(exc)) from exc
    except CampaignStoreError as exc:
        raise CampaignServiceError("Campaign 存储不可用") from exc
    if binding is None:
        raise ThesisBindingNotFoundError(f"campaign {campaign_id} has no thesis binding")
    return binding
