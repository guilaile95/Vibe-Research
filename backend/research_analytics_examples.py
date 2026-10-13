"""Synthetic, deterministic teaching inputs; never read/write user portfolio data."""
from datetime import date, timedelta


def example_input(kind):
    if kind == 'cost-comparison':
        securities = [{'code': code, 'currency': currency, 'timezone': timezone,
            'opening_quantity': 0.0, 'opening_lots_complete': True, 'opening_lots': [],
            'fees_confirmed': True, 'corporate_actions_complete': True, 'actions': [],
            'terminal_price': 18.0, 'terminal_price_date': '2025-01-31'}
            for code, currency, timezone in [('SYNTH_CN', 'CNY', 'Asia/Shanghai'), ('SYNTH_US', 'USD', 'America/New_York')]]
        trades = []
        for security in securities:
            for n, operation, price in [(1, 'buy', 10.0), (2, 'buy', 20.0), (3, 'sell', 20.0)]:
                trades.append({'trade_id': security['code'] + '_' + str(n), 'code': security['code'],
                    'executed_at': f'2025-01-{[3, 6, 7][n-1]:02d}T15:00:00Z', 'sequence': 0,
                    'operation': operation, 'quantity': 100.0, 'price': price, 'fee': 1.0, 'other_cost': 0.0})
        return {'mode': 'QUALIFIED_RESEARCH', 'source_label': 'SYNTHETIC_COST_METHOD_COMPARISON',
            'date_from': '2025-01-02', 'date_to': '2025-01-31', 'securities': securities, 'trades': trades}
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
