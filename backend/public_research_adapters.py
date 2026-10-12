"""Native parsers for fixed public providers, independently implemented from contracts.

Only bytes are parsed. No upstream code is imported or executed. Every returned
number is qualified by source, time, identity, units and incomplete coverage.
"""
from datetime import datetime, timezone
import json
import re
import public_research_contract as C

NORMALIZER = 'public-research-adapter.v1'


def _source_time(value, captured):
    if value is None or value == '':
        return None
    normalized = C.utc(value)
    if C.stamp(normalized) > C.stamp(captured):
        raise ValueError('future provider timestamp')
    return normalized


def _source_day(value, captured):
    result = C.day(value)
    if result > C.stamp(captured).date().isoformat():
        raise ValueError('future provider date')
    return result


def _optional_number(value, maximum=1e18):
    return None if value is None or value == '' else C.number(value, maximum=maximum)


def _list(value):
    if type(value) is str:
        value = C.decode(value.encode())
    return C.rows(value)


def _row(key, title, value, currency, unit, source_date=None, source_time=None, **extra):
    return {'id': C.text(key), 'title': C.text(title), 'value': value, 'currency': currency, 'unit': unit,
            'source_date': source_date, 'source_time': source_time, 'status': 'normal', 'missing': [], **extra}


def _events(source, data, captured):
    markets = C.rows(data if source == 'public_polymarket' else data.get('markets'))
    output = []
    for m in markets:
        if type(m) is not dict:
            raise ValueError('invalid market object')
        if source == 'public_polymarket':
            contract = C.text(m.get('conditionId'))
            question_id = C.text(m['questionID']) if m.get('questionID') else None
            market_id = C.text(m.get('id'))
            title = C.text(m.get('question'))
            outcomes, prices, tokens = (_list(m.get(k)) for k in ('outcomes', 'outcomePrices', 'clobTokenIds'))
            if not outcomes or len(outcomes) != len(prices) or len(outcomes) != len(tokens):
                raise ValueError('outcome identity mismatch')
            if type(m.get('closed')) is not bool or type(m.get('active')) is not bool:
                raise ValueError('unknown market state')
            status = 'closed' if m['closed'] else 'open' if m['active'] else 'inactive'
            source_time = _source_time(m.get('updatedAt'), captured)
            resolution = m.get('umaResolutionStatus')
            if resolution is not None:
                C.text(resolution, 80)
            for label, price, token in zip(outcomes, prices, tokens):
                key = C.text(token, 160)
                row = _row(contract + ':' + key, title, _optional_number(price, 1), 'USD', 'USD-equivalent per outcome share', source_time=source_time,
                    question_id=question_id, market_id=market_id, contract_id=contract, outcome_id=key, outcome=C.text(label),
                    price_convention='provider_outcome_price_0_to_1', bid=None, ask=None,
                    market_status=status, resolution_status=resolution or 'unknown', settlement_currency='provider collateral; not verified',
                    volume_24h=_optional_number(m.get('volume24hr')), volume_unit='USD-equivalent', open_interest=None,
                    close_time=C.utc(m['endDate']) if m.get('endDate') else None)
                output.append(row)
        else:
            contract = C.text(m.get('ticker'), 160)
            question_id = C.text(m.get('event_ticker'), 160)
            source_time = _source_time(m.get('updated_time'), captured)
            status = C.text(m.get('status'), 40)
            if status not in ('initialized', 'inactive', 'active', 'open', 'closed', 'settled', 'finalized', 'determined', 'disputed', 'amended'):
                raise ValueError('unknown Kalshi market status')
            # Dollar fixed-point fields are not legacy cents; never mix them.
            bid, ask = (_optional_number(m.get(k), 1) for k in ('yes_bid_dollars', 'yes_ask_dollars'))
            last = _optional_number(m.get('last_price_dollars'), 1)
            if bid is not None and ask is not None and bid > ask:
                raise ValueError('crossed source quote')
            closed_state = status in ('closed', 'settled', 'finalized', 'determined')
            book_usable = bid is not None and ask is not None and (ask > 0 or closed_state)
            # Zero ask is ambiguous in an open book; do not turn it into a zero midpoint.
            # Preserve the provider's raw bid/ask for audit, without certifying sentinel semantics.
            usable_last = last if closed_state or last is None or last > 0 else None
            price = (bid + ask) / 2 if book_usable else usable_last
            convention = 'yes_bid_ask_midpoint_dollars' if book_usable else 'yes_last_trade_dollars' if usable_last is not None else 'unquoted'
            row = _row(contract + ':yes', C.text(m.get('title')), price, 'USD', 'USD per YES contract', source_time=source_time,
                question_id=question_id, question_id_semantics='provider event_ticker', contract_id=contract, outcome_id=contract + ':yes', outcome='Yes',
                price_convention=convention, bid=bid, ask=ask, market_status=status,
                resolution_status=C.text(m.get('result'), 40) if m.get('result') else 'unknown', settlement_currency='USD',
                volume_24h=_optional_number(m.get('volume_24h_fp')), volume_unit='contracts',
                open_interest=_optional_number(m.get('open_interest_fp')), close_time=C.utc(m['close_time']) if m.get('close_time') else None)
            if not book_usable:
                row['missing'].append('AMBIGUOUS_OR_MISSING_BOOK')
            if last == 0 and not closed_state:
                row['missing'].append('ZERO_LAST_TRADE_UNVERIFIED')
            output.append(row)
    for row in output:
        if row['market_status'] in ('closed', 'settled', 'finalized', 'determined'):
            row['status'] = 'closed'
        if row['question_id'] is None:
            row['missing'].append('QUESTION_ID_UNKNOWN')
        if row['value'] is None:
            row['missing'].append('PRICE_MISSING')
        if row['source_time'] is None:
            row['missing'].append('SOURCE_UPDATE_TIME_UNKNOWN')
        if row['volume_24h'] is None:
            row['missing'].append('LIQUIDITY_UNKNOWN')
        row['objective_probability'] = None
    return output, ['BOUNDED_MARKET_SAMPLE_NOT_UNIVERSE']


def _taiwan(data, subject, captured):
    months = {}
    for item in C.rows(data.get('data')):
        if type(item) is not dict:
            raise ValueError('invalid revenue object')
        if item.get('stock_id') != subject:
            raise ValueError('issuer mismatch')
        y, m = item.get('revenue_year'), item.get('revenue_month')
        if type(y) is not int or type(m) is not int or not 2000 <= y <= 2100 or not 1 <= m <= 12:
            raise ValueError('invalid revenue period')
        period = f'{y:04d}-{m:02d}'
        if period >= captured[:7]:
            raise ValueError('uncompleted or future reporting period')
        publication = _source_day(item.get('date'), captured)
        if publication[:7] < period:
            raise ValueError('publication before reporting period')
        entry = (C.number(item.get('revenue')), publication)
        if period in months and months[period] != entry:
            raise ValueError('conflicting revenue revision')
        months[period] = entry
    if not months:
        return [], ['NO_REVENUE_ROWS']
    period = max(months)
    value, publication = months[period]
    basis = f'{int(period[:4])-1:04d}{period[4:]}'
    previous = months.get(basis)
    raw_yoy = (value / previous[0] - 1) * 100 if previous and previous[0] > 0 else None
    # Bounds + finite JSON check also cover ratio arithmetic overflow.
    C.canonical(raw_yoy)
    row = _row(subject + ':' + period, subject + ' 月营收', value, 'TWD', 'TWD', source_date=publication,
        issuer=subject, reporting_period=period, comparison_period=basis,
        comparison_value=previous[0] if previous else None, source_series_yoy_pct=raw_yoy,
        yoy_pct=None, comparable_basis='same issuer/month/TWD/FinMind series; consolidation and restatement not verified',
        consolidation_scope='not disclosed by source', revision_id=None, revision_semantics='unknown; raw capture version retained')
    row['missing'] = ['CONSOLIDATION_AND_REVISION_COMPARABILITY_UNKNOWN'] + ([] if raw_yoy is not None else ['YOY_DENOMINATOR_MISSING_OR_ZERO'])
    return [row], []


def _dated_price(data, source, subject, captured):
    if source == 'dram_spot_thermo':
        key, field = ('logs', 'session_average') if subject == 'DDR4' else ('ddr5' if subject == 'DDR5' else 'tlc', 'session_avg')
        values = C.rows(data.get(key))
        grade = data.get('product') if subject == 'DDR4' else None
        if grade is not None:
            C.text(grade)
    else:
        values, grade = C.rows(data), None
    dates = {}
    for item in values:
        if source == 'dram_spot_thermo':
            if type(item) is not dict:
                raise ValueError('invalid DRAM object')
            raw_date, value = item.get('date'), item.get(field)
            # Two explicit provider date grammars, never slice arbitrary text.
            if type(raw_date) is str and re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', raw_date):
                raw_date = datetime.strptime(raw_date, '%m/%d/%Y').date().isoformat()
            if type(value) is str and value.startswith('$'):
                value = value[1:]
        else:
            if type(item) is not list or len(item) != 8:
                raise ValueError('invalid futures daily row')
            raw_date, value = item[0], item[4]
        day = _source_day(raw_date, captured)
        price = C.number(value)
        if price <= 0:
            raise ValueError('nonpositive price')
        if day in dates and dates[day] != price:
            raise ValueError('conflicting daily price')
        dates[day] = price
    if not dates:
        return [], ['NO_PRICE_ROWS']
    day = max(dates)
    if source == 'dram_spot_thermo':
        row = _row(subject + ':' + day, subject, dates[day], 'USD', 'USD per chip (community convention)', source_date=day,
                   grade=grade, price_convention='community_transcribed_session_average', is_hbm_price=False,
                   unit_verification='community convention; official primary source not verified')
        row['missing'] = ['SECONDARY_SOURCE_UNIT_NOT_PRIMARY_VERIFIED'] + ([] if grade else ['EXACT_GRADE_UNKNOWN'])
    else:
        row = _row(subject + ':' + day, subject, dates[day], 'CNY', 'CNY per metric tonne', source_date=day,
                   contract_id=subject, exchange='GFEX' if subject == 'SI0' else 'SHFE', delivery_month=None,
                   contract_kind='continuous', active_delivery_contract=None, roll_adjustment='not disclosed',
                   price_convention='continuous_series_daily_close', change_pct=None)
        row['missing'] = ['DELIVERY_CONTRACT_AND_ROLL_BASIS_UNKNOWN']
    return [row], []


def _hiring(data, subject, captured):
    ats, board = subject.split(':')
    listings = {}
    duplicate_count = 0
    for item in C.rows(data.get('jobs')):
        if type(item) is not dict:
            raise ValueError('invalid listing object')
        raw_id = item.get('id')
        if type(raw_id) not in (str, int) or type(raw_id) is bool:
            raise ValueError('missing listing identity')
        key = C.text(str(raw_id), 160)
        title = C.text(item.get('title'))
        time = _source_time(item.get('updated_at') if ats == 'greenhouse' else item.get('publishedAt'), captured)
        entry = {'listing_id': key, 'title': title, 'source_time': time,
                 'time_semantics': 'updated_at' if ats == 'greenhouse' else 'publishedAt'}
        if key in listings:
            if listings[key] != entry:
                raise ValueError('conflicting listing identity')
            duplicate_count += 1
        listings[key] = entry
    row = _row(subject, subject, len(listings), None, 'unique public listing IDs',
               ats=ats, board=board, listing_count=len(listings), deduplicated_count=duplicate_count,
               listings=list(listings.values()), observation_date=captured[:10],
               source_date_semantics='per-listing source times; capture date is not posting date', fulfilled_hires=None)
    row['missing'] = ['LISTING_DATE_UNKNOWN'] if any(x['source_time'] is None for x in listings.values()) else []
    return [row], ['ZERO_LISTINGS_NOT_VERIFIED_NO_HIRING'] if not listings else []


def normalize(raw, source, subject, captured, *, now=None):
    from public_research_extended_contract import SPECS
    if source in SPECS:
        from public_research_extended_adapters import normalize_extended
        return normalize_extended(raw, source, subject, captured, now=now)
    spec = C.identity(source, subject)
    captured = C.utc(captured)
    now = now or datetime.now(timezone.utc)
    if C.stamp(captured) > now:
        raise ValueError('future capture')
    # JSONP is inert text: exact fixed callback wrapper only, no eval or JS VM.
    if source == 'cn_commodity_futures':
        if type(raw) is not bytes or len(raw) > C.MAX_BYTES:
            raise ValueError('invalid raw bytes')
        match = re.fullmatch(rb'\s*var _V21052021_4_12=\((.*)\);?\s*', raw, flags=re.S)
        if not match:
            raise ValueError('invalid fixed JSONP wrapper')
        data = C.decode(match.group(1))
    else:
        data = C.decode(raw)
    if source in ('public_kalshi', 'tw_monthly_revenue', 'dram_spot_thermo', 'hiring_anchor_signal') and type(data) is not dict:
        raise ValueError('invalid provider object')
    if source.startswith('public_'):
        output, reasons = _events(source, data, captured)
    elif source == 'tw_monthly_revenue':
        output, reasons = _taiwan(data, subject, captured)
    elif source == 'hiring_anchor_signal':
        output, reasons = _hiring(data, subject, captured)
    else:
        output, reasons = _dated_price(data, source, subject, captured)
    if len(output) > 500 or len({x['id'] for x in output}) != len(output):
        raise ValueError('duplicate or excessive normalized rows')
    for row in output:
        reference = C.stamp(row['source_time']) if row['source_time'] else datetime.fromisoformat(row['source_date']).replace(tzinfo=timezone.utc) if row['source_date'] else C.stamp(captured)
        row['stale'] = (now - reference).total_seconds() > spec['stale_days'] * 86400
        if row['status'] != 'closed':
            row['status'] = 'stale' if row['stale'] else 'partial' if row['missing'] else 'normal'
    result = {'schema_version': C.VERSION, 'source_id': source, 'subject': subject, 'label': spec['label'],
              'status': 'missing' if not output else 'partial' if reasons or any(x['status'] != 'normal' for x in output) else 'normal',
              'rows': output, 'reason_codes': reasons, 'guard': spec['guard'], 'captured_at': captured,
              'observed_at': captured, 'source_url': C.request_spec(source, subject), 'license_status': 'PROVIDER_TERMS_NOT_VERIFIED',
              'coverage': 'bounded provider response; not universal coverage', 'normalizer_version': NORMALIZER}
    C.canonical(result)
    return result
