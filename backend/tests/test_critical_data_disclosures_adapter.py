"""P0-DS1 — cap.security.disclosures evaluator 专项测试。

全部注入 fake announcements reader；不访问真实数据源、不发网络请求。
覆盖：provider failure / EMPTY_BUT_VALID（无公告 ≠ 失败）/
freshness 无法证明 → UNKNOWN / 结构损坏 fail closed / USABLE positive proof。
"""
from __future__ import annotations

import pytest

import critical_data_disclosures_adapter as adapter
from critical_data_disclosures_adapter import (
    ADAPTER_AUTHORITY_REF,
    DisclosuresCapabilityError,
    EMPTY_BUT_VALID_REF,
    SAME_DAY_DATE_ONLY_REF,
    evaluate_disclosures_capability,
)

SECURITY = "600519"
CAMPAIGN = "campaign_" + "a" * 32
AS_OF = "2026-08-13T04:00:00.000000Z"
FETCHED_AT = "2026-08-13T03:00:00.000000Z"


def _payload(**overrides):
    base = {
        "announcements": [
            {"date": "2026-08-12", "title": "公告一", "type": "定期报告", "url": "u"},
            {"date": "2026-08-10", "title": "公告二", "type": "权益分派", "url": "u"},
        ],
        "fetched_at": FETCHED_AT,
        "source": "eastmoney-announcements",
    }
    base.update(overrides)
    return base


def _evaluate(reader, *, as_of: str = AS_OF):
    return evaluate_disclosures_capability(
        security_code=SECURITY,
        campaign_id=CAMPAIGN,
        as_of=as_of,
        announcements_reader=reader,
    )


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        {"security_code": "bad"},
        {"campaign_id": "nope"},
        {"as_of": ""},
    ],
)
def test_invalid_inputs_raise(kwargs):
    params = {
        "security_code": SECURITY,
        "campaign_id": CAMPAIGN,
        "as_of": AS_OF,
        **kwargs,
    }
    with pytest.raises(DisclosuresCapabilityError):
        evaluate_disclosures_capability(**params)


# ---------------------------------------------------------------------------
# provider failure / 形状
# ---------------------------------------------------------------------------

def test_reader_exception_is_error_unavailable():
    def broken(_code):
        raise RuntimeError("network down")

    assert _evaluate(broken)["state"] == "ERROR"


def test_reader_none_or_non_mapping_is_error():
    assert _evaluate(lambda _code: None)["state"] == "ERROR"
    assert _evaluate(lambda _code: "bad")["state"] == "ERROR"


def test_announcements_not_list_is_error():
    assert _evaluate(lambda _code: _payload(announcements="bad"))["state"] == "ERROR"


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------

def test_missing_fetched_at_is_unknown():
    """无法证明 freshness → UNKNOWN，绝不因 HTTP 200 而 USABLE。"""
    assert _evaluate(lambda _code: _payload(fetched_at=None))["state"] == "UNKNOWN"


def test_malformed_fetched_at_is_unknown():
    assert _evaluate(
        lambda _code: _payload(fetched_at="2026-08-13 11:00:00")
    )["state"] == "UNKNOWN"


def test_fetched_at_after_as_of_is_normal_not_not_evaluated():
    """§1/§A：生产实际顺序 snapshot → request → retrieval completes later；
    fetched_at 晚于 as_of 是正常网络耗时，绝不天然 NOT_EVALUATED。"""
    result = _evaluate(lambda _code: _payload(
        fetched_at="2026-08-13T04:01:00.000000Z",  # 晚于 as_of 04:00:00
    ))
    assert result["state"] == "USABLE"
    assert "disclosures:count=2" in result["authority_refs"]


def test_lookahead_announcements_excluded_but_result_usable():
    """§B：历史 as_of 不得 look-ahead —— 未来公告从判定排除；可见公告正常评估。"""
    result = _evaluate(lambda _code: _payload(announcements=[
        {"date": "2026-08-13", "notice_at": "2026-08-13 10:00:00",
         "title": "可见", "type": "A", "url": "u"},
        {"date": "2026-08-15", "notice_at": "2026-08-15 10:00:00",
         "title": "未来", "type": "B", "url": "u"},
    ]))
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert "disclosures:count=1" in refs
    assert "disclosures:latest_notice_date=2026-08-13" in refs
    assert any(ref.startswith("disclosures:lookahead-excluded=") for ref in refs)


def test_all_lookahead_announcements_is_empty_but_valid():
    """全部公告都是未来 → as_of 时点无可见公告 = 有效空（非失败、非伪造）。"""
    result = _evaluate(lambda _code: _payload(announcements=[
        {"date": "2026-08-15", "notice_at": "2026-08-15 10:00:00",
         "title": "未来一", "type": "A", "url": "u"},
        {"date": "2026-08-16", "notice_at": "2026-08-16 10:00:00",
         "title": "未来二", "type": "B", "url": "u"},
    ]))
    assert result["state"] == "USABLE"
    assert EMPTY_BUT_VALID_REF in result["authority_refs"]
    assert any(
        ref.startswith("disclosures:lookahead-excluded=")
        for ref in result["authority_refs"]
    )


# ---------------------------------------------------------------------------
# R2：same-day look-ahead（publish time <= as_of 证明可见）
# ---------------------------------------------------------------------------

def test_same_day_earlier_disclosure_visible():
    """§A：as_of=当天 12:00（北京），公告 10:00 发布 → 可见。"""
    result = _evaluate(lambda _code: _payload(announcements=[
        {"date": "2026-08-13", "notice_at": "2026-08-13 10:00:00",
         "title": "早于 as_of", "type": "A", "url": "u"},
    ]))
    assert result["state"] == "USABLE"
    assert "disclosures:count=1" in result["authority_refs"]


def test_same_day_later_disclosure_excluded():
    """§B：as_of=当天 12:00（北京），公告 20:00 发布 → 排除（look-ahead）。"""
    result = _evaluate(lambda _code: _payload(announcements=[
        {"date": "2026-08-13", "notice_at": "2026-08-13 20:00:00",
         "title": "晚于 as_of", "type": "A", "url": "u"},
    ]))
    assert result["state"] == "USABLE"  # 有效空（全部被排除）
    assert EMPTY_BUT_VALID_REF in result["authority_refs"]
    assert any(
        ref.startswith("disclosures:lookahead-excluded=")
        for ref in result["authority_refs"]
    )


def test_date_only_same_day_fails_closed():
    """§C：date-only 且 == as_of 北京当日 + 历史 as_of → 不得猜已发布 →
    UNKNOWN + 显式 ref。"""
    result = _evaluate(lambda _code: _payload(announcements=[
        {"date": "2026-08-13", "title": "同日无时间", "type": "A", "url": "u"},
    ]))
    assert result["state"] == "UNKNOWN"
    assert SAME_DAY_DATE_ONLY_REF in result["authority_refs"]


def test_date_only_past_day_still_visible():
    """date-only 但早于北京当日 → 肯定已发布，可见。"""
    result = _evaluate(lambda _code: _payload(announcements=[
        {"date": "2026-08-12", "title": "昨日公告", "type": "A", "url": "u"},
    ]))
    assert result["state"] == "USABLE"
    assert "disclosures:count=1" in result["authority_refs"]


# ---------------------------------------------------------------------------
# EMPTY_BUT_VALID / USABLE
# ---------------------------------------------------------------------------

def test_empty_but_valid_is_usable_not_provider_failure():
    """§11-E：无公告但查询成功 ≠ provider failure。"""
    result = _evaluate(lambda _code: _payload(announcements=[]))
    assert result["state"] == "USABLE"
    assert EMPTY_BUT_VALID_REF in result["authority_refs"]


def test_announcements_present_is_usable_with_coverage_refs():
    result = _evaluate(lambda _code: _payload())
    assert result["state"] == "USABLE"
    refs = result["authority_refs"]
    assert ADAPTER_AUTHORITY_REF in refs
    assert "disclosures:source=eastmoney-announcements" in refs
    assert f"disclosures:fetched_at={FETCHED_AT}" in refs
    assert "disclosures:count=2" in refs
    assert "disclosures:latest_notice_date=2026-08-12" in refs


def test_malformed_announcement_date_fails_closed():
    result = _evaluate(lambda _code: _payload(
        announcements=[{"date": "2026/08/12", "title": "x", "type": "", "url": ""}]
    ))
    assert result["state"] == "ERROR"


def test_non_mapping_announcement_item_fails_closed():
    result = _evaluate(lambda _code: _payload(announcements=["bad"]))
    assert result["state"] == "ERROR"


def test_result_identity_and_as_of():
    result = _evaluate(lambda _code: _payload())
    assert result["dependency_id"] == adapter.DEPENDENCY_ID
    assert result["as_of"] == AS_OF
