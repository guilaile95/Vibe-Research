"""Provider raw → existing FactLake → registered read API contract, entirely offline."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import socket

import httpx
import pytest
from fastapi import FastAPI
from fact_lake_store import initialize_fact_lake, open_existing_fact_lake_snapshot
import public_research_adapters as A
import public_research_archive as archive
import public_research_contract as C
from public_research_router import router
from public_research_fixtures import raw, seed, CAPTURED

NOW = datetime(2026, 10, 1, 13, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw):
        raise AssertionError('public research tests must not use network')
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)


def normalized(source, subject=None, body=None, captured=CAPTURED):
    subject = subject or C.SOURCES[source]['subjects'][0]
    return A.normalize(body if body is not None else raw(source, subject), source, subject, captured, now=NOW)


@pytest.mark.parametrize('source', list(C.SOURCES))
def test_all_producers_archive_and_replay(tmp_path, source):
    lake = initialize_fact_lake(tmp_path / 'lake')
    subject = C.SOURCES[source]['subjects'][0]
    calls = []
    def transport(url, **kw):
        calls.append((url, kw))
        return 200, raw(source, subject)
    receipt = archive.collect(lake, source, subject, transport=transport, fixture=True)
    assert receipt['fixture'] is True
    assert calls == [(C.request_spec(source, subject), {'max_bytes': C.MAX_BYTES, 'timeout': 20, 'allow_redirects': False})]
    stored = lake.get_observation(receipt['observation_id'])
    result = archive.replay(lake, stored)
    assert result['rows'] and result['fixture']
    assert result['evidence']['raw_payload_hash'] == receipt['raw_payload_hash']
    assert result['evidence']['point_in_time_claim'] == 'NONE'


def test_quote_direction_units_and_unquoted():
    poly = normalized('public_polymarket')['rows']
    assert [(r['outcome'], r['value'], r['outcome_id']) for r in poly] == [('No', .35, 'synthetic-no-token'), ('Yes', .65, 'synthetic-yes-token')]
    quote = normalized('public_kalshi')['rows'][0]
    assert quote['value'] == pytest.approx(.42) and quote['price_convention'] == 'yes_bid_ask_midpoint_dollars'
    assert quote['volume_24h'] == 0 and quote['open_interest'] == 1000
    data = json.loads(raw('public_kalshi', 'markets'))
    for key in ('yes_bid_dollars', 'yes_ask_dollars', 'last_price_dollars'):
        data['markets'][0].pop(key)
    data['markets'][0]['yes_bid'] = 40  # legacy cents must never masquerade as dollars
    q = normalized('public_kalshi', body=C.canonical(data).encode())['rows'][0]
    assert q['value'] is None and q['objective_probability'] is None and 'PRICE_MISSING' in q['missing']
    data['markets'][0]['status'] = 'settled'
    assert normalized('public_kalshi', body=C.canonical(data).encode())['rows'][0]['status'] == 'closed'


def test_industry_semantics_and_dedup():
    tw = normalized('tw_monthly_revenue')['rows'][0]
    assert tw['currency'] == 'TWD' and tw['reporting_period'] == '2026-08'
    assert tw['source_series_yoy_pct'] == pytest.approx(20) and tw['yoy_pct'] is None
    assert tw['comparison_period'] == '2025-08'
    dram = normalized('dram_spot_thermo')['rows'][0]
    assert dram['grade'] is None and dram['is_hbm_price'] is False and 'EXACT_GRADE_UNKNOWN' in dram['missing']
    commodity = normalized('cn_commodity_futures')['rows'][0]
    assert commodity['contract_id'] == 'CU0' and commodity['currency'] == 'CNY' and commodity['delivery_month'] is None
    assert commodity['change_pct'] is None and commodity['exchange'] == 'SHFE'
    job = normalized('hiring_anchor_signal')['rows'][0]
    assert job['value'] == 1 and job['deduplicated_count'] == 1 and job['fulfilled_hires'] is None
    assert job['listings'][0]['source_time'] == '2026-09-30T08:00:00.000000Z'


@pytest.mark.parametrize('value', ['2026-02-30T00:00:00Z', '2026-10-01T24:00:00Z', '2026-10-01T00:00:00+08:60', '2026-10-01T00:00:00+24:00', '20261001T00:00:00Z', '2026-10-01 00:00:00Z', '2026-10-01T00:00:00.1234567Z'])
def test_strict_timestamp(value):
    with pytest.raises(ValueError): C.stamp(value)


@pytest.mark.parametrize('value', [True, float('inf'), float('nan'), '-1', 'NaN', 1e300])
def test_bad_numeric(value):
    with pytest.raises(ValueError): C.number(value)


@pytest.mark.parametrize('change', ['future', 'conflict', 'wrong_issuer', 'bool', 'zero'])
def test_taiwan_invalid_comparability(change):
    data = json.loads(raw('tw_monthly_revenue', '2383'))
    if change == 'future': data['data'][1]['date'] = '2026-12-01'
    if change == 'conflict': data['data'].append({**data['data'][1], 'revenue': 9})
    if change == 'wrong_issuer': data['data'][1]['stock_id'] = '9999'
    if change == 'bool': data['data'][1]['revenue'] = True
    if change == 'zero':
        data['data'][0]['revenue'] = 0
        row = normalized('tw_monthly_revenue', body=C.canonical(data).encode())['rows'][0]
        assert row['source_series_yoy_pct'] is None
    else:
        with pytest.raises(ValueError): normalized('tw_monthly_revenue', body=C.canonical(data).encode())


def test_bounds_invalid_json_and_future():
    for body in (b'{"jobs":[],"jobs":[]}', b'{"jobs":NaN}', b'x' * (C.MAX_BYTES + 1)):
        with pytest.raises(ValueError): normalized('hiring_anchor_signal', body=body)
    with pytest.raises(ValueError): normalized('public_polymarket', captured='2030-01-01T00:00:00Z')
    with pytest.raises(ValueError): C.request_spec('hiring_anchor_signal', 'ashby:../../secret')
    with pytest.raises(ValueError): normalized('cn_commodity_futures', body=b'eval(alert(1));')


def test_http_failure_archived_without_error_disclosure(tmp_path):
    lake = initialize_fact_lake(tmp_path / 'lake')
    receipt = archive.persist_capture(lake, b'private URL token error', 'public_kalshi', 'markets', CAPTURED, fixture=True, http_status=402)
    result = archive.replay(lake, lake.get_observation(receipt['observation_id']))
    assert result['status'] == 'unavailable' and result['rows'] == []
    assert 'token' not in C.canonical(result)


def request(url, method='GET'):
    from app import app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8900') as client:
            return await client.request(method, url)
    return asyncio.run(run())


def test_registered_api_to_frozen_lake_all_sources(tmp_path, monkeypatch):
    root = tmp_path / 'lake'; seed(initialize_fact_lake(root)); monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(root))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    for source in C.SOURCES:
        response = request('/api/public-research?source_id=' + source)
        assert response.status_code == 200
        data = response.json()['data']
        assert data['fixture'] is True and data['blocks'] and not data['missing_subjects'], data
        assert data['ingestion_enabled'] is False and data['schedule_enabled'] is False
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert before == after
    assert 'app.include_router(public_research_router.router)' in (Path(__file__).parents[1] / 'app.py').read_text(encoding="utf-8")


@pytest.mark.parametrize('query', ['source_id=private', 'source_id=public_kalshi&path=/etc/passwd', 'source_id=public_kalshi&url=https://localhost', 'source_id=public_kalshi&source_id=public_polymarket'])
def test_route_rejects_override(query):
    assert request('/api/public-research?' + query).status_code == 422


def test_no_write_route_and_missing(monkeypatch):
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)
    assert request('/api/public-research?source_id=public_kalshi', 'POST').status_code == 405
    assert request('/api/public-research?source_id=public_kalshi').json()['data']['status'] == 'missing'


def test_strict_golden_registered_api(tmp_path, monkeypatch):
    # Frozen time only affects query freshness; captured raw and local receipt order remain validated.
    root = tmp_path / 'lake'
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(archive, 'datetime', Clock)
    seed(initialize_fact_lake(root)); monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(root))
    actual = {source: request('/api/public-research?source_id=' + source).json()['data'] for source in C.SOURCES}
    actual = golden_stable(actual)
    target = Path(__file__).parents[2] / 'frontend/tests/fixtures/public-research.golden.json'
    assert actual == json.loads(target.read_text(encoding="utf-8")), 'Public-source golden differs from registered API; regenerate deliberately and review'


def golden_stable(value):
    """Remove only nondeterministic local receipt UUID/time; keep all research values/guards."""
    import copy
    value = copy.deepcopy(value)
    for source in value.values():
        for block in source['blocks']:
            block['evidence']['observation_id'] = 'synthetic-golden-receipt-' + block['subject']
            block['evidence']['locally_received_at'] = '2026-10-12T12:00:00.000000Z'
    return value


@pytest.mark.parametrize('source,body', [('public_polymarket', b'[null]'), ('public_kalshi', b'{"markets":[null]}'), ('tw_monthly_revenue', b'{"data":[null]}'), ('dram_spot_thermo', b'{"ddr5":[null]}'), ('hiring_anchor_signal', b'{"jobs":[null]}')])
def test_malformed_rows_preserve_failed_raw_receipt(tmp_path, source, body):
    lake = initialize_fact_lake(tmp_path / 'lake')
    receipt = archive.persist_capture(lake, body, source, C.SOURCES[source]['subjects'][0], CAPTURED, fixture=True)
    assert receipt['status'] == 'unavailable'
    assert lake.read_payload(receipt['observation_id']) == body
    assert archive.replay(lake, lake.get_observation(receipt['observation_id']))['rows'] == []


def test_conflicting_listing_and_direction_arrays():
    data = json.loads(raw('hiring_anchor_signal', 'greenhouse:lightmatter'))
    data['jobs'][1]['title'] = 'Changed title'
    with pytest.raises(ValueError): normalized('hiring_anchor_signal', body=C.canonical(data).encode())
    data = json.loads(raw('public_polymarket', 'markets'))
    data[0]['clobTokenIds'] = '["same", "same"]'
    with pytest.raises(ValueError): normalized('public_polymarket', body=C.canonical(data).encode())
    data[0]['clobTokenIds'] = '[true, "other"]'
    with pytest.raises(ValueError): normalized('public_polymarket', body=C.canonical(data).encode())


def test_stale_time_unknown_question_id_and_future_source():
    data = json.loads(raw('public_polymarket', 'markets')); data[0].pop('questionID')
    got = normalized('public_polymarket', body=C.canonical(data).encode())
    assert got['rows'][0]['question_id'] is None and got['rows'][0]['market_id'] == 'synthetic-question-1'
    data[0]['updatedAt'] = '2026-10-01T12:00:00.000001Z'
    with pytest.raises(ValueError): normalized('public_polymarket', body=C.canonical(data).encode())
    got = A.normalize(raw('public_polymarket', 'markets'), 'public_polymarket', 'markets', CAPTURED,
                      now=datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert got['rows'][0]['stale'] is True


def test_exact_instant_latest_selection_and_ambiguity(tmp_path, monkeypatch):
    root = tmp_path / 'lake'; lake = initialize_fact_lake(root); monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(root))
    source = 'hiring_anchor_signal'; subject = C.SOURCES[source]['subjects'][0]
    old = archive.persist_capture(lake, raw(source, subject), source, subject, '2026-10-01T12:00:00.000001Z', fixture=True)
    new = archive.persist_capture(lake, b'{"jobs":[]}', source, subject, '2026-10-01T20:00:00.000002+08:00', fixture=True)
    result = archive.query_source(source)
    assert result['blocks'][0]['evidence']['observation_id'] == new['observation_id'] != old['observation_id']
    archive.persist_capture(lake, raw(source, subject), source, subject, '2026-10-01T12:00:00.000002Z', fixture=True)
    assert archive.query_source(source)['reason_codes'] == ['ARCHIVE_VALIDATION_FAILED']


def test_replay_passes_remaining_byte_budget_before_read(tmp_path, monkeypatch):
    lake = initialize_fact_lake(tmp_path / 'lake'); source = 'public_kalshi'; subject = 'markets'
    receipt = archive.persist_capture(lake, raw(source, subject), source, subject, CAPTURED, fixture=True)
    read = lake.read_payload; seen = []
    def bounded_read(identifier, *, max_payload_bytes):
        seen.append(max_payload_bytes)
        return read(identifier, max_payload_bytes=max_payload_bytes)
    monkeypatch.setattr(lake, 'read_payload', bounded_read)
    with pytest.raises(Exception): archive.replay(lake, lake.get_observation(receipt['observation_id']), max_bytes=3)
    assert seen == [3]


@pytest.mark.parametrize('bid,ask,last,status,expected,convention', [
    ('0', '0', None, 'open', None, 'unquoted'),
    ('0', '0', '0', 'open', None, 'unquoted'),
    ('0', '0', '.4', 'open', .4, 'yes_last_trade_dollars'),
    ('0', '.4', None, 'open', .2, 'yes_bid_ask_midpoint_dollars'),
    (None, '.4', '.3', 'open', .3, 'yes_last_trade_dollars'),
    ('0', '0', None, 'closed', 0, 'yes_bid_ask_midpoint_dollars'),
])
def test_kalshi_zero_or_missing_book(bid, ask, last, status, expected, convention):
    data = json.loads(raw('public_kalshi', 'markets'))
    def fixed(value): return '0' + value if value and value.startswith('.') else value
    data['markets'][0].update(yes_bid_dollars=fixed(bid), yes_ask_dollars=fixed(ask), last_price_dollars=fixed(last), status=status)
    row = normalized('public_kalshi', body=C.canonical(data).encode())['rows'][0]
    assert row['value'] == expected and row['price_convention'] == convention
    if status != 'closed' and (bid is None or ask == '0'):
        assert 'AMBIGUOUS_OR_MISSING_BOOK' in row['missing']
    assert row['bid'] == (None if bid is None else float(bid))
    assert row['ask'] == (None if ask is None else float(ask))


def test_pinned_upstream_license_notice_exact_git_blob_bytes():
    import hashlib
    root = Path(__file__).parents[2] / 'docs/third-party'
    for name, expected in [('vibe-astock-LICENSE', 'd645695673349e3947e8e5ae42332d0ac3164cd7'),
                           ('vibe-astock-NOTICE', 'fb76b6b1e9874e440d543814ee56217bee223917')]:
        body = (root / name).read_bytes()
        assert hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == expected
