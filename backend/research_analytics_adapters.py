"""Local read-only RDP / authoritative Trade Ledger adapters. No data collection."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from research_analytics import digest, envelope, performance, xirr
from research_analytics_contract import LedgerPerformanceRequest, PerformanceRequest, RdpRequest


_UTC_STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|\+00:00)$')


def _current_rdp_snapshot(rdp):
    raw = json.loads(rdp._manifest_path(rdp.resolve_root()).read_text(encoding='utf8'))
    snapshot_id = hashlib.sha256(rdp._canonical_bytes(raw)).hexdigest()
    rdp.read_manifest(snapshot_id=snapshot_id)
    return snapshot_id


def rdp_inputs(request: RdpRequest):
    import research_data_plane as rdp
    instruments, receipts, missing = [], [], []
    dates = set()
    try:
        snapshot_id = _current_rdp_snapshot(rdp)  # existing archive required, never auto-archive
    except (OSError, ValueError, rdp.ResearchDataPlaneError):
        return envelope(request, status='MISSING_INPUTS', missing=[{'reason': 'RDP_ARCHIVED_SNAPSHOT_REQUIRED'}], instruments=[], receipts=[])
    for code in request.codes:
        rows = []
        try:
            for offset in (0, 1000):
                report = rdp.query_daily_bars(code=code, date_from=request.date_from, date_to=request.date_to,
                                              limit=1000, offset=offset, snapshot_id=snapshot_id)
                snapshot_id = report.get('snapshot_id', snapshot_id)
                rows.extend(report['rows'])
                receipts.append({'code': code, 'provenance': report.get('provenance'),
                                 'replay_receipt': report.get('replay_receipt')})
                if report.get('next_offset') is None:
                    break
            if len(rows) == 2000 and report.get('next_offset') is not None:
                missing.append({'code': code, 'reason': 'WINDOW_LIMIT_REQUIRES_NARROWER_DATES'})
        except rdp.ResearchDataPlaneError:
            missing.append({'code': code, 'reason': 'RDP_UNAVAILABLE_OR_INVALID'})
        dates.update(row['trade_date'] for row in rows)
        instruments.append({'code': code, 'currency': 'CNY', 'market': 'CN', 'weight': 1 / len(request.codes),
                            'bars': [{'date': row['trade_date'], 'open': row['open'], 'close': row['close'],
                                      'suspended': None, 'limit_up': None, 'limit_down': None, 'price_limit_rule': None, 'upper_price_limit': None, 'lower_price_limit': None} for row in rows],
                            'lot_size': None, 'settlement_sessions': None, 'fee_bps': None,
                            'min_fee': None, 'slippage_bps': None, 'corporate_actions_complete': False, 'actions': []})
    result = envelope(request, status='ADAPTER_INPUT_REQUIRES_QUALIFICATION', instruments=instruments,
                    observed_dates=sorted(dates), receipts=receipts, missing=missing,
                    required_contracts=['official session calendar (observed dates are not a calendar)',
                        'per-instrument lot, settlement, fee and slippage', 'per-session suspension and directional limits',
                        'complete raw-price corporate actions and payment dates'],
                    price_basis='RAW_WITH_EXPLICIT_ACTIONS')
    result['input_fingerprint'] = digest({'request': request.model_dump(), 'receipts': receipts, 'instruments': instruments})
    return result


def ledger_performance(request: LedgerPerformanceRequest, *, trades=None):
    import performance_attribution_service as pa
    import trade_ledger_service as ledger
    gaps = []
    if not request.ledger_fees_confirmed:
        gaps.append('LEGACY_LEDGER_FEES_REQUIRE_EXPLICIT_CONFIRMATION')
    if not request.opening_positions_complete:
        gaps.append('OPENING_POSITIONS_REQUIRE_COMPLETE_FIRST_CLOSE_SNAPSHOT')
    if any(i.market != 'CN' or i.currency != 'CNY' for i in request.instruments):
        gaps.append('CURRENT_AUTHORITATIVE_LEDGER_ADAPTER_SUPPORTS_CNY_A_SHARES_ONLY')
    codes = {i.code for i in request.instruments}
    if len({o.code for o in request.opening}) != len(request.opening) or any(o.code not in codes for o in request.opening):
        raise ValueError('opening identities must be unique panel members')
    bars = {i.code: {b.date: b for b in i.bars} for i in request.instruments}
    for i in request.instruments:
        if not i.corporate_actions_complete:
            gaps.append('CORPORATE_ACTION_CONTRACT_MISSING:' + i.code)
        if any(d not in bars[i.code] or bars[i.code][d].close is None for d in request.sessions):
            gaps.append('EXACT_SESSION_CLOSE_MISSING:' + i.code)
    if gaps:
        return envelope(request, status='MISSING_INPUTS', missing=gaps, twr=None, mwr=None)
    snapshot = None
    account_events = []
    if trades is None:
        from research_analytics_ledger import read_frozen_ledger
        try:
            snapshot, all_rows, account_events = read_frozen_ledger(ledger.resolve_db_path())
            # Corrections affect authoritative facts; never silently replay raw values.
            # A different code can later be targeted by a correction, so global active
            # correction presence fails this adapter closed pending governed replay.
            if any(e['event_type'] == 'CORRECTION' for e in account_events):
                return envelope(request, status='MISSING_INPUTS', missing=['ACTIVE_CORRECTION_REQUIRES_GOVERNED_RECONCILIATION'], twr=None, mwr=None)
            trades = [row for row in all_rows if row['execution_status'] != 'not_executed']
        except Exception:
            return envelope(request, status='MISSING_INPUTS', missing=['AUTHORITATIVE_LEDGER_UNAVAILABLE'], twr=None, mwr=None)
    if len(trades) > 10000:
        return envelope(request, status='MISSING_INPUTS', missing=['LEDGER_WINDOW_EXCEEDS_10000_TRADES'], twr=None, mwr=None)
    by_day, selected, opening_day = {}, [], []
    for trade in trades:
        raw = trade.get('executed_at')
        try:
            if not isinstance(raw, str) or not _UTC_STAMP.fullmatch(raw):
                raise ValueError('canonical UTC execution time required')
            stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('timezone required')
            day = stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        except (AttributeError, TypeError, ValueError):
            gaps.append('LEDGER_EXECUTION_TIME_INVALID')
            continue
        if not request.sessions[0] <= day <= request.sessions[-1]:
            continue
        if trade['code'] not in codes:
            # Explicit stock basket, not entire account: other securities are not silently claimed covered.
            continue
        if day == request.sessions[0]:
            opening_day.append(trade['trade_id'])
            continue  # declared post-close opening snapshot already incorporates these trades
        if day not in request.sessions:
            gaps.append('LEDGER_TRADE_OUTSIDE_SESSION_CALENDAR')
            continue
        for key in ('fee', 'other_cost', 'actual_price', 'actual_quantity'):
            value = trade.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1e12 or (key in {'actual_price', 'actual_quantity'} and value <= 0):
                gaps.append('INVALID_OR_UNKNOWN_LEDGER_' + key.upper())
        if trade['operation'] not in {'buy', 'add', 'reduce', 'sell'}:
            gaps.append('INVALID_LEDGER_OPERATION')
        selected.append(trade)
        by_day.setdefault(day, []).append(trade)
    if gaps:
        return envelope(request, status='MISSING_INPUTS', missing=sorted(set(gaps)), twr=None, mwr=None)
    held = {c: 0.0 for c in codes}
    held.update({o.code: o.quantity for o in request.opening})
    valuations, receivables, actual_flows = [], [], []
    for idx, day in enumerate(request.sessions):
        begin, end = 0.0, 0.0
        if idx:
            for i in request.instruments:
                for action in i.actions:
                    if action.ex_date == day:
                        amount = held[i.code] * action.dividend_per_old_share
                        receivables.append({'pay_date': action.pay_date, 'amount': amount})
                        if action.pay_date <= request.sessions[-1]:
                            actual_flows.append((action.pay_date, amount))
                        held[i.code] *= action.split_ratio
            for trade in by_day.get(day, []):
                qty, price = trade['actual_quantity'], trade['actual_price']
                cost = trade['fee'] + trade['other_cost']
                code = trade['code']
                if trade['operation'] in {'buy', 'add'}:
                    held[code] += qty
                    begin += qty * price + cost
                    actual_flows.append((day, -(qty * price + cost)))
                else:
                    if qty > held[code] + 1e-8:
                        return envelope(request, status='MISSING_INPUTS', missing=['SELL_EXCEEDS_RECONSTRUCTED_OPENING_QUANTITY'], twr=None, mwr=None)
                    held[code] -= qty
                    end -= qty * price - cost
                    actual_flows.append((day, qty * price - cost))
            due = sum(r['amount'] for r in receivables if r['pay_date'] <= day)
            end -= due
            receivables = [r for r in receivables if r['pay_date'] > day]
        value = sum(held[c] * bars[c][day].close for c in codes) + sum(r['amount'] for r in receivables)
        valuations.append({'date': day, 'value': value, 'flow_begin': begin, 'flow_end': end})
    adapted = PerformanceRequest(currency='CNY', scope='STOCK_BASKET', source_label='AUTHORITATIVE_TRADE_LEDGER_PLUS_EXPLICIT_VALUATIONS',
                                 valuations=valuations, fees_complete=True, corporate_actions_complete=True, coverage_complete=True)
    result = performance(adapted)
    if result['status'] == 'CALCULATED':
        # Ledger MWR keeps actual execution/payment dates; the daily TWR convention
        # remains an approximation because intraday valuations are unavailable.
        dated_flows = [(valuations[0]['date'], -valuations[0]['value'])]
        dated_flows.extend(actual_flows)
        dated_flows.append((valuations[-1]['date'], valuations[-1]['value']))
        result['mwr'] = xirr(dated_flows)
    result.update(input_fingerprint=digest({'version': result['schema_version'], 'request': request.model_dump(), 'selected_trades': selected, 'account_events': account_events}),
                  authority='TRADE_LEDGER_READ_ONLY_PLUS_UNVERIFIED_PRICE_ACTION_OPENING_ADAPTER',
                  selected_trade_ids=[t['trade_id'] for t in selected], opening_snapshot_incorporates_trade_ids=opening_day,
                  basket_codes=sorted(codes), whole_account_performance=False,
                  flow_convention='DAILY_APPROXIMATION: session purchases+costs treated before close-to-close return; net sales/dividends after return. MWR uses actual execution/payment dates; no intraday valuation claim',
                  opening_convention='FIRST_SESSION_POST_CLOSE_QUANTITIES_AT_FIRST_CLOSE_PRICES; NOT_HISTORICAL_COST')
    if snapshot is not None:
        try:
            snapshot.assert_unchanged()
        except Exception:
            return envelope(request, status='MISSING_INPUTS', missing=['AUTHORITATIVE_LEDGER_CHANGED_DURING_READ'], twr=None, mwr=None)
    return result
