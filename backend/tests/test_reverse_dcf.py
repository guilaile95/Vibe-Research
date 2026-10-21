"""Synthetic local evidence only. No provider/model/network dependencies."""
from copy import deepcopy
from datetime import date, timedelta
import math
import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reverse_dcf import ReverseDcfInput, calculate, enterprise_value, solve_growth
from company_research_router import router

TODAY = date(2026, 10, 19)

def payload():
    def observation(value, unit, currency="USD"):
        return dict(value=value, unit=unit, currency=currency, source="Synthetic filing p.1", as_of=TODAY.isoformat())
    return dict(market="US", symbol="TEST", industry="non_financial", industry_source="Synthetic classification", fcf_basis="annual_unlevered_fcff", price=observation(20., "currency_per_share"), fcff=observation(100., "million_currency"), net_debt=observation(200., "million_currency"), shares=observation(100., "million_shares", "NONE"), assumptions=dict(wacc=.1, terminal_growth=.02, years=5, growth_lower=-.9, growth_upper=1., sensitivity_wacc=[.08, .1, .12], rationale="Synthetic sensitivity assumptions"))

def calc(p):
    return calculate(ReverseDcfInput.model_validate(p), today=TODAY)

@pytest.mark.parametrize("growth", [-.9, -.3, 0., .123456789, 1.])
def test_forward_reverse_parity_and_boundaries(growth):
    p = payload()
    ev = enterprise_value(100e6, growth, .1, .02, 5)
    p['net_debt']['value'] = 0.
    p['price']['value'] = ev / 100e6
    result = calc(p)
    assert result['status'] == 'SOLVED'
    assert result['implied_growth'] == pytest.approx(growth, abs=1e-12)
    assert abs(result['residual_ev']) <= ev * 1e-12


def test_forward_formula_independent_constant_growth_closed_form():
    # If explicit and terminal growth coincide, infinite annuity reduces to FCF1/(r-g).
    assert enterprise_value(100, .02, .1, .02, 5) == pytest.approx(100 * 1.02 / (.1 - .02))


def test_price_and_wacc_monotonicity_sensitivity_recomputes():
    p = payload(); result = calc(p)
    assert result['status'] == 'SOLVED'
    rates = [x['implied_growth'] for x in result['sensitivity']]
    assert rates[0] < rates[1] < rates[2]
    assert rates[1] == result['implied_growth']
    p['price']['value'] *= 1.1
    assert calc(p)['implied_growth'] > result['implied_growth']
    assert result['inputs']['assumptions'] == payload()['assumptions']


def test_no_root_is_not_clamped_or_forecast():
    p = payload(); p['price']['value'] = 1e12
    result = calc(p)
    assert result['status'] == 'NO_ROOT'
    assert result['implied_growth'] is None
    assert all(row['status'] == 'NO_ROOT' for row in result['sensitivity'])
    assert result['classification'] == 'MODEL_IMPLIED_NOT_FORECAST'
    assert result['input_verification'] == 'USER_ENTERED_UNVERIFIED'
    assert solve_growth(100, .0001, .1, .02, 5, -.1, .1)['status'] == 'NO_ROOT'


def test_unit_normalization_and_currency_invariance():
    p = payload(); expected = calc(p)['implied_growth']
    for field in ['fcff', 'net_debt', 'shares']:
        p[field]['value'] *= 1e6
        p[field]['unit'] = 'shares' if field == 'shares' else 'currency'
    assert calc(p)['implied_growth'] == pytest.approx(expected)
    for field in ['price', 'fcff', 'net_debt']: p[field]['currency'] = 'HKD'
    assert calc(p)['implied_growth'] == pytest.approx(expected)

@pytest.mark.parametrize('field,value', [('wacc', .02), ('wacc', 0), ('terminal_growth', .1), ('years', 0), ('years', 31), ('years', 2.5), ('growth_lower', -1), ('growth_upper', -.9), ('growth_upper', 4), ('sensitivity_wacc', [.02]), ('sensitivity_wacc', []), ('sensitivity_wacc', [True]), ('sensitivity_wacc', ['.1']), ('wacc', True), ('wacc', '.1'), ('rationale', '  ')])
def test_invalid_assumptions_reject(field, value):
    p = payload(); p['assumptions'][field] = value
    with pytest.raises(ValidationError): ReverseDcfInput.model_validate(p)

@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), True, '20', None])
def test_nonfinite_and_coerced_numbers_reject(value):
    p = payload(); p['price']['value'] = value
    with pytest.raises(ValidationError): ReverseDcfInput.model_validate(p)

@pytest.mark.parametrize('change', ['currency', 'unit', 'missing', 'source', 'zero_price', 'zero_shares', 'extra'])
def test_incompatible_or_missing_input_reject(change):
    p = payload()
    if change == 'currency': p['fcff']['currency'] = 'CNY'
    if change == 'unit': p['price']['unit'] = 'currency'
    if change == 'missing': del p['fcff']
    if change == 'source': p['fcff']['source'] = ' '
    if change == 'zero_price': p['price']['value'] = 0.
    if change == 'zero_shares': p['shares']['value'] = 0.
    if change == 'extra': p['net_income'] = 100.
    with pytest.raises(ValidationError): ReverseDcfInput.model_validate(p)

@pytest.mark.parametrize('field,days', [('price', 7), ('fcff', 550), ('net_debt', 180), ('shares', 180)])
def test_staleness_exact_boundaries_and_future(field, days):
    p = payload(); p[field]['as_of'] = (TODAY - timedelta(days=days)).isoformat()
    assert calc(p)['status'] == 'SOLVED'
    p[field]['as_of'] = (TODAY - timedelta(days=days + 1)).isoformat()
    result = calc(p)
    assert result['status'] == 'UNKNOWN' and result['implied_growth'] is None and not result['sensitivity']
    assert f'{field.upper()}_STALE' in result['reason_codes']
    p[field]['as_of'] = (TODAY + timedelta(days=1)).isoformat()
    assert f'{field.upper()}_FUTURE' in calc(p)['reason_codes']

@pytest.mark.parametrize('field,value,status,reason', [('industry', 'financial', 'INAPPLICABLE', 'FINANCIAL_FIRM_INAPPLICABLE'), ('industry', 'unknown', 'UNKNOWN', 'INDUSTRY_UNKNOWN'), ('fcf_basis', 'unknown', 'UNKNOWN', 'FCFF_BASIS_UNKNOWN'), ('fcff', 0., 'INAPPLICABLE', 'NONPOSITIVE_FCFF_INAPPLICABLE'), ('fcff', -1., 'INAPPLICABLE', 'NONPOSITIVE_FCFF_INAPPLICABLE')])
def test_applicability_fail_closed(field, value, status, reason):
    p = payload()
    if field == 'fcff': p[field]['value'] = value
    else: p[field] = value
    result = calc(p)
    assert result['status'] == status and reason in result['reason_codes']
    assert result['implied_growth'] is None and not result['sensitivity']


def test_nonpositive_ev_and_negative_net_debt():
    p = payload(); p['net_debt']['value'] = -100.
    assert calc(p)['status'] == 'SOLVED'
    p['net_debt']['value'] = -2000.
    assert 'NONPOSITIVE_ENTERPRISE_VALUE_INAPPLICABLE' in calc(p)['reason_codes']


def test_tiny_terminal_spread_rejected_without_silent_adjustment():
    p = payload(); p['assumptions']['terminal_growth'] = .1 - 1e-12
    p['assumptions']['sensitivity_wacc'] = [.1]
    with pytest.raises(ValidationError): ReverseDcfInput.model_validate(p)


def test_local_router_has_no_capture_or_generation_calls(monkeypatch):
    import company_research
    def forbidden(*args, **kwargs): raise AssertionError('No fetching or model calls')
    monkeypatch.setattr(company_research, 'capture', forbidden)
    monkeypatch.setattr(company_research, 'generate', forbidden)
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    response = client.post('/api/company-research/reverse-dcf', json=payload())
    assert response.status_code == 200
    assert response.json()['data']['classification'] == 'MODEL_IMPLIED_NOT_FORECAST'
    p = payload(); p['assumptions']['wacc'] = .02
    assert client.post('/api/company-research/reverse-dcf', json=p).status_code == 422
