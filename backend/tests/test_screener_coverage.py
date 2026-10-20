"""Requested batch and observed sample coverage are not whole-artifact coverage."""
import csv
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import research_data_plane as rdp
import screener_router
import screener_service as svc
from screener_models import ScreenerEvaluateIn
from test_screener_latest_window import seed, body


def api(body):
    app = FastAPI(); app.include_router(screener_router.router)
    response = TestClient(app).post('/api/screener/evaluate', json=body.model_dump())
    assert response.status_code == 200, response.text
    return response.json()


def test_all_missing_code_is_not_available_source_or_dataset_coverage(tmp_path, monkeypatch):
    _, manifest = seed(tmp_path, monkeypatch)
    result = api(body(['000002']))
    assert result['status'] == result['research_data']['status'] == 'unavailable'
    assert result['research_data']['coverage']['code_count'] == 2  # explicitly whole artifact
    assert result['batch_coverage'] == dict(requested_count=1, with_data_count=0, empty_count=1,
        failed_count=0, stale_count=0, fully_evaluable_count=0, missing_condition_count=0, unavailable_count=1)
    observed = result['unavailable'][0]['data_coverage']
    assert observed == dict(freshness='unknown', status='empty', returned_rows=0, start=None, end=None,
        snapshot_id=manifest['snapshot_id'], artifact_sha256=manifest['artifact_sha256'], cutoff=manifest['coverage_end'])
    assert result['unavailable'][0]['matched'] is None


def test_mixed_requested_coverage_counts_only_requested_symbols(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    result = api(body(['000001', '000002']))
    assert result['research_data']['status'] == 'partial'
    coverage = result['batch_coverage']
    assert coverage['requested_count'] == 2 and coverage['with_data_count'] == 1
    assert coverage['empty_count'] == 1 and coverage['fully_evaluable_count'] == 1
    observed = result['rejected'][0]['data_coverage']
    assert observed['returned_rows'] == 120
    assert observed['start'] == '2026-01-31' and observed['end'] == '2026-05-30'
    assert result['research_data']['coverage']['row_count'] == 300


@pytest.mark.parametrize('failed', ['000001', '000003'])
def test_batch_source_partial_independent_of_first_sorted_failure(tmp_path, monkeypatch, failed):
    seed(tmp_path, monkeypatch)
    original = rdp.query_daily_bars
    def query(**kwargs):
        if kwargs['code'] == failed: raise RuntimeError('synthetic')
        return original(**kwargs)
    monkeypatch.setattr(rdp, 'query_daily_bars', query)
    result = api(body(['000001', '000003']))
    assert result['status'] == result['research_data']['status'] == 'partial'
    assert result['research_data']['coverage']['code_count'] == 2
    assert result['batch_coverage']['with_data_count'] == result['batch_coverage']['failed_count'] == 1
    missing = result['unavailable'][0]['data_coverage']
    assert missing['returned_rows'] is None and missing['status'] == 'unavailable'
    assert missing['snapshot_id'] is None and missing['end'] is None


def test_all_fetch_failures_have_unknown_count_not_observed_empty(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    monkeypatch.setattr(rdp, 'query_daily_bars', lambda **kwargs: (_ for _ in ()).throw(RuntimeError('synthetic')))
    result = api(body(['000001', '000003']))
    assert result['research_data']['status'] == 'unavailable'
    assert result['research_data']['coverage'] is None
    assert result['batch_coverage']['failed_count'] == 2
    assert result['batch_coverage']['empty_count'] == 0


def test_condition_unknown_does_not_change_explicit_and_false(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, days=30)
    request = ScreenerEvaluateIn(codes=['000001'], conditions=[{'id':'price_lt_sma20'}, {'id':'price_gt_sma60'}])
    result = api(request)
    assert result['rejected'][0]['matched'] is False
    assert result['rejected'][0]['condition_results'][1]['passed'] is None
    assert result['batch_coverage']['with_data_count'] == 1
    assert result['batch_coverage']['fully_evaluable_count'] == 0
    assert result['batch_coverage']['missing_condition_count'] == 1
    assert result['batch_coverage']['unavailable_count'] == 0


def test_global_cutoff_is_not_reported_as_stock_last_date(tmp_path, monkeypatch):
    root, _ = seed(tmp_path, monkeypatch)
    source = tmp_path/'synthetic.csv'
    rows = list(csv.reader(source.open()))
    source.write_text('\n'.join(','.join(r) for r in rows if r[0] != '000003' or r[1] <= '2026-01-30')+'\n')
    rdp.import_csv(source, root=root)
    result = api(body(['000003']))
    observed = (result['matched'] + result['rejected'] + result['unavailable'])[0]['data_coverage']
    assert observed['end'] == '2026-01-30'
    assert observed['cutoff'] == result['research_data']['as_of'] == '2026-05-30'
    assert observed['returned_rows'] == 30


def test_stale_tail_matches_full_market_and_never_current_match(tmp_path, monkeypatch):
    root, _ = seed(tmp_path, monkeypatch)
    source = tmp_path/'synthetic.csv'
    rows = list(csv.reader(source.open()))
    source.write_text('\n'.join(','.join(r) for r in rows if r[0] != '000003' or r[1] <= '2026-03-21')+'\n')
    manifest = rdp.import_csv(source, root=root)
    result = api(body(['000001', '000003']))
    stale = result['unavailable'][0]
    assert stale['code'] == '000003' and stale['matched'] is None
    assert stale['technical_status'] == stale['data_coverage']['freshness'] == 'stale'
    condition = stale['condition_results'][0]
    assert condition['evaluable'] is False and condition['passed'] is None
    assert condition['evidence']['reason'] == 'STALE'
    assert condition['evidence']['last_known']['passed'] is True
    assert result['batch_coverage']['stale_count'] == 1
    assert result['batch_coverage']['fully_evaluable_count'] == 1
    assert result['status'] == 'partial'
    assert result['rejected'][0]['data_coverage']['freshness'] == 'current'
    full = rdp.query_full_market(latest=True)
    assert next(r for r in full['rows'] if r['code'] == '000003')['status'] == 'stale'
    # Explicit pinned historical cutoff remains current, regardless of wall clock.
    old = svc.evaluate_one_stock('000003', body().conditions, snapshot_id=manifest['snapshot_id'], cutoff='2026-03-21')
    assert old['bucket'] == 'matched'
    assert old['research_data']['_screener_sample']['freshness'] == 'current'


def test_stale_insufficient_history_keeps_stale_count(tmp_path, monkeypatch):
    root, _ = seed(tmp_path, monkeypatch)
    source = tmp_path/'synthetic.csv'
    rows = list(csv.reader(source.open()))
    source.write_text('\n'.join(','.join(r) for r in rows if r[0] != '000003' or r[1] <= '2026-01-05')+'\n')
    rdp.import_csv(source, root=root)
    result = api(body(['000003']))
    assert result['unavailable'][0]['technical_status'] == 'stale'
    assert result['batch_coverage']['stale_count'] == 1
    assert result['batch_coverage']['fully_evaluable_count'] == 0
    assert result['status'] == 'unavailable'


def test_stale_classifier_never_promotes_last_known_pass():
    assert svc.classify_stock([{'evaluable': True, 'passed': True}], 'stale') == 'unavailable'
