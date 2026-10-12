import json
import pytest
from fact_lake_store import initialize_fact_lake
from short_term_theme_capture import store_ths_theme_capture, normalize_tencent_forward_capture, store_tencent_forward_capture
from test_short_term_theme_research import pages, DAYS


def test_theme_pages_preserve_exact_bytes_and_immutable_identity(tmp_path):
    lake = initialize_fact_lake(tmp_path / 'archive')
    raw = json.dumps(pages(DAYS[-1])[0]).encode()
    one = store_ths_theme_capture(lake, [raw], trade_date=DAYS[-1], captured_at=DAYS[-1]+'T08:00:00Z', fixture=True)
    two = store_ths_theme_capture(lake, [raw], trade_date=DAYS[-1], captured_at=DAYS[-1]+'T08:00:00Z', fixture=True)
    assert one == two
    assert lake.read_payload(one[0].observation.observation_id) == raw
    assert one[0].observation.payload['fixture'] is True


def raw_bars(bars=None, key='qfqday'):
    return json.dumps({'data': {'sz000001': {key: bars or [[DAYS[0], '10','11','12','9','100'], [DAYS[-1],'11','12','13','10','100']]}}}).encode()


def test_single_response_basis_and_paused_unknown():
    result = normalize_tencent_forward_capture(raw_bars(), stock_code='000001')
    assert result['rows'][0]['close'] == 11
    assert result['rows'][0]['high'] == 12 and result['rows'][0]['low'] == 9
    assert result['single_capture'] and result['adjustment_basis_id'].startswith('sha256:')
    raw = raw_bars([[DAYS[0], '10','11','12','9','0']])
    assert normalize_tencent_forward_capture(raw, stock_code='000001')['rows'][0]['close'] is None
    assert result['adjustment_basis_id'] != normalize_tencent_forward_capture(raw, stock_code='000001')['adjustment_basis_id']


@pytest.mark.parametrize('raw', [raw_bars(key='day'), raw_bars([[DAYS[0],'10','11','12','9','100']]*2),
    raw_bars([['2026-09-26','10','11','12','9','100']]), raw_bars([[DAYS[0],'10','99','12','9','100']]),
    raw_bars([[DAYS[0],'10','11','12','9',None]]), raw_bars([[DAYS[0],'10','11','12','9','nan']])])
def test_malformed_raw_prices_rejected(raw):
    with pytest.raises(ValueError): normalize_tencent_forward_capture(raw, stock_code='000001')


def test_price_bytes_use_same_factlake(tmp_path):
    lake = initialize_fact_lake(tmp_path / 'archive')
    receipt = store_tencent_forward_capture(lake, raw_bars(), stock_code='000001', trade_date=DAYS[-1], captured_at=DAYS[-1]+'T08:00:00Z', fixture=True)
    assert lake.read_payload(receipt.observation.observation_id) == raw_bars()


def test_receipt_manifest_identity_and_exact_provider_are_replayed(tmp_path):
    from dataclasses import replace
    from short_term_theme_capture import verify_capture_receipt
    lake = initialize_fact_lake(tmp_path / 'receipt')
    raw = json.dumps(pages(DAYS[-1])[0]).encode()
    stored = store_ths_theme_capture(lake, [raw], trade_date=DAYS[-1], captured_at=DAYS[-1]+'T08:00:00Z', fixture=True)[0]
    verify_capture_receipt(stored, raw)
    for changed in [replace(stored.observation, provider_symbol='anything'),
                    replace(stored.observation, request_fingerprint='tampered'),
                    replace(stored.observation, payload={**stored.observation.payload, 'fixture': 'yes'}),
                    replace(stored.observation, payload={**stored.observation.payload, 'capture_batch_id': 'sha256:'+'0'*64})]:
        with pytest.raises(ValueError): verify_capture_receipt(replace(stored, observation=changed), raw)


def test_oversized_labels_fail_closed_without_truncation():
    from short_term_theme_research import normalize_ths_theme_pages
    p = pages(DAYS[-1]); p[0]['data']['info'][0]['reason_type'] = 'x' * 257
    with pytest.raises(ValueError, match='OVERSIZED'): normalize_ths_theme_pages(p, DAYS[-1])
    p[0]['data']['info'][0]['reason_type'] = '+'.join(str(i) for i in range(65))
    with pytest.raises(ValueError, match='OVERSIZED'): normalize_ths_theme_pages(p, DAYS[-1])
