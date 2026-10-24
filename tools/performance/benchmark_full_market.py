"""Synthetic, offline real DuckDB/Parquet full-market query benchmark.

Same harness supports --source-root for before/after. Fixture setup excluded.
First call does not purge OS caches. Network prohibited, no service lifecycle.
"""
from __future__ import annotations
import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import sys
import tempfile
import time
from unittest.mock import patch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument('--codes', type=int, default=5000)
    p.add_argument('--days', type=int, default=65)
    p.add_argument('--samples', type=int, default=15)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if not 1 <= a.codes <= 10000 or not 1 <= a.days <= 250 or not 1 <= a.samples <= 100:
        p.error('fixture sizes outside benchmark bounds')
    source = a.source_root.resolve()
    sys.path.insert(0, str(source / 'tools'))
    from validation_environment import configure_pytest_environment
    with tempfile.TemporaryDirectory(prefix='vr-perf-rdp-') as tmp:
        root = Path(tmp)
        configure_pytest_environment(root, os.environ)
        def deny(*_a, **_kw):
            raise RuntimeError('network prohibited in offline performance benchmark')
        with patch.object(socket, 'create_connection', deny), patch.object(socket, 'getaddrinfo', deny):
            sys.path.insert(0, str(source / 'backend'))
            import research_data_plane as rdp
            # Fast synthetic fixture setup, outside timing. Query still performs
            # its complete production hash/schema/coverage validation on every run.
            fixture = root / 'rdp'
            (fixture / 'artifacts').mkdir(parents=True)
            artifact = fixture / 'fixture.parquet'
            conn = rdp.duckdb.connect(':memory:')
            try:
                conn.execute("CREATE TABLE fixture AS SELECT lpad(CAST(i AS VARCHAR),6,'0') AS code, "
                             "CAST('2026-01-01' AS DATE) + CAST(day AS INTEGER) AS trade_date, "
                             "CAST(10 + i % 99 + day AS DOUBLE) AS open, "
                             "CAST(11 + i % 99 + day AS DOUBLE) AS high, "
                             "CAST(9 + i % 99 + day AS DOUBLE) AS low, "
                             "CAST(10 + i % 99 + day AS DOUBLE) AS close, "
                             "CAST(1000 + day AS DOUBLE) AS volume "
                             "FROM range(?) d(day) CROSS JOIN range(?) c(i) "
                             "WHERE NOT(i % 101 = 0 AND day = ?) AND NOT(i % 103 = 0 AND day < ?)",
                             [a.days,a.codes,a.days-1,a.days-10])
                stats = conn.execute('SELECT COUNT(*), COUNT(DISTINCT code), MIN(trade_date), MAX(trade_date) FROM fixture').fetchone()
                conn.execute('COPY fixture TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(artifact)])
            finally:
                conn.close()
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            final = rdp._artifact_path(fixture, digest)
            artifact.rename(final)
            manifest = dict(schema_version=rdp.SCHEMA_VERSION, dataset_id=rdp.DATASET_ID,
                            provider_id=rdp.PROVIDER_ID, adjustment=rdp.ADJUSTMENT, license_status=rdp.LICENSE_STATUS,
                            source_kind='LOCAL_BULK_DUMP',source_name='synthetic-benchmark',artifact_sha256=digest,
                            artifact_file=final.name,row_count=stats[0],code_count=stats[1],coverage_start=stats[2].isoformat(),
                            coverage_end=stats[3].isoformat(),imported_at='2026-10-24T00:00:00Z',
                            update_semantics='immutable_artifact_per_import')
            rdp._archive_manifest(fixture, manifest)
            rdp._manifest_path(fixture).write_bytes(rdp._canonical_bytes(manifest))
            request = dict(root=fixture, latest=True, limit=1000, sort_by='return_20d', sort_order='desc',
                           filters=[{'metric': 'latest_close', 'operator': 'gt', 'value': 25}])
            def once():
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                result = rdp.query_full_market(**request)
                elapsed = (time.perf_counter_ns() - wall) / 1e6
                cpu_ms = (time.process_time_ns() - cpu) / 1e6
                digest = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                return dict(wall_ms=elapsed, cpu_ms=cpu_ms, sha256=digest,
                            status=result['status'], returned_rows=result['returned_rows'], total_rows=result['total_rows'],
                            coverage=result['coverage'], receipt=result['replay_receipt'])
            cold = once()
            samples = [once() for _ in range(a.samples)]
            def stats(key):
                vals = sorted(x[key] for x in samples)
                return dict(p50=statistics.median(vals), p95=vals[math.ceil(len(vals)*.95)-1], min=vals[0], max=vals[-1])
            result = dict(schema='full-market-performance.v1', environment=dict(python=sys.version, platform=platform.platform(), cpu_count=os.cpu_count(), duckdb=rdp.duckdb.__version__),
                          fixture=dict(codes=a.codes, days=a.days, rows=manifest['row_count'], samples=a.samples, network='DENIED', inputs='SYNTHETIC', data='real immutable Parquet'),
                          first_call=cold, samples=samples, wall_ms=stats('wall_ms'), cpu_ms=stats('cpu_ms'),
                          stable_output=len({x['sha256'] for x in [cold, *samples]}) == 1)
            a.output.parent.mkdir(parents=True, exist_ok=True)
            a.output.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({k: result[k] for k in ('fixture','wall_ms','cpu_ms','stable_output')}, indent=2))


if __name__ == '__main__':
    main()
