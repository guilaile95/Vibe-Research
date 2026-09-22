"""组件错误归属与敏感异常清洗；纯函数，不联网或写缓存。"""
from __future__ import annotations

import pytest

import daily_review_errors as errors


_CLIST_ERROR = (
    "ProxyError: HTTPSConnectionPool(host='provider.example', port=443): "
    "Max retries exceeded with url: /api/qt/clist/get?token=test-token "
    "https://test-user:test-password@127.0.0.1:7890/ Traceback"
)


@pytest.mark.parametrize("label", ["行业板块", "概念板块", "地域板块", "成交额榜", "全球指数"])
def test_explicit_component_owns_clist_network_failure(label):
    warnings = errors.sanitize_warning_list([_CLIST_ERROR], component_label=label)

    assert warnings == [f"{label}数据获取失败，暂不可用。"]


def test_review_envelopes_keep_component_ownership_and_failure_state():
    def unavailable():
        return {"status": "unavailable", "data": None, "warnings": [_CLIST_ERROR]}

    review = {
        "status": "partial",
        "market_environment": {"global_indices": unavailable(), "breadth": unavailable()},
        "capital_activity": {"turnover_top": unavailable()},
        "sector_rotation": {
            "industry": unavailable(), "concept": unavailable(), "region": unavailable(),
        },
    }
    result = errors.sanitize_review_public_fields(review)

    assert result is review
    assert result["status"] == "partial"
    for env, expected in (
        (review["market_environment"]["global_indices"], "全球指数数据获取失败，暂不可用。"),
        (review["market_environment"]["breadth"], errors.SAFE_BREADTH_UNAVAILABLE),
        (review["capital_activity"]["turnover_top"], "成交额榜数据获取失败，暂不可用。"),
        (review["sector_rotation"]["industry"], "行业板块数据获取失败，暂不可用。"),
        (review["sector_rotation"]["concept"], "概念板块数据获取失败，暂不可用。"),
        (review["sector_rotation"]["region"], "地域板块数据获取失败，暂不可用。"),
    ):
        assert env == {"status": "unavailable", "data": None, "warnings": [expected]}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_CLIST_ERROR, errors.SAFE_BREADTH_UNAVAILABLE),
        ("a_share_snapshot page 6 request failed", errors.SAFE_BREADTH_UNAVAILABLE),
        ("ProxyError: Unable to connect to proxy", errors.SAFE_MARKET_COMPONENT_UNAVAILABLE),
        (None, errors.SAFE_MARKET_COMPONENT_UNAVAILABLE),
        ("", errors.SAFE_MARKET_COMPONENT_UNAVAILABLE),
    ],
)
def test_unlabeled_calls_keep_legacy_behavior(raw, expected):
    assert errors.sanitize_public_message(raw) == expected


@pytest.mark.parametrize("label", ["市场广度", "breadth"])
def test_explicit_breadth_keeps_breadth_message_without_endpoint_hints(label):
    assert errors.sanitize_public_message(
        "ProxyError: Unable to connect to proxy", component_label=label,
    ) == errors.SAFE_BREADTH_UNAVAILABLE


@pytest.mark.parametrize(
    "raw",
    [
        "a_share_snapshot request failed",
        "https://test-user:test-password@provider.example/?token=test-token",
        "ProxyError: proxy 127.0.0.1:7890",
        'Traceback (most recent call last): File "private/path.py"',
    ],
)
def test_single_message_component_precedence_preserves_filtering(raw):
    assert errors.sanitize_public_message(
        raw, component_label="成交额榜",
    ) == "成交额榜数据获取失败，暂不可用。"


def test_unlabeled_custom_default_remains_compatible():
    assert errors.sanitize_public_message("ProxyError", default="刷新失败") == "刷新失败"
    assert errors.sanitize_public_message(_CLIST_ERROR, default="刷新失败") == errors.SAFE_BREADTH_UNAVAILABLE


def test_warning_list_preserves_safe_warnings_order_and_deduplication():
    assert errors.sanitize_warning_list(
        ["源数据未提供明确交易日期和行情时间", _CLIST_ERROR, _CLIST_ERROR,
         "有 5 个板块缺少有效涨跌幅", None, 7],
        component_label="行业板块",
    ) == [
        "源数据未提供明确交易日期和行情时间",
        "行业板块数据获取失败，暂不可用。",
        "有 5 个板块缺少有效涨跌幅",
    ]
