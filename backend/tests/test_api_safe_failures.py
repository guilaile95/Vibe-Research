"""Public failure bodies must never expose raw provider/system exception text."""
import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import app as app_module


@pytest.mark.parametrize('endpoint,provider', [
    ('margin','margin_trading'), ('block-trade','block_trade'),
    ('holders','holder_num_change'), ('dividend','dividend_history'),
    ('fund-flow','stock_fund_flow_120d'), ('dragon-tiger','dragon_tiger_board'),
    ('lockup','lockup_expiry'), ('blocks','concept_blocks'),
    ('hot-concepts','hot_concepts'), ('investor-qa','investor_qa'),
    ('industry','industry_comparison'), ('valuation','full_valuation'),
    ('reports','eastmoney_reports'), ('info','individual_info'),
    ('disclosure','disclosure'), ('kline','kline'), ('finance','finance'),
])
def test_provider_failure_is_fixed_safe_502(monkeypatch,endpoint,provider):
    marker = 'SYNTHETIC_SECRET https://private.example/path?token=fixture /private/file Traceback SQL SELECT'
    def fail(*args, **kwargs):
        raise RuntimeError(marker)
    monkeypatch.setattr(app_module.astock,provider,fail)
    monkeypatch.setattr(app_module,'_cached',lambda endpoint,code,ttl,fetch:fetch())
    monkeypatch.setattr(app_module, "_DC_CACHE", app_module.TTLCache(max_entries=1024))
    response = TestClient(app_module.app).get(f'/api/{endpoint}',params={'code':'000001'})
    assert response.status_code == 502
    assert '请稍后重试' in response.json()['detail']
    for forbidden in ['SYNTHETIC_SECRET','private.example','token=','/private/file','Traceback','SELECT']:
        assert forbidden not in response.text


def test_generic_502_literals_never_interpolate_raw_caught_exceptions():
    tree = ast.parse(Path(app_module.__file__).read_text())
    for handler in (node for node in ast.walk(tree) if isinstance(node,ast.ExceptHandler) and node.name and isinstance(node.type,ast.Name) and node.type.id=="Exception"):
        for call in (node for node in ast.walk(handler) if isinstance(node,ast.Call)):
            if not isinstance(call.func,ast.Name) or call.func.id != 'HTTPException' or len(call.args)<2:
                continue
            if not isinstance(call.args[0],ast.Constant) or call.args[0].value != 502:
                continue
            assert not any(isinstance(node,ast.Name) and node.id==handler.name for node in ast.walk(call.args[1])), f'raw exception in HTTP 502 at line {call.lineno}'
