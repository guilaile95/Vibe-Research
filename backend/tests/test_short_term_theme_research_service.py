"""Actual registered API + synthetic immutable receipts; outbound and writes blocked."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import socket

import httpx
import pytest
import app
from fact_lake_store import FactLake, initialize_fact_lake
import shortline_research_archive as pool_archive
import short_term_theme_capture as capture
import short_term_theme_research_service as service
from test_short_term_theme_research import DAYS, pages
from test_shortline_research import metadata, raw_pool, poolrow


def seed(lake, pool_transform=None):
    for index, day in enumerate(DAYS):
        codes = ['000001', '000002'] if index < 4 else ['000001', '000003']
        rows = [poolrow(code, 2 if code == '000001' else 1) for code in codes]
        for kind, items in [('limit_up', rows), ('broken', []), ('limit_down', [])]:
            meta = metadata(kind, day)
            if pool_transform:
                pool_transform(meta)
            pool_archive.persist_capture(lake, raw_pool(items, day), meta)
        themes = pages(day)
        source = themes[0]['data']
        source['info'] = [dict(source['info'][0], code=code, reason_type='芯片+半导体' if code == '000001' else '昨日题材' if code == '000002' else '新题材') for code in codes]
        source['page']['total'] = len(codes)
        capture.store_ths_theme_capture(lake, [json.dumps(themes[0]).encode()], trade_date=day, captured_at=day+'T08:00:00Z', fixture=True)
    raw = json.dumps({'data': {'sz000001': {'qfqday': [[day, '10', str(10 + i), '15', '9', '100'] for i, day in enumerate(DAYS)]}}}).encode()
    capture.store_tencent_forward_capture(lake, raw, stock_code='000001', trade_date=DAYS[-1], captured_at=DAYS[-1]+'T08:00:00Z', fixture=True)


def tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def public_golden(value):
    result = copy.deepcopy(value)
    # Raw IDs and receipt times have separate assertions; synthetic UI golden is
    # intentionally content-address-agnostic and contains no real local paths.
    for day in result['projection']['days']:
        day['source'] = {'synthetic_fixture': True}
    for item in result['projection']['lineage']:
        item['source'] = {'synthetic_fixture': True}
    return result


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path/'private'))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)


@pytest.fixture
def http_get(monkeypatch):
    loop = asyncio.new_event_loop()
    def forbidden(*args, **kwargs): raise AssertionError('external effects forbidden')
    for name in ('connect', 'connect_ex'): monkeypatch.setattr(socket.socket, name, forbidden)
    for name in ('create_connection', 'getaddrinfo'): monkeypatch.setattr(socket, name, forbidden)
    for name in ('store_observation', 'store_normalization', 'stage_canonical_publication', 'commit_canonical_publication', 'append_reconciliation', 'publish_canonical_artifact'):
        monkeypatch.setattr(FactLake, name, forbidden)
    async def get(path, headers=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://testserver') as client:
            return await client.get(path, headers=headers)
    yield lambda path, headers=None: loop.run_until_complete(get(path, headers))
    loop.run_until_complete(loop.shutdown_asyncgens()); loop.close()


@pytest.fixture
def archive(monkeypatch, tmp_path):
    root = tmp_path/'archive'; lake = initialize_fact_lake(root); seed(lake)
    monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(root))
    return root, lake


def test_real_archive_registered_api_golden_immutable(archive, http_get):
    root, _ = archive; before = tree(root)
    response = http_get('/api/market/theme-research?trade_date='+DAYS[-1])
    assert response.status_code == 200
    result = response.json()['data']
    assert result['status'] == 'complete', result
    assert tree(root) == before
    assert result['projection']['days'][0]['source']['themes'][0]['raw_payload_hash'].startswith('sha256:')
    assert result['projection']['days'][0]['source']['pool'][0]['observation_id']
    expected = json.loads((Path(__file__).parent/'fixtures/theme-research-golden.json').read_text())
    assert public_golden(result) == expected


def test_unconnected_and_query_whitelist(http_get):
    path = '/api/market/theme-research?trade_date='+DAYS[-1]
    assert http_get(path).json()['data']['reason_codes'] == ['ARCHIVE_NOT_CONNECTED']
    for suffix in ['&root=/tmp/private', '&as_of=2020-01-01', '&refresh=1', '&trade_date='+DAYS[-1]]:
        assert http_get(path+suffix).status_code == 422
    assert http_get('/api/market/theme-research?trade_date=2026-09-26').json()['data']['reason_codes'] == ['CALENDAR_WINDOW_UNAVAILABLE']


def test_snapshot_change_no_partial_result(archive, http_get, monkeypatch):
    from fact_lake_store import FactLakeSnapshot, FactLakeBusyError
    def changed(self): raise FactLakeBusyError('private secret path')
    monkeypatch.setattr(FactLakeSnapshot, 'assert_unchanged', changed)
    result = http_get('/api/market/theme-research?trade_date='+DAYS[-1]).json()['data']
    assert result['projection'] is None and result['reason_codes'] == ['ARCHIVE_BUSY']
    assert 'secret' not in json.dumps(result)


def test_bad_raw_hash_fails_closed(archive, http_get):
    root, lake = archive
    receipts = lake.list_observations(dataset_id=capture.THEME_DATASET, start_trade_date=DAYS[-1], end_trade_date=DAYS[-1])
    (root / receipts[0].blob_relpath).write_bytes(b'{}')
    result = http_get('/api/market/theme-research?trade_date='+DAYS[-1]).json()['data']
    assert result['projection'] is None and result['reason_codes'] == ['ARCHIVE_VALIDATION_FAILED']


def test_real_preclose_pools_with_postclose_themes_remain_unknown(monkeypatch, tmp_path):
    root = tmp_path/'preclose'; lake = initialize_fact_lake(root)
    seed(lake, lambda meta: meta.update(captured_at=meta['trade_date']+'T06:00:00Z'))
    monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(root))
    result = service.query_theme_research(DAYS[-1])
    assert result['status'] == 'unavailable'
    assert all(d['limit_up'] is None for d in result['projection']['days'])


@pytest.mark.parametrize('kind', ['broken', 'limit_down'])
def test_real_synthetic_outcome_mix_fails_closed(kind, monkeypatch, tmp_path):
    root = tmp_path/'mixed'; lake = initialize_fact_lake(root)
    seed(lake, lambda meta: meta.update(fixture=False) if meta['kind'] == kind else None)
    monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(root))
    result = service.query_theme_research(DAYS[-1])
    assert result['projection'] is None
    assert result['reason_codes'] == ['ARCHIVE_VALIDATION_FAILED']


def test_full_page_unavailable_fixtures_match_actual_registered_api(http_get):
    fixture = json.loads((Path(__file__).parents[2]/'frontend/tests/fixtures/theme-research-unavailable.json').read_text())
    assert set(fixture) == {'2026-07-31', '2026-10-08'}
    for day, expected in fixture.items():
        response = http_get('/api/market/theme-research?trade_date='+day)
        assert response.status_code == 200
        assert response.json()['data'] == expected


def test_sibling_shortline_full_page_fixtures_match_actual_router(http_get, monkeypatch):
    from fastapi import FastAPI
    from shortline_research_router import router
    isolated_app = FastAPI(); isolated_app.include_router(router)
    monkeypatch.setattr(app, 'app', isolated_app)
    fixture = json.loads((Path(__file__).parents[2]/'frontend/tests/fixtures/shortline-research-unavailable.json').read_text())
    assert set(fixture) == {'2026-07-31', '2026-10-08'}
    for day, expected in fixture.items():
        response = http_get('/api/market/shortline-research?trade_date='+day)
        assert response.status_code == 200
        assert response.json()['data'] == expected
