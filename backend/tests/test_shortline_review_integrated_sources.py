"""Cumulative-only integration: real P2/P3 services over temporary synthetic archives.

Dependencies are authored in parallel; skip is explicit before their integration.
The release acceptance run must include both tests without skips.
"""
import importlib.util
import pytest
import shortline_review_sources as sources
import shortline_review_supplement as supplement
import shortline_review_contract as C

requires_dependencies=pytest.mark.skipif(any(importlib.util.find_spec(name)is None for name in ('shortline_research_service','short_term_theme_research_service')),reason='P2/P3 cumulative integration dependencies not present')


@requires_dependencies
def test_actual_p2_p3_services_bind_scoped_archive_evidence(tmp_path,monkeypatch):
    from test_short_term_theme_research_service import seed,tree,DAYS
    from fact_lake_store import initialize_fact_lake
    root=tmp_path/'archive';lake=initialize_fact_lake(root);seed(lake)
    monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root));monkeypatch.setenv('VR_DATA_DIR',str(tmp_path/'private'))
    before=tree(root)
    observed=sources.market_sources(DAYS[-1])
    assert {'sentiment','leader','theme'}<=set(observed)
    assert all(observed[k][3]=='FIXTURE'for k in ('sentiment','leader','theme'))
    bundle=sources.build_bundle(DAYS[-1],'daily')
    C.validate_bundle(bundle)
    assert bundle['sections'][0]['evidence'] and bundle['sections'][2]['evidence']
    assert tree(root)==before


@requires_dependencies
def test_supplement_real_receipt_replay_uses_integrated_snapshot(tmp_path,monkeypatch):
    import json
    from fact_lake_store import initialize_fact_lake
    from test_short_term_theme_research_service import tree,DAYS
    root=tmp_path/'archive';lake=initialize_fact_lake(root);day=DAYS[-1]
    raw=json.dumps({'success':True,'code':0,'result':{'count':1,'data':[{'DIM_DATE':day,'RZRQYE':100}]}}).encode()
    supplement.persist_raw(lake,'margin',day,raw,fixture=True)
    monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root));before=tree(root)
    result=supplement.query_supplements(day)
    assert result['capital_extra']['fixture']is True
    assert result['capital_extra']['data']['margin']['rows'][0]['margin_balance_yuan']==100
    assert tree(root)==before


@requires_dependencies
def test_real_same_second_receipts_choose_later_instant(tmp_path,monkeypatch):
    import json
    from fact_lake_store import initialize_fact_lake
    root=tmp_path/'archive';lake=initialize_fact_lake(root);day='2026-07-23'
    for timestamp,amount in [('2026-07-23T08:00:00Z',100),('2026-07-23T08:00:00.500000Z',200)]:
        raw=json.dumps({'success':True,'code':0,'result':{'count':1,'data':[{'DIM_DATE':day,'RZRQYE':amount}]}}).encode()
        supplement.persist_raw(lake,'margin',day,raw,fixture=True,captured_at=timestamp)
    monkeypatch.setenv('VR_FACT_LAKE_ROOT',str(root))
    result=supplement.query_supplements(day)
    assert result['capital_extra']['data']['margin']['rows'][0]['margin_balance_yuan']==200
