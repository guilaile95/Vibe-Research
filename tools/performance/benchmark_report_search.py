"""Offline scoped-report search benchmark; synthetic catalog, no model/network calls.

Run this same script with --repo pointing at baseline and candidate checkouts.
Each sample executes the public search function including its filesystem integrity
reads; the OS page cache is warm. This is not a user-machine or cold-disk result.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--sizes-mib', type=int, nargs='+', default=[1, 8, 32])
    parser.add_argument('--repeats', type=int, default=25)
    parser.add_argument('--operation', choices=['search', 'context'], default='search')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    sys.path[:0] = [str(args.repo / 'backend'), str(args.repo / 'tools')]
    from validation_environment import configure_pytest_environment
    with tempfile.TemporaryDirectory(prefix='vr-report-performance-') as temp:
        root = Path(temp)
        configure_pytest_environment(root, os.environ)
        import myreports_fulltext as ft
        import myreports as mr
        import fact_lake_store as lake
        results = []
        for size in args.sizes_mib:
            reports_dir = root / f'reports-{size}'
            reports_dir.mkdir()
            text = 'semiconductor evidence ' * 50
            source = text.encode()
            sha = hashlib.sha256(source).hexdigest()
            (reports_dir / 'selected.txt').write_bytes(source)
            report = {'id': 'selected', 'ext': '.txt', 'file_sha256': sha, 'title': 'Synthetic report'}
            conn = ft._connect_write(reports_dir)
            conn.execute('BEGIN')
            for rid in ['selected', 'unrelated']:
                conn.execute('INSERT INTO report_text_index VALUES (?,?,?,?,?,?)',
                             (rid, sha, ft.STATUS_SEARCHABLE, '2026-10-24T00:00:00Z', None, ''))
            conn.execute('INSERT INTO report_text_chunks VALUES (?,?,?)', ('selected', 1, text))
            # Unselected text grows the shared index without altering query results.
            chunk = 'unrelated source text ' * 2000
            for page in range(math.ceil(size * 1024 * 1024 / len(chunk))):
                conn.execute('INSERT INTO report_text_chunks VALUES (?,?,?)', ('unrelated', page + 1, chunk))
            conn.execute('COMMIT'); conn.close()
            actual_size = ft._path(reports_dir).stat().st_size
            hits = ft.search(reports_dir, [report], 'semiconductor', report_ids=['selected'])
            assert len(hits) == 1
            (reports_dir / 'index.json').write_text(json.dumps([report]))
            mr.REPORTS_DIR = reports_dir
            operation = (lambda: ft.search(reports_dir, [report], 'semiconductor', report_ids=['selected'])) if args.operation == 'search' else (lambda: mr.build_chat_report_context(hits, report_ids=['selected']))
            expected = operation()
            counters = {'snapshot_reads': 0, 'snapshot_bytes': 0}
            original = lake._ControlSnapshot.read_bounded
            def tracked(self):
                value = original(self)
                counters['snapshot_reads'] += 1
                counters['snapshot_bytes'] += len(value)
                return value
            lake._ControlSnapshot.read_bounded = tracked
            samples = []
            cpu_samples = []
            try:
                for _ in range(args.repeats):
                    cpu = time.process_time_ns(); start = time.perf_counter_ns()
                    actual = operation()
                    samples.append((time.perf_counter_ns() - start) / 1e6)
                    cpu_samples.append((time.process_time_ns() - cpu) / 1e6)
                    assert actual == expected
            finally:
                lake._ControlSnapshot.read_bounded = original
            results.append({'requested_mib': size, 'index_bytes': actual_size,
                            'samples_ms': samples, 'cpu_samples_ms': cpu_samples,
                            'p50_ms': statistics.median(samples),
                            'p95_ms': sorted(samples)[math.ceil(.95 * len(samples)) - 1],
                            'snapshot_reads_per_query': counters['snapshot_reads'] / args.repeats,
                            'snapshot_bytes_per_query': counters['snapshot_bytes'] / args.repeats,
                            'result_sha256': hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()})
        output = {'python': platform.python_version(), 'platform': platform.platform(),
                  'environment': 'isolated synthetic, warm filesystem cache, no external calls',
                  'repeats': args.repeats, 'operation': args.operation, 'results': results}
        data = json.dumps(output, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(data + '\n')
        print(data)

if __name__ == '__main__':
    main()
