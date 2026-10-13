"""Synthetic provider frames through the actual reader, adapter and consumers."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

import ai_tools
import astock
import chat
import debate


def provider(monkeypatch, size, title_size=5):
    rows = [{'新闻标题': f'{i}:' + '题' * title_size, '发布时间': 'fixture-time', '文章来源': 'fixture'}
            for i in range(size)]
    frame = pd.DataFrame(rows)
    calls = []
    monkeypatch.setattr(astock, '_akshare', lambda: SimpleNamespace(
        stock_news_em=lambda **kwargs: calls.append(kwargs) or frame))
    return rows, frame, calls


def test_source_row_omission_is_not_hidden_by_complete_adapter_window(monkeypatch):
    _rows, _frame, calls = provider(monkeypatch, 20)
    payload = ai_tools.exec_tool('query_news', {'code': '000001'})
    serialized, status, truncated = chat._serialize_tool_result(payload)
    assert (status, truncated) == ('partial', False)
    assert len(payload) == 15 and len(calls) == 1
    assert payload[0]['adapter_coverage']['input_rows'] == 15
    assert payload[0]['adapter_coverage']['omitted_rows'] == 0
    assert payload[0]['source_coverage'] == {
        'scope': 'provider_response_before_requested_limit',
        'provider_response_rows': 20, 'returned_rows': 15,
        'omitted_rows': 5, 'requested_limit': 15, 'total_history_rows': None,
    }
    assert json.loads(serialized)['data'][0]['source_coverage']['omitted_rows'] == 5


@pytest.mark.parametrize('size', [0, 5, 15, 16])
@pytest.mark.parametrize('strict', [False, True])
def test_opt_in_reader_coverage_preserves_requested_limit_and_default_list(monkeypatch, size, strict):
    rows, frame, calls = provider(monkeypatch, size)
    before = frame.copy(deep=True)
    ordinary = astock.stock_news('000001', limit=15, strict=strict)
    window = astock.stock_news('000001', limit=15, strict=strict, with_coverage=True)
    assert ordinary == window['rows'] == rows[:15]
    assert isinstance(ordinary, list)
    assert window['source_coverage']['provider_response_rows'] == size
    assert window['source_coverage']['omitted_rows'] == max(0, size - 15)
    assert window['source_coverage']['total_history_rows'] is None
    assert len(calls) == 2  # One source request per reader invocation, no follow-up fetch.
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize('size', [1, 15])
def test_full_returned_window_does_not_invent_omission_or_history_total(monkeypatch, size):
    provider(monkeypatch, size)
    payload = ai_tools.exec_tool('query_news', {'code': '000001'})
    assert chat._serialize_tool_result(payload)[1:] == ('success', False)
    assert payload[0]['source_coverage']['omitted_rows'] == 0
    assert payload[0]['source_coverage']['total_history_rows'] is None
    assert '不证明历史完整' in payload[0]['note']


def test_missing_provider_response_is_unknown_not_zero_total(monkeypatch):
    monkeypatch.setattr(astock, '_akshare', lambda: SimpleNamespace(stock_news_em=lambda **kwargs: None))
    assert astock.stock_news('000001') == []
    window = astock.stock_news('000001', with_coverage=True)
    assert window['rows'] == []
    assert window['source_coverage']['provider_response_rows'] is None
    assert window['source_coverage']['omitted_rows'] is None
    assert window['source_coverage']['total_history_rows'] is None
    assert ai_tools.exec_tool('query_news', {'code': '000001'}) == []
    with pytest.raises(ValueError):
        astock.stock_news('000001', strict=True, with_coverage=True)


def test_http_keeps_shape_and_requested_window_after_ai_read(monkeypatch):
    import app
    rows, _frame, calls = provider(monkeypatch, 20)
    ai_tools.exec_tool('query_news', {'code': '000001'})
    assert app.news(code='000001', limit=3) == {'data': rows[:3]}
    assert len(calls) == 2
    assert all('source_coverage' not in row for row in rows)


def test_source_coverage_and_partial_status_survive_context_compaction(monkeypatch):
    provider(monkeypatch, 20, title_size=1000)
    payload = ai_tools.exec_tool('query_news', {'code': '000001'})
    serialized, status, truncated = chat._serialize_tool_result(payload)
    assert status == 'partial' and truncated and len(serialized) <= chat._TOOL_RESULT_CAP
    assert json.loads(serialized)['data'][0]['source_coverage'] == payload[0]['source_coverage']
    section = debate._fetch_section(('query_news', {}, 'fixture news', False, True), '000001')
    assert section['status'] == 'partial' and section['truncated'] and not section['ok']
    assert len(section['body']) <= debate._SECTION_CAP
    assert json.loads(section['body'])['data'][0]['source_coverage']['omitted_rows'] == 5
