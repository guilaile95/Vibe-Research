"""Explicit synthetic provider-shaped golden bytes. No real account or quote data."""
import json
from pathlib import Path

ROOT = Path(__file__).parent / 'fixtures' / 'public_research'
CAPTURED = '2026-10-01T12:00:00.000000Z'


def raw(source, subject):
    name = {'public_polymarket': 'polymarket.json', 'public_kalshi': 'kalshi.json',
            'tw_monthly_revenue': 'taiwan.json', 'dram_spot_thermo': 'dram.json',
            'cn_commodity_futures': 'commodity.txt', 'hiring_anchor_signal': 'hiring.json'}[source]
    body = (ROOT / name).read_bytes()
    # Only synthetic subject identity changes; schema and values remain pinned.
    if source == 'tw_monthly_revenue':
        body = body.replace(b'2383', subject.encode())
    return body


def seed(lake):
    import public_research_contract as C
    from public_research_archive import persist_capture
    for source, spec in C.SOURCES.items():
        for subject in spec['subjects']:
            persist_capture(lake, raw(source, subject), source, subject, CAPTURED, fixture=True)
