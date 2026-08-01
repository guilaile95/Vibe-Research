"""告警规则 CRUD API v0.1。

只暴露已验收的 AlertRule 领域模型与 alert_rule_store 持久化能力。
不实现求值、事实快照、通知、调度、历史或恢复。
"""

from __future__ import annotations

import re
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request

from alert_rules import CODE_PATTERN, RULE_ID_PATTERN, AlertRule
import alert_rule_store as store

router = APIRouter(
    prefix="/api",
    tags=["alert-rules"],
)

_LIMIT_PATTERN = re.compile(r"^[1-9][0-9]*$")
_OFFSET_PATTERN = re.compile(r"^(0|[1-9][0-9]*)$")
_REVISION_PATTERN = re.compile(r"^[1-9][0-9]*$")

_INVALID_INPUT_DETAIL = "告警规则参数无效"
_NOT_FOUND_DETAIL = "告警规则不存在"
_ALREADY_EXISTS_DETAIL = "告警规则已存在"
_REVISION_CONFLICT_DETAIL = "告警规则已发生变化，请重新加载后重试"
_STORE_UNAVAILABLE_DETAIL = "告警规则存储暂时不可用"
_INTERNAL_ERROR_DETAIL = "告警规则服务内部错误"


def _parse_bool_query(request: Request, name: str) -> bool | None:
    """只接受小写 true/false；重复、大小写变体、1/0/yes/on、空格均 422。"""
    values = request.query_params.getlist(name)
    if not values:
        return None
    if len(values) != 1:
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    value = values[0]
    if value == "true":
        return True
    if value == "false":
        return False
    raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)


def _parse_int_query(
    request: Request,
    name: str,
    *,
    pattern: re.Pattern[str],
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    """只接受规范 ASCII 整数字面量；重复、前导零、+、小数、布尔值均 422。"""
    values = request.query_params.getlist(name)
    if not values:
        return default
    if len(values) != 1:
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    value = values[0]
    if not pattern.fullmatch(value):
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    return number


def _parse_required_revision(request: Request) -> int:
    """expected_revision 必填；只接受 ^[1-9][0-9]*$；重复值 422。"""
    values = request.query_params.getlist("expected_revision")
    if not values:
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    if len(values) != 1:
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    value = values[0]
    if not _REVISION_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    return int(value)


def _parse_code_query(request: Request) -> str | None:
    """code 筛选必须精确匹配 ASCII 六位数字；不 trim；重复值 422。"""
    values = request.query_params.getlist("code")
    if not values:
        return None
    if len(values) != 1:
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    value = values[0]
    if not CODE_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    return value


def _validated_rule_id(rule_id: str) -> None:
    """路径 rule_id 必须匹配既有 RULE_ID_PATTERN，非法值在触碰数据库前 422。"""
    if not isinstance(rule_id, str) or not RULE_ID_PATTERN.fullmatch(rule_id):
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)


def _raise_store_error(exc: Exception) -> NoReturn:
    """集中式异常映射，顺序从具体到一般，detail 固定且不含内部信息。"""
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, store.AlertRuleStoreInputError):
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL) from exc
    if isinstance(exc, store.AlertRuleNotFoundError):
        raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL) from exc
    if isinstance(exc, store.AlertRuleAlreadyExistsError):
        raise HTTPException(status_code=409, detail=_ALREADY_EXISTS_DETAIL) from exc
    if isinstance(exc, store.AlertRuleRevisionConflictError):
        raise HTTPException(
            status_code=409, detail=_REVISION_CONFLICT_DETAIL
        ) from exc
    if isinstance(exc, store.AlertRuleStoreCorruptedError):
        raise HTTPException(
            status_code=500, detail=store.AlertRuleStoreCorruptedError.MESSAGE
        ) from exc
    if isinstance(exc, store.AlertRuleStoreError):
        raise HTTPException(status_code=500, detail=_STORE_UNAVAILABLE_DETAIL) from exc
    raise HTTPException(status_code=500, detail=_INTERNAL_ERROR_DETAIL) from exc


@router.post("/alert-rules", status_code=201)
def create_alert_rule(body: AlertRule) -> dict[str, Any]:
    """创建告警规则；重复 rule_id（含软删除）返回 409。"""
    try:
        record = store.create_alert_rule(body)
    except Exception as exc:
        _raise_store_error(exc)
    return {"data": record.model_dump(mode="json")}


@router.get("/alert-rules")
def list_alert_rules(request: Request) -> dict[str, Any]:
    """列表：code/enabled/include_deleted/limit/offset，排序与过滤沿用 Store。"""
    code = _parse_code_query(request)
    enabled = _parse_bool_query(request, "enabled")
    include_deleted = _parse_bool_query(request, "include_deleted") or False
    limit = _parse_int_query(
        request,
        "limit",
        pattern=_LIMIT_PATTERN,
        default=100,
        minimum=1,
        maximum=200,
    )
    offset = _parse_int_query(
        request,
        "offset",
        pattern=_OFFSET_PATTERN,
        default=0,
        minimum=0,
    )
    try:
        records = store.list_alert_rules(
            code=code,
            enabled=enabled,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_store_error(exc)
    return {"data": [record.model_dump(mode="json") for record in records]}


@router.get("/alert-rules/{rule_id}")
def get_alert_rule(rule_id: str, request: Request) -> dict[str, Any]:
    """单条读取；默认隐藏软删除，include_deleted=true 可读取。"""
    _validated_rule_id(rule_id)
    include_deleted = _parse_bool_query(request, "include_deleted") or False
    try:
        record = store.get_alert_rule(rule_id, include_deleted=include_deleted)
    except Exception as exc:
        _raise_store_error(exc)
    if record is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
    return {"data": record.model_dump(mode="json")}


@router.put("/alert-rules/{rule_id}")
def replace_alert_rule(
    rule_id: str, request: Request, body: AlertRule
) -> dict[str, Any]:
    """完整替换；路径 rule_id 必须等于 body.rule_id；乐观锁走 expected_revision。"""
    _validated_rule_id(rule_id)
    expected_revision = _parse_required_revision(request)
    if body.rule_id != rule_id:
        raise HTTPException(status_code=422, detail=_INVALID_INPUT_DETAIL)
    try:
        record = store.replace_alert_rule(
            rule_id, body, expected_revision=expected_revision
        )
    except Exception as exc:
        _raise_store_error(exc)
    return {"data": record.model_dump(mode="json")}


@router.delete("/alert-rules/{rule_id}")
def delete_alert_rule(rule_id: str, request: Request) -> dict[str, Any]:
    """软删除；不接收 JSON body；返回软删除后的完整记录。"""
    _validated_rule_id(rule_id)
    expected_revision = _parse_required_revision(request)
    try:
        record = store.delete_alert_rule(
            rule_id, expected_revision=expected_revision
        )
    except Exception as exc:
        _raise_store_error(exc)
    return {"data": record.model_dump(mode="json")}
