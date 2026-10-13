"""Offline adapters for existing quote parser and bounded raw announcement pages.

No requests are sent here. An authorized existing runtime can pass a response to
these functions; this release does not register a timer or activate ingestion.
"""
from datetime import datetime
import re

import observation_workflows as obs


def tencent_quote_rows(response):
    """Adapt astock.tencent_quote's existing normalized response without fetching."""
    from astock import get_prefix
    if not isinstance(response, dict) or len(response) > 200:
        raise obs.ObservationError('腾讯报价批次无效')
    rows = []
    for code, item in response.items():
        if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code) or not isinstance(item, dict):
            raise obs.ObservationError('腾讯报价身份无效')
        at = item.get('data_time')
        try:
            at = datetime.fromisoformat(at)
            if at.tzinfo is None or item.get('trade_date') != at.astimezone(obs.SHANGHAI).date().isoformat():
                raise ValueError()
            at = obs.stamp(at)
        except (TypeError, ValueError):
            at = None
        price, limit = item.get('price'), item.get('limit_up')
        limit_state = abs(price-limit) < .005 if obs.finite(price, True) and obs.finite(limit, True) else None
        amount = item.get('amount_wan')
        rows.append({'symbol': get_prefix(code)+code, 'price': price, 'open_price': item.get('open'),
                     'previous_close': item.get('last_close'), 'provider_at': at, 'source_id': 'tencent:qt.gtimg.cn',
                     'is_limit_up': limit_state,
                     'turnover_yuan': amount*10000 if obs.finite(amount) and amount >= 0 and obs.finite(amount*10000) else None})
    return rows


def tencent_raw_capture(text):
    """Reuse the existing provider parser; unknown provider time stays unknown."""
    from astock import _parse_gtimg
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise obs.ObservationError('腾讯报价响应无效')
    return tencent_quote_rows(_parse_gtimg(text))


def capture_using_existing_quote_port(day, slot, groups, quote_port):
    """Finite adapter for an approved runtime's existing batched quote port."""
    return obs.capture_slot(day, slot, groups, lambda prefixed: tencent_quote_rows(quote_port([code[2:] for code in prefixed])))


def eastmoney_announcement_page(response, code, since, through):
    """Full <=50 raw page only; no total/partial/page overflow never advances cursor.

    Provider notice_date must include time. Date-only availability cannot become
    midnight source availability. Whole source page is validated before filtering.
    """
    obs.symbol(code)
    if not isinstance(response, dict) or not isinstance(response.get('data'), dict):
        return {'status': 'NOT_CHECKED', 'reason': 'SOURCE_ENVELOPE_MISSING'}
    data = response['data']
    rows, total = data.get('list'), data.get('total_hits')
    if (not isinstance(rows, list) or type(total) is not int or total < 0 or total > 50
            or len(rows) != total or data.get('page_index', 1) != 1):
        return {'status': 'NOT_CHECKED', 'reason': 'WHOLE_BOUNDED_BATCH_REQUIRED'}
    until = obs.instant(through)
    start = obs.instant(since) if since else None
    items, seen = [], set()
    for item in rows:
        if (not isinstance(item, dict) or not isinstance(item.get('art_code'), str) or not item['art_code']
                or item['art_code'] in seen or not isinstance(item.get('title'), str) or not item['title'].strip()
                or not isinstance(item.get('codes'), list) or not any(isinstance(c, dict) and c.get('stock_code') == code[2:] for c in item['codes'])):
            raise obs.ObservationError('公告提供商记录身份冲突')
        seen.add(item['art_code'])
        raw = item.get('notice_date')
        if not isinstance(raw, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[+]08:00)?', raw):
            raise obs.ObservationError('公告只有日期或没有可确认时间')
        at = datetime.fromisoformat(raw)
        at = at.replace(tzinfo=obs.SHANGHAI) if at.tzinfo is None else at
        if at > until:
            raise obs.ObservationError('公告来源时间在读取窗口之后')
        if start is not None and at <= start:
            continue
        items.append({'id': item['art_code'], 'symbol': code, 'title': item['title'],
                      'published_at': obs.stamp(at), 'source_id': 'eastmoney:security/ann'})
    return {'status': 'COMPLETE', 'since': since, 'through': through, 'has_more': False,
            'items': sorted(items, key=lambda i: (i['published_at'], i['id']))}
