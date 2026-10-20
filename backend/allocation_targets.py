"""User-declared allocation targets; read-only comparison, never trade policy.

CN/CNY securities + cash only. Uses current holding authority and immutable quote
receipts; never fetches quotes or normalizes an incomplete book to 100%.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import observation_workflow_store as store
import position_reality_service as positions
import account_reality_service as accounts
from portfolio_risk_context import _account_sections
from public_research_extended_service import load_blocks


class TargetInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    expected_version: int = Field(strict=True, ge=0)
    effective_date: date
    market: Literal['CN']
    currency: Literal['CNY']
    basis: Literal['CONFIRMED_ACCOUNT_ASSETS']
    coverage: Literal['PARTIAL', 'FULL']
    targets: dict[str, float] = Field(min_length=1, max_length=101)

    @model_validator(mode='before')
    @classmethod
    def weights(cls, value):
        targets = value.get('targets', {}) if isinstance(value, dict) else {}
        if not isinstance(value, dict) or not isinstance(targets, dict):
            raise ValueError('Target mapping required')
        for key, weight in targets.items():
            if not isinstance(key, str) or key != 'CASH' and not re.fullmatch(r'(?:[0368][0-9]{5})', key):
                raise ValueError('Only CN security codes and CASH are supported')
            if type(weight) not in (int, float) or not math.isfinite(weight) or not 0 <= weight <= 100 or Decimal(str(weight)).as_tuple().exponent < -2:
                raise ValueError('Weights require 0–100 percent with at most two decimals')
        total = sum((Decimal(str(x)) for x in targets.values()), Decimal(0))
        if total > 100 or (value.get('coverage') == 'FULL' and total != 100):
            raise ValueError('Full targets must sum to exactly 100%; partial targets must not exceed 100%')
        return value


def _records(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='allocation_targets' AND type='table'").fetchone():
        return []
    rows = conn.execute('SELECT version,payload FROM allocation_targets ORDER BY version LIMIT 501').fetchall()
    if len(rows) > 500:
        raise store.StoreError('Target history exceeds limit')
    out = []
    try:
        for version, payload in rows:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise ValueError('duplicate field')
                    result[key] = value
                return result
            if not isinstance(payload, str) or len(payload.encode()) > 32768: raise ValueError('invalid payload size')
            record = json.loads(payload, object_pairs_hook=unique)
            if set(record) != {'version', 'created_at', 'input'} or type(version) is not int or version != len(out) + 1 or type(record['version']) is not int or record['version'] != version:
                raise ValueError('invalid version')
            parsed = TargetInput.model_validate(record['input'])
            if parsed.expected_version != version - 1: raise ValueError('invalid parent version')
            datetime.fromisoformat(record['created_at'].replace('Z', '+00:00'))
            out.append(record)
    except (ValueError, TypeError, KeyError):
        raise store.StoreError('Target history cannot be verified') from None
    return out


def history():
    with store.read() as conn:
        return _records(conn)


def save(body: TargetInput):
    with store.write() as conn:
        records = _records(conn)
        if len(records) != body.expected_version:
            raise LookupError('Targets changed; reload before saving')
        if len(records) >= 500: raise ValueError('Target version limit reached')
        record = {'version': len(records) + 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'input': body.model_dump(mode='json')}
        conn.execute('INSERT INTO allocation_targets(version,payload) VALUES (?,?)', (record['version'], store.encode(record)))
    return record


def cached_quotes(codes, today):
    # Existing archive reader bounds each immutable image to eleven receipts.
    if len(codes) > 11: return {}, ['QUOTE_ARCHIVE_BUDGET_EXCEEDED']
    if not codes: return {}, []
    blocks, error = load_blocks([('cn_quote_ref', f'A:{code}@{today}') for code in codes])
    if error: return {}, [error]
    result = {}
    for block in blocks:
        code = block.get('symbol')
        if block.get('fixture') is not False or block.get('archive_stale') is not False or block.get('status') != 'normal':
            continue
        for row in block.get('rows', []):
            q = row.get('quote', {})
            age = row.get('quote_age_seconds_at_capture')
            if row.get('symbol') != code or q.get('symbol') != code or q.get('currency') != 'CNY' or row.get('source_stale') is not False or type(age) not in (int, float) or not 0 <= age <= 300:
                continue
            try:
                source_time = datetime.fromisoformat(q['source_time'].replace('Z', '+00:00'))
                source_age = (datetime.now(timezone.utc) - source_time).total_seconds()
                if not 0 <= source_age <= 300: continue
            except (ValueError, KeyError, TypeError):
                continue
            result[code] = {'price': q.get('price'), 'currency': q.get('currency'), 'source_time': q.get('source_time'), 'receipt': block.get('evidence'), 'industry': 'UNKNOWN'}
    return result, []


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def compare(records, snapshot, account, quotes, *, today, authority='CANONICAL', reasons=()):
    active = [r for r in records if r['input']['effective_date'] <= today]
    selected = max(active, key=lambda r: (r['input']['effective_date'], r['version'])) if active else None
    result = {'schema_version': 'allocation-targets.v1', 'latest_version': records[-1]['version'] if records else 0,
              'versions': records, 'active_version': selected['version'] if selected else None,
              'status': 'NOT_CONFIGURED' if not records else 'NOT_EFFECTIVE' if not selected else 'UNAVAILABLE',
              'as_of': datetime.now(timezone.utc).isoformat(),
              'valid_until': min(datetime.now(timezone.utc) + timedelta(seconds=300),
                                 datetime.combine(datetime.now(timezone.utc).date() + timedelta(days=1), datetime.min.time(), timezone.utc)).isoformat(), 'market': 'CN', 'currency': 'CNY',
              'basis': 'CONFIRMED_ACCOUNT_ASSETS', 'denominator': None, 'rows': [], 'reasons': list(reasons),
              'coverage': {'holding_count': 0, 'priced_count': 0, 'unknown_industry_count': 0},
              'limitations': ['只读当前 mixed-time 账户资产比较，不是正式 NAV、投资建议或调仓指令。',
                             '仅 CN/CNY 证券和现金；无汇率换算。行业分类未知，不推断行业目标。',
                             '仅使用今日截止的已归档真实报价；报价/归档超过 300 秒不可比较。最多 11 只持仓。',
                             '未配置的目标保持未知；部分目标不补齐到 100%。']}
    if not selected: return result
    gaps = result['reasons']
    if authority != 'CANONICAL': gaps.append('POSITION_AUTHORITY_NOT_CANONICAL')
    facts, total, cash, denominator, cash_value = _account_sections(account)
    currency_declarations = [account.get('currency', 'CNY')]
    for section in ('account_total_assets', 'cash'):
        currency_declarations.append((account.get(section) or {}).get('current_fact', {}).get('currency', 'CNY'))
    if any(currency != 'CNY' for currency in currency_declarations): gaps.append('UNSUPPORTED_ACCOUNT_CURRENCY_NO_FX')
    if denominator is None or cash_value is None or not total.get('confirmation_id') or total.get('confirmation_id') != cash.get('confirmation_id'):
        gaps.append('ACCOUNT_CASH_DENOMINATOR_NOT_CONFIRMED')
    result['denominator'] = denominator
    raw = snapshot.get('holdings')
    holdings = raw if isinstance(raw, list) else []
    if not isinstance(raw, list): gaps.append('HOLDINGS_UNAVAILABLE')
    values = {}; seen = set(); details = {}
    for row in holdings:
        code = row.get('code') if isinstance(row, dict) else None
        shares = _number(row.get('shares')) if isinstance(row, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r'[0368][0-9]{5}', code) or code in seen or shares is None or shares < 0 or row.get('currency', 'CNY') != 'CNY':
            gaps.append('UNSUPPORTED_HOLDING_OR_CURRENCY'); continue
        seen.add(code)
        quote = quotes.get(code, {})
        price = _number(quote.get('price'))
        if shares == 0:
            values[code] = 0.0
        elif price is None or price <= 0 or quote.get('currency') != 'CNY':
            gaps.append('MISSING_OR_STALE_QUOTE:' + code)
        else:
            market_value = shares * price
            if not math.isfinite(market_value):
                gaps.append('INVALID_MARKET_VALUE:' + code); continue
            values[code] = market_value
            details[code] = quote
    result['coverage'] = {'holding_count': len(holdings), 'priced_count': len(values), 'unknown_industry_count': len(holdings)}
    if cash_value is not None: values['CASH'] = cash_value
    if denominator is not None and not gaps and abs(sum(values.values()) - denominator) > max(.01, denominator * .000001):
        gaps.append('ACCOUNT_ASSET_RECONCILIATION_GAP')
    targets = selected['input']['targets']
    comparable = not gaps
    for code in sorted(set(values) | set(targets) | seen):
        # Absence is a proven zero holding only with a complete canonical book.
        actual = round(values.get(code, 0) / denominator * 100, 4) if comparable else None
        target = targets.get(code)
        result['rows'].append({'key': code, 'target_pct': target, 'actual_pct': actual,
                               'drift_pp': round(actual - target, 4) if actual is not None and target is not None else None,
                               'reason': 'TARGET_NOT_CONFIGURED' if target is None else None if comparable else 'ACTUAL_NOT_COMPARABLE',
                               'quote': details.get(code), 'industry': None if code == 'CASH' else 'UNKNOWN'})
    expiries = [datetime.fromisoformat(q['source_time'].replace('Z', '+00:00')) + timedelta(seconds=300) for q in details.values() if q.get('source_time')]
    if expiries: result['valid_until'] = min([datetime.fromisoformat(result['valid_until']), *expiries]).isoformat()
    result['status'] = 'COMPARABLE' if comparable else 'UNAVAILABLE'
    result['reasons'] = sorted(set(gaps))
    return result


def current():
    records = history(); today = datetime.now(timezone.utc).date().isoformat()
    if not records: return compare(records, {}, {}, {}, today=today)
    try:
        authority = positions.get_holding_authority_state()
        snapshot = positions.read_current_holdings_snapshot()
        account = accounts.get_account_reality()
        codes = sorted({r['code'] for r in snapshot['holdings'] if _number(r.get('shares')) != 0})
        if any(not re.fullmatch(r'[0368][0-9]{5}', code) for code in codes):
            quotes, reasons = {}, ['UNSUPPORTED_MARKET_NO_FX']
        else:
            quotes, reasons = cached_quotes(codes, today)
        if snapshot != positions.read_current_holdings_snapshot() or authority != positions.get_holding_authority_state() or _account_sections(account) != _account_sections(accounts.get_account_reality()):
            reasons.append('ACTUAL_CHANGED_DURING_READ')
        return compare(records, snapshot, account, quotes, today=today, authority=authority, reasons=reasons)
    except Exception:
        return compare(records, {}, {}, {}, today=today, authority='UNAVAILABLE', reasons=['ACTUAL_SNAPSHOT_UNAVAILABLE'])
