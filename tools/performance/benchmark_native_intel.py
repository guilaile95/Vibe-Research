"""Offline, synthetic SQLite benchmark for the production Native Intel trending path.

Run the same script against two checkouts via --source-root. No live credentials,
network, real user records, or application lifespan. OS filesystem cache is not
purged: first_call is application-cold, repeated samples are warm filesystem runs.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import statistics
import sys
import tempfile
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--operation', choices=['trending', 'status'], default='trending')
    parser.add_argument('--rows', type=int, default=500)
    parser.add_argument('--history', type=int, default=20)
    parser.add_argument('--top-n', type=int, default=20)
    parser.add_argument('--samples', type=int, default=15)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= 5000 or not 1 <= args.history <= 100 or not 1 <= args.samples <= 100:
        parser.error('bounded fixture/sample sizes required')
    source = args.source_root.resolve()
    sys.path.insert(0, str(source / 'tools'))
    from validation_environment import configure_pytest_environment
    with tempfile.TemporaryDirectory(prefix='vr-perf-intel-') as directory:
        root = Path(directory)
        configure_pytest_environment(root, os.environ)
        def deny(*_a, **_kw):
            raise RuntimeError('network prohibited in offline performance benchmark')
        with patch.object(socket, 'create_connection', deny), patch.object(socket, 'getaddrinfo', deny):
            sys.path.insert(0, str(source / 'backend'))
            import native_intel_store as store
            import native_intel_service as service
            now = datetime(2026, 10, 24, 10, tzinfo=timezone.utc)
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return now if tz else now.replace(tzinfo=None)
            store.datetime = Clock
            service.datetime = Clock
            path = root / 'fixture.sqlite3'
            store.initialize_store(path)
            stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
            source_id = 'hotlist-perf-synthetic'
            store.upsert_sources([dict(source_id=source_id, name='Synthetic benchmark', hint='a-share',
                url='https://example.invalid/perf', source_type='hotlist', has_real_rank=True)], path)
            # Bulk fixture setup is deliberately outside timing; exercised read path is production.
            with sqlite3.connect(path) as conn:
                for h in range(args.history):
                    observed = (now - timedelta(hours=args.history - h - 1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                    run = f'perf-{h:04d}'
                    conn.execute('INSERT INTO intel_fetch_runs (run_id,started_at,finished_at,status,trigger,source_total,source_ok,source_failed,item_seen,item_new) VALUES (?,?,?,?,?,1,1,0,?,?)',
                        (run, observed, observed, 'ok', 'benchmark', args.rows, args.rows if h == 0 else 0))
                    conn.execute('INSERT INTO intel_source_runs (run_id,source_id,status,item_count) VALUES (?,?,?,?)', (run, source_id, 'ok', args.rows))
                for i in range(1, args.rows + 1):
                    title = f'Synthetic market item {i:06d}'
                    conn.execute('INSERT INTO intel_items (item_id,item_key,canonical_url,url,title,title_key,summary,source_id,hint,first_seen_at,last_seen_at,observation_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (i, f'{source_id}:{i}', f'https://example.invalid/{i}', f'https://example.invalid/{i}', title, title, 'Synthetic evidence only', source_id, 'a-share', stamp, stamp, args.history, stamp))
                    for h in range(args.history):
                        observed = (now - timedelta(hours=args.history - h - 1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                        conn.execute('INSERT INTO intel_observations (run_id,item_id,source_id,observed_at,rank,observed_title) VALUES (?,?,?,?,?,?)',
                            (f'perf-{h:04d}', i, source_id, observed, (i + h) % args.rows + 1, title))
            original_connect = sqlite3.connect
            counts = {'connections': 0, 'statements': 0, 'rank_reads': 0}
            rank_entry = '_item_rank_state' if hasattr(store, '_item_rank_state') else 'get_item_rank_state'
            original_rank = getattr(store, rank_entry)
            def traced_connect(*a, **kw):
                counts['connections'] += 1
                conn = original_connect(*a, **kw)
                def trace(_statement):
                    counts['statements'] += 1
                conn.set_trace_callback(trace)
                return conn
            def rank(*a, **kw):
                counts['rank_reads'] += 1
                return original_rank(*a, **kw)
            def once(instrument=False):
                counts.update({k: 0 for k in counts})
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                result = (service.trending(str(path), top_n=args.top_n) if args.operation == 'trending'
                          else service.status(str(path)))
                if args.operation == 'status':
                    result['store']['db_path'] = '<SYNTHETIC_DB>'
                elapsed = (time.perf_counter_ns() - wall) / 1e6
                cpu_ms = (time.process_time_ns() - cpu) / 1e6
                digest = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                return dict(wall_ms=elapsed, cpu_ms=cpu_ms, sha256=digest,
                            counts=dict(counts) if instrument else None,
                            returned_items=len(result.get('items', [])), item_count=result.get('item_count', result.get('store', {}).get('item_count')))
            cold = once()
            samples = [once() for _ in range(args.samples)]
            with patch.object(sqlite3, 'connect', traced_connect), patch.object(store, rank_entry, rank):
                counted = once(True)
            def stats(key):
                vals = sorted(x[key] for x in samples)
                return dict(p50=statistics.median(vals), p95=vals[max(0, __import__('math').ceil(len(vals)*.95)-1)], min=vals[0], max=vals[-1])
            output = dict(schema='native-intel-performance.v1', environment=dict(python=sys.version, platform=platform.platform(), cpu_count=os.cpu_count()),
                          fixture=dict(operation=args.operation, rows=args.rows, history=args.history, top_n=args.top_n, samples=args.samples, network='DENIED', inputs='SYNTHETIC', database='SQLite file, normal production connection settings'),
                          first_call=cold, samples=samples, instrumented=counted, wall_ms=stats('wall_ms'), cpu_ms=stats('cpu_ms'),
                          stable_output=len({x['sha256'] for x in [cold, *samples, counted]}) == 1)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2) + '\n')
            print(json.dumps({k: output[k] for k in ('fixture','wall_ms','cpu_ms','instrumented','stable_output')}, indent=2))


if __name__ == '__main__':
    main()
