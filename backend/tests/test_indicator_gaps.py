"""Independent gap contracts: dated observations are never compressed or filled."""
from datetime import date, timedelta
import math
import pytest
import technical_indicators as ti


def rows(n=100):
    return [dict(datetime=str(date(2026, 1, 1)+timedelta(days=i)), close=100+i,
                 high=101+i, low=99+i, volume=1000+i) for i in range(n)]


def compute(bars):
    return ti.compute_indicators(bars, code='000001', period='daily', days=len(bars), fetched_at='2026-05-01T00:00:00Z')


@pytest.mark.parametrize('missing', [None, float('nan'), float('inf'), float('-inf')])
def test_interior_gap_preserves_date_and_window(missing):
    bars = rows(); bars[95]['close'] = missing
    result = compute(bars)
    assert result['status'] == 'partial'
    assert result['trade_date'] == bars[-1]['datetime']
    assert len(result['series']) == 60
    assert result['series'][-5]['date'] == bars[95]['datetime']
    for name in ['sma5', 'sma20', 'sma60', 'ema12', 'ema26', 'macd_histogram', 'rsi14', 'bollinger_middle', 'kdj_k']:
        assert result['latest'][name] is None, name
    assert result['latest']['volume_ratio_5_20'] is not None  # independent complete volume window
    assert result['limitations']


def test_latest_missing_does_not_fall_back():
    bars = rows(); bars[-1]['close'] = None
    result = compute(bars)
    assert result['status'] == 'unavailable'
    assert result['trade_date'] == bars[-1]['datetime']
    assert result['latest']['close'] is None
    assert result['triggers'] == []


def test_ema_reset_and_explicit_post_gap_warmup():
    assert ti._ema([10., 12., None, 20., 22., 24., 26.], 3) == [10., 11., None, None, None, 22.5, 24.25]
    assert ti._ema([10., None, 20., None, 30., 32., 34.], 3) == [10., None, None, None, None, None, 32.5]


def test_macd_gap_needs_26_closes_then_9_difs():
    dif, dea, hist = ti._macd([10.] * 80 + [None] + [20.] * 34)
    assert all(v is None for v in dif[80:106])
    assert dif[106] == 0
    assert all(v is None for v in dea[80:114])
    assert dea[114] == hist[114] == 0


def test_rsi_restart_is_causal_not_future_seeded():
    values = [10., 11., None, 30., 29., 31., 30.]
    # n=3: gains 0,2,0; losses 1,0,1 -> 50, only on last index.
    assert ti._rsi(values, 3) == [None]*6 + [50.]
    assert ti._rsi(values[:5], 3) == [None]*5


def test_kdj_restart_discards_pre_gap_state():
    closes = [10.] * 10 + [None] + [10.] * 9
    highs = [12.] * len(closes); lows = [9.] * len(closes)
    k, d, j = ti._kdj(closes, highs, lows)
    assert all(v is None for v in k[10:19])
    assert k[19] == pytest.approx(400/9)  # 2/3*50 + 1/3*(100/3)
    assert d[19] == pytest.approx(1300/27)


def test_no_calendar_padding_zero_boundary_and_deterministic_duplicates():
    bars = rows(70)[::2]  # absent calendar dates are not provider-reported gaps
    result = compute(bars)
    assert len(result['series']) == 35
    assert result['latest']['sma20'] == pytest.approx(sum(b['close'] for b in bars[-20:])/20)
    missing_duplicate = {**bars[-1], 'close': None}
    assert compute([missing_duplicate, *reversed(bars)]) == result
    assert ti._parse_klines([{'date': '2026-01-01', 'close': 0}])[0]['close'] == 0
    assert ti._sma([0., 1., 2.], 3)[-1] == 1.


def test_complete_series_matches_independent_recurrences():
    values = [100. + math.sin(i/3)*10 for i in range(100)]
    bars = rows()
    for bar, close in zip(bars, values):
        bar.update(close=close, high=close+1, low=close-1)
    result = compute(bars)['latest']
    def ema(xs, n):
        out = []; last = xs[0]
        for i, x in enumerate(xs):
            last = x if i == 0 else (2*x+(n-1)*last)/(n+1)
            out.append(last)
        return out
    e12, e26 = ema(values, 12), ema(values, 26)
    dif = [a-b for a,b in zip(e12,e26)]
    assert result['ema12'] == pytest.approx(e12[-1])
    assert result['macd_histogram'] == pytest.approx(2*(dif[-1]-ema(dif,9)[-1]))
    assert result['sma20'] == pytest.approx(sum(values[-20:])/20)
    gain = sum(max(values[i]-values[i-1],0) for i in range(1,15))/14
    loss = sum(max(values[i-1]-values[i],0) for i in range(1,15))/14
    for i in range(15,len(values)):
        gain = (13*gain+max(values[i]-values[i-1],0))/14
        loss = (13*loss+max(values[i-1]-values[i],0))/14
    assert result['rsi14'] == pytest.approx(100-100/(1+gain/loss))


def test_gap_signal_is_not_a_screener_match():
    import screener_service as svc
    from screener_models import ScreenerEvaluateIn
    bars = rows(); bars[-5]['close'] = None
    body = ScreenerEvaluateIn(codes=['000001'], conditions=[{'id': 'price_gt_sma20'}])
    result = svc.evaluate_screener(body, kline_fn=lambda *args: bars)
    assert result['matched'] == []
    assert result['unavailable'][0]['condition_results'][0]['evaluable'] is False


@pytest.mark.parametrize('window', [5, 10, 20, 60])
def test_fixed_window_recovers_only_when_gap_exits(window):
    values = [1.] * 70 + [None] + [2.] * window
    output = ti._sma(values, window)
    assert all(value is None for value in output[70:70+window])
    assert output[-1] == 2.


def test_recursive_gap_series_are_prefix_causal():
    values = [float(i+1) if i not in {4, 32, 33, 75} else None for i in range(120)]
    full = (ti._ema(values, 12), *ti._macd(values), ti._rsi(values))
    for stop in [5, 15, 32, 34, 60, 76, 90, 110]:
        prefix = values[:stop]
        actual = (ti._ema(prefix, 12), *ti._macd(prefix), ti._rsi(prefix))
        assert actual == tuple(series[:stop] for series in full)
