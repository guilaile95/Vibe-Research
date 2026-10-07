"""Actual report/news adapters and consumers, with synthetic source windows."""
import copy
import json

import pytest

import ai_tools
import chat
import debate
import mcp_server


CASES = [
    ('query_reports', 'eastmoney_reports', ('title', 'publishDate', 'orgSName', 'emRatingName'),
     15, {'code': '000001'}, {'max_pages': 1}, 'infoCode'),
    ('query_news', 'stock_news', ('新闻标题', '发布时间', '文章来源'),
     15, {'code': '000001'}, {'limit': 15}, '新闻内容'),
    ('query_industry_reports', 'eastmoney_industry_reports', ('title', 'publishDate', 'orgSName', 'industryName'),
     20, {'keywords': ['fixture'], 'days': 7}, {'keywords': ['fixture'], 'days': 7, 'max_pages': 1}, 'infoCode'),
]


@pytest.fixture(params=CASES, ids=lambda case: case[0])
def source(request, monkeypatch):
    tool, provider, keys, limit, args, kwargs, extra = request.param
    rows = [{**{key: f'fixture-{key}' for key in keys}, extra: 'omitted-synthetic-detail'}]
    calls = []

    def read(*actual_args, **actual_kwargs):
        calls.append((actual_args, actual_kwargs))
        return rows

    monkeypatch.setattr(ai_tools.astock, provider, read)
    return tool, keys, limit, args, kwargs, rows, calls


def test_field_projection_below_context_cap_is_explicit_and_array_compatible(source):
    tool, keys, _limit, args, kwargs, rows, calls = source
    before = copy.deepcopy(rows)
    payload = ai_tools.exec_tool(tool, args)
    assert rows == before
    assert isinstance(payload, list) and len(payload) == 1
    assert [{key: row[key] for key in keys} for row in payload] == [{key: rows[0][key] for key in keys}]
    serialized, status, truncated = chat._serialize_tool_result(payload)
    assert (status, truncated) == ('partial', False)
    assert payload[0]['adapter_coverage']['omitted_fields_in_selected_rows'] == 1
    assert payload[0]['adapter_coverage']['omitted_rows'] == 0
    assert 'omitted-synthetic-detail' not in serialized
    assert '不是全文' in serialized
    assert len(calls) == 1 and calls[0][1] == kwargs


def test_row_and_field_counts_are_distinct(source):
    tool, _keys, limit, args, _kwargs, rows, _calls = source
    # News' reader currently returns at most 15 rows; a larger synthetic window
    # also verifies the adapter remains honest if that reader contract expands.
    rows.extend(copy.deepcopy(rows[0]) for _ in range(limit))
    payload = ai_tools.exec_tool(tool, args)
    coverage = payload[0]['adapter_coverage']
    assert len(payload) == limit
    assert coverage['input_rows'] == limit + 1
    assert coverage['output_rows'] == coverage['omitted_fields_in_selected_rows'] == limit
    assert coverage['omitted_rows'] == 1
    assert all('adapter_coverage' not in row for row in payload[1:])


def test_empty_and_unprojected_rows_do_not_claim_false_partial(source):
    tool, keys, _limit, args, _kwargs, rows, _calls = source
    rows[:] = [{key: rows[0][key] for key in keys}]
    payload = ai_tools.exec_tool(tool, args)
    assert chat._serialize_tool_result(payload)[1:] == ('success', False)
    rows.clear()
    assert ai_tools.exec_tool(tool, args) == []
    assert chat._serialize_tool_result(ai_tools.exec_tool(tool, args))[1:] == ('empty', False)


def test_mcp_and_debate_consume_real_projection(source, monkeypatch):
    tool, _keys, _limit, args, _kwargs, _rows, _calls = source
    replies = []
    monkeypatch.setattr(mcp_server, '_result', lambda rid, value: replies.append(value))
    mcp_server._handle({'id': 1, 'method': 'tools/call', 'params': {'name': tool, 'arguments': args}})
    payload = json.loads(replies[0]['content'][0]['text'])
    assert isinstance(payload, list) and payload[0]['status'] == 'partial'
    assert not replies[0]['isError']
    section = debate._fetch_section((tool, args, 'fixture title', False, True), '000001')
    assert section['status'] == 'partial' and not section['ok']
    assert section['truncated'] is False
    assert json.loads(section['body'])['data'] == payload
    assert len(section['body']) <= debate._SECTION_CAP


def test_nonstream_chat_consumes_real_projection_without_extra_tool_calls(source, monkeypatch):
    tool, _keys, _limit, args, _kwargs, _rows, calls = source
    replies = iter([{'role': 'assistant', 'tool_calls': [{'id': 'fixture-call', 'function': {
        'name': tool, 'arguments': json.dumps(args)}}]}, {'role': 'assistant', 'content': 'fixture'}])
    sent = []

    def call(_cfg, messages, use_tools):
        sent.append(copy.deepcopy(messages))
        return {'choices': [{'message': next(replies)}]}

    monkeypatch.setattr(chat, '_call_llm', call)
    response = chat.run_chat({}, [{'role': 'user', 'content': 'fixture request'}])
    assert len(calls) == 1 and response['rounds'] == 2
    assert response['trace'][0]['status'] == 'partial'
    message = next(item for item in sent[1] if item['role'] == 'tool')
    envelope = json.loads(message['content'])
    assert isinstance(envelope['data'], list)
    assert envelope['status'] == 'partial'


def test_http_news_does_not_inherit_tool_projection(monkeypatch):
    import app
    rows = [{'新闻标题': 'fixture title', '新闻内容': 'fixture body', '新闻链接': 'https://example.test/story'}]
    monkeypatch.setattr(ai_tools.astock, 'stock_news', lambda *args, **kwargs: rows)
    ai_tools.exec_tool('query_news', {'code': '000001'})
    assert app.news(code='000001', limit=15) == {'data': rows}
    assert 'adapter_coverage' not in rows[0]


def test_http_reports_does_not_inherit_tool_projection(monkeypatch):
    import app
    rows = [{'title': 'fixture title', 'infoCode': 'fixture-id'}]
    monkeypatch.setattr(ai_tools.astock, 'eastmoney_reports', lambda *args, **kwargs: rows)
    monkeypatch.setattr(ai_tools.astock, 'pdf_url', lambda code: 'https://example.test/fixture.pdf')
    ai_tools.exec_tool('query_reports', {'code': '000001'})
    payload = app.reports(code='000001', pages=1)
    assert payload == {'data': [{'title': 'fixture title', 'infoCode': 'fixture-id', 'pdfUrl': 'https://example.test/fixture.pdf'}]}
    assert 'adapter_coverage' not in rows[0]
