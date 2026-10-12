"""Synthetic immutable-snapshot lookback acceptance; no external data."""
import csv
import json
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import research_data_plane as rdp
import screener_router
import screener_service as svc
from screener_models import ScreenerEvaluateIn


def seed(tmp_path, monkeypatch, days=150, revised=False):
    root = tmp_path / 'rdp'
    monkeypatch.setenv('VIBE_RESEARCH_RESEARCH_DATA_DIR', str(root))
    source = tmp_path / 'synthetic.csv'
    with source.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['code', 'trade_date', 'open', 'high', 'low', 'close', 'volume'])
        for i in range(days):
            close = (10 + i / 10 if i < 120 else 1.0) + (1 if revised else 0)
            for code in ['000001', '000003']:
                w.writerow([code, (date(2026, 1, 1) + timedelta(days=i)).isoformat(), close, close+1, close-.5, close, 1000+i])
    return root, rdp.import_csv(source, root=root, imported_at='2026-06-01T00:00:00Z')


def body(codes=None):
    return ScreenerEvaluateIn(codes=codes or ['000001'], conditions=[{'id': 'price_gt_sma20'}])


def test_150_bars_latest_window_corrects_oldest_false_match(tmp_path, monkeypatch):
    root, _ = seed(tmp_path, monkeypatch)
    old = rdp.query_daily_bars(root=root, code='000001', limit=120)
    assert old['rows'][-1]['trade_date'] == '2026-04-30'
    assert old['next_offset'] == 120
    assert 'latest_window' not in old['replay_receipt']['parameters']
    assert old == rdp.query_daily_bars(root=root, code='000001', limit=120, latest_window=False)
    app = FastAPI(); app.include_router(screener_router.router)
    result = TestClient(app).post('/api/screener/evaluate', json=body().model_dump()).json()
    assert result['matched'] == []
    assert result['rejected'][0]['trade_date'] == '2026-05-30'
    assert result['rejected'][0]['condition_results'][0]['passed'] is False


@pytest.mark.parametrize('days', [1, 19, 20, 30, 119, 120, 121, 150])
def test_bounded_chronological_rows_and_missing_code(tmp_path, monkeypatch, days):
    root, manifest = seed(tmp_path, monkeypatch, days=days)
    result = rdp.query_daily_bars(root=root, code='000001', limit=120, latest_window=True)
    rows = result['rows']
    assert len(rows) == min(days, 120)
    assert [r['trade_date'] for r in rows] == sorted(set(r['trade_date'] for r in rows))
    assert rows[-1]['trade_date'] == manifest['coverage_end']
    assert rdp.query_daily_bars(root=root, code='000002', latest_window=True)['rows'] == []


def test_cutoff_replay_and_generation_swap(tmp_path, monkeypatch):
    root, first = seed(tmp_path, monkeypatch)
    before = rdp.query_daily_bars(root=root, code='000001', date_to='2026-04-10', limit=120, latest_window=True)
    assert before['rows'][-1]['trade_date'] == '2026-04-10'
    seed(tmp_path, monkeypatch, revised=True)
    receipt = before['replay_receipt']
    replay = rdp.query_daily_bars(root=root, snapshot_id=receipt['snapshot_id'], **receipt['parameters'])
    assert replay == before
    assert receipt['parameters']['latest_window'] is True
    assert receipt['snapshot_id'] == first['snapshot_id']
    # Existing fail-closed path, no current-generation fallback.
    monkeypatch.setattr(rdp, '_snapshot_path', lambda *a: tmp_path/'absent.json')
    with pytest.raises(rdp.ResearchDataPlaneUnavailableError):
        rdp.query_daily_bars(root=root, snapshot_id=receipt['snapshot_id'], **receipt['parameters'])


def test_batch_pins_one_snapshot_even_when_current_manifest_changes(tmp_path, monkeypatch):
    root, first = seed(tmp_path, monkeypatch)
    second_source = tmp_path/'revised.csv'
    second_source.write_text((tmp_path/'synthetic.csv').read_text().replace(',1.0,2.0,0.5,1.0,', ',2.0,3.0,1.5,2.0,'))
    original = rdp.query_daily_bars
    seen = []
    def query(**kwargs):
        seen.append((kwargs['snapshot_id'], kwargs['date_to']))
        if len(seen) == 1:
            rdp.import_csv(second_source, root=root)
        return original(**kwargs)
    monkeypatch.setattr(rdp, 'query_daily_bars', query)
    result = svc.evaluate_screener(body(['000001','000003']), max_workers=1)
    assert seen == [(first['snapshot_id'], first['coverage_end'])] * 2
    assert [r['code'] for r in result['rejected']] == ['000001','000003']


@pytest.mark.parametrize('value', ['bad', '2026-02-30', '2026-04-01'])
def test_invalid_or_inconsistent_manifest_cutoff_is_unavailable(tmp_path, monkeypatch, value):
    root, _ = seed(tmp_path, monkeypatch)
    path = root/'manifest.json'
    manifest = json.loads(path.read_text()); manifest['coverage_end'] = value
    path.write_text(json.dumps(manifest))
    result = svc.evaluate_screener(body(['000001','000003']))
    assert result['status'] == 'unavailable'
    assert not result['matched'] and not result['rejected']


def test_mismatched_snapshot_is_per_code_unavailable(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    original = rdp.query_daily_bars
    def query(**kwargs):
        result = original(**kwargs)
        if kwargs['code'] == '000003': result['snapshot_id'] = '0' * 64
        return result
    monkeypatch.setattr(rdp, 'query_daily_bars', query)
    result = svc.evaluate_screener(body(['000001','000003']))
    assert result['status'] == 'partial'
    assert [r['code'] for r in result['rejected']] == ['000001']
    assert [r['code'] for r in result['unavailable']] == ['000003']


def test_overlap_dates_between_codes_allowed_duplicate_observations_rejected(tmp_path, monkeypatch):
    root, _ = seed(tmp_path, monkeypatch)
    result = rdp.query_daily_bars(root=root, limit=120, latest_window=True)
    assert len({(r['trade_date'], r['code']) for r in result['rows']}) == 120
    source = tmp_path/'synthetic.csv'
    lines = source.read_text().splitlines()
    source.write_text('\n'.join(lines + [lines[1]])+'\n')
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match='duplicate observation'):
        rdp.import_csv(source, root=root)


@pytest.mark.parametrize('latest', [None, 1, 'true'])
def test_latest_mode_rejects_non_boolean(tmp_path, monkeypatch, latest):
    root, _ = seed(tmp_path, monkeypatch, days=1)
    with pytest.raises(rdp.ResearchDataPlaneQueryValidationError):
        rdp.query_daily_bars(root=root, latest_window=latest)


@pytest.mark.parametrize("date_to", [None, "2026-12-31"])
def test_future_lower_bound_empty_window_replays_exactly(tmp_path, monkeypatch, date_to):
    root, _ = seed(tmp_path, monkeypatch, days=1)
    before = rdp.query_daily_bars(root=root, code="000001", date_from="2026-06-01",
                                 date_to=date_to, latest_window=True)
    assert before["rows"] == []
    assert before["window_cutoff"] == "2026-01-01"
    receipt = before["replay_receipt"]
    assert receipt["parameters"]["date_to"] == date_to
    assert rdp.query_daily_bars(root=root, snapshot_id=receipt["snapshot_id"],
                                **receipt["parameters"]) == before
