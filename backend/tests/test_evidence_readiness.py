"""Actual API over temporary archives; synthetic data, no production acquisition."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3

import pytest
import app
import evidence_readiness_router as router
import evidence_readiness_service as service
import next_day_verification as journal
import short_term_fact_store as store
import cohort_identity_service as cohort
from fact_lake_store import initialize_fact_lake
from test_cohort_identity import envelope
from test_short_term_seal_quality_service import publish, http_get

# The isolated lane does not own app.py; cumulative integration registers this
# exact router. Exercise the real middleware in either checkout.
if not any(getattr(r, 'path', None) == '/api/market/evidence-readiness' for r in app.app.routes):
    app.app.include_router(router.router)
DAY, PREVIOUS = '2026-07-30', '2026-07-29'


def tree(root):
    result = {}
    for path in root.rglob('*'):
        stat = path.stat()
        result[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
            stat.st_dev, stat.st_ino, hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
    return result


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.delenv('VR_FACT_LAKE_ROOT', raising=False)
    monkeypatch.setattr(store, '_utc_now', lambda: '2026-07-31T01:00:00+00:00')
    monkeypatch.setattr(journal, '_now', lambda: datetime(2026, 8, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(cohort, '_now', journal._now)


@pytest.fixture
def archives(monkeypatch, tmp_path):
    lake = initialize_fact_lake(tmp_path / 'lake')
    publish(lake)
    monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(lake.root))
    for day in (PREVIOUS, DAY):
        store.save_daily_facts_monotonic(envelope(day, [('600001', 1)]))
    return lake


def result(http_get, day=DAY):
    response = http_get('/api/market/evidence-readiness?trade_date=' + day)
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_missing_sources_never_created(tmp_path, http_get):
    before = tree(tmp_path)
    value = result(http_get)
    assert [f['status'] for f in value['features']] == ['not_configured', 'missing', 'missing']
    assert value['read_only'] and not value['ingestion_enabled']
    assert tree(tmp_path) == before
    assert value['journal']['verification_claim'] == 'NONE'


def test_real_stores_actual_http_and_metadata_immutable(archives, tmp_path, monkeypatch, http_get):
    before = tree(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('legacy loader or storage initializer invoked')
    monkeypatch.setattr(store, 'load_final_fact_record', forbidden)
    monkeypatch.setattr(store, 'init_db', forbidden)
    value = result(http_get)
    assert [f['status'] for f in value['features']] == ['ready', 'ready', 'ready']
    assert value['journal']['state'] == 'SEALED'
    assert value['journal']['prior_metric_available'] == {'limit_up_count': True, 'failed_board_rate': True}
    assert value['features'][1]['required_dates'] == [PREVIOUS, DAY]
    assert value['features'][2]['required_dates'] == [DAY, '2026-07-31']
    assert tree(tmp_path) == before
    assert not journal.journal_path().exists()


@pytest.mark.parametrize('query', ['', '?trade_date=2026-02-30', '?trade_date=20260730',
    '?trade_date=2026-07-30&path=/tmp/secret', '?trade_date=2026-07-30&trade_date=2026-07-29',
    '?trade_date=2026-07-30&as_of=2026-07-30T08:00:00Z', '?trade_date=2026-07-30&root=/tmp'])
def test_exact_query_only(query, http_get):
    assert http_get('/api/market/evidence-readiness' + query).status_code == 422


def test_future_and_nontrading_dates_do_not_invent_facts(http_get):
    value = result(http_get, '2026-08-01')
    assert all(f['status'] == 'ineligible' and f['reason_codes'] == ['NON_TRADING_DATE'] for f in value['features'])
    value = result(http_get, '2026-08-03')
    assert value['features'][2]['status'] == 'missing'
    assert value['journal']['state'] == 'NOT_YET_OPEN'


def test_busy_canonical_archive_preserves_sidecars(archives, tmp_path, http_get):
    sidecar = Path(str(store.resolve_db_path()) + '-wal')
    sidecar.write_bytes(b'active writer')
    before = tree(tmp_path)
    value = result(http_get)
    assert [f['status'] for f in value['features']] == ['ready', 'busy', 'busy']
    assert tree(tmp_path) == before


def test_corrupt_archive_is_safe_ineligible(archives, tmp_path, http_get):
    store.resolve_db_path().write_bytes(b'private /secret key=do-not-print')
    before = tree(tmp_path)
    value = result(http_get)
    assert [f['status'] for f in value['features']] == ['ready', 'ineligible', 'ineligible']
    assert 'secret' not in json.dumps(value)
    assert tree(tmp_path) == before


def test_no_fallback_for_other_date(archives, http_get):
    value = result(http_get, '2026-07-31')
    assert [f['status'] for f in value['features']] == ['missing', 'missing', 'missing']


def test_source_errors_never_expose_paths(monkeypatch, http_get):
    def broken(*args):
        raise RuntimeError('/private/secret password value')
    monkeypatch.setattr(service.seal, 'query_seal_quality', broken)
    response = http_get('/api/market/evidence-readiness?trade_date=' + DAY)
    assert response.status_code == 503
    assert 'secret' not in response.text and 'password' not in response.text


@pytest.fixture
def golden_archives(monkeypatch, tmp_path):
    lake = initialize_fact_lake(tmp_path / 'lake')
    monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(lake.root))
    monkeypatch.setattr(journal, '_now', lambda: datetime(2026, 7, 31, 10, tzinfo=timezone.utc))
    monkeypatch.setattr(cohort, '_now', journal._now)
    for day in ('2026-07-29', '2026-07-30', '2026-07-31'):
        monkeypatch.setattr(store, '_utc_now', lambda day=day: day + 'T09:30:00+00:00')
        store.save_daily_facts_monotonic(envelope(day, [('600001', 1)]))
        publish(lake, day=day)


def test_committed_frontend_goldens_match_actual_api(golden_archives, http_get):
    path = Path(__file__).parents[2] / 'frontend/tests/fixtures/evidence-readiness-golden.json'
    goldens = json.loads(path.read_text(encoding="utf-8"))
    for day, expected in goldens.items():
        assert result(http_get, day) == expected
