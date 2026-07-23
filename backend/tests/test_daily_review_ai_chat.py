"""chat.prepare_daily_review_messages 编排离线测试（Mock 三层与市场函数，不联网）。"""
from __future__ import annotations

from unittest.mock import call, patch

import pytest

import chat
import daily_review
import daily_review_ai_prompt
import daily_review_context


def _msgs():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


# ---------------------------------------------------------------------------
# 1. 完整调用链
# ---------------------------------------------------------------------------

def test_prepare_full_call_chain():
    review = {"status": "normal", "warnings": ["w1"]}
    ctx = '{"schema":"ok"}'
    out = _msgs()
    user_req = "重点分析市场广度"

    with (
        patch.object(daily_review, "generate_daily_review", return_value=review) as mock_gen,
        patch.object(
            daily_review_context, "render_daily_review_ai_context", return_value=ctx
        ) as mock_render,
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=out
        ) as mock_build,
    ):
        result = chat.prepare_daily_review_messages(user_req)

    assert result is out
    mock_gen.assert_called_once_with()
    mock_render.assert_called_once_with(review)
    mock_build.assert_called_once_with(ctx, user_req)
    # 顺序：gen → render → build
    assert mock_gen.call_count == 1
    assert mock_render.call_count == 1
    assert mock_build.call_count == 1


def test_prepare_analysis_returns_same_review_context_and_messages_once():
    review = {
        "status": "normal",
        "trade_date": "2026-07-23",
        "generated_at": "2026-07-23 15:30:00",
        "data_cutoff": "2026-07-23 15:00:00",
    }
    messages = _msgs()
    with (
        patch.object(daily_review, "generate_daily_review", return_value=review) as mock_gen,
        patch.object(
            daily_review_context, "render_daily_review_ai_context", return_value="context-once"
        ) as mock_render,
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=messages
        ) as mock_build,
    ):
        result = chat.prepare_daily_review_analysis("重点")

    assert result == {
        "review": review,
        "context_json": "context-once",
        "messages": messages,
    }
    mock_gen.assert_called_once_with()
    mock_render.assert_called_once_with(review)
    mock_build.assert_called_once_with("context-once", "重点")


class _SseResponse:
    def __init__(self, *chunks: bytes):
        self._chunks = chunks

    def iter_content(self, chunk_size=None):
        assert chunk_size is None
        yield from self._chunks


def test_sse_requires_explicit_done_even_after_valid_delta():
    response = _SseResponse(b'data: {"choices":[{"delta":{"content":"half"}}]}\n')
    with pytest.raises(chat.ModelStreamIncompleteError):
        list(chat._iter_sse_deltas(response))


def test_sse_accepts_done_in_final_unterminated_buffer():
    response = _SseResponse(
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
        b"data: [DONE]",
    )
    assert list(chat._iter_sse_deltas(response)) == [{"content": "ok"}]


# ---------------------------------------------------------------------------
# 2. 默认用户请求 None
# ---------------------------------------------------------------------------

def test_prepare_user_request_none_passed_through():
    with (
        patch.object(daily_review, "generate_daily_review", return_value={"status": "normal"}),
        patch.object(daily_review_context, "render_daily_review_ai_context", return_value="{}"),
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=_msgs()
        ) as mock_build,
    ):
        chat.prepare_daily_review_messages(None)

    mock_build.assert_called_once_with("{}", None)


# ---------------------------------------------------------------------------
# 3. 空字符串原样传递
# ---------------------------------------------------------------------------

def test_prepare_empty_string_not_rewritten():
    with (
        patch.object(daily_review, "generate_daily_review", return_value={"status": "normal"}),
        patch.object(daily_review_context, "render_daily_review_ai_context", return_value="{}"),
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=_msgs()
        ) as mock_build,
    ):
        chat.prepare_daily_review_messages("")

    mock_build.assert_called_once_with("{}", "")


# ---------------------------------------------------------------------------
# 4. partial 仍构建消息
# ---------------------------------------------------------------------------

def test_prepare_partial_still_builds():
    review = {
        "status": "partial",
        "warnings": ["[概念板块] timeout"],
        "data_health": {"components": {"concept_boards": "unavailable"}},
    }
    with (
        patch.object(daily_review, "generate_daily_review", return_value=review) as mock_gen,
        patch.object(
            daily_review_context, "render_daily_review_ai_context", return_value='{"status":"partial"}'
        ) as mock_render,
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=_msgs()
        ) as mock_build,
    ):
        result = chat.prepare_daily_review_messages("观察")

    assert result == _msgs()
    mock_gen.assert_called_once()
    mock_render.assert_called_once_with(review)
    # 未短路、未改 status
    assert mock_render.call_args[0][0]["status"] == "partial"
    assert mock_render.call_args[0][0]["warnings"] == ["[概念板块] timeout"]
    mock_build.assert_called_once()


# ---------------------------------------------------------------------------
# 5. unavailable 仍构建消息
# ---------------------------------------------------------------------------

def test_prepare_unavailable_still_builds():
    review = {"status": "unavailable", "warnings": ["核心数据不可用"]}
    with (
        patch.object(daily_review, "generate_daily_review", return_value=review),
        patch.object(
            daily_review_context, "render_daily_review_ai_context", return_value="{}"
        ) as mock_render,
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=_msgs()
        ) as mock_build,
    ):
        result = chat.prepare_daily_review_messages(None)

    assert result == _msgs()
    mock_render.assert_called_once()
    mock_build.assert_called_once()
    # chat 层不生成固定拒绝文案
    assert all("无法完成" not in (m.get("content") or "") for m in result)


# ---------------------------------------------------------------------------
# 6. 聚合器异常
# ---------------------------------------------------------------------------

def test_prepare_aggregator_error_propagates():
    with (
        patch.object(
            daily_review, "generate_daily_review", side_effect=RuntimeError("snapshot failed")
        ),
        patch.object(daily_review_context, "render_daily_review_ai_context") as mock_render,
        patch.object(daily_review_ai_prompt, "build_daily_review_messages") as mock_build,
    ):
        with pytest.raises(RuntimeError, match="snapshot failed"):
            chat.prepare_daily_review_messages("x")
        mock_render.assert_not_called()
        mock_build.assert_not_called()


# ---------------------------------------------------------------------------
# 7. 投影器异常
# ---------------------------------------------------------------------------

def test_prepare_renderer_error_propagates():
    with (
        patch.object(daily_review, "generate_daily_review", return_value={"status": "normal"}),
        patch.object(
            daily_review_context,
            "render_daily_review_ai_context",
            side_effect=RuntimeError("render failed"),
        ),
        patch.object(daily_review_ai_prompt, "build_daily_review_messages") as mock_build,
    ):
        with pytest.raises(RuntimeError, match="render failed"):
            chat.prepare_daily_review_messages("x")
        mock_build.assert_not_called()


# ---------------------------------------------------------------------------
# 8. prompt 构建异常
# ---------------------------------------------------------------------------

def test_prepare_prompt_builder_error_propagates():
    with (
        patch.object(daily_review, "generate_daily_review", return_value={"status": "normal"}),
        patch.object(
            daily_review_context, "render_daily_review_ai_context", return_value="{}"
        ),
        patch.object(
            daily_review_ai_prompt,
            "build_daily_review_messages",
            side_effect=ValueError("bad context"),
        ),
    ):
        with pytest.raises(ValueError, match="bad context"):
            chat.prepare_daily_review_messages("x")


# ---------------------------------------------------------------------------
# 9. 不调用底层市场函数
# ---------------------------------------------------------------------------

def test_prepare_does_not_call_market_layer():
    def _boom(*_a, **_k):
        raise AssertionError("market/astock must not be called")

    with (
        patch("market.get_market_breadth", side_effect=_boom),
        patch("market.get_board_ranking", side_effect=_boom),
        patch("market.get_short_term_emotion", side_effect=_boom),
        patch("astock.index_quote", side_effect=_boom),
        patch.object(daily_review, "generate_daily_review", return_value={"status": "normal"}),
        patch.object(
            daily_review_context, "render_daily_review_ai_context", return_value="{}"
        ),
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=_msgs()
        ),
    ):
        result = chat.prepare_daily_review_messages("ok")
    assert result == _msgs()


# ---------------------------------------------------------------------------
# 10. 消息结构不被追加
# ---------------------------------------------------------------------------

def test_prepare_does_not_append_extra_messages():
    prepared = [
        {"role": "system", "content": "daily-system-only"},
        {"role": "user", "content": "daily-user-only"},
    ]
    with (
        patch.object(daily_review, "generate_daily_review", return_value={}),
        patch.object(
            daily_review_context, "render_daily_review_ai_context", return_value="{}"
        ),
        patch.object(
            daily_review_ai_prompt, "build_daily_review_messages", return_value=prepared
        ),
    ):
        result = chat.prepare_daily_review_messages("x")

    assert result == prepared
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert result[1]["role"] == "user"
    # 未混入通用 SYSTEM_PROMPT
    assert "投研分析框架" not in result[0]["content"]
    assert "query_quote" not in result[0]["content"]
    # 无 assistant 占位
    assert all(m["role"] != "assistant" for m in result)
