"""Synthetic, deterministic teaching inputs; never read/write user portfolio data."""
from datetime import date, timedelta


def example_input(kind):
    if kind == 'performance':
        return {'currency': 'CNY', 'scope': 'WHOLE_ACCOUNT', 'source_label': 'SYNTHETIC_EXAMPLE_NOT_USER_ACCOUNT',
                'fees_complete': True, 'corporate_actions_complete': True, 'coverage_complete': True,
                'valuations': [{'date': '2024-01-02', 'value': 1000.0},
                               {'date': '2024-07-02', 'value': 1600.0, 'flow_end': 500.0},
                               {'date': '2025-01-02', 'value': 1760.0}]}
    start = date(2025, 1, 2)
    sessions = [(start + timedelta(days=n)).isoformat() for n in range(65) if (start + timedelta(days=n)).weekday() < 5]
    instrument = {'code': 'SYNTH_A', 'currency': 'CNY', 'market': 'CN', 'weight': .6,
                  'lot_size': 100, 'settlement_sessions': 1, 'fee_bps': 3.0, 'min_fee': 5.0, 'slippage_bps': 2.0,
                  'corporate_actions_complete': True, 'actions': [],
                  'bars': [{'date': day, 'open': 10 + n * .03 + (n % 4) * .1,
                            'close': 10 + n * .04 + (n % 3) * .1,
                            'suspended': False, 'limit_up': False, 'limit_down': False, 'price_limit_rule': 'NO_DAILY_LIMIT'} for n, day in enumerate(sessions)]}
    base = {'sessions': sessions, 'calendar_source': 'SYNTHETIC_WEEKDAY_FIXTURE_NOT_OFFICIAL_CALENDAR',
            'source_label': 'SYNTHETIC_EXAMPLE_NOT_MARKET_DATA', 'price_basis': 'RAW_WITH_EXPLICIT_ACTIONS',
            'instruments': [instrument]}
    if kind == 'simulation':
        return {**base, 'strategy': {'name': 'SMA_CROSS', 'fast': 5, 'slow': 20},
                'initial_cash': 10000.0, 'terminal_liquidation': False, 'robustness': True,
                'benchmark': {**instrument, 'code': 'SYNTH_BENCHMARK', 'weight': 1.0}}
    if kind == 'scenario':
        return {**base, 'event_dates': [sessions[10], sessions[-2]], 'event_horizon': 5}
    # This template intentionally cannot read real records until explicitly qualified.
    return {**base, 'opening': [{'code': 'SYNTH_A', 'quantity': 100.0}],
            'ledger_fees_confirmed': False, 'opening_positions_complete': False}
