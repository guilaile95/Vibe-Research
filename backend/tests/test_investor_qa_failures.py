"""Synthetic CNInfo failure/empty contracts through existing API and AI paths."""
import pytest
import requests

import ai_tools
import app
import astock

SAFE = "数据获取失败，请稍后重试。"
VALID = {'rows': [{'mainContent': 'fixture question', 'attachedContent': None}]}


class Response:
    def __init__(self, payload, *, status_error=False):
        self.payload, self.status_error = payload, status_error
    def raise_for_status(self):
        if self.status_error:
            raise requests.HTTPError('https://private.invalid/?token=fixture-secret')
    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


@pytest.fixture
def provider(monkeypatch):
    state = {'lookup': {'data': [{'secid': 'fixture-org'}]}, 'page': VALID, 'calls': [], 'status_error': False}
    def post(url, **kwargs):
        state['calls'].append((url, kwargs))
        value = state['lookup'] if url.endswith('queryKeyboardInfo') else state['page']
        if isinstance(value, requests.RequestException):
            raise value
        return Response(value, status_error=state['status_error'])
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(app, '_DC_CACHE', app.TTLCache())
    return state


@pytest.mark.parametrize('target,value', [
    ('lookup', requests.Timeout('fixture-secret')), ('lookup', ValueError('fixture-secret')),
    ('lookup', {}), ('lookup', None), ('lookup', {'data': None}), ('lookup', {'data': []}),
    ('lookup', {'data': [None]}), ('lookup', {'data': [{}]}),
    ('lookup', {'data': [{'secid': ''}]}),
    ('page', requests.Timeout('fixture-secret')), ('page', ValueError('fixture-secret')),
    ('page', {}), ('page', {'rows': None}), ('page', {'rows': {}}),
    ('page', {'rows': [None]}), ('page', {'rows': [{}]}),
    ('page', {'rows': [{'mainContent': 123}]}),
    ('page', {'rows': [{'mainContent': 'fixture', 'attachedContent': {}}]}),
    ('page', {'rows': [{'mainContent': 'fixture', 'pubDate': {}}]}),
])
def test_failures_are_safe_not_cached_and_recover(provider, target, value):
    provider[target] = value
    with pytest.raises(app.HTTPException) as error:
        app.investor_qa('000001')
    assert error.value.status_code == 502
    model = ai_tools.exec_tool('query_investor_qa', {'code': '000001'})
    # The AI boundary deliberately normalizes provider failures, not empty data.
    assert model == {'error': SAFE}
    assert 'fixture-secret' not in str(model)
    before = len(provider['calls'])
    provider['lookup'], provider['page'] = {'data': [{'secid': 'fixture-org'}]}, VALID
    assert app.investor_qa('000001')['data'][0]['question'] == 'fixture question'
    assert len(provider['calls']) == before + 2


def test_http_failure_never_becomes_empty(provider):
    provider['status_error'] = True
    with pytest.raises(RuntimeError, match='投资者互动数据暂不可用'):
        astock.investor_qa('000001')
    assert 'fixture-secret' not in ai_tools.exec_tool('query_investor_qa', {'code': '000001'})['error']


def test_resolved_empty_page_is_cached(provider):
    provider['page'] = {'rows': []}
    assert app.investor_qa('000001') == {'data': []}
    provider['page'] = VALID
    assert app.investor_qa('000001') == {'data': []}
    assert len(provider['calls']) == 2


@pytest.mark.parametrize('extra', [{}, {'attachedContent': None}, {'attachedContent': ''}, {'attachedContent': 'fixture answer', 'attachedAuthor': None, 'companyShortName': None}])
def test_optional_fields_and_unanswered_questions_remain_valid(provider, extra):
    provider['page'] = {'rows': [{'mainContent': 'fixture question', **extra}]}
    row = astock.investor_qa('000001')[0]
    assert row['answer'] == extra.get('attachedContent')
    assert row['ask_time'] == ''


@pytest.mark.parametrize('code', ['600519', '688981', '900901', '920982'])
def test_route_unchanged_no_source_match_is_unavailable(provider, code):
    provider['lookup'] = {'data': []}
    with pytest.raises(RuntimeError, match='投资者互动数据暂不可用'):
        astock.investor_qa(code)
    assert len(provider['calls']) == 1
    assert provider['calls'][0][0].startswith('https://irm.cninfo.com.cn/')
