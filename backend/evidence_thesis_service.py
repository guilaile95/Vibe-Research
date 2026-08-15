"""投资逻辑与证据账本服务层。

负责：
* 输入规范化与校验
* subject 一致性校验
* 股票市场识别
* 乐观并发控制
* 聚合状态快照组装
* revision 生成
* archived 冻结
* EvidenceRecord 联动 revision
* diff 生成
* 事务编排

不 import portfolio_advice_service、portfolio_advice_policy、daily_review、chat。
"""

from __future__ import annotations

import json
import copy
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import evidence_thesis_store as store

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class EvidenceNotFoundError(LookupError):
    pass


class ThesisNotFoundError(LookupError):
    pass


class RevisionConflictError(RuntimeError):
    """expected_revision 不匹配或 archived thesis 被修改。"""

    def __init__(self, message: str, current_revision: int | None = None):
        super().__init__(message)
        self.current_revision = current_revision


class ArchivedThesisError(RuntimeError):
    """已归档的投资逻辑不可修改。"""

    def __init__(self):
        super().__init__("已归档的投资逻辑不可修改")


class FormalLifecycleConflictError(RuntimeError):
    """Formal thesis state does not permit the requested transition/mutation."""


class ContentLockedError(FormalLifecycleConflictError):
    """Confirmed/frozen formal content is immutable."""


class EvidenceLedgerCorruptedError(store.EvidenceLedgerCorruptedError):
    """Compatibility alias for callers/tests that import the service error."""


class SubjectMismatchError(ValueError):
    """证据与投资逻辑的 subject 不一致。"""

    def __init__(self):
        super().__init__("证据与投资逻辑的研究对象不一致，无法关联")


class ValidationError(ValueError):
    pass


class ThesisDeltaConflictError(RuntimeError):
    """Canonical thesis delta precondition or terminal-chain conflict."""

    pass


# ---------------------------------------------------------------------------
# 数据库路径解析
# ---------------------------------------------------------------------------

_DB_ENV = "VIBE_RESEARCH_EVIDENCE_THESIS_DB"


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """优先级：显式 db_path → VIBE_RESEARCH_EVIDENCE_THESIS_DB → VR_DATA_DIR/evidence_thesis.db → ~/.vibe-research/evidence_thesis.db。"""
    if db_path is not None:
        return Path(db_path)
    env_val = os.environ.get(_DB_ENV)
    if env_val and str(env_val).strip():
        return Path(str(env_val).strip())
    data_dir = os.environ.get("VR_DATA_DIR") or str(Path.home() / ".vibe-research")
    return Path(data_dir) / "evidence_thesis.db"


# ---------------------------------------------------------------------------
# subject 规范化
# ---------------------------------------------------------------------------

_THEME_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
_KR_SUFFIXES = (".KS", ".KQ", ".KR")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 美股 ticker：1–5 位大写字母，可选一位 class share 后缀（如 BRK.B）
_US_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

_VALID_SUBJECT_TYPES = frozenset({"stock", "sector", "theme"})
_VALID_EVIDENCE_TYPES = frozenset({"news", "announcement", "report", "research_note", "financial_filing", "other"})
_VALID_CLASSIFICATIONS = frozenset({"fact", "inference", "unknown"})
_VALID_CONFIDENCES = frozenset({"high", "medium", "low"})
_VALID_STANCES = frozenset({"support", "oppose", "neutral"})
_VALID_STATUSES = frozenset({"active", "weakened", "invalidated", "archived"})


def _validate_expected_revision(value: object) -> int:
    """服务层防御：expected_revision 必须是严格正整数（拒绝 bool / 0 / 负数）。"""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValidationError("expected_revision 必须是正整数")
    return value


def normalize_subject(subject_type: str, subject_id: str) -> tuple[str, str, str | None]:
    """规范化 (subject_type, subject_id) 并解析 market。

    返回 (normalized_type, normalized_id, market)。
    market 仅 stock 类型有值，sector/theme 为 None。
    subject_id 与 subject_type 必须成对提供。
    """
    if subject_type not in _VALID_SUBJECT_TYPES:
        raise ValidationError(f"subject_type 必须是 {sorted(_VALID_SUBJECT_TYPES)} 之一")

    if not isinstance(subject_id, str):
        raise ValidationError("subject_id 必须是字符串")
    sid = subject_id.strip()
    if not sid:
        raise ValidationError("subject_id 不能为空")

    if subject_type == "stock":
        sid, market = _normalize_stock_code(sid)
        return subject_type, sid, market
    elif subject_type == "sector":
        # sector slug：小写、字母数字短横线下划线
        sid_lower = sid.lower()
        if not _THEME_SLUG_RE.match(sid_lower):
            raise ValidationError("sector subject_id 必须是小写字母、数字、短横线或下划线")
        if len(sid_lower) > 64:
            raise ValidationError("sector subject_id 最大长度 64")
        return subject_type, sid_lower, None
    else:  # theme
        sid_lower = sid.lower()
        if not _THEME_SLUG_RE.match(sid_lower):
            raise ValidationError("theme subject_id 必须是小写字母、数字、短横线或下划线")
        if len(sid_lower) > 64:
            raise ValidationError("theme subject_id 最大长度 64")
        return subject_type, sid_lower, None


def _normalize_stock_code(raw: str) -> tuple[str, str]:
    """规范化股票代码并解析市场。返回 (normalized_code, market)。

    A股: 600519 → CN (6位数字，明确前缀规则；含 301xxx 创业板注册制、688xxx 科创板)
    港股: 00700 → HK (5位及以下数字)
    美股: AAPL / BRK.B → US (明确 ticker 正则，不得仅因含字母通过)
    韩股: 005930.KS → KR (明确 .KS/.KQ/.KR 后缀)
    """
    code = raw.strip().upper()
    if not code:
        raise ValidationError("股票代码不能为空")

    # 拒绝明显非法字符
    if any(c in code for c in ('$', '/', ' ', '\t', '\n')):
        raise ValidationError(f"股票代码包含非法字符：{raw}")

    # 长度检查
    if len(code) > 20:
        raise ValidationError(f"股票代码过长：{raw}")

    # 韩股：检查 .KS/.KQ/.KR 后缀
    for suf in _KR_SUFFIXES:
        if code.endswith(suf):
            bare = code[: -len(suf)]
            if not bare or not bare.isdigit():
                raise ValidationError(f"韩股代码后缀前必须是数字：{raw}")
            return code, "KR"

    # 检查是否包含点号但不是合法韩股后缀
    if '.' in code:
        # 如果有点号，检查是否是纯数字+未知后缀的情况
        parts = code.split('.')
        if len(parts) == 2 and parts[0].isdigit():
            # 纯数字 + 点号 + 后缀，但不是 .KS/.KQ/.KR
            raise ValidationError(f"无法识别的股票代码后缀：{raw}（支持的韩股后缀：.KS .KQ .KR）")
        # 其他情况（如 BRK.B）继续往下判断

    # 纯数字：A股（6位，明确前缀）或港股（5位及以下补零到5位）
    if code.isdigit():
        if len(code) == 6:
            # A股：明确前缀规则
            # 6xxxxx: 沪市主板 / 科创板(688)
            # 000xxx, 001xxx, 002xxx, 003xxx: 深市
            # 300xxx / 301xxx: 创业板
            first_three = code[:3]
            if code[0] == '6' or first_three in ('000', '001', '002', '003', '300', '301'):
                return code, "CN"
            else:
                raise ValidationError(f"无法识别的6位数字股票代码：{raw}（可能是韩股，需添加 .KS/.KQ 后缀）")
        elif len(code) <= 5:
            # 港股补零到 5 位
            return code.zfill(5), "HK"
        else:
            raise ValidationError(f"无法识别的股票代码：{raw}")

    # 美股：明确 ticker 正则（不得仅因「包含字母」通过）
    if _US_TICKER_RE.match(code):
        return code, "US"

    raise ValidationError(f"无法识别的股票代码：{raw}")


def _validate_iso_date(value: str | None, field: str, allow_none: bool = True) -> str | None:
    if value is None or value == "":
        if allow_none:
            return None
        raise ValidationError(f"{field} 不能为空")
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValidationError(f"{field} 必须是 ISO 8601 date (YYYY-MM-DD)")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as e:
        raise ValidationError(f"{field} 不是有效日期：{value}") from e
    return value


def _validate_iso_datetime(value: str, field: str) -> str:
    """验证 ISO 8601 datetime，必须带时区，保存时转换为 UTC。"""
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field} 不能为空")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as e:
        raise ValidationError(f"{field} 必须是 ISO 8601 datetime") from e

    # 必须带时区
    if dt.tzinfo is None:
        raise ValidationError(f"{field} 必须包含时区信息 (如 +00:00 或 Z)")

    # 转换为 UTC 并返回 ISO 格式
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.isoformat(timespec="microseconds")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ---------------------------------------------------------------------------
# 分页校验
# ---------------------------------------------------------------------------

def validate_pagination(limit: int = 50, offset: int = 0) -> tuple[int, int]:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValidationError("limit 必须是整数")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ValidationError("offset 必须是整数")
    if limit <= 0 or limit > 200:
        raise ValidationError("limit 必须在 1-200 之间")
    if offset < 0:
        raise ValidationError("offset 必须 >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# 聚合状态快照组装
# ---------------------------------------------------------------------------

_SNAPSHOT_EVIDENCE_FIELDS = (
    "evidence_id",
    "evidence_type",
    "stance",
    "claim",
    "classification",
    "confidence",
    "source_title",
    "source_url",
    "source_date",
    "accessed_at",
)


def _assemble_snapshot(conn, thesis_row) -> dict:
    """组装完整聚合状态快照。"""
    thesis_dict = store._thesis_row_to_dict(thesis_row)
    links = store._list_links_for_thesis(conn, thesis_dict["id"])
    evidence_links = []
    for link in links:
        ev_row = store._get_evidence_row(conn, link["evidence_id"])
        if ev_row is None or int(ev_row["deleted"]) == 1:
            continue  # 跳过已软删除的证据
        evidence_links.append({
            "evidence_id": ev_row["id"],
            "evidence_type": ev_row["evidence_type"],
            "stance": link["stance"],
            "claim": ev_row["claim"],
            "classification": ev_row["classification"],
            "confidence": ev_row["confidence"],
            "source_title": ev_row["source_title"],
            "source_url": ev_row["source_url"],
            "source_date": ev_row["source_date"],
            "accessed_at": ev_row["accessed_at"],
        })
    return {
        "thesis": thesis_dict,
        "evidence_links": evidence_links,
    }


def _generate_revision(conn, thesis_id: str, change_summary: str) -> int:
    """为 thesis 生成下一 revision 并更新 current_revision。返回新 revision 号。

    snapshot 中的 current_revision 必须是新版本号（与 thesis 主表一致），
    因此先更新 current_revision，再重新读取 thesis_row 组装 snapshot。
    """
    thesis_row = store._get_thesis_row(conn, thesis_id)
    if thesis_row is None:
        raise ThesisNotFoundError(f"thesis {thesis_id} 不存在")
    current_rev = int(thesis_row["current_revision"])
    new_rev = current_rev + 1
    # 先更新 current_revision，确保 snapshot 反映新版本状态
    store._update_thesis_revision(conn, thesis_id, new_rev)
    # 重新读取已更新的 thesis_row 组装 snapshot
    thesis_row = store._get_thesis_row(conn, thesis_id)
    snapshot = _assemble_snapshot(conn, thesis_row)
    conn.execute(
        """
        INSERT INTO thesis_revisions
          (id, thesis_id, revision_number, snapshot, change_summary, created_at, revision_kind)
        VALUES (?, ?, ?, ?, ?, ?, 'CONTENT')
        """,
        (store.new_id(), thesis_id, new_rev, json.dumps(snapshot, ensure_ascii=False),
         change_summary, _utc_now_iso()),
    )
    return new_rev


# ---------------------------------------------------------------------------
# EvidenceRecord 服务
# ---------------------------------------------------------------------------

def create_evidence(db_path, data: dict) -> dict:
    """创建证据记录。"""
    stype, sid, _market = normalize_subject(data.get("subject_type"), data.get("subject_id"))

    if data.get("evidence_type") not in _VALID_EVIDENCE_TYPES:
        raise ValidationError(f"evidence_type 必须是 {sorted(_VALID_EVIDENCE_TYPES)} 之一")
    if not isinstance(data.get("claim"), str) or not data["claim"].strip():
        raise ValidationError("claim 不能为空")
    if not isinstance(data.get("source_title"), str) or not data["source_title"].strip():
        raise ValidationError("source_title 不能为空")
    if data.get("classification") not in _VALID_CLASSIFICATIONS:
        raise ValidationError(f"classification 必须是 {sorted(_VALID_CLASSIFICATIONS)} 之一")
    if data.get("confidence") not in _VALID_CONFIDENCES:
        raise ValidationError(f"confidence 必须是 {sorted(_VALID_CONFIDENCES)} 之一")

    source_url = data.get("source_url")
    if source_url is not None and not isinstance(source_url, str):
        raise ValidationError("source_url 必须是字符串或 null")
    source_date = _validate_iso_date(data.get("source_date"), "source_date", allow_none=True)
    accessed_at = _validate_iso_datetime(data.get("accessed_at", ""), "accessed_at")

    now = _utc_now_iso()
    evidence_id = store.new_id()
    record = {
        "id": evidence_id,
        "subject_type": stype,
        "subject_id": sid,
        "evidence_type": data["evidence_type"],
        "claim": data["claim"].strip(),
        "source_title": data["source_title"].strip(),
        "source_url": source_url,
        "source_date": source_date,
        "accessed_at": accessed_at,
        "classification": data["classification"],
        "confidence": data["confidence"],
        "created_at": now,
        "updated_at": now,
    }

    def _do(conn):
        store._insert_evidence(conn, record)
        return record

    return store.write_transaction(db_path, _do)


def update_evidence(db_path, evidence_id: str, data: dict) -> dict:
    """更新证据记录，联动更新所有非归档关联 thesis 的 revision。"""
    if data.get("evidence_type") not in _VALID_EVIDENCE_TYPES:
        raise ValidationError(f"evidence_type 必须是 {sorted(_VALID_EVIDENCE_TYPES)} 之一")
    if not isinstance(data.get("claim"), str) or not data["claim"].strip():
        raise ValidationError("claim 不能为空")
    if not isinstance(data.get("source_title"), str) or not data["source_title"].strip():
        raise ValidationError("source_title 不能为空")
    if data.get("classification") not in _VALID_CLASSIFICATIONS:
        raise ValidationError(f"classification 必须是 {sorted(_VALID_CLASSIFICATIONS)} 之一")
    if data.get("confidence") not in _VALID_CONFIDENCES:
        raise ValidationError(f"confidence 必须是 {sorted(_VALID_CONFIDENCES)} 之一")

    source_url = data.get("source_url")
    if source_url is not None and not isinstance(source_url, str):
        raise ValidationError("source_url 必须是字符串或 null")
    source_date = _validate_iso_date(data.get("source_date"), "source_date", allow_none=True)
    accessed_at = _validate_iso_datetime(data.get("accessed_at", ""), "accessed_at")

    now = _utc_now_iso()
    update_data = {
        "evidence_type": data["evidence_type"],
        "claim": data["claim"].strip(),
        "source_title": data["source_title"].strip(),
        "source_url": source_url,
        "source_date": source_date,
        "accessed_at": accessed_at,
        "classification": data["classification"],
        "confidence": data["confidence"],
        "updated_at": now,
    }

    def _do(conn):
        existing = store._get_evidence_row(conn, evidence_id)
        if existing is None:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 不存在")
        if int(existing["deleted"]) == 1:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 已删除")

        store._update_evidence(conn, evidence_id, update_data)

        # 联动更新所有非归档关联 thesis
        thesis_ids = store._list_non_archived_thesis_ids_for_evidence(conn, evidence_id)
        change_summary = f"更新关联证据：{evidence_id}"
        for tid in thesis_ids:
            trow = store._get_thesis_row(conn, tid)
            if trow is not None and trow["formal_state"] in ("confirmed", "frozen"):
                continue
            _generate_revision(conn, tid, change_summary)

        # 返回更新后的证据
        row = store._get_evidence_row(conn, evidence_id)
        return store._evidence_row_to_dict(row)

    return store.write_transaction(db_path, _do)


def soft_delete_evidence(db_path, evidence_id: str) -> dict:
    """软删除证据，联动更新所有非归档关联 thesis 的 revision。"""
    now = _utc_now_iso()

    def _do(conn):
        existing = store._get_evidence_row(conn, evidence_id)
        if existing is None:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 不存在")
        if int(existing["deleted"]) == 1:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 已删除")

        store._soft_delete_evidence(conn, evidence_id, now)

        # 联动更新所有非归档关联 thesis
        thesis_ids = store._list_non_archived_thesis_ids_for_evidence(conn, evidence_id)
        change_summary = f"删除关联证据：{evidence_id}"
        for tid in thesis_ids:
            trow = store._get_thesis_row(conn, tid)
            if trow is not None and trow["formal_state"] in ("confirmed", "frozen"):
                continue
            _generate_revision(conn, tid, change_summary)

        row = store._get_evidence_row(conn, evidence_id)
        return store._evidence_row_to_dict(row)

    return store.write_transaction(db_path, _do)


def get_evidence(db_path, evidence_id: str) -> dict | None:
    """获取单条证据（含已删除）。"""
    def _do(conn):
        row = store._get_evidence_row(conn, evidence_id)
        if row is None:
            return None
        return store._evidence_row_to_dict(row)

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return None


def list_evidence(db_path, subject_type: str | None = None, subject_id: str | None = None,
                  limit: int = 50, offset: int = 0) -> dict:
    """列出证据（不含已删除）。返回 {items, total, limit, offset}。"""
    limit, offset = validate_pagination(limit, offset)
    # 规范化 subject 过滤
    norm_type = None
    norm_id = None
    if subject_type is not None:
        if subject_type not in _VALID_SUBJECT_TYPES:
            raise ValidationError(f"subject_type 必须是 {sorted(_VALID_SUBJECT_TYPES)} 之一")
        norm_type = subject_type
        if subject_id is not None:
            norm_type, norm_id, _ = normalize_subject(subject_type, subject_id)
        else:
            # subject_type 提供但 subject_id 未提供，拒绝
            raise ValidationError("提供 subject_type 时必须同时提供 subject_id")
    elif subject_id is not None:
        # subject_id 提供但 subject_type 未提供，拒绝
        raise ValidationError("提供 subject_id 时必须同时提供 subject_type")

    def _do(conn):
        rows = store._list_evidence_rows(conn, norm_type, norm_id, limit, offset, include_deleted=False)
        total = store._count_evidence(conn, norm_type, norm_id, include_deleted=False)
        return {
            "items": [store._evidence_row_to_dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# InvestmentThesis 服务
# ---------------------------------------------------------------------------

def _validate_thesis_fields(data: dict, is_create: bool = True) -> None:
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        raise ValidationError("title 不能为空")
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValidationError("summary 不能为空")
    for field in ("core_claims", "catalysts", "risks", "invalidation_conditions"):
        val = data.get(field)
        if not isinstance(val, list):
            raise ValidationError(f"{field} 必须是数组")
        for item in val:
            if not isinstance(item, str):
                raise ValidationError(f"{field} 中的每个元素必须是字符串")
    if not is_create:
        if data.get("status") is not None and data["status"] not in _VALID_STATUSES:
            raise ValidationError(f"status 必须是 {sorted(_VALID_STATUSES)} 之一")


def _validate_formal_fields(strategy: str | None, horizon: object) -> dict | None:
    if strategy is not None and strategy not in store.THESIS_STRATEGIES:
        raise ValidationError(f"strategy 必须是 {list(store.THESIS_STRATEGIES)} 之一")
    if horizon is None:
        return None
    if not isinstance(horizon, dict):
        raise ValidationError("expected_horizon 必须是对象")
    if horizon.get("unit") != "TRADING_DAY" or horizon.get("anchor") != "FREEZE_AT":
        raise ValidationError("expected_horizon unit/anchor 无效")
    low, high = horizon.get("min"), horizon.get("max")
    if (isinstance(low, bool) or isinstance(high, bool)
            or not isinstance(low, int) or not isinstance(high, int)
            or low < 1 or high < low):
        raise ValidationError("expected_horizon min/max 无效")
    if strategy is not None:
        lo, hi = store.STRATEGY_HORIZON_RANGES[strategy]
        if low < lo or high > hi:
            raise ValidationError(f"{strategy} 的 expected_horizon 必须在 {lo}-{hi} trading days 内")
    return {"unit": "TRADING_DAY", "min": low, "max": high, "anchor": "FREEZE_AT"}


def create_thesis(db_path, data: dict) -> dict:
    """创建投资逻辑，同事务生成 revision 1。"""
    stype, sid, market = normalize_subject(data.get("subject_type"), data.get("subject_id"))
    _validate_thesis_fields(data, is_create=True)

    now = _utc_now_iso()
    thesis_id = store.new_id()
    change_summary = (data.get("change_summary") or "创建投资逻辑").strip() or "创建投资逻辑"

    thesis_record = {
        "id": thesis_id,
        "subject_type": stype,
        "subject_id": sid,
        "market": market,
        "title": data["title"].strip(),
        "summary": data["summary"].strip(),
        "status": "active",
        "core_claims": data["core_claims"],
        "catalysts": data["catalysts"],
        "risks": data["risks"],
        "invalidation_conditions": data["invalidation_conditions"],
        "created_at": now,
        "updated_at": now,
        "current_revision": 1,
    }

    def _do(conn):
        store._insert_thesis(conn, thesis_record)
        # 生成 revision 1（snapshot 是创建后的完整聚合状态）
        thesis_row = store._get_thesis_row(conn, thesis_id)
        snapshot = _assemble_snapshot(conn, thesis_row)
        store._insert_revision(conn, {
            "id": store.new_id(),
            "thesis_id": thesis_id,
            "revision_number": 1,
            "snapshot": snapshot,
            "change_summary": change_summary,
            "created_at": now,
            "revision_kind": "CONTENT",
        })
        # 返回完整聚合状态
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


def update_thesis(db_path, thesis_id: str, data: dict, expected_revision: int) -> dict:
    """编辑投资逻辑，生成新 revision。"""
    _validate_thesis_fields(data, is_create=False)
    expected_revision = _validate_expected_revision(expected_revision)

    now = _utc_now_iso()
    change_summary = (data.get("change_summary") or "更新投资逻辑").strip() or "更新投资逻辑"

    # 不允许通过 PUT 直接设为 archived（必须用 DELETE 归档）
    status = data.get("status", "active")
    if status == "archived":
        raise ValidationError("归档请使用 DELETE /api/thesis/{id}?confirm=true")

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")

        if thesis_row["status"] == "archived":
            raise ArchivedThesisError()
        if thesis_row["formal_state"] in ("confirmed", "frozen"):
            raise ContentLockedError()

        current_rev = int(thesis_row["current_revision"])
        if expected_revision != current_rev:
            raise RevisionConflictError(
                "投资逻辑已发生变化，请重新加载后重试",
                current_revision=current_rev,
            )

        # Legacy and draft content share the stable main-row primitive.  Formal
        # fields are updated in the same transaction and never via a legacy
        # caller's implicit defaults.
        current = store._thesis_row_to_dict(thesis_row)
        update_data = {
            "title": data.get("title", current["title"]).strip(),
            "summary": data.get("summary", current["summary"]).strip(),
            "status": status,
            "core_claims": data.get("core_claims", current["core_claims"]),
            "catalysts": data.get("catalysts", current["catalysts"]),
            "risks": data.get("risks", current["risks"]),
            "invalidation_conditions": data.get("invalidation_conditions", current["invalidation_conditions"]),
            "updated_at": now,
        }
        store._update_thesis_main(conn, thesis_id, update_data)
        if thesis_row["formal_state"] == "draft":
            strategy = data.get("strategy", current["strategy"])
            horizon = data.get("expected_horizon", current["expected_horizon"])
            horizon = _validate_formal_fields(strategy, horizon)
            free_notes = data.get("free_notes", current["free_notes"])
            conn.execute(
                """UPDATE investment_theses SET strategy=?, expected_horizon=?, free_notes=? WHERE id=?""",
                (strategy, json.dumps(horizon, ensure_ascii=False) if horizon is not None else None,
                 free_notes, thesis_id),
            )
        _generate_revision(conn, thesis_id, change_summary)
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


def begin_formalization(db_path, thesis_id: str) -> dict:
    """LEGACY -> DRAFT marker, deliberately without a revision bump."""
    now = _utc_now_iso()

    def _do(conn):
        row = store._get_thesis_row(conn, thesis_id)
        if row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if row["status"] == "archived":
            raise ArchivedThesisError()
        if row["formal_state"] is not None:
            raise FormalLifecycleConflictError("只能从 legacy 投资逻辑开始 formalization")
        conn.execute(
            "UPDATE investment_theses SET formal_state='draft', formalization_started_at=?, updated_at=? WHERE id=?",
            (now, now, thesis_id),
        )
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


def confirm_formalization(db_path, thesis_id: str, expected_revision: int) -> dict:
    """DRAFT -> CONFIRMED hard-gated transition, without a revision bump.

    ``expected_revision`` protects the user's reviewed draft from being
    confirmed after another writer has changed the content.
    """
    expected_revision = _validate_expected_revision(expected_revision)
    now = _utc_now_iso()

    def _do(conn):
        row = store._get_thesis_row(conn, thesis_id)
        if row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if row["formal_state"] != "draft":
            raise FormalLifecycleConflictError("只有 draft thesis 才能 confirm")
        current = int(row["current_revision"])
        if current != expected_revision:
            raise RevisionConflictError(
                "投资逻辑已发生变化，请重新加载后重试",
                current_revision=current,
            )
        if row["status"] != "active":
            raise ValidationError("confirm 要求 status=active")
        claims = json.loads(row["core_claims"])
        if not 3 <= len(claims) <= 5:
            raise ValidationError("core_claims 数量必须在 3-5 之间")
        horizon = json.loads(row["expected_horizon"]) if row["expected_horizon"] else None
        _validate_formal_fields(row["strategy"], horizon)
        if row["strategy"] is None or horizon is None:
            raise ValidationError("confirm 要求 strategy 和 expected_horizon")
        conn.execute(
            "UPDATE investment_theses SET formal_state='confirmed', confirmed_at=?, updated_at=? WHERE id=?",
            (now, now, thesis_id),
        )
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


_FORMAL_CONTENT_KEYS = (
    "title", "summary", "core_claims", "catalysts", "risks",
    "invalidation_conditions", "free_notes", "strategy", "expected_horizon",
)
def _extract_snapshot_content(snapshot: dict) -> dict:
    """Accept historical aggregate (nested thesis) and vNext flat snapshots."""
    nested = snapshot.get("thesis")
    return nested if isinstance(nested, dict) else snapshot


def _content_matches_row(content: dict, row) -> bool:
    live = store._thesis_row_to_dict(row)
    for key in _FORMAL_CONTENT_KEYS:
        if json.dumps(content.get(key), sort_keys=True, ensure_ascii=False) != json.dumps(
            live.get(key), sort_keys=True, ensure_ascii=False
        ):
            return False
    return True


def _build_formal_snapshot(raw: dict, *, row, state: str, now: str,
                           revision: int, archived_at: str | None = None) -> dict:
    """Deep-copy the confirmed revision and add flat vNext metadata.

    Keeping the original aggregate under ``thesis`` preserves the existing API
    shape; flat fields are canonical for the persisted Formal validators.
    """
    snap = copy.deepcopy(raw)
    content = copy.deepcopy(_extract_snapshot_content(raw))
    # The flat representation is intentionally authoritative for vNext reads.
    for key in _FORMAL_CONTENT_KEYS:
        snap[key] = copy.deepcopy(content.get(key))
    if isinstance(snap.get("thesis"), dict):
        snap["thesis"].update({
            "formal_state": state,
            "formalization_started_at": row["formalization_started_at"],
            "confirmed_at": row["confirmed_at"],
            "frozen_at": now if state == "frozen" else row["frozen_at"],
            "frozen_revision": revision if state == "frozen" else row["frozen_revision"],
            "status": "archived" if archived_at else row["status"],
            "current_revision": revision,
            "updated_at": now,
            "archived_at": archived_at,
        })
    snap.update({
        "formal_state": state,
        "formalization_started_at": row["formalization_started_at"],
        "confirmed_at": row["confirmed_at"],
        "frozen_at": now if state == "frozen" else row["frozen_at"],
        "frozen_revision": revision if state == "frozen" else row["frozen_revision"],
        "status": "archived" if archived_at else row["status"],
        "current_revision": revision,
        "updated_at": now,
        "archived_at": archived_at,
    })
    return snap


def freeze_formalization(db_path, thesis_id: str, expected_revision: int) -> dict:
    """CONFIRMED -> FROZEN with strict CAS and fail-closed content drift check."""
    expected_revision = _validate_expected_revision(expected_revision)
    now = _utc_now_iso()

    def _do(conn):
        row = store._get_thesis_row(conn, thesis_id)
        if row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if row["formal_state"] != "confirmed" or row["status"] != "active":
            raise FormalLifecycleConflictError("只有 active confirmed thesis 才能 freeze")
        current = int(row["current_revision"])
        if current != expected_revision:
            raise RevisionConflictError("投资逻辑已发生变化，请重新加载后重试", current_revision=current)
        rev = store._get_revision_row(conn, thesis_id, expected_revision)
        if rev is None:
            raise store.EvidenceLedgerCorruptedError()
        try:
            raw = json.loads(rev["snapshot"])
        except (TypeError, ValueError) as exc:
            raise store.EvidenceLedgerCorruptedError() from exc
        if not isinstance(raw, dict):
            raise store.EvidenceLedgerCorruptedError()
        content = _extract_snapshot_content(raw)
        if not _content_matches_row(content, row):
            raise store.EvidenceLedgerCorruptedError()
        new_revision = expected_revision + 1
        frozen_snapshot = _build_formal_snapshot(raw, row=row, state="frozen",
                                                  now=now, revision=new_revision)
        conn.execute(
            """UPDATE investment_theses SET formal_state='frozen', frozen_at=?, frozen_revision=?,
               current_revision=?, updated_at=? WHERE id=?""",
            (now, new_revision, new_revision, now, thesis_id),
        )
        conn.execute(
            """INSERT INTO thesis_revisions
               (id, thesis_id, revision_number, snapshot, change_summary, created_at, revision_kind)
               VALUES (?, ?, ?, ?, ?, ?, 'FORMAL_FREEZE')""",
            (store.new_id(), thesis_id, new_revision, json.dumps(frozen_snapshot, ensure_ascii=False),
             "冻结 Formal Thesis", now),
        )
        return frozen_snapshot

    return store.write_transaction(db_path, _do)


def archive_formalization(db_path, thesis_id: str, expected_revision: int) -> dict:
    """FROZEN ACTIVE -> FROZEN ARCHIVED, preserving frozen content/evidence."""
    expected_revision = _validate_expected_revision(expected_revision)
    now = _utc_now_iso()

    def _do(conn):
        row = store._get_thesis_row(conn, thesis_id)
        if row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if row["formal_state"] != "frozen" or row["status"] != "active":
            raise FormalLifecycleConflictError("只有 active frozen thesis 才能 archive")
        frozen_revision = int(row["frozen_revision"])
        if expected_revision != frozen_revision or int(row["current_revision"]) != expected_revision:
            raise RevisionConflictError("投资逻辑已发生变化，请重新加载后重试",
                                        current_revision=int(row["current_revision"]))
        rev = store._get_revision_row(conn, thesis_id, frozen_revision)
        if rev is None or rev["revision_kind"] != "FORMAL_FREEZE":
            raise store.EvidenceLedgerCorruptedError()
        try:
            raw = json.loads(rev["snapshot"])
        except (TypeError, ValueError) as exc:
            raise store.EvidenceLedgerCorruptedError() from exc
        if not isinstance(raw, dict):
            raise store.EvidenceLedgerCorruptedError()
        new_revision = frozen_revision + 1
        # Archive is a lifecycle-only revision: preserve every frozen field
        # (especially frozen_at/frozen_revision and evidence snapshot) and
        # change only the explicitly permitted lifecycle markers.
        archived_snapshot = copy.deepcopy(raw)
        archived_snapshot["status"] = "archived"
        archived_snapshot["current_revision"] = new_revision
        archived_snapshot["updated_at"] = now
        archived_snapshot["archived_at"] = now
        nested_thesis = archived_snapshot.get("thesis")
        if isinstance(nested_thesis, dict):
            nested_thesis["status"] = "archived"
            nested_thesis["current_revision"] = new_revision
            nested_thesis["updated_at"] = now
            nested_thesis["archived_at"] = now
        conn.execute(
            "UPDATE investment_theses SET status='archived', current_revision=?, updated_at=?, archived_at=? WHERE id=?",
            (new_revision, now, now, thesis_id),
        )
        conn.execute(
            """INSERT INTO thesis_revisions
               (id, thesis_id, revision_number, snapshot, change_summary, created_at, revision_kind)
               VALUES (?, ?, ?, ?, ?, ?, 'FORMAL_ARCHIVE')""",
            (store.new_id(), thesis_id, new_revision, json.dumps(archived_snapshot, ensure_ascii=False),
             "归档 Formal Thesis", now),
        )
        return archived_snapshot

    return store.write_transaction(db_path, _do)


def archive_thesis(db_path, thesis_id: str, expected_revision: int, change_summary: str | None = None) -> dict:
    """归档投资逻辑，生成最终 revision。"""
    expected_revision = _validate_expected_revision(expected_revision)

    now = _utc_now_iso()
    summary = (change_summary or "归档投资逻辑").strip() or "归档投资逻辑"

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")

        # 检查是否已归档
        if thesis_row["status"] == "archived":
            raise ArchivedThesisError()
        if thesis_row["formal_state"] == "draft":
            raise FormalLifecycleConflictError(
                "draft thesis 不能通过 legacy archive；请完成 formal lifecycle"
            )
        if thesis_row["formal_state"] in ("confirmed", "frozen"):
            raise ContentLockedError()

        current_rev = int(thesis_row["current_revision"])
        if expected_revision != current_rev:
            raise RevisionConflictError(
                "投资逻辑已发生变化，请重新加载后重试",
                current_revision=current_rev,
            )

        # 更新 status 为 archived
        thesis_dict = store._thesis_row_to_dict(thesis_row)
        thesis_dict["status"] = "archived"
        thesis_dict["updated_at"] = now
        store._update_thesis_main(conn, thesis_id, thesis_dict)
        _generate_revision(conn, thesis_id, summary)
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


def get_thesis(db_path, thesis_id: str) -> dict | None:
    """获取投资逻辑当前聚合状态。

    archived thesis 以 current_revision snapshot 为权威，不重新组装。
    非 archived thesis 实时组装聚合状态（与 snapshot 等价）。
    """
    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            return None
        return _get_thesis_aggregate(conn, thesis_id)

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return None


def _validate_thesis_read(conn, thesis_row) -> None:
    """Apply the complete persisted Formal contract before any thesis read."""
    thesis_id = thesis_row["id"]
    store.validate_persisted_thesis_main(thesis_row)
    store.validate_persisted_revision_history(conn, thesis_id, thesis_row)
    store.validate_persisted_thesis_chain(conn, thesis_id, thesis_row)
    store.validate_persisted_delta_chain(conn, thesis_id)


def _get_thesis_aggregate(conn, thesis_id: str) -> dict:
    """获取 thesis 当前聚合状态。

    archived → 从 current_revision snapshot 读取（权威）。
    非 archived → 实时组装（与 snapshot 等价）。
    """
    thesis_row = store._get_thesis_row(conn, thesis_id)
    if thesis_row is None:
        raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")

    # P0-PH2 S2D-A：read path fail-closed —— 主行五态 + Formal 链 + delta 链校验
    _validate_thesis_read(conn, thesis_row)

    thesis_dict = store._thesis_row_to_dict(thesis_row)

    if thesis_dict["status"] == "archived" or thesis_dict["formal_state"] == "frozen":
        # Frozen (including archived) reads are authoritative snapshots; live
        # evidence edits must never rewrite the confirmed/frozen original.
        revision_number = thesis_dict["current_revision"]
        if thesis_dict["formal_state"] == "frozen" and thesis_dict["status"] != "archived":
            revision_number = thesis_dict["frozen_revision"]
        rev_row = store._get_revision_row(conn, thesis_id, revision_number)
        if rev_row is None:
            raise store.EvidenceLedgerCorruptedError()
        snapshot = json.loads(rev_row["snapshot"])
        return snapshot
    else:
        # 非 archived: 实时组装
        return _assemble_snapshot(conn, thesis_row)


def list_thesis(db_path, subject_type: str | None = None, subject_id: str | None = None,
                status: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """列出投资逻辑。返回 {items, total, limit, offset}。"""
    limit, offset = validate_pagination(limit, offset)
    if status is not None and status not in _VALID_STATUSES:
        raise ValidationError(f"status 必须是 {sorted(_VALID_STATUSES)} 之一")

    norm_type = None
    norm_id = None
    if subject_type is not None:
        if subject_type not in _VALID_SUBJECT_TYPES:
            raise ValidationError(f"subject_type 必须是 {sorted(_VALID_SUBJECT_TYPES)} 之一")
        norm_type = subject_type
        if subject_id is not None:
            norm_type, norm_id, _ = normalize_subject(subject_type, subject_id)
        else:
            # subject_type 提供但 subject_id 未提供，拒绝
            raise ValidationError("提供 subject_type 时必须同时提供 subject_id")
    elif subject_id is not None:
        # subject_id 提供但 subject_type 未提供，拒绝
        raise ValidationError("提供 subject_id 时必须同时提供 subject_type")

    def _do(conn):
        rows = store._list_thesis_rows(conn, norm_type, norm_id, status, limit, offset)
        total = store._count_thesis(conn, norm_type, norm_id, status)
        for row in rows:
            _validate_thesis_read(conn, row)
        # 返回 thesis 列表（不含 evidence_links，只含主表字段）
        return {
            "items": [store._thesis_row_to_dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Canonical Thesis Delta（S2D-C，append-only）
# ---------------------------------------------------------------------------

_DELTA_STATES = frozenset({
    "STRENGTHENED", "STABLE", "WEAKENED", "UNKNOWN",
    "DISPROVEN", "INVALIDATED",
})
_TERMINAL_DELTA_STATES = frozenset({"DISPROVEN", "INVALIDATED"})


def create_thesis_delta(
    db_path,
    thesis_id: str,
    delta_state: str | dict,
    reason: str | None = None,
    evidence_ids: list[str] | None = None,
    base_revision: int | None = None,
) -> dict:
    """Append one immutable canonical delta to a frozen, active thesis.

    Sequence allocation and evidence snapshotting happen in one BEGIN IMMEDIATE
    transaction supplied by :func:`store.write_transaction`.
    """
    # Accept the service-layer convention used by create_evidence/create_thesis
    # (a body dict) as well as the explicit argument form used by the router.
    if isinstance(delta_state, dict):
        body = delta_state
        delta_state = body.get("delta_state")
        reason = body.get("reason")
        evidence_ids = body.get("evidence_ids", [])
        base_revision = body.get("base_revision")
    if not isinstance(delta_state, str) or delta_state not in _DELTA_STATES:
        raise ValidationError(f"delta_state 必须是 {sorted(_DELTA_STATES)} 之一")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("reason 必须是非空字符串")
    if evidence_ids is None:
        evidence_ids = []
    if not isinstance(evidence_ids, list) or any(
        not isinstance(evidence_id, str) or not evidence_id.strip()
        for evidence_id in evidence_ids
    ):
        raise ValidationError("evidence_ids 必须是字符串数组")
    # Duplicate links cannot produce two snapshots for one evidence record.
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValidationError("evidence_ids 不得重复")

    now = _utc_now_iso()

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if thesis_row["status"] == "archived":
            raise ThesisDeltaConflictError("已归档的投资逻辑不可追加 delta")
        if thesis_row["formal_state"] != "frozen":
            raise ThesisDeltaConflictError("NEEDS_FROZEN: thesis formal_state 必须为 frozen")
        if thesis_row["frozen_revision"] is None:
            raise store.EvidenceLedgerCorruptedError()
        frozen_revision = int(thesis_row["frozen_revision"])
        if base_revision is not None:
            if (
                not isinstance(base_revision, int)
                or isinstance(base_revision, bool)
                or base_revision != frozen_revision
            ):
                raise ThesisDeltaConflictError(
                    f"base_revision 必须严格等于 frozen_revision ({frozen_revision})"
                )

        # Never append to a corrupt chain, and never append after a terminal delta.
        store.validate_persisted_delta_chain(conn, thesis_id)
        latest = conn.execute(
            "SELECT delta_state FROM thesis_deltas "
            "WHERE thesis_id = ? ORDER BY delta_sequence DESC LIMIT 1",
            (thesis_id,),
        ).fetchone()
        if latest is not None and latest["delta_state"] in _TERMINAL_DELTA_STATES:
            raise ThesisDeltaConflictError("terminal delta 已确认，禁止继续追加")

        next_sequence = int(conn.execute(
            "SELECT COALESCE(MAX(delta_sequence), 0) + 1 AS next_sequence "
            "FROM thesis_deltas WHERE thesis_id = ?",
            (thesis_id,),
        ).fetchone()["next_sequence"])
        delta_id = store.new_id()
        conn.execute(
            """INSERT INTO thesis_deltas
               (delta_id, thesis_id, delta_sequence, base_revision, delta_state, reason, confirmed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (delta_id, thesis_id, next_sequence, frozen_revision,
             delta_state, reason.strip(), now),
        )

        for evidence_id in evidence_ids:
            ev_row = store._get_evidence_row(conn, evidence_id)
            if ev_row is None or int(ev_row["deleted"]) == 1:
                raise EvidenceNotFoundError(f"证据 {evidence_id} 不存在")
            link_row = store._get_link_row(conn, thesis_id, evidence_id)
            if link_row is None:
                raise EvidenceNotFoundError(f"证据 {evidence_id} 未关联到此投资逻辑")
            conn.execute(
                """INSERT INTO thesis_delta_evidence_links
                   (delta_id, evidence_id, evidence_type, claim, classification, confidence,
                    source_title, source_url, source_date, accessed_at, stance, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    delta_id, evidence_id, ev_row["evidence_type"], ev_row["claim"],
                    ev_row["classification"], ev_row["confidence"], ev_row["source_title"],
                    ev_row["source_url"], ev_row["source_date"], ev_row["accessed_at"],
                    link_row["stance"], now,
                ),
            )

        delta = {
            "delta_id": delta_id,
            "thesis_id": thesis_id,
            "delta_sequence": next_sequence,
            "base_revision": frozen_revision,
            "delta_state": delta_state,
            "reason": reason.strip(),
            "confirmed_at": now,
            "evidence_links": [],
        }
        rows = conn.execute(
            "SELECT * FROM thesis_delta_evidence_links WHERE delta_id = ? ORDER BY evidence_id",
            (delta_id,),
        ).fetchall()
        delta["evidence_links"] = [store._delta_evidence_row_to_dict(row) for row in rows]
        return delta

    return store.write_transaction(db_path, _do)


def list_thesis_deltas(db_path, thesis_id: str) -> dict | None:
    """Return ordered immutable deltas and their evidence snapshots."""
    def _do(conn):
        if store._get_thesis_row(conn, thesis_id) is None:
            return None
        store.validate_persisted_delta_chain(conn, thesis_id)
        rows = conn.execute(
            "SELECT * FROM thesis_deltas WHERE thesis_id = ? ORDER BY delta_sequence ASC",
            (thesis_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = store._delta_row_to_dict(row)
            links = conn.execute(
                "SELECT * FROM thesis_delta_evidence_links WHERE delta_id = ? ORDER BY evidence_id",
                (row["delta_id"],),
            ).fetchall()
            item["evidence_links"] = [store._delta_evidence_row_to_dict(link) for link in links]
            items.append(item)
        return {"items": items, "total": len(items)}

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# 证据关联服务
# ---------------------------------------------------------------------------

def link_evidence(db_path, thesis_id: str, evidence_id: str, stance: str,
                  expected_revision: int, change_summary: str | None = None) -> dict:
    """关联证据到投资逻辑，生成新 revision。"""
    if stance not in _VALID_STANCES:
        raise ValidationError(f"stance 必须是 {sorted(_VALID_STANCES)} 之一")
    expected_revision = _validate_expected_revision(expected_revision)
    summary = (change_summary or "关联证据").strip() or "关联证据"
    now = _utc_now_iso()

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if thesis_row["status"] == "archived":
            raise ArchivedThesisError()
        if thesis_row["formal_state"] in ("confirmed", "frozen"):
            raise ContentLockedError()

        current_rev = int(thesis_row["current_revision"])
        if expected_revision != current_rev:
            raise RevisionConflictError(
                "投资逻辑已发生变化，请重新加载后重试",
                current_revision=current_rev,
            )

        ev_row = store._get_evidence_row(conn, evidence_id)
        if ev_row is None:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 不存在")
        if int(ev_row["deleted"]) == 1:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 已删除")

        # subject 一致性校验
        if (thesis_row["subject_type"] != ev_row["subject_type"]
                or thesis_row["subject_id"] != ev_row["subject_id"]):
            raise SubjectMismatchError()

        # 检查是否已关联
        existing_link = store._get_link_row(conn, thesis_id, evidence_id)
        if existing_link is not None:
            raise ValidationError("该证据已关联到此投资逻辑")

        store._insert_link(conn, {
            "thesis_id": thesis_id,
            "evidence_id": evidence_id,
            "stance": stance,
            "created_at": now,
            "updated_at": now,
        })
        _generate_revision(conn, thesis_id, summary)
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


def update_stance(db_path, thesis_id: str, evidence_id: str, stance: str,
                  expected_revision: int, change_summary: str | None = None) -> dict:
    """修改关联证据的 stance，生成新 revision。"""
    if stance not in _VALID_STANCES:
        raise ValidationError(f"stance 必须是 {sorted(_VALID_STANCES)} 之一")
    expected_revision = _validate_expected_revision(expected_revision)
    summary = (change_summary or "修改证据立场").strip() or "修改证据立场"
    now = _utc_now_iso()

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if thesis_row["status"] == "archived":
            raise ArchivedThesisError()
        # Confirmed and frozen Formal Thesis content is immutable.  Stance is
        # part of the thesis/evidence content snapshot, so it must not bypass
        # the same lock enforced by update_thesis/link_evidence.
        if thesis_row["formal_state"] in ("confirmed", "frozen"):
            raise ContentLockedError()

        current_rev = int(thesis_row["current_revision"])
        if expected_revision != current_rev:
            raise RevisionConflictError(
                "投资逻辑已发生变化，请重新加载后重试",
                current_revision=current_rev,
            )

        link_row = store._get_link_row(conn, thesis_id, evidence_id)
        if link_row is None:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 未关联到此投资逻辑")

        store._update_link_stance(conn, thesis_id, evidence_id, stance, now)
        _generate_revision(conn, thesis_id, summary)
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


def unlink_evidence(db_path, thesis_id: str, evidence_id: str,
                    expected_revision: int, change_summary: str | None = None) -> dict:
    """取消证据关联，生成新 revision。"""
    expected_revision = _validate_expected_revision(expected_revision)
    summary = (change_summary or "取消关联证据").strip() or "取消关联证据"

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            raise ThesisNotFoundError(f"投资逻辑 {thesis_id} 不存在")
        if thesis_row["status"] == "archived":
            raise ArchivedThesisError()
        # Removing a link changes the persisted thesis content and therefore
        # is also closed after Formal confirmation/freeze.
        if thesis_row["formal_state"] in ("confirmed", "frozen"):
            raise ContentLockedError()

        current_rev = int(thesis_row["current_revision"])
        if expected_revision != current_rev:
            raise RevisionConflictError(
                "投资逻辑已发生变化，请重新加载后重试",
                current_revision=current_rev,
            )

        link_row = store._get_link_row(conn, thesis_id, evidence_id)
        if link_row is None:
            raise EvidenceNotFoundError(f"证据 {evidence_id} 未关联到此投资逻辑")

        store._delete_link(conn, thesis_id, evidence_id)
        _generate_revision(conn, thesis_id, summary)
        return _get_thesis_aggregate(conn, thesis_id)

    return store.write_transaction(db_path, _do)


# ---------------------------------------------------------------------------
# Revision 服务
# ---------------------------------------------------------------------------

def list_revisions(db_path, thesis_id: str) -> dict | None:
    """列出投资逻辑的所有版本。"""
    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            return None
        _validate_thesis_read(conn, thesis_row)
        rows = store._list_revision_rows(conn, thesis_id)
        return {
            "items": [
                {
                    "id": r["id"],
                    "thesis_id": r["thesis_id"],
                    "revision_number": int(r["revision_number"]),
                    "change_summary": r["change_summary"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
            "total": len(rows),
        }

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return None


def get_revision(db_path, thesis_id: str, revision_number: int) -> dict | None:
    """获取指定版本快照。"""
    if not isinstance(revision_number, int) or isinstance(revision_number, bool) or revision_number < 1:
        raise ValidationError("revision_number 必须是正整数")

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            return None
        _validate_thesis_read(conn, thesis_row)
        row = store._get_revision_row(conn, thesis_id, revision_number)
        if row is None:
            return None
        return store._revision_row_to_dict(row)

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return None


def diff_revisions(db_path, thesis_id: str, from_rev: int, to_rev: int) -> dict | None:
    """比较两个版本的字段级差异。"""
    if not isinstance(from_rev, int) or isinstance(from_rev, bool) or from_rev < 1:
        raise ValidationError("from 必须是正整数")
    if not isinstance(to_rev, int) or isinstance(to_rev, bool) or to_rev < 1:
        raise ValidationError("to 必须是正整数")

    def _do(conn):
        thesis_row = store._get_thesis_row(conn, thesis_id)
        if thesis_row is None:
            return None
        _validate_thesis_read(conn, thesis_row)
        from_row = store._get_revision_row(conn, thesis_id, from_rev)
        to_row = store._get_revision_row(conn, thesis_id, to_rev)
        if from_row is None or to_row is None:
            return None
        from_snapshot = json.loads(from_row["snapshot"])
        to_snapshot = json.loads(to_row["snapshot"])
        return _compute_diff(from_snapshot, to_snapshot)

    try:
        return store.read_transaction(db_path, _do)
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# Diff 计算
# ---------------------------------------------------------------------------

def _compute_diff(from_snap: dict, to_snap: dict) -> dict:
    """计算两个 snapshot 的字段级 diff。"""
    from_thesis = from_snap.get("thesis", {})
    to_thesis = to_snap.get("thesis", {})
    from_links = {l["evidence_id"]: l for l in from_snap.get("evidence_links", [])}
    to_links = {l["evidence_id"]: l for l in to_snap.get("evidence_links", [])}

    # Thesis 字段 diff
    thesis_changes = {}
    _THESIS_DIFF_FIELDS = (
        "title", "summary", "status", "market",
        "core_claims", "catalysts", "risks", "invalidation_conditions",
    )
    for field in _THESIS_DIFF_FIELDS:
        old_val = from_thesis.get(field)
        new_val = to_thesis.get(field)
        if old_val != new_val:
            thesis_changes[field] = {"from": old_val, "to": new_val}

    # current_revision 变化
    old_rev = from_thesis.get("current_revision")
    new_rev = to_thesis.get("current_revision")
    if old_rev != new_rev:
        thesis_changes["current_revision"] = {"from": old_rev, "to": new_rev}

    # Evidence links diff
    evidence_added = []
    evidence_removed = []
    evidence_changed = []

    all_evidence_ids = set(from_links.keys()) | set(to_links.keys())
    for eid in all_evidence_ids:
        in_from = eid in from_links
        in_to = eid in to_links
        if in_from and not in_to:
            evidence_removed.append({"evidence_id": eid, "from": from_links[eid]})
        elif in_to and not in_from:
            evidence_added.append({"evidence_id": eid, "to": to_links[eid]})
        else:
            # 对比每个字段
            changes = {}
            for field in _SNAPSHOT_EVIDENCE_FIELDS:
                old_val = from_links[eid].get(field)
                new_val = to_links[eid].get(field)
                if old_val != new_val:
                    changes[field] = {"from": old_val, "to": new_val}
            if changes:
                evidence_changed.append({"evidence_id": eid, "changes": changes})

    return {
        "from_revision": old_rev,
        "to_revision": new_rev,
        "thesis_changes": thesis_changes,
        "evidence_added": evidence_added,
        "evidence_removed": evidence_removed,
        "evidence_changed": evidence_changed,
    }


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
