from datetime import datetime, timezone, timedelta
import copy
import pytest

from short_term_theme_research import build_theme_research, normalize_ths_theme_pages

DAYS = ['2026-09-23', '2026-09-24', '2026-09-28', '2026-09-29', '2026-09-30']


def pages(day, rows=None):
    stamp = datetime.fromisoformat(day + 'T09:35:00+08:00').timestamp()
    rows = rows if rows is not None else [{'code': '000001', 'first_limit_up_time': stamp, 'reason_type': '芯片+芯片+半导体'}]
    return [{'status_code': 0, 'data': {'info': rows, 'page': {'total': len(rows)}}}]


def evidence(day, assignments, *, complete=True, boards=None):
    codes = list(assignments)
    return {'trade_date': day, 'pool': {'trade_date': day, 'complete': complete, 'status': 'normal' if complete else 'partial', 'post_close_observation': True,
            'rows': [{'stock_code': c, 'boards': (boards or {}).get(c, 1), 'name': c, 'first_seal': '09:35:00'} for c in codes]},
            'themes': {'trade_date': day, 'complete': True, 'rows': [
                {'stock_code': c, 'source_trade_date': day, 'tags': tags} for c, tags in assignments.items()]}}


def test_source_dates_every_row_and_no_synonym_merge():
    result = normalize_ths_theme_pages(pages(DAYS[-1]), DAYS[-1])
    assert result['rows'][0]['tags'] == ['芯片', '半导体']
    rows = pages(DAYS[-1])[0]['data']['info'] + pages(DAYS[-2])[0]['data']['info']
    rows[1]['code'] = '000002'
    with pytest.raises(ValueError, match='DATE_MISMATCH'):
        normalize_ths_theme_pages(pages(DAYS[-1], rows), DAYS[-1])


@pytest.mark.parametrize('mutator', [
    lambda p: p[0]['data']['info'].append(dict(p[0]['data']['info'][0])),
    lambda p: p[0]['data']['page'].update(total=2),
    lambda p: p[0]['data']['info'][0].update(first_limit_up_time=True),
    lambda p: p[0]['data']['info'][0].update(first_limit_up_time=float('nan')),
])
def test_bad_capture_fails_closed(mutator):
    p = pages(DAYS[-1]); mutator(p)
    with pytest.raises(ValueError): normalize_ths_theme_pages(p, DAYS[-1])


def test_partial_absence_unknown_complete_absence_zero_and_all_faded_retained():
    ev = {DAYS[-2]: evidence(DAYS[-2], {'000001': ['昨日'], '000002': ['独立']}),
          DAYS[-1]: evidence(DAYS[-1], {'000003': ['今日']})}
    result = build_theme_research(DAYS, ev)
    assert len(result['days']) == 5
    rot = {r['tag']: r for r in result['rotation']}
    assert rot['昨日']['cells'][0]['count'] is None
    assert rot['昨日']['cells'][-1]['count'] == 0
    assert {x['tag'] for x in result['tree']} == {'昨日', '独立', '今日'}
    ev[DAYS[-1]]['themes']['rows'][0]['tags'] = []
    result = build_theme_research(DAYS, ev)
    assert all(r['cells'][-1]['count'] is None for r in result['rotation'])


def test_multilabel_distinct_denominator_and_competition_ties():
    ev = {d: evidence(d, {'000001': ['A', 'A', 'B'], '000002': ['B'], '000003': ['C']}) for d in DAYS}
    result = build_theme_research(DAYS, ev)
    ranks = {r['tag']: r['cells'][-1]['rank'] for r in result['rotation']}
    assert ranks == {'A': 2, 'B': 1, 'C': 2}
    assert result['days'][-1]['covered'] == result['days'][-1]['limit_up'] == 3
    assert result['rotation'][0]['cells'][-1]['count'] == 1
    assert all(r['top3_days'] == 5 for r in result['rotation'])


def test_partial_counts_lower_bound_and_rank_unknown():
    ev = {DAYS[-1]: evidence(DAYS[-1], {'000001': ['A'], '000002': []})}
    cell = build_theme_research(DAYS, ev)['rotation'][0]['cells'][-1]
    assert cell == {'date': DAYS[-1], 'count': 1, 'rank': None, 'highest': 1, 'lower_bound': True}


def test_previous_membership_not_survivor_or_current_tag_filtered():
    ev = {DAYS[-2]: evidence(DAYS[-2], {'000001': ['A'], '000002': ['A']}),
          DAYS[-1]: evidence(DAYS[-1], {'000001': ['B']})}
    tree = {r['tag']: r for r in build_theme_research(DAYS, ev)['tree']}
    assert tree['A']['previous_count'] == 2
    assert tree['A']['continued_count'] == 1
    assert tree['A']['continuation_rate'] == .5
    assert tree['A']['count'] == 0


def test_all_leader_ties_and_exact_appearance_close_missing_end():
    ev = {d: evidence(d, {'000001': ['A'], '000002': ['A']}, boards={'000001': 3, '000002': 3}) for d in DAYS}
    price = {'stock_code': '000001', 'price_unit': 'CNY/share', 'adjustment': 'forward_adjusted',
             'adjustment_basis_id': 'provider-adjustment-version-1', 'single_capture': True,
             'rows': [{'date': d, 'close': v} for d, v in zip(DAYS, [10, 11, 12, 11]) ]}
    result = build_theme_research(DAYS, ev, {'000001': price})
    assert len(result['lineage']) == 2
    first = result['lineage'][0]
    assert first['series'][0]['cum_return_pct'] == 0
    assert first['cum_return_pct'] is None
    assert first['peak_cum_return_pct'] is None
    price['rows'].append({'date': DAYS[-1], 'close': 10.8})
    first = build_theme_research(DAYS, ev, {'000001': price})['lineage'][0]
    assert first['cum_return_pct'] == 8
    assert first['peak_cum_return_pct'] == 20
    assert first['drawdown_from_peak_pct'] == -10
    price['adjustment_basis_id'] = None
    assert build_theme_research(DAYS, ev, {'000001': price})['lineage'][0]['cum_return_pct'] is None


def test_missing_appearance_close_no_later_rebase_and_nonmutating():
    ev = {d: evidence(d, {'000001': ['A']}) for d in DAYS}
    before = copy.deepcopy(ev)
    p = {'stock_code': '000001', 'price_unit': 'CNY/share', 'adjustment': 'forward_adjusted',
         'adjustment_basis_id': 'v1', 'single_capture': True, 'rows': [{'date': DAYS[-1], 'close': 10}]}
    result = build_theme_research(DAYS, ev, {'000001': p})
    assert all(x['cum_return_pct'] is None for x in result['lineage'][0]['series'])
    assert before == ev


def test_fixed_window_rejects_data_driven_short_window():
    with pytest.raises(ValueError): build_theme_research(DAYS[1:], {})


def test_preclose_complete_pool_is_not_admitted():
    ev = evidence(DAYS[-1], {'000001': ['A']})
    ev['pool'].update(post_close_observation=False, status='partial')
    result = build_theme_research(DAYS, {DAYS[-1]: ev})
    assert result['days'][-1]['limit_up'] is None
    assert result['days'][-1]['available'] is False


def test_contradictory_pool_overlap_suppresses_broken_rate_and_outcome():
    ev = evidence(DAYS[-1], {'000001': ['A']})
    ev['pool'].update(broken_complete=True, broken_rows=[{'stock_code': '000001'}])
    result = build_theme_research(DAYS, {DAYS[-1]: ev})
    assert result['days'][-1]['pool_overlap_count'] == 1
    assert result['days'][-1]['broken_rate'] is None
    assert result['tree'][0]['cohort_broken'] is None


def test_extreme_finite_price_arithmetic_stays_json_safe_unknown():
    ev = {d: evidence(d, {'000001': ['A']}) for d in DAYS}
    prices = {'000001': {'stock_code': '000001', 'price_unit': 'CNY/share', 'adjustment': 'forward_adjusted',
              'adjustment_basis_id': 'one-response', 'single_capture': True,
              'rows': [{'date': d, 'close': 1e-308 if i == 0 else 1e308} for i, d in enumerate(DAYS)]}}
    result = build_theme_research(DAYS, ev, prices)
    assert result['lineage'][0]['cum_return_pct'] is None
    assert result['lineage'][0]['peak_cum_return_pct'] is None
    import json
    json.dumps(result, allow_nan=False)
