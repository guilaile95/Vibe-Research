"""Private, read-only calculation API. No generated-code or provider execution."""
from fastapi import APIRouter, Body, HTTPException, Response
from pydantic import ValidationError
from research_analytics import METRIC_KEYS, VERSION, performance, scenario
from research_analytics_contract import SimulationRequest, ScenarioRequest, PerformanceRequest, LedgerPerformanceRequest, RdpRequest
from research_analytics_simulation import simulate, simulation_plan
from research_analytics_adapters import ledger_performance, rdp_inputs
from research_cost_comparison import CostComparisonRequest, compare_costs

router = APIRouter(prefix='/api/research-analytics', tags=['research-analytics'])


def _calculate(body, model, fn, response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        request = model.model_validate(body)
        return fn(request)
    except (ValidationError, ValueError, ArithmeticError):
        # Never serialize raw private input, NaN, provider paths, SQL or traceback.
        raise HTTPException(status_code=422, detail='研究输入合同不满足：检查字段、有限数值、唯一日期、币种及样本边界。') from None


@router.get('/catalog')
def catalog():
    return {'schema_version': VERSION, 'research_only': True, 'formal_writes': 0,
            'strategies': ['BUY_AND_HOLD', 'SMA_CROSS'], 'execution': 'PRIOR_CLOSE_TO_NEXT_OPEN',
            'limits': {'instruments': 20, 'sessions': 2000, 'ledger_trades': 10000, 'bootstrap_samples': 200},
            'metric_inventory': [{'name': key, 'implementation': 'SUPPORTED_WITH_EXPLICIT_UNDEFINED_STATES',
                                  'source': 'backtest/metrics.py:calc_metrics'} for key in METRIC_KEYS],
            'inventory_correction': 'Fixed source returns 20 core metrics; prior 43-metric count withdrawn as unsupported.',
            'supplemental_inventory': [
                {'name': 'same-input FIFO / moving-average currency-separated comparison', 'status': 'SUPPORTED', 'source': 'orchestrator/src/finance/holdings.ts;pages/Portfolio.tsx'},
                {'name': 'benchmark matched calendar', 'status': 'SUPPORTED', 'source': 'backtest/benchmark.py'},
                {'name': 'zero-cost and double-cost comparison', 'status': 'SUPPORTED', 'source': 'backtest/cost_compare.py'},
                {'name': 'bounded 3×3 SMA parameter grid', 'status': 'SUPPORTED', 'source': 'backtest/sensitivity.py'},
                {'name': 'bootstrap Sharpe interval / chronological subwindows', 'status': 'SUPPORTED', 'source': 'backtest/validation.py'},
                {'name': 'bounded closed-PnL trade-order Monte Carlo', 'status': 'SUPPORTED', 'source': 'backtest/validation.py'},
                {'name': 'explicit event-date forward windows', 'status': 'SUPPORTED', 'source': 'backtest/event_study.py'},
                {'name': 'live event discovery and provider collection', 'status': 'UNSUPPORTED', 'source': 'backtest/event_study.py', 'value': None},
                {'name': 'TWR and bounded uniqueness-aware XIRR', 'status': 'SUPPORTED', 'source': 'backtest/portfolio_perf.py'},
                {'name': 'correlation / covariance / historical VaR / replay', 'status': 'SUPPORTED', 'source': 'backtest/risk_xray.py;scenario_replay.py'},
            ]}


@router.get('/example/{kind}')
def example(kind: str, response: Response):
    from research_analytics_examples import example_input
    response.headers['Cache-Control'] = 'no-store'
    if kind not in {'simulation', 'scenario', 'performance', 'ledger-performance', 'cost-comparison'}:
        raise HTTPException(status_code=404, detail='unknown example')
    return {'synthetic': True, 'input': example_input(kind)}


@router.post('/simulation-plan')
def simulation_plan_endpoint(response: Response, body: dict = Body(...)):
    return _calculate(body, SimulationRequest, simulation_plan, response)


@router.post('/simulation')
def simulation_endpoint(response: Response, body: dict = Body(...)):
    return _calculate(body, SimulationRequest, simulate, response)


@router.post('/scenario')
def scenario_endpoint(response: Response, body: dict = Body(...)):
    return _calculate(body, ScenarioRequest, scenario, response)


@router.post('/performance')
def performance_endpoint(response: Response, body: dict = Body(...)):
    return _calculate(body, PerformanceRequest, performance, response)


@router.post('/ledger-performance')
def ledger_endpoint(response: Response, body: dict = Body(...)):
    return _calculate(body, LedgerPerformanceRequest, ledger_performance, response)


@router.post('/rdp-inputs')
def rdp_endpoint(response: Response, body: dict = Body(...)):
    return _calculate(body, RdpRequest, rdp_inputs, response)


@router.post('/cost-comparison')
def cost_comparison_endpoint(response: Response, body: dict = Body(...)):
    return _calculate(body, CostComparisonRequest, compare_costs, response)
