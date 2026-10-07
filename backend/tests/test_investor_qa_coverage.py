"""Synthetic adapter/model-envelope checks, without provider or model calls."""
import copy
import json

import pytest

import ai_tools
import chat
import mcp_server


def result(monkeypatch, rows):
    before = copy.deepcopy(rows)
    monkeypatch.setattr(ai_tools.astock, 'investor_qa', lambda code: rows)
    output = ai_tools.exec_tool('query_investor_qa', {'code': '000001'})
    assert rows == before
    return output


def test_short_payload_discloses_lost_qualification(monkeypatch):
    payload = result(monkeypatch, [{'question': '问', 'answer': '答' * 400 + '仅为假设'}])
    serialized, status, truncated = chat._serialize_tool_result(payload)
    assert status == 'partial'
    assert not truncated  # Context fits; loss already happened in the adapter.
    assert payload['adapter_coverage']['answer_chars_omitted_in_selected_rows'] == 4
    assert payload['items'][0]['answer_truncated'] is True
    assert '仅为假设' not in serialized
    assert json.loads(serialized)['limitations']


@pytest.mark.parametrize('qsize,asize,partial', [(199, 399, False), (200, 400, False), (201, 401, True)])
def test_exact_unicode_boundaries(monkeypatch, qsize, asize, partial):
    payload = result(monkeypatch, [{'question': '问' * qsize, 'answer': '答' * asize}])
    row = payload['items'][0]
    assert len(row['question']) == min(qsize, 200)
    assert len(row['answer']) == min(asize, 400)
    assert row['question_truncated'] == row['answer_truncated'] == partial
    assert payload['status'] == ('partial' if partial else 'success')
    assert chat._serialize_tool_result(payload)[1:] == (payload['status'], False)


def test_row_limit_counts_only_returned_source_window(monkeypatch):
    payload = result(monkeypatch, [{'question': f'Q{i}', 'answer': 'A'} for i in range(30)])
    assert payload['adapter_coverage'] == {
        'scope': 'adapter_input_before_context_compaction',
        'input_rows': 30, 'output_rows': 12, 'omitted_rows': 18,
        'question_chars_omitted_in_selected_rows': 0,
        'answer_chars_omitted_in_selected_rows': 0,
    }
    assert len(payload['items']) == 12
    assert chat._serialize_tool_result(payload)[1:] == ('partial', False)


@pytest.mark.parametrize('rows', [[], None])
def test_coverage_cannot_turn_empty_input_into_evidence(monkeypatch, rows):
    payload = result(monkeypatch, rows)
    assert payload['items'] == []
    assert chat._serialize_tool_result(payload)[1:] == ('empty', False)


def test_missing_answer_remains_unknown(monkeypatch):
    payload = result(monkeypatch, [{'question': '有提问', 'answer': None}])
    assert payload['items'][0]['answer'] is None
    assert not payload['items'][0]['answer_truncated']


def test_context_compaction_is_separate_from_adapter_counts(monkeypatch):
    payload = result(monkeypatch, [{'question': '问' * 250, 'answer': '答' * 500} for _ in range(30)])
    serialized, status, truncated = chat._serialize_tool_result(payload)
    envelope = json.loads(serialized)
    assert status == 'partial' and truncated
    assert len(serialized) <= chat._TOOL_RESULT_CAP
    assert envelope['data']['adapter_coverage'] == payload['adapter_coverage']
    assert len(envelope['data']['items']) < payload['adapter_coverage']['output_rows']
    assert envelope['data']['adapter_coverage']['answer_chars_omitted_in_selected_rows'] == 1200
    assert any('遗漏' in note for note in envelope['limitations'])


def test_mcp_returns_same_adapter_disclosure(monkeypatch):
    payload = result(monkeypatch, [{'question': '问', 'answer': '答' * 401}])
    replies = []
    monkeypatch.setattr(mcp_server, '_result', lambda rid, value: replies.append(value))
    mcp_server._handle({'id': 1, 'method': 'tools/call', 'params': {
        'name': 'query_investor_qa', 'arguments': {'code': '000001'}}})
    assert not replies[0]['isError']
    assert json.loads(replies[0]['content'][0]['text']) == payload


def test_missing_text_is_not_evidence(monkeypatch):
    payload = result(monkeypatch, [{'question': None, 'answer': None}])
    assert chat._serialize_tool_result(payload)[1:] == ('empty', False)


def test_chat_stream_propagates_adapter_partial_status(monkeypatch):
    result(monkeypatch, [{'question': '问', 'answer': '答' * 401}])
    rounds = iter([
        [{'tool_calls': [{'index': 0, 'id': 'fixture-call', 'function': {
            'name': 'query_investor_qa', 'arguments': '{"code":"000001"}'}}]}],
        [{'content': 'synthetic answer'}],
    ])
    sent = []
    monkeypatch.setattr(chat, '_call_llm_stream', lambda _cfg, messages, _tools: sent.append(copy.deepcopy(messages)))
    monkeypatch.setattr(chat, '_iter_sse_deltas', lambda _response: iter(next(rounds)))
    events = list(chat.run_chat_stream({'baseURL': 'https://example.test/v1', 'apiKey': 'synthetic', 'model': 'fixture'},
                                      [{'role': 'user', 'content': '查询问答'}]))
    finished = next(event for event in events if event['type'] == 'tool_result')
    assert finished['status'] == 'partial' and finished['truncated'] is False
    tool_message = next(message for message in sent[1] if message['role'] == 'tool')
    envelope = json.loads(tool_message['content'])
    assert envelope['status'] == 'partial'
    assert envelope['data']['items'][0]['answer_truncated'] is True
