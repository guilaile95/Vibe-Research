from __future__ import annotations

import copy

import pytest

from short_term_board_semantics import (
    REASON_THEME_PROJECTION_UNAVAILABLE,
    REASON_ZT_STAT_INVALID,
    classify_board,
    exact_board_tiers,
    order_by_effective_height,
    parse_zt_stat,
)


def test_parse_exact_n_over_m_and_rebound_label():
    assert parse_zt_stat("4/2") == (4, 2)
    result = classify_board({"boards": 1, "zt_stat": "4/2"})
    assert result["stat_boards"] == 2
    assert result["effective_height"] == 2
    assert result["is_rebound"] is True
    assert result["label"] == "4天2板"


def test_adapter_shape_projects_to_rebound_semantics():
    result = classify_board({"stock_code": "000001", "boards": 1, "zt_stat": "3/2"})
    assert result["stock_code"] == "000001"
    assert result["label"] == "3天2板"
    assert result["effective_height"] == 2


def test_regular_stat_preserves_consecutive_board_height():
    result = classify_board({"boards": 3, "zt_stat": "3/3"})
    assert result["stat_boards"] == 3
    assert result["effective_height"] == 3
    assert result["is_rebound"] is False
    assert result["label"] == "3板"


def test_invalid_stat_does_not_invent_rebound():
    result = classify_board({"boards": 2, "zt_stat": "not-a-stat"})
    assert result["stat_boards"] is None
    assert result["is_rebound"] is False
    assert result["label"] == "2板"
    assert result["reason_codes"] == [REASON_ZT_STAT_INVALID]


def test_exact_tiers_do_not_compress_heights():
    assert exact_board_tiers([
        {"boards": 1}, {"boards": 2}, {"boards": 3}, {"boards": 3},
        {"boards": 5},
    ]) == [
        {"boards": 1, "count": 1},
        {"boards": 2, "count": 1},
        {"boards": 3, "count": 2},
        {"boards": 5, "count": 1},
    ]


def test_theme_ordering_is_not_applicable_without_existing_projection():
    result = order_by_effective_height(theme_projection=None)
    assert result == {
        "status": "NOT_APPLICABLE",
        "reason_codes": [REASON_THEME_PROJECTION_UNAVAILABLE],
        "members": [],
    }


def test_existing_projection_is_sorted_by_effective_height():
    result = order_by_effective_height(
        theme_projection=[
            {"code": "B", "boards": 3, "zt_stat": "3/3"},
            {"code": "A", "boards": 1, "zt_stat": "4/2"},
        ],
    )
    assert [item["label"] for item in result["members"]] == ["3板", "4天2板"]
    assert [item["code"] for item in result["members"]] == ["B", "A"]


def test_input_is_not_mutated_and_invalid_rows_fail_closed():
    rows = [{"boards": 1, "zt_stat": "2/1"}]
    before = copy.deepcopy(rows)
    classify_board(rows[0])
    assert rows == before
    with pytest.raises(ValueError):
        classify_board({"boards": 0})
