"""Offline fixed-year forecast expiry, including retained upstream rows."""
from datetime import datetime, timezone

import astock
import pytest


@pytest.fixture
def retained_forecast(monkeypatch):
    monkeypatch.setattr(astock, 'tencent_quote', lambda _: {'000001': {'name': 'Synthetic', 'price': 10}})
    monkeypatch.setattr(astock, 'eastmoney_stock_valuation', lambda _: {'code': '000001', 'pe_ttm': 18, 'pb': 2, 'market_cap': 1e9})
    monkeypatch.setattr(astock, 'profit_forecast', lambda _: [
        {'年度': '2026', '均值': 1, '预测机构数': 4}, {'年度': '2027', '均值': 1.5}])


def test_retained_old_rows_not_current_forecast(monkeypatch, retained_forecast):
    class FutureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2027, 1, 4, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(astock, 'datetime', FutureClock)
    value = astock.full_valuation('000001')
    assert value['pe_26e'] is None


def clock(monkeypatch, instant):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)
    monkeypatch.setattr(astock, 'datetime', Clock)


@pytest.mark.parametrize('instant,expired', [
    ('2026-12-31T15:59:59+00:00', False),
    ('2026-12-31T16:00:00+00:00', True),
    ('2027-01-04T00:00:00+00:00', True),
])
def test_shanghai_boundary_and_nonforecast_preservation(monkeypatch, retained_forecast, instant, expired):
    clock(monkeypatch, datetime.fromisoformat(instant))
    value = astock.full_valuation('000001')
    assert (value.get('forecast_status') == 'EXPIRED') is expired
    assert {k: value[k] for k in ('price', 'pe_ttm', 'pb', 'mcap_yi')} == dict(price=10, pe_ttm=18, pb=2, mcap_yi=10)
    assert value['eps_26e'] == 1 and value['eps_27e'] == 1.5
    assert value['analyst_count'] == 4
    if expired:
        assert all(value[k] is None for k in ('pe_26e', 'cagr_pct', 'peg', 'digest_years'))
        assert '已过期' in value['forecast_note']
    else:
        assert value['pe_26e'] == 10 and value['cagr_pct'] == 50 and value['peg'] == .2


@pytest.mark.parametrize('rows', [[], [{'年度': '2026', '均值': 0}, {'年度': '2027', '均值': -1}]])
def test_expired_missing_or_zero_raw_facts(monkeypatch, retained_forecast, rows):
    clock(monkeypatch, datetime(2027, 1, 4, tzinfo=timezone.utc))
    monkeypatch.setattr(astock, 'profit_forecast', lambda _: rows)
    value = astock.full_valuation('000001')
    assert value['forecast_status'] == 'EXPIRED'
    assert value['eps_26e'] == (0 if rows else None)
    assert value['eps_27e'] == (-1 if rows else None)
    assert value['price'] == 10 and value['peg'] is None


@pytest.mark.parametrize('failure', [astock.DependencyMissing('unavailable'), RuntimeError('private detail')])
def test_expiry_warning_survives_provider_failure_and_checkpoints(monkeypatch, retained_forecast, failure):
    clock(monkeypatch, datetime(2027, 1, 4, tzinfo=timezone.utc))
    def fail(_):
        raise failure
    monkeypatch.setattr(astock, 'profit_forecast', fail)
    checkpoints = []
    value = astock.full_valuation('000001', on_quote=checkpoints.append)
    for result in [*checkpoints, value]:
        assert result['forecast_status'] == 'EXPIRED'
        assert '已过期' in result['forecast_note']
        assert 'private detail' not in result['forecast_note']
    assert value['pe_ttm'] == 18


def test_cache_cannot_replay_valid_forecast_across_rollover(monkeypatch, retained_forecast):
    import public_data_budget as budget
    monkeypatch.setattr(budget, '_CACHE', {})
    monkeypatch.setattr(budget, '_INFLIGHT', set())
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return astock.full_valuation('000001')
    monkeypatch.setattr(budget, '_run_process', run)
    clock(monkeypatch, datetime.fromisoformat('2026-12-31T15:59:59+00:00'))
    before = budget.run('valuation', '000001')
    assert before['pe_26e'] == 10
    clock(monkeypatch, datetime.fromisoformat('2026-12-31T16:00:00+00:00'))
    after = budget.run('valuation', '000001')
    assert len(calls) == 1  # Exercise the actual 30-second cache hit.
    assert after['forecast_status'] == 'EXPIRED' and after['pe_26e'] is None
    assert after['pe_ttm'] == before['pe_ttm'] == 18
    assert before['pe_26e'] == 10  # Guard never mutates prior observations.


def test_cockpit_old_snapshot_cannot_score_forecasts(monkeypatch, retained_forecast):
    from decision_cockpit_signals import evaluate_value
    clock(monkeypatch, datetime(2026, 12, 31, tzinfo=timezone.utc))
    old = astock.full_valuation('000001')
    clock(monkeypatch, datetime(2027, 1, 4, tzinfo=timezone.utc))
    signals = {s['label']: s for s in evaluate_value('000001', None, None, old)}
    for label in ('eps_26e', 'pe_26e', 'cagr_pct', 'peg'):
        assert signals[label]['assessment'] == 'unknown'
        assert signals[label]['value'] is None
        assert '已过期' in signals[label]['context']['forecast_note']


def test_ai_tool_and_company_research_receive_expiry_metadata(monkeypatch, retained_forecast):
    import ai_tools
    import company_research
    clock(monkeypatch, datetime(2027, 1, 4, tzinfo=timezone.utc))
    # Tool dispatch uses the real producer, not a replacement payload.
    handler = ai_tools._HANDLERS
    result = handler['query_valuation']({'code': '000001'})
    assert result['forecast_status'] == 'EXPIRED' and result['pe_26e'] is None
    assert '已过期' in result['forecast_note']
    plan = [entry for entry in company_research.source_plan('A', '000001') if entry[0] == 'valuation']
    captured = company_research.capture('A', '000001', reader_plan=plan)
    source = next(row for row in captured['sources'] if row['evidence_id'] == 'valuation')
    assert source['status'] == 'AVAILABLE'
    assert source['payload'] == result


@pytest.mark.parametrize('partial', [False, True])
def test_inflight_or_partial_result_requalified_at_return(monkeypatch, retained_forecast, partial):
    import public_data_budget as budget
    monkeypatch.setattr(budget, '_CACHE', {})
    monkeypatch.setattr(budget, '_INFLIGHT', set())
    clock(monkeypatch, datetime.fromisoformat('2026-12-31T15:59:59+00:00'))
    completed = astock.full_valuation('000001')
    if partial:
        completed.update(status='partial', reason_code='SOURCE_TIMEOUT', forecast_note='一致预期来源尚未完成')
    def straddle(*args, **kwargs):
        clock(monkeypatch, datetime.fromisoformat('2026-12-31T16:00:00+00:00'))
        return completed
    monkeypatch.setattr(budget, '_run_process', straddle)
    value = budget.run('valuation', '000001')
    assert value['forecast_status'] == 'EXPIRED' and value['pe_26e'] is None
    assert value['pe_ttm'] == 18
    assert '已过期' in value['forecast_note']
    if partial:
        assert value['reason_code'] == 'SOURCE_TIMEOUT'
        assert '尚未完成' in value['forecast_note']
        assert not budget._CACHE
