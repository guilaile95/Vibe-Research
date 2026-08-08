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
from campaign_store import CampaignStoreCorruptedError, CampaignStoreError
from campaign_store import CampaignStoreInputError

DRAFT_STATUS = "DRAFT"


class CampaignServiceError(RuntimeError):
    """Campaign 服务错误基类（API 层统一映射为稳定 HTTP 状态）。"""


class CampaignInputError(CampaignServiceError, ValueError):
    """入参不满足领域契约。"""


class CampaignNotFoundError(CampaignServiceError, LookupError):
    """目标 Campaign 不存在。"""


class CampaignConflictError(CampaignServiceError):
    """campaign_id 冲突（不应发生于服务端生成的 ID，防御性保留）。"""


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
