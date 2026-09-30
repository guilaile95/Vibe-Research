"""Offline tool-result and grounding contracts; not a claim of real-model quality."""
import copy
import json

import pytest

import chat


@pytest.mark.parametrize("payload,status", [
    (None, "empty"), ([], "empty"), ({}, "empty"),
    ({"data": [], "source": "fixture", "trade_date": "2026-09-29"}, "empty"),
    ({"period": "近5年", "metrics": {}}, "empty"),
    ({"unit": "元", "recent": []}, "empty"),
    ({"rows": [{}], "items": [], "generated_at": "fixture"}, "empty"),
    ({"history": [], "upcoming": []}, "empty"),
    ({"price": 0, "change_pct": 0, "missing": None}, "success"),
    ({"data": [{"change_pct": 0}], "status": "normal"}, "success"),
    ({"error": "PRIVATE PROVIDER URL KEY"}, "error"),
    ({"forward": {"unavailable": True, "err": "PRIVATE", "months": []}}, "error"),
    ({"status": "partial", "rows": [{"price": 12}]}, "partial"),
    ({"error": "PRIVATE", "rows": [{"price": 12}]}, "partial"),
    ({"spot": {"price": 12}, "forward": {"unavailable": True, "err": "PRIVATE"}}, "partial"),
    ({"status": "stale", "data": [{"price": 12}]}, "partial"),
])
def test_actual_tool_shapes_keep_empty_zero_and_partial_distinct(payload, status):
    serialized, outcome, truncated = chat._serialize_tool_result(payload)
    result = json.loads(serialized)
    assert outcome == result["status"] == status
    assert not truncated
    assert "PRIVATE" not in serialized
    if isinstance(payload, dict) and payload.get("rows") and status == "partial":
        assert result["data"]["rows"] == payload["rows"]
    if isinstance(payload, dict) and "change_pct" in payload:
        assert result["data"]["change_pct"] == 0
        assert result["data"]["missing"] is None


def test_truncation_is_valid_json_and_keeps_source_time_and_health():
    payload = {"data": [{"title": '\\"中文' * 1000, "price": 12.3} for _ in range(80)],
               "source": "fixture", "trade_date": "2026-09-29", "is_stale": True,
               "observed_at": "2026-09-29T10:00:00+08:00"}
    serialized, status, truncated = chat._serialize_tool_result(payload)
    assert len(serialized) <= chat._TOOL_RESULT_CAP
    result = json.loads(serialized)
    assert status == "partial" and truncated and result["truncated"]
    assert result["data"]["source"] == "fixture"
    assert result["data"]["trade_date"] == "2026-09-29"
    assert result["data"]["observed_at"] == payload["observed_at"]
    assert result["data"]["is_stale"] is True
    assert result["data"]["data"][0]["price"] == 12.3
    assert any("遗漏" in text for text in result["limitations"])


def test_unrepresentable_payload_is_not_reported_as_success():
    for payload in ({"price": float("nan")}, {"price": object()}):
        serialized, status, truncated = chat._serialize_tool_result(payload)
        assert status == "error" and not truncated
        assert json.loads(serialized)["data"] is None
    serialized, status, truncated = chat._serialize_tool_result({"K" * 7000: 12})
    assert len(serialized) <= chat._TOOL_RESULT_CAP
    assert status == "empty" and truncated
    assert json.loads(serialized)["data"] is None


@pytest.mark.parametrize("result,status", [({"price": 0}, "success"), ([], "empty"),
    ({"error": "PRIVATE"}, "error"), ({"price": 12, "err": "PRIVATE"}, "partial")])
def test_stream_sends_result_after_execution_and_returns_same_model_envelope(monkeypatch, result, status):
    rounds = iter([
        [{"tool_calls": [{"index": 0, "id": "upstream-id", "function": {
            "name": "query_quote", "arguments": '{"codes":["600519"]}'}}]}],
        [{"content": "fixture answer"}],
    ])
    sent = []
    monkeypatch.setattr(chat, "_call_llm_stream", lambda _cfg, messages, _tools: sent.append(copy.deepcopy(messages)))
    monkeypatch.setattr(chat, "_iter_sse_deltas", lambda _response: iter(next(rounds)))
    executed = []
    monkeypatch.setattr(chat, "_exec_tool", lambda *_: executed.append(True) or result)
    stream = chat.run_chat_stream({"baseURL": "https://example.test/v1", "apiKey": "synthetic", "model": "fixture"},
                                  [{"role": "user", "content": "查价格"}])
    started = next(stream)
    assert started["type"] == "tool" and not executed
    finished = next(stream)
    assert executed and finished == {"type": "tool_result", "call_id": started["call_id"],
        "tool": "query_quote", "status": status, "truncated": False}
    remaining = list(stream)
    assert [event["type"] for event in remaining] == ["delta", "done"]
    tool_message = next(message for message in sent[1] if message["role"] == "tool")
    assert tool_message["tool_call_id"] == "upstream-id"
    assert json.loads(tool_message["content"])["status"] == status
    assert "PRIVATE" not in tool_message["content"]
    assert chat.GROUNDING_RULES in sent[0][0]["content"]


def test_grounding_contract_limits_inference_without_changing_formal_authority():
    for term in ("已知事实", "可能解释", "待核对问题", "相反证据", "什么新证据", "null/缺失",
                 "不是新的事实来源", "抓取时间", "只有新闻/公告/研报标题", "不能把分歧写成一致结论"):
        assert term in chat.GROUNDING_RULES
